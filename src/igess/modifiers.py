from __future__ import annotations

from dataclasses import dataclass

from .numbers import SimNumber
from .schema import EconomyModel, SimulationState


@dataclass(frozen=True)
class Modifier:
    stage: str
    value: SimNumber


class ModifierStack:
    @classmethod
    def apply(cls, base: SimNumber, modifiers: list[Modifier]) -> SimNumber:
        flat = SimNumber.zero()
        add_pct = SimNumber.zero()
        mult = SimNumber.one()
        exp = SimNumber.one()
        for modifier in modifiers:
            if modifier.stage == "flat":
                flat += modifier.value
            elif modifier.stage == "add_pct":
                add_pct += modifier.value
            elif modifier.stage == "mult":
                mult *= modifier.value
            elif modifier.stage == "exp":
                exp *= modifier.value
        return ((base + flat) * (SimNumber.one() + add_pct) * mult) ** exp

    @classmethod
    def collect_for_generator_output(
        cls, model: EconomyModel, state: SimulationState, generator_id: str
    ) -> list[Modifier]:
        modifiers: list[Modifier] = []
        for upgrade_id in sorted(state.upgrades_purchased):
            upgrade = model.upgrades[upgrade_id]
            if upgrade.target not in {
                f"generator:{generator_id}.output",
                "generator:*.output",
            }:
                continue
            modifiers.append(
                Modifier(
                    stage=model.modifier_types[upgrade.modifier_type],
                    value=SimNumber.parse(upgrade.value),
                )
            )
        return modifiers

    @classmethod
    def apply_generator_output(
        cls, model: EconomyModel, state: SimulationState, generator_id: str, owned: int
    ) -> SimNumber:
        base = model.generator_output(generator_id, owned, SimNumber.one())
        modifiers = cls.collect_for_generator_output(model, state, generator_id)
        return cls.apply(base, modifiers)
