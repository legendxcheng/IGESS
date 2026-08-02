from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from .fish_data import FishDataError, FishDataSnapshot
from .fish_state import PlayerState
from .fish_trash_model import (
    TrashManRebirthRule,
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
        self._rebirth_rules = self._rebirth_rows()
        self._strength_material_multipliers = (
            self._strength_material_multiplier_rows()
        )

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

    def progression_seconds_to_next_realm(self, realm_id: int) -> int:
        try:
            return self._realms[realm_id].progression_seconds_to_next_realm
        except KeyError as exc:
            raise FishDataError(
                f"unknown production trash-man realm id: {realm_id}"
            ) from exc

    def material_required_to_next_realm(self, realm_id: int) -> SimNumber:
        try:
            return self._realms[realm_id].material_required_to_next_realm
        except KeyError as exc:
            raise FishDataError(
                f"unknown production trash-man realm id: {realm_id}"
            ) from exc

    def can_fund_realm_breakthrough(self, state: PlayerState) -> bool:
        if not isinstance(state, PlayerState):
            raise FishDataError("state must be a PlayerState")
        realm_id = state.trash_man.realm_id
        if realm_id not in self._realms:
            raise FishDataError(
                f"unknown production trash-man realm id: {realm_id}"
            )
        if (
            state.trash_man.breakthrough.active
            or realm_id != state.trash_man.highest_realm_id
            or self.next_realm_id(realm_id) is None
        ):
            return False
        return (
            self.material_required_to_next_realm(realm_id)
            <= state.wallet.material.to_sim_number()
        )

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

    def fish_hall_output_multiplier(
        self,
        completed_rebirth_count: int,
    ) -> SimNumber:
        """Map 0 to implicit 1x and n>=1 to tbtrashmanrebirth id n."""

        self._validate_rebirth_count(completed_rebirth_count)
        if completed_rebirth_count == 0:
            return SimNumber.one()
        return self.trash_man_rebirth_rule(
            completed_rebirth_count
        ).fish_hall_output_multiplier

    def strength_material_output_multiplier(
        self,
        completed_rebirth_count: int,
    ) -> SimNumber:
        if (
            type(completed_rebirth_count) is not int
            or completed_rebirth_count < 0
        ):
            raise FishDataError(
                "strength rebirth completed count must be non-negative"
            )
        if completed_rebirth_count == 0:
            return SimNumber.one()
        if completed_rebirth_count > len(self._strength_material_multipliers):
            raise FishDataError(
                "strength rebirth completed count is out of range: "
                f"{completed_rebirth_count}"
            )
        return self._strength_material_multipliers[
            completed_rebirth_count - 1
        ]

    @property
    def max_trash_man_rebirth_count(self) -> int:
        return len(self._rebirth_rules)

    def trash_man_rebirth_rule(
        self,
        completed_count: int,
    ) -> TrashManRebirthRule:
        """Return the row earned after exactly ``completed_count`` rebirths."""

        self._validate_rebirth_count(completed_count)
        if completed_count == 0:
            raise FishDataError(
                "trash-man rebirth count 0 has the default 1x multiplier "
                "and no table row"
            )
        return self._rebirth_rules[completed_count - 1]

    def next_trash_man_rebirth_rule(
        self,
        completed_count: int,
    ) -> TrashManRebirthRule:
        """Return the realm requirement and reward for the next rebirth."""

        self._validate_rebirth_count(completed_count)
        if completed_count >= self.max_trash_man_rebirth_count:
            raise FishDataError(
                "trash-man rebirth is already at max completed count: "
                f"{completed_count}"
            )
        return self.trash_man_rebirth_rule(completed_count + 1)

    def can_trash_man_rebirth(self, state: PlayerState) -> bool:
        if not isinstance(state, PlayerState):
            raise FishDataError("state must be a PlayerState")
        completed_count = state.rebirth.trash_man_completed_count
        self._validate_rebirth_count(completed_count)
        if state.trash_man.realm_id not in self._realms:
            raise FishDataError(
                "unknown production trash-man realm id: "
                f"{state.trash_man.realm_id}"
            )
        if (
            completed_count >= self.max_trash_man_rebirth_count
            or state.trash_man.breakthrough.active
        ):
            return False
        return (
            state.trash_man.realm_id
            >= self.next_trash_man_rebirth_rule(
                completed_count
            ).realm_requirement
        )

    def settle(
        self,
        state: PlayerState,
        elapsed_seconds: int,
        *,
        runtime: TrashProcessingRuntime | None = None,
        processing_efficiency: SimNumber = SimNumber.one(),
    ) -> TrashProcessingSettlement:
        from .fish_trash_settlement import settle_trash

        return settle_trash(
            self,
            state,
            elapsed_seconds,
            runtime=runtime,
            processing_efficiency=processing_efficiency,
        )

    def settle_online(
        self,
        state: PlayerState,
        elapsed_seconds: int,
        *,
        runtime: TrashProcessingRuntime | None = None,
        _mutate: bool = False,
    ) -> TrashOnlineSettlement:
        from .fish_trash_settlement import settle_trash_online

        return settle_trash_online(
            self,
            state,
            elapsed_seconds,
            runtime=runtime,
            _mutate=_mutate,
        )

    def settle_offline(
        self,
        state: PlayerState,
        elapsed_seconds: int,
        *,
        runtime: TrashProcessingRuntime | None = None,
        processing_efficiency: SimNumber = SimNumber.parse("0.5"),
    ) -> TrashOnlineSettlement:
        from .fish_trash_settlement import settle_trash_offline

        return settle_trash_offline(
            self,
            state,
            elapsed_seconds,
            runtime=runtime,
            processing_efficiency=processing_efficiency,
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
                progression_seconds_to_next_realm=_nonnegative_int(
                    _field(
                        row,
                        "breakthroughSecondsToNextRealm",
                        "tbtrashmanrealm",
                    ),
                    (
                        "tbtrashmanrealm."
                        f"{row_id}.breakthroughSecondsToNextRealm"
                    ),
                ),
                material_required_to_next_realm=_nonnegative_sim_number(
                    _field(
                        row,
                        "materialRequireToNextRealm",
                        "tbtrashmanrealm",
                    ),
                    (
                        "tbtrashmanrealm."
                        f"{row_id}.materialRequireToNextRealm"
                    ),
                ),
            )
        if not result:
            raise FishDataError("tbtrashmanrealm must not be empty")
        order = tuple(sorted(result))
        for realm_id in order[:-1]:
            if (
                result[realm_id].material_required_to_next_realm
                <= SimNumber.zero()
            ):
                raise FishDataError(
                    "tbtrashmanrealm non-final materialRequireToNextRealm "
                    "must be positive"
                )
        for current_id, next_id in zip(order[:-2], order[1:-1]):
            if (
                result[current_id].material_required_to_next_realm
                >= result[next_id].material_required_to_next_realm
            ):
                raise FishDataError(
                    "tbtrashmanrealm non-final materialRequireToNextRealm "
                    "must strictly increase by id"
                )
        if (
            result[order[-1]].material_required_to_next_realm
            != SimNumber.zero()
        ):
            raise FishDataError(
                "tbtrashmanrealm final materialRequireToNextRealm must be zero"
            )
        return result, order

    def _rebirth_rows(self) -> tuple[TrashManRebirthRule, ...]:
        result: dict[int, TrashManRebirthRule] = {}
        for row in self.data.table("tbtrashmanrebirth"):
            row_id = _positive_int(
                _field(row, "id", "tbtrashmanrebirth"),
                "tbtrashmanrebirth.id",
            )
            if row_id in result:
                raise FishDataError(
                    f"tbtrashmanrebirth contains duplicate id: {row_id}"
                )
            result[row_id] = TrashManRebirthRule(
                completed_count=row_id,
                realm_requirement=_nonnegative_int(
                    _field(
                        row,
                        "realmRequirement",
                        "tbtrashmanrebirth",
                    ),
                    f"tbtrashmanrebirth.{row_id}.realmRequirement",
                ),
                fish_hall_output_multiplier=_positive_sim_number(
                    _field(
                        row,
                        "fishHallOutputMultiplier",
                        "tbtrashmanrebirth",
                    ),
                    (
                        "tbtrashmanrebirth."
                        f"{row_id}.fishHallOutputMultiplier"
                    ),
                ),
            )
        if not result:
            raise FishDataError(
                "tbtrashmanrebirth must contain at least one row"
            )
        expected_ids = set(range(1, len(result) + 1))
        if set(result) != expected_ids:
            raise FishDataError(
                "tbtrashmanrebirth ids must be contiguous and start at 1"
            )
        return tuple(result[row_id] for row_id in sorted(result))

    def _strength_material_multiplier_rows(self) -> tuple[SimNumber, ...]:
        result: dict[int, SimNumber] = {}
        for row in self.data.table("tbstrengthrebirth"):
            row_id = _positive_int(
                _field(row, "id", "tbstrengthrebirth"),
                "tbstrengthrebirth.id",
            )
            if row_id in result:
                raise FishDataError(
                    f"tbstrengthrebirth contains duplicate id: {row_id}"
                )
            result[row_id] = _positive_sim_number(
                _field(
                    row,
                    "materialOutputMultiplier",
                    "tbstrengthrebirth",
                ),
                f"tbstrengthrebirth.{row_id}.materialOutputMultiplier",
            )
        if not result:
            raise FishDataError(
                "tbstrengthrebirth must contain at least one row"
            )
        expected_ids = set(range(1, len(result) + 1))
        if set(result) != expected_ids:
            raise FishDataError(
                "tbstrengthrebirth ids must be contiguous and start at 1"
            )
        return tuple(result[row_id] for row_id in sorted(result))

    def _validate_rebirth_count(self, completed_count: int) -> None:
        if type(completed_count) is not int or completed_count < 0:
            raise FishDataError(
                "trash-man rebirth completed count must be non-negative"
            )
        if completed_count > self.max_trash_man_rebirth_count:
            raise FishDataError(
                "trash-man rebirth completed count is out of range: "
                f"{completed_count}"
            )


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
    parsed = _nonnegative_sim_number(value, field)
    if parsed <= SimNumber.zero():
        raise FishDataError(f"{field} must be a positive number")
    return parsed


def _nonnegative_sim_number(value: Any, field: str) -> SimNumber:
    raw: Any
    if hasattr(value, "sign") and hasattr(value, "digits") and hasattr(value, "scale"):
        sign = getattr(value, "sign")
        digits = getattr(value, "digits")
        scale = getattr(value, "scale")
        if sign not in {-1, 0, 1} or not isinstance(digits, str):
            raise FishDataError(f"{field} must be a non-negative number")
        try:
            raw = Decimal(digits) * (Decimal(10) ** int(scale))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise FishDataError(f"{field} must be a non-negative number") from exc
        if sign < 0:
            raw = -raw
        elif sign == 0:
            raw = Decimal(0)
    else:
        raw = value
    try:
        parsed = SimNumber.parse(raw)
    except (ArithmeticError, TypeError, ValueError) as exc:
        raise FishDataError(f"{field} must be a non-negative number") from exc
    if parsed < SimNumber.zero():
        raise FishDataError(f"{field} must be a non-negative number")
    return parsed
