from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from .fish_data import FishDataError, FishDataSnapshot
from .fish_state import PlayerState
from .fish_trash_model import (
    TrashOnlineSettlement,
    TrashProcessingRuntime,
    TrashProcessingSettlement,
    TrashRule,
    TrashManRealmRule,
)
from .numbers import SimNumber


class FishTrashDataAdapter:
    """Authoritative Trash/TrashMan table rules.

    Queue and online settlement live in fish_trash_settlement; these methods
    remain as compatibility entry points for existing callers.
    """

    def __init__(self, snapshot: FishDataSnapshot) -> None:
        self.data = snapshot
        self._trash = self._trash_rows()
        self._realms, self._realm_order = self._realm_rows()
        self._realm_indexes = {
            realm_id: index for index, realm_id in enumerate(self._realm_order)
        }
        self.initial_realm_id = self._realm_order[0]
        self._rebirth_output = self._rebirth_rows()

    def trash_rule(self, trash_id: int) -> TrashRule:
        try:
            return self._trash[trash_id]
        except KeyError as exc:
            raise FishDataError(f"unknown production trash id: {trash_id}") from exc

    def initialize_realm(self, state: PlayerState) -> PlayerState:
        """Explicitly migrate the pre-Phase-5 ``realmId=0`` new-player state."""

        if not isinstance(state, PlayerState):
            raise TypeError("state must be a PlayerState")
        if state.trash_man.realm_id != 0 or state.trash_man.highest_realm_id != 0:
            return state
        migrated = state.copy()
        migrated.trash_man.realm_id = self.initial_realm_id
        migrated.trash_man.highest_realm_id = self.initial_realm_id
        return migrated

    def realm_speed(self, realm_id: int) -> SimNumber:
        try:
            return self._realms[realm_id].decompose_speed_multiplier
        except KeyError as exc:
            raise FishDataError(
                f"unknown production trash-man realm id: {realm_id}"
            ) from exc

    def cultivation_seconds_to_next_realm(self, realm_id: int) -> int:
        try:
            return self._realms[realm_id].cultivation_seconds_to_next_realm
        except KeyError as exc:
            raise FishDataError(
                f"unknown production trash-man realm id: {realm_id}"
            ) from exc

    def next_realm_id(self, realm_id: int) -> int | None:
        try:
            index = self._realm_indexes[realm_id]
        except KeyError as exc:
            raise FishDataError(
                f"unknown production trash-man realm id: {realm_id}"
            ) from exc
        if index + 1 >= len(self._realm_order):
            return None
        return self._realm_order[index + 1]

    def material_output_multiplier(
        self,
        completed_rebirth_count: int,
    ) -> SimNumber:
        if type(completed_rebirth_count) is not int or completed_rebirth_count < 0:
            raise FishDataError(
                "trash-man completed rebirth count must be non-negative"
            )
        if completed_rebirth_count == 0:
            return SimNumber.one()
        row_id = completed_rebirth_count - 1
        try:
            return self._rebirth_output[row_id]
        except KeyError as exc:
            raise FishDataError(
                "trash-man completed rebirth count exceeds production data: "
                f"{completed_rebirth_count}"
            ) from exc

    def settle(
        self,
        state: PlayerState,
        elapsed_seconds: int,
        *,
        runtime: TrashProcessingRuntime | None = None,
    ) -> TrashProcessingSettlement:
        from .fish_trash_settlement import settle_trash

        return settle_trash(
            self,
            state,
            elapsed_seconds,
            runtime=runtime,
        )

    def settle_online(
        self,
        state: PlayerState,
        elapsed_seconds: int,
        *,
        runtime: TrashProcessingRuntime | None = None,
    ) -> TrashOnlineSettlement:
        from .fish_trash_settlement import settle_trash_online

        return settle_trash_online(
            self,
            state,
            elapsed_seconds,
            runtime=runtime,
        )

    def _trash_rows(self) -> dict[int, TrashRule]:
        result: dict[int, TrashRule] = {}
        for row in self.data.table("tbtrash"):
            row_id = _positive_int(_field(row, "id", "tbtrash"), "tbtrash.id")
            if row_id in result:
                raise FishDataError(f"tbtrash contains duplicate id: {row_id}")
            result[row_id] = TrashRule(
                trash_id=row_id,
                base_decompose_seconds=_positive_int(
                    _field(row, "baseDecomposeSeconds", "tbtrash"),
                    f"tbtrash.{row_id}.baseDecomposeSeconds",
                ),
                base_material_per_second=_positive_sim_number(
                    _field(row, "baseMaterialPerSecond", "tbtrash"),
                    f"tbtrash.{row_id}.baseMaterialPerSecond",
                ),
            )
        if not result:
            raise FishDataError("tbtrash must not be empty")
        return result

    def _realm_rows(
        self,
    ) -> tuple[dict[int, TrashManRealmRule], tuple[int, ...]]:
        result: dict[int, TrashManRealmRule] = {}
        for row in self.data.table("tbtrashmanrealm"):
            row_id = _positive_int(
                _field(row, "id", "tbtrashmanrealm"),
                "tbtrashmanrealm.id",
            )
            if row_id in result:
                raise FishDataError(f"tbtrashmanrealm contains duplicate id: {row_id}")
            result[row_id] = TrashManRealmRule(
                realm_id=row_id,
                decompose_speed_multiplier=_positive_sim_number(
                    _field(
                        row,
                        "decomposeSpeedMultiplier",
                        "tbtrashmanrealm",
                    ),
                    ("tbtrashmanrealm." f"{row_id}.decomposeSpeedMultiplier"),
                ),
                cultivation_seconds_to_next_realm=_nonnegative_int(
                    _field(
                        row,
                        "cultivationSecondsToNextRealm",
                        "tbtrashmanrealm",
                    ),
                    ("tbtrashmanrealm." f"{row_id}.cultivationSecondsToNextRealm"),
                ),
            )
        if not result:
            raise FishDataError("tbtrashmanrealm must not be empty")
        return result, tuple(sorted(result))

    def _rebirth_rows(self) -> dict[int, SimNumber]:
        result: dict[int, SimNumber] = {}
        for row in self.data.table("tbtrashmanrebirth"):
            row_id = _nonnegative_int(
                _field(row, "id", "tbtrashmanrebirth"),
                "tbtrashmanrebirth.id",
            )
            if row_id in result:
                raise FishDataError(
                    f"tbtrashmanrebirth contains duplicate id: {row_id}"
                )
            result[row_id] = _positive_sim_number(
                _field(
                    row,
                    "trashToTreasureOutputMultiplier",
                    "tbtrashmanrebirth",
                ),
                ("tbtrashmanrebirth." f"{row_id}.trashToTreasureOutputMultiplier"),
            )
        return result


def _field(row: Any, name: str, table_name: str) -> Any:
    try:
        return getattr(row, name)
    except AttributeError as exc:
        raise FishDataError(
            f"generated {table_name} row is missing field: {name}"
        ) from exc


def _positive_int(value: Any, field: str) -> int:
    if type(value) is not int or value <= 0:
        raise FishDataError(f"{field} must be a positive integer")
    return value


def _nonnegative_int(value: Any, field: str) -> int:
    if type(value) is not int or value < 0:
        raise FishDataError(f"{field} must be a non-negative integer")
    return value


def _positive_sim_number(value: Any, field: str) -> SimNumber:
    raw: Any
    if hasattr(value, "sign") and hasattr(value, "digits") and hasattr(value, "scale"):
        sign = getattr(value, "sign")
        digits = getattr(value, "digits")
        scale = getattr(value, "scale")
        if sign not in {-1, 0, 1} or not isinstance(digits, str):
            raise FishDataError(f"{field} must be a positive number")
        try:
            raw = Decimal(digits) * (Decimal(10) ** int(scale))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise FishDataError(f"{field} must be a positive number") from exc
        if sign < 0:
            raw = -raw
        elif sign == 0:
            raw = Decimal(0)
    else:
        raw = value
    try:
        parsed = SimNumber.parse(raw)
    except (ArithmeticError, TypeError, ValueError) as exc:
        raise FishDataError(f"{field} must be a positive number") from exc
    if parsed <= SimNumber.zero():
        raise FishDataError(f"{field} must be a positive number")
    return parsed
