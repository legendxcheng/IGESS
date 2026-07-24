from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from igess.builder import ModelBuilder
from igess.behavior import (
    BehaviorDecision,
    BehaviorRuntimeState,
    BehaviorScheduler,
)
from igess.fish_barbell import FishBarbellDataAdapter
from igess.fish_behavior import (
    FishBehaviorAdapter,
    FishBehaviorConfigError,
    STRENGTH_REBIRTH_BEHAVIOR_ID,
    SYNTHESIZE_BARBELL_BEHAVIOR_ID,
    UPGRADE_FISH_HALL_BEHAVIOR_ID,
)
from igess.fish_commands import (
    FishCommandError,
    apply_fish_hall_upgrade,
    apply_strength_rebirth,
    apply_throw_resolution,
    equip_barbell,
    lock_throw_request,
    settle_fish_hall_income,
    synthesize_barbell,
    upgrade_fish,
)
from igess.fish_data import (
    FISH_REQUIRED_TABLES,
    FishDataError,
    FishDataLoader,
    FishDataSnapshot,
    GeneratedLubanProvider,
)
from igess.fish_hall import FishHallDataAdapter
from igess.fish_production import (
    FishProductionRuntime,
    settle_fish_production,
)
from igess.fish_state import (
    BigNumberDTO,
    FishCheckpointCodec,
    FishInstance,
    OwnedBarbell,
    PlayerState,
    TrashStock,
)
from igess.fish_simulator import FishEconomySimulator
from igess.fish_throw import map_torpedo_power_to_trash_luck
from igess.fish_throw_data import (
    FishThrowDataAdapter,
    ProductionThrowConfig,
    ProductionThrowRequest,
)
from igess.fish_trash import (
    FishTrashDataAdapter,
    TrashProcessingRuntime,
)
from igess.loader import ConfigLoader
from igess.numbers import SimNumber


@dataclass(frozen=True)
class _BigNumber:
    sign: int
    digits: str
    scale: int


def _big(value: int) -> _BigNumber:
    return _BigNumber(1, str(value), 0)


def _snapshot(
    tmp_path: Path,
    *,
    initial_torpedo_id: int = 1,
    trash_duration: int = 300,
) -> FishDataSnapshot:
    tables = {
        "tbfishrandompool": (
            SimpleNamespace(
                id=1,
                rarityId=1,
                strengthUpperBound=_big(50),
                startLuck=1,
                endLuck=3,
            ),
            SimpleNamespace(
                id=2,
                rarityId=2,
                strengthUpperBound=_big(2000),
                startLuck=5,
                endLuck=8,
            ),
        ),
        "tbtrashrandompool": (
            SimpleNamespace(
                id=1,
                rarityId=1,
                powerUpperBound=_big(50),
                name="池1",
                startLuck=1,
                endLuck=3,
            ),
            SimpleNamespace(
                id=2,
                rarityId=2,
                powerUpperBound=_big(2000),
                name="池2",
                startLuck=5,
                endLuck=8,
            ),
        ),
        "tbbonusfirstlayer": (
            SimpleNamespace(
                id=1,
                resultType=0,
                name="无 Bonus",
                rollPowerRequirement=1,
                continueChain=False,
                luckMultiplier=1,
            ),
            SimpleNamespace(
                id=2,
                resultType=1,
                name="进入变异",
                rollPowerRequirement=3.787878787878788,
                continueChain=True,
                luckMultiplier=1,
            ),
            SimpleNamespace(
                id=3,
                resultType=2,
                name="Luck ×2",
                rollPowerRequirement=10,
                continueChain=True,
                luckMultiplier=2,
            ),
        ),
        "tbmutation": (
            SimpleNamespace(
                id=7,
                name="正常",
                mutationWeight=0,
                incomeMultiplier=1,
            ),
            SimpleNamespace(
                id=2,
                name="金色",
                mutationWeight=100000,
                incomeMultiplier=1.5,
            ),
        ),
        "tbfish": (
            SimpleNamespace(
                id=1,
                baseMoneyPerSecond=_big(10),
                name="鱼1",
                rarityId=1,
                Denominator=_big(1),
                weight=1250,
            ),
            SimpleNamespace(
                id=2,
                baseMoneyPerSecond=_big(8),
                name="鱼2",
                rarityId=2,
                Denominator=_big(10),
                weight=800,
            ),
        ),
        "tbtrash": (
            SimpleNamespace(
                id=1,
                name="废料1",
                baseDecomposeSeconds=trash_duration,
                baseMaterialPerSecond=_big(2),
                rarityId=1,
                Denominator=_big(1),
            ),
            SimpleNamespace(
                id=2,
                name="废料2",
                baseDecomposeSeconds=trash_duration,
                baseMaterialPerSecond=_big(4),
                rarityId=2,
                Denominator=_big(10),
            ),
        ),
        "tbtrashmanrealm": (
            SimpleNamespace(
                id=1,
                name="初境",
                decomposeSpeedMultiplier=1,
                cultivationSecondsToNextRealm=0,
            ),
            SimpleNamespace(
                id=2,
                name="二境",
                decomposeSpeedMultiplier=1.25,
                cultivationSecondsToNextRealm=1,
            ),
            SimpleNamespace(
                id=3,
                name="三境",
                decomposeSpeedMultiplier=2,
                cultivationSecondsToNextRealm=2,
            ),
        ),
        "tbtrashmanrebirth": (
            SimpleNamespace(
                id=0,
                realmRequirement=0,
                trashToTreasureOutputMultiplier=2,
            ),
            SimpleNamespace(
                id=1,
                realmRequirement=4,
                trashToTreasureOutputMultiplier=3,
            ),
        ),
        "tbtorpedo": (
            SimpleNamespace(
                id=initial_torpedo_id,
                name="初始鱼雷",
                rarityId=1,
                power=_big(50),
            ),
        ),
        "tbbarbell": (
            SimpleNamespace(
                id=1,
                name="杠铃1",
                strengthPerExercise=2,
                price=_big(20),
                rarityId=1,
                timeCost=1,
            ),
            SimpleNamespace(
                id=2,
                name="杠铃2",
                strengthPerExercise=5,
                price=_big(75),
                rarityId=2,
                timeCost=1,
            ),
        ),
        "tbstrengthrebirth": (
            SimpleNamespace(
                id=1,
                strengthRequirement=_big(1000),
                fishHallOutputMultiplier=2,
            ),
            SimpleNamespace(
                id=2,
                strengthRequirement=_big(10000),
                fishHallOutputMultiplier=3,
            ),
        ),
        "tbfishhallupgrade": (
            SimpleNamespace(
                id=11,
                upgradePrice=_big(100),
                slotQty=2,
            ),
            SimpleNamespace(
                id=12,
                upgradePrice=_big(0),
                slotQty=3,
            ),
        ),
    }
    return FishDataSnapshot(
        root=tmp_path,
        tables=tables,
        files=(),
        loader_files=(),
        production_data=False,
    )


def test_generated_rows_drive_one_replayable_throw(tmp_path: Path) -> None:
    adapter = FishThrowDataAdapter(
        _snapshot(tmp_path),
        bonus_base_luck=1,
        max_bonus_layers=4,
    )
    request = ProductionThrowRequest(
        root_random_seed=20260722,
        throw_id=0,
        strength=50,
        torpedo_id=1,
    )

    resolution = adapter.resolve(request)
    replay = adapter.resolve(request)

    assert replay == resolution
    assert resolution.outcome.strength_luck.base_fish_luck == 3
    assert resolution.torpedo_power == 50
    assert resolution.trash_luck_mapping.base_trash_luck == 3
    assert len(adapter.rules.fish_pool) == 2
    assert len(adapter.rules.trash_pool) == 2
    assert adapter.rules.fish_pool[-1].rarity_id == 2
    assert [row.id for row in adapter.rules.mutations] == ["2"]
    assert resolution.outcome.fish_reward is not None
    assert resolution.outcome.trash_reward is not None
    assert (
        resolution.fish_weight_gram
        == {
            "1": 1250,
            "2": 800,
        }[resolution.outcome.fish_reward.id]
    )
    assert resolution.fish_mutation_id == (
        7
        if resolution.outcome.mutation is None
        else int(resolution.outcome.mutation.id)
    )
    assert "reward_application" not in resolution.event_details()


def test_throw_application_atomically_persists_rewards(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)
    adapter = FishThrowDataAdapter(
        snapshot,
        bonus_base_luck=1,
        max_bonus_layers=4,
    )
    hall_adapter = FishHallDataAdapter(snapshot)
    resolution = adapter.resolve(
        ProductionThrowRequest(
            root_random_seed=20260722,
            throw_id=0,
            strength=50,
            torpedo_id=1,
        )
    )
    state = PlayerState.new(initial_torpedo_id=1)
    original = state.to_dict()

    application = apply_throw_resolution(
        state,
        resolution,
        adapter=adapter,
        hall_adapter=hall_adapter,
    )

    assert state.to_dict() == original
    assert application.state is not state
    assert application.state.fish.next_instance_id == 2
    assert len(application.state.fish.items) == 1
    fish = application.state.fish.items[0]
    assert fish.instance_id == 1
    assert fish.fish_id == int(resolution.outcome.fish_reward.id)
    assert fish.mutation_id == resolution.fish_mutation_id
    assert fish.level == 1
    assert fish.weight_gram == resolution.fish_weight_gram
    assert fish.hall_slot == 1
    assert application.state.trash_man.processing.stocks == [
        TrashStock(
            trash_id=int(resolution.outcome.trash_reward.id),
            count=1,
        )
    ]
    assert application.state.statistics.total_throws == 1
    assert application.state.statistics.total_fish_caught == 1
    assert application.state.collection == state.collection
    assert application.state.meta.revision == 1
    application_details = application.event_details()
    assert application_details["reward_application"] == ("applied_to_player_state")
    assert application_details["fish_instance_id"] == "1"
    assert application_details["trash_stock_count"] == "1"
    assert application_details["player_state_revision"] == "1"
    assert application_details["fish_hall_capacity_after_throw"] == "2"
    assert application_details["fish_hall_policy_after_throw"] == ("fixed_max_income")
    assert application_details["fish_hall_tie_breaker_after_throw"] == (
        "instance_id_ascending"
    )
    assert application_details["fish_hall_deployed_instance_ids_after_throw"] == "[1]"
    assert application_details["fish_hall_income_per_second_after_throw"] in {
        "8",
        "10",
        "12",
        "15",
    }

    committed = application.state.to_dict()
    with pytest.raises(FishCommandError, match="throw_id"):
        apply_throw_resolution(
            application.state,
            resolution,
            adapter=adapter,
            hall_adapter=hall_adapter,
        )
    assert application.state.to_dict() == committed


def test_throw_application_increments_existing_trash_stock(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot(tmp_path)
    adapter = FishThrowDataAdapter(
        snapshot,
        bonus_base_luck=1,
        max_bonus_layers=4,
    )
    resolution = adapter.resolve(
        ProductionThrowRequest(
            root_random_seed=20260722,
            throw_id=0,
            strength=50,
            torpedo_id=1,
        )
    )
    trash_id = int(resolution.outcome.trash_reward.id)
    state = PlayerState.new(initial_torpedo_id=1)
    state.trash_man.processing.stocks = [TrashStock(trash_id=trash_id, count=4)]

    application = apply_throw_resolution(
        state,
        resolution,
        adapter=adapter,
        hall_adapter=FishHallDataAdapter(snapshot),
    )

    assert application.trash_stock_count == 5
    assert application.state.trash_man.processing.stocks == [
        TrashStock(trash_id=trash_id, count=5)
    ]
    assert state.trash_man.processing.stocks == [TrashStock(trash_id=trash_id, count=4)]


def test_throw_application_rejects_changed_selected_torpedo(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot(tmp_path)
    adapter = FishThrowDataAdapter(
        snapshot,
        bonus_base_luck=1,
        max_bonus_layers=4,
    )
    resolution = adapter.resolve(
        ProductionThrowRequest(
            root_random_seed=20260722,
            throw_id=0,
            strength=50,
            torpedo_id=1,
        )
    )
    state = PlayerState.new(initial_torpedo_id=2)
    original = state.to_dict()

    with pytest.raises(FishCommandError, match="resolved torpedo"):
        apply_throw_resolution(
            state,
            resolution,
            adapter=adapter,
            hall_adapter=FishHallDataAdapter(snapshot),
        )

    assert state.to_dict() == original


def test_throw_application_rejects_non_authoritative_resolution(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot(tmp_path)
    adapter = FishThrowDataAdapter(
        snapshot,
        bonus_base_luck=1,
        max_bonus_layers=4,
    )
    resolution = adapter.resolve(
        ProductionThrowRequest(
            root_random_seed=20260722,
            throw_id=0,
            strength=50,
            torpedo_id=1,
        )
    )
    altered = replace(
        resolution,
        fish_weight_gram=resolution.fish_weight_gram + 1,
    )
    state = PlayerState.new(initial_torpedo_id=1)

    with pytest.raises(FishCommandError, match="authoritative"):
        apply_throw_resolution(
            state,
            altered,
            adapter=adapter,
            hall_adapter=FishHallDataAdapter(snapshot),
        )

    assert state.fish.items == []

    malformed = replace(resolution, request=None)  # type: ignore[arg-type]
    with pytest.raises(FishCommandError, match="authoritative"):
        apply_throw_resolution(
            state,
            malformed,
            adapter=adapter,
            hall_adapter=FishHallDataAdapter(snapshot),
        )

    assert state.fish.items == []


def test_fish_weight_must_be_a_positive_integer(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)
    snapshot.table("tbfish")[0].weight = 0

    with pytest.raises(FishDataError, match=r"tbfish\.1\.weight"):
        FishThrowDataAdapter(
            snapshot,
            bonus_base_luck=1,
            max_bonus_layers=4,
        )


def test_max_income_layout_uses_capacity_income_and_stable_ties(
    tmp_path: Path,
) -> None:
    hall_adapter = FishHallDataAdapter(_snapshot(tmp_path))
    state = PlayerState.new(initial_torpedo_id=1)
    state.fish.items = [
        FishInstance(1, 1, 7, 1, 100, 0),
        FishInstance(2, 2, 2, 1, 100, 0),
        FishInstance(3, 1, 7, 1, 100, 0),
    ]
    state.fish.next_instance_id = 4

    assert hall_adapter.capacity(0) == 2
    assert hall_adapter.capacity(1) == 3
    assert hall_adapter.expected_layout(state) == {2: 1, 1: 2}

    for item in state.fish.items:
        item.hall_slot = hall_adapter.expected_layout(state).get(
            item.instance_id,
            0,
        )
    snapshot = hall_adapter.snapshot(state)

    assert snapshot.deployed_instance_ids == (2, 1)
    assert snapshot.total_income_per_second.to_decimal_string() == "22"
    assert [
        trace.income_per_second.to_decimal_string() for trace in snapshot.traces
    ] == [
        "12",
        "10",
    ]
    assert state.fish.items[2].hall_slot == 0

    state.rebirth.strength_completed_count = 1
    reborn_snapshot = hall_adapter.snapshot(state)
    assert reborn_snapshot.base_total_income_per_second == SimNumber.parse(22)
    assert reborn_snapshot.strength_rebirth_multiplier == SimNumber.parse(2)
    assert reborn_snapshot.total_income_per_second == SimNumber.parse(44)
    assert (
        reborn_snapshot.event_details()[
            "strength_rebirth_fish_hall_multiplier_source"
        ]
        == "tbstrengthrebirth[id=1].fishHallOutputMultiplier"
    )


def test_fish_level_price_and_income_formulas_use_bignumber(
    tmp_path: Path,
) -> None:
    hall_adapter = FishHallDataAdapter(_snapshot(tmp_path))
    normal = FishInstance(1, 1, 7, 1, 100, 0)
    upgraded = FishInstance(1, 1, 7, 2, 100, 0)
    mutated = FishInstance(1, 1, 2, 3, 100, 0)

    assert hall_adapter.upgrade_price(normal).to_decimal_string() == "10"
    assert hall_adapter.upgrade_price(upgraded).to_decimal_string() == "15"
    assert (
        hall_adapter.upgrade_price(FishInstance(1, 1, 2, 2, 100, 0)).to_decimal_string()
        == "15"
    )
    assert (
        hall_adapter.income_trace(upgraded).income_per_second.to_decimal_string()
        == "12.5"
    )
    mutation_trace = hall_adapter.income_trace(mutated)
    assert mutation_trace.level_income_multiplier.to_decimal_string() == "1.5625"
    assert mutation_trace.level_money_per_second.to_decimal_string() == "15.625"
    assert mutation_trace.mutation_income_multiplier.to_decimal_string() == "1.5"
    assert mutation_trace.income_per_second.to_decimal_string() == "23.4375"
    assert (
        mutation_trace.event_entry()["formula"]
        == "base_money_per_second*1.25^(level-1)*mutation_income_multiplier"
    )

    at_cap = FishInstance(1, 1, 7, 100, 100, 0)
    with pytest.raises(FishDataError, match="already at max level"):
        hall_adapter.upgrade_price(at_cap)


def test_fish_upgrade_atomically_pays_levels_and_reorders_hall(
    tmp_path: Path,
) -> None:
    hall_adapter = FishHallDataAdapter(_snapshot(tmp_path))
    state = PlayerState.new(initial_torpedo_id=1)
    state.wallet.money = state.wallet.money.from_value("100")
    state.fish.items = [
        FishInstance(1, 1, 7, 1, 100, 2),
        FishInstance(2, 2, 2, 1, 100, 1),
    ]
    state.fish.next_instance_id = 3
    original = state.to_dict(context=hall_adapter.validation_context())

    application = upgrade_fish(state, 1, hall_adapter=hall_adapter)

    assert state.to_dict(context=hall_adapter.validation_context()) == original
    assert application.from_level == 1
    assert application.to_level == 2
    assert application.price.to_decimal_string() == "10"
    assert application.money_before.to_decimal_string() == "100"
    assert application.money_after.to_decimal_string() == "90"
    assert application.income_before.income_per_second.to_decimal_string() == "10"
    assert application.income_after.income_per_second.to_decimal_string() == "12.5"
    assert application.state.wallet.money.to_sim_number() == SimNumber.parse("90")
    assert application.state.fish.items[0].level == 2
    assert application.state.fish.items[0].hall_slot == 1
    assert application.state.fish.items[1].hall_slot == 2
    assert application.state.meta.revision == 1
    details = application.event_details()
    assert details["fish_upgrade_price_formula"] == (
        "base_money_per_second*1.5^(current_level-1)"
    )
    assert details["fish_upgrade_price_uses_mutation"] == "false"
    assert details["fish_income_formula"] == (
        "base_money_per_second*1.25^(level-1)*mutation_income_multiplier"
    )
    assert details["fish_hall_deployed_instance_ids_after_upgrade"] == "[1,2]"


def test_fish_upgrade_rejects_insufficient_money_without_mutation(
    tmp_path: Path,
) -> None:
    hall_adapter = FishHallDataAdapter(_snapshot(tmp_path))
    state = PlayerState.new(initial_torpedo_id=1)
    state.wallet.money = state.wallet.money.from_value("9")
    state.fish.items = [FishInstance(1, 1, 7, 1, 100, 1)]
    state.fish.next_instance_id = 2
    original = state.to_dict(context=hall_adapter.validation_context())

    with pytest.raises(FishCommandError, match="insufficient money"):
        upgrade_fish(state, 1, hall_adapter=hall_adapter)

    assert state.to_dict(context=hall_adapter.validation_context()) == original


def test_hall_upgrade_uses_current_row_price_and_last_row_is_max(
    tmp_path: Path,
) -> None:
    hall_adapter = FishHallDataAdapter(_snapshot(tmp_path))

    assert hall_adapter.can_upgrade_hall(0) is True
    assert hall_adapter.hall_upgrade_price(0) == SimNumber.parse(100)
    assert hall_adapter.can_upgrade_hall(1) is False
    with pytest.raises(FishDataError, match="already at max"):
        hall_adapter.hall_upgrade_price(1)


def test_hall_upgrade_rejects_zero_price_in_a_purchasable_row(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot(tmp_path)
    snapshot.table("tbfishhallupgrade")[0].upgradePrice = _big(0)

    with pytest.raises(
        FishDataError,
        match=r"tbfishhallupgrade\.0\.upgradePrice",
    ):
        FishHallDataAdapter(snapshot)


def test_hall_upgrade_requires_zero_final_price_and_increasing_capacity(
    tmp_path: Path,
) -> None:
    nonzero_final = _snapshot(tmp_path)
    nonzero_final.table("tbfishhallupgrade")[-1].upgradePrice = _big(1)
    with pytest.raises(FishDataError, match="max-level sentinel"):
        FishHallDataAdapter(nonzero_final)

    flat_capacity = _snapshot(tmp_path)
    flat_capacity.table("tbfishhallupgrade")[-1].slotQty = 2
    with pytest.raises(FishDataError, match="strictly increasing"):
        FishHallDataAdapter(flat_capacity)


def test_strength_rebirth_uses_implicit_one_x_then_one_based_table_rows(
    tmp_path: Path,
) -> None:
    adapter = FishHallDataAdapter(_snapshot(tmp_path))

    assert adapter.max_strength_rebirth_count == 2
    assert adapter.strength_rebirth_multiplier(0) == SimNumber.one()
    first = adapter.next_strength_rebirth_rule(0)
    assert first.completed_count == 1
    assert first.strength_requirement == SimNumber.parse(1000)
    assert first.fish_hall_output_multiplier == SimNumber.parse(2)
    assert adapter.strength_rebirth_multiplier(1) == SimNumber.parse(2)
    second = adapter.next_strength_rebirth_rule(1)
    assert second.completed_count == 2
    assert second.strength_requirement == SimNumber.parse(10000)
    assert second.fish_hall_output_multiplier == SimNumber.parse(3)
    assert adapter.strength_rebirth_multiplier(2) == SimNumber.parse(3)

    with pytest.raises(FishDataError, match="default 1x"):
        adapter.strength_rebirth_rule(0)
    with pytest.raises(FishDataError, match="already at max"):
        adapter.next_strength_rebirth_rule(2)

    zero_based = _snapshot(tmp_path)
    zero_based.table("tbstrengthrebirth")[0].id = 0
    with pytest.raises(FishDataError, match="positive integer"):
        FishHallDataAdapter(zero_based)


def test_strength_rebirth_resets_only_strength_and_applies_hall_multiplier(
    tmp_path: Path,
) -> None:
    adapter = FishHallDataAdapter(_snapshot(tmp_path))
    state = PlayerState.new(
        initial_torpedo_id=1,
        initial_strength=1500,
        initial_trash_man_realm_id=1,
    )
    state.wallet.money = BigNumberDTO.from_value(123)
    state.wallet.material = BigNumberDTO.from_value(456)
    state.fish.items = [FishInstance(1, 1, 7, 1, 100, 1)]
    state.fish.next_instance_id = 2
    state.trash_man.processing.stocks = [TrashStock(1, 2)]
    before = state.to_dict(context=adapter.validation_context())

    application = apply_strength_rebirth(state, hall_adapter=adapter)

    assert state.to_dict(context=adapter.validation_context()) == before
    committed = application.state
    assert application.from_completed_count == 0
    assert application.to_completed_count == 1
    assert application.strength_requirement == SimNumber.parse(1000)
    assert application.strength_before == SimNumber.parse(1500)
    assert application.strength_after == SimNumber.zero()
    assert committed.wallet.strength.to_sim_number() == SimNumber.zero()
    assert committed.rebirth.strength_completed_count == 1
    assert committed.meta.revision == state.meta.revision + 1
    assert application.fish_hall_before.total_income_per_second == (
        SimNumber.parse(10)
    )
    assert application.fish_hall_after.base_total_income_per_second == (
        SimNumber.parse(10)
    )
    assert application.fish_hall_after.total_income_per_second == (
        SimNumber.parse(20)
    )
    after = committed.to_dict(context=adapter.validation_context())
    for field in (
        "fish",
        "trashMan",
        "wallet",
        "torpedo",
        "barbell",
        "fishHall",
        "collection",
        "automation",
        "statistics",
        "production",
    ):
        if field == "wallet":
            assert after[field]["money"] == before[field]["money"]
            assert after[field]["material"] == before[field]["material"]
        else:
            assert after[field] == before[field]
    details = application.event_details()
    assert details["strength_rebirth_table_id"] == "1"
    assert details["strength_rebirth_multiplier_before"] == "1"
    assert details["strength_rebirth_multiplier_after"] == "2"
    assert details["strength_rebirth_reset_fields"] == "wallet.strength"


def test_strength_rebirth_rejects_insufficient_strength_and_max_count_atomically(
    tmp_path: Path,
) -> None:
    adapter = FishHallDataAdapter(_snapshot(tmp_path))
    insufficient = PlayerState.new(
        initial_torpedo_id=1,
        initial_strength=999,
        initial_trash_man_realm_id=1,
    )
    insufficient_before = insufficient.to_dict(
        context=adapter.validation_context()
    )

    with pytest.raises(FishCommandError, match="insufficient strength"):
        apply_strength_rebirth(insufficient, hall_adapter=adapter)
    assert insufficient.to_dict(
        context=adapter.validation_context()
    ) == insufficient_before

    maxed = insufficient.copy()
    maxed.wallet.strength = BigNumberDTO.from_value("1e100")
    maxed.rebirth.strength_completed_count = 2
    maxed_before = maxed.to_dict(context=adapter.validation_context())
    with pytest.raises(FishCommandError, match="already at max"):
        apply_strength_rebirth(maxed, hall_adapter=adapter)
    assert maxed.to_dict(context=adapter.validation_context()) == maxed_before


def test_fish_hall_upgrade_atomically_pays_material_and_expands_layout(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot(tmp_path)
    snapshot.table("tbfishhallupgrade")[0].upgradePrice = _BigNumber(
        1,
        "125",
        -1,
    )
    hall_adapter = FishHallDataAdapter(snapshot)
    state = PlayerState.new(initial_torpedo_id=1)
    state.wallet.material = BigNumberDTO.from_value("12.75")
    state.fish.items = [
        FishInstance(1, 1, 7, 1, 100, 2),
        FishInstance(2, 2, 2, 1, 100, 1),
        FishInstance(3, 1, 7, 1, 100, 0),
    ]
    state.fish.next_instance_id = 4
    original = state.to_dict(context=hall_adapter.validation_context())

    application = apply_fish_hall_upgrade(
        state,
        hall_adapter=hall_adapter,
    )

    assert state.to_dict(context=hall_adapter.validation_context()) == original
    assert application.from_level == 0
    assert application.to_level == 1
    assert application.price == SimNumber.parse("12.5")
    assert application.material_before == SimNumber.parse("12.75")
    assert application.material_after == SimNumber.parse("0.25")
    assert application.state.wallet.material.to_sim_number() == (
        SimNumber.parse("0.25")
    )
    assert application.state.fish_hall.upgrade_level == 1
    assert application.fish_hall_before.capacity == 2
    assert application.fish_hall_after.capacity == 3
    assert application.fish_hall_before.deployed_instance_ids == (2, 1)
    assert application.fish_hall_after.deployed_instance_ids == (2, 1, 3)
    assert [item.hall_slot for item in application.state.fish.items] == [2, 1, 3]
    assert application.state.meta.revision == 1
    details = application.event_details()
    assert details["fish_hall_upgrade_price"] == "12.5"
    assert details["fish_hall_upgrade_price_resource"] == "material"
    assert details["fish_hall_upgrade_price_source"] == (
        "tbfishhallupgrade[current_upgrade_level].upgradePrice"
    )
    assert details["fish_hall_upgrade_max_level"] == "1"
    assert details["fish_hall_upgrade_layout_policy"] == "fixed_max_income"
    assert details["fish_hall_capacity_before_hall_upgrade"] == "2"
    assert details["fish_hall_capacity_after_hall_upgrade"] == "3"
    assert details["fish_hall_deployed_instance_ids_after_hall_upgrade"] == (
        "[2,1,3]"
    )
    assert details["player_state_revision"] == "1"


@pytest.mark.parametrize(
    ("material", "upgrade_level", "message"),
    [
        ("99", 0, "insufficient material"),
        ("1000", 1, "already at max"),
    ],
)
def test_fish_hall_upgrade_failure_does_not_mutate_state(
    tmp_path: Path,
    material: str,
    upgrade_level: int,
    message: str,
) -> None:
    hall_adapter = FishHallDataAdapter(_snapshot(tmp_path))
    state = PlayerState.new(initial_torpedo_id=1)
    state.wallet.material = BigNumberDTO.from_value(material)
    state.fish_hall.upgrade_level = upgrade_level
    state.fish.items = [FishInstance(1, 1, 7, 1, 100, 1)]
    state.fish.next_instance_id = 2
    original = state.to_dict(context=hall_adapter.validation_context())

    with pytest.raises(FishCommandError, match=message):
        apply_fish_hall_upgrade(state, hall_adapter=hall_adapter)

    assert state.to_dict(context=hall_adapter.validation_context()) == original


def test_barbell_adapter_uses_strength_per_exercise_and_time_cost(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot(tmp_path)
    snapshot.table("tbbarbell")[1].timeCost = 5
    adapter = FishBarbellDataAdapter(snapshot)

    assert adapter.synthesis_price(1) == SimNumber.parse(20)
    assert adapter.strength_per_second(1) == SimNumber.parse(2)
    assert adapter.strength_per_second(2) == SimNumber.parse(1)

    snapshot.table("tbbarbell")[0].timeCost = 0
    with pytest.raises(FishDataError, match="timeCost"):
        FishBarbellDataAdapter(snapshot)


def test_barbell_synthesis_atomically_pays_material_and_equips_best(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot(tmp_path)
    hall_adapter = FishHallDataAdapter(snapshot)
    barbell_adapter = FishBarbellDataAdapter(snapshot)
    state = PlayerState.new(initial_torpedo_id=1)
    state.wallet.material = BigNumberDTO.from_value(200)
    original = state.to_dict(context=hall_adapter.validation_context())

    first = synthesize_barbell(
        state,
        1,
        hall_adapter=hall_adapter,
        barbell_adapter=barbell_adapter,
    )

    assert state.to_dict(context=hall_adapter.validation_context()) == original
    assert first.state.wallet.material.to_sim_number() == SimNumber.parse(180)
    assert first.state.barbell.owned == [OwnedBarbell(1, 1)]
    assert first.state.barbell.equipped_id == 1
    assert first.state.meta.revision == 1
    assert first.production_after.strength_per_second == SimNumber.parse(2)

    second = synthesize_barbell(
        first.state,
        2,
        hall_adapter=hall_adapter,
        barbell_adapter=barbell_adapter,
    )

    assert second.state.wallet.material.to_sim_number() == SimNumber.parse(105)
    assert second.state.barbell.owned == [
        OwnedBarbell(1, 1),
        OwnedBarbell(2, 1),
    ]
    assert second.state.barbell.equipped_id == 2
    assert second.production_after.strength_per_second == SimNumber.parse(5)
    details = second.event_details()
    assert details["barbell_synthesis_price_resource"] == "material"
    assert details["barbell_auto_equip_policy"] == (
        "highest_strength_per_second"
    )
    assert details["barbell_equipped_id_after_synthesis"] == "2"
    assert details["barbell_owned_count_affects_output_after_synthesis"] == (
        "false"
    )


def test_barbell_synthesis_and_equip_failures_do_not_mutate_state(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot(tmp_path)
    hall_adapter = FishHallDataAdapter(snapshot)
    barbell_adapter = FishBarbellDataAdapter(snapshot)
    state = PlayerState.new(initial_torpedo_id=1)
    state.wallet.material = BigNumberDTO.from_value(19)
    original = state.to_dict(context=hall_adapter.validation_context())

    with pytest.raises(FishCommandError, match="insufficient material"):
        synthesize_barbell(
            state,
            1,
            hall_adapter=hall_adapter,
            barbell_adapter=barbell_adapter,
        )
    with pytest.raises(FishCommandError, match="not owned"):
        equip_barbell(
            state,
            1,
            hall_adapter=hall_adapter,
            barbell_adapter=barbell_adapter,
        )

    assert state.to_dict(context=hall_adapter.validation_context()) == original


def test_explicit_barbell_equip_changes_only_the_equipped_item(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot(tmp_path)
    hall_adapter = FishHallDataAdapter(snapshot)
    barbell_adapter = FishBarbellDataAdapter(snapshot)
    state = PlayerState.new(initial_torpedo_id=1)
    state.barbell.owned = [OwnedBarbell(1, 2), OwnedBarbell(2, 1)]
    state.barbell.equipped_id = 2
    original_owned = state.copy().barbell.owned

    application = equip_barbell(
        state,
        1,
        hall_adapter=hall_adapter,
        barbell_adapter=barbell_adapter,
    )

    assert application.state.barbell.equipped_id == 1
    assert application.state.barbell.owned == original_owned
    assert application.state.meta.revision == 1
    assert application.production_before.strength_per_second == (
        SimNumber.parse(5)
    )
    assert application.production_after.strength_per_second == (
        SimNumber.parse(2)
    )


def test_barbell_online_strength_is_part_of_unified_production_settlement(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot(tmp_path)
    hall_adapter = FishHallDataAdapter(snapshot)
    barbell_adapter = FishBarbellDataAdapter(snapshot)
    state = PlayerState.new(
        initial_torpedo_id=1,
        initial_strength=10,
        initial_trash_man_realm_id=1,
    )
    state.barbell.owned = [OwnedBarbell(1, 3)]
    state.barbell.equipped_id = 1

    settlement = settle_fish_production(
        state,
        5,
        hall_adapter=hall_adapter,
        trash_adapter=FishTrashDataAdapter(snapshot),
        barbell_adapter=barbell_adapter,
    )

    assert settlement.strength_added == SimNumber.parse(10)
    assert settlement.state.wallet.strength.to_sim_number() == (
        SimNumber.parse(20)
    )
    assert settlement.state.meta.revision == 1
    assert settlement.barbell.equipped_count == 3
    assert settlement.barbell.strength_per_second == SimNumber.parse(2)
    assert settlement.event_details()["barbell_strength_added"] == "10"
    assert (
        settlement.event_details()[
            "barbell_owned_count_affects_output_before_command"
        ]
        == "false"
    )


def test_fish_hall_income_settlement_is_atomic_and_traced(
    tmp_path: Path,
) -> None:
    hall_adapter = FishHallDataAdapter(_snapshot(tmp_path))
    state = PlayerState.new(initial_torpedo_id=1)
    state.wallet.money = state.wallet.money.from_value("5")
    state.fish.items = [
        FishInstance(1, 1, 7, 1, 100, 2),
        FishInstance(2, 2, 2, 1, 100, 1),
        FishInstance(3, 1, 7, 1, 100, 0),
    ]
    state.fish.next_instance_id = 4
    original = state.to_dict(context=hall_adapter.validation_context())

    settlement = settle_fish_hall_income(
        state,
        5,
        hall_adapter=hall_adapter,
    )

    assert state.to_dict(context=hall_adapter.validation_context()) == original
    assert settlement.money_added.to_decimal_string() == "110"
    assert settlement.state.wallet.money.to_sim_number().to_decimal_string() == "115"
    assert settlement.state.production.last_settled_at == 5
    assert settlement.state.meta.revision == 1
    details = settlement.event_details()
    assert details["fish_hall_settlement_elapsed_seconds"] == "5"
    assert details["fish_hall_income_per_second_before_throw"] == "22"
    assert (
        "base_money_per_second*1.25^(level-1)"
        in details["fish_hall_formula_trace_before_throw"]
    )


def test_trash_processing_batches_queue_and_preserves_fractional_work(
    tmp_path: Path,
) -> None:
    adapter = FishTrashDataAdapter(_snapshot(tmp_path))
    state = PlayerState.new(initial_trash_man_realm_id=1)
    state.trash_man.processing.active_trash_id = 1
    state.trash_man.processing.active_progress_seconds = 100
    state.trash_man.processing.stocks = [
        TrashStock(trash_id=2, count=1),
        TrashStock(trash_id=1, count=2),
    ]

    settlement = adapter.settle(
        state,
        500,
        runtime=TrashProcessingRuntime(SimNumber.parse("0.5")),
    )

    assert settlement.completed_by_trash == ((1, 2),)
    assert settlement.completed_count == 2
    assert settlement.material_added == SimNumber.parse("1001")
    assert settlement.work_consumed == SimNumber.parse("500")
    assert settlement.unused_work == SimNumber.zero()
    assert settlement.processing.stocks == [TrashStock(trash_id=2, count=1)]
    assert settlement.processing.active_trash_id == 2
    assert settlement.processing.active_progress_seconds == 0
    assert settlement.runtime.progress_remainder == SimNumber.parse("0.5")


def test_trash_processing_speed_change_preserves_total_batch_yield(
    tmp_path: Path,
) -> None:
    adapter = FishTrashDataAdapter(_snapshot(tmp_path))
    state = PlayerState.new(initial_trash_man_realm_id=2)
    state.rebirth.trash_man_completed_count = 1
    state.trash_man.processing.active_trash_id = 1
    state.trash_man.processing.stocks = [TrashStock(trash_id=1, count=1)]

    first = adapter.settle(state, 1)
    assert first.decompose_speed_multiplier == SimNumber.parse("1.25")
    assert first.material_output_multiplier == SimNumber.parse("2")
    assert first.material_added == SimNumber.parse("5")
    assert first.processing.active_progress_seconds == 1
    assert first.runtime.progress_remainder == SimNumber.parse("0.25")

    changed = state.copy()
    changed.trash_man.processing = first.processing
    changed.trash_man.realm_id = 3
    changed.trash_man.highest_realm_id = 3
    second = adapter.settle(
        changed,
        150,
        runtime=first.runtime,
    )

    assert second.completed_count == 1
    assert second.material_added == SimNumber.parse("1195")
    assert second.unused_work == SimNumber.parse("1.25")
    assert second.processing.stocks == []
    assert first.material_added + second.material_added == SimNumber.parse("1200")


def test_fish_production_atomically_settles_material_and_queue(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot(tmp_path)
    state = PlayerState.new(initial_trash_man_realm_id=1)
    state.trash_man.processing.active_trash_id = 1
    state.trash_man.processing.stocks = [TrashStock(trash_id=1, count=1)]

    settlement = settle_fish_production(
        state,
        300,
        hall_adapter=FishHallDataAdapter(snapshot),
        trash_adapter=FishTrashDataAdapter(snapshot),
        runtime=FishProductionRuntime(),
    )

    assert state.wallet.material.to_sim_number() == SimNumber.zero()
    assert settlement.material_added == SimNumber.parse("600")
    assert settlement.state.wallet.material.to_sim_number() == SimNumber.parse("600")
    assert settlement.state.trash_man.processing.stocks == []
    assert settlement.state.production.last_settled_at == 300
    assert settlement.state.meta.revision == 1
    details = settlement.event_details()
    assert details["trash_processing_queue_policy"] == "trash_id_ascending"
    assert details["trash_completed_count"] == "1"
    assert details["trash_material_added"] == "600"


def test_online_cultivation_splits_trash_work_at_realm_boundary(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot(tmp_path, trash_duration=10)
    hall_adapter = FishHallDataAdapter(snapshot)
    trash_adapter = FishTrashDataAdapter(snapshot)
    state = PlayerState.new(initial_trash_man_realm_id=2)
    state.trash_man.highest_realm_id = 3
    state.trash_man.processing.active_trash_id = 1
    state.trash_man.processing.stocks = [TrashStock(trash_id=1, count=1)]

    first = settle_fish_production(
        state,
        1,
        hall_adapter=hall_adapter,
        trash_adapter=trash_adapter,
    )

    assert first.state.trash_man.realm_id == 3
    assert first.state.trash_man.highest_realm_id == 3
    assert first.state.trash_man.training_progress_seconds == 0
    assert first.material_added == SimNumber.parse("2.5")
    assert first.trash_processing.work_consumed == SimNumber.parse("1.25")
    assert first.trash_processing.runtime.progress_remainder == (
        SimNumber.parse("0.25")
    )
    assert [
        transition.to_dict() for transition in first.trash_processing.transitions
    ] == [
        {
            "from_realm_id": 2,
            "to_realm_id": 3,
            "at_elapsed_seconds": 1,
        }
    ]

    second = settle_fish_production(
        first.state,
        2,
        hall_adapter=hall_adapter,
        trash_adapter=trash_adapter,
        runtime=first.runtime,
    )

    assert second.material_added == SimNumber.parse("4")
    assert second.state.wallet.material.to_sim_number() == SimNumber.parse("6.5")
    details = first.event_details()
    assert details["trash_man_cultivation_online_only"] == "true"
    assert details["trash_man_cultivation_ceiling"] == ("historical_highest_realm")
    assert details["trash_man_realm_id_before"] == "2"
    assert details["trash_man_realm_id_after"] == "3"
    assert json.loads(details["trash_processing_realm_segments"]) == [
        {
            "decompose_speed_multiplier": "1.25",
            "elapsed_seconds": 1,
            "material_added": "2.5",
            "realm_id": 2,
            "unused_work": "0",
            "work_consumed": "1.25",
        }
    ]


def test_online_cultivation_handles_zero_duration_and_stops_at_highest(
    tmp_path: Path,
) -> None:
    adapter = FishTrashDataAdapter(_snapshot(tmp_path, trash_duration=10))
    state = PlayerState.new(initial_trash_man_realm_id=1)
    state.trash_man.highest_realm_id = 3
    state.trash_man.processing.active_trash_id = 1
    state.trash_man.processing.stocks = [TrashStock(trash_id=1, count=1)]

    settlement = adapter.settle_online(state, 5)

    assert settlement.realm_id_after == 3
    assert settlement.training_progress_seconds_after == 0
    assert settlement.material_added == SimNumber.parse("18.5")
    assert [transition.to_dict() for transition in settlement.transitions] == [
        {
            "from_realm_id": 1,
            "to_realm_id": 2,
            "at_elapsed_seconds": 0,
        },
        {
            "from_realm_id": 2,
            "to_realm_id": 3,
            "at_elapsed_seconds": 1,
        },
    ]
    assert [
        (segment.realm_id, segment.elapsed_seconds) for segment in settlement.segments
    ] == [(2, 1), (3, 4)]

    already_at_highest = settlement.processing
    capped = state.copy()
    capped.trash_man.realm_id = 3
    capped.trash_man.highest_realm_id = 3
    capped.trash_man.processing = already_at_highest
    capped.trash_man.training_progress_seconds = 7

    capped_settlement = adapter.settle_online(
        capped,
        2,
        runtime=settlement.runtime,
    )

    assert capped_settlement.realm_id_after == 3
    assert capped_settlement.training_progress_seconds_after == 7
    assert capped_settlement.transitions == ()


def test_online_cultivation_checkpoint_resume_does_not_split_active_behavior(
    tmp_path: Path,
) -> None:
    raw = ConfigLoader.load(
        "projects/fish/economy.yaml",
        "projects/fish/luban_exports",
    )
    model = ModelBuilder.build(raw)
    profile = model.player_profiles["default"]
    profile.behavior_weights = {"idle": SimNumber.one()}
    profile.behavior_durations = {"idle": {"type": "fixed", "seconds": 4}}
    snapshot = _snapshot(tmp_path)
    model_digest = "sha256:" + ("d" * 64)
    simulator = FishEconomySimulator(
        model,
        snapshot,
        model_digest=model_digest,
    )
    initial_state = PlayerState.new(
        initial_torpedo_id=1,
        initial_strength=50,
        initial_trash_man_realm_id=1,
    )
    initial_state.trash_man.highest_realm_id = 3
    initial_checkpoint = FishCheckpointCodec.new(
        initial_state,
        model_digest=model_digest,
        scenario_id="smoke",
        profile_id="default",
        root_random_seed=model.config.random_seed,
        behavior_state=BehaviorRuntimeState().to_dict(),
        engine_runtime_state=FishProductionRuntime().to_dict(),
        context=FishHallDataAdapter(snapshot).validation_context(),
    )

    continuous = simulator.run_scenario("smoke", initial_checkpoint)
    first = simulator.run_scenario(
        "smoke",
        initial_checkpoint,
        until_seconds=2,
    )
    resumed = simulator.run_scenario("smoke", first.checkpoint)

    assert first.checkpoint.engine_state["trashMan"]["realmId"] == 1
    assert first.checkpoint.engine_state["production"]["lastSettledAt"] == 0
    assert continuous.checkpoint.engine_state["trashMan"]["realmId"] == 3
    assert resumed.checkpoint.engine_state == (continuous.checkpoint.engine_state)
    assert resumed.checkpoint.engine_runtime_state == (
        continuous.checkpoint.engine_runtime_state
    )
    assert resumed.checkpoint.event_counters == (continuous.checkpoint.event_counters)
    assert (
        first.result.timeline + resumed.result.timeline[1:]
        == continuous.result.timeline
    )

    def behavior_events(run):
        return [
            event for event in run.result.events if event.kind != "fish_engine_ready"
        ]

    assert behavior_events(first) + behavior_events(resumed) == (
        behavior_events(continuous)
    )
    first_idle = next(
        event
        for event in continuous.result.events
        if event.kind == "fish_behavior_idle_completed"
    )
    assert first_idle.details["trash_man_realm_advance_count"] == "2"


def test_active_throw_loop_processes_trash_and_replays_checkpoint(
    tmp_path: Path,
) -> None:
    raw = ConfigLoader.load(
        "projects/fish/economy.yaml",
        "projects/fish/luban_exports",
    )
    model = ModelBuilder.build(raw)
    simulator = FishEconomySimulator(
        model,
        _snapshot(tmp_path, trash_duration=3),
        model_digest="sha256:" + ("c" * 64),
    )

    continuous = simulator.run_scenario("smoke")
    first = simulator.run_scenario("smoke", until_seconds=5)
    resumed = simulator.run_scenario("smoke", first.checkpoint)
    final_processing = continuous.checkpoint.engine_state["trashMan"]["processing"]

    assert continuous.checkpoint.event_counters["trash_processed"] == 3
    assert sum(stock["count"] for stock in final_processing["stocks"]) == 7
    assert continuous.checkpoint.engine_state["wallet"]["material"]["sign"] == 1
    assert resumed.checkpoint.engine_state == continuous.checkpoint.engine_state
    assert (
        resumed.checkpoint.engine_runtime_state
        == continuous.checkpoint.engine_runtime_state
    )
    assert resumed.checkpoint.event_counters == continuous.checkpoint.event_counters


def test_active_throw_config_requires_attributable_non_table_values() -> None:
    config = ProductionThrowConfig.from_mapping(
        {
            "initial_strength": "50",
            "interval_seconds": 1,
            "regular_luck_multiplier": "1",
            "bonus_base_luck": "1",
            "max_bonus_layers": 4,
        }
    )

    assert config.manifest_parameters() == {
        "initial_strength": "50",
        "interval_seconds": 1,
        "regular_luck_multiplier": "1",
        "bonus_base_luck": "1",
        "max_bonus_layers": 4,
    }


def test_throw_request_locks_strength_and_torpedo_from_player_state(
    tmp_path: Path,
) -> None:
    adapter = FishThrowDataAdapter(
        _snapshot(tmp_path),
        bonus_base_luck=1,
        max_bonus_layers=4,
    )
    state = PlayerState.new(
        initial_torpedo_id=1,
        initial_strength="75",
    )

    request = lock_throw_request(
        state,
        adapter=adapter,
        root_random_seed=123,
        throw_id=0,
    )
    state.wallet.strength = state.wallet.strength.from_value("100")

    assert request.strength == 75
    assert request.torpedo_id == 1
    assert request.throw_id == 0


def test_active_throw_loop_matches_checkpoint_segmented_resume(
    tmp_path: Path,
) -> None:
    raw = ConfigLoader.load(
        "projects/fish/economy.yaml",
        "projects/fish/luban_exports",
    )
    model = ModelBuilder.build(raw)
    simulator = FishEconomySimulator(
        model,
        _snapshot(tmp_path),
        model_digest="sha256:" + ("a" * 64),
    )

    continuous = simulator.run_scenario("smoke")
    first_half = simulator.run_scenario("smoke", until_seconds=5)
    second_half = simulator.run_scenario(
        "smoke",
        first_half.checkpoint,
    )

    def throw_events(run):
        return [
            event for event in run.result.events if event.kind == "fish_throw_resolved"
        ]

    continuous_throws = throw_events(continuous)
    segmented_throws = throw_events(first_half) + throw_events(second_half)
    assert segmented_throws == continuous_throws
    assert [event.time_seconds for event in continuous_throws] == list(range(1, 11))
    assert all(
        event.details["strength_source"] == "player_state_snapshot"
        and event.details["input_strength"] == "50"
        for event in continuous_throws
    )
    assert second_half.checkpoint.engine_state == continuous.checkpoint.engine_state
    assert second_half.checkpoint.next_throw_id == 10
    assert second_half.checkpoint.event_counters == {
        "active_throw_resolved": 10,
        "fish_hall_settled": 10,
    }
    assert continuous.result.timeline[0].total_cps == "0"
    assert all(row.total_cps != "0" for row in continuous.result.timeline[1:])
    previous_money = "0"
    previous_cps = "0"
    for row in continuous.result.timeline[1:]:
        expected_money = (
            SimNumber.parse(previous_money) + SimNumber.parse(previous_cps)
        ).to_decimal_string()
        assert SimNumber.parse(row.resources["money"]) == SimNumber.parse(
            expected_money
        )
        previous_money = row.resources["money"]
        previous_cps = row.total_cps
    assert (
        first_half.result.timeline + second_half.result.timeline[1:]
        == continuous.result.timeline
    )


def test_weighted_manual_throw_behavior_replays_across_mid_action_checkpoint(
    tmp_path: Path,
) -> None:
    raw = ConfigLoader.load(
        "projects/fish/economy.yaml",
        "projects/fish/luban_exports",
    )
    model = ModelBuilder.build(raw)
    profile = model.player_profiles["default"]
    profile.behavior_weights = {"manual_throw": SimNumber.one()}
    profile.behavior_durations = {"manual_throw": {"type": "fixed", "seconds": 3}}
    simulator = FishEconomySimulator(
        model,
        _snapshot(tmp_path),
        model_digest="sha256:" + ("b" * 64),
    )

    continuous = simulator.run_scenario("smoke")
    first = simulator.run_scenario("smoke", until_seconds=5)
    resumed = simulator.run_scenario("smoke", first.checkpoint)

    def behavior_events(run):
        return [
            event for event in run.result.events if event.kind != "fish_engine_ready"
        ]

    assert behavior_events(first) + behavior_events(resumed) == (
        behavior_events(continuous)
    )
    assert (
        first.result.timeline + resumed.result.timeline[1:]
        == continuous.result.timeline
    )
    assert resumed.checkpoint.engine_state == continuous.checkpoint.engine_state
    assert resumed.checkpoint.behavior_state == (continuous.checkpoint.behavior_state)
    assert resumed.checkpoint.event_counters == (continuous.checkpoint.event_counters)
    assert first.checkpoint.behavior_state["active"] == {
        "sequence_id": 1,
        "profile_id": "default",
        "behavior_id": "manual_throw",
        "target_id": None,
        "duration_seconds": 3,
        "started_at_seconds": 3,
        "completes_at_seconds": 6,
    }


def test_upgrade_behavior_settles_old_income_before_level_change(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot(tmp_path)
    throw_config = ProductionThrowConfig.from_mapping(
        {
            "initial_strength": "50",
            "interval_seconds": 1,
            "regular_luck_multiplier": "1",
            "bonus_base_luck": "1",
            "max_bonus_layers": 4,
        }
    )
    throw_adapter = FishThrowDataAdapter(
        snapshot,
        bonus_base_luck=1,
        max_bonus_layers=4,
    )
    hall_adapter = FishHallDataAdapter(snapshot)
    adapter = FishBehaviorAdapter(
        throw_adapter=throw_adapter,
        hall_adapter=hall_adapter,
        trash_adapter=FishTrashDataAdapter(snapshot),
        barbell_adapter=FishBarbellDataAdapter(snapshot),
        throw_config=throw_config,
    )
    state = PlayerState.new(
        initial_torpedo_id=1,
        initial_strength=50,
        initial_trash_man_realm_id=1,
    )
    resolution = throw_adapter.resolve(
        ProductionThrowRequest(
            root_random_seed=9,
            throw_id=0,
            strength=50,
            torpedo_id=1,
        )
    )
    state = apply_throw_resolution(
        state,
        resolution,
        adapter=throw_adapter,
        hall_adapter=hall_adapter,
    ).state
    state.wallet.money = BigNumberDTO.from_value("100")
    profile = ConfigLoader.load_rules_only(
        "projects/fish/economy.yaml"
    ).rules.player_profiles["default"]
    profile.behavior_weights = {"upgrade_fish": SimNumber.one()}
    profile.behavior_durations = {"upgrade_fish": {"type": "fixed", "seconds": 4}}
    profile.behavior_target_policies = {"upgrade_fish": "random_affordable"}
    decision = BehaviorScheduler(23).decide(
        adapter.candidates(state, profile),
        adapter.behavior_profile(profile),
        sequence_id=0,
        started_at_seconds=0,
    )
    old_income = hall_adapter.snapshot(state).total_income_per_second

    completion = adapter.complete(
        state,
        decision,
        root_random_seed=23,
        next_throw_id=1,
    )

    upgraded = completion.state.fish.items[0]
    price = hall_adapter.upgrade_price(state.fish.items[0])
    assert upgraded.level == 2
    assert completion.event_kind == "fish_upgraded"
    assert (
        completion.details["fish_hall_money_added"]
        == (old_income * SimNumber.parse(4)).to_decimal_string()
    )
    assert completion.state.wallet.money.to_sim_number() == (
        SimNumber.parse(100) + old_income * SimNumber.parse(4) - price
    )


def test_upgrade_behavior_requires_explicit_known_target_policy(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot(tmp_path)
    config = ProductionThrowConfig.from_mapping(
        {
            "initial_strength": "50",
            "interval_seconds": 1,
            "regular_luck_multiplier": "1",
            "bonus_base_luck": "1",
            "max_bonus_layers": 4,
        }
    )
    adapter = FishBehaviorAdapter(
        throw_adapter=FishThrowDataAdapter(
            snapshot,
            bonus_base_luck=1,
            max_bonus_layers=4,
        ),
        hall_adapter=FishHallDataAdapter(snapshot),
        trash_adapter=FishTrashDataAdapter(snapshot),
        barbell_adapter=FishBarbellDataAdapter(snapshot),
        throw_config=config,
    )
    profile = ConfigLoader.load_rules_only(
        "projects/fish/economy.yaml"
    ).rules.player_profiles["default"]
    profile.behavior_weights = {"upgrade_fish": SimNumber.one()}
    profile.behavior_durations = {"upgrade_fish": {"type": "fixed", "seconds": 1}}

    with pytest.raises(FishBehaviorConfigError, match="explicit target"):
        adapter.behavior_profile(profile)

    profile.behavior_target_policies = {"upgrade_fish": "highest_income"}
    with pytest.raises(FishBehaviorConfigError, match="unknown"):
        adapter.behavior_profile(profile)


def test_fish_hall_upgrade_behavior_is_targetless_and_ignores_fish_count(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot(tmp_path)
    config = ProductionThrowConfig.from_mapping(
        {
            "initial_strength": "50",
            "interval_seconds": 1,
            "regular_luck_multiplier": "1",
            "bonus_base_luck": "1",
            "max_bonus_layers": 4,
        }
    )
    throw_adapter = FishThrowDataAdapter(
        snapshot,
        bonus_base_luck=1,
        max_bonus_layers=4,
    )
    hall_adapter = FishHallDataAdapter(snapshot)
    adapter = FishBehaviorAdapter(
        throw_adapter=throw_adapter,
        hall_adapter=hall_adapter,
        trash_adapter=FishTrashDataAdapter(snapshot),
        barbell_adapter=FishBarbellDataAdapter(snapshot),
        throw_config=config,
    )
    profile = ConfigLoader.load_rules_only(
        "projects/fish/economy.yaml"
    ).rules.player_profiles["default"]
    profile.behavior_weights = {
        UPGRADE_FISH_HALL_BEHAVIOR_ID: SimNumber.one()
    }
    profile.behavior_durations = {
        UPGRADE_FISH_HALL_BEHAVIOR_ID: {
            "type": "fixed",
            "seconds": 4,
        }
    }

    empty_state = PlayerState.new(
        initial_torpedo_id=1,
        initial_strength=50,
        initial_trash_man_realm_id=1,
    )
    empty_state.wallet.material = BigNumberDTO.from_value(100)
    empty_candidate = adapter.candidates(empty_state, profile)[0]
    empty_decision = BehaviorScheduler(23).decide(
        (empty_candidate,),
        adapter.behavior_profile(profile),
        sequence_id=0,
        started_at_seconds=0,
    )

    resolution = throw_adapter.resolve(
        ProductionThrowRequest(
            root_random_seed=9,
            throw_id=0,
            strength=50,
            torpedo_id=1,
        )
    )
    state_with_fish = apply_throw_resolution(
        empty_state,
        resolution,
        adapter=throw_adapter,
        hall_adapter=hall_adapter,
    ).state
    populated_candidate = adapter.candidates(state_with_fish, profile)[0]
    populated_decision = BehaviorScheduler(23).decide(
        (populated_candidate,),
        adapter.behavior_profile(profile),
        sequence_id=0,
        started_at_seconds=0,
    )

    assert empty_candidate.available
    assert empty_candidate.targets == ()
    assert populated_candidate.available
    assert populated_candidate.targets == ()
    assert populated_candidate == empty_candidate
    assert populated_decision == empty_decision
    assert empty_decision.target_id is None

    profile.behavior_target_policies = {
        UPGRADE_FISH_HALL_BEHAVIOR_ID: "random_affordable"
    }
    with pytest.raises(FishBehaviorConfigError, match="unsupported target"):
        adapter.behavior_profile(profile)


def test_fish_hall_upgrade_candidate_requires_material_and_remaining_level(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot(tmp_path)
    config = ProductionThrowConfig.from_mapping(
        {
            "initial_strength": "50",
            "interval_seconds": 1,
            "regular_luck_multiplier": "1",
            "bonus_base_luck": "1",
            "max_bonus_layers": 4,
        }
    )
    adapter = FishBehaviorAdapter(
        throw_adapter=FishThrowDataAdapter(
            snapshot,
            bonus_base_luck=1,
            max_bonus_layers=4,
        ),
        hall_adapter=FishHallDataAdapter(snapshot),
        trash_adapter=FishTrashDataAdapter(snapshot),
        barbell_adapter=FishBarbellDataAdapter(snapshot),
        throw_config=config,
    )
    profile = ConfigLoader.load_rules_only(
        "projects/fish/economy.yaml"
    ).rules.player_profiles["default"]
    profile.behavior_weights = {
        UPGRADE_FISH_HALL_BEHAVIOR_ID: SimNumber.one()
    }
    profile.behavior_durations = {
        UPGRADE_FISH_HALL_BEHAVIOR_ID: {
            "type": "fixed",
            "seconds": 1,
        }
    }
    state = PlayerState.new(
        initial_torpedo_id=1,
        initial_strength=50,
        initial_trash_man_realm_id=1,
    )

    assert not adapter.candidates(state, profile)[0].available

    state.wallet.material = BigNumberDTO.from_value(100)
    assert adapter.candidates(state, profile)[0].available

    maxed = state.copy()
    maxed.fish_hall.upgrade_level = 1
    assert not adapter.candidates(maxed, profile)[0].available


def test_fish_hall_upgrade_checkpoint_does_not_pay_or_reselect_mid_behavior(
    tmp_path: Path,
) -> None:
    raw = ConfigLoader.load(
        "projects/fish/economy.yaml",
        "projects/fish/luban_exports",
    )
    model = ModelBuilder.build(raw)
    model.scenarios["smoke"].duration_hours = 4 / 3600
    profile = model.player_profiles["default"]
    profile.behavior_weights = {
        UPGRADE_FISH_HALL_BEHAVIOR_ID: SimNumber.one()
    }
    profile.behavior_durations = {
        UPGRADE_FISH_HALL_BEHAVIOR_ID: {
            "type": "fixed",
            "seconds": 4,
        }
    }
    snapshot = _snapshot(tmp_path)
    model_digest = "sha256:" + ("e" * 64)
    simulator = FishEconomySimulator(
        model,
        snapshot,
        model_digest=model_digest,
    )
    initial_state = PlayerState.new(
        initial_torpedo_id=1,
        initial_strength=50,
        initial_trash_man_realm_id=1,
    )
    initial_state.wallet.material = BigNumberDTO.from_value(100)
    initial_checkpoint = FishCheckpointCodec.new(
        initial_state,
        model_digest=model_digest,
        scenario_id="smoke",
        profile_id="default",
        root_random_seed=model.config.random_seed,
        behavior_state=BehaviorRuntimeState().to_dict(),
        engine_runtime_state=FishProductionRuntime().to_dict(),
        context=FishHallDataAdapter(snapshot).validation_context(),
    )

    continuous = simulator.run_scenario("smoke", initial_checkpoint)
    first = simulator.run_scenario(
        "smoke",
        initial_checkpoint,
        until_seconds=2,
    )
    resumed = simulator.run_scenario("smoke", first.checkpoint)

    assert first.checkpoint.engine_state["fishHall"]["upgradeLevel"] == 0
    assert first.checkpoint.engine_state["wallet"]["material"] == (
        initial_checkpoint.engine_state["wallet"]["material"]
    )
    assert first.checkpoint.event_counters == {
        "behavior_decisions_started": 1
    }
    assert first.checkpoint.behavior_state["active"] == {
        "sequence_id": 0,
        "profile_id": "default",
        "behavior_id": UPGRADE_FISH_HALL_BEHAVIOR_ID,
        "target_id": None,
        "duration_seconds": 4,
        "started_at_seconds": 0,
        "completes_at_seconds": 4,
    }
    assert resumed.checkpoint.engine_state == continuous.checkpoint.engine_state
    assert resumed.checkpoint.behavior_state == (
        continuous.checkpoint.behavior_state
    )
    assert resumed.checkpoint.event_counters == (
        continuous.checkpoint.event_counters
    )
    assert continuous.checkpoint.engine_state["fishHall"]["upgradeLevel"] == 1
    assert continuous.checkpoint.engine_state["wallet"]["material"]["sign"] == 0
    assert continuous.checkpoint.event_counters == {
        "behavior_decisions_started": 1,
        "behavior_completed": 1,
        f"{UPGRADE_FISH_HALL_BEHAVIOR_ID}_completed": 1,
        "fish_hall_settled": 1,
    }
    upgrade_event = next(
        event
        for event in continuous.result.events
        if event.kind == "fish_hall_upgraded"
    )
    assert upgrade_event.time_seconds == 4
    assert upgrade_event.item_id == "fish_hall:1"
    assert upgrade_event.details["behavior_target_id"] == ""
    assert (
        upgrade_event.details["fish_hall_settlement_to_seconds"]
        == "4"
    )
    assert upgrade_event.details["fish_hall_upgrade_price_resource"] == "material"


def test_strength_rebirth_behavior_settles_old_multiplier_before_reset(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot(tmp_path)
    config = ProductionThrowConfig.from_mapping(
        {
            "initial_strength": "50",
            "interval_seconds": 1,
            "regular_luck_multiplier": "1",
            "bonus_base_luck": "1",
            "max_bonus_layers": 4,
        }
    )
    hall_adapter = FishHallDataAdapter(snapshot)
    adapter = FishBehaviorAdapter(
        throw_adapter=FishThrowDataAdapter(
            snapshot,
            bonus_base_luck=1,
            max_bonus_layers=4,
        ),
        hall_adapter=hall_adapter,
        trash_adapter=FishTrashDataAdapter(snapshot),
        barbell_adapter=FishBarbellDataAdapter(snapshot),
        throw_config=config,
    )
    profile = ConfigLoader.load_rules_only(
        "projects/fish/economy.yaml"
    ).rules.player_profiles["default"]
    profile.behavior_weights = {
        STRENGTH_REBIRTH_BEHAVIOR_ID: SimNumber.one()
    }
    profile.behavior_durations = {
        STRENGTH_REBIRTH_BEHAVIOR_ID: {
            "type": "fixed",
            "seconds": 4,
        }
    }
    state = PlayerState.new(
        initial_torpedo_id=1,
        initial_strength=1000,
        initial_trash_man_realm_id=1,
    )
    state.fish.items = [FishInstance(1, 1, 7, 1, 100, 1)]
    state.fish.next_instance_id = 2
    candidate = adapter.candidates(state, profile)[0]
    decision = BehaviorScheduler(23).decide(
        (candidate,),
        adapter.behavior_profile(profile),
        sequence_id=0,
        started_at_seconds=0,
    )

    completion = adapter.complete(
        state,
        decision,
        root_random_seed=23,
        next_throw_id=0,
    )

    assert candidate.available
    assert candidate.targets == ()
    assert completion.event_kind == "strength_reborn"
    assert completion.item_id == "strength_rebirth:1"
    assert completion.state.wallet.money.to_sim_number() == SimNumber.parse(40)
    assert completion.state.wallet.strength.to_sim_number() == SimNumber.zero()
    assert completion.state.rebirth.strength_completed_count == 1
    assert completion.details["fish_hall_money_added"] == "40"
    assert completion.details["strength_rebirth_multiplier_before"] == "1"
    assert completion.details["strength_rebirth_multiplier_after"] == "2"
    assert (
        hall_adapter.snapshot(
            completion.state
        ).total_income_per_second
        == SimNumber.parse(20)
    )

    below_requirement = state.copy()
    below_requirement.wallet.strength = BigNumberDTO.from_value(999)
    assert not adapter.candidates(below_requirement, profile)[0].available
    maxed = state.copy()
    maxed.rebirth.strength_completed_count = 2
    assert not adapter.candidates(maxed, profile)[0].available


def test_strength_rebirth_checkpoint_does_not_reset_mid_behavior(
    tmp_path: Path,
) -> None:
    raw = ConfigLoader.load(
        "projects/fish/economy.yaml",
        "projects/fish/luban_exports",
    )
    model = ModelBuilder.build(raw)
    model.scenarios["smoke"].duration_hours = 4 / 3600
    profile = model.player_profiles["default"]
    profile.behavior_weights = {
        STRENGTH_REBIRTH_BEHAVIOR_ID: SimNumber.one()
    }
    profile.behavior_durations = {
        STRENGTH_REBIRTH_BEHAVIOR_ID: {
            "type": "fixed",
            "seconds": 4,
        }
    }
    snapshot = _snapshot(tmp_path)
    model_digest = "sha256:" + ("7" * 64)
    simulator = FishEconomySimulator(
        model,
        snapshot,
        model_digest=model_digest,
    )
    initial_state = PlayerState.new(
        initial_torpedo_id=1,
        initial_strength=1000,
        initial_trash_man_realm_id=1,
    )
    initial_checkpoint = FishCheckpointCodec.new(
        initial_state,
        model_digest=model_digest,
        scenario_id="smoke",
        profile_id="default",
        root_random_seed=model.config.random_seed,
        behavior_state=BehaviorRuntimeState().to_dict(),
        engine_runtime_state=FishProductionRuntime().to_dict(),
        context=FishHallDataAdapter(snapshot).validation_context(),
    )

    continuous = simulator.run_scenario("smoke", initial_checkpoint)
    first = simulator.run_scenario(
        "smoke",
        initial_checkpoint,
        until_seconds=2,
    )
    resumed = simulator.run_scenario("smoke", first.checkpoint)

    assert first.checkpoint.engine_state["wallet"]["strength"] == (
        initial_checkpoint.engine_state["wallet"]["strength"]
    )
    assert first.checkpoint.engine_state["rebirth"][
        "strengthCompletedCount"
    ] == 0
    assert first.checkpoint.engine_state["production"]["lastSettledAt"] == 0
    assert first.checkpoint.event_counters == {
        "behavior_decisions_started": 1
    }
    assert first.checkpoint.behavior_state["active"] == {
        "sequence_id": 0,
        "profile_id": "default",
        "behavior_id": STRENGTH_REBIRTH_BEHAVIOR_ID,
        "target_id": None,
        "duration_seconds": 4,
        "started_at_seconds": 0,
        "completes_at_seconds": 4,
    }
    assert resumed.checkpoint.engine_state == continuous.checkpoint.engine_state
    assert resumed.checkpoint.behavior_state == (
        continuous.checkpoint.behavior_state
    )
    assert resumed.checkpoint.event_counters == (
        continuous.checkpoint.event_counters
    )
    assert continuous.checkpoint.engine_state["rebirth"][
        "strengthCompletedCount"
    ] == 1
    assert continuous.checkpoint.engine_state["wallet"]["strength"][
        "sign"
    ] == 0
    assert continuous.checkpoint.event_counters == {
        "behavior_decisions_started": 1,
        "behavior_completed": 1,
        f"{STRENGTH_REBIRTH_BEHAVIOR_ID}_completed": 1,
        "fish_hall_settled": 1,
    }
    event = next(
        event
        for event in continuous.result.events
        if event.kind == "strength_reborn"
    )
    assert event.time_seconds == 4
    assert event.item_id == "strength_rebirth:1"
    assert event.details["behavior_target_id"] == ""


def test_barbell_synthesis_behavior_uses_explicit_affordable_unowned_targets(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot(tmp_path)
    config = ProductionThrowConfig.from_mapping(
        {
            "initial_strength": "50",
            "interval_seconds": 1,
            "regular_luck_multiplier": "1",
            "bonus_base_luck": "1",
            "max_bonus_layers": 4,
        }
    )
    adapter = FishBehaviorAdapter(
        throw_adapter=FishThrowDataAdapter(
            snapshot,
            bonus_base_luck=1,
            max_bonus_layers=4,
        ),
        hall_adapter=FishHallDataAdapter(snapshot),
        trash_adapter=FishTrashDataAdapter(snapshot),
        barbell_adapter=FishBarbellDataAdapter(snapshot),
        throw_config=config,
    )
    profile = ConfigLoader.load_rules_only(
        "projects/fish/economy.yaml"
    ).rules.player_profiles["default"]
    profile.behavior_weights = {
        SYNTHESIZE_BARBELL_BEHAVIOR_ID: SimNumber.one()
    }
    profile.behavior_durations = {
        SYNTHESIZE_BARBELL_BEHAVIOR_ID: {
            "type": "fixed",
            "seconds": 1,
        }
    }
    state = PlayerState.new(
        initial_torpedo_id=1,
        initial_trash_man_realm_id=1,
    )
    state.wallet.material = BigNumberDTO.from_value(20)

    with pytest.raises(FishBehaviorConfigError, match="explicit target"):
        adapter.behavior_profile(profile)

    profile.behavior_target_policies = {
        SYNTHESIZE_BARBELL_BEHAVIOR_ID: "random_affordable"
    }
    candidate = adapter.candidates(state, profile)[0]
    assert candidate.available
    assert [target.target_id for target in candidate.targets] == ["1"]

    state.barbell.owned = [OwnedBarbell(1, 1)]
    state.barbell.equipped_id = 1
    state.wallet.material = BigNumberDTO.from_value(75)
    candidate = adapter.candidates(state, profile)[0]
    assert [target.target_id for target in candidate.targets] == ["2"]


def test_barbell_synthesis_settles_old_equipment_before_auto_equip(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot(tmp_path)
    adapter = FishBehaviorAdapter(
        throw_adapter=FishThrowDataAdapter(
            snapshot,
            bonus_base_luck=1,
            max_bonus_layers=4,
        ),
        hall_adapter=FishHallDataAdapter(snapshot),
        trash_adapter=FishTrashDataAdapter(snapshot),
        barbell_adapter=FishBarbellDataAdapter(snapshot),
        throw_config=ProductionThrowConfig.from_mapping(
            {
                "initial_strength": "50",
                "interval_seconds": 1,
                "regular_luck_multiplier": "1",
                "bonus_base_luck": "1",
                "max_bonus_layers": 4,
            }
        ),
    )
    state = PlayerState.new(
        initial_torpedo_id=1,
        initial_strength=0,
        initial_trash_man_realm_id=1,
    )
    state.wallet.material = BigNumberDTO.from_value(75)
    state.barbell.owned = [OwnedBarbell(1, 1)]
    state.barbell.equipped_id = 1
    decision = BehaviorDecision(
        sequence_id=0,
        profile_id="default",
        behavior_id=SYNTHESIZE_BARBELL_BEHAVIOR_ID,
        target_id="2",
        duration_seconds=4,
        started_at_seconds=0,
        completes_at_seconds=4,
    )

    completion = adapter.complete(
        state,
        decision,
        root_random_seed=7,
        next_throw_id=0,
    )

    assert completion.details["barbell_strength_added"] == "8"
    assert (
        completion.state.wallet.strength.to_sim_number()
        == SimNumber.parse(8)
    )
    assert completion.state.wallet.material.to_sim_number().is_zero()
    assert completion.state.barbell.equipped_id == 2
    assert completion.details[
        "barbell_strength_per_second_before_command"
    ] == "2"
    assert completion.details[
        "barbell_strength_per_second_after_synthesis"
    ] == "5"


def test_barbell_synthesis_checkpoint_does_not_pay_or_produce_mid_behavior(
    tmp_path: Path,
) -> None:
    raw = ConfigLoader.load(
        "projects/fish/economy.yaml",
        "projects/fish/luban_exports",
    )
    model = ModelBuilder.build(raw)
    model.scenarios["smoke"].duration_hours = 4 / 3600
    profile = model.player_profiles["default"]
    profile.behavior_weights = {
        SYNTHESIZE_BARBELL_BEHAVIOR_ID: SimNumber.one()
    }
    profile.behavior_durations = {
        SYNTHESIZE_BARBELL_BEHAVIOR_ID: {
            "type": "fixed",
            "seconds": 4,
        }
    }
    profile.behavior_target_policies = {
        SYNTHESIZE_BARBELL_BEHAVIOR_ID: "random_affordable"
    }
    snapshot = _snapshot(tmp_path)
    model_digest = "sha256:" + ("f" * 64)
    simulator = FishEconomySimulator(
        model,
        snapshot,
        model_digest=model_digest,
    )
    initial_state = PlayerState.new(
        initial_torpedo_id=1,
        initial_strength=0,
        initial_trash_man_realm_id=1,
    )
    initial_state.wallet.material = BigNumberDTO.from_value(20)
    initial_checkpoint = FishCheckpointCodec.new(
        initial_state,
        model_digest=model_digest,
        scenario_id="smoke",
        profile_id="default",
        root_random_seed=model.config.random_seed,
        behavior_state=BehaviorRuntimeState().to_dict(),
        engine_runtime_state=FishProductionRuntime().to_dict(),
        context=FishHallDataAdapter(snapshot).validation_context(),
    )

    continuous = simulator.run_scenario("smoke", initial_checkpoint)
    first = simulator.run_scenario(
        "smoke",
        initial_checkpoint,
        until_seconds=2,
    )
    resumed = simulator.run_scenario("smoke", first.checkpoint)

    assert first.checkpoint.engine_state["barbell"] == {
        "equippedId": 0,
        "owned": [],
    }
    assert first.checkpoint.engine_state["wallet"]["material"] == (
        initial_checkpoint.engine_state["wallet"]["material"]
    )
    assert first.checkpoint.engine_state["wallet"]["strength"]["sign"] == 0
    assert resumed.checkpoint.engine_state == continuous.checkpoint.engine_state
    assert resumed.checkpoint.behavior_state == (
        continuous.checkpoint.behavior_state
    )
    assert resumed.checkpoint.event_counters == (
        continuous.checkpoint.event_counters
    )
    assert continuous.checkpoint.engine_state["barbell"] == {
        "equippedId": 1,
        "owned": [{"barbellId": 1, "count": 1}],
    }
    assert continuous.checkpoint.engine_state["wallet"]["material"]["sign"] == 0
    assert continuous.checkpoint.engine_state["wallet"]["strength"]["sign"] == 0
    assert continuous.checkpoint.event_counters == {
        "behavior_decisions_started": 1,
        "behavior_completed": 1,
        f"{SYNTHESIZE_BARBELL_BEHAVIOR_ID}_completed": 1,
        "fish_hall_settled": 1,
    }
    synthesis_event = next(
        event
        for event in continuous.result.events
        if event.kind == "barbell_synthesized"
    )
    assert synthesis_event.time_seconds == 4
    assert synthesis_event.item_id == "barbell:1"
    assert synthesis_event.details["barbell_strength_added"] == "0"

    final_state = FishCheckpointCodec.decode_state(
        continuous.checkpoint,
        expected_model_digest=model_digest,
        context=FishHallDataAdapter(snapshot).validation_context(),
    )
    post_synthesis = settle_fish_production(
        final_state,
        6,
        hall_adapter=FishHallDataAdapter(snapshot),
        trash_adapter=FishTrashDataAdapter(snapshot),
        barbell_adapter=FishBarbellDataAdapter(snapshot),
        runtime=FishProductionRuntime.from_dict(
            continuous.checkpoint.engine_runtime_state
        ),
    )
    assert post_synthesis.strength_added == SimNumber.parse(4)


def test_initial_torpedo_uses_first_generated_row_without_hardcoded_id(
    tmp_path: Path,
) -> None:
    adapter = FishThrowDataAdapter(
        _snapshot(tmp_path, initial_torpedo_id=7),
        bonus_base_luck=1,
        max_bonus_layers=4,
    )

    assert adapter.initial_torpedo_id == 7


def test_trash_luck_uses_inclusive_power_upper_bound(tmp_path: Path) -> None:
    adapter = FishThrowDataAdapter(
        _snapshot(tmp_path),
        bonus_base_luck=1,
        max_bonus_layers=4,
    )

    at_endpoint = map_torpedo_power_to_trash_luck(50, adapter.trash_luck_pools)
    above_endpoint = map_torpedo_power_to_trash_luck(
        50.000001, adapter.trash_luck_pools
    )

    assert at_endpoint.pool_id == 1
    assert at_endpoint.base_trash_luck == 3
    assert above_endpoint.pool_id == 2
    assert above_endpoint.base_trash_luck == pytest.approx(5, abs=1e-12)


@pytest.mark.external_data
def test_current_production_snapshot_resolves_one_throw() -> None:
    snapshot = FishDataLoader(
        GeneratedLubanProvider("E:/fish-oasis/igess_export/python/schema.py")
    ).load(
        "E:/fish-oasis/igess_export/json",
        production_data=True,
        required_tables=FISH_REQUIRED_TABLES,
    )
    adapter = FishThrowDataAdapter(
        snapshot,
        bonus_base_luck=1,
        max_bonus_layers=4,
    )

    resolution = adapter.resolve(
        ProductionThrowRequest(
            root_random_seed=20260626,
            throw_id=0,
            strength=50,
            torpedo_id=1,
        )
    )

    assert len(adapter.rules.strength_luck_pools) == 13
    assert len(adapter.trash_luck_pools) == 13
    assert len(adapter.rules.fish_pool) == 121
    assert len(adapter.rules.trash_pool) == 39
    assert resolution.outcome.strength_luck.base_fish_luck == 3
    assert resolution.trash_luck_mapping.base_trash_luck == 3
    assert resolution.outcome.fish_reward.id
    assert resolution.outcome.trash_reward.id
    expected_fish = next(
        row
        for row in snapshot.table("tbfish")
        if row.id == int(resolution.outcome.fish_reward.id)
    )
    assert resolution.fish_weight_gram == expected_fish.weight
    assert resolution.fish_weight_gram > 0

    trash_adapter = FishTrashDataAdapter(snapshot)
    first_trash = snapshot.table("tbtrash")[0]
    first_realm = snapshot.table("tbtrashmanrealm")[0]
    assert (
        trash_adapter.trash_rule(first_trash.id).base_decompose_seconds
        == first_trash.baseDecomposeSeconds
    )
    assert trash_adapter.trash_rule(
        first_trash.id
    ).base_material_per_second == SimNumber.parse("2")
    assert trash_adapter.initial_realm_id == first_realm.id
    assert trash_adapter.realm_speed(first_realm.id) == SimNumber.parse(
        first_realm.decomposeSpeedMultiplier
    )
    assert trash_adapter.cultivation_seconds_to_next_realm(first_realm.id) == int(
        first_realm.cultivationSecondsToNextRealm
    )
    assert trash_adapter.material_output_multiplier(1) == SimNumber.parse("2")

    barbell_adapter = FishBarbellDataAdapter(snapshot)
    assert len(barbell_adapter.rules) == 15
    assert barbell_adapter.rule(1).strength_per_exercise == SimNumber.parse(2)
    assert barbell_adapter.rule(1).time_cost_seconds == 1
    assert barbell_adapter.rule(1).price == SimNumber.parse(20)
    assert barbell_adapter.strength_per_second(15) == SimNumber.parse(
        5000000
    )

    hall_adapter = FishHallDataAdapter(snapshot)
    assert hall_adapter.max_hall_upgrade_level == 20
    assert hall_adapter.max_strength_rebirth_count == 10
    assert hall_adapter.strength_rebirth_multiplier(0) == SimNumber.one()
    first_strength_rebirth = hall_adapter.next_strength_rebirth_rule(0)
    assert first_strength_rebirth.completed_count == 1
    assert first_strength_rebirth.strength_requirement == SimNumber.parse(
        "1000"
    )
    assert (
        first_strength_rebirth.fish_hall_output_multiplier
        == SimNumber.parse(2)
    )
    final_strength_rebirth = hall_adapter.strength_rebirth_rule(10)
    assert final_strength_rebirth.strength_requirement == SimNumber.parse(
        "1e12"
    )
    assert (
        final_strength_rebirth.fish_hall_output_multiplier
        == SimNumber.parse(11)
    )
    production_rebirth_state = PlayerState.new(
        initial_torpedo_id=adapter.initial_torpedo_id,
        initial_strength=first_strength_rebirth.strength_requirement,
        initial_trash_man_realm_id=trash_adapter.initial_realm_id,
    )
    production_rebirth = apply_strength_rebirth(
        production_rebirth_state,
        hall_adapter=hall_adapter,
    )
    assert production_rebirth.to_completed_count == 1
    assert (
        production_rebirth.state.rebirth.strength_completed_count
        == 1
    )
    assert production_rebirth.state.wallet.strength.to_sim_number() == (
        SimNumber.zero()
    )
    assert (
        production_rebirth.fish_hall_after.strength_rebirth_multiplier
        == SimNumber.parse(2)
    )
    assert hall_adapter.capacity(0) == 10
    assert hall_adapter.hall_upgrade_price(0) == SimNumber.parse("5000000")
    assert hall_adapter.capacity(19) == 29
    assert hall_adapter.hall_upgrade_price(19) == SimNumber.parse(
        "50000000000000"
    )
    assert hall_adapter.capacity(20) == 30
    assert hall_adapter.can_upgrade_hall(20) is False
    with pytest.raises(FishDataError, match="already at max"):
        hall_adapter.hall_upgrade_price(20)
    state = PlayerState.new(initial_torpedo_id=1)
    state.fish.items = [
        FishInstance(
            instance_id=1,
            fish_id=int(resolution.outcome.fish_reward.id),
            mutation_id=resolution.fish_mutation_id,
            level=1,
            weight_gram=resolution.fish_weight_gram,
            hall_slot=1,
        )
    ]
    state.fish.next_instance_id = 2
    price = hall_adapter.upgrade_price(state.fish.items[0])
    state.wallet.money = state.wallet.money.from_value(price * 2)

    application = upgrade_fish(state, 1, hall_adapter=hall_adapter)

    assert application.price == application.income_before.base_money_per_second
    assert application.to_level == 2
    assert application.income_after.income_per_second == (
        application.income_before.income_per_second * SimNumber.parse("1.25")
    )
