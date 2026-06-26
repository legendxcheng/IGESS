from __future__ import annotations

import operator
import re
from collections.abc import Callable

OWNED_RE = re.compile(r"^owned\(([A-Za-z0-9_*.-]+)\)\s*(>=|<=|==|>|<)\s*(\d+)$")

OPS: dict[str, Callable[[int, int], bool]] = {
    ">=": operator.ge,
    "<=": operator.le,
    "==": operator.eq,
    ">": operator.gt,
    "<": operator.lt,
}


def referenced_owned_id(condition: str) -> str | None:
    condition = (condition or "always").strip()
    if condition == "always":
        return None
    match = OWNED_RE.match(condition)
    if not match:
        raise ValueError(f"unsupported unlock condition: {condition}")
    return match.group(1)


def evaluate(condition: str, owned_lookup: Callable[[str], int]) -> bool:
    condition = (condition or "always").strip()
    if condition == "always":
        return True
    match = OWNED_RE.match(condition)
    if not match:
        raise ValueError(f"unsupported unlock condition: {condition}")
    item_id, op, threshold = match.groups()
    return OPS[op](owned_lookup(item_id), int(threshold))
