from __future__ import annotations

from .formula import FormulaEngine
from .linter import ConfigLinter
from .numbers import SimNumber
from .schema import EconomyModel, RawConfig, RuntimeConfig


class ModelBuilder:
    @classmethod
    def build(cls, raw: RawConfig) -> EconomyModel:
        ConfigLinter.validate(raw)
        formulas = {
            formula_id: FormulaEngine.compile(formula_id, formula.args, formula.expr)
            for formula_id, formula in raw.rules.formulas.items()
        }
        return EconomyModel(
            config=RuntimeConfig(
                model_id=raw.rules.model.id,
                tick_seconds=raw.rules.model.tick_seconds,
                number_backend=raw.rules.model.number_backend,
                random_seed=int(raw.rules.model.random_seed or 0),
                engine_id=raw.rules.model.engine_id,
            ),
            resources={row.id: row for row in raw.resources},
            generators={row.id: row for row in raw.generators},
            activities={row.id: row for row in raw.activities},
            activity_outputs={row.id: row for row in raw.activity_outputs},
            upgrades={row.id: row for row in raw.upgrades},
            constants={row.id: SimNumber.parse(row.value) for row in raw.constants},
            milestones={row.id: row for row in raw.milestones},
            prestige_layers={row.id: row for row in raw.prestige_layers},
            formulas=formulas,
            generator_types=raw.rules.generator_types,
            source_types=raw.rules.source_types,
            modifier_pipeline=raw.rules.modifier_pipeline,
            modifier_types=raw.rules.modifier_types,
            behavior_policies=raw.rules.behavior_policies,
            session_patterns=raw.rules.session_patterns,
            player_profiles=raw.rules.player_profiles,
            scenarios=raw.rules.scenarios,
            rng_tables=raw.rules.rng_tables,
            rng_scenarios=raw.rules.rng_scenarios,
            engine_settings=raw.rules.engine_settings,
        )
