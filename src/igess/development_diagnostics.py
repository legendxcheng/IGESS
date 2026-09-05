"""Owner-only diagnostics. This module must stay out of operator exports."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import traceback
from typing import Any
import uuid

from .formal_run import RunFailure


_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_MAX_TRACEBACK_CHARS = 256 * 1024


class DevelopmentDiagnostics:
    def __init__(self, project_root: str | Path) -> None:
        self.project_root = Path(project_root).absolute()

    def __call__(self, failure: RunFailure, context: Mapping[str, Any]) -> dict[str, str]:
        run_id = context.get("run_id")
        diagnostic_id = failure.diagnostic.get("diagnostic_id") or (
            run_id if isinstance(run_id, str) and _SAFE_ID.fullmatch(run_id)
            else "attempt-" + uuid.uuid4().hex
        )
        if not _SAFE_ID.fullmatch(diagnostic_id):
            raise ValueError("invalid diagnostic id")
        root = self.project_root
        _require_directory(root)
        for name in (".igess", "diagnostics"):
            root = root / name
            root.mkdir(exist_ok=True)
            _require_directory(root)
        path = root / f"{diagnostic_id}.json"
        payload = {
            "schema_version": 1,
            "diagnostic_id": diagnostic_id,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "phase": failure.stage,
            "context": dict(context),
            "primary_error": _exception_details(failure.error),
            "secondary_errors": [
                {"stage": stage, **_exception_details(error)}
                for stage, error in failure.secondary_errors
            ],
        }
        descriptor, temporary_name = tempfile.mkstemp(prefix=".diagnostic-", suffix=".tmp", dir=root)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2, default=str)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            _require_directory(root)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        return {"diagnostic_id": diagnostic_id, "diagnostic_path": str(path)}


def _exception_details(error: Exception) -> dict[str, str]:
    trace = "".join(traceback.TracebackException.from_exception(error, capture_locals=False).format(chain=True))
    return {
        "error_type": type(error).__name__,
        "message": str(error)[:_MAX_TRACEBACK_CHARS],
        "traceback": trace[:_MAX_TRACEBACK_CHARS],
    }


def _require_directory(path: Path) -> None:
    info = path.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    ):
        raise ValueError("development diagnostics require a real local directory")
