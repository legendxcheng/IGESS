"""Durable audit records for incremental authoring attempts."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
import errno
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
from typing import Any
import warnings as _warnings

from .change import ModelChange
from .response import AuthoringError
from .status import ModelStatus


CHANGE_RECORD_VERSION = 1
_CHANGE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_RECORD_NAME_RE = re.compile(
    r"^(?P<stamp>[0-9]{8}T[0-9]{12}Z)-(?P<change_id>[A-Za-z0-9][A-Za-z0-9_-]{0,127})\.json$"
)
_SUCCESS_KEYS = {
    "version",
    "outcome",
    "timestamp",
    "change",
    "pre_digest",
    "post_digest",
    "affected_files",
    "status",
    "warnings",
    "run_id",
}
_FAILURE_KEYS = (_SUCCESS_KEYS - {"status"}) | {"error"}


class ChangeRecordWarning(UserWarning):
    """A stored record was ignored because it could not be trusted."""


class ChangeRecordStore:
    """Stage successful audits and persist failed-attempt audits atomically.

    Successful records are staged outside the registry so the authoring
    transaction can publish sources, exports, run artifacts, and their audit as
    one recoverable unit.  Failed records do not change formal model state and
    are written directly below ``changes/failed``.
    """

    def __init__(
        self,
        changes_root: str | os.PathLike[str],
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(changes_root, (str, os.PathLike)):
            raise TypeError("changes_root must be path-like")
        if clock is not None and not callable(clock):
            raise TypeError("clock must be callable")
        self.changes_root = Path(changes_root).absolute()
        self.failed_root = self.changes_root / "failed"
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def stage_success(
        self,
        staging_path: str | os.PathLike[str],
        *,
        change_id: str,
        change: ModelChange,
        pre_digest: str,
        post_digest: str,
        affected_files: Sequence[str],
        status: ModelStatus,
        warnings: Sequence[object] = (),
        run_id: str | None = None,
    ) -> Path:
        """Atomically write a success record to transaction-owned staging.

        The returned path is the final registry destination.  This method never
        creates that final path; :class:`~igess.authoring.transactions.Transaction`
        is responsible for moving the staged file there during commit.
        """

        if not isinstance(staging_path, (str, os.PathLike)):
            raise TypeError("staging_path must be path-like")
        _require_change_id(change_id)
        _require_change(change)
        _require_digest(pre_digest, "pre_digest")
        _require_digest(post_digest, "post_digest")
        if not isinstance(status, ModelStatus):
            raise TypeError("status must be a ModelStatus")
        timestamp = _utc_timestamp(self._clock())
        destination = self.changes_root / _record_filename(timestamp, change_id)
        if destination.exists():
            _audit_error("A success audit destination already exists", destination)

        staged = Path(staging_path).absolute()
        if _lexically_within(staged, self.changes_root):
            raise ValueError("successful records must be staged outside changes_root")
        payload = {
            "version": CHANGE_RECORD_VERSION,
            "outcome": "success",
            "timestamp": _timestamp_text(timestamp),
            "change": change.to_payload(),
            "pre_digest": pre_digest,
            "post_digest": post_digest,
            "affected_files": _affected_files(affected_files),
            "status": status.to_payload(),
            "warnings": _warning_payloads(warnings),
            "run_id": _optional_run_id(run_id),
        }
        try:
            _require_real_directory(staged.parent, "success audit staging directory")
            _atomic_json_write(staged, payload)
        except (OSError, UnicodeError) as error:
            _audit_error(
                "The success audit could not be staged",
                staged,
                error=error,
            )
        return destination

    def write_failure(
        self,
        *,
        change_id: str,
        change: ModelChange,
        pre_digest: str,
        affected_files: Sequence[str],
        error: AuthoringError,
        warnings: Sequence[object] = (),
        run_id: str | None = None,
    ) -> Path:
        """Atomically persist one failed attempt without changing model state."""

        _require_change_id(change_id)
        _require_change(change)
        _require_digest(pre_digest, "pre_digest")
        if not isinstance(error, AuthoringError):
            raise TypeError("error must be an AuthoringError")
        timestamp = _utc_timestamp(self._clock())
        path = self.failed_root / _record_filename(timestamp, change_id)
        payload = {
            "version": CHANGE_RECORD_VERSION,
            "outcome": "failure",
            "timestamp": _timestamp_text(timestamp),
            "change": change.to_payload(),
            "pre_digest": pre_digest,
            "post_digest": None,
            "affected_files": _affected_files(affected_files),
            "error": {
                "code": error.code,
                "message": error.message,
                "details": _strict_json_copy(error.details, "error.details"),
                "result": _strict_json_copy(error.result, "error.result"),
            },
            "warnings": _warning_payloads(warnings),
            "run_id": _optional_run_id(run_id),
        }
        try:
            _ensure_real_directory(self.changes_root, "change audit registry")
            _ensure_real_directory(self.failed_root, "failed change audit registry")
            if path.exists():
                _audit_error("A failed audit destination already exists", path)
            _atomic_json_write(path, payload)
        except AuthoringError:
            raise
        except (OSError, UnicodeError) as media_error:
            _audit_error(
                "The failed-attempt audit could not be written",
                path,
                error=media_error,
            )
        return path

    def list_records(self, *, include_failed: bool = False) -> list[dict[str, Any]]:
        """Return valid records oldest-first, skipping malformed media safely."""

        candidates: list[tuple[Path, str]] = []
        if self.changes_root.exists():
            candidates.extend((path, "success") for path in self.changes_root.glob("*.json"))
        if include_failed and self.failed_root.exists():
            candidates.extend((path, "failure") for path in self.failed_root.glob("*.json"))

        loaded: list[tuple[datetime, str, dict[str, Any]]] = []
        for path, expected_outcome in candidates:
            try:
                identity = path.lstat()
                if stat.S_ISLNK(identity.st_mode) or not stat.S_ISREG(identity.st_mode):
                    raise ValueError("record path is not a regular file")
                payload = json.loads(path.read_text(encoding="utf-8"))
                timestamp = _validate_loaded_record(path, payload, expected_outcome)
            except (OSError, UnicodeError, ValueError, TypeError, KeyError) as error:
                _warnings.warn(
                    f"Skipped malformed change record {path}: {type(error).__name__}",
                    ChangeRecordWarning,
                    stacklevel=2,
                )
                continue
            loaded.append((timestamp, path.as_posix(), payload))
        loaded.sort(key=lambda item: (item[0], item[1]))
        return [payload for _, _, payload in loaded]

    def latest(self, *, include_failed: bool = False) -> dict[str, Any] | None:
        """Return the newest valid record, or ``None`` for an empty registry."""

        records = self.list_records(include_failed=include_failed)
        return records[-1] if records else None


def _utc_timestamp(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError("clock must return a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("clock must return a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _timestamp_text(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _record_filename(value: datetime, change_id: str) -> str:
    return f"{value.strftime('%Y%m%dT%H%M%S%fZ')}-{change_id}.json"


def _require_change_id(value: object) -> None:
    if not isinstance(value, str):
        raise TypeError("change_id must be a string")
    if _CHANGE_ID_RE.fullmatch(value) is None:
        raise ValueError("change_id must be one safe ASCII path component")


def _require_change(value: object) -> None:
    if not isinstance(value, ModelChange):
        raise TypeError("change must be a ModelChange")


def _require_digest(value: object, name: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if _DIGEST_RE.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


def _optional_run_id(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("run_id must be a string or None")
    if _CHANGE_ID_RE.fullmatch(value) is None:
        raise ValueError("run_id must be one safe ASCII path component")
    return value


def _affected_files(values: Sequence[str]) -> list[str]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)):
        raise TypeError("affected_files must be a sequence of paths")
    normalized: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value:
            raise TypeError("affected file paths must be non-empty strings")
        path = PurePosixPath(value.replace("\\", "/"))
        if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
            raise ValueError("affected file paths must be safe project-relative paths")
        normalized.add(path.as_posix())
    return sorted(normalized)


def _warning_payloads(values: Sequence[object]) -> list[dict[str, Any]]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)):
        raise TypeError("warnings must be a sequence")
    result: list[dict[str, Any]] = []
    for value in values:
        if isinstance(value, Mapping):
            payload = value
        else:
            to_payload = getattr(value, "to_payload", None)
            if not callable(to_payload):
                raise TypeError("warnings must be mappings or expose to_payload()")
            payload = to_payload()
        copied = _strict_json_copy(payload, "warning")
        if not isinstance(copied, dict):
            raise TypeError("warning payloads must be mappings")
        code = copied.get("code")
        message = copied.get("message")
        if not isinstance(code, str) or not code:
            raise ValueError("warning code must be a non-empty string")
        if not isinstance(message, str) or not message:
            raise ValueError("warning message must be a non-empty string")
        result.append(dict(sorted(copied.items())))
    return result


def _strict_json_copy(value: object, role: str) -> Any:
    def copy(node: object) -> Any:
        if isinstance(node, Mapping):
            result: dict[str, Any] = {}
            for key, item in node.items():
                if not isinstance(key, str):
                    raise TypeError(f"{role} mappings require string keys")
                result[key] = copy(item)
            return result
        if isinstance(node, (list, tuple)):
            return [copy(item) for item in node]
        if isinstance(node, (set, frozenset)):
            copied = [copy(item) for item in node]
            return sorted(copied, key=lambda item: (type(item).__name__, repr(item)))
        if node is None or type(node) in {bool, int, str}:
            return node
        raise TypeError(f"{role} contains a non-JSON value: {type(node).__name__}")

    copied = copy(value)
    json.dumps(copied, allow_nan=False)
    return copied


def _lexically_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _lstat_or_none(path: Path) -> os.stat_result | None:
    try:
        return path.lstat()
    except FileNotFoundError:
        return None


def _require_real_directory(path: Path, role: str) -> None:
    identity = _lstat_or_none(path)
    if identity is None:
        raise OSError(f"{role} is missing: {path}")
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    attributes = getattr(identity, "st_file_attributes", 0)
    if (
        stat.S_ISLNK(identity.st_mode)
        or attributes & reparse_flag
        or not stat.S_ISDIR(identity.st_mode)
    ):
        raise OSError(f"{role} is not a real directory: {path}")


def _ensure_real_directory(path: Path, role: str) -> None:
    identity = _lstat_or_none(path)
    if identity is None:
        parent = path.parent
        _require_real_directory(parent, f"{role} parent")
        path.mkdir()
        _fsync_directory(parent)
    _require_real_directory(path, role)


def _atomic_json_write(path: Path, payload: Mapping[str, Any]) -> None:
    _require_real_directory(path.parent, "audit destination directory")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        try:
            temporary.unlink()
        except OSError:
            pass
        raise


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        if _unsupported_directory_fsync(error):
            return
        raise
    try:
        os.fsync(descriptor)
    except OSError as error:
        if not _unsupported_directory_fsync(error):
            raise
    finally:
        os.close(descriptor)


def _unsupported_directory_fsync(error: OSError) -> bool:
    unsupported = {
        errno.EINVAL,
        getattr(errno, "ENOTSUP", errno.EINVAL),
        getattr(errno, "EOPNOTSUPP", errno.EINVAL),
    }
    if os.name == "nt":
        unsupported.update({errno.EACCES, errno.EBADF, errno.EPERM})
    return error.errno in unsupported


def _validate_loaded_record(
    path: Path,
    payload: object,
    expected_outcome: str,
) -> datetime:
    if not isinstance(payload, dict):
        raise ValueError("record is not an object")
    if payload.get("version") != CHANGE_RECORD_VERSION:
        raise ValueError("unsupported record version")
    outcome = payload.get("outcome")
    if outcome != expected_outcome:
        raise ValueError("record outcome does not match its registry")
    expected_keys = _SUCCESS_KEYS if outcome == "success" else _FAILURE_KEYS
    if set(payload) != expected_keys:
        raise ValueError("record keys do not match its schema")

    match = _RECORD_NAME_RE.fullmatch(path.name)
    if match is None:
        raise ValueError("record filename is malformed")
    _require_change_id(match.group("change_id"))
    timestamp = datetime.strptime(
        str(payload["timestamp"]), "%Y-%m-%dT%H:%M:%S.%fZ"
    ).replace(tzinfo=timezone.utc)
    if timestamp.strftime("%Y%m%dT%H%M%S%fZ") != match.group("stamp"):
        raise ValueError("record timestamp does not match its filename")

    _require_digest(payload["pre_digest"], "pre_digest")
    if outcome == "success":
        _require_digest(payload["post_digest"], "post_digest")
        if not isinstance(payload["status"], dict):
            raise ValueError("success status is not an object")
    elif payload["post_digest"] is not None:
        raise ValueError("failure post_digest must be null")
    if not isinstance(payload["change"], dict):
        raise ValueError("change envelope is not an object")
    affected = payload["affected_files"]
    if (
        not isinstance(affected, list)
        or affected != sorted(set(affected))
        or any(not isinstance(item, str) for item in affected)
    ):
        raise ValueError("affected files are not a sorted unique string list")
    if not isinstance(payload["warnings"], list):
        raise ValueError("warnings are not an array")
    _optional_run_id(payload["run_id"])
    if outcome == "failure":
        error = payload["error"]
        if not isinstance(error, dict) or set(error) != {
            "code",
            "message",
            "details",
            "result",
        }:
            raise ValueError("failure error envelope is malformed")
        if not isinstance(error["code"], str) or not error["code"]:
            raise ValueError("failure error code is malformed")
        if not isinstance(error["message"], str) or not error["message"]:
            raise ValueError("failure error message is malformed")
        if not isinstance(error["details"], dict) or not isinstance(error["result"], dict):
            raise ValueError("failure error context is malformed")
    _strict_json_copy(payload, "record")
    return timestamp


def _audit_error(
    message: str,
    path: Path,
    *,
    error: BaseException | None = None,
) -> None:
    details = {"path": str(path)}
    if error is not None:
        details["error_type"] = type(error).__name__
    raise AuthoringError("audit_failed", message, details) from None


__all__ = [
    "CHANGE_RECORD_VERSION",
    "ChangeRecordStore",
    "ChangeRecordWarning",
]
