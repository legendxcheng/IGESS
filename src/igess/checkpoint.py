from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


CHECKPOINT_SCHEMA_VERSION = 1
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_MAX_CHECKPOINT_BYTES = 16 * 1024 * 1024
_MAX_JSON_DEPTH = 64
_MAX_JSON_WORK_UNITS = 32_768


class CheckpointValidationError(ValueError):
    """Stable, path-aware checkpoint validation failure."""

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


@dataclass
class SimulationCheckpoint:
    """Engine-neutral envelope for resumable domain simulations."""

    engine_id: str
    model_digest: str
    scenario_id: str
    profile_id: str
    simulated_time_seconds: int
    root_random_seed: int
    next_throw_id: int
    engine_state: dict[str, Any]
    event_counters: dict[str, int] = field(default_factory=dict)
    schema_version: int = CHECKPOINT_SCHEMA_VERSION

    def validate(
        self,
        *,
        expected_engine_id: str | None = None,
        expected_model_digest: str | None = None,
    ) -> None:
        _expect_exact_int(
            self.schema_version,
            "$.schema_version",
            minimum=CHECKPOINT_SCHEMA_VERSION,
        )
        if self.schema_version != CHECKPOINT_SCHEMA_VERSION:
            _fail(
                "checkpoint_version_unsupported",
                "$.schema_version",
                self.schema_version,
            )
        _expect_identifier(self.engine_id, "$.engine_id")
        if expected_engine_id is not None and self.engine_id != expected_engine_id:
            _fail(
                "checkpoint_engine_mismatch",
                "$.engine_id",
                f"expected {expected_engine_id!r}, got {self.engine_id!r}",
            )
        if not isinstance(self.model_digest, str) or _DIGEST_RE.fullmatch(
            self.model_digest
        ) is None:
            _fail("checkpoint_model_digest_invalid", "$.model_digest")
        if (
            expected_model_digest is not None
            and self.model_digest != expected_model_digest
        ):
            _fail(
                "checkpoint_model_digest_mismatch",
                "$.model_digest",
                f"expected {expected_model_digest!r}, got {self.model_digest!r}",
            )
        _expect_identifier(self.scenario_id, "$.scenario_id")
        _expect_identifier(self.profile_id, "$.profile_id")
        _expect_exact_int(
            self.simulated_time_seconds,
            "$.simulated_time_seconds",
            minimum=0,
        )
        _expect_exact_int(self.root_random_seed, "$.root_random_seed")
        _expect_exact_int(self.next_throw_id, "$.next_throw_id", minimum=0)

        if type(self.event_counters) is not dict:
            _fail("checkpoint_invalid_type", "$.event_counters")
        for name, value in self.event_counters.items():
            _expect_identifier(name, "$.event_counters.<key>")
            _expect_exact_int(
                value,
                f"$.event_counters.{name}",
                minimum=0,
            )

        if type(self.engine_state) is not dict:
            _fail("checkpoint_invalid_type", "$.engine_state")
        _validate_plain_json(self.engine_state, "$.engine_state")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema_version": self.schema_version,
            "engine_id": self.engine_id,
            "model_digest": self.model_digest,
            "scenario_id": self.scenario_id,
            "profile_id": self.profile_id,
            "simulated_time_seconds": self.simulated_time_seconds,
            "root_random_seed": self.root_random_seed,
            "next_throw_id": self.next_throw_id,
            "event_counters": dict(sorted(self.event_counters.items())),
            "engine_state": _copy_plain_json(self.engine_state),
        }

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
        *,
        expected_engine_id: str | None = None,
        expected_model_digest: str | None = None,
    ) -> "SimulationCheckpoint":
        document = _expect_object(payload, "$")
        expected_keys = {
            "schema_version",
            "engine_id",
            "model_digest",
            "scenario_id",
            "profile_id",
            "simulated_time_seconds",
            "root_random_seed",
            "next_throw_id",
            "event_counters",
            "engine_state",
        }
        _expect_keys(document, expected_keys, "$")
        event_counters = _expect_object(
            document["event_counters"],
            "$.event_counters",
        )
        engine_state = _expect_object(document["engine_state"], "$.engine_state")
        checkpoint = cls(
            schema_version=document["schema_version"],
            engine_id=document["engine_id"],
            model_digest=document["model_digest"],
            scenario_id=document["scenario_id"],
            profile_id=document["profile_id"],
            simulated_time_seconds=document["simulated_time_seconds"],
            root_random_seed=document["root_random_seed"],
            next_throw_id=document["next_throw_id"],
            event_counters=dict(event_counters),
            engine_state=_copy_plain_json(engine_state),
        )
        checkpoint.validate(
            expected_engine_id=expected_engine_id,
            expected_model_digest=expected_model_digest,
        )
        return checkpoint

    def copy(self) -> "SimulationCheckpoint":
        return SimulationCheckpoint.from_dict(self.to_dict())


class CheckpointCodec:
    """Canonical JSON codec with bounded reads and atomic replacement."""

    @staticmethod
    def dumps(checkpoint: SimulationCheckpoint) -> str:
        return (
            json.dumps(
                checkpoint.to_dict(),
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
        expected_engine_id: str | None = None,
        expected_model_digest: str | None = None,
    ) -> SimulationCheckpoint:
        if not isinstance(text, str):
            _fail("checkpoint_invalid_type", "$")
        if len(text.encode("utf-8")) > _MAX_CHECKPOINT_BYTES:
            _fail("checkpoint_too_large", "$")
        try:
            payload = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
        except CheckpointValidationError:
            raise
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise CheckpointValidationError(
                "checkpoint_json_invalid",
                "$",
                str(exc),
            ) from exc
        return SimulationCheckpoint.from_dict(
            payload,
            expected_engine_id=expected_engine_id,
            expected_model_digest=expected_model_digest,
        )

    @classmethod
    def read(
        cls,
        path: str | Path,
        *,
        expected_engine_id: str | None = None,
        expected_model_digest: str | None = None,
    ) -> SimulationCheckpoint:
        source = Path(path)
        try:
            size = source.stat().st_size
        except OSError as exc:
            raise CheckpointValidationError(
                "checkpoint_read_failed",
                "$",
                str(exc),
            ) from exc
        if size > _MAX_CHECKPOINT_BYTES:
            _fail("checkpoint_too_large", "$", size)
        try:
            text = source.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise CheckpointValidationError(
                "checkpoint_read_failed",
                "$",
                str(exc),
            ) from exc
        return cls.loads(
            text,
            expected_engine_id=expected_engine_id,
            expected_model_digest=expected_model_digest,
        )

    @classmethod
    def write(cls, checkpoint: SimulationCheckpoint, path: str | Path) -> Path:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        content = cls.dumps(checkpoint).encode("utf-8")
        descriptor = -1
        temporary: Path | None = None
        try:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{destination.name}.",
                suffix=".tmp",
                dir=destination.parent,
            )
            temporary = Path(temporary_name)
            with os.fdopen(descriptor, "wb") as handle:
                descriptor = -1
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
        except OSError as exc:
            raise CheckpointValidationError(
                "checkpoint_write_failed",
                "$",
                str(exc),
            ) from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
        return destination


def _fail(code: str, path: str, detail: object | None = None) -> None:
    raise CheckpointValidationError(code, path, detail)


def _expect_exact_int(
    value: object,
    path: str,
    *,
    minimum: int | None = None,
) -> int:
    if type(value) is not int or (minimum is not None and value < minimum):
        _fail("checkpoint_invalid_value", path)
    return value


def _expect_identifier(value: object, path: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        _fail("checkpoint_invalid_value", path)
    return value


def _expect_object(value: object, path: str) -> dict[str, Any]:
    if type(value) is not dict:
        _fail("checkpoint_invalid_type", path)
    if any(not isinstance(key, str) for key in value):
        _fail("checkpoint_invalid_key", path)
    return value


def _expect_keys(
    value: Mapping[str, Any],
    expected: set[str],
    path: str,
) -> None:
    actual = set(value)
    if actual == expected:
        return
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    _fail(
        "checkpoint_schema_keys_invalid",
        path,
        {"missing": missing, "extra": extra},
    )


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail("checkpoint_duplicate_key", "$", key)
        result[key] = value
    return result


def _validate_plain_json(value: object, path: str) -> None:
    remaining = _MAX_JSON_WORK_UNITS

    def visit(item: object, item_path: str, depth: int) -> None:
        nonlocal remaining
        remaining -= 1
        if remaining < 0:
            _fail("checkpoint_engine_state_too_large", item_path)
        if depth > _MAX_JSON_DEPTH:
            _fail("checkpoint_engine_state_too_deep", item_path)
        if item is None or type(item) in {bool, int, str}:
            return
        if type(item) is list:
            for index, child in enumerate(item):
                visit(child, f"{item_path}[{index}]", depth + 1)
            return
        if type(item) is dict:
            for key, child in item.items():
                if not isinstance(key, str):
                    _fail("checkpoint_invalid_key", item_path)
                visit(child, f"{item_path}.{key}", depth + 1)
            return
        _fail("checkpoint_engine_state_not_plain", item_path)

    visit(value, path, 0)


def _copy_plain_json(value: Any) -> Any:
    if type(value) is dict:
        return {key: _copy_plain_json(item) for key, item in value.items()}
    if type(value) is list:
        return [_copy_plain_json(item) for item in value]
    return value
