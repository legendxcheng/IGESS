from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Mapping

from .checkpoint import CheckpointCodec, SimulationCheckpoint
from .numbers import SimNumber


FISH_ENGINE_ID = "fish"
FISH_ARCHIVE_VERSION = 1
FISH_MAX_LEVEL = 100
MAX_BIG_NUMBER_EXPONENT = 1_000_000
DEFAULT_MAX_FUTURE_SECONDS = 300
_COLLECTION_KEY_RE = re.compile(r"^\d+:\d+$")

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
        payload = _expect_object(value, "$")
        _expect_keys(
            payload,
            {
                "meta",
                "production",
                "wallet",
                "torpedo",
                "barbell",
                "fishHall",
                "fish",
                "trashMan",
                "rebirth",
                "collection",
                "automation",
                "statistics",
            },
            "$",
        )

        meta = _expect_object(payload["meta"], "meta")
        _expect_keys(meta, {"createdAt", "revision"}, "meta")
        production = _expect_object(payload["production"], "production")
        _expect_keys(production, {"lastSettledAt"}, "production")
        wallet = _expect_object(payload["wallet"], "wallet")
        _expect_keys(wallet, {"money", "material", "strength"}, "wallet")
        torpedo = _expect_object(payload["torpedo"], "torpedo")
        _expect_keys(torpedo, {"selectedId", "ownedIds"}, "torpedo")
        barbell = _expect_object(payload["barbell"], "barbell")
        _expect_keys(barbell, {"equippedId", "owned"}, "barbell")
        fish_hall = _expect_object(payload["fishHall"], "fishHall")
        _expect_keys(fish_hall, {"upgradeLevel"}, "fishHall")
        fish = _expect_object(payload["fish"], "fish")
        _expect_keys(fish, {"nextInstanceId", "items"}, "fish")
        trash_man = _expect_object(payload["trashMan"], "trashMan")
        _expect_keys(
            trash_man,
            {
                "realmId",
                "highestRealmId",
                "upgrades",
                "trainingProgressSeconds",
                "breakthrough",
                "processing",
            },
            "trashMan",
        )
        breakthrough = _expect_object(
            trash_man["breakthrough"],
            "trashMan.breakthrough",
        )
        _expect_keys(
            breakthrough,
            {"active", "targetRealmId", "progressSeconds"},
            "trashMan.breakthrough",
        )
        processing = _expect_object(
            trash_man["processing"],
            "trashMan.processing",
        )
        _expect_keys(
            processing,
            {"activeTrashId", "activeProgressSeconds", "stocks"},
            "trashMan.processing",
        )
        rebirth = _expect_object(payload["rebirth"], "rebirth")
        _expect_keys(
            rebirth,
            {"strengthCompletedCount", "trashManCompletedCount"},
            "rebirth",
        )
        collection = _expect_object(payload["collection"], "collection")
        _expect_keys(
            collection,
            {"unlockedKeys", "viewedKeys", "claimedRewardIds"},
            "collection",
        )
        automation = _expect_object(payload["automation"], "automation")
        _expect_keys(
            automation,
            {"autoThrowUnlocked", "autoThrowEnabled"},
            "automation",
        )
        statistics = _expect_object(payload["statistics"], "statistics")
        _expect_keys(
            statistics,
            {"totalThrows", "totalFishCaught", "maxDistanceCm"},
            "statistics",
        )

        owned_barbells: list[OwnedBarbell] = []
        for index, entry_value in enumerate(
            _expect_array(barbell["owned"], "barbell.owned"),
            start=1,
        ):
            path = f"barbell.owned[{index}]"
            entry = _expect_object(entry_value, path)
            _expect_keys(entry, {"barbellId", "count"}, path)
            owned_barbells.append(
                OwnedBarbell(
                    barbell_id=_expect_int(entry["barbellId"], f"{path}.barbellId"),
                    count=_expect_int(entry["count"], f"{path}.count"),
                )
            )

        fish_items: list[FishInstance] = []
        for index, item_value in enumerate(
            _expect_array(fish["items"], "fish.items"),
            start=1,
        ):
            path = f"fish.items[{index}]"
            item = _expect_object(item_value, path)
            _expect_keys(
                item,
                {
                    "instanceId",
                    "fishId",
                    "mutationId",
                    "level",
                    "weightGram",
                    "hallSlot",
                },
                path,
            )
            fish_items.append(
                FishInstance(
                    instance_id=_expect_int(item["instanceId"], f"{path}.instanceId"),
                    fish_id=_expect_int(item["fishId"], f"{path}.fishId"),
                    mutation_id=_expect_int(
                        item["mutationId"],
                        f"{path}.mutationId",
                    ),
                    level=_expect_int(item["level"], f"{path}.level"),
                    weight_gram=_expect_int(
                        item["weightGram"],
                        f"{path}.weightGram",
                    ),
                    hall_slot=_expect_int(item["hallSlot"], f"{path}.hallSlot"),
                )
            )

        upgrades: list[TrashManUpgrade] = []
        for index, entry_value in enumerate(
            _expect_array(trash_man["upgrades"], "trashMan.upgrades"),
            start=1,
        ):
            path = f"trashMan.upgrades[{index}]"
            entry = _expect_object(entry_value, path)
            _expect_keys(entry, {"upgradeId", "level"}, path)
            upgrades.append(
                TrashManUpgrade(
                    upgrade_id=_expect_int(entry["upgradeId"], f"{path}.upgradeId"),
                    level=_expect_int(entry["level"], f"{path}.level"),
                )
            )

        stocks: list[TrashStock] = []
        for index, entry_value in enumerate(
            _expect_array(processing["stocks"], "trashMan.processing.stocks"),
            start=1,
        ):
            path = f"trashMan.processing.stocks[{index}]"
            entry = _expect_object(entry_value, path)
            _expect_keys(entry, {"trashId", "count"}, path)
            stocks.append(
                TrashStock(
                    trash_id=_expect_int(entry["trashId"], f"{path}.trashId"),
                    count=_expect_int(entry["count"], f"{path}.count"),
                )
            )

        state = cls(
            meta=ArchiveMeta(
                created_at=_expect_int(meta["createdAt"], "meta.createdAt"),
                revision=_expect_int(meta["revision"], "meta.revision"),
            ),
            production=ProductionState(
                last_settled_at=_expect_int(
                    production["lastSettledAt"],
                    "production.lastSettledAt",
                )
            ),
            wallet=WalletState(
                money=BigNumberDTO.from_dict(
                    wallet["money"],
                    path="wallet.money",
                    allow_negative=False,
                ),
                material=BigNumberDTO.from_dict(
                    wallet["material"],
                    path="wallet.material",
                    allow_negative=False,
                ),
                strength=BigNumberDTO.from_dict(
                    wallet["strength"],
                    path="wallet.strength",
                    allow_negative=False,
                ),
            ),
            torpedo=TorpedoState(
                selected_id=_expect_int(
                    torpedo["selectedId"],
                    "torpedo.selectedId",
                ),
                owned_ids=[
                    _expect_int(item, f"torpedo.ownedIds[{index}]")
                    for index, item in enumerate(
                        _expect_array(torpedo["ownedIds"], "torpedo.ownedIds"),
                        start=1,
                    )
                ],
            ),
            barbell=BarbellState(
                equipped_id=_expect_int(
                    barbell["equippedId"],
                    "barbell.equippedId",
                ),
                owned=owned_barbells,
            ),
            fish_hall=FishHallState(
                upgrade_level=_expect_int(
                    fish_hall["upgradeLevel"],
                    "fishHall.upgradeLevel",
                )
            ),
            fish=FishInventory(
                next_instance_id=_expect_int(
                    fish["nextInstanceId"],
                    "fish.nextInstanceId",
                ),
                items=fish_items,
            ),
            trash_man=TrashManState(
                realm_id=_expect_int(trash_man["realmId"], "trashMan.realmId"),
                highest_realm_id=_expect_int(
                    trash_man["highestRealmId"],
                    "trashMan.highestRealmId",
                ),
                upgrades=upgrades,
                training_progress_seconds=_expect_int(
                    trash_man["trainingProgressSeconds"],
                    "trashMan.trainingProgressSeconds",
                ),
                breakthrough=BreakthroughState(
                    active=_expect_bool(
                        breakthrough["active"],
                        "trashMan.breakthrough.active",
                    ),
                    target_realm_id=_expect_int(
                        breakthrough["targetRealmId"],
                        "trashMan.breakthrough.targetRealmId",
                    ),
                    progress_seconds=_expect_int(
                        breakthrough["progressSeconds"],
                        "trashMan.breakthrough.progressSeconds",
                    ),
                ),
                processing=TrashProcessingState(
                    active_trash_id=_expect_int(
                        processing["activeTrashId"],
                        "trashMan.processing.activeTrashId",
                    ),
                    active_progress_seconds=_expect_int(
                        processing["activeProgressSeconds"],
                        "trashMan.processing.activeProgressSeconds",
                    ),
                    stocks=stocks,
                ),
            ),
            rebirth=RebirthState(
                strength_completed_count=_expect_int(
                    rebirth["strengthCompletedCount"],
                    "rebirth.strengthCompletedCount",
                ),
                trash_man_completed_count=_expect_int(
                    rebirth["trashManCompletedCount"],
                    "rebirth.trashManCompletedCount",
                ),
            ),
            collection=CollectionState(
                unlocked_keys=[
                    _expect_string(item, f"collection.unlockedKeys[{index}]")
                    for index, item in enumerate(
                        _expect_array(
                            collection["unlockedKeys"],
                            "collection.unlockedKeys",
                        ),
                        start=1,
                    )
                ],
                viewed_keys=[
                    _expect_string(item, f"collection.viewedKeys[{index}]")
                    for index, item in enumerate(
                        _expect_array(
                            collection["viewedKeys"],
                            "collection.viewedKeys",
                        ),
                        start=1,
                    )
                ],
                claimed_reward_ids=[
                    _expect_int(item, f"collection.claimedRewardIds[{index}]")
                    for index, item in enumerate(
                        _expect_array(
                            collection["claimedRewardIds"],
                            "collection.claimedRewardIds",
                        ),
                        start=1,
                    )
                ],
            ),
            automation=AutomationState(
                auto_throw_unlocked=_expect_bool(
                    automation["autoThrowUnlocked"],
                    "automation.autoThrowUnlocked",
                ),
                auto_throw_enabled=_expect_bool(
                    automation["autoThrowEnabled"],
                    "automation.autoThrowEnabled",
                ),
            ),
            statistics=StatisticsState(
                total_throws=_expect_int(
                    statistics["totalThrows"],
                    "statistics.totalThrows",
                ),
                total_fish_caught=_expect_int(
                    statistics["totalFishCaught"],
                    "statistics.totalFishCaught",
                ),
                max_distance_cm=_expect_int(
                    statistics["maxDistanceCm"],
                    "statistics.maxDistanceCm",
                ),
            ),
        )
        state.validate(context)
        return state

    def validate(
        self,
        context: FishStateValidationContext | None = None,
    ) -> None:
        context = context or FishStateValidationContext()
        _validate_context(context)
        for value, expected_type, path in (
            (self.meta, ArchiveMeta, "meta"),
            (self.production, ProductionState, "production"),
            (self.wallet, WalletState, "wallet"),
            (self.torpedo, TorpedoState, "torpedo"),
            (self.barbell, BarbellState, "barbell"),
            (self.fish_hall, FishHallState, "fishHall"),
            (self.fish, FishInventory, "fish"),
            (self.trash_man, TrashManState, "trashMan"),
            (self.rebirth, RebirthState, "rebirth"),
            (self.collection, CollectionState, "collection"),
            (self.automation, AutomationState, "automation"),
            (self.statistics, StatisticsState, "statistics"),
        ):
            if not isinstance(value, expected_type):
                _fail("archive_schema_invalid_type", path)
        _validate_timestamp(self.meta.created_at, "meta.createdAt", context)
        _expect_nonnegative_int(self.meta.revision, "meta.revision")
        _validate_timestamp(
            self.production.last_settled_at,
            "production.lastSettledAt",
            context,
        )
        if (
            self.meta.created_at > 0
            and self.production.last_settled_at < self.meta.created_at
        ):
            _fail(
                "archive_schema_order_invalid",
                "production.lastSettledAt",
            )

        for name in ("money", "material", "strength"):
            value = getattr(self.wallet, name)
            if not isinstance(value, BigNumberDTO):
                _fail("archive_schema_big_number_invalid", f"wallet.{name}")
            try:
                value.validate(path=f"wallet.{name}", allow_negative=False)
            except FishStateValidationError as exc:
                raise FishStateValidationError(
                    "archive_schema_big_number_invalid",
                    f"wallet.{name}",
                    exc.code,
                ) from exc

        _validate_id(
            self.torpedo.selected_id,
            "torpedo",
            "torpedo.selectedId",
            context,
            allow_zero=True,
        )
        owned_torpedoes = _validate_unique_ids(
            self.torpedo.owned_ids,
            "torpedo.ownedIds",
            "torpedo",
            context,
        )
        if (
            self.torpedo.selected_id != 0
            and self.torpedo.selected_id not in owned_torpedoes
        ):
            _fail("archive_schema_reference_missing", "torpedo.selectedId")

        _validate_id(
            self.barbell.equipped_id,
            "barbell",
            "barbell.equippedId",
            context,
            allow_zero=True,
        )
        _expect_state_list(self.barbell.owned, "barbell.owned")
        owned_barbells: set[int] = set()
        for index, entry in enumerate(self.barbell.owned, start=1):
            path = f"barbell.owned[{index}]"
            if not isinstance(entry, OwnedBarbell):
                _fail("archive_schema_invalid_type", path)
            _validate_id(
                entry.barbell_id,
                "barbell",
                f"{path}.barbellId",
                context,
            )
            _expect_positive_int(entry.count, f"{path}.count")
            if entry.barbell_id in owned_barbells:
                _fail("archive_schema_duplicate_id", f"{path}.barbellId")
            owned_barbells.add(entry.barbell_id)
        if (
            self.barbell.equipped_id != 0
            and self.barbell.equipped_id not in owned_barbells
        ):
            _fail("archive_schema_reference_missing", "barbell.equippedId")

        _expect_nonnegative_int(
            self.fish_hall.upgrade_level,
            "fishHall.upgradeLevel",
        )
        capacity = _resolve_hall_capacity(context, self.fish_hall.upgrade_level)
        _expect_positive_int(self.fish.next_instance_id, "fish.nextInstanceId")
        _expect_state_list(self.fish.items, "fish.items")
        instance_ids: set[int] = set()
        hall_slots: set[int] = set()
        highest_instance_id = 0
        for index, item in enumerate(self.fish.items, start=1):
            path = f"fish.items[{index}]"
            if not isinstance(item, FishInstance):
                _fail("archive_schema_invalid_type", path)
            _expect_positive_int(item.instance_id, f"{path}.instanceId")
            if item.instance_id in instance_ids:
                _fail("archive_schema_duplicate_id", f"{path}.instanceId")
            instance_ids.add(item.instance_id)
            highest_instance_id = max(highest_instance_id, item.instance_id)
            _validate_id(
                item.fish_id,
                "fish",
                f"{path}.fishId",
                context,
            )
            _validate_id(
                item.mutation_id,
                "mutation",
                f"{path}.mutationId",
                context,
            )
            _expect_positive_int(item.level, f"{path}.level")
            if item.level > FISH_MAX_LEVEL:
                _fail("archive_schema_invalid_value", f"{path}.level")
            _expect_positive_int(item.weight_gram, f"{path}.weightGram")
            _expect_nonnegative_int(item.hall_slot, f"{path}.hallSlot")
            if item.hall_slot > 0:
                if item.hall_slot in hall_slots:
                    _fail("archive_schema_duplicate_slot", f"{path}.hallSlot")
                if capacity is not None and item.hall_slot > capacity:
                    _fail("archive_schema_capacity_exceeded", f"{path}.hallSlot")
                hall_slots.add(item.hall_slot)
        if self.fish.next_instance_id <= highest_instance_id:
            _fail("archive_schema_next_id_invalid", "fish.nextInstanceId")

        _validate_id(
            self.trash_man.realm_id,
            "trashManRealm",
            "trashMan.realmId",
            context,
            allow_zero=True,
        )
        _validate_id(
            self.trash_man.highest_realm_id,
            "trashManRealm",
            "trashMan.highestRealmId",
            context,
            allow_zero=True,
        )
        if self.trash_man.realm_id > self.trash_man.highest_realm_id:
            _fail("archive_schema_order_invalid", "trashMan.realmId")
        _expect_nonnegative_int(
            self.trash_man.training_progress_seconds,
            "trashMan.trainingProgressSeconds",
        )

        _expect_state_list(self.trash_man.upgrades, "trashMan.upgrades")
        upgrade_ids: set[int] = set()
        for index, upgrade in enumerate(self.trash_man.upgrades, start=1):
            path = f"trashMan.upgrades[{index}]"
            if not isinstance(upgrade, TrashManUpgrade):
                _fail("archive_schema_invalid_type", path)
            _validate_id(
                upgrade.upgrade_id,
                "trashManUpgrade",
                f"{path}.upgradeId",
                context,
            )
            _expect_positive_int(upgrade.level, f"{path}.level")
            if upgrade.upgrade_id in upgrade_ids:
                _fail("archive_schema_duplicate_id", f"{path}.upgradeId")
            upgrade_ids.add(upgrade.upgrade_id)

        breakthrough = self.trash_man.breakthrough
        if not isinstance(breakthrough, BreakthroughState):
            _fail("archive_schema_invalid_type", "trashMan.breakthrough")
        if not isinstance(breakthrough.active, bool):
            _fail(
                "archive_schema_invalid_type",
                "trashMan.breakthrough.active",
            )
        _validate_id(
            breakthrough.target_realm_id,
            "trashManRealm",
            "trashMan.breakthrough.targetRealmId",
            context,
            allow_zero=True,
        )
        _expect_nonnegative_int(
            breakthrough.progress_seconds,
            "trashMan.breakthrough.progressSeconds",
        )
        if breakthrough.active and breakthrough.target_realm_id == 0:
            _fail(
                "archive_schema_reference_missing",
                "trashMan.breakthrough.targetRealmId",
            )

        processing = self.trash_man.processing
        if not isinstance(processing, TrashProcessingState):
            _fail("archive_schema_invalid_type", "trashMan.processing")
        _validate_id(
            processing.active_trash_id,
            "trash",
            "trashMan.processing.activeTrashId",
            context,
            allow_zero=True,
        )
        _expect_nonnegative_int(
            processing.active_progress_seconds,
            "trashMan.processing.activeProgressSeconds",
        )
        _expect_state_list(processing.stocks, "trashMan.processing.stocks")
        stock_ids: set[int] = set()
        for index, stock in enumerate(processing.stocks, start=1):
            path = f"trashMan.processing.stocks[{index}]"
            if not isinstance(stock, TrashStock):
                _fail("archive_schema_invalid_type", path)
            _validate_id(
                stock.trash_id,
                "trash",
                f"{path}.trashId",
                context,
            )
            _expect_positive_int(stock.count, f"{path}.count")
            if stock.trash_id in stock_ids:
                _fail("archive_schema_duplicate_id", f"{path}.trashId")
            stock_ids.add(stock.trash_id)

        _expect_nonnegative_int(
            self.rebirth.strength_completed_count,
            "rebirth.strengthCompletedCount",
        )
        _expect_nonnegative_int(
            self.rebirth.trash_man_completed_count,
            "rebirth.trashManCompletedCount",
        )

        unlocked = _validate_collection_keys(
            self.collection.unlocked_keys,
            "collection.unlockedKeys",
        )
        viewed = _validate_collection_keys(
            self.collection.viewed_keys,
            "collection.viewedKeys",
        )
        missing_viewed = sorted(viewed - unlocked)
        if missing_viewed:
            _fail(
                "archive_schema_reference_missing",
                "collection.viewedKeys",
                missing_viewed[0],
            )
        _validate_unique_ids(
            self.collection.claimed_reward_ids,
            "collection.claimedRewardIds",
            "collectionReward",
            context,
        )

        if not isinstance(self.automation.auto_throw_unlocked, bool):
            _fail(
                "archive_schema_invalid_type",
                "automation.autoThrowUnlocked",
            )
        if not isinstance(self.automation.auto_throw_enabled, bool):
            _fail(
                "archive_schema_invalid_type",
                "automation.autoThrowEnabled",
            )
        if (
            self.automation.auto_throw_enabled
            and not self.automation.auto_throw_unlocked
        ):
            _fail(
                "archive_schema_reference_missing",
                "automation.autoThrowEnabled",
            )

        _expect_nonnegative_int(
            self.statistics.total_throws,
            "statistics.totalThrows",
        )
        _expect_nonnegative_int(
            self.statistics.total_fish_caught,
            "statistics.totalFishCaught",
        )
        _expect_nonnegative_int(
            self.statistics.max_distance_cm,
            "statistics.maxDistanceCm",
        )

    def to_dict(
        self,
        *,
        context: FishStateValidationContext | None = None,
    ) -> dict[str, Any]:
        self.validate(context)
        return {
            "meta": {
                "createdAt": self.meta.created_at,
                "revision": self.meta.revision,
            },
            "production": {
                "lastSettledAt": self.production.last_settled_at,
            },
            "wallet": {
                "money": self.wallet.money.to_dict(),
                "material": self.wallet.material.to_dict(),
                "strength": self.wallet.strength.to_dict(),
            },
            "torpedo": {
                "selectedId": self.torpedo.selected_id,
                "ownedIds": sorted(self.torpedo.owned_ids),
            },
            "barbell": {
                "equippedId": self.barbell.equipped_id,
                "owned": [
                    {"barbellId": entry.barbell_id, "count": entry.count}
                    for entry in sorted(
                        self.barbell.owned,
                        key=lambda entry: entry.barbell_id,
                    )
                ],
            },
            "fishHall": {
                "upgradeLevel": self.fish_hall.upgrade_level,
            },
            "fish": {
                "nextInstanceId": self.fish.next_instance_id,
                "items": [
                    {
                        "instanceId": item.instance_id,
                        "fishId": item.fish_id,
                        "mutationId": item.mutation_id,
                        "level": item.level,
                        "weightGram": item.weight_gram,
                        "hallSlot": item.hall_slot,
                    }
                    for item in sorted(
                        self.fish.items,
                        key=lambda item: item.instance_id,
                    )
                ],
            },
            "trashMan": {
                "realmId": self.trash_man.realm_id,
                "highestRealmId": self.trash_man.highest_realm_id,
                "upgrades": [
                    {
                        "upgradeId": upgrade.upgrade_id,
                        "level": upgrade.level,
                    }
                    for upgrade in sorted(
                        self.trash_man.upgrades,
                        key=lambda upgrade: upgrade.upgrade_id,
                    )
                ],
                "trainingProgressSeconds": (
                    self.trash_man.training_progress_seconds
                ),
                "breakthrough": {
                    "active": self.trash_man.breakthrough.active,
                    "targetRealmId": (
                        self.trash_man.breakthrough.target_realm_id
                    ),
                    "progressSeconds": (
                        self.trash_man.breakthrough.progress_seconds
                    ),
                },
                "processing": {
                    "activeTrashId": (
                        self.trash_man.processing.active_trash_id
                    ),
                    "activeProgressSeconds": (
                        self.trash_man.processing.active_progress_seconds
                    ),
                    "stocks": [
                        {"trashId": stock.trash_id, "count": stock.count}
                        for stock in sorted(
                            self.trash_man.processing.stocks,
                            key=lambda stock: stock.trash_id,
                        )
                    ],
                },
            },
            "rebirth": {
                "strengthCompletedCount": (
                    self.rebirth.strength_completed_count
                ),
                "trashManCompletedCount": (
                    self.rebirth.trash_man_completed_count
                ),
            },
            "collection": {
                "unlockedKeys": sorted(self.collection.unlocked_keys),
                "viewedKeys": sorted(self.collection.viewed_keys),
                "claimedRewardIds": sorted(
                    self.collection.claimed_reward_ids
                ),
            },
            "automation": {
                "autoThrowUnlocked": self.automation.auto_throw_unlocked,
                "autoThrowEnabled": self.automation.auto_throw_enabled,
            },
            "statistics": {
                "totalThrows": self.statistics.total_throws,
                "totalFishCaught": self.statistics.total_fish_caught,
                "maxDistanceCm": self.statistics.max_distance_cm,
            },
        }

    def copy(self) -> "PlayerState":
        return PlayerState.from_dict(self.to_dict())


@dataclass
class FishArchiveEnvelope:
    data: PlayerState
    version: int = FISH_ARCHIVE_VERSION

    def validate(
        self,
        context: FishStateValidationContext | None = None,
    ) -> None:
        if type(self.version) is not int or self.version != FISH_ARCHIVE_VERSION:
            _fail("archive_version_unsupported", "version", self.version)
        self.data.validate(context)

    def to_dict(
        self,
        *,
        context: FishStateValidationContext | None = None,
    ) -> dict[str, Any]:
        self.validate(context)
        return {
            "version": self.version,
            "data": self.data.to_dict(context=context),
        }


class FishArchiveCodec:
    """Codec for the real ProjectSaveCodec ``{version, data}`` shape."""

    @staticmethod
    def dumps(
        value: FishArchiveEnvelope | PlayerState,
        *,
        context: FishStateValidationContext | None = None,
    ) -> str:
        envelope = (
            value
            if isinstance(value, FishArchiveEnvelope)
            else FishArchiveEnvelope(data=value)
        )
        return (
            json.dumps(
                envelope.to_dict(context=context),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            + "\n"
        )

    @staticmethod
    def loads(
        text: str,
        *,
        context: FishStateValidationContext | None = None,
    ) -> FishArchiveEnvelope:
        if not isinstance(text, str):
            _fail("archive_schema_invalid_type", "$")
        try:
            payload = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
        except FishStateValidationError:
            raise
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise FishStateValidationError(
                "archive_json_invalid",
                "$",
                str(exc),
            ) from exc
        document = _expect_object(payload, "$")
        _expect_keys(document, {"version", "data"}, "$")
        version = _expect_int(document["version"], "version")
        if version != FISH_ARCHIVE_VERSION:
            _fail("archive_version_unsupported", "version", version)
        return FishArchiveEnvelope(
            version=version,
            data=PlayerState.from_dict(document["data"], context=context),
        )


class FishCheckpointCodec:
    """Bridge between the engine-neutral checkpoint and Fish PlayerState."""

    @staticmethod
    def new(
        state: PlayerState,
        *,
        model_digest: str,
        scenario_id: str,
        profile_id: str,
        root_random_seed: int,
        simulated_time_seconds: int = 0,
        next_throw_id: int | None = None,
        event_counters: Mapping[str, int] | None = None,
        behavior_state: Mapping[str, Any] | None = None,
        engine_runtime_state: Mapping[str, Any] | None = None,
        context: FishStateValidationContext | None = None,
    ) -> SimulationCheckpoint:
        return SimulationCheckpoint(
            engine_id=FISH_ENGINE_ID,
            model_digest=model_digest,
            scenario_id=scenario_id,
            profile_id=profile_id,
            simulated_time_seconds=simulated_time_seconds,
            root_random_seed=root_random_seed,
            next_throw_id=(
                state.statistics.total_throws
                if next_throw_id is None
                else next_throw_id
            ),
            event_counters=dict(event_counters or {}),
            behavior_state=dict(behavior_state or {}),
            engine_runtime_state=dict(engine_runtime_state or {}),
            engine_state=state.to_dict(context=context),
        )

    @staticmethod
    def decode_state(
        checkpoint: SimulationCheckpoint,
        *,
        expected_model_digest: str | None = None,
        context: FishStateValidationContext | None = None,
    ) -> PlayerState:
        checkpoint.validate(
            expected_engine_id=FISH_ENGINE_ID,
            expected_model_digest=expected_model_digest,
        )
        return PlayerState.from_dict(checkpoint.engine_state, context=context)

    @classmethod
    def dumps(
        cls,
        checkpoint: SimulationCheckpoint,
        *,
        expected_model_digest: str | None = None,
        context: FishStateValidationContext | None = None,
    ) -> str:
        cls.decode_state(
            checkpoint,
            expected_model_digest=expected_model_digest,
            context=context,
        )
        return CheckpointCodec.dumps(checkpoint)

    @classmethod
    def loads(
        cls,
        text: str,
        *,
        expected_model_digest: str | None = None,
        context: FishStateValidationContext | None = None,
    ) -> tuple[SimulationCheckpoint, PlayerState]:
        checkpoint = CheckpointCodec.loads(
            text,
            expected_engine_id=FISH_ENGINE_ID,
            expected_model_digest=expected_model_digest,
        )
        state = cls.decode_state(
            checkpoint,
            expected_model_digest=expected_model_digest,
            context=context,
        )
        return checkpoint, state

    @classmethod
    def write(
        cls,
        checkpoint: SimulationCheckpoint,
        path: str | Path,
        *,
        expected_model_digest: str | None = None,
        context: FishStateValidationContext | None = None,
    ) -> Path:
        cls.decode_state(
            checkpoint,
            expected_model_digest=expected_model_digest,
            context=context,
        )
        return CheckpointCodec.write(checkpoint, path)

    @classmethod
    def read(
        cls,
        path: str | Path,
        *,
        expected_model_digest: str | None = None,
        context: FishStateValidationContext | None = None,
    ) -> tuple[SimulationCheckpoint, PlayerState]:
        checkpoint = CheckpointCodec.read(
            path,
            expected_engine_id=FISH_ENGINE_ID,
            expected_model_digest=expected_model_digest,
        )
        state = cls.decode_state(
            checkpoint,
            expected_model_digest=expected_model_digest,
            context=context,
        )
        return checkpoint, state


def normalize_player_state(
    value: Mapping[str, Any],
    *,
    now: int = 0,
    context: FishStateValidationContext | None = None,
) -> tuple[PlayerState, bool]:
    """Fill missing v1 fields only for new archives or explicit migrations."""

    payload = _deep_copy_plain(_expect_object(value, "$"))
    defaults = PlayerState.new(now).to_dict()
    changed = _merge_missing(payload, defaults)
    effective_context = context or FishStateValidationContext(now=now)
    return PlayerState.from_dict(payload, context=effective_context), changed


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


def _validate_context(context: FishStateValidationContext) -> None:
    if context.now is not None:
        _expect_nonnegative_int(context.now, "$validation.now")
    _expect_nonnegative_int(
        context.max_future_seconds,
        "$validation.maxFutureSeconds",
    )


def _validate_timestamp(
    value: object,
    path: str,
    context: FishStateValidationContext,
) -> None:
    parsed = _expect_nonnegative_int(value, path)
    if (
        context.now is not None
        and parsed > context.now + context.max_future_seconds
    ):
        _fail("archive_schema_time_in_future", path)


def _validate_id(
    value: object,
    category: str,
    path: str,
    context: FishStateValidationContext,
    *,
    allow_zero: bool = False,
) -> int:
    parsed = _expect_int(value, path)
    minimum = 0 if allow_zero else 1
    if parsed < minimum:
        _fail("archive_schema_invalid_value", path)
    if parsed == 0 or context.id_exists is None:
        return parsed
    try:
        exists = context.id_exists(category, parsed)
    except Exception as exc:
        raise FishStateValidationError(
            "archive_schema_validator_exception",
            path,
            str(exc),
        ) from exc
    if exists is not True:
        _fail("archive_schema_unknown_id", path, category)
    return parsed


def _validate_unique_ids(
    values: object,
    path: str,
    category: str,
    context: FishStateValidationContext,
) -> set[int]:
    if type(values) is not list:
        _fail("archive_schema_array_invalid", path)
    seen: set[int] = set()
    for index, value in enumerate(values, start=1):
        item_path = f"{path}[{index}]"
        parsed = _validate_id(value, category, item_path, context)
        if parsed in seen:
            _fail("archive_schema_duplicate_id", item_path)
        seen.add(parsed)
    return seen


def _resolve_hall_capacity(
    context: FishStateValidationContext,
    upgrade_level: int,
) -> int | None:
    if context.fish_hall_capacity is None:
        return None
    try:
        capacity = context.fish_hall_capacity(upgrade_level)
    except Exception as exc:
        raise FishStateValidationError(
            "archive_schema_validator_exception",
            "fishHall.upgradeLevel",
            str(exc),
        ) from exc
    if type(capacity) is not int or capacity < 0:
        _fail(
            "archive_schema_validator_invalid",
            "fishHall.upgradeLevel",
            capacity,
        )
    return capacity


def _validate_collection_keys(values: object, path: str) -> set[str]:
    if type(values) is not list:
        _fail("archive_schema_array_invalid", path)
    seen: set[str] = set()
    for index, value in enumerate(values, start=1):
        item_path = f"{path}[{index}]"
        if (
            not isinstance(value, str)
            or _COLLECTION_KEY_RE.fullmatch(value) is None
        ):
            _fail("archive_schema_invalid_value", item_path)
        if value in seen:
            _fail("archive_schema_duplicate_id", item_path)
        seen.add(value)
    return seen


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail("archive_duplicate_key", "$", key)
        result[key] = value
    return result


def _deep_copy_plain(value: Any) -> Any:
    if type(value) is dict:
        return {key: _deep_copy_plain(item) for key, item in value.items()}
    if type(value) is list:
        return [_deep_copy_plain(item) for item in value]
    if value is None or type(value) in {bool, int, str}:
        return value
    if type(value) is float and math.isfinite(value):
        return value
    _fail("archive_schema_non_plain_data", "$")


def _merge_missing(target: dict[str, Any], defaults: dict[str, Any]) -> bool:
    changed = False
    for key, default in defaults.items():
        if key not in target:
            target[key] = _deep_copy_plain(default)
            changed = True
        elif type(target[key]) is dict and type(default) is dict:
            if _merge_missing(target[key], default):
                changed = True
    return changed
