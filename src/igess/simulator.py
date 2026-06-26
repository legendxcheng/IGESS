from __future__ import annotations

from .conditions import evaluate
from .modifiers import ModifierStack
from .numbers import SimNumber
from .policy import PolicyEngine
from .schema import EconomyModel, Event, SimulationResult, SimulationState, TimelineRow
from .time_engine import TimeEngine


class Simulator:
    def __init__(self, model: EconomyModel):
        self.model = model
        self.policy = PolicyEngine(model)
        self.time = TimeEngine(model.config.tick_seconds)

    def run_scenario(self, scenario_id: str) -> SimulationResult:
        scenario = self.model.scenarios[scenario_id]
        duration_seconds = int(scenario.duration_hours * 3600)
        timeline: list[TimelineRow] = []
        events: list[Event] = []
        for profile_id in scenario.profiles:
            state = SimulationState.new(self.model)
            self._update_unlocks(scenario_id, profile_id, 0, state, events)
            for current_time in self.time.ticks_for_duration(duration_seconds):
                if current_time > 0:
                    self._produce(profile_id, state)
                    self._apply_offline_reward(scenario_id, profile_id, current_time, state, events)
                    self._update_unlocks(scenario_id, profile_id, current_time, state, events)
                    self._purchase_available(scenario_id, profile_id, current_time, state, events)
                    self._apply_milestones(scenario_id, profile_id, current_time, state, events)
                    self._apply_prestige(scenario_id, profile_id, current_time, state, events)
                    self._update_unlocks(scenario_id, profile_id, current_time, state, events)
                if (
                    current_time == 0
                    or current_time == duration_seconds
                    or current_time % scenario.record_interval_seconds == 0
                ):
                    timeline.append(self._timeline_row(scenario_id, profile_id, current_time, state))
        return SimulationResult(scenario_id=scenario_id, timeline=timeline, events=events)

    def _produce(self, profile_id: str, state: SimulationState) -> None:
        profile = self.model.player_profiles[profile_id]
        for generator_id, generator in self.model.generators.items():
            owned = state.generators_owned[generator_id]
            if owned <= 0:
                continue
            output = ModifierStack.apply_generator_output(self.model, state, generator_id, owned)
            efficiency = profile.source_efficiency.get(generator.source_type, SimNumber.one())
            produced = output * efficiency * SimNumber.parse(self.model.config.tick_seconds)
            state.resources[generator.output_resource] = (
                state.resources[generator.output_resource] + produced
            )

    def _apply_offline_reward(
        self,
        scenario_id: str,
        profile_id: str,
        current_time: int,
        state: SimulationState,
        events: list[Event],
    ) -> None:
        profile = self.model.player_profiles[profile_id]
        pattern = self.model.session_patterns.get(profile.session_pattern, {})
        every = int(pattern.get("offline_every_seconds", 0) or 0)
        duration = int(pattern.get("offline_duration_seconds", 0) or 0)
        if every <= 0 or duration <= 0 or current_time % every != 0:
            return
        efficiency = profile.source_efficiency.get("offline", SimNumber.one())
        produced_by_resource: dict[str, SimNumber] = {}
        for generator_id, generator in self.model.generators.items():
            owned = state.generators_owned[generator_id]
            if owned <= 0:
                continue
            produced = (
                ModifierStack.apply_generator_output(self.model, state, generator_id, owned)
                * efficiency
                * SimNumber.parse(duration)
            )
            produced_by_resource[generator.output_resource] = (
                produced_by_resource.get(generator.output_resource, SimNumber.zero()) + produced
            )
        for resource_id, amount in sorted(produced_by_resource.items()):
            if amount <= SimNumber.zero():
                continue
            state.resources[resource_id] = state.resources[resource_id] + amount
            events.append(
                Event(
                    scenario_id,
                    profile_id,
                    current_time,
                    "offline_reward",
                    resource_id,
                    {
                        "amount": amount.to_decimal_string(),
                        "duration_seconds": str(duration),
                    },
                )
            )

    def _purchase_available(
        self,
        scenario_id: str,
        profile_id: str,
        current_time: int,
        state: SimulationState,
        events: list[Event],
    ) -> None:
        purchases_this_tick = 0
        while purchases_this_tick < 20:
            action = self.policy.choose_action(profile_id, state)
            if action is None:
                return
            self.policy.apply_action(action, state)
            events.append(
                Event(
                    scenario_id=scenario_id,
                    profile_id=profile_id,
                    time_seconds=current_time,
                    kind=action.kind,
                    item_id=action.item_id,
                    details={
                        "cost": action.cost.to_decimal_string(),
                        "resource": action.cost_resource,
                    },
                )
            )
            purchases_this_tick += 1

    def _apply_milestones(
        self,
        scenario_id: str,
        profile_id: str,
        current_time: int,
        state: SimulationState,
        events: list[Event],
    ) -> None:
        profile = self.model.player_profiles[profile_id]
        efficiency = profile.source_efficiency.get("milestone", SimNumber.one())
        for milestone_id, milestone in self.model.milestones.items():
            if milestone_id in state.milestones_claimed:
                continue
            if not evaluate(milestone.condition, lambda item_id: state.generators_owned.get(item_id, 0)):
                continue
            reward = SimNumber.parse(milestone.reward_amount) * efficiency
            state.resources[milestone.reward_resource] = state.resources[milestone.reward_resource] + reward
            state.milestones_claimed.add(milestone_id)
            events.append(
                Event(
                    scenario_id,
                    profile_id,
                    current_time,
                    "milestone_reward",
                    milestone_id,
                    {
                        "amount": reward.to_decimal_string(),
                        "reward_resource": milestone.reward_resource,
                    },
                )
            )

    def _apply_prestige(
        self,
        scenario_id: str,
        profile_id: str,
        current_time: int,
        state: SimulationState,
        events: list[Event],
    ) -> None:
        profile = self.model.player_profiles[profile_id]
        efficiency = profile.source_efficiency.get("prestige", SimNumber.one())
        for layer_id, layer in self.model.prestige_layers.items():
            if not evaluate(layer.unlock_condition, lambda item_id: state.generators_owned.get(item_id, 0)):
                continue
            gain = self.model.formulas[layer.formula](
                {
                    "progress": state.resources[layer.trigger_resource],
                    "divisor": SimNumber.parse(layer.divisor),
                    "exponent": SimNumber.parse(layer.exponent),
                }
            )
            gain = gain * efficiency
            if gain < SimNumber.parse(layer.min_gain):
                continue
            for resource_id in layer.reset_resources:
                state.resources[resource_id] = SimNumber.zero()
            state.resources[layer.reward_resource] = state.resources[layer.reward_resource] + gain
            state.prestige_counts[layer_id] = state.prestige_counts.get(layer_id, 0) + 1
            events.append(
                Event(
                    scenario_id,
                    profile_id,
                    current_time,
                    "prestige_reset",
                    layer_id,
                    {
                        "gain": gain.to_decimal_string(),
                        "reward_resource": layer.reward_resource,
                        "reset_resources": ",".join(layer.reset_resources),
                    },
                )
            )

    def _update_unlocks(
        self,
        scenario_id: str,
        profile_id: str,
        current_time: int,
        state: SimulationState,
        events: list[Event],
    ) -> None:
        for generator_id, generator in self.model.generators.items():
            if generator_id in state.unlocked_generators:
                continue
            if evaluate(generator.unlock_condition, lambda item_id: state.generators_owned.get(item_id, 0)):
                state.unlocked_generators.add(generator_id)
                events.append(
                    Event(
                        scenario_id,
                        profile_id,
                        current_time,
                        "unlock_generator",
                        generator_id,
                        {},
                    )
                )
        for upgrade_id, upgrade in self.model.upgrades.items():
            if upgrade_id in state.unlocked_upgrades:
                continue
            if evaluate(upgrade.unlock_condition, lambda item_id: state.generators_owned.get(item_id, 0)):
                state.unlocked_upgrades.add(upgrade_id)
                events.append(
                    Event(
                        scenario_id,
                        profile_id,
                        current_time,
                        "unlock_upgrade",
                        upgrade_id,
                        {},
                    )
                )

    def _timeline_row(
        self, scenario_id: str, profile_id: str, current_time: int, state: SimulationState
    ) -> TimelineRow:
        return TimelineRow(
            scenario_id=scenario_id,
            profile_id=profile_id,
            time_seconds=current_time,
            resources={
                resource_id: state.resources[resource_id].to_decimal_string()
                for resource_id in sorted(self.model.resources)
            },
            generators_owned={key: state.generators_owned[key] for key in sorted(state.generators_owned)},
            upgrades_purchased=sorted(state.upgrades_purchased),
            total_cps=self._total_cps(state).to_decimal_string(),
        )

    def _total_cps(self, state: SimulationState) -> SimNumber:
        total = SimNumber.zero()
        for generator_id in self.model.generators:
            total += ModifierStack.apply_generator_output(
                self.model, state, generator_id, state.generators_owned[generator_id]
            )
        return total
