from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from fish_test_support import _snapshot
from igess.fish_barbell import FishBarbellDataAdapter
from igess.fish_commands import (
    FishCommandError,
    apply_strength_rebirth,
    apply_throw_resolution,
    upgrade_fish,
)
from igess.fish_data import (
    FISH_REQUIRED_TABLES,
    FishDataError,
    FishDataLoader,
    GeneratedLubanProvider,
)
from igess.fish_hall import FishHallDataAdapter
from igess.fish_state import FishInstance, PlayerState, TrashStock
from igess.fish_throw import map_torpedo_power_to_trash_luck
from igess.fish_throw_data import (
    FishThrowDataAdapter,
    ProductionThrowRequest,
)
from igess.fish_trash import FishTrashDataAdapter
from igess.numbers import SimNumber


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
