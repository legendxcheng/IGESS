"""Errors and serialization shared by the public analysis operations."""
from __future__ import annotations

from typing import Any


class AnalysisError(ValueError):
    def __init__(self, code: str, message: str, **details: Any):
        super().__init__(message)
        self.code = code
        self.details = details
