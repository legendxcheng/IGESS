from __future__ import annotations

from .conditions import evaluate
from .modifiers import ModifierStack
from .numbers import SimNumber
from .schema import Action, EconomyModel, SimulationState


class PolicyEngine:
    def __init__(self, model: EconomyModel):
        self.model = model

    def choose_action(self, profile_id: str, state: SimulationState) -> Action | None:
        profile = self.model.player_profiles[profile_id]
        policy = self.model.behavior_policies[profile.behavior_policy]
        actions = self.available_actions(profile_id, state)
        if not actions:
            return None
        policy_type = policy["type"]
        if policy_type == "cheap_unlock_first":
            return min(actions, key=lambda action: (action.cost.decimal, action.kind, action.item_id))
        if policy_type == "new_content_bias":
            return min(
                actions,
                key=lambda action: (
                    self._owned_count(action, state) > 0,
                    action.kind != "buy_upgrade",
                    action.cost.decimal,
                    action.item_id,
                ),
            )
        if policy_type == "fastest_payback":
            scored = [self._with_payback_score(action, state, policy) for action in actions]
            return min(scored, key=lambda action: (action.score.decimal, action.cost.decimal, action.item_id))
        return None

    def available_actions(self, profile_id: str, state: SimulationState) -> list[Action]:
        actions: list[Action] = []
        for generator_id, generator in self.model.generators.items():
            if not self._is_unlocked(generator.unlock_condition, state):
                continue
            cost = self.model.generator_cost(generator_id, state.generators_owned[generator_id])
            if state.resources[generator.cost_resource] >= cost:
                actions.append(
                    Action(
                        kind="buy_generator",
                        item_id=generator_id,
                        cost_resource=generator.cost_resource,
                        cost=cost,
                        score=cost,
                    )
                )
        for upgrade_id, upgrade in self.model.upgrades.items():
            if upgrade_id in state.upgrades_purchased:
                continue
            if not self._is_unlocked(upgrade.unlock_condition, state):
                continue
            cost = self.model.upgrade_cost(upgrade_id)
            if state.resources[upgrade.cost_resource] >= cost:
                actions.append(
                    Action(
                        kind="buy_upgrade",
                        item_id=upgrade_id,
                        cost_resource=upgrade.cost_resource,
                        cost=cost,
                        score=cost,
                    )
                )
        return sorted(actions, key=lambda action: (action.kind, action.item_id))

    def apply_action(self, action: Action, state: SimulationState) -> None:
        state.resources[action.cost_resource] = state.resources[action.cost_resource] - action.cost
        if action.kind == "buy_generator":
            state.generators_owned[action.item_id] += 1
        elif action.kind == "buy_upgrade":
            state.upgrades_purchased.add(action.item_id)

    def _with_payback_score(
        self, action: Action, state: SimulationState, policy: dict
    ) -> Action:
        benefit = self._action_benefit(action, state)
        if policy.get("include_unlock_chain_value") and int(policy.get("lookahead_depth", 0)) >= 1:
            benefit += self._unlock_chain_bonus(action, state)
        if benefit <= SimNumber.zero():
            score = SimNumber.parse("1e99")
        else:
            score = action.cost / benefit
        return Action(action.kind, action.item_id, action.cost_resource, action.cost, score)

    def _action_benefit(self, action: Action, state: SimulationState) -> SimNumber:
        if action.kind == "buy_generator":
            before = self.generator_total_output(action.item_id, state)
            simulated = state.copy()
            simulated.generators_owned[action.item_id] += 1
            after = self.generator_total_output(action.item_id, simulated)
            return after - before
        if action.kind == "buy_upgrade":
            upgrade = self.model.upgrades[action.item_id]
            target = upgrade.target.removeprefix("generator:").removesuffix(".output")
            targets = self.model.generators if target == "*" else {target: self.model.generators[target]}
            before = sum((self.generator_total_output(item_id, state) for item_id in targets), SimNumber.zero())
            simulated = state.copy()
            simulated.upgrades_purchased.add(action.item_id)
            after = sum((self.generator_total_output(item_id, simulated) for item_id in targets), SimNumber.zero())
            return after - before
        return SimNumber.zero()

    def _unlock_chain_bonus(self, action: Action, state: SimulationState) -> SimNumber:
        simulated = state.copy()
        if action.kind == "buy_generator":
            simulated.generators_owned[action.item_id] += 1
        elif action.kind == "buy_upgrade":
            simulated.upgrades_purchased.add(action.item_id)
        bonus = SimNumber.zero()
        for upgrade_id, upgrade in self.model.upgrades.items():
            if upgrade_id in state.upgrades_purchased:
                continue
            was_unlocked = self._is_unlocked(upgrade.unlock_condition, state)
            now_unlocked = self._is_unlocked(upgrade.unlock_condition, simulated)
            if not was_unlocked and now_unlocked:
                target = upgrade.target.removeprefix("generator:").removesuffix(".output")
                if target == "*":
                    for generator_id in self.model.generators:
                        bonus += self.generator_total_output(generator_id, simulated)
                else:
                    bonus += self.generator_total_output(target, simulated) * SimNumber.parse(upgrade.value)
        return bonus

    def generator_total_output(self, generator_id: str, state: SimulationState) -> SimNumber:
        owned = state.generators_owned.get(generator_id, 0)
        if owned <= 0:
            return SimNumber.zero()
        return ModifierStack.apply_generator_output(self.model, state, generator_id, owned)

    def _is_unlocked(self, condition: str, state: SimulationState) -> bool:
        return evaluate(condition, lambda item_id: state.generators_owned.get(item_id, 0))

    def _owned_count(self, action: Action, state: SimulationState) -> int:
        if action.kind == "buy_generator":
            return state.generators_owned[action.item_id]
        if action.kind == "buy_upgrade":
            return int(action.item_id in state.upgrades_purchased)
        return 0
