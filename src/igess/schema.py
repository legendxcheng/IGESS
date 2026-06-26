from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .formula import CompiledFormula
from .numbers import SimNumber


@dataclass
class FormulaDef:
    args: list[str]
    expr: str


@dataclass
class ModelSettings:
    id: str
    tick_seconds: int
    number_backend: str
    random_seed: int | None


@dataclass
class Rules:
    model: ModelSettings
    formulas: dict[str, FormulaDef]
    generator_types: dict[str, dict[str, Any]]
    source_types: dict[str, dict[str, Any]]
    modifier_pipeline: list[str]
    modifier_types: dict[str, str]
    behavior_policies: dict[str, dict[str, Any]]
    session_patterns: dict[str, dict[str, Any]]
    player_profiles: dict[str, "PlayerProfile"]
    scenarios: dict[str, "Scenario"]


@dataclass
class ResourceRow:
    id: str
    name: str


@dataclass
class GeneratorRow:
    id: str
    name: str
    generator_type: str
    output_resource: str
    source_type: str
    base_output: str
    base_cost: str
    cost_resource: str
    cost_growth: str
    unlock_condition: str = "always"


@dataclass
class UpgradeRow:
    id: str
    name: str
    target: str
    modifier_type: str
    value: str
    cost_resource: str
    base_cost: str
    unlock_condition: str = "always"


@dataclass
class ConstantRow:
    id: str
    value: str


@dataclass
class MilestoneRow:
    id: str
    name: str
    condition: str
    reward_resource: str
    reward_amount: str


@dataclass
class PrestigeLayerRow:
    id: str
    name: str
    trigger_resource: str
    reward_resource: str
    formula: str
    divisor: str
    exponent: str
    min_gain: str
    reset_resources: list[str]
    unlock_condition: str = "always"


@dataclass
class PlayerProfile:
    id: str
    source_efficiency: dict[str, SimNumber]
    behavior_policy: str
    session_pattern: str
    prestige_policy: str


@dataclass
class Scenario:
    id: str
    duration_hours: float
    profiles: list[str]
    start_state: str
    record_interval_seconds: int
    outputs: list[str]
    time_mode: str = "tick"


@dataclass
class RawConfig:
    rules: Rules
    resources: list[ResourceRow]
    generators: list[GeneratorRow]
    upgrades: list[UpgradeRow]
    constants: list[ConstantRow]
    milestones: list[MilestoneRow]
    prestige_layers: list[PrestigeLayerRow]


@dataclass(frozen=True)
class RuntimeConfig:
    model_id: str
    tick_seconds: int
    number_backend: str
    random_seed: int


@dataclass
class EconomyModel:
    config: RuntimeConfig
    resources: dict[str, ResourceRow]
    generators: dict[str, GeneratorRow]
    upgrades: dict[str, UpgradeRow]
    constants: dict[str, SimNumber]
    milestones: dict[str, MilestoneRow]
    prestige_layers: dict[str, PrestigeLayerRow]
    formulas: dict[str, CompiledFormula]
    generator_types: dict[str, dict[str, Any]]
    source_types: dict[str, dict[str, Any]]
    modifier_pipeline: list[str]
    modifier_types: dict[str, str]
    behavior_policies: dict[str, dict[str, Any]]
    session_patterns: dict[str, dict[str, Any]]
    player_profiles: dict[str, PlayerProfile]
    scenarios: dict[str, Scenario]

    def generator_cost(self, generator_id: str, owned: int) -> SimNumber:
        generator = self.generators[generator_id]
        formula_id = self.generator_types[generator.generator_type]["cost_formula"]
        return self.formulas[formula_id](
            {
                "base_cost": SimNumber.parse(generator.base_cost),
                "growth": SimNumber.parse(generator.cost_growth),
                "owned": SimNumber.parse(owned),
            }
        )

    def generator_output(self, generator_id: str, owned: int, multiplier: SimNumber) -> SimNumber:
        generator = self.generators[generator_id]
        formula_id = self.generator_types[generator.generator_type]["production_formula"]
        return self.formulas[formula_id](
            {
                "base_output": SimNumber.parse(generator.base_output),
                "owned": SimNumber.parse(owned),
                "multiplier": multiplier,
            }
        )

    def upgrade_cost(self, upgrade_id: str) -> SimNumber:
        return SimNumber.parse(self.upgrades[upgrade_id].base_cost)


@dataclass
class SimulationState:
    resources: dict[str, SimNumber]
    generators_owned: dict[str, int]
    upgrades_purchased: set[str] = field(default_factory=set)
    unlocked_generators: set[str] = field(default_factory=set)
    unlocked_upgrades: set[str] = field(default_factory=set)
    milestones_claimed: set[str] = field(default_factory=set)
    prestige_counts: dict[str, int] = field(default_factory=dict)

    @classmethod
    def new(cls, model: EconomyModel) -> "SimulationState":
        resources = {resource_id: SimNumber.zero() for resource_id in model.resources}
        for resource_id in model.resources:
            constant_id = f"starting_{resource_id}"
            if constant_id in model.constants:
                resources[resource_id] = model.constants[constant_id]
        return cls(
            resources=resources,
            generators_owned={generator_id: 0 for generator_id in model.generators},
        )

    def copy(self) -> "SimulationState":
        return SimulationState(
            resources=dict(self.resources),
            generators_owned=dict(self.generators_owned),
            upgrades_purchased=set(self.upgrades_purchased),
            unlocked_generators=set(self.unlocked_generators),
            unlocked_upgrades=set(self.unlocked_upgrades),
            milestones_claimed=set(self.milestones_claimed),
            prestige_counts=dict(self.prestige_counts),
        )


@dataclass(frozen=True)
class Action:
    kind: str
    item_id: str
    cost_resource: str
    cost: SimNumber
    score: SimNumber


@dataclass(frozen=True)
class TimelineRow:
    scenario_id: str
    profile_id: str
    time_seconds: int
    resources: dict[str, str]
    generators_owned: dict[str, int]
    upgrades_purchased: list[str]
    total_cps: str

    def to_ordered_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "profile_id": self.profile_id,
            "time_seconds": self.time_seconds,
            "resources": dict(sorted(self.resources.items())),
            "generators_owned": dict(sorted(self.generators_owned.items())),
            "upgrades_purchased": list(self.upgrades_purchased),
            "total_cps": self.total_cps,
        }


@dataclass(frozen=True)
class Event:
    scenario_id: str
    profile_id: str
    time_seconds: int
    kind: str
    item_id: str
    details: dict[str, str]

    def to_ordered_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "profile_id": self.profile_id,
            "time_seconds": self.time_seconds,
            "kind": self.kind,
            "item_id": self.item_id,
            "details": dict(sorted(self.details.items())),
        }


@dataclass
class SimulationResult:
    scenario_id: str
    timeline: list[TimelineRow]
    events: list[Event]
