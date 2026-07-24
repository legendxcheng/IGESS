"""Public Trash/TrashMan API with compatibility imports."""

from .fish_trash_model import (
    TrashManRebirthRule,
    TrashManRealmRule,
    TrashManRealmTransition,
    TrashOnlineSettlement,
    TrashProcessingRuntime,
    TrashProcessingSettlement,
    TrashRule,
)
from .fish_trash_rules import FishTrashDataAdapter

__all__ = [
    "FishTrashDataAdapter",
    "TrashManRebirthRule",
    "TrashManRealmRule",
    "TrashManRealmTransition",
    "TrashOnlineSettlement",
    "TrashProcessingRuntime",
    "TrashProcessingSettlement",
    "TrashRule",
]
