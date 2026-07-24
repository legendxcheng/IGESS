from __future__ import annotations

import re
from typing import Any

from .fish_state_model import (
    ArchiveMeta,
    AutomationState,
    BarbellState,
    BigNumberDTO,
    BreakthroughState,
    CollectionState,
    FISH_MAX_LEVEL,
    FishHallState,
    FishInstance,
    FishInventory,
    FishStateValidationContext,
    FishStateValidationError,
    OwnedBarbell,
    PlayerState,
    ProductionState,
    RebirthState,
    StatisticsState,
    TorpedoState,
    TrashManState,
    TrashManUpgrade,
    TrashProcessingState,
    TrashStock,
    WalletState,
    _expect_int,
    _expect_nonnegative_int,
    _expect_positive_int,
    _expect_state_list,
    _fail,
)

_COLLECTION_KEY_RE = re.compile(r"^\d+:\d+$")


def validate_player_state(
    self: PlayerState,
    *,
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
