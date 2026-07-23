from __future__ import annotations

import json
from pathlib import Path

import pytest

from igess.checkpoint import CheckpointValidationError, SimulationCheckpoint
from igess.fish_state import (
    BigNumberDTO,
    FishArchiveCodec,
    FishCheckpointCodec,
    FishInstance,
    FishStateValidationContext,
    FishStateValidationError,
    OwnedBarbell,
    PlayerState,
    TrashManUpgrade,
    TrashStock,
    normalize_player_state,
)
from igess.numbers import SimNumber


_DIGEST = "sha256:" + ("f" * 64)


def _known_id(category: str, item_id: int) -> bool:
    known = {
        "torpedo": {1, 2},
        "barbell": {1, 2},
        "fish": {17, 18},
        "mutation": {1, 2},
        "trashManRealm": {1, 2, 3},
        "trashManUpgrade": {1, 2},
        "trash": {1, 2},
        "collectionReward": {1, 2},
    }
    return item_id in known[category]


def _context(now: int = 1_000) -> FishStateValidationContext:
    return FishStateValidationContext(
        now=now,
        id_exists=_known_id,
        fish_hall_capacity=lambda level: 2 + level,
    )


def _populated_state() -> PlayerState:
    state = PlayerState.new(1_000)
    state.wallet.money = BigNumberDTO.from_value("123400000", allow_negative=False)
    state.wallet.material = BigNumberDTO.from_value("25", allow_negative=False)
    state.wallet.strength = BigNumberDTO.from_value("1e12", allow_negative=False)
    state.torpedo.owned_ids = [2, 1]
    state.torpedo.selected_id = 2
    state.barbell.owned = [
        OwnedBarbell(barbell_id=2, count=3),
        OwnedBarbell(barbell_id=1, count=1),
    ]
    state.barbell.equipped_id = 1
    state.fish_hall.upgrade_level = 1
    state.fish.items = [
        FishInstance(2, 18, 2, 3, 800, 0),
        FishInstance(1, 17, 1, 1, 1_250, 1),
    ]
    state.fish.next_instance_id = 3
    state.trash_man.realm_id = 2
    state.trash_man.highest_realm_id = 3
    state.trash_man.upgrades = [
        TrashManUpgrade(upgrade_id=2, level=1),
        TrashManUpgrade(upgrade_id=1, level=2),
    ]
    state.trash_man.training_progress_seconds = 50
    state.trash_man.breakthrough.active = True
    state.trash_man.breakthrough.target_realm_id = 3
    state.trash_man.breakthrough.progress_seconds = 5
    state.trash_man.processing.active_trash_id = 1
    state.trash_man.processing.active_progress_seconds = 7
    state.trash_man.processing.stocks = [
        TrashStock(trash_id=2, count=4),
        TrashStock(trash_id=1, count=2),
    ]
    state.rebirth.strength_completed_count = 2
    state.rebirth.trash_man_completed_count = 1
    state.collection.unlocked_keys = ["18:2", "17:1"]
    state.collection.viewed_keys = ["17:1"]
    state.collection.claimed_reward_ids = [2, 1]
    state.automation.auto_throw_unlocked = True
    state.automation.auto_throw_enabled = True
    state.statistics.total_throws = 8
    state.statistics.total_fish_caught = 8
    state.statistics.max_distance_cm = 12_345
    state.validate(_context())
    return state


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("0", (0, 0, 0)),
        ("10", (1, 1000, -2)),
        ("-123400000", (-1, 1234, 5)),
        ("12345", (1, 1235, 1)),
        ("99995", (1, 1000, 2)),
        ("0.0012345", (1, 1235, -6)),
        ("1e1000003", (1, 1000, 1000000)),
    ],
)
def test_big_number_dto_matches_game_four_digit_normalization(
    value: str,
    expected: tuple[int, int, int],
) -> None:
    dto = BigNumberDTO.from_value(value)
    assert (dto.sign, dto.coeff, dto.exp) == expected


def test_big_number_dto_round_trips_through_sim_number() -> None:
    dto = BigNumberDTO.from_value(SimNumber.parse("123400000"))

    assert dto == BigNumberDTO(sign=1, coeff=1234, exp=5)
    assert dto.to_sim_number() == SimNumber.parse("123400000")
    assert dto.to_decimal_string() == "1234E+5"


@pytest.mark.parametrize(
    "dto",
    [
        BigNumberDTO(sign=0, coeff=1, exp=0),
        BigNumberDTO(sign=1, coeff=999, exp=0),
        BigNumberDTO(sign=1, coeff=1000, exp=1_000_001),
    ],
)
def test_big_number_dto_rejects_noncanonical_values(dto: BigNumberDTO) -> None:
    with pytest.raises(FishStateValidationError):
        dto.validate()


def test_new_state_matches_real_archive_shape_and_has_no_derived_fields() -> None:
    state = PlayerState.new(1_000)
    payload = state.to_dict(context=_context())

    assert payload["meta"] == {"createdAt": 1_000, "revision": 0}
    assert payload["production"] == {"lastSettledAt": 1_000}
    assert payload["wallet"]["money"] == {"sign": 0, "coeff": 0, "exp": 0}
    assert payload["fish"] == {"nextInstanceId": 1, "items": []}
    assert set(payload) == {
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
    }
    encoded = json.dumps(payload)
    for forbidden in (
        "fishLuck",
        "trashLuck",
        "moneyPerSecond",
        "pendingThrowResult",
        "schemaVersion",
    ):
        assert forbidden not in encoded


def test_new_state_can_receive_first_generated_torpedo() -> None:
    state = PlayerState.new(1_000, initial_torpedo_id=1)

    payload = state.to_dict(context=_context())

    assert payload["torpedo"] == {"selectedId": 1, "ownedIds": [1]}


def test_archive_codec_is_canonical_and_uses_project_save_envelope() -> None:
    state = _populated_state()

    first = FishArchiveCodec.dumps(state, context=_context())
    loaded = FishArchiveCodec.loads(first, context=_context())
    second = FishArchiveCodec.dumps(loaded, context=_context())

    assert second == first
    payload = json.loads(first)
    assert payload["version"] == 1
    assert "schemaVersion" not in payload["data"]
    assert payload["data"]["torpedo"]["ownedIds"] == [1, 2]
    assert [
        item["instanceId"] for item in payload["data"]["fish"]["items"]
    ] == [1, 2]


def test_copy_is_deep_and_does_not_share_nested_state() -> None:
    original = _populated_state()
    copied = original.copy()

    copied.fish.items[0].level = 99
    copied.collection.unlocked_keys.append("17:2")
    copied.trash_man.processing.stocks[0].count = 999

    assert {item.instance_id: item.level for item in original.fish.items} == {
        1: 1,
        2: 3,
    }
    assert original.collection.unlocked_keys == ["18:2", "17:1"]
    assert {stock.trash_id: stock.count for stock in original.trash_man.processing.stocks} == {
        1: 2,
        2: 4,
    }


@pytest.mark.parametrize(
    ("mutate", "code", "path"),
    [
        (
            lambda state: setattr(
                state.wallet,
                "money",
                BigNumberDTO(-1, 1000, 0),
            ),
            "archive_schema_big_number_invalid",
            "wallet.money",
        ),
        (
            lambda state: state.torpedo.owned_ids.extend([1, 1]),
            "archive_schema_duplicate_id",
            "torpedo.ownedIds[2]",
        ),
        (
            lambda state: setattr(state.torpedo, "selected_id", 1),
            "archive_schema_reference_missing",
            "torpedo.selectedId",
        ),
        (
            lambda state: state.fish.items.extend(
                [
                    FishInstance(1, 17, 1, 1, 100, 1),
                    FishInstance(2, 18, 1, 1, 100, 1),
                ]
            ),
            "archive_schema_duplicate_slot",
            "fish.items[2].hallSlot",
        ),
        (
            lambda state: state.fish.items.append(
                FishInstance(1, 17, 1, 1, 100, 3)
            ),
            "archive_schema_capacity_exceeded",
            "fish.items[1].hallSlot",
        ),
        (
            lambda state: (
                state.fish.items.append(
                    FishInstance(1, 17, 1, 1, 100, 0)
                ),
                setattr(state.fish, "next_instance_id", 1),
            ),
            "archive_schema_next_id_invalid",
            "fish.nextInstanceId",
        ),
        (
            lambda state: (
                setattr(state.trash_man, "realm_id", 2),
                setattr(state.trash_man, "highest_realm_id", 1),
            ),
            "archive_schema_order_invalid",
            "trashMan.realmId",
        ),
        (
            lambda state: state.collection.viewed_keys.append("17:1"),
            "archive_schema_reference_missing",
            "collection.viewedKeys",
        ),
        (
            lambda state: setattr(
                state.automation,
                "auto_throw_enabled",
                True,
            ),
            "archive_schema_reference_missing",
            "automation.autoThrowEnabled",
        ),
    ],
)
def test_state_rejects_corrupt_references_and_values(
    mutate,
    code: str,
    path: str,
) -> None:
    state = PlayerState.new(1_000)
    mutate(state)

    with pytest.raises(FishStateValidationError) as caught:
        state.validate(_context())

    assert caught.value.code == code
    assert caught.value.path == path


def test_config_ids_and_server_timestamps_are_validated() -> None:
    state = PlayerState.new(1_000)
    state.torpedo.owned_ids = [99]

    with pytest.raises(FishStateValidationError) as unknown:
        state.validate(_context())
    assert unknown.value.code == "archive_schema_unknown_id"
    assert unknown.value.path == "torpedo.ownedIds[1]"

    state = PlayerState.new(1_000)
    state.production.last_settled_at = 1_301
    with pytest.raises(FishStateValidationError) as future:
        state.validate(_context())
    assert future.value.code == "archive_schema_time_in_future"


def test_current_version_is_strict_but_explicit_normalization_fills_defaults() -> None:
    partial = {"meta": {"createdAt": 1_000, "revision": 0}}

    with pytest.raises(FishStateValidationError) as strict:
        PlayerState.from_dict(partial, context=_context())
    assert strict.value.code == "archive_schema_keys_invalid"

    normalized, changed = normalize_player_state(
        partial,
        now=1_000,
        context=_context(),
    )
    assert changed is True
    assert normalized.production.last_settled_at == 1_000
    assert normalized.fish.next_instance_id == 1


def test_extra_cached_or_runtime_fields_are_rejected() -> None:
    payload = PlayerState.new(1_000).to_dict()
    payload["wallet"]["fishLuck"] = 5

    with pytest.raises(FishStateValidationError) as caught:
        PlayerState.from_dict(payload, context=_context())

    assert caught.value.code == "archive_schema_keys_invalid"
    assert caught.value.path == "wallet"


def test_fish_checkpoint_round_trip_and_model_digest_guard(
    tmp_path: Path,
) -> None:
    state = _populated_state()
    checkpoint = FishCheckpointCodec.new(
        state,
        model_digest=_DIGEST,
        scenario_id="day_1_progression",
        profile_id="max_income",
        root_random_seed=20260720,
        simulated_time_seconds=600,
        event_counters={"trash_job": 3},
        context=_context(),
    )

    assert checkpoint.engine_id == "fish"
    assert checkpoint.next_throw_id == state.statistics.total_throws
    first = FishCheckpointCodec.dumps(
        checkpoint,
        expected_model_digest=_DIGEST,
        context=_context(),
    )
    loaded_checkpoint, loaded_state = FishCheckpointCodec.loads(
        first,
        expected_model_digest=_DIGEST,
        context=_context(),
    )
    assert FishCheckpointCodec.dumps(
        loaded_checkpoint,
        expected_model_digest=_DIGEST,
        context=_context(),
    ) == first
    assert loaded_state.to_dict(context=_context()) == state.to_dict(
        context=_context()
    )

    path = tmp_path / "fish-checkpoint.json"
    FishCheckpointCodec.write(
        checkpoint,
        path,
        expected_model_digest=_DIGEST,
        context=_context(),
    )
    _, file_state = FishCheckpointCodec.read(
        path,
        expected_model_digest=_DIGEST,
        context=_context(),
    )
    assert file_state.to_dict(context=_context()) == state.to_dict(
        context=_context()
    )

    with pytest.raises(CheckpointValidationError) as mismatch:
        FishCheckpointCodec.loads(
            first,
            expected_model_digest="sha256:" + ("0" * 64),
            context=_context(),
        )
    assert mismatch.value.code == "checkpoint_model_digest_mismatch"


def test_fish_checkpoint_rejects_wrong_engine_and_corrupt_engine_state() -> None:
    state = PlayerState.new(1_000)
    checkpoint = FishCheckpointCodec.new(
        state,
        model_digest=_DIGEST,
        scenario_id="smoke",
        profile_id="progression",
        root_random_seed=1,
    )
    checkpoint.engine_id = "generic"
    with pytest.raises(CheckpointValidationError) as engine:
        FishCheckpointCodec.decode_state(checkpoint)
    assert engine.value.code == "checkpoint_engine_mismatch"

    corrupt = SimulationCheckpoint(
        engine_id="fish",
        model_digest=_DIGEST,
        scenario_id="smoke",
        profile_id="progression",
        simulated_time_seconds=0,
        root_random_seed=1,
        next_throw_id=0,
        engine_state={"meta": {}},
    )
    with pytest.raises(FishStateValidationError):
        FishCheckpointCodec.decode_state(corrupt)
