from __future__ import annotations

import json
import os
import re
import secrets
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Literal


RunKind = Literal["smoke", "formal", "advice"]

_RUN_STATUS_VERSION = 1
_RUN_KINDS = frozenset({"smoke", "formal", "advice"})
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_MAX_STATUS_BYTES = 1024 * 1024
_STATUS_TEMP_PREFIX = ".run_status."
_STATUS_TEMP_SUFFIX = ".tmp"
_TRASH_NAME = ".run-trash"
_TOMBSTONE_RE = re.compile(r"^tomb-[0-9a-f]{32}$")


@dataclass(frozen=True)
class RunRecord:
    run_id: str
    status: str
    scenario_id: str
    message: str
    run_dir: Path
    output_dir: Path
    report_dir: Path
    report_index: Path
    status_path: Path
    version: int | None = None
    kind: RunKind = "formal"
    change_id: str | None = None
    model_digest: str | None = None


@dataclass(frozen=True)
class _LoadedStatus:
    payload: dict[str, Any]
    directory_identity: os.stat_result
    status_identity: os.stat_result


@dataclass(frozen=True)
class _BoundRunRecord:
    record: RunRecord
    loaded: _LoadedStatus


@dataclass(frozen=True)
class _DirectoryBinding:
    identity: os.stat_result
    resolved_path: Path
    fd: int | None = None


@dataclass(frozen=True)
class _WindowsDeleteHandle:
    fd: int
    handle: int
    identity: os.stat_result
    final_path: Path
    attributes: int


class RunRegistry:
    """Read and write simulation run records.

    ``runs_root`` is the sole write and retention root. ``read_roots`` can add
    legacy registries for history views; duplicate ids always resolve to the
    modern/write root.
    """

    def __init__(
        self,
        runs_root: str | Path,
        read_roots: Iterable[str | Path] | None = None,
    ):
        self.runs_root = Path(runs_root)
        roots = [self.runs_root]
        if read_roots is not None:
            roots.extend(Path(root) for root in read_roots)
        self.read_roots = tuple(_deduplicate_roots(roots))

    def new_run_dir(
        self,
        scenario_id: str,
        *,
        kind: RunKind | None = None,
        change_id: str | None = None,
    ) -> Path:
        from datetime import datetime, timezone

        if kind is not None:
            _require_kind(kind)
        if kind == "smoke":
            _require_component(change_id, "change_id")
            suffix = f"smoke-{change_id}"
        else:
            if change_id is not None:
                _require_component(change_id, "change_id")
            suffix = _safe_scenario_suffix(scenario_id)

        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        return self.runs_root / f"{stamp}-{suffix}"

    def write_status(
        self,
        run_dir: Path,
        *,
        status: str,
        scenario_id: str,
        message: str,
        output_dir: Path,
        report_dir: Path,
        report_index: Path,
        kind: RunKind | None = None,
        change_id: str | None = None,
        model_digest: str | None = None,
    ) -> RunRecord:
        run_dir = Path(run_dir)
        if not isinstance(status, str) or not status:
            raise ValueError("status must be a non-empty string")
        if not isinstance(scenario_id, str):
            raise TypeError("scenario_id must be a string")
        if not isinstance(message, str):
            raise TypeError("message must be a string")

        authoring = kind is not None or change_id is not None or model_digest is not None
        if authoring:
            if kind is None:
                raise ValueError("kind is required for an authoring run status")
            _require_kind(kind)
            if change_id is not None:
                _require_component(change_id, "change_id")
            if kind == "smoke" and change_id is None:
                raise ValueError("change_id is required for a smoke run status")
            _require_digest(model_digest)

        self.runs_root.mkdir(parents=True, exist_ok=True)
        _require_owned_run_dir(self.runs_root, run_dir, require_exists=False)
        run_dir.mkdir(parents=False, exist_ok=True)
        _require_owned_run_dir(self.runs_root, run_dir, require_exists=True)

        output_dir = _require_run_path(Path(output_dir), run_dir, "output_dir")
        report_dir = _require_run_path(Path(report_dir), run_dir, "report_dir")
        report_index = _require_run_path(
            Path(report_index),
            run_dir,
            "report_index",
            boundary=report_dir,
        )

        payload: dict[str, Any] = {
            "run_id": run_dir.name,
            "status": status,
            "scenario_id": scenario_id,
            "message": message,
            "output_dir": str(output_dir),
            "report_dir": str(report_dir),
            "report_index": str(report_index),
        }
        if authoring:
            assert kind is not None
            payload.update(
                {
                    "version": _RUN_STATUS_VERSION,
                    "kind": kind,
                    "change_id": change_id,
                    "model_digest": model_digest,
                }
            )

        status_path = run_dir / "run_status.json"
        _atomic_write_status(self.runs_root, run_dir, payload)
        return self._load_bound_record(self.runs_root, run_dir).record

    def list_runs(self) -> list[RunRecord]:
        records: dict[str, RunRecord] = {}
        for root in self.read_roots:
            for record in self._records_from_root(root):
                records.setdefault(record.run_id, record)
        return sorted(records.values(), key=lambda record: record.run_id)

    def latest(self, *, kind: RunKind | None = None) -> RunRecord | None:
        if kind is not None:
            _require_kind(kind)
        matches = [
            record
            for record in self.list_runs()
            if kind is None or record.kind == kind
        ]
        return matches[-1] if matches else None

    def latest_smoke(self) -> RunRecord | None:
        """Return the newest automatic smoke record across readable roots."""

        return self.latest(kind="smoke")

    def prune_smoke(self, keep: int = 20) -> list[str]:
        """Delete old automatic smoke runs from the modern registry only."""

        if isinstance(keep, bool) or not isinstance(keep, int) or keep < 0:
            raise ValueError("keep must be a non-negative integer")
        self._recover_run_trash()
        smoke = sorted(
            (
                bound
                for bound in self._bound_records_from_root(self.runs_root)
                if bound.record.kind == "smoke"
            ),
            key=lambda bound: bound.record.run_id,
        )
        to_delete = smoke[: max(0, len(smoke) - keep)]
        deleted: list[str] = []
        for bound in to_delete:
            if self._quarantine_and_delete_smoke(bound):
                deleted.append(bound.record.run_id)
        return deleted

    def _records_from_root(self, root: Path) -> list[RunRecord]:
        return [bound.record for bound in self._bound_records_from_root(root)]

    def _bound_records_from_root(self, root: Path) -> list[_BoundRunRecord]:
        try:
            if not root.is_dir():
                return []
            root.resolve(strict=True)
        except (OSError, RuntimeError, ValueError):
            return []

        records: list[_BoundRunRecord] = []
        try:
            candidates = sorted(root.iterdir(), key=lambda path: path.name)
        except OSError:
            return []
        for run_dir in candidates:
            try:
                records.append(self._load_bound_record(root, run_dir))
            except (OSError, RuntimeError, UnicodeError, ValueError, TypeError, json.JSONDecodeError):
                continue
        return records

    def _load_bound_record(self, root: Path, run_dir: Path) -> _BoundRunRecord:
        loaded = _read_status_payload(root, run_dir)
        status_path = run_dir / "run_status.json"
        record = self._record_from_payload(status_path, loaded.payload, root=root)
        current_identity = _snapshot_owned_run_dir(root, run_dir)
        if not os.path.samestat(loaded.directory_identity, current_identity):
            raise ValueError("run directory changed while its status was parsed")
        return _BoundRunRecord(record, loaded)

    def _record_from_payload(
        self,
        status_path: Path,
        payload: dict[str, Any],
        *,
        root: Path | None = None,
    ) -> RunRecord:
        run_dir = status_path.parent
        if root is not None:
            _require_owned_run_dir(root, run_dir, require_exists=True)

        run_id, version, kind, change_id, model_digest = _parse_run_metadata(
            payload,
            expected_run_id=run_dir.name,
        )
        status = _required_text(payload, "status")
        scenario_id = _optional_text(payload, "scenario_id")
        message = _optional_text(payload, "message")

        output_dir = _payload_run_path(payload, "output_dir", run_dir / "output", run_dir)
        report_dir = _payload_run_path(payload, "report_dir", run_dir / "report", run_dir)
        report_index = _payload_run_path(
            payload,
            "report_index",
            report_dir / "index.html",
            run_dir,
            boundary=report_dir,
        )
        return RunRecord(
            run_id=run_id,
            status=status,
            scenario_id=scenario_id,
            message=message,
            run_dir=run_dir,
            output_dir=output_dir,
            report_dir=report_dir,
            report_index=report_index,
            status_path=status_path,
            version=version,
            kind=kind,
            change_id=change_id,
            model_digest=model_digest,
        )

    def _quarantine_and_delete_smoke(self, original: _BoundRunRecord) -> bool:
        record = original.record
        destination: Path | None = None
        moved = False
        try:
            current = self._load_bound_record(self.runs_root, record.run_dir)
            if (
                current.record.run_id != record.run_id
                or current.record.kind != "smoke"
                or not os.path.samestat(
                    original.loaded.directory_identity,
                    current.loaded.directory_identity,
                )
            ):
                return False

            trash = self.runs_root / _TRASH_NAME
            trash_identity = _ensure_private_trash(self.runs_root, trash)
            destination = trash / _new_tombstone_name()
            if _path_exists_or_link(destination):
                return False

            before_rename = _snapshot_owned_run_dir(self.runs_root, record.run_dir)
            if not os.path.samestat(current.loaded.directory_identity, before_rename):
                return False
            os.replace(record.run_dir, destination)
            moved = True

            if not _directory_identity_matches(self.runs_root, trash, trash_identity):
                raise ValueError("run trash changed during quarantine")
            quarantined_identity = _snapshot_owned_run_dir(trash, destination)
            if not os.path.samestat(
                current.loaded.directory_identity,
                quarantined_identity,
            ):
                raise ValueError("quarantined run identity changed before rename")

            quarantined = _read_status_payload(trash, destination)
            metadata = _parse_run_metadata(
                quarantined.payload,
                expected_run_id=record.run_id,
            )
            if metadata[2] != "smoke":
                raise ValueError("quarantined run is not a smoke record")
            if (
                not os.path.samestat(
                    current.loaded.status_identity,
                    quarantined.status_identity,
                )
                or _stat_signature(current.loaded.status_identity)
                != _stat_signature(quarantined.status_identity)
            ):
                raise ValueError("quarantined status changed before deletion")
            final_identity = _snapshot_owned_run_dir(trash, destination)
            if not os.path.samestat(quarantined_identity, final_identity):
                raise ValueError("quarantined run changed before deletion")

            if not _delete_bound_tombstone(
                trash,
                destination,
                quarantined_identity,
            ):
                if _directory_identity_matches(
                    trash,
                    destination,
                    quarantined_identity,
                ):
                    moved = False
                    return False
                raise ValueError("quarantined run changed at the deletion boundary")
            moved = False
            return True
        except (
            OSError,
            RuntimeError,
            UnicodeError,
            ValueError,
            TypeError,
            json.JSONDecodeError,
        ):
            return False
        finally:
            if moved and destination is not None:
                self._recover_run_trash()

    def _recover_run_trash(self) -> None:
        _recover_run_trash(self.runs_root)


def _parse_run_metadata(
    payload: dict[str, Any],
    *,
    expected_run_id: str,
) -> tuple[str, int | None, RunKind, str | None, str | None]:
    run_id = _required_text(payload, "run_id")
    if run_id != expected_run_id or Path(run_id).name != run_id:
        raise ValueError("run_id must match its run directory")
    if "version" not in payload:
        return run_id, None, "formal", None, None

    version_value = payload["version"]
    if type(version_value) is not int or version_value != _RUN_STATUS_VERSION:
        raise ValueError("unsupported run status version")
    kind_value = payload.get("kind")
    _require_kind(kind_value)
    kind: RunKind = kind_value
    change_id = payload.get("change_id")
    if change_id is not None:
        _require_component(change_id, "change_id")
    if kind == "smoke" and change_id is None:
        raise ValueError("change_id is required for a smoke run status")
    digest = payload.get("model_digest")
    _require_digest(digest)
    return run_id, _RUN_STATUS_VERSION, kind, change_id, digest


def _atomic_write_status(root: Path, run_dir: Path, payload: dict[str, Any]) -> None:
    data = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    if len(data) > _MAX_STATUS_BYTES:
        raise ValueError("run status exceeds the maximum supported size")

    binding = _bind_directory(root, run_dir)
    status_path = run_dir / "run_status.json"
    previous_status: os.stat_result | None = None
    temp_path: Path | None = None
    temp_cleanup_path: Path | None = None
    temp_identity: os.stat_result | None = None
    replaced = False
    try:
        previous_status = _optional_regular_leaf(status_path, "run status")
        for _ in range(8):
            candidate = run_dir / (
                f"{_STATUS_TEMP_PREFIX}{secrets.token_hex(16)}{_STATUS_TEMP_SUFFIX}"
            )
            try:
                if binding.fd is None:
                    fd = _open_exclusive_regular(candidate)
                else:
                    fd = _open_exclusive_regular(candidate.name, dir_fd=binding.fd)
            except FileExistsError:
                continue
            temp_path = candidate
            break
        else:
            raise OSError("unable to allocate a private run-status temporary file")

        try:
            temp_identity = os.fstat(fd)
            if not stat.S_ISREG(temp_identity.st_mode):
                raise ValueError("run-status temporary path is not a regular file")
            temp_cleanup_path = _validate_opened_temp_parent(
                root,
                run_dir,
                binding,
                fd,
                candidate,
                temp_identity,
            )
            _write_all(fd, data)
            os.fsync(fd)
            temp_identity = os.fstat(fd)
        finally:
            os.close(fd)

        if not _binding_matches(root, run_dir, binding):
            raise ValueError("run directory changed before status replacement")
        current_status = _optional_regular_leaf(status_path, "run status")
        if not _same_optional_snapshot(previous_status, current_status):
            raise ValueError("run status changed before atomic replacement")
        current_temp = _required_regular_leaf(temp_path, "run-status temporary file")
        if (
            temp_identity is None
            or not os.path.samestat(temp_identity, current_temp)
            or _stat_signature(temp_identity) != _stat_signature(current_temp)
        ):
            raise ValueError("run-status temporary file changed before replacement")

        if binding.fd is None:
            os.replace(temp_path, status_path)
        else:
            os.replace(
                temp_path.name,
                status_path.name,
                src_dir_fd=binding.fd,
                dst_dir_fd=binding.fd,
            )
        replaced = True
        if not _binding_matches(root, run_dir, binding):
            raise ValueError("run directory changed during status replacement")
        installed = _required_regular_leaf(status_path, "run status")
        if not os.path.samestat(temp_identity, installed):
            raise ValueError("installed run status does not match the staged file")
        _fsync_directory(run_dir)
    finally:
        if not replaced and temp_path is not None and temp_identity is not None:
            _remove_bound_temp(
                binding,
                temp_path,
                temp_cleanup_path,
                temp_identity,
            )
        if binding.fd is not None:
            os.close(binding.fd)


def _read_status_payload(root: Path, run_dir: Path) -> _LoadedStatus:
    directory_before = _snapshot_owned_run_dir(root, run_dir)
    status_path = run_dir / "run_status.json"
    leaf_before = _required_regular_leaf(status_path, "run status")
    if leaf_before.st_size > _MAX_STATUS_BYTES:
        raise ValueError("run status exceeds the maximum supported size")

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(status_path, flags)
    try:
        opened_before = os.fstat(fd)
        if (
            not stat.S_ISREG(opened_before.st_mode)
            or not os.path.samestat(leaf_before, opened_before)
            or _stat_signature(leaf_before) != _stat_signature(opened_before)
            or opened_before.st_size > _MAX_STATUS_BYTES
        ):
            raise ValueError("run status changed while it was opened")
        data = _read_bounded(fd, _MAX_STATUS_BYTES)
        opened_after = os.fstat(fd)
        if _stat_signature(opened_before) != _stat_signature(opened_after):
            raise ValueError("run status changed while it was read")
    finally:
        os.close(fd)

    leaf_after = _required_regular_leaf(status_path, "run status")
    if (
        not os.path.samestat(opened_after, leaf_after)
        or _stat_signature(opened_after) != _stat_signature(leaf_after)
    ):
        raise ValueError("run status path changed while it was read")
    directory_after = _snapshot_owned_run_dir(root, run_dir)
    if not os.path.samestat(directory_before, directory_after):
        raise ValueError("run directory changed while its status was read")

    payload = json.loads(data.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("run status payload must be an object")
    return _LoadedStatus(payload, directory_after, opened_after)


def _bind_directory(root: Path, run_dir: Path) -> _DirectoryBinding:
    identity = _snapshot_owned_run_dir(root, run_dir)
    resolved = run_dir.resolve(strict=True)
    if os.name == "nt":
        return _DirectoryBinding(identity, resolved)

    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    fd = os.open(run_dir, flags)
    try:
        opened = os.fstat(fd)
        if (
            not stat.S_ISDIR(opened.st_mode)
            or not os.path.samestat(identity, opened)
            or not _directory_identity_matches(root, run_dir, identity)
        ):
            raise ValueError("run directory changed while it was bound")
    except BaseException:
        os.close(fd)
        raise
    return _DirectoryBinding(opened, resolved, fd)


def _binding_matches(root: Path, run_dir: Path, binding: _DirectoryBinding) -> bool:
    if not _directory_identity_matches(root, run_dir, binding.identity):
        return False
    if binding.fd is None:
        return True
    try:
        opened = os.fstat(binding.fd)
    except OSError:
        return False
    return stat.S_ISDIR(opened.st_mode) and os.path.samestat(binding.identity, opened)


def _validate_opened_temp_parent(
    root: Path,
    run_dir: Path,
    binding: _DirectoryBinding,
    fd: int,
    candidate: Path,
    temp_identity: os.stat_result,
) -> Path:
    if binding.fd is not None:
        if not _binding_matches(root, run_dir, binding):
            raise ValueError("run directory changed before temporary-file write")
        return candidate

    final_path = _final_path_from_fd(fd)
    if final_path is None:
        raise ValueError("temporary-file parent identity could not be verified")
    try:
        final_parent = final_path.parent.resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as error:
        raise ValueError(
            f"temporary-file parent could not be resolved: {type(error).__name__}"
        ) from None
    if os.path.normcase(str(final_parent)) != os.path.normcase(str(binding.resolved_path)):
        raise ValueError("temporary file was created outside the bound run directory")
    if not _binding_matches(root, run_dir, binding):
        raise ValueError("run directory changed before temporary-file write")
    current = _required_regular_leaf(final_path, "run-status temporary file")
    if not os.path.samestat(temp_identity, current):
        raise ValueError("temporary-file handle no longer matches its final path")
    return final_path


def _final_path_from_fd(fd: int) -> Path | None:
    if os.name != "nt":
        try:
            return Path(os.readlink(f"/proc/self/fd/{fd}"))
        except OSError:
            return None

    import ctypes
    from ctypes import wintypes
    import msvcrt

    handle = msvcrt.get_osfhandle(fd)
    buffer = ctypes.create_unicode_buffer(32768)
    get_final_path = ctypes.windll.kernel32.GetFinalPathNameByHandleW
    get_final_path.argtypes = [
        wintypes.HANDLE,
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
    ]
    get_final_path.restype = wintypes.DWORD
    length = get_final_path(handle, buffer, len(buffer), 0)
    if length == 0 or length >= len(buffer):
        return None
    value = buffer.value
    if value.startswith("\\\\?\\UNC\\"):
        value = "\\\\" + value[8:]
    elif value.startswith("\\\\?\\"):
        value = value[4:]
    return Path(value)


def _open_exclusive_regular(
    path: str | Path,
    *,
    dir_fd: int | None = None,
) -> int:
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    return os.open(path, flags, 0o600, dir_fd=dir_fd)


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError("short write while staging run status")
        view = view[written:]


def _read_bounded(fd: int, limit: int) -> bytes:
    result = bytearray()
    while len(result) <= limit:
        remaining = limit + 1 - len(result)
        chunk = os.read(fd, min(64 * 1024, remaining))
        if not chunk:
            break
        result.extend(chunk)
    if len(result) > limit:
        raise ValueError("run status exceeds the maximum supported size")
    return bytes(result)


def _optional_regular_leaf(path: Path, role: str) -> os.stat_result | None:
    try:
        return _required_regular_leaf(path, role)
    except FileNotFoundError:
        return None


def _required_regular_leaf(path: Path, role: str) -> os.stat_result:
    info = path.lstat()
    if _is_stat_link_like(info):
        raise ValueError(f"{role} must not be a link or reparse point")
    if not stat.S_ISREG(info.st_mode):
        raise ValueError(f"{role} must be a regular file")
    return info


def _same_optional_snapshot(
    first: os.stat_result | None,
    second: os.stat_result | None,
) -> bool:
    if first is None or second is None:
        return first is second
    return os.path.samestat(first, second) and _stat_signature(first) == _stat_signature(second)


def _stat_signature(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_size,
        info.st_mtime_ns,
    )


def _remove_bound_temp(
    binding: _DirectoryBinding,
    temp_path: Path,
    final_path: Path | None,
    temp_identity: os.stat_result,
) -> None:
    try:
        if binding.fd is not None:
            current = os.stat(
                temp_path.name,
                dir_fd=binding.fd,
                follow_symlinks=False,
            )
            if _is_stat_link_like(current) or not os.path.samestat(temp_identity, current):
                return
            os.unlink(temp_path.name, dir_fd=binding.fd)
            return
        cleanup_path = final_path or temp_path
        current = _required_regular_leaf(cleanup_path, "run-status temporary file")
        if os.path.samestat(temp_identity, current):
            cleanup_path.unlink()
    except (OSError, RuntimeError, ValueError):
        return


def _ensure_private_trash(root: Path, trash: Path) -> os.stat_result:
    if not _path_exists_or_link(trash):
        trash.mkdir(mode=0o700)
    return _snapshot_owned_run_dir(root, trash)


def _delete_bound_tombstone(
    trash: Path,
    tombstone: Path,
    expected_identity: os.stat_result,
) -> bool:
    if tombstone.parent != trash or _TOMBSTONE_RE.fullmatch(tombstone.name) is None:
        return False
    if os.name == "nt":
        return _windows_delete_bound_tombstone(tombstone, expected_identity)
    return _posix_delete_bound_tombstone(trash, tombstone, expected_identity)


def _windows_delete_bound_tombstone(
    tombstone: Path,
    expected_identity: os.stat_result,
) -> bool:
    entry: _WindowsDeleteHandle | None = None
    try:
        entry = _windows_open_delete_handle(tombstone)
        if (
            not os.path.samestat(expected_identity, entry.identity)
            or not stat.S_ISDIR(entry.identity.st_mode)
            or _windows_is_reparse(entry.attributes)
            or not _same_absolute_path(entry.final_path, tombstone)
        ):
            return False
        if not _windows_delete_children(tombstone):
            return False
        current = os.fstat(entry.fd)
        if not os.path.samestat(expected_identity, current):
            return False
        if not _windows_mark_handle_for_deletion(entry.handle):
            return False
        return True
    except (OSError, RuntimeError, ValueError):
        return False
    finally:
        if entry is not None:
            os.close(entry.fd)


def _windows_delete_children(directory: Path) -> bool:
    try:
        children = [Path(item.path) for item in os.scandir(directory)]
    except OSError:
        return False
    for child in children:
        if not _windows_delete_entry(child):
            return False
    return True


def _windows_delete_entry(path: Path) -> bool:
    entry: _WindowsDeleteHandle | None = None
    try:
        entry = _windows_open_delete_handle(path)
        if not _same_absolute_path(entry.final_path, path):
            return False
        is_directory = stat.S_ISDIR(entry.identity.st_mode)
        if is_directory and not _windows_is_reparse(entry.attributes):
            if not _windows_delete_children(path):
                return False
        current = os.fstat(entry.fd)
        if not os.path.samestat(entry.identity, current):
            return False
        return _windows_mark_handle_for_deletion(entry.handle)
    except (OSError, RuntimeError, ValueError):
        return False
    finally:
        if entry is not None:
            os.close(entry.fd)


def _windows_open_delete_handle(path: Path) -> _WindowsDeleteHandle:
    import ctypes
    from ctypes import wintypes
    import msvcrt

    delete_access = 0x00010000
    file_read_attributes = 0x00000080
    share_read_write = 0x00000001 | 0x00000002
    open_existing = 3
    backup_semantics = 0x02000000
    open_reparse_point = 0x00200000
    create_file = ctypes.windll.kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    handle = create_file(
        str(path),
        delete_access | file_read_attributes,
        share_read_write,
        None,
        open_existing,
        backup_semantics | open_reparse_point,
        None,
    )
    invalid_handle = ctypes.c_void_p(-1).value
    if ctypes.c_void_p(handle).value == invalid_handle:
        raise ctypes.WinError()
    try:
        fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | getattr(os, "O_BINARY", 0))
    except BaseException:
        ctypes.windll.kernel32.CloseHandle(handle)
        raise
    try:
        identity = os.fstat(fd)
        final_path = _final_path_from_fd(fd)
        if final_path is None:
            raise ValueError("delete handle final path could not be resolved")
        attributes = getattr(identity, "st_file_attributes", 0)
        return _WindowsDeleteHandle(fd, msvcrt.get_osfhandle(fd), identity, final_path, attributes)
    except BaseException:
        os.close(fd)
        raise


def _windows_mark_handle_for_deletion(handle: int) -> bool:
    import ctypes
    from ctypes import wintypes

    class FileDispositionInfo(ctypes.Structure):
        _fields_ = [("DeleteFile", wintypes.BOOLEAN)]

    disposition = FileDispositionInfo(True)
    set_information = ctypes.windll.kernel32.SetFileInformationByHandle
    set_information.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    set_information.restype = wintypes.BOOL
    return bool(
        set_information(
            handle,
            4,
            ctypes.byref(disposition),
            ctypes.sizeof(disposition),
        )
    )


def _windows_is_reparse(attributes: int) -> bool:
    return bool(attributes & 0x00000400)


def _same_absolute_path(first: Path, second: Path) -> bool:
    return os.path.normcase(os.path.abspath(first)) == os.path.normcase(os.path.abspath(second))


def _posix_delete_bound_tombstone(
    trash: Path,
    tombstone: Path,
    expected_identity: os.stat_result,
) -> bool:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    parent_fd: int | None = None
    entry_fd: int | None = None
    try:
        parent_fd = os.open(trash, flags)
        entry_fd = os.open(tombstone.name, flags, dir_fd=parent_fd)
        opened = os.fstat(entry_fd)
        if not os.path.samestat(expected_identity, opened):
            return False
        if not _posix_delete_children(entry_fd):
            return False
        current = os.stat(tombstone.name, dir_fd=parent_fd, follow_symlinks=False)
        if _is_stat_link_like(current) or not os.path.samestat(opened, current):
            return False
        os.rmdir(tombstone.name, dir_fd=parent_fd)
        return True
    except (OSError, RuntimeError, ValueError):
        return False
    finally:
        if entry_fd is not None:
            os.close(entry_fd)
        if parent_fd is not None:
            os.close(parent_fd)


def _posix_delete_children(directory_fd: int) -> bool:
    try:
        names = sorted(os.listdir(directory_fd))
    except OSError:
        return False
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    for name in names:
        child_fd: int | None = None
        try:
            before = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            if stat.S_ISDIR(before.st_mode) and not _is_stat_link_like(before):
                child_fd = os.open(name, flags, dir_fd=directory_fd)
                opened = os.fstat(child_fd)
                if not os.path.samestat(before, opened):
                    return False
                if not _posix_delete_children(child_fd):
                    return False
                current = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                if not os.path.samestat(opened, current):
                    return False
                os.rmdir(name, dir_fd=directory_fd)
            else:
                os.unlink(name, dir_fd=directory_fd)
        except (OSError, RuntimeError, ValueError):
            return False
        finally:
            if child_fd is not None:
                os.close(child_fd)
    return True


def _new_tombstone_name() -> str:
    return f"tomb-{secrets.token_hex(16)}"


def _recover_run_trash(root: Path) -> None:
    trash = root / _TRASH_NAME
    try:
        if not _path_exists_or_link(trash):
            return
        trash_identity = _snapshot_owned_run_dir(root, trash)
        candidates = _strict_tombstones(trash)
    except (OSError, RuntimeError, ValueError):
        return

    max_rounds = max(1, len(candidates) * 2 + 2)
    for _ in range(max_rounds):
        progress = False
        for tombstone in _strict_tombstones(trash):
            if _recover_one_tombstone(root, trash, trash_identity, tombstone):
                progress = True
        if not progress:
            break


def _strict_tombstones(trash: Path) -> list[Path]:
    try:
        children = sorted(trash.iterdir(), key=lambda path: path.name)
    except OSError:
        return []
    return [child for child in children if _TOMBSTONE_RE.fullmatch(child.name)]


def _recover_one_tombstone(
    root: Path,
    trash: Path,
    trash_identity: os.stat_result,
    tombstone: Path,
) -> bool:
    displaced: Path | None = None
    try:
        if not _directory_identity_matches(root, trash, trash_identity):
            return False
        loaded = _read_status_payload(trash, tombstone)
        run_id, _version, _kind, _change_id, _digest = _parse_run_metadata(
            loaded.payload,
            expected_run_id=_stored_run_id(loaded.payload),
        )
        desired = root / run_id
        if not _path_exists_or_link(desired):
            return _move_tombstone_to_run(
                root,
                trash,
                trash_identity,
                tombstone,
                loaded.directory_identity,
                desired,
            )

        occupied = _read_status_payload(root, desired)
        occupied_run_id = _stored_run_id(occupied.payload)
        _parse_run_metadata(occupied.payload, expected_run_id=occupied_run_id)
        if occupied_run_id == desired.name:
            return False

        occupied_target = root / occupied_run_id
        if _path_exists_or_link(occupied_target):
            return False
        displaced = trash / _new_tombstone_name()
        if _path_exists_or_link(displaced):
            return False
        if not _directory_identity_matches(root, trash, trash_identity):
            return False
        current_occupied = _snapshot_owned_run_dir(root, desired)
        if not os.path.samestat(occupied.directory_identity, current_occupied):
            return False
        os.replace(desired, displaced)
        displaced_identity = _snapshot_owned_run_dir(trash, displaced)
        if not os.path.samestat(occupied.directory_identity, displaced_identity):
            return False

        restored = _move_tombstone_to_run(
            root,
            trash,
            trash_identity,
            tombstone,
            loaded.directory_identity,
            desired,
        )
        if not restored:
            return False
        _recover_one_tombstone(root, trash, trash_identity, displaced)
        return True
    except (
        OSError,
        RuntimeError,
        UnicodeError,
        ValueError,
        TypeError,
        json.JSONDecodeError,
    ):
        return False


def _move_tombstone_to_run(
    root: Path,
    trash: Path,
    trash_identity: os.stat_result,
    tombstone: Path,
    tombstone_identity: os.stat_result,
    destination: Path,
) -> bool:
    if _path_exists_or_link(destination):
        return False
    if not _directory_identity_matches(root, trash, trash_identity):
        return False
    current = _snapshot_owned_run_dir(trash, tombstone)
    if not os.path.samestat(tombstone_identity, current):
        return False
    os.replace(tombstone, destination)
    restored = _snapshot_owned_run_dir(root, destination)
    return os.path.samestat(tombstone_identity, restored)


def _stored_run_id(payload: dict[str, Any]) -> str:
    run_id = _required_text(payload, "run_id")
    if Path(run_id).name != run_id or run_id in {".", ".."}:
        raise ValueError("stored run_id is not a safe path component")
    return run_id


def _path_exists_or_link(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        fd = os.open(path, flags)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _deduplicate_roots(roots: Iterable[Path]) -> list[Path]:
    result: list[Path] = []
    lexical: set[str] = set()
    for root in roots:
        key = os.path.normcase(str(root.absolute()))
        if key in lexical:
            continue
        duplicate = False
        for existing in result:
            try:
                if root.exists() and existing.exists() and os.path.samefile(root, existing):
                    duplicate = True
                    break
            except OSError:
                pass
        if duplicate:
            continue
        lexical.add(key)
        result.append(root)
    return result


def _safe_scenario_suffix(scenario_id: str) -> str:
    if not isinstance(scenario_id, str):
        raise TypeError("scenario_id must be a string")
    suffix = "".join(
        char if char.isalnum() or char in "-_" else "_" for char in scenario_id
    )
    return suffix or "scenario"


def _require_kind(value: object) -> None:
    if not isinstance(value, str) or value not in _RUN_KINDS:
        raise ValueError("kind must be smoke, formal, or advice")


def _require_component(value: object, name: str) -> None:
    if not isinstance(value, str) or _SAFE_COMPONENT.fullmatch(value) is None:
        raise ValueError(f"{name} must be one safe ASCII path component")


def _require_digest(value: object) -> None:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise ValueError("model_digest must match sha256:<64 lowercase hex>")


def _required_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _optional_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    return value


def _payload_run_path(
    payload: dict[str, Any],
    key: str,
    default: Path,
    run_dir: Path,
    *,
    boundary: Path | None = None,
) -> Path:
    value = payload.get(key)
    if value is None or value == "":
        path = default
    elif isinstance(value, str):
        path = Path(value)
    else:
        raise ValueError(f"{key} must be a path string")
    return _require_run_path(path, run_dir, key, boundary=boundary)


def _require_run_path(
    path: Path,
    run_dir: Path,
    name: str,
    *,
    boundary: Path | None = None,
) -> Path:
    try:
        resolved_run = run_dir.resolve(strict=True)
        resolved_boundary = (boundary or run_dir).resolve(strict=False)
        resolved_path = path.resolve(strict=False)
    except (OSError, RuntimeError, ValueError) as error:
        raise ValueError(f"{name} could not be resolved: {type(error).__name__}") from None
    if not resolved_boundary.is_relative_to(resolved_run):
        raise ValueError(f"{name} boundary is outside the run directory")
    if not resolved_path.is_relative_to(resolved_boundary):
        raise ValueError(f"{name} must stay inside the run directory")
    return path


def _require_owned_run_dir(root: Path, run_dir: Path, *, require_exists: bool) -> None:
    if not require_exists:
        try:
            resolved_root = root.resolve(strict=True)
            if _path_exists_or_link(run_dir) and _is_link_like(run_dir):
                raise ValueError("run directory must not be a link or reparse point")
            resolved_run = run_dir.resolve(strict=False)
            if resolved_run.parent != resolved_root:
                raise ValueError("run directory must be a direct child of the registry")
        except OSError as error:
            raise ValueError(
                f"run directory could not be inspected: {type(error).__name__}"
            ) from None
        return
    _snapshot_owned_run_dir(root, run_dir)


def _snapshot_owned_run_dir(root: Path, run_dir: Path) -> os.stat_result:
    try:
        resolved_root = root.resolve(strict=True)
        info = run_dir.lstat()
        if _is_stat_link_like(info):
            raise ValueError("run directory must not be a link or reparse point")
        if not stat.S_ISDIR(info.st_mode):
            raise ValueError("run directory must be a directory")
        resolved_run = run_dir.resolve(strict=True)
        if resolved_run.parent != resolved_root:
            raise ValueError("run directory must be a direct child of the registry")
        after = run_dir.lstat()
        if _is_stat_link_like(after) or not os.path.samestat(info, after):
            raise ValueError("run directory changed while it was inspected")
        return after
    except FileNotFoundError:
        raise ValueError("run directory is missing") from None
    except OSError as error:
        raise ValueError(f"run directory could not be inspected: {type(error).__name__}") from None


def _directory_identity_matches(
    root: Path,
    run_dir: Path,
    expected: os.stat_result,
) -> bool:
    try:
        current = _snapshot_owned_run_dir(root, run_dir)
    except (OSError, RuntimeError, ValueError):
        return False
    return os.path.samestat(expected, current)


def _is_link_like(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return _is_stat_link_like(info)


def _is_stat_link_like(info: os.stat_result) -> bool:
    attributes = getattr(info, "st_file_attributes", 0)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(info.st_mode) or bool(attributes & reparse)
