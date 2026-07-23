from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from igess.builder import ModelBuilder
from igess.fish_commands import (
    FishCommandError,
    apply_throw_resolution,
    lock_throw_request,
)
from igess.fish_data import (
    FISH_REQUIRED_TABLES,
    FishDataError,
    FishDataLoader,
    FishDataSnapshot,
    GeneratedLubanProvider,
)
from igess.fish_state import PlayerState, TrashStock
from igess.fish_simulator import FishEconomySimulator
from igess.fish_throw import map_torpedo_power_to_trash_luck
from igess.fish_throw_data import (
    FishThrowDataAdapter,
    ProductionThrowConfig,
    ProductionThrowRequest,
)
from igess.loader import ConfigLoader


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
                name="鱼1",
                rarityId=1,
                Denominator=_big(1),
                weight=1250,
            ),
            SimpleNamespace(
                id=2,
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
                rarityId=1,
                Denominator=_big(1),
            ),
            SimpleNamespace(
                id=2,
                name="废料2",
                rarityId=2,
                Denominator=_big(10),
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
    assert resolution.fish_weight_gram == {
        "1": 1250,
        "2": 800,
    }[resolution.outcome.fish_reward.id]
    assert resolution.fish_mutation_id == (
        7
        if resolution.outcome.mutation is None
        else int(resolution.outcome.mutation.id)
    )
    assert "reward_application" not in resolution.event_details()


def test_throw_application_atomically_persists_rewards(tmp_path: Path) -> None:
    adapter = FishThrowDataAdapter(
        _snapshot(tmp_path),
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
    state = PlayerState.new(initial_torpedo_id=1)
    original = state.to_dict()

    application = apply_throw_resolution(
        state,
        resolution,
        adapter=adapter,
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
    assert fish.hall_slot == 0
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
    assert application.event_details() == {
        "reward_application": "applied_to_player_state",
        "fish_instance_id": "1",
        "trash_stock_count": "1",
        "player_state_revision": "1",
    }

    committed = application.state.to_dict()
    with pytest.raises(FishCommandError, match="throw_id"):
        apply_throw_resolution(
            application.state,
            resolution,
            adapter=adapter,
        )
    assert application.state.to_dict() == committed


def test_throw_application_increments_existing_trash_stock(
    tmp_path: Path,
) -> None:
    adapter = FishThrowDataAdapter(
        _snapshot(tmp_path),
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
    state.trash_man.processing.stocks = [
        TrashStock(trash_id=trash_id, count=4)
    ]

    application = apply_throw_resolution(
        state,
        resolution,
        adapter=adapter,
    )

    assert application.trash_stock_count == 5
    assert application.state.trash_man.processing.stocks == [
        TrashStock(trash_id=trash_id, count=5)
    ]
    assert state.trash_man.processing.stocks == [
        TrashStock(trash_id=trash_id, count=4)
    ]


def test_throw_application_rejects_changed_selected_torpedo(
    tmp_path: Path,
) -> None:
    adapter = FishThrowDataAdapter(
        _snapshot(tmp_path),
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
        apply_throw_resolution(state, resolution, adapter=adapter)

    assert state.to_dict() == original


def test_throw_application_rejects_non_authoritative_resolution(
    tmp_path: Path,
) -> None:
    adapter = FishThrowDataAdapter(
        _snapshot(tmp_path),
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
        apply_throw_resolution(state, altered, adapter=adapter)

    assert state.fish.items == []

    malformed = replace(resolution, request=None)  # type: ignore[arg-type]
    with pytest.raises(FishCommandError, match="authoritative"):
        apply_throw_resolution(state, malformed, adapter=adapter)

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
            event
            for event in run.result.events
            if event.kind == "fish_throw_resolved"
        ]

    continuous_throws = throw_events(continuous)
    segmented_throws = throw_events(first_half) + throw_events(second_half)
    assert segmented_throws == continuous_throws
    assert [event.time_seconds for event in continuous_throws] == list(
        range(1, 11)
    )
    assert all(
        event.details["strength_source"] == "player_state_snapshot"
        and event.details["input_strength"] == "50"
        for event in continuous_throws
    )
    assert second_half.checkpoint.engine_state == continuous.checkpoint.engine_state
    assert second_half.checkpoint.next_throw_id == 10
    assert second_half.checkpoint.event_counters == {
        "active_throw_resolved": 10
    }
    assert (
        first_half.result.timeline + second_half.result.timeline[1:]
        == continuous.result.timeline
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

    at_endpoint = map_torpedo_power_to_trash_luck(
        50, adapter.trash_luck_pools
    )
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
