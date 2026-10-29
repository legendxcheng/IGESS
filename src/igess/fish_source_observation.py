"""Reconstruct owned complete observations from the optional source transport."""
from __future__ import annotations

from typing import Any
from uuid import uuid4


def _copy(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _copy(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_copy(item) for item in value]
    return value


def _mapping(value: Any) -> dict[str, Any]:
    # The source JSON contract represents an empty Lua table as [].
    if value == []:
        return {}
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError("observation object required")
    return value


def _patch(previous: dict[str, Any], patch: Any) -> dict[str, Any]:
    if not isinstance(patch, dict) or set(patch) != {"values", "removed"}:
        raise ValueError("invalid observation patch")
    values = _mapping(patch["values"])
    removed = patch["removed"]
    if not isinstance(removed, list) or any(not isinstance(key, str) for key in removed):
        raise ValueError("invalid removed fields")
    if len(set(removed)) != len(removed) or set(removed) & values.keys():
        raise ValueError("conflicting observation fields")
    result = previous.copy()
    for key in removed:
        if key not in result:
            raise ValueError("removed field missing from baseline")
        del result[key]
    result.update(values)
    return result


class SourceObservation:
    def __init__(self) -> None:
        self.channel = uuid4().hex
        self.token = 0
        self._state: dict[str, Any] | None = None

    def apply(self, response: dict[str, Any]) -> dict[str, Any]:
        token = response.get("token")
        base = response.get("base")
        if (response.get("channel") != self.channel or type(token) is not int
                or token <= self.token or token > 9007199254740991 or type(base) is not int):
            raise ValueError("invalid observation identity")
        if response.get("kind") == "full":
            if set(response) != {"channel", "token", "base", "kind", "state"} or response["base"] != 0:
                raise ValueError("invalid full observation")
            state = response["state"]
            if not isinstance(state, dict):
                raise ValueError("complete observation required")
        elif response.get("kind") == "delta":
            if set(response) != {"channel", "token", "base", "kind", "patch"}:
                raise ValueError("invalid delta observation")
            if self._state is None or response["base"] != self.token or token != self.token + 1:
                raise ValueError("observation baseline mismatch")
            patch = response["patch"]
            if not isinstance(patch, dict) or set(patch) != {"values", "removed", "sections"}:
                raise ValueError("invalid observation delta")
            sections = _mapping(patch["sections"])
            state = _patch(self._state, {"values": patch["values"], "removed": patch["removed"]})
            for key, change in sections.items():
                if key in _mapping(patch["values"]) or key in patch["removed"] or not isinstance(state.get(key), dict):
                    raise ValueError("invalid observation section")
                state[key] = _patch(state[key], change)
        else:
            raise ValueError("unknown observation kind")
        self._state, self.token = state, token
        return _copy(state)
