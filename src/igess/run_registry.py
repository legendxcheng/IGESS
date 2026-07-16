from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Literal


RunKind = Literal["smoke", "formal", "advice"]
TombstoneEntryType = Literal["directory", "file", "link", "other"]

_RUN_STATUS_VERSION = 1
_RUN_KINDS = frozenset({"smoke", "formal", "advice"})
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_MAX_STATUS_BYTES = 1024 * 1024
_STATUS_TEMP_PREFIX = ".run_status."
_STATUS_TEMP_SUFFIX = ".tmp"
_TRASH_NAME = ".run-trash"
_TOMBSTONE_RE = re.compile(r"^tomb-[0-9a-f]{32}$")
_TOMBSTONE_MANIFEST_RE = re.compile(r"^(tomb-[0-9a-f]{32})\.json$")
_PRIVATE_CHILD_PREFIX = ".delete-quarantine-"
_TOMBSTONE_MANIFEST_VERSION = 2
_MAX_MANIFEST_BYTES = 2 * 1024 * 1024


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
    fd: int | None = None


@dataclass(frozen=True)
class _WindowsDeleteHandle:
    fd: int
    handle: int
    identity: os.stat_result
    attributes: int


@dataclass(frozen=True)
class _TombstoneManifest:
    tombstone: str
    run_id: str
    kind: RunKind
    directory_dev: int
    directory_ino: int
    status_payload: dict[str, Any]
    entries: tuple[_TombstoneEntry, ...]
    file_identity: os.stat_result


@dataclass(frozen=True)
class _TombstoneEntry:
    path: str
    entry_type: TombstoneEntryType
    dev: int
    ino: int
    mode: int
    size: int
    mtime_ns: int


@dataclass(frozen=True)
class _TombstoneDeletionPlan:
    root: Path
    trash: Path
    trash_identity: os.stat_result
    entries: dict[str, _TombstoneEntry]


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
        recovered_deletions = self._recover_run_trash()
        smoke = sorted(
            (
                bound
                for bound in self._bound_records_from_root(self.runs_root)
                if bound.record.kind == "smoke"
            ),
            key=lambda bound: bound.record.run_id,
        )
        to_delete = smoke[: max(0, len(smoke) - keep)]
        deleted: list[str] = list(recovered_deletions)
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
        manifest_path: Path | None = None
        manifest_identity: os.stat_result | None = None
        manifest_entries: tuple[_TombstoneEntry, ...] | None = None
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

            manifest_entries = _snapshot_tombstone_entries(
                record.run_dir,
                current.loaded.directory_identity,
            )
            status_entry = {
                entry.path: entry for entry in manifest_entries
            }.get("run_status.json")
            if (
                status_entry is None
                or not _entry_matches_identity(
                    status_entry,
                    current.loaded.status_identity,
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

            manifest_path, manifest_identity = _write_tombstone_manifest(
                self.runs_root,
                trash,
                trash_identity,
                destination,
                quarantined,
                manifest_entries,
            )

            if not _tombstone_tree_matches_exact(
                destination,
                quarantined_identity,
                manifest_entries,
            ):
                moved = False
                return False

            if not _delete_bound_tombstone(
                trash,
                destination,
                quarantined_identity,
                expected_entries=manifest_entries,
                expected_trash_identity=trash_identity,
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
            _delete_bound_manifest(
                self.runs_root,
                trash,
                trash_identity,
                manifest_path,
                manifest_identity,
            )
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

    def _recover_run_trash(self) -> list[str]:
        return _recover_run_trash(self.runs_root)


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


def _canonical_status_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _strict_relative_posix_path(parts: tuple[str, ...]) -> str:
    if not parts or any(
        not part or part in {".", ".."} or "/" in part or "\\" in part or "\x00" in part
        for part in parts
    ):
        raise ValueError("tombstone entry path is not a strict relative POSIX path")
    value = PurePosixPath(*parts).as_posix()
    if value.startswith("/") or value in {".", ".."}:
        raise ValueError("tombstone entry path is not a strict relative POSIX path")
    return value


def _tombstone_entry_type(
    identity: os.stat_result,
    *,
    windows_attributes: int | None = None,
) -> TombstoneEntryType:
    attributes = (
        getattr(identity, "st_file_attributes", 0)
        if windows_attributes is None
        else windows_attributes
    )
    if _is_stat_link_like(identity) or _windows_is_reparse(attributes):
        return "link"
    if stat.S_ISDIR(identity.st_mode):
        return "directory"
    if stat.S_ISREG(identity.st_mode):
        return "file"
    return "other"


def _tombstone_entry(
    parts: tuple[str, ...],
    identity: os.stat_result,
    *,
    windows_attributes: int | None = None,
) -> _TombstoneEntry:
    return _TombstoneEntry(
        path=_strict_relative_posix_path(parts),
        entry_type=_tombstone_entry_type(
            identity,
            windows_attributes=windows_attributes,
        ),
        dev=identity.st_dev,
        ino=identity.st_ino,
        mode=identity.st_mode,
        size=identity.st_size,
        mtime_ns=identity.st_mtime_ns,
    )


def _entry_matches_identity(
    entry: _TombstoneEntry,
    identity: os.stat_result,
    *,
    windows_attributes: int | None = None,
) -> bool:
    if (
        entry.entry_type
        != _tombstone_entry_type(identity, windows_attributes=windows_attributes)
        or entry.dev != identity.st_dev
        or entry.ino != identity.st_ino
    ):
        return False
    if entry.entry_type in {"directory", "link"}:
        return True
    return (
        entry.mode == identity.st_mode
        and entry.size == identity.st_size
        and entry.mtime_ns == identity.st_mtime_ns
    )


def _snapshot_tombstone_entries(
    tombstone: Path,
    expected_identity: os.stat_result,
) -> tuple[_TombstoneEntry, ...]:
    return _record_bound_tombstone_entries(tombstone, expected_identity)


def _record_bound_tombstone_entries(
    tombstone: Path,
    expected_identity: os.stat_result,
) -> tuple[_TombstoneEntry, ...]:
    if os.name == "nt":
        root_handle: _WindowsDeleteHandle | None = None
        try:
            root_handle = _windows_open_delete_handle(tombstone)
            if (
                not os.path.samestat(expected_identity, root_handle.identity)
                or not stat.S_ISDIR(root_handle.identity.st_mode)
                or _windows_is_reparse(root_handle.attributes)
            ):
                raise ValueError("tombstone changed before its tree was recorded")
            entries = _windows_snapshot_entries(tombstone, ())
            current = os.fstat(root_handle.fd)
            if not os.path.samestat(expected_identity, current):
                raise ValueError("tombstone changed while its tree was recorded")
        finally:
            if root_handle is not None:
                os.close(root_handle.fd)
    else:
        flags = (
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        root_fd = os.open(tombstone, flags)
        try:
            opened = os.fstat(root_fd)
            if not os.path.samestat(expected_identity, opened):
                raise ValueError("tombstone changed before its tree was recorded")
            entries = _posix_snapshot_entries(root_fd, ())
            current = os.fstat(root_fd)
            if not os.path.samestat(expected_identity, current):
                raise ValueError("tombstone changed while its tree was recorded")
        finally:
            os.close(root_fd)
    return tuple(sorted(entries, key=lambda entry: entry.path))


def _tombstone_tree_matches_exact(
    tombstone: Path,
    expected_identity: os.stat_result,
    expected_entries: tuple[_TombstoneEntry, ...],
) -> bool:
    try:
        current_entries = _record_bound_tombstone_entries(
            tombstone,
            expected_identity,
        )
    except (OSError, RuntimeError, ValueError):
        return False
    return current_entries == expected_entries


def _windows_snapshot_entries(
    directory: Path,
    prefix: tuple[str, ...],
) -> list[_TombstoneEntry]:
    children = sorted(
        (
            (Path(item.path), Path(item.path).lstat())
            for item in os.scandir(directory)
        ),
        key=lambda item: item[0].name,
    )
    result: list[_TombstoneEntry] = []
    for child, enumerated_identity in children:
        handle: _WindowsDeleteHandle | None = None
        try:
            handle = _windows_open_delete_handle(child)
            if not os.path.samestat(enumerated_identity, handle.identity):
                raise ValueError("tombstone entry changed while its tree was recorded")
            parts = (*prefix, child.name)
            entry = _tombstone_entry(
                parts,
                handle.identity,
                windows_attributes=handle.attributes,
            )
            result.append(entry)
            if entry.entry_type == "directory":
                result.extend(_windows_snapshot_entries(child, parts))
            current = os.fstat(handle.fd)
            if not os.path.samestat(handle.identity, current):
                raise ValueError("tombstone entry changed while its tree was recorded")
        finally:
            if handle is not None:
                os.close(handle.fd)
    return result


def _posix_snapshot_entries(
    directory_fd: int,
    prefix: tuple[str, ...],
) -> list[_TombstoneEntry]:
    names = sorted(os.listdir(directory_fd))
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    result: list[_TombstoneEntry] = []
    for name in names:
        before = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        parts = (*prefix, name)
        entry = _tombstone_entry(parts, before)
        result.append(entry)
        if entry.entry_type != "directory":
            continue
        child_fd = os.open(name, flags, dir_fd=directory_fd)
        try:
            opened = os.fstat(child_fd)
            if not os.path.samestat(before, opened):
                raise ValueError("tombstone entry changed while its tree was recorded")
            result.extend(_posix_snapshot_entries(child_fd, parts))
            current = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            if not os.path.samestat(opened, current):
                raise ValueError("tombstone entry changed while its tree was recorded")
        finally:
            os.close(child_fd)
    return result


def _entry_documents(entries: tuple[_TombstoneEntry, ...]) -> list[dict[str, Any]]:
    return [
        {
            "path": entry.path,
            "type": entry.entry_type,
            "dev": entry.dev,
            "ino": entry.ino,
            "mode": entry.mode,
            "size": entry.size,
            "mtime_ns": entry.mtime_ns,
        }
        for entry in entries
    ]


def _write_tombstone_manifest(
    root: Path,
    trash: Path,
    trash_identity: os.stat_result,
    tombstone: Path,
    loaded: _LoadedStatus,
    entries: tuple[_TombstoneEntry, ...],
) -> tuple[Path, os.stat_result]:
    if tombstone.parent != trash or _TOMBSTONE_RE.fullmatch(tombstone.name) is None:
        raise ValueError("tombstone manifest target is invalid")
    current_tombstone = _snapshot_owned_run_dir(trash, tombstone)
    if not os.path.samestat(loaded.directory_identity, current_tombstone):
        raise ValueError("tombstone changed before its manifest was written")
    run_id = _stored_run_id(loaded.payload)
    metadata = _parse_run_metadata(loaded.payload, expected_run_id=run_id)
    if metadata[2] != "smoke":
        raise ValueError("only smoke tombstones can have deletion manifests")
    _validate_manifest_status_payload(loaded.payload, run_id)
    entries_by_path = {entry.path: entry for entry in entries}
    if len(entries_by_path) != len(entries):
        raise ValueError("tombstone manifest entries are duplicated")
    status_entry = entries_by_path.get("run_status.json")
    if (
        status_entry is None
        or not _entry_matches_identity(status_entry, loaded.status_identity)
    ):
        raise ValueError("recorded tombstone tree does not match its validated status")

    status_digest = "sha256:" + hashlib.sha256(
        _canonical_status_bytes(loaded.payload)
    ).hexdigest()
    entry_documents = _entry_documents(entries)
    entries_digest = "sha256:" + hashlib.sha256(
        json.dumps(
            entry_documents,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    document = {
        "version": _TOMBSTONE_MANIFEST_VERSION,
        "tombstone": tombstone.name,
        "run_id": run_id,
        "kind": metadata[2],
        "directory_identity": {
            "dev": current_tombstone.st_dev,
            "ino": current_tombstone.st_ino,
        },
        "status_sha256": status_digest,
        "status": loaded.payload,
        "entries_sha256": entries_digest,
        "entries": entry_documents,
    }
    data = (
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    if len(data) > _MAX_MANIFEST_BYTES:
        raise ValueError("tombstone manifest exceeds the maximum supported size")

    manifest_path = trash / f"{tombstone.name}.json"
    binding = _bind_directory(root, trash)
    temp_path: Path | None = None
    temp_cleanup_path: Path | None = None
    temp_identity: os.stat_result | None = None
    installed = False
    try:
        if not os.path.samestat(trash_identity, binding.identity):
            raise ValueError("run trash changed before manifest creation")
        if _path_exists_or_link(manifest_path):
            raise ValueError("tombstone manifest path is already occupied")
        for _ in range(8):
            candidate = trash / (
                f".{tombstone.name}.manifest-{secrets.token_hex(16)}.tmp"
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
            raise OSError("unable to allocate a private tombstone-manifest file")

        try:
            temp_identity = os.fstat(fd)
            if not stat.S_ISREG(temp_identity.st_mode):
                raise ValueError("tombstone-manifest temporary path is not a regular file")
            temp_cleanup_path = _validate_opened_temp_parent(
                root,
                trash,
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

        if not _binding_matches(root, trash, binding):
            raise ValueError("run trash changed before manifest replacement")
        if _path_exists_or_link(manifest_path):
            raise ValueError("tombstone manifest path changed before replacement")
        current_temp = _required_regular_leaf(
            temp_path,
            "tombstone-manifest temporary file",
        )
        if (
            temp_identity is None
            or not os.path.samestat(temp_identity, current_temp)
            or _stat_signature(temp_identity) != _stat_signature(current_temp)
        ):
            raise ValueError("tombstone-manifest temporary file changed")

        if binding.fd is None:
            os.replace(temp_path, manifest_path)
        else:
            os.replace(
                temp_path.name,
                manifest_path.name,
                src_dir_fd=binding.fd,
                dst_dir_fd=binding.fd,
            )
        installed = True
        if not _binding_matches(root, trash, binding):
            raise ValueError("run trash changed during manifest replacement")
        manifest_identity = _required_regular_leaf(
            manifest_path,
            "tombstone manifest",
        )
        if not os.path.samestat(temp_identity, manifest_identity):
            raise ValueError("installed tombstone manifest does not match its staged file")
        _fsync_directory(trash)
        return manifest_path, manifest_identity
    finally:
        if not installed and temp_path is not None and temp_identity is not None:
            _remove_bound_temp(
                binding,
                temp_path,
                temp_cleanup_path,
                temp_identity,
            )
        if binding.fd is not None:
            os.close(binding.fd)


def _read_tombstone_manifest(
    root: Path,
    trash: Path,
    manifest_path: Path,
) -> _TombstoneManifest:
    match = _TOMBSTONE_MANIFEST_RE.fullmatch(manifest_path.name)
    if manifest_path.parent != trash or match is None:
        raise ValueError("tombstone manifest name is invalid")
    directory_before = _snapshot_owned_run_dir(root, trash)
    leaf_before = _required_regular_leaf(manifest_path, "tombstone manifest")
    if leaf_before.st_size > _MAX_MANIFEST_BYTES:
        raise ValueError("tombstone manifest exceeds the maximum supported size")

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(manifest_path, flags)
    try:
        opened_before = os.fstat(fd)
        if (
            not stat.S_ISREG(opened_before.st_mode)
            or not os.path.samestat(leaf_before, opened_before)
            or _stat_signature(leaf_before) != _stat_signature(opened_before)
            or opened_before.st_size > _MAX_MANIFEST_BYTES
        ):
            raise ValueError("tombstone manifest changed while it was opened")
        data = _read_bounded(fd, _MAX_MANIFEST_BYTES)
        opened_after = os.fstat(fd)
        if _stat_signature(opened_before) != _stat_signature(opened_after):
            raise ValueError("tombstone manifest changed while it was read")
    finally:
        os.close(fd)

    leaf_after = _required_regular_leaf(manifest_path, "tombstone manifest")
    if (
        not os.path.samestat(opened_after, leaf_after)
        or _stat_signature(opened_after) != _stat_signature(leaf_after)
    ):
        raise ValueError("tombstone manifest path changed while it was read")
    directory_after = _snapshot_owned_run_dir(root, trash)
    if not os.path.samestat(directory_before, directory_after):
        raise ValueError("run trash changed while its manifest was read")

    document = json.loads(data.decode("utf-8"))
    if not isinstance(document, dict) or set(document) != {
        "version",
        "tombstone",
        "run_id",
        "kind",
        "directory_identity",
        "status_sha256",
        "status",
        "entries_sha256",
        "entries",
    }:
        raise ValueError("tombstone manifest schema is invalid")
    if type(document["version"]) is not int or document["version"] != _TOMBSTONE_MANIFEST_VERSION:
        raise ValueError("unsupported tombstone manifest version")
    tombstone = document["tombstone"]
    if not isinstance(tombstone, str) or tombstone != match.group(1):
        raise ValueError("tombstone manifest does not match its filename")
    run_id = document["run_id"]
    if not isinstance(run_id, str):
        raise ValueError("tombstone manifest run_id is invalid")
    run_id = _stored_run_id({"run_id": run_id})
    kind_value = document["kind"]
    _require_kind(kind_value)
    kind: RunKind = kind_value
    if kind != "smoke":
        raise ValueError("tombstone manifest is not for a smoke run")
    directory_identity = document["directory_identity"]
    if (
        not isinstance(directory_identity, dict)
        or set(directory_identity) != {"dev", "ino"}
        or type(directory_identity["dev"]) is not int
        or type(directory_identity["ino"]) is not int
        or directory_identity["dev"] < 0
        or directory_identity["ino"] < 0
    ):
        raise ValueError("tombstone manifest directory identity is invalid")
    status_payload = document["status"]
    if not isinstance(status_payload, dict):
        raise ValueError("tombstone manifest status must be an object")
    _validate_manifest_status_payload(status_payload, run_id)
    metadata = _parse_run_metadata(status_payload, expected_run_id=run_id)
    if metadata[2] != kind:
        raise ValueError("tombstone manifest kind does not match its status")
    status_digest = document["status_sha256"]
    if not isinstance(status_digest, str) or _DIGEST.fullmatch(status_digest) is None:
        raise ValueError("tombstone manifest status digest is invalid")
    expected_digest = "sha256:" + hashlib.sha256(
        _canonical_status_bytes(status_payload)
    ).hexdigest()
    if status_digest != expected_digest:
        raise ValueError("tombstone manifest status digest does not match its status")
    entries = _parse_tombstone_entries(document["entries"])
    entries_digest = document["entries_sha256"]
    if not isinstance(entries_digest, str) or _DIGEST.fullmatch(entries_digest) is None:
        raise ValueError("tombstone manifest entries digest is invalid")
    expected_entries_digest = "sha256:" + hashlib.sha256(
        json.dumps(
            _entry_documents(entries),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    if entries_digest != expected_entries_digest:
        raise ValueError("tombstone manifest entries digest does not match its entries")
    status_entry = next(
        (entry for entry in entries if entry.path == "run_status.json"),
        None,
    )
    if status_entry is None or status_entry.entry_type != "file":
        raise ValueError("tombstone manifest does not bind its run status")
    return _TombstoneManifest(
        tombstone=tombstone,
        run_id=run_id,
        kind=kind,
        directory_dev=directory_identity["dev"],
        directory_ino=directory_identity["ino"],
        status_payload=status_payload,
        entries=entries,
        file_identity=leaf_after,
    )


def _parse_tombstone_entries(value: object) -> tuple[_TombstoneEntry, ...]:
    if not isinstance(value, list):
        raise ValueError("tombstone manifest entries must be an array")
    entries: list[_TombstoneEntry] = []
    paths: set[str] = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {
            "path",
            "type",
            "dev",
            "ino",
            "mode",
            "size",
            "mtime_ns",
        }:
            raise ValueError("tombstone manifest entry schema is invalid")
        path = item["path"]
        if not isinstance(path, str):
            raise ValueError("tombstone manifest entry path is invalid")
        parts = tuple(path.split("/"))
        if _strict_relative_posix_path(parts) != path or path in paths:
            raise ValueError("tombstone manifest entry path is invalid or duplicated")
        entry_type = item["type"]
        if entry_type not in {"directory", "file", "link", "other"}:
            raise ValueError("tombstone manifest entry type is invalid")
        for key in ("dev", "ino", "mode", "size", "mtime_ns"):
            if type(item[key]) is not int:
                raise ValueError("tombstone manifest entry identity is invalid")
        if (
            item["dev"] < 0
            or item["ino"] < 0
            or item["mode"] < 0
            or item["size"] < 0
        ):
            raise ValueError("tombstone manifest entry identity is invalid")
        entries.append(
            _TombstoneEntry(
                path=path,
                entry_type=entry_type,
                dev=item["dev"],
                ino=item["ino"],
                mode=item["mode"],
                size=item["size"],
                mtime_ns=item["mtime_ns"],
            )
        )
        paths.add(path)
    if [entry.path for entry in entries] != sorted(paths):
        raise ValueError("tombstone manifest entries must be sorted")
    by_path = {entry.path: entry for entry in entries}
    for entry in entries:
        parts = entry.path.split("/")
        for index in range(1, len(parts)):
            parent = by_path.get("/".join(parts[:index]))
            if parent is None or parent.entry_type != "directory":
                raise ValueError("tombstone manifest entry parent is not a directory")
    return tuple(entries)


def _validate_manifest_status_payload(
    payload: dict[str, Any],
    run_id: str,
) -> None:
    _parse_run_metadata(payload, expected_run_id=run_id)
    _required_text(payload, "status")
    _optional_text(payload, "scenario_id")
    _optional_text(payload, "message")
    for key in ("output_dir", "report_dir", "report_index"):
        value = payload.get(key)
        if value is not None and not isinstance(value, str):
            raise ValueError(f"{key} must be a path string")


def _manifest_matches_directory(
    manifest: _TombstoneManifest,
    identity: os.stat_result,
) -> bool:
    return (
        stat.S_ISDIR(identity.st_mode)
        and not _is_stat_link_like(identity)
        and identity.st_dev == manifest.directory_dev
        and identity.st_ino == manifest.directory_ino
    )


def _delete_bound_manifest(
    root: Path,
    trash: Path,
    trash_identity: os.stat_result,
    manifest_path: Path,
    manifest_identity: os.stat_result,
) -> bool:
    if (
        manifest_path.parent != trash
        or _TOMBSTONE_MANIFEST_RE.fullmatch(manifest_path.name) is None
    ):
        return False
    binding: _DirectoryBinding | None = None
    try:
        binding = _bind_directory(root, trash)
        if not os.path.samestat(trash_identity, binding.identity):
            return False
        current = _required_regular_leaf(manifest_path, "tombstone manifest")
        if (
            not os.path.samestat(manifest_identity, current)
            or _stat_signature(manifest_identity) != _stat_signature(current)
        ):
            return False
        if binding.fd is None:
            deleted = _windows_delete_entry(manifest_path, manifest_identity)
        else:
            private_name = f"{_PRIVATE_CHILD_PREFIX}{secrets.token_hex(16)}"
            os.rename(
                manifest_path.name,
                private_name,
                src_dir_fd=binding.fd,
                dst_dir_fd=binding.fd,
            )
            quarantined = os.stat(
                private_name,
                dir_fd=binding.fd,
                follow_symlinks=False,
            )
            if (
                _is_stat_link_like(quarantined)
                or not stat.S_ISREG(quarantined.st_mode)
                or not os.path.samestat(manifest_identity, quarantined)
                or _stat_signature(manifest_identity) != _stat_signature(quarantined)
            ):
                try:
                    os.stat(
                        manifest_path.name,
                        dir_fd=binding.fd,
                        follow_symlinks=False,
                    )
                except FileNotFoundError:
                    os.rename(
                        private_name,
                        manifest_path.name,
                        src_dir_fd=binding.fd,
                        dst_dir_fd=binding.fd,
                    )
                return False
            os.unlink(private_name, dir_fd=binding.fd)
            try:
                os.fsync(binding.fd)
            except OSError:
                pass
            deleted = True
        return deleted and _binding_matches(root, trash, binding)
    except (OSError, RuntimeError, ValueError):
        return False
    finally:
        if binding is not None and binding.fd is not None:
            os.close(binding.fd)


def _bind_directory(root: Path, run_dir: Path) -> _DirectoryBinding:
    identity = _snapshot_owned_run_dir(root, run_dir)
    if os.name == "nt":
        return _DirectoryBinding(identity)

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
    return _DirectoryBinding(opened, fd)


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
        final_parent_identity = final_parent.lstat()
    except (OSError, RuntimeError, ValueError) as error:
        raise ValueError(
            f"temporary-file parent could not be resolved: {type(error).__name__}"
        ) from None
    if (
        _is_stat_link_like(final_parent_identity)
        or not stat.S_ISDIR(final_parent_identity.st_mode)
        or not os.path.samestat(final_parent_identity, binding.identity)
    ):
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
    *,
    expected_entries: tuple[_TombstoneEntry, ...] | None = None,
    expected_trash_identity: os.stat_result | None = None,
) -> bool:
    if tombstone.parent != trash or _TOMBSTONE_RE.fullmatch(tombstone.name) is None:
        return False
    plan: _TombstoneDeletionPlan | None = None
    if expected_entries is not None:
        if expected_trash_identity is None:
            return False
        if not _directory_identity_matches(
            trash.parent,
            trash,
            expected_trash_identity,
        ):
            return False
        entries = {entry.path: entry for entry in expected_entries}
        if len(entries) != len(expected_entries):
            return False
        plan = _TombstoneDeletionPlan(
            root=trash.parent,
            trash=trash,
            trash_identity=expected_trash_identity,
            entries=entries,
        )
    if os.name == "nt":
        return _windows_delete_bound_tombstone(tombstone, expected_identity, plan)
    return _posix_delete_bound_tombstone(
        trash,
        tombstone,
        expected_identity,
        plan,
    )


def _windows_delete_bound_tombstone(
    tombstone: Path,
    expected_identity: os.stat_result,
    plan: _TombstoneDeletionPlan | None = None,
) -> bool:
    entry: _WindowsDeleteHandle | None = None
    try:
        entry = _windows_open_delete_handle(tombstone)
        if (
            not os.path.samestat(expected_identity, entry.identity)
            or not stat.S_ISDIR(entry.identity.st_mode)
            or _windows_is_reparse(entry.attributes)
        ):
            return False
        if not _windows_delete_children(tombstone, plan=plan):
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


def _windows_delete_children(
    directory: Path,
    *,
    plan: _TombstoneDeletionPlan | None = None,
    prefix: tuple[str, ...] = (),
) -> bool:
    try:
        children = sorted(
            (
                (Path(item.path), Path(item.path).lstat())
                for item in os.scandir(directory)
            ),
            key=lambda item: item[0].name,
        )
    except OSError:
        return False
    for child, expected_identity in children:
        child_parts = (*prefix, child.name)
        allowed: _TombstoneEntry | None = None
        if plan is not None:
            try:
                relative_path = _strict_relative_posix_path(child_parts)
            except ValueError:
                return False
            allowed = plan.entries.get(relative_path)
            attributes = getattr(expected_identity, "st_file_attributes", 0)
            if allowed is None or not _entry_matches_identity(
                allowed,
                expected_identity,
                windows_attributes=attributes,
            ):
                if (
                    stat.S_ISDIR(expected_identity.st_mode)
                    and not _windows_is_reparse(attributes)
                ):
                    _route_foreign_run_directory(
                        plan,
                        directory,
                        child,
                        expected_identity,
                    )
                return False
        if not _windows_delete_entry(
            child,
            expected_identity,
            plan=plan,
            child_parts=child_parts,
            allowed=allowed,
        ):
            return False
    return True


def _windows_delete_entry(
    path: Path,
    expected_identity: os.stat_result,
    *,
    plan: _TombstoneDeletionPlan | None = None,
    child_parts: tuple[str, ...] = (),
    allowed: _TombstoneEntry | None = None,
) -> bool:
    entry: _WindowsDeleteHandle | None = None
    try:
        entry = _windows_open_delete_handle(path)
        if not os.path.samestat(expected_identity, entry.identity):
            return False
        if plan is not None and (
            allowed is None
            or not _entry_matches_identity(
                allowed,
                entry.identity,
                windows_attributes=entry.attributes,
            )
        ):
            return False
        is_directory = stat.S_ISDIR(entry.identity.st_mode)
        if is_directory and not _windows_is_reparse(entry.attributes):
            if not _windows_delete_children(
                path,
                plan=plan,
                prefix=child_parts,
            ):
                return False
        current = os.fstat(entry.fd)
        if not os.path.samestat(entry.identity, current):
            return False
        if plan is not None and (
            allowed is None
            or not _entry_matches_identity(
                allowed,
                current,
                windows_attributes=getattr(current, "st_file_attributes", 0),
            )
        ):
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
        attributes = getattr(identity, "st_file_attributes", 0)
        return _WindowsDeleteHandle(fd, msvcrt.get_osfhandle(fd), identity, attributes)
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


def _posix_delete_bound_tombstone(
    trash: Path,
    tombstone: Path,
    expected_identity: os.stat_result,
    plan: _TombstoneDeletionPlan | None = None,
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
        if plan is not None:
            trash_opened = os.fstat(parent_fd)
            if not os.path.samestat(plan.trash_identity, trash_opened):
                return False
        if not _posix_delete_children(
            entry_fd,
            directory_path=tombstone,
            plan=plan,
        ):
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


def _posix_delete_children(
    directory_fd: int,
    *,
    directory_path: Path | None = None,
    plan: _TombstoneDeletionPlan | None = None,
    prefix: tuple[str, ...] = (),
) -> bool:
    try:
        names = sorted(os.listdir(directory_fd))
    except OSError:
        return False
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    for name in names:
        if name.startswith(_PRIVATE_CHILD_PREFIX):
            return False
        child_fd: int | None = None
        try:
            before = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            child_parts = (*prefix, name)
            allowed: _TombstoneEntry | None = None
            if plan is not None:
                relative_path = _strict_relative_posix_path(child_parts)
                allowed = plan.entries.get(relative_path)
                if allowed is None or not _entry_matches_identity(allowed, before):
                    if (
                        directory_path is not None
                        and stat.S_ISDIR(before.st_mode)
                        and not _is_stat_link_like(before)
                    ):
                        _route_foreign_run_directory(
                            plan,
                            directory_path,
                            directory_path / name,
                            before,
                            parent_fd=directory_fd,
                        )
                    return False
            if stat.S_ISDIR(before.st_mode) and not _is_stat_link_like(before):
                child_fd = os.open(name, flags, dir_fd=directory_fd)
                opened = os.fstat(child_fd)
                if not os.path.samestat(before, opened) or (
                    plan is not None
                    and (
                        allowed is None
                        or not _entry_matches_identity(allowed, opened)
                    )
                ):
                    return False
                if not _posix_delete_children(
                    child_fd,
                    directory_path=(
                        None if directory_path is None else directory_path / name
                    ),
                    plan=plan,
                    prefix=child_parts,
                ):
                    return False
                current = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                if not os.path.samestat(opened, current) or (
                    plan is not None
                    and (
                        allowed is None
                        or not _entry_matches_identity(allowed, current)
                    )
                ):
                    return False
                os.rmdir(name, dir_fd=directory_fd)
            else:
                private_name = f"{_PRIVATE_CHILD_PREFIX}{secrets.token_hex(16)}"
                os.rename(
                    name,
                    private_name,
                    src_dir_fd=directory_fd,
                    dst_dir_fd=directory_fd,
                )
                quarantined = os.stat(
                    private_name,
                    dir_fd=directory_fd,
                    follow_symlinks=False,
                )
                if not os.path.samestat(before, quarantined) or (
                    plan is not None
                    and (
                        allowed is None
                        or not _entry_matches_identity(allowed, quarantined)
                    )
                ):
                    try:
                        os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                    except FileNotFoundError:
                        os.rename(
                            private_name,
                            name,
                            src_dir_fd=directory_fd,
                            dst_dir_fd=directory_fd,
                        )
                    return False
                os.unlink(private_name, dir_fd=directory_fd)
        except (OSError, RuntimeError, ValueError):
            return False
        finally:
            if child_fd is not None:
                os.close(child_fd)
    return True


def _route_foreign_run_directory(
    plan: _TombstoneDeletionPlan,
    parent: Path,
    child: Path,
    expected_identity: os.stat_result,
    *,
    parent_fd: int | None = None,
) -> bool:
    binding: _DirectoryBinding | None = None
    try:
        if child.parent != parent:
            return False
        if not _directory_identity_matches(plan.root, plan.trash, plan.trash_identity):
            return False
        loaded = _read_status_payload(parent, child)
        run_id = _stored_run_id(loaded.payload)
        _parse_run_metadata(loaded.payload, expected_run_id=run_id)
        if not os.path.samestat(expected_identity, loaded.directory_identity):
            return False

        binding = _bind_directory(plan.root, plan.trash)
        if not os.path.samestat(plan.trash_identity, binding.identity):
            return False
        if parent_fd is None:
            current = _snapshot_owned_run_dir(parent, child)
        else:
            current = os.stat(
                child.name,
                dir_fd=parent_fd,
                follow_symlinks=False,
            )
        if (
            _is_stat_link_like(current)
            or not stat.S_ISDIR(current.st_mode)
            or not os.path.samestat(expected_identity, current)
        ):
            return False

        for _ in range(8):
            candidate = plan.trash / _new_tombstone_name()
            if not _path_exists_or_link(candidate):
                displaced = candidate
                break
        else:
            return False
        if parent_fd is not None and binding.fd is not None:
            os.rename(
                child.name,
                displaced.name,
                src_dir_fd=parent_fd,
                dst_dir_fd=binding.fd,
            )
        else:
            os.replace(child, displaced)
        if not _binding_matches(plan.root, plan.trash, binding):
            return False
        isolated = _snapshot_owned_run_dir(plan.trash, displaced)
        if not os.path.samestat(expected_identity, isolated):
            return False
        _recover_one_tombstone(
            plan.root,
            plan.trash,
            plan.trash_identity,
            displaced,
        )
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
        if binding is not None and binding.fd is not None:
            os.close(binding.fd)


def _new_tombstone_name() -> str:
    return f"tomb-{secrets.token_hex(16)}"


def _recover_run_trash(root: Path) -> list[str]:
    trash = root / _TRASH_NAME
    try:
        if not _path_exists_or_link(trash):
            return []
        trash_identity = _snapshot_owned_run_dir(root, trash)
        candidates = _strict_tombstones(trash)
    except (OSError, RuntimeError, ValueError):
        return []

    deleted: list[str] = []
    protected_tombstones: set[str] = set()
    for manifest_path in _strict_tombstone_manifests(trash):
        run_id, protected = _recover_one_manifest(
            root,
            trash,
            trash_identity,
            manifest_path,
        )
        if run_id is not None and run_id not in deleted:
            deleted.append(run_id)
        if protected is not None:
            protected_tombstones.add(protected)

    max_rounds = max(1, len(candidates) * 2 + 2)
    for _ in range(max_rounds):
        progress = False
        for tombstone in _strict_tombstones(trash):
            if tombstone.name in protected_tombstones:
                continue
            if _recover_one_tombstone(root, trash, trash_identity, tombstone):
                progress = True
        if not progress:
            break
    return deleted


def _strict_tombstones(trash: Path) -> list[Path]:
    try:
        children = sorted(trash.iterdir(), key=lambda path: path.name)
    except OSError:
        return []
    return [child for child in children if _TOMBSTONE_RE.fullmatch(child.name)]


def _strict_tombstone_manifests(trash: Path) -> list[Path]:
    try:
        children = sorted(trash.iterdir(), key=lambda path: path.name)
    except OSError:
        return []
    return [
        child
        for child in children
        if _TOMBSTONE_MANIFEST_RE.fullmatch(child.name)
    ]


def _recover_one_manifest(
    root: Path,
    trash: Path,
    trash_identity: os.stat_result,
    manifest_path: Path,
) -> tuple[str | None, str | None]:
    try:
        if not _directory_identity_matches(root, trash, trash_identity):
            return None, None
        manifest = _read_tombstone_manifest(root, trash, manifest_path)
        if not os.path.samestat(manifest.file_identity, manifest_path.lstat()):
            return None, None
        tombstone = trash / manifest.tombstone
        if not _path_exists_or_link(tombstone):
            _delete_bound_manifest(
                root,
                trash,
                trash_identity,
                manifest_path,
                manifest.file_identity,
            )
            return None, None

        tombstone_identity = _snapshot_owned_run_dir(trash, tombstone)
        if not _manifest_matches_directory(manifest, tombstone_identity):
            return None, None
        if not _delete_bound_tombstone(
            trash,
            tombstone,
            tombstone_identity,
            expected_entries=manifest.entries,
            expected_trash_identity=trash_identity,
        ):
            return None, tombstone.name
        _delete_bound_manifest(
            root,
            trash,
            trash_identity,
            manifest_path,
            manifest.file_identity,
        )
        return manifest.run_id, None
    except (
        OSError,
        RuntimeError,
        UnicodeError,
        ValueError,
        TypeError,
        json.JSONDecodeError,
    ):
        return None, None


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
