from __future__ import annotations

import json
import os
import re
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Literal


RunKind = Literal["smoke", "formal", "advice"]

_RUN_STATUS_VERSION = 1
_RUN_KINDS = frozenset({"smoke", "formal", "advice"})
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_MAX_STATUS_BYTES = 1024 * 1024


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
        status_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        return self._record_from_payload(status_path, payload, root=self.runs_root)

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
        smoke = sorted(
            (
                record
                for record in self._records_from_root(self.runs_root)
                if record.kind == "smoke"
            ),
            key=lambda record: record.run_id,
        )
        to_delete = smoke[: max(0, len(smoke) - keep)]
        deleted: list[str] = []
        for record in to_delete:
            if self._delete_owned_smoke(record):
                deleted.append(record.run_id)
        return deleted

    def _records_from_root(self, root: Path) -> list[RunRecord]:
        try:
            if not root.is_dir():
                return []
            root.resolve(strict=True)
        except (OSError, RuntimeError, ValueError):
            return []

        records: list[RunRecord] = []
        try:
            candidates = sorted(root.iterdir(), key=lambda path: path.name)
        except OSError:
            return []
        for run_dir in candidates:
            status_path = run_dir / "run_status.json"
            try:
                _require_owned_run_dir(root, run_dir, require_exists=True)
                if _is_link_like(status_path):
                    continue
                status_info = status_path.stat()
                if not stat.S_ISREG(status_info.st_mode) or status_info.st_size > _MAX_STATUS_BYTES:
                    continue
                payload = json.loads(status_path.read_text(encoding="utf-8"))
                if not isinstance(payload, dict):
                    continue
                records.append(self._record_from_payload(status_path, payload, root=root))
            except (OSError, RuntimeError, UnicodeError, ValueError, TypeError, json.JSONDecodeError):
                continue
        return records

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

        run_id = _required_text(payload, "run_id")
        if run_id != run_dir.name or Path(run_id).name != run_id:
            raise ValueError("run_id must match its run directory")
        status = _required_text(payload, "status")
        scenario_id = _optional_text(payload, "scenario_id")
        message = _optional_text(payload, "message")

        if "version" not in payload:
            version: int | None = None
            kind: RunKind = "formal"
            change_id = None
            model_digest = None
        else:
            version_value = payload["version"]
            if isinstance(version_value, bool) or version_value != _RUN_STATUS_VERSION:
                raise ValueError("unsupported run status version")
            version = _RUN_STATUS_VERSION
            kind_value = payload.get("kind")
            _require_kind(kind_value)
            kind = kind_value
            change_id_value = payload.get("change_id")
            if change_id_value is not None:
                _require_component(change_id_value, "change_id")
            if kind == "smoke" and change_id_value is None:
                raise ValueError("change_id is required for a smoke run status")
            change_id = change_id_value
            digest_value = payload.get("model_digest")
            _require_digest(digest_value)
            model_digest = digest_value

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

    def _delete_owned_smoke(self, record: RunRecord) -> bool:
        try:
            _require_owned_run_dir(self.runs_root, record.run_dir, require_exists=True)
            if _is_link_like(record.status_path):
                return False
            status_info = record.status_path.stat()
            if (
                not stat.S_ISREG(status_info.st_mode)
                or status_info.st_size > _MAX_STATUS_BYTES
            ):
                return False
            current = self._record_from_payload(
                record.status_path,
                json.loads(record.status_path.read_text(encoding="utf-8")),
                root=self.runs_root,
            )
            if current.run_id != record.run_id or current.kind != "smoke":
                return False
            shutil.rmtree(record.run_dir)
        except (OSError, RuntimeError, UnicodeError, ValueError, TypeError, json.JSONDecodeError):
            return False
        return True


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
        raise ValueError("model_digest must be a lowercase SHA-256 digest")


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
    try:
        resolved_root = root.resolve(strict=True)
        if _is_link_like(run_dir):
            raise ValueError("run directory must not be a link or reparse point")
        resolved_run = run_dir.resolve(strict=require_exists)
        if resolved_run.parent != resolved_root:
            raise ValueError("run directory must be a direct child of the registry")
        if require_exists:
            info = run_dir.lstat()
            if not stat.S_ISDIR(info.st_mode):
                raise ValueError("run directory must be a directory")
    except FileNotFoundError:
        raise ValueError("run directory is missing") from None
    except OSError as error:
        raise ValueError(f"run directory could not be inspected: {type(error).__name__}") from None


def _is_link_like(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    attributes = getattr(info, "st_file_attributes", 0)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(info.st_mode) or bool(attributes & reparse)
