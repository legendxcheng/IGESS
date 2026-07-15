"""Command response contracts shared by authoring services and front ends."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import json
import re
from typing import Any, Mapping, Sequence


class AuthoringError(Exception):
    """A structured domain error that can be converted into a command response."""

    def __init__(
        self,
        code: str,
        message: str,
        details: Mapping[str, Any] | None = None,
        result: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = deepcopy(dict(details or {}))
        self.result = deepcopy(dict(result or {}))


_ARTIFACT_KEYS = (
    "project",
    "config",
    "datas",
    "tables",
    "readme",
    "run_script",
    "output_dir",
    "report_index",
)


@dataclass(frozen=True, slots=True)
class CommandResponse:
    """The stable schema-version-1 response emitted by authoring commands."""

    command: str
    ok: bool
    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "details", deepcopy(dict(self.details)))
        object.__setattr__(self, "result", deepcopy(dict(self.result)))

    def to_payload(self) -> dict[str, Any]:
        """Return a defensive copy with the protocol's fixed outer key order."""

        return {
            "schema_version": 1,
            "command": self.command,
            "ok": self.ok,
            "code": self.code,
            "message": self.message,
            "details": deepcopy(self.details),
            "result": deepcopy(self.result),
        }

    def to_json(self) -> str:
        """Serialize one compact, deterministic JSON object without ASCII escaping."""

        return json.dumps(
            self.to_payload(),
            ensure_ascii=False,
            separators=(",", ":"),
        )

    def human_lines(self) -> list[str]:
        """Render only the typed, human-facing parts of a command result."""

        lines = [self.message]
        nested_status = self.result.get("status")
        status = nested_status if isinstance(nested_status, Mapping) else self.result

        self._append_issues(lines, "Missing requirements:", status.get("missing_requirements"))
        self._append_issues(lines, "Warnings:", status.get("warnings"))

        changed_files = _string_items(self.result.get("changed_files"))
        if changed_files:
            lines.append("Changed files:")
            lines.extend(f"- {path}" for path in changed_files)

        artifacts = [
            (key, value)
            for key in _ARTIFACT_KEYS
            if isinstance((value := self.result.get(key)), str) and value
        ]
        if artifacts:
            lines.append("Artifacts:")
            lines.extend(f"- {key}: {value}" for key, value in artifacts)

        return lines

    @staticmethod
    def _append_issues(lines: list[str], header: str, value: Any) -> None:
        issues = _issue_messages(value)
        if issues:
            lines.append(header)
            lines.extend(f"- {message}" for message in issues)


def _string_items(value: Any) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _issue_messages(value: Any) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []

    messages: list[str] = []
    for issue in value:
        if isinstance(issue, str):
            if issue:
                messages.append(issue)
            continue
        if not isinstance(issue, Mapping):
            continue
        message = issue.get("message")
        if not isinstance(message, str) or not message:
            continue
        entity = issue.get("entity")
        entity_id = issue.get("id")
        reference_parts = [part for part in (entity, entity_id) if isinstance(part, str) and part]
        if reference_parts and not all(_contains_reference(message, part) for part in reference_parts):
            message = f"[{':'.join(reference_parts)}] {message}"
        messages.append(message)
    return messages


def _contains_reference(message: str, part: str) -> bool:
    return re.search(
        rf"(?<![\w-]){re.escape(part)}(?![\w-])",
        message,
        flags=re.IGNORECASE,
    ) is not None
