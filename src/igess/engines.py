from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence

from .checkpoint import SimulationCheckpoint
from .fish_data import (
    FishDataError,
    FishDataLoader,
    FishDataSnapshot,
    FishLubanProvider,
    GeneratedLubanProvider,
)
from .fish_simulator import FishEconomySimulator
from .fish_state import FishCheckpointCodec
from .fish_throw_data import ProductionThrowConfig
from .schema import EconomyModel, SimulationResult
from .simulator import Simulator


class EngineAdapterError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.details = dict(details or {})
        super().__init__(message)


@dataclass(frozen=True)
class PreparedEngine:
    engine_id: str
    model: EconomyModel
    model_digest: str
    manifest_metadata: Mapping[str, Any] = field(default_factory=dict)
    domain_model: Any = None


@dataclass(frozen=True)
class EngineExecution:
    result: SimulationResult
    checkpoint: SimulationCheckpoint | None = None


class DomainEngineAdapter(Protocol):
    engine_id: str

    def prepare(
        self,
        model: EconomyModel,
        *,
        source_digest: str,
        base_dir: Path,
        overrides: Sequence[str] = (),
    ) -> PreparedEngine: ...

    def run_scenario(
        self,
        prepared: PreparedEngine,
        scenario_id: str,
        *,
        checkpoint_input: str | Path | None = None,
    ) -> EngineExecution: ...

    def write_checkpoint(
        self,
        execution: EngineExecution,
        path: str | Path,
        *,
        model_digest: str,
    ) -> Path | None: ...


class GenericEngineAdapter:
    engine_id = "generic"

    def __init__(
        self,
        simulator_factory: Callable[[EconomyModel], Any] = Simulator,
    ) -> None:
        self._simulator_factory = simulator_factory

    def prepare(
        self,
        model: EconomyModel,
        *,
        source_digest: str,
        base_dir: Path,
        overrides: Sequence[str] = (),
    ) -> PreparedEngine:
        del base_dir
        if overrides:
            raise ValueError("generic workflow overrides must be applied before model build")
        return PreparedEngine(
            engine_id=self.engine_id,
            model=model,
            model_digest=source_digest,
        )

    def run_scenario(
        self,
        prepared: PreparedEngine,
        scenario_id: str,
        *,
        checkpoint_input: str | Path | None = None,
    ) -> EngineExecution:
        if checkpoint_input is not None:
            raise ValueError("the generic engine does not support checkpoints")
        result = self._simulator_factory(prepared.model).run_scenario(scenario_id)
        return EngineExecution(result=result)

    def write_checkpoint(
        self,
        execution: EngineExecution,
        path: str | Path,
        *,
        model_digest: str,
    ) -> Path | None:
        del execution, path, model_digest
        return None


class FishEngineAdapter:
    engine_id = "fish"

    def __init__(self, luban_provider: FishLubanProvider | None = None) -> None:
        self._luban_provider = luban_provider

    def prepare(
        self,
        model: EconomyModel,
        *,
        source_digest: str,
        base_dir: Path,
        overrides: Sequence[str] = (),
    ) -> PreparedEngine:
        settings = model.engine_settings
        data_root_value = settings.get("data_root")
        if not isinstance(data_root_value, str) or not data_root_value:
            raise ValueError("Fish engine requires engine.data_root")
        data_root = Path(data_root_value)
        if not data_root.is_absolute():
            data_root = base_dir / data_root
        production_data = settings.get("production_data", False)
        if not isinstance(production_data, bool):
            raise ValueError("engine.production_data must be a boolean")
        required_value = settings.get("required_tables")
        if required_value is not None and (
            not isinstance(required_value, list)
            or any(not isinstance(item, str) for item in required_value)
        ):
            raise ValueError("engine.required_tables must be a list of table names")
        if overrides and production_data and not settings.get(
            "allow_production_overrides", False
        ):
            raise ValueError("formal Fish production runs do not allow overrides")

        provider = self._luban_provider
        if provider is None:
            schema_value = settings.get("python_schema")
            if not isinstance(schema_value, str) or not schema_value:
                raise EngineAdapterError(
                    "fish_data_unavailable",
                    "Fish engine requires engine.python_schema",
                    {"engine_id": self.engine_id},
                )
            schema_path = Path(schema_value)
            if not schema_path.is_absolute():
                schema_path = base_dir / schema_path
            provider = GeneratedLubanProvider(schema_path)

        try:
            snapshot = FishDataLoader(provider).load(
                data_root,
                production_data=production_data,
                required_tables=required_value,
                overrides=overrides,
            )
        except FishDataError as exc:
            raise EngineAdapterError(
                "fish_data_unavailable",
                str(exc),
                {"engine_id": self.engine_id, "data_root": str(data_root)},
            ) from exc
        model_digest = snapshot.model_digest(source_digest)
        strategy_id = settings.get("strategy_id", "fish_smoke")
        if not isinstance(strategy_id, str) or not strategy_id:
            raise ValueError("engine.strategy_id must be a non-empty string")
        strategy_parameters: dict[str, Any] = {}
        if "active_throw" in settings:
            strategy_parameters["active_throw"] = (
                ProductionThrowConfig.from_mapping(
                    settings["active_throw"]
                ).manifest_parameters()
            )
            strategy_parameters["trash_processing"] = {
                "formula": "fixed_base_work_continuous_yield_v1",
                "queue_policy": "trash_id_ascending",
                "fractional_progress": "engine_runtime_state",
                "rebirth_mapping": (
                    "completed_count_0_is_1x;"
                    "completed_count_n_uses_table_id_n_minus_1"
                ),
            }
        behavior_profiles = {
            profile_id: {
                "weights": {
                    behavior_id: weight.to_decimal_string()
                    for behavior_id, weight in sorted(
                        profile.behavior_weights.items()
                    )
                },
                "durations": {
                    behavior_id: dict(duration)
                    for behavior_id, duration in sorted(
                        profile.behavior_durations.items()
                    )
                },
                "target_policies": dict(
                    sorted(profile.behavior_target_policies.items())
                ),
            }
            for profile_id, profile in sorted(
                model.player_profiles.items()
            )
            if profile.behavior_weights
        }
        if behavior_profiles:
            strategy_parameters["behavior_scheduler"] = {
                "schema": "weighted_duration_v1",
                "profiles": behavior_profiles,
            }
        metadata = {
            "engine_id": self.engine_id,
            "strategy": {
                "id": strategy_id,
                "parameters": strategy_parameters,
            },
            **snapshot.manifest_metadata(),
        }
        return PreparedEngine(
            engine_id=self.engine_id,
            model=model,
            model_digest=model_digest,
            manifest_metadata=metadata,
            domain_model=snapshot,
        )

    def run_scenario(
        self,
        prepared: PreparedEngine,
        scenario_id: str,
        *,
        checkpoint_input: str | Path | None = None,
    ) -> EngineExecution:
        if not isinstance(prepared.domain_model, FishDataSnapshot):
            raise TypeError("Fish engine requires a FishDataSnapshot")
        checkpoint = None
        if checkpoint_input is not None:
            checkpoint, _state = FishCheckpointCodec.read(
                checkpoint_input,
                expected_model_digest=prepared.model_digest,
            )
        run = FishEconomySimulator(
            prepared.model,
            prepared.domain_model,
            model_digest=prepared.model_digest,
        ).run_scenario(scenario_id, checkpoint)
        return EngineExecution(result=run.result, checkpoint=run.checkpoint)

    def write_checkpoint(
        self,
        execution: EngineExecution,
        path: str | Path,
        *,
        model_digest: str,
    ) -> Path | None:
        if execution.checkpoint is None:
            return None
        return FishCheckpointCodec.write(
            execution.checkpoint,
            path,
            expected_model_digest=model_digest,
        )


class EngineRegistry:
    def __init__(self, adapters: Sequence[DomainEngineAdapter]) -> None:
        self._adapters: dict[str, DomainEngineAdapter] = {}
        for adapter in adapters:
            if adapter.engine_id in self._adapters:
                raise ValueError(f"duplicate engine adapter: {adapter.engine_id}")
            self._adapters[adapter.engine_id] = adapter

    @classmethod
    def standard(
        cls,
        simulator_factory: Callable[[EconomyModel], Any] = Simulator,
        fish_luban_provider: FishLubanProvider | None = None,
    ) -> "EngineRegistry":
        return cls(
            (
                GenericEngineAdapter(simulator_factory),
                FishEngineAdapter(fish_luban_provider),
            )
        )

    def resolve(self, engine_id: str) -> DomainEngineAdapter:
        try:
            return self._adapters[engine_id]
        except KeyError as exc:
            available = ", ".join(sorted(self._adapters))
            raise ValueError(
                f"unknown engine_id '{engine_id}'; available: {available}"
            ) from exc
