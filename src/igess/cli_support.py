from __future__ import annotations

from pathlib import Path


def require_file(path: str | Path, role: str) -> Path:
    candidate = Path(path)
    if not candidate.exists():
        raise ValueError(f"{role} not found: {candidate}")
    if not candidate.is_file():
        raise ValueError(f"{role} is not a file: {candidate}")
    return candidate


def require_directory(path: str | Path, role: str) -> Path:
    candidate = Path(path)
    if not candidate.exists():
        raise ValueError(f"{role} not found: {candidate}")
    if not candidate.is_dir():
        raise ValueError(f"{role} is not a directory: {candidate}")
    return candidate
