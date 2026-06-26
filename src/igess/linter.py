from __future__ import annotations

from .conditions import referenced_owned_id
from .formula import FormulaCompileError, FormulaEngine
from .schema import RawConfig


class ConfigError(ValueError):
    pass


class ConfigLinter:
    ALLOWED_BACKENDS = {"bignum_log", "native_double", "big_int"}
    ALLOWED_POLICY_TYPES = {"cheap_unlock_first", "fastest_payback", "new_content_bias"}

    @classmethod
    def validate(cls, raw: RawConfig) -> None:
        rules = raw.rules
        if rules.model.number_backend not in cls.ALLOWED_BACKENDS:
            raise ConfigError(f"unknown number_backend '{rules.model.number_backend}'")
        if rules.model.random_seed is None:
            raise ConfigError("model.random_seed is required for deterministic simulation")
        if rules.model.tick_seconds <= 0:
            raise ConfigError("model.tick_seconds must be positive")

        resource_ids = {row.id for row in raw.resources}
        generator_ids = {row.id for row in raw.generators}

        for formula_id, formula in rules.formulas.items():
            try:
                FormulaEngine.compile(formula_id, formula.args, formula.expr)
            except FormulaCompileError as exc:
                raise ConfigError(str(exc)) from exc

        for generator in raw.generators:
            if generator.output_resource not in resource_ids:
                raise ConfigError(
                    f"generator '{generator.id}' unknown output_resource '{generator.output_resource}'"
                )
            if generator.cost_resource not in resource_ids:
                raise ConfigError(
                    f"generator '{generator.id}' unknown cost_resource '{generator.cost_resource}'"
                )
            if generator.source_type not in rules.source_types:
                raise ConfigError(
                    f"generator '{generator.id}' unknown source_type '{generator.source_type}'"
                )
            if generator.generator_type not in rules.generator_types:
                raise ConfigError(
                    f"generator '{generator.id}' unknown generator_type '{generator.generator_type}'"
                )
            cls._validate_condition(generator.unlock_condition, generator_ids, generator.id)
        cls._validate_unlock_dependency_cycles(raw)

        for upgrade in raw.upgrades:
            if upgrade.cost_resource not in resource_ids:
                raise ConfigError(
                    f"upgrade '{upgrade.id}' unknown cost_resource '{upgrade.cost_resource}'"
                )
            if upgrade.modifier_type not in rules.modifier_types:
                raise ConfigError(
                    f"upgrade '{upgrade.id}' unknown modifier_type '{upgrade.modifier_type}'"
                )
            cls._validate_modifier_target(upgrade.target, generator_ids)
            cls._validate_condition(upgrade.unlock_condition, generator_ids, upgrade.id)

        for milestone in raw.milestones:
            if milestone.reward_resource not in resource_ids:
                raise ConfigError(
                    f"milestone '{milestone.id}' unknown reward_resource '{milestone.reward_resource}'"
                )
            cls._validate_condition(milestone.condition, generator_ids, milestone.id)

        for prestige in raw.prestige_layers:
            if prestige.trigger_resource not in resource_ids:
                raise ConfigError(
                    f"prestige '{prestige.id}' unknown trigger_resource '{prestige.trigger_resource}'"
                )
            if prestige.reward_resource not in resource_ids:
                raise ConfigError(
                    f"prestige '{prestige.id}' unknown reward_resource '{prestige.reward_resource}'"
                )
            if prestige.formula not in rules.formulas:
                raise ConfigError(f"prestige '{prestige.id}' unknown formula '{prestige.formula}'")
            for resource_id in prestige.reset_resources:
                if resource_id not in resource_ids:
                    raise ConfigError(
                        f"prestige '{prestige.id}' unknown reset_resource '{resource_id}'"
                    )
            cls._validate_condition(prestige.unlock_condition, generator_ids, prestige.id)

        for generator_type, data in rules.generator_types.items():
            for field in ("cost_formula", "production_formula"):
                if data.get(field) not in rules.formulas:
                    raise ConfigError(f"generator_type '{generator_type}' unknown {field}")

        for policy_id, policy in rules.behavior_policies.items():
            if policy.get("type") not in cls.ALLOWED_POLICY_TYPES:
                raise ConfigError(f"policy '{policy_id}' unknown type '{policy.get('type')}'")

        for profile_id, profile in rules.player_profiles.items():
            if profile.behavior_policy not in rules.behavior_policies:
                raise ConfigError(
                    f"profile '{profile_id}' unknown behavior_policy '{profile.behavior_policy}'"
                )
            if profile.session_pattern not in rules.session_patterns:
                raise ConfigError(
                    f"profile '{profile_id}' unknown session_pattern '{profile.session_pattern}'"
                )
            for source_type in profile.source_efficiency:
                if source_type not in rules.source_types:
                    raise ConfigError(
                        f"profile '{profile_id}' unknown source_efficiency key '{source_type}'"
                    )

        for scenario_id, scenario in rules.scenarios.items():
            for profile_id in scenario.profiles:
                if profile_id not in rules.player_profiles:
                    raise ConfigError(
                        f"scenario '{scenario_id}' unknown profile '{profile_id}'"
                    )

    @classmethod
    def _validate_condition(cls, condition: str, generator_ids: set[str], owner_id: str) -> None:
        try:
            owned_id = referenced_owned_id(condition)
        except ValueError as exc:
            raise ConfigError(f"'{owner_id}' has unsupported unlock_condition") from exc
        if owned_id and owned_id not in generator_ids:
            raise ConfigError(f"'{owner_id}' unlock_condition references unknown generator '{owned_id}'")

    @classmethod
    def _validate_modifier_target(cls, target: str, generator_ids: set[str]) -> None:
        parts = target.split(":")
        if len(parts) != 2 or parts[0] != "generator" or not parts[1].endswith(".output"):
            raise ConfigError(f"unsupported modifier target '{target}'")
        generator_id = parts[1].removesuffix(".output")
        if generator_id != "*" and generator_id not in generator_ids:
            raise ConfigError(f"unknown modifier target '{target}'")

    @classmethod
    def _validate_unlock_dependency_cycles(cls, raw: RawConfig) -> None:
        graph: dict[str, str] = {}
        generator_ids = {row.id for row in raw.generators}
        for generator in raw.generators:
            dependency = referenced_owned_id(generator.unlock_condition)
            if dependency and dependency in generator_ids:
                graph[generator.id] = dependency

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node: str, path: list[str]) -> None:
            if node in visited:
                return
            if node in visiting:
                cycle_start = path.index(node)
                cycle = " -> ".join(path[cycle_start:] + [node])
                raise ConfigError(f"unlock dependency cycle detected: {cycle}")
            visiting.add(node)
            dependency = graph.get(node)
            if dependency:
                visit(dependency, path + [dependency])
            visiting.remove(node)
            visited.add(node)

        for generator_id in sorted(graph):
            visit(generator_id, [generator_id])
