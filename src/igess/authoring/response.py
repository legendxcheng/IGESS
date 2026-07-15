"""Command response contracts shared by authoring services and front ends."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from types import MappingProxyType
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
        self.details = _deep_freeze(dict(details or {}))
        self.result = _deep_freeze(dict(result or {}))

    def __reduce__(self) -> tuple[Any, tuple[Any, ...]]:
        return (
            type(self),
            (
                self.code,
                self.message,
                _deep_thaw(self.details),
                _deep_thaw(self.result),
            ),
        )


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
    details: Mapping[str, Any] = field(default_factory=dict)
    result: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "details", _deep_freeze(self.details))
        object.__setattr__(self, "result", _deep_freeze(self.result))

    def to_payload(self) -> dict[str, Any]:
        """Return a defensive copy with the protocol's fixed outer key order."""

        return {
            "schema_version": 1,
            "command": self.command,
            "ok": self.ok,
            "code": self.code,
            "message": self.message,
            "details": _deep_thaw(self.details),
            "result": _deep_thaw(self.result),
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
        missing_parts = [part for part in reference_parts if not _contains_reference(message, part)]
        if missing_parts:
            message = f"[{':'.join(missing_parts)}] {message}"
        messages.append(message)
    return messages


def _contains_reference(message: str, part: str) -> bool:
    return re.search(
        rf"(?<![\w-]){re.escape(part)}(?![\w-])",
        message,
        flags=re.IGNORECASE,
    ) is not None


def _deep_freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        items = list(value.items())
        if all(isinstance(key, str) for key, _ in items):
            items.sort(key=lambda item: item[0])
        return MappingProxyType({key: _deep_freeze(item) for key, item in items})
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_deep_freeze(item) for item in value)
    return value


def _deep_thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _deep_thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_deep_thaw(item) for item in value]
    if isinstance(value, frozenset):
        thawed = [_deep_thaw(item) for item in value]
        return sorted(thawed, key=lambda item: (type(item).__name__, repr(item)))
    return value
