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


@dataclass(frozen=True)
class SourceRef:
    table: str
    workbook: str
    row: int

    def to_details(self) -> dict[str, str]:
        return {
            "source_table": self.table,
            "source_workbook": self.workbook,
            "source_row": str(self.row),
        }


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
    rng_tables: dict[str, "RngTable"]
    rng_scenarios: dict[str, "RngScenario"]
    regression_gates: dict[str, dict[str, Any]]


@dataclass
class ResourceRow:
    id: str
    name: str
    dimension: str
    source_ref: SourceRef | None = None


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
    source_ref: SourceRef | None = None


@dataclass
class ActivityRow:
    id: str
    name: str
    source_type: str
    unlock_condition: str = "always"
    source_ref: SourceRef | None = None


@dataclass
class ActivityOutputRow:
    id: str
    activity_id: str
    output_resource: str
    amount_per_second: str
    source_ref: SourceRef | None = None


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
    source_ref: SourceRef | None = None


@dataclass
class ConstantRow:
    id: str
    value: str
    source_ref: SourceRef | None = None


@dataclass
class MilestoneRow:
    id: str
    name: str
    condition: str
    reward_resource: str
    reward_amount: str
    source_ref: SourceRef | None = None


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
    source_ref: SourceRef | None = None


@dataclass
class PlayerProfile:
    id: str
    source_efficiency: dict[str, SimNumber]
    behavior_policy: str
    session_pattern: str
    prestige_policy: str
    luck: SimNumber = field(default_factory=SimNumber.one)
    activity_weights: dict[str, SimNumber] = field(default_factory=dict)


@dataclass
class Scenario:
    id: str
    duration_hours: float
    profiles: list[str]
    start_state: str
    record_interval_seconds: int
    outputs: list[str]
    time_mode: str = "tick"


@dataclass(frozen=True)
class RngRarity:
    id: str
    denominator: SimNumber


@dataclass
class RngTable:
    id: str
    algorithm: str
    rarities: list[RngRarity]


@dataclass
class RngScenario:
    id: str
    table: str
    rolls: int
    trials: int
    profiles: list[str]
    event_threshold: str | None = None


@dataclass
class RawConfig:
    rules: Rules
    resources: list[ResourceRow]
    generators: list[GeneratorRow]
    upgrades: list[UpgradeRow]
    constants: list[ConstantRow]
    milestones: list[MilestoneRow]
    prestige_layers: list[PrestigeLayerRow]
    activities: list[ActivityRow] = field(default_factory=list)
    activity_outputs: list[ActivityOutputRow] = field(default_factory=list)


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
    rng_tables: dict[str, RngTable]
    rng_scenarios: dict[str, RngScenario]
    activities: dict[str, ActivityRow] = field(default_factory=dict)
    activity_outputs: dict[str, ActivityOutputRow] = field(default_factory=dict)

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

    def source_details(self, kind: str, item_id: str) -> dict[str, str]:
        item_kind = kind.removeprefix("buy_").removeprefix("unlock_")
        if item_kind == "generator":
            row = self.generators.get(item_id)
        elif item_kind == "upgrade":
            row = self.upgrades.get(item_id)
        elif item_kind == "activity":
            row = self.activities.get(item_id)
        elif item_kind == "milestone":
            row = self.milestones.get(item_id)
        elif item_kind == "prestige":
            row = self.prestige_layers.get(item_id)
        else:
            row = None
        if row is None or row.source_ref is None:
            return {}
        return row.source_ref.to_details()


@dataclass
class SimulationState:
    resources: dict[str, SimNumber]
    generators_owned: dict[str, int]
    upgrades_purchased: set[str] = field(default_factory=set)
    unlocked_generators: set[str] = field(default_factory=set)
    unlocked_upgrades: set[str] = field(default_factory=set)
    milestones_claimed: set[str] = field(default_factory=set)
    prestige_counts: dict[str, int] = field(default_factory=dict)
    unlocked_activities: set[str] = field(default_factory=set)

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
            unlocked_activities=set(self.unlocked_activities),
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
