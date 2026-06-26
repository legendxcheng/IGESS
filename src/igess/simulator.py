from __future__ import annotations

from .conditions import evaluate
from .modifiers import ModifierStack
from .numbers import SimNumber
from .policy import PolicyEngine
from .schema import EconomyModel, Event, SimulationResult, SimulationState, TimelineRow
from .time_engine import TimeEngine
from .trace import action_formula_trace, prestige_formula_trace


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
            current_time = 0
            timeline.append(self._timeline_row(scenario_id, profile_id, current_time, state))
            while current_time < duration_seconds:
                next_time = self._next_time(
                    profile_id,
                    state,
                    current_time,
                    duration_seconds,
                    scenario.record_interval_seconds,
                    scenario.time_mode,
                )
                delta_seconds = next_time - current_time
                current_time = next_time
                self._produce(profile_id, state, delta_seconds)
                self._apply_offline_reward(scenario_id, profile_id, current_time, state, events)
                self._update_unlocks(scenario_id, profile_id, current_time, state, events)
                if scenario.time_mode == "analytic":
                    self._apply_milestones(scenario_id, profile_id, current_time, state, events)
                    self._apply_prestige(scenario_id, profile_id, current_time, state, events)
                    self._purchase_available(scenario_id, profile_id, current_time, state, events)
                    self._apply_milestones(scenario_id, profile_id, current_time, state, events)
                    self._apply_prestige(scenario_id, profile_id, current_time, state, events)
                else:
                    self._purchase_available(scenario_id, profile_id, current_time, state, events)
                    self._apply_milestones(scenario_id, profile_id, current_time, state, events)
                    self._apply_prestige(scenario_id, profile_id, current_time, state, events)
                self._update_unlocks(scenario_id, profile_id, current_time, state, events)
                if current_time == duration_seconds or current_time % scenario.record_interval_seconds == 0:
                    timeline.append(self._timeline_row(scenario_id, profile_id, current_time, state))
        return SimulationResult(scenario_id=scenario_id, timeline=timeline, events=events)

    def _next_time(
        self,
        profile_id: str,
        state: SimulationState,
        current_time: int,
        duration_seconds: int,
        record_interval_seconds: int,
        time_mode: str,
    ) -> int:
        if time_mode == "tick":
            return min(duration_seconds, current_time + self.model.config.tick_seconds)
        candidates = {duration_seconds}
        next_record = ((current_time // record_interval_seconds) + 1) * record_interval_seconds
        if current_time < next_record <= duration_seconds:
            candidates.add(next_record)
        next_offline = self._next_offline_time(profile_id, current_time, duration_seconds)
        if next_offline is not None:
            candidates.add(next_offline)
        next_affordable = self._next_affordable_time(profile_id, state, current_time, duration_seconds)
        if next_affordable is not None:
            candidates.add(next_affordable)
        next_prestige = self._next_prestige_time(profile_id, state, current_time, duration_seconds)
        if next_prestige is not None:
            candidates.add(next_prestige)
        next_time = min(candidate for candidate in candidates if candidate > current_time)
        return current_time + self.time.analytic_leap(current_time, next_time)

    def _next_offline_time(
        self, profile_id: str, current_time: int, duration_seconds: int
    ) -> int | None:
        profile = self.model.player_profiles[profile_id]
        pattern = self.model.session_patterns.get(profile.session_pattern, {})
        every = int(pattern.get("offline_every_seconds", 0) or 0)
        duration = int(pattern.get("offline_duration_seconds", 0) or 0)
        if every <= 0 or duration <= 0:
            return None
        next_time = ((current_time // every) + 1) * every
        if next_time <= duration_seconds:
            return next_time
        return None

    def _next_affordable_time(
        self,
        profile_id: str,
        state: SimulationState,
        current_time: int,
        duration_seconds: int,
    ) -> int | None:
        income = self._resource_cps(profile_id, state)
        candidates: list[int] = []
        for generator_id, generator in self.model.generators.items():
            if not evaluate(generator.unlock_condition, lambda item_id: state.generators_owned.get(item_id, 0)):
                continue
            cost = self.model.generator_cost(generator_id, state.generators_owned[generator_id])
            seconds = self.time.seconds_until_affordable(
                state.resources[generator.cost_resource],
                cost,
                income.get(generator.cost_resource, SimNumber.zero()),
            )
            if seconds is None:
                continue
            candidates.append(current_time + max(seconds, self.model.config.tick_seconds))
        for upgrade_id, upgrade in self.model.upgrades.items():
            if upgrade_id in state.upgrades_purchased:
                continue
            if not evaluate(upgrade.unlock_condition, lambda item_id: state.generators_owned.get(item_id, 0)):
                continue
            cost = self.model.upgrade_cost(upgrade_id)
            seconds = self.time.seconds_until_affordable(
                state.resources[upgrade.cost_resource],
                cost,
                income.get(upgrade.cost_resource, SimNumber.zero()),
            )
            if seconds is None:
                continue
            candidates.append(current_time + max(seconds, self.model.config.tick_seconds))
        bounded = [candidate for candidate in candidates if current_time < candidate <= duration_seconds]
        if not bounded:
            return None
        return min(bounded)

    def _next_prestige_time(
        self,
        profile_id: str,
        state: SimulationState,
        current_time: int,
        duration_seconds: int,
    ) -> int | None:
        income = self._resource_cps(profile_id, state)
        profile = self.model.player_profiles[profile_id]
        candidates: list[int] = []
        for layer in self.model.prestige_layers.values():
            if not evaluate(layer.unlock_condition, lambda item_id: state.generators_owned.get(item_id, 0)):
                continue
            if not self._prestige_policy_ready(profile_id, state):
                continue
            efficiency = profile.source_efficiency.get("prestige", SimNumber.one())
            if efficiency <= SimNumber.zero():
                continue
            exponent = SimNumber.parse(layer.exponent)
            if exponent <= SimNumber.zero():
                continue
            required_raw_gain = (self._required_prestige_gain(profile_id, layer) / efficiency).ceil()
            threshold = SimNumber.parse(layer.divisor) * (
                required_raw_gain ** (SimNumber.one() / exponent)
            )
            seconds = self.time.seconds_until_affordable(
                state.resources[layer.trigger_resource],
                threshold,
                income.get(layer.trigger_resource, SimNumber.zero()),
            )
            if seconds is None:
                continue
            candidates.append(current_time + max(seconds, self.model.config.tick_seconds))
        bounded = [candidate for candidate in candidates if current_time < candidate <= duration_seconds]
        if not bounded:
            return None
        return min(bounded)

    def _resource_cps(self, profile_id: str, state: SimulationState) -> dict[str, SimNumber]:
        profile = self.model.player_profiles[profile_id]
        income: dict[str, SimNumber] = {}
        for generator_id, generator in self.model.generators.items():
            owned = state.generators_owned[generator_id]
            if owned <= 0:
                continue
            output = ModifierStack.apply_generator_output(self.model, state, generator_id, owned)
            efficiency = profile.source_efficiency.get(generator.source_type, SimNumber.one())
            income[generator.output_resource] = (
                income.get(generator.output_resource, SimNumber.zero()) + output * efficiency
            )
        return income

    def _produce(self, profile_id: str, state: SimulationState, delta_seconds: int) -> None:
        profile = self.model.player_profiles[profile_id]
        for generator_id, generator in self.model.generators.items():
            owned = state.generators_owned[generator_id]
            if owned <= 0:
                continue
            output = ModifierStack.apply_generator_output(self.model, state, generator_id, owned)
            efficiency = profile.source_efficiency.get(generator.source_type, SimNumber.one())
            produced = output * efficiency * SimNumber.parse(delta_seconds)
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
            details = {
                "cost": action.cost.to_decimal_string(),
                "resource": action.cost_resource,
                **self.model.source_details(action.kind, action.item_id),
                "formula_trace": action_formula_trace(self.model, action, state),
            }
            self.policy.apply_action(action, state)
            events.append(
                Event(
                    scenario_id=scenario_id,
                    profile_id=profile_id,
                    time_seconds=current_time,
                    kind=action.kind,
                    item_id=action.item_id,
                    details=details,
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
                        **self.model.source_details("milestone", milestone_id),
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
            if not self._prestige_policy_ready(profile_id, state):
                continue
            if gain < self._required_prestige_gain(profile_id, layer):
                continue
            formula_trace = prestige_formula_trace(self.model, layer_id, state)
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
                        **self.model.source_details("prestige", layer_id),
                        "formula_trace": formula_trace,
                    },
                )
            )

    def _required_prestige_gain(self, profile_id: str, layer) -> SimNumber:
        required = SimNumber.parse(layer.min_gain)
        profile = self.model.player_profiles[profile_id]
        if profile.prestige_policy == "conservative":
            return required * SimNumber.parse("2")
        return required

    def _prestige_policy_ready(self, profile_id: str, state: SimulationState) -> bool:
        profile = self.model.player_profiles[profile_id]
        if profile.prestige_policy != "milestone_based":
            return True
        return set(self.model.milestones).issubset(state.milestones_claimed)

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
                        self.model.source_details("generator", generator_id),
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
                        self.model.source_details("upgrade", upgrade_id),
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
            total_cps=self._total_cps(profile_id, state).to_decimal_string(),
        )

    def _total_cps(self, profile_id: str, state: SimulationState) -> SimNumber:
        return sum(self._resource_cps(profile_id, state).values(), SimNumber.zero())
