from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Mapping

from .numbers import SimNumber


FISH_ENGINE_ID = "fish"
FISH_ARCHIVE_VERSION = 1
FISH_MAX_LEVEL = 100
MAX_BIG_NUMBER_EXPONENT = 1_000_000
DEFAULT_MAX_FUTURE_SECONDS = 300

IdExists = Callable[[str, int], bool]
HallCapacity = Callable[[int], int]


class FishStateValidationError(ValueError):
    """Stable, path-aware validation failure for Fish player archives."""

    def __init__(
        self,
        code: str,
        path: str,
        detail: object | None = None,
    ) -> None:
        self.code = code
        self.path = path
        self.detail = detail
        message = f"{code} at {path}"
        if detail is not None:
            message += f": {detail}"
        super().__init__(message)


@dataclass(frozen=True)
class FishStateValidationContext:
    """Optional live-config and server-clock checks used while loading."""

    now: int | None = None
    max_future_seconds: int = DEFAULT_MAX_FUTURE_SECONDS
    id_exists: IdExists | None = None
    fish_hall_capacity: HallCapacity | None = None


@dataclass(frozen=True)
class BigNumberDTO:
    """The canonical four-significant-digit DTO used by Fish Oasis saves."""

    sign: int
    coeff: int
    exp: int

    @classmethod
    def zero(cls) -> "BigNumberDTO":
        return cls(sign=0, coeff=0, exp=0)

    @classmethod
    def from_value(
        cls,
        value: "BigNumberDTO | SimNumber | Decimal | int | str",
        *,
        allow_negative: bool = True,
    ) -> "BigNumberDTO":
        if isinstance(value, BigNumberDTO):
            value.validate(allow_negative=allow_negative)
            return value
        if isinstance(value, SimNumber):
            text = value.to_decimal_string()
        elif isinstance(value, Decimal):
            text = str(value)
        elif type(value) is int:
            text = str(value)
        elif isinstance(value, str):
            text = value.strip()
            if text != value or not text:
                _fail("big_number_value_invalid", "$")
        else:
            _fail("big_number_value_invalid", "$")

        try:
            decimal = Decimal(text)
        except (InvalidOperation, ValueError) as exc:
            raise FishStateValidationError(
                "big_number_value_invalid",
                "$",
                text,
            ) from exc
        if not decimal.is_finite():
            _fail("big_number_value_invalid", "$", text)
        if decimal == 0:
            return cls.zero()

        sign = -1 if decimal.is_signed() else 1
        digits = "".join(str(digit) for digit in decimal.as_tuple().digits)
        digits = digits.lstrip("0")
        if not digits:
            return cls.zero()
        original_length = len(digits)
        if original_length >= 4:
            coeff = int(digits[:4])
            if original_length > 4 and int(digits[4]) >= 5:
                coeff += 1
        else:
            coeff = int(digits + ("0" * (4 - original_length)))
        exp = original_length + decimal.as_tuple().exponent - 4
        if coeff >= 10_000:
            coeff = 1_000
            exp += 1

        dto = cls(sign=sign, coeff=coeff, exp=exp)
        dto.validate(allow_negative=allow_negative)
        return dto

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
        *,
        path: str,
        allow_negative: bool = True,
    ) -> "BigNumberDTO":
        payload = _expect_object(value, path)
        _expect_keys(payload, {"sign", "coeff", "exp"}, path)
        dto = cls(
            sign=_expect_int(payload["sign"], f"{path}.sign"),
            coeff=_expect_int(payload["coeff"], f"{path}.coeff"),
            exp=_expect_int(payload["exp"], f"{path}.exp"),
        )
        dto.validate(path=path, allow_negative=allow_negative)
        return dto

    def validate(
        self,
        *,
        path: str = "$",
        allow_negative: bool = True,
    ) -> None:
        if type(self.sign) is not int or self.sign not in {-1, 0, 1}:
            _fail("big_number_dto_value_invalid", f"{path}.sign")
        if type(self.coeff) is not int or self.coeff < 0:
            _fail("big_number_dto_value_invalid", f"{path}.coeff")
        if (
            type(self.exp) is not int
            or abs(self.exp) > MAX_BIG_NUMBER_EXPONENT
        ):
            _fail("big_number_dto_value_invalid", f"{path}.exp")
        if self.sign == 0:
            if self.coeff != 0 or self.exp != 0:
                _fail("big_number_dto_zero_invalid", path)
            return
        if not allow_negative and self.sign < 0:
            _fail("big_number_dto_negative", path)
        if self.coeff < 1_000 or self.coeff > 9_999:
            _fail("big_number_dto_not_canonical", path)

    def to_dict(self) -> dict[str, int]:
        self.validate()
        return {"sign": self.sign, "coeff": self.coeff, "exp": self.exp}

    def to_sim_number(self) -> SimNumber:
        self.validate()
        if self.sign == 0:
            return SimNumber.zero()
        prefix = "-" if self.sign < 0 else ""
        return SimNumber.parse(f"{prefix}{self.coeff}e{self.exp}")

    def to_decimal_string(self) -> str:
        self.validate()
        if self.sign == 0:
            return "0"
        prefix = "-" if self.sign < 0 else ""
        exponent = f"+{self.exp}" if self.exp >= 0 else str(self.exp)
        return f"{prefix}{self.coeff}E{exponent}"


@dataclass
class ArchiveMeta:
    created_at: int
    revision: int = 0


@dataclass
class ProductionState:
    last_settled_at: int


@dataclass
class WalletState:
    money: BigNumberDTO = field(default_factory=BigNumberDTO.zero)
    material: BigNumberDTO = field(default_factory=BigNumberDTO.zero)
    strength: BigNumberDTO = field(default_factory=BigNumberDTO.zero)


@dataclass
class TorpedoState:
    selected_id: int = 0
    owned_ids: list[int] = field(default_factory=list)


@dataclass
class OwnedBarbell:
    barbell_id: int
    count: int


@dataclass
class BarbellState:
    equipped_id: int = 0
    owned: list[OwnedBarbell] = field(default_factory=list)


@dataclass
class FishHallState:
    upgrade_level: int = 0


@dataclass
class FishInstance:
    instance_id: int
    fish_id: int
    mutation_id: int
    level: int
    weight_gram: int
    hall_slot: int = 0


@dataclass
class FishInventory:
    next_instance_id: int = 1
    items: list[FishInstance] = field(default_factory=list)


@dataclass
class TrashManUpgrade:
    upgrade_id: int
    level: int


@dataclass
class BreakthroughState:
    active: bool = False
    target_realm_id: int = 0
    progress_seconds: int = 0


@dataclass
class TrashStock:
    trash_id: int
    count: int


@dataclass
class TrashProcessingState:
    active_trash_id: int = 0
    active_progress_seconds: int = 0
    stocks: list[TrashStock] = field(default_factory=list)


@dataclass
class TrashManState:
    realm_id: int = 0
    highest_realm_id: int = 0
    upgrades: list[TrashManUpgrade] = field(default_factory=list)
    training_progress_seconds: int = 0
    breakthrough: BreakthroughState = field(default_factory=BreakthroughState)
    processing: TrashProcessingState = field(default_factory=TrashProcessingState)


@dataclass
class RebirthState:
    strength_completed_count: int = 0
    trash_man_completed_count: int = 0


@dataclass
class CollectionState:
    unlocked_keys: list[str] = field(default_factory=list)
    viewed_keys: list[str] = field(default_factory=list)
    claimed_reward_ids: list[int] = field(default_factory=list)


@dataclass
class AutomationState:
    auto_throw_unlocked: bool = False
    auto_throw_enabled: bool = False


@dataclass
class StatisticsState:
    total_throws: int = 0
    total_fish_caught: int = 0
    max_distance_cm: int = 0


@dataclass
class PlayerState:
    """Fish Oasis persistent player facts, excluding all derived values."""

    meta: ArchiveMeta
    production: ProductionState
    wallet: WalletState = field(default_factory=WalletState)
    torpedo: TorpedoState = field(default_factory=TorpedoState)
    barbell: BarbellState = field(default_factory=BarbellState)
    fish_hall: FishHallState = field(default_factory=FishHallState)
    fish: FishInventory = field(default_factory=FishInventory)
    trash_man: TrashManState = field(default_factory=TrashManState)
    rebirth: RebirthState = field(default_factory=RebirthState)
    collection: CollectionState = field(default_factory=CollectionState)
    automation: AutomationState = field(default_factory=AutomationState)
    statistics: StatisticsState = field(default_factory=StatisticsState)

    @classmethod
    def new(
        cls,
        server_unix_seconds: int = 0,
        *,
        initial_torpedo_id: int = 0,
        initial_strength: BigNumberDTO | SimNumber | Decimal | int | str = 0,
        initial_trash_man_realm_id: int = 0,
    ) -> "PlayerState":
        if type(server_unix_seconds) is not int:
            _fail("archive_schema_invalid_value", "meta.createdAt")
        if type(initial_torpedo_id) is not int or initial_torpedo_id < 0:
            _fail("archive_schema_invalid_value", "torpedo.selectedId")
        if (
            type(initial_trash_man_realm_id) is not int
            or initial_trash_man_realm_id < 0
        ):
            _fail("archive_schema_invalid_value", "trashMan.realmId")
        now = max(server_unix_seconds, 0)
        state = cls(
            meta=ArchiveMeta(created_at=now),
            production=ProductionState(last_settled_at=now),
            wallet=WalletState(
                strength=BigNumberDTO.from_value(
                    initial_strength,
                    allow_negative=False,
                )
            ),
            torpedo=TorpedoState(
                selected_id=initial_torpedo_id,
                owned_ids=(
                    [] if initial_torpedo_id == 0 else [initial_torpedo_id]
                ),
            ),
            trash_man=TrashManState(
                realm_id=initial_trash_man_realm_id,
                highest_realm_id=initial_trash_man_realm_id,
            ),
        )
        state.validate(FishStateValidationContext(now=now))
        return state

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
        *,
        context: FishStateValidationContext | None = None,
    ) -> "PlayerState":
        from .fish_state_parse import player_state_from_dict

        return player_state_from_dict(value, context=context, state_type=cls)

    def validate(
        self,
        context: FishStateValidationContext | None = None,
    ) -> None:
        from .fish_state_validation import validate_player_state

        validate_player_state(self, context=context)

    def to_dict(
        self,
        *,
        context: FishStateValidationContext | None = None,
    ) -> dict[str, Any]:
        from .fish_state_serialization import player_state_to_dict

        return player_state_to_dict(self, context=context)

    def copy(self) -> "PlayerState":
        return PlayerState.from_dict(self.to_dict())


def _fail(code: str, path: str, detail: object | None = None) -> None:
    raise FishStateValidationError(code, path, detail)


def _expect_object(value: object, path: str) -> dict[str, Any]:
    if type(value) is not dict or any(not isinstance(key, str) for key in value):
        _fail("archive_schema_invalid_type", path)
    return value


def _expect_array(value: object, path: str) -> list[Any]:
    if type(value) is not list:
        _fail("archive_schema_array_invalid", path)
    return value


def _expect_state_list(value: object, path: str) -> list[Any]:
    if type(value) is not list:
        _fail("archive_schema_array_invalid", path)
    return value


def _expect_keys(
    value: Mapping[str, Any],
    expected: set[str],
    path: str,
) -> None:
    actual = set(value)
    if actual != expected:
        _fail(
            "archive_schema_keys_invalid",
            path,
            {
                "missing": sorted(expected - actual),
                "extra": sorted(actual - expected),
            },
        )


def _expect_int(value: object, path: str) -> int:
    if type(value) is not int:
        _fail("archive_schema_invalid_value", path)
    return value


def _expect_bool(value: object, path: str) -> bool:
    if type(value) is not bool:
        _fail("archive_schema_invalid_type", path)
    return value


def _expect_string(value: object, path: str) -> str:
    if not isinstance(value, str):
        _fail("archive_schema_invalid_value", path)
    return value


def _expect_nonnegative_int(value: object, path: str) -> int:
    parsed = _expect_int(value, path)
    if parsed < 0:
        _fail("archive_schema_invalid_value", path)
    return parsed


def _expect_positive_int(value: object, path: str) -> int:
    parsed = _expect_int(value, path)
    if parsed < 1:
        _fail("archive_schema_invalid_value", path)
    return parsed
