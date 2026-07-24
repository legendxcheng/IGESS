from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .checkpoint import CheckpointCodec, SimulationCheckpoint
from .fish_state_model import (
    FISH_ARCHIVE_VERSION,
    FISH_ENGINE_ID,
    FishStateValidationContext,
    FishStateValidationError,
    PlayerState,
    _expect_int,
    _expect_keys,
    _expect_object,
    _fail,
)


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


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail("archive_duplicate_key", "$", key)
        result[key] = value
    return result
