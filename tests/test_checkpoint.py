from __future__ import annotations

import json
from pathlib import Path

import pytest

from igess.behavior import BehaviorDecision, BehaviorRuntimeState
from igess.checkpoint import (
    CheckpointCodec,
    CheckpointValidationError,
    SimulationCheckpoint,
)


_DIGEST = "sha256:" + ("a" * 64)


def _checkpoint(**overrides: object) -> SimulationCheckpoint:
    values = {
        "engine_id": "fish",
        "model_digest": _DIGEST,
        "scenario_id": "day_1",
        "profile_id": "progression",
        "simulated_time_seconds": 60,
        "root_random_seed": 20260720,
        "next_throw_id": 2,
        "event_counters": {"trash_job": 1},
        "engine_state": {"wallet": {"money": 10}, "items": [1, 2]},
    }
    values.update(overrides)
    return SimulationCheckpoint(**values)


def test_checkpoint_canonical_round_trip_and_atomic_file_write(
    tmp_path: Path,
) -> None:
    checkpoint = _checkpoint()

    first = CheckpointCodec.dumps(checkpoint)
    loaded = CheckpointCodec.loads(
        first,
        expected_engine_id="fish",
        expected_model_digest=_DIGEST,
    )
    second = CheckpointCodec.dumps(loaded)

    assert second == first
    assert list(json.loads(first)) == [
        "engine_id",
        "engine_state",
        "event_counters",
        "model_digest",
        "next_throw_id",
        "profile_id",
        "root_random_seed",
        "scenario_id",
        "schema_version",
        "simulated_time_seconds",
    ]

    destination = tmp_path / "nested" / "checkpoint.json"
    assert CheckpointCodec.write(checkpoint, destination) == destination
    assert destination.read_text(encoding="utf-8") == first
    assert CheckpointCodec.read(destination).to_dict() == checkpoint.to_dict()
    assert not list(destination.parent.glob("*.tmp"))


@pytest.mark.parametrize(
    ("overrides", "code", "path"),
    [
        ({"schema_version": 2}, "checkpoint_version_unsupported", "$.schema_version"),
        ({"engine_id": ""}, "checkpoint_invalid_value", "$.engine_id"),
        ({"model_digest": "a" * 64}, "checkpoint_model_digest_invalid", "$.model_digest"),
        (
            {"simulated_time_seconds": -1},
            "checkpoint_invalid_value",
            "$.simulated_time_seconds",
        ),
        ({"next_throw_id": -1}, "checkpoint_invalid_value", "$.next_throw_id"),
        (
            {"event_counters": {"job": -1}},
            "checkpoint_invalid_value",
            "$.event_counters.job",
        ),
        (
            {"engine_state": {"derived": 1.5}},
            "checkpoint_engine_state_not_plain",
            "$.engine_state.derived",
        ),
    ],
)
def test_checkpoint_rejects_invalid_envelope_values(
    overrides: dict[str, object],
    code: str,
    path: str,
) -> None:
    with pytest.raises(CheckpointValidationError) as caught:
        CheckpointCodec.dumps(_checkpoint(**overrides))

    assert caught.value.code == code
    assert caught.value.path == path


def test_checkpoint_rejects_model_and_engine_mismatches() -> None:
    encoded = CheckpointCodec.dumps(_checkpoint())

    with pytest.raises(CheckpointValidationError) as digest_error:
        CheckpointCodec.loads(
            encoded,
            expected_model_digest="sha256:" + ("b" * 64),
        )
    assert digest_error.value.code == "checkpoint_model_digest_mismatch"

    with pytest.raises(CheckpointValidationError) as engine_error:
        CheckpointCodec.loads(encoded, expected_engine_id="generic")
    assert engine_error.value.code == "checkpoint_engine_mismatch"


def test_checkpoint_rejects_unknown_and_duplicate_json_fields() -> None:
    payload = _checkpoint().to_dict()
    payload["unknown"] = True
    with pytest.raises(CheckpointValidationError) as unknown:
        CheckpointCodec.loads(json.dumps(payload))
    assert unknown.value.code == "checkpoint_schema_keys_invalid"

    duplicate = '{"schema_version":1,"schema_version":1}'
    with pytest.raises(CheckpointValidationError) as repeated:
        CheckpointCodec.loads(duplicate)
    assert repeated.value.code == "checkpoint_duplicate_key"


def test_checkpoint_copy_has_independent_engine_state() -> None:
    original = _checkpoint()
    copied = original.copy()

    copied.engine_state["items"].append(3)
    copied.event_counters["trash_job"] = 2

    assert original.engine_state["items"] == [1, 2]
    assert original.event_counters == {"trash_job": 1}


def test_checkpoint_optionally_round_trips_behavior_runtime_state() -> None:
    runtime = BehaviorRuntimeState(
        next_sequence_id=4,
        active=BehaviorDecision(
            sequence_id=3,
            profile_id="progression",
            behavior_id="upgrade_fish",
            target_id="27",
            duration_seconds=8,
            started_at_seconds=55,
            completes_at_seconds=63,
        ),
    )
    checkpoint = _checkpoint(behavior_state=runtime.to_dict())

    encoded = CheckpointCodec.dumps(checkpoint)
    loaded = CheckpointCodec.loads(encoded)

    assert BehaviorRuntimeState.from_dict(loaded.behavior_state) == runtime
    assert json.loads(encoded)["behavior_state"] == runtime.to_dict()


def test_checkpoint_optionally_round_trips_engine_runtime_state() -> None:
    runtime = {
        "version": 1,
        "trash_processing": {
            "version": 1,
            "progress_remainder": "0.25",
        },
    }
    checkpoint = _checkpoint(engine_runtime_state=runtime)

    encoded = CheckpointCodec.dumps(checkpoint)
    loaded = CheckpointCodec.loads(encoded)

    assert loaded.engine_runtime_state == runtime
    assert json.loads(encoded)["engine_runtime_state"] == runtime
    assert "engine_runtime_state" not in _checkpoint().to_dict()
