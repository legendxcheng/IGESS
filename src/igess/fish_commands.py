from __future__ import annotations

from dataclasses import dataclass

from .fish_barbell import (
    BarbellProductionSnapshot,
    FishBarbellDataAdapter,
)
from .fish_data import FishDataError
from .fish_hall import (
    FishHallDataAdapter,
    FishHallIncomeSnapshot,
    FishIncomeTrace,
)
from .fish_state import (
    FISH_MAX_LEVEL,
    BigNumberDTO,
    FishInstance,
    OwnedBarbell,
    PlayerState,
    TrashStock,
)
from .fish_throw_data import (
    FishThrowDataAdapter,
    ProductionThrowResolution,
    ProductionThrowRequest,
)
from .numbers import SimNumber


class FishCommandError(ValueError):
    """Raised when a Fish domain command cannot be committed."""


@dataclass(frozen=True)
class AppliedThrowResolution:
    """Committed state and stable facts produced by one throw transaction."""

    state: PlayerState
    fish_instance_id: int
    trash_stock_count: int
    fish_hall: FishHallIncomeSnapshot

    def event_details(self) -> dict[str, str]:
        details = {
            "reward_application": "applied_to_player_state",
            "fish_instance_id": str(self.fish_instance_id),
            "trash_stock_count": str(self.trash_stock_count),
            "player_state_revision": str(self.state.meta.revision),
        }
        details.update(self.fish_hall.event_details(suffix="after_throw"))
        return details


@dataclass(frozen=True)
class AppliedFishHallSettlement:
    state: PlayerState
    from_time_seconds: int
    to_time_seconds: int
    elapsed_seconds: int
    money_added: SimNumber
    fish_hall: FishHallIncomeSnapshot

    def event_details(self) -> dict[str, str]:
        details = {
            "fish_hall_settlement_from_seconds": str(self.from_time_seconds),
            "fish_hall_settlement_to_seconds": str(self.to_time_seconds),
            "fish_hall_settlement_elapsed_seconds": str(self.elapsed_seconds),
            "fish_hall_money_added": self.money_added.to_decimal_string(),
        }
        details.update(self.fish_hall.event_details(suffix="before_throw"))
        return details


@dataclass(frozen=True)
class AppliedFishUpgrade:
    state: PlayerState
    instance_id: int
    from_level: int
    to_level: int
    price: SimNumber
    money_before: SimNumber
    money_after: SimNumber
    income_before: FishIncomeTrace
    income_after: FishIncomeTrace
    fish_hall_before: FishHallIncomeSnapshot
    fish_hall_after: FishHallIncomeSnapshot

    def event_details(self) -> dict[str, str]:
        details = {
            "fish_instance_id": str(self.instance_id),
            "fish_level_before": str(self.from_level),
            "fish_level_after": str(self.to_level),
            "fish_max_level": str(FISH_MAX_LEVEL),
            "fish_upgrade_price": self.price.to_decimal_string(),
            "fish_upgrade_price_formula": (
                "base_money_per_second*1.5^(current_level-1)"
            ),
            "fish_upgrade_price_uses_mutation": "false",
            "fish_income_formula": (
                "base_money_per_second*1.25^(level-1)"
                "*mutation_income_multiplier"
            ),
            "fish_income_per_second_before": (
                self.income_before.income_per_second.to_decimal_string()
            ),
            "fish_income_per_second_after": (
                self.income_after.income_per_second.to_decimal_string()
            ),
            "money_before_fish_upgrade": (
                self.money_before.to_decimal_string()
            ),
            "money_after_fish_upgrade": self.money_after.to_decimal_string(),
            "player_state_revision": str(self.state.meta.revision),
        }
        details.update(
            self.fish_hall_before.event_details(suffix="before_upgrade")
        )
        details.update(
            self.fish_hall_after.event_details(suffix="after_upgrade")
        )
        return details


@dataclass(frozen=True)
class AppliedFishHallUpgrade:
    state: PlayerState
    from_level: int
    to_level: int
    price: SimNumber
    material_before: SimNumber
    material_after: SimNumber
    max_level: int
    fish_hall_before: FishHallIncomeSnapshot
    fish_hall_after: FishHallIncomeSnapshot

    def event_details(self) -> dict[str, str]:
        details = {
            "fish_hall_upgrade_level_before": str(self.from_level),
            "fish_hall_upgrade_level_after": str(self.to_level),
            "fish_hall_upgrade_price": self.price.to_decimal_string(),
            "fish_hall_upgrade_price_resource": "material",
            "fish_hall_upgrade_price_source": (
                "tbfishhallupgrade[current_upgrade_level].upgradePrice"
            ),
            "fish_hall_upgrade_max_level": str(self.max_level),
            "fish_hall_upgrade_layout_policy": "fixed_max_income",
            "material_before_fish_hall_upgrade": (
                self.material_before.to_decimal_string()
            ),
            "material_after_fish_hall_upgrade": (
                self.material_after.to_decimal_string()
            ),
            "player_state_revision": str(self.state.meta.revision),
        }
        details.update(
            self.fish_hall_before.event_details(
                suffix="before_hall_upgrade"
            )
        )
        details.update(
            self.fish_hall_after.event_details(
                suffix="after_hall_upgrade"
            )
        )
        return details


@dataclass(frozen=True)
class AppliedStrengthRebirth:
    state: PlayerState
    from_completed_count: int
    to_completed_count: int
    strength_requirement: SimNumber
    strength_before: SimNumber
    strength_after: SimNumber
    fish_hall_before: FishHallIncomeSnapshot
    fish_hall_after: FishHallIncomeSnapshot

    def event_details(self) -> dict[str, str]:
        details = {
            "strength_rebirth_completed_count_before": str(
                self.from_completed_count
            ),
            "strength_rebirth_completed_count_after": str(
                self.to_completed_count
            ),
            "strength_rebirth_table_id": str(self.to_completed_count),
            "strength_rebirth_requirement": (
                self.strength_requirement.to_decimal_string()
            ),
            "strength_rebirth_requirement_source": (
                "tbstrengthrebirth"
                f"[id={self.to_completed_count}].strengthRequirement"
            ),
            "strength_before_rebirth": (
                self.strength_before.to_decimal_string()
            ),
            "strength_after_rebirth": (
                self.strength_after.to_decimal_string()
            ),
            "strength_rebirth_reset_fields": "wallet.strength",
            "strength_rebirth_preserved_fields": (
                "fish,trash,money,material,torpedo,barbell,fish_hall,"
                "trash_man,collection,automation,statistics"
            ),
            "strength_rebirth_multiplier_before": (
                self.fish_hall_before.strength_rebirth_multiplier
                .to_decimal_string()
            ),
            "strength_rebirth_multiplier_after": (
                self.fish_hall_after.strength_rebirth_multiplier
                .to_decimal_string()
            ),
            "strength_rebirth_multiplier_source": (
                "completed_count_0_is_default_1x_not_in_table;"
                "completed_count_n_uses_tbstrengthrebirth_id_n"
            ),
            "player_state_revision": str(self.state.meta.revision),
        }
        details.update(
            self.fish_hall_before.event_details(
                suffix="before_strength_rebirth"
            )
        )
        details.update(
            self.fish_hall_after.event_details(
                suffix="after_strength_rebirth"
            )
        )
        return details


@dataclass(frozen=True)
class AppliedBarbellSynthesis:
    state: PlayerState
    barbell_id: int
    price: SimNumber
    material_before: SimNumber
    material_after: SimNumber
    count_before: int
    count_after: int
    production_before: BarbellProductionSnapshot
    production_after: BarbellProductionSnapshot

    def event_details(self) -> dict[str, str]:
        details = {
            "barbell_id": str(self.barbell_id),
            "barbell_synthesis_price": self.price.to_decimal_string(),
            "barbell_synthesis_price_resource": "material",
            "barbell_synthesis_price_source": "tbbarbell.price",
            "barbell_count_before": str(self.count_before),
            "barbell_count_after": str(self.count_after),
            "barbell_auto_equip_policy": "highest_strength_per_second",
            "material_before_barbell_synthesis": (
                self.material_before.to_decimal_string()
            ),
            "material_after_barbell_synthesis": (
                self.material_after.to_decimal_string()
            ),
            "player_state_revision": str(self.state.meta.revision),
        }
        details.update(
            self.production_before.event_details(
                suffix="before_synthesis"
            )
        )
        details.update(
            self.production_after.event_details(
                suffix="after_synthesis"
            )
        )
        return details


@dataclass(frozen=True)
class AppliedBarbellEquip:
    state: PlayerState
    barbell_id: int
    production_before: BarbellProductionSnapshot
    production_after: BarbellProductionSnapshot

    def event_details(self) -> dict[str, str]:
        details = {
            "barbell_id": str(self.barbell_id),
            "barbell_equip_source": "explicit_domain_command",
            "player_state_revision": str(self.state.meta.revision),
        }
        details.update(
            self.production_before.event_details(suffix="before_equip")
        )
        details.update(
            self.production_after.event_details(suffix="after_equip")
        )
        return details


def lock_throw_request(
    state: PlayerState,
    *,
    adapter: FishThrowDataAdapter,
    root_random_seed: int,
    throw_id: int,
    regular_luck_multiplier: float = 1.0,
) -> ProductionThrowRequest:
    """Lock strength and selected torpedo from PlayerState for one throw."""

    if not isinstance(state, PlayerState):
        raise FishCommandError("state must be a PlayerState")
    if not isinstance(adapter, FishThrowDataAdapter):
        raise FishCommandError("adapter must be a FishThrowDataAdapter")
    state.validate()
    if throw_id != state.statistics.total_throws:
        raise FishCommandError(
            "throw_id does not match PlayerState.statistics.totalThrows"
        )
    if state.torpedo.selected_id <= 0:
        raise FishCommandError("PlayerState has no selected torpedo")

    stored_strength = state.wallet.strength.to_sim_number()
    if stored_strength <= SimNumber.zero():
        raise FishCommandError("PlayerState strength must be positive")
    max_strength = adapter.rules.strength_luck_pools[-1].strength_upper_bound
    max_strength_value = SimNumber.parse(str(max_strength))
    locked_strength = min(stored_strength, max_strength_value).to_float()
    return ProductionThrowRequest(
        root_random_seed=root_random_seed,
        throw_id=throw_id,
        strength=locked_strength,
        torpedo_id=state.torpedo.selected_id,
        regular_luck_multiplier=regular_luck_multiplier,
    )


def apply_throw_resolution(
    state: PlayerState,
    resolution: ProductionThrowResolution,
    *,
    adapter: FishThrowDataAdapter,
    hall_adapter: FishHallDataAdapter,
) -> AppliedThrowResolution:
    """Atomically add one resolved fish and trash reward to PlayerState.

    The input state is never mutated. A validated copy is returned only after
    every reward fact and counter has been updated successfully.
    """

    if not isinstance(state, PlayerState):
        raise FishCommandError("state must be a PlayerState")
    if not isinstance(resolution, ProductionThrowResolution):
        raise FishCommandError(
            "resolution must be a ProductionThrowResolution"
        )
    if not isinstance(adapter, FishThrowDataAdapter):
        raise FishCommandError("adapter must be a FishThrowDataAdapter")
    if not isinstance(hall_adapter, FishHallDataAdapter):
        raise FishCommandError("hall_adapter must be a FishHallDataAdapter")
    state.validate(hall_adapter.validation_context())
    try:
        adapter.verify_resolution(resolution)
    except FishDataError as exc:
        raise FishCommandError(
            "resolution does not match the authoritative Fish data replay"
        ) from exc
    if state.torpedo.selected_id != resolution.request.torpedo_id:
        raise FishCommandError(
            "resolved torpedo does not match PlayerState.torpedo.selectedId"
        )
    if resolution.request.throw_id != state.statistics.total_throws:
        raise FishCommandError(
            "resolved throw_id does not match PlayerState.statistics.totalThrows"
        )

    fish_id = _positive_config_id(
        resolution.outcome.fish_reward.id,
        "fish_reward.id",
    )
    trash_id = _positive_config_id(
        resolution.outcome.trash_reward.id,
        "trash_reward.id",
    )
    if (
        type(resolution.fish_weight_gram) is not int
        or resolution.fish_weight_gram <= 0
    ):
        raise FishCommandError("fish_weight_gram must be a positive integer")
    if (
        type(resolution.fish_mutation_id) is not int
        or resolution.fish_mutation_id <= 0
    ):
        raise FishCommandError("fish_mutation_id must be a positive integer")

    committed = state.copy()
    instance_id = committed.fish.next_instance_id
    committed.fish.items.append(
        FishInstance(
            instance_id=instance_id,
            fish_id=fish_id,
            mutation_id=resolution.fish_mutation_id,
            level=1,
            weight_gram=resolution.fish_weight_gram,
            hall_slot=0,
        )
    )
    committed.fish.next_instance_id += 1

    trash_stock_count = 1
    for stock in committed.trash_man.processing.stocks:
        if stock.trash_id == trash_id:
            stock.count += 1
            trash_stock_count = stock.count
            break
    else:
        committed.trash_man.processing.stocks.append(
            TrashStock(trash_id=trash_id, count=1)
        )

    committed.statistics.total_throws += 1
    committed.statistics.total_fish_caught += 1
    layout = hall_adapter.expected_layout(committed)
    for item in committed.fish.items:
        item.hall_slot = layout.get(item.instance_id, 0)
    committed.meta.revision += 1
    committed.validate(hall_adapter.validation_context())
    fish_hall = hall_adapter.snapshot(committed)
    return AppliedThrowResolution(
        state=committed,
        fish_instance_id=instance_id,
        trash_stock_count=trash_stock_count,
        fish_hall=fish_hall,
    )


def settle_fish_hall_income(
    state: PlayerState,
    to_time_seconds: int,
    *,
    hall_adapter: FishHallDataAdapter,
) -> AppliedFishHallSettlement:
    """Settle fixed max-income hall production to one server timestamp."""

    if not isinstance(state, PlayerState):
        raise FishCommandError("state must be a PlayerState")
    if not isinstance(hall_adapter, FishHallDataAdapter):
        raise FishCommandError("hall_adapter must be a FishHallDataAdapter")
    state.validate(hall_adapter.validation_context())
    if type(to_time_seconds) is not int:
        raise FishCommandError("to_time_seconds must be an integer")
    from_time_seconds = state.production.last_settled_at
    if to_time_seconds < from_time_seconds:
        raise FishCommandError("fish hall settlement time cannot move backwards")

    fish_hall = hall_adapter.snapshot(state)
    elapsed_seconds = to_time_seconds - from_time_seconds
    money_added = fish_hall.total_income_per_second * elapsed_seconds
    committed = state.copy()
    if elapsed_seconds > 0:
        next_money = committed.wallet.money.to_sim_number() + money_added
        committed.wallet.money = BigNumberDTO.from_value(
            next_money,
            allow_negative=False,
        )
        committed.production.last_settled_at = to_time_seconds
        committed.meta.revision += 1
    committed.validate(hall_adapter.validation_context())
    return AppliedFishHallSettlement(
        state=committed,
        from_time_seconds=from_time_seconds,
        to_time_seconds=to_time_seconds,
        elapsed_seconds=elapsed_seconds,
        money_added=money_added,
        fish_hall=fish_hall,
    )


def upgrade_fish(
    state: PlayerState,
    instance_id: int,
    *,
    hall_adapter: FishHallDataAdapter,
) -> AppliedFishUpgrade:
    """Atomically pay for one level and recompute the fixed hall layout.

    Callers must settle continuous production to the command timestamp before
    invoking this transaction.
    """

    if not isinstance(state, PlayerState):
        raise FishCommandError("state must be a PlayerState")
    if not isinstance(hall_adapter, FishHallDataAdapter):
        raise FishCommandError("hall_adapter must be a FishHallDataAdapter")
    if type(instance_id) is not int or instance_id <= 0:
        raise FishCommandError("instance_id must be a positive integer")
    state.validate(hall_adapter.validation_context())
    try:
        source_item = next(
            item for item in state.fish.items if item.instance_id == instance_id
        )
    except StopIteration as exc:
        raise FishCommandError(
            f"unknown fish instance id: {instance_id}"
        ) from exc

    try:
        price = hall_adapter.upgrade_price(source_item)
    except FishDataError as exc:
        raise FishCommandError(str(exc)) from exc
    money_before = state.wallet.money.to_sim_number()
    if money_before < price:
        raise FishCommandError(
            "insufficient money for fish upgrade: "
            f"need {price.to_decimal_string()}, "
            f"have {money_before.to_decimal_string()}"
        )

    fish_hall_before = hall_adapter.snapshot(state)
    income_before = hall_adapter.income_trace(source_item)
    committed = state.copy()
    committed_item = next(
        item
        for item in committed.fish.items
        if item.instance_id == instance_id
    )
    committed_item.level += 1
    calculated_money_after = money_before - price
    committed.wallet.money = BigNumberDTO.from_value(
        calculated_money_after,
        allow_negative=False,
    )
    money_after = committed.wallet.money.to_sim_number()
    layout = hall_adapter.expected_layout(committed)
    for item in committed.fish.items:
        item.hall_slot = layout.get(item.instance_id, 0)
    committed.meta.revision += 1
    committed.validate(hall_adapter.validation_context())
    income_after = hall_adapter.income_trace(committed_item)
    fish_hall_after = hall_adapter.snapshot(committed)
    return AppliedFishUpgrade(
        state=committed,
        instance_id=instance_id,
        from_level=source_item.level,
        to_level=committed_item.level,
        price=price,
        money_before=money_before,
        money_after=money_after,
        income_before=income_before,
        income_after=income_after,
        fish_hall_before=fish_hall_before,
        fish_hall_after=fish_hall_after,
    )


def apply_fish_hall_upgrade(
    state: PlayerState,
    *,
    hall_adapter: FishHallDataAdapter,
) -> AppliedFishHallUpgrade:
    """Atomically pay material for one hall level and apply its new capacity.

    Callers must settle all continuous production to the command timestamp
    before invoking this transaction.
    """

    if not isinstance(state, PlayerState):
        raise FishCommandError("state must be a PlayerState")
    if not isinstance(hall_adapter, FishHallDataAdapter):
        raise FishCommandError("hall_adapter must be a FishHallDataAdapter")
    state.validate(hall_adapter.validation_context())

    from_level = state.fish_hall.upgrade_level
    try:
        price = hall_adapter.hall_upgrade_price(from_level)
    except FishDataError as exc:
        raise FishCommandError(str(exc)) from exc
    material_before = state.wallet.material.to_sim_number()
    if material_before < price:
        raise FishCommandError(
            "insufficient material for fish hall upgrade: "
            f"need {price.to_decimal_string()}, "
            f"have {material_before.to_decimal_string()}"
        )

    fish_hall_before = hall_adapter.snapshot(state)
    committed = state.copy()
    committed.fish_hall.upgrade_level = from_level + 1
    calculated_material_after = material_before - price
    committed.wallet.material = BigNumberDTO.from_value(
        calculated_material_after,
        allow_negative=False,
    )
    material_after = committed.wallet.material.to_sim_number()
    layout = hall_adapter.expected_layout(committed)
    for item in committed.fish.items:
        item.hall_slot = layout.get(item.instance_id, 0)
    committed.meta.revision += 1
    committed.validate(hall_adapter.validation_context())
    fish_hall_after = hall_adapter.snapshot(committed)
    return AppliedFishHallUpgrade(
        state=committed,
        from_level=from_level,
        to_level=committed.fish_hall.upgrade_level,
        price=price,
        material_before=material_before,
        material_after=material_after,
        max_level=hall_adapter.max_hall_upgrade_level,
        fish_hall_before=fish_hall_before,
        fish_hall_after=fish_hall_after,
    )


def apply_strength_rebirth(
    state: PlayerState,
    *,
    hall_adapter: FishHallDataAdapter,
) -> AppliedStrengthRebirth:
    """Atomically reset strength and earn the next permanent hall multiplier.

    Callers must settle continuous production to the command timestamp before
    invoking this transaction.
    """

    if not isinstance(state, PlayerState):
        raise FishCommandError("state must be a PlayerState")
    if not isinstance(hall_adapter, FishHallDataAdapter):
        raise FishCommandError("hall_adapter must be a FishHallDataAdapter")
    state.validate(hall_adapter.validation_context())

    from_completed_count = state.rebirth.strength_completed_count
    try:
        rule = hall_adapter.next_strength_rebirth_rule(
            from_completed_count
        )
    except FishDataError as exc:
        raise FishCommandError(str(exc)) from exc
    strength_before = state.wallet.strength.to_sim_number()
    if strength_before < rule.strength_requirement:
        raise FishCommandError(
            "insufficient strength for strength rebirth: "
            f"need {rule.strength_requirement.to_decimal_string()}, "
            f"have {strength_before.to_decimal_string()}"
        )

    fish_hall_before = hall_adapter.snapshot(state)
    committed = state.copy()
    committed.wallet.strength = BigNumberDTO.from_value(
        SimNumber.zero(),
        allow_negative=False,
    )
    committed.rebirth.strength_completed_count = rule.completed_count
    committed.meta.revision += 1
    committed.validate(hall_adapter.validation_context())
    fish_hall_after = hall_adapter.snapshot(committed)
    return AppliedStrengthRebirth(
        state=committed,
        from_completed_count=from_completed_count,
        to_completed_count=rule.completed_count,
        strength_requirement=rule.strength_requirement,
        strength_before=strength_before,
        strength_after=committed.wallet.strength.to_sim_number(),
        fish_hall_before=fish_hall_before,
        fish_hall_after=fish_hall_after,
    )


def synthesize_barbell(
    state: PlayerState,
    barbell_id: int,
    *,
    hall_adapter: FishHallDataAdapter,
    barbell_adapter: FishBarbellDataAdapter,
) -> AppliedBarbellSynthesis:
    """Atomically pay material, add one barbell, and equip the best owned.

    Callers must settle continuous production to the command timestamp before
    invoking this transaction.
    """

    if not isinstance(state, PlayerState):
        raise FishCommandError("state must be a PlayerState")
    if not isinstance(hall_adapter, FishHallDataAdapter):
        raise FishCommandError("hall_adapter must be a FishHallDataAdapter")
    if not isinstance(barbell_adapter, FishBarbellDataAdapter):
        raise FishCommandError(
            "barbell_adapter must be a FishBarbellDataAdapter"
        )
    if type(barbell_id) is not int or barbell_id <= 0:
        raise FishCommandError("barbell_id must be a positive integer")
    state.validate(hall_adapter.validation_context())
    production_before = barbell_adapter.production_snapshot(state)
    try:
        price = barbell_adapter.synthesis_price(barbell_id)
    except FishDataError as exc:
        raise FishCommandError(str(exc)) from exc
    material_before = state.wallet.material.to_sim_number()
    if material_before < price:
        raise FishCommandError(
            "insufficient material for barbell synthesis: "
            f"need {price.to_decimal_string()}, "
            f"have {material_before.to_decimal_string()}"
        )

    source_owned = next(
        (
            entry
            for entry in state.barbell.owned
            if entry.barbell_id == barbell_id
        ),
        None,
    )
    count_before = 0 if source_owned is None else source_owned.count
    committed = state.copy()
    committed_owned = next(
        (
            entry
            for entry in committed.barbell.owned
            if entry.barbell_id == barbell_id
        ),
        None,
    )
    if committed_owned is None:
        committed_owned = OwnedBarbell(barbell_id=barbell_id, count=1)
        committed.barbell.owned.append(committed_owned)
    else:
        committed_owned.count += 1
    committed.barbell.equipped_id = barbell_adapter.best_owned_id(committed)
    committed.wallet.material = BigNumberDTO.from_value(
        material_before - price,
        allow_negative=False,
    )
    committed.meta.revision += 1
    committed.validate(hall_adapter.validation_context())
    production_after = barbell_adapter.production_snapshot(committed)
    return AppliedBarbellSynthesis(
        state=committed,
        barbell_id=barbell_id,
        price=price,
        material_before=material_before,
        material_after=committed.wallet.material.to_sim_number(),
        count_before=count_before,
        count_after=committed_owned.count,
        production_before=production_before,
        production_after=production_after,
    )


def equip_barbell(
    state: PlayerState,
    barbell_id: int,
    *,
    hall_adapter: FishHallDataAdapter,
    barbell_adapter: FishBarbellDataAdapter,
) -> AppliedBarbellEquip:
    """Atomically equip one already-owned barbell.

    Callers must settle continuous production to the command timestamp before
    invoking this transaction.
    """

    if not isinstance(state, PlayerState):
        raise FishCommandError("state must be a PlayerState")
    if not isinstance(hall_adapter, FishHallDataAdapter):
        raise FishCommandError("hall_adapter must be a FishHallDataAdapter")
    if not isinstance(barbell_adapter, FishBarbellDataAdapter):
        raise FishCommandError(
            "barbell_adapter must be a FishBarbellDataAdapter"
        )
    if type(barbell_id) is not int or barbell_id <= 0:
        raise FishCommandError("barbell_id must be a positive integer")
    state.validate(hall_adapter.validation_context())
    try:
        barbell_adapter.rule(barbell_id)
    except FishDataError as exc:
        raise FishCommandError(str(exc)) from exc
    if not any(
        entry.barbell_id == barbell_id and entry.count > 0
        for entry in state.barbell.owned
    ):
        raise FishCommandError(
            f"barbell is not owned: {barbell_id}"
        )
    if state.barbell.equipped_id == barbell_id:
        raise FishCommandError(f"barbell is already equipped: {barbell_id}")

    production_before = barbell_adapter.production_snapshot(state)
    committed = state.copy()
    committed.barbell.equipped_id = barbell_id
    committed.meta.revision += 1
    committed.validate(hall_adapter.validation_context())
    production_after = barbell_adapter.production_snapshot(committed)
    return AppliedBarbellEquip(
        state=committed,
        barbell_id=barbell_id,
        production_before=production_before,
        production_after=production_after,
    )


def _positive_config_id(value: object, field: str) -> int:
    if not isinstance(value, str) or not value.isdigit():
        raise FishCommandError(f"{field} must be a positive integer id")
    parsed = int(value)
    if parsed <= 0:
        raise FishCommandError(f"{field} must be a positive integer id")
    return parsed
