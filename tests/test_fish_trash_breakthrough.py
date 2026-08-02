from __future__ import annotations

from pathlib import Path

import pytest

from fish_test_support import _big, _snapshot
from igess.behavior import BehaviorRuntimeState
from igess.builder import ModelBuilder
from igess.fish_barbell import FishBarbellDataAdapter
from igess.fish_behavior import (
    FUND_TRASH_MAN_BREAKTHROUGH_BEHAVIOR_ID,
)
from igess.fish_commands import (
    FishCommandError,
    fund_trash_man_realm_breakthrough,
)
from igess.fish_data import FishDataError
from igess.fish_hall import FishHallDataAdapter
from igess.fish_production import FishProductionRuntime, settle_fish_production
from igess.fish_simulator import FishEconomySimulator
from igess.fish_behavior_simulator import FishBehaviorSimulator
from igess.fish_state import BigNumberDTO, FishCheckpointCodec, PlayerState, TrashStock
from igess.fish_trash import FishTrashDataAdapter
from igess.loader import ConfigLoader
from igess.numbers import SimNumber


def _state_with_material(amount: int, *, realm_id: int = 1) -> PlayerState:
    state = PlayerState.new(initial_trash_man_realm_id=realm_id)
    state.wallet.material = BigNumberDTO.from_value(
        amount,
        allow_negative=False,
    )
    return state


def test_realm_table_exposes_nonfinal_prices_and_zero_final_sentinel(
    tmp_path: Path,
) -> None:
    adapter = FishTrashDataAdapter(_snapshot(tmp_path))

    assert adapter.material_required_to_next_realm(1) == SimNumber.parse(20)
    assert adapter.material_required_to_next_realm(2) == SimNumber.parse(100)
    assert adapter.material_required_to_next_realm(3) == SimNumber.zero()


def test_realm_table_rejects_non_increasing_nonfinal_prices(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot(tmp_path)
    rows = snapshot.table("tbtrashmanrealm")
    rows[0].materialRequireToNextRealm = _big(100)

    with pytest.raises(FishDataError, match="must strictly increase by id"):
        FishTrashDataAdapter(snapshot)


def test_fund_breakthrough_atomically_pays_and_rejects_invalid_states(
    tmp_path: Path,
) -> None:
    adapter = FishTrashDataAdapter(_snapshot(tmp_path))
    state = _state_with_material(20)
    state.wallet.money = BigNumberDTO.from_value(999)

    funded = fund_trash_man_realm_breakthrough(
        state,
        trash_adapter=adapter,
    )

    assert state.wallet.material.to_sim_number() == SimNumber.parse(20)
    assert state.wallet.money.to_sim_number() == SimNumber.parse(999)
    assert not state.trash_man.breakthrough.active
    assert funded.material_before == SimNumber.parse(20)
    assert funded.material_after == SimNumber.zero()
    assert funded.state.wallet.money.to_sim_number() == SimNumber.parse(999)
    assert funded.price == SimNumber.parse(20)
    assert funded.required_online_seconds == 0
    assert funded.state.trash_man.realm_id == 1
    assert funded.state.trash_man.highest_realm_id == 1
    assert funded.state.trash_man.breakthrough.active
    assert funded.state.trash_man.breakthrough.target_realm_id == 2
    assert funded.state.trash_man.breakthrough.progress_seconds == 0

    for invalid in (
        _state_with_material(19),
        _state_with_material(100, realm_id=3),
    ):
        before = invalid.to_dict()
        with pytest.raises(FishCommandError):
            fund_trash_man_realm_breakthrough(
                invalid,
                trash_adapter=adapter,
            )
        assert invalid.to_dict() == before

    catching_up = _state_with_material(100)
    catching_up.trash_man.highest_realm_id = 2
    before = catching_up.to_dict()
    with pytest.raises(FishCommandError, match="historical realm catch-up"):
        fund_trash_man_realm_breakthrough(
            catching_up,
            trash_adapter=adapter,
        )
    assert catching_up.to_dict() == before

    active = funded.state
    before = active.to_dict()
    with pytest.raises(FishCommandError, match="already active"):
        fund_trash_man_realm_breakthrough(
            active,
            trash_adapter=adapter,
        )
    assert active.to_dict() == before


def test_online_breakthrough_advances_realm_and_offline_only_processes_trash(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot(tmp_path, trash_duration=10)
    hall_adapter = FishHallDataAdapter(snapshot)
    trash_adapter = FishTrashDataAdapter(snapshot)
    state = _state_with_material(100, realm_id=2)
    state.trash_man.processing.active_trash_id = 1
    state.trash_man.processing.stocks = [TrashStock(1, 1)]
    funded = fund_trash_man_realm_breakthrough(
        state,
        trash_adapter=trash_adapter,
    ).state

    offline = settle_fish_production(
        funded,
        10,
        hall_adapter=hall_adapter,
        trash_adapter=trash_adapter,
        barbell_adapter=FishBarbellDataAdapter(snapshot),
        online=False,
    )

    assert offline.state.trash_man.realm_id == 2
    assert offline.state.trash_man.highest_realm_id == 2
    assert offline.state.trash_man.breakthrough.active
    assert offline.state.trash_man.breakthrough.progress_seconds == 0
    assert offline.material_added == SimNumber.parse("12.5")
    assert offline.trash_processing.breakthrough_completions == ()

    online = settle_fish_production(
        offline.state,
        11,
        hall_adapter=hall_adapter,
        trash_adapter=trash_adapter,
        barbell_adapter=FishBarbellDataAdapter(snapshot),
        runtime=offline.runtime,
        online=True,
    )

    assert online.state.trash_man.realm_id == 3
    assert online.state.trash_man.highest_realm_id == 3
    assert not online.state.trash_man.breakthrough.active
    assert online.state.trash_man.breakthrough.target_realm_id == 0
    assert online.state.trash_man.breakthrough.progress_seconds == 0
    assert len(online.trash_processing.breakthrough_completions) == 1
    completion = online.trash_processing.breakthrough_completions[0]
    assert completion.from_realm_id == 2
    assert completion.to_realm_id == 3
    assert completion.at_elapsed_seconds == 1
    assert completion.required_seconds == 1
    assert completion.material_cost == SimNumber.parse(100)


def test_breakthrough_behavior_emits_persistent_completion_and_replays_checkpoint(
    tmp_path: Path,
) -> None:
    raw = ConfigLoader.load(
        "projects/fish/economy.yaml",
        "projects/fish/luban_exports",
    )
    model = ModelBuilder.build(raw)
    model.scenarios["smoke"].duration_hours = 2 / 3600
    profile = model.player_profiles["default"]
    profile.behavior_weights = {
        FUND_TRASH_MAN_BREAKTHROUGH_BEHAVIOR_ID: SimNumber.one()
    }
    profile.behavior_durations = {
        FUND_TRASH_MAN_BREAKTHROUGH_BEHAVIOR_ID: {
            "type": "fixed",
            "seconds": 1,
        }
    }
    profile.behavior_target_policies = {}
    snapshot = _snapshot(tmp_path)
    digest = "sha256:" + ("b" * 64)
    simulator = FishEconomySimulator(model, snapshot, model_digest=digest)
    initial_state = _state_with_material(20)
    initial_checkpoint = FishCheckpointCodec.new(
        initial_state,
        model_digest=digest,
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
        until_seconds=1,
    )
    resumed = simulator.run_scenario("smoke", first.checkpoint)

    assert first.checkpoint.engine_state["trashMan"]["breakthrough"] == {
        "active": True,
        "targetRealmId": 2,
        "progressSeconds": 0,
    }
    assert resumed.checkpoint.engine_state == continuous.checkpoint.engine_state
    assert resumed.checkpoint.event_counters == continuous.checkpoint.event_counters
    assert continuous.checkpoint.engine_state["trashMan"]["realmId"] == 2
    assert continuous.checkpoint.engine_state["trashMan"]["highestRealmId"] == 2
    assert continuous.checkpoint.event_counters[
        "trash_man_realm_broken_through"
    ] == 1
    realm_event = next(
        event
        for event in continuous.result.events
        if event.kind == "trash_man_realm_broken_through"
    )
    assert realm_event.time_seconds == 1
    assert realm_event.details["trash_man_realm_before"] == "1"
    assert realm_event.details["trash_man_realm_after"] == "2"
    assert realm_event.details["trash_man_breakthrough_price"] == "20"
    assert realm_event.details["trash_man_breakthrough_price_resource"] == (
        "material"
    )


@pytest.mark.parametrize(
    ("policy", "expected_behavior_ids"),
    [
        ("immediate", (FUND_TRASH_MAN_BREAKTHROUGH_BEHAVIOR_ID,)),
        (
            "weighted_delay",
            (FUND_TRASH_MAN_BREAKTHROUGH_BEHAVIOR_ID, "idle"),
        ),
        ("preserve_material", ("idle",)),
    ],
)
def test_breakthrough_player_policy_controls_the_explicit_command_candidate(
    tmp_path: Path,
    policy: str,
    expected_behavior_ids: tuple[str, ...],
) -> None:
    raw = ConfigLoader.load(
        "projects/fish/economy.yaml",
        "projects/fish/luban_exports",
    )
    model = ModelBuilder.build(raw)
    model.engine_settings["behavior_scheduler"][
        "trash_man_breakthrough_policy"
    ] = policy
    profile = model.player_profiles["default"]
    profile.behavior_weights = {
        FUND_TRASH_MAN_BREAKTHROUGH_BEHAVIOR_ID: SimNumber.one(),
        "idle": SimNumber.one(),
    }
    profile.behavior_durations = {
        FUND_TRASH_MAN_BREAKTHROUGH_BEHAVIOR_ID: {
            "type": "fixed",
            "seconds": 1,
        },
        "idle": {"type": "fixed", "seconds": 1},
    }
    profile.behavior_target_policies = {}
    simulator = FishBehaviorSimulator(
        model,
        _snapshot(tmp_path),
        model_digest="sha256:" + ("e" * 64),
        _mutate_state=False,
    )

    candidates = simulator.adapter.candidates(
        _state_with_material(20),
        profile,
    )

    assert tuple(
        candidate.behavior_id for candidate in candidates
    ) == expected_behavior_ids


def test_breakthrough_player_policy_rejects_non_string_configuration(
    tmp_path: Path,
) -> None:
    raw = ConfigLoader.load(
        "projects/fish/economy.yaml",
        "projects/fish/luban_exports",
    )
    model = ModelBuilder.build(raw)
    model.engine_settings["behavior_scheduler"][
        "trash_man_breakthrough_policy"
    ] = ["immediate"]

    with pytest.raises(ValueError, match="must be a string"):
        FishBehaviorSimulator(
            model,
            _snapshot(tmp_path),
            model_digest="sha256:" + ("e" * 64),
            _mutate_state=False,
        )
