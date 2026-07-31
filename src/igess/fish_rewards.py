from __future__ import annotations

from dataclasses import dataclass

from .numbers import SimNumber
from .schema import PlayerProfile


FISH_HALL_MONEY_SOURCE = "fish_hall_money"
TRASH_MATERIAL_SOURCE = "trash_material"
BARBELL_STRENGTH_SOURCE = "barbell_strength"


@dataclass(frozen=True)
class FishRewardMultipliers:
    """Profile-owned multipliers for Fish positive resource gains.

    Costs, drop probabilities, and production-table values are intentionally
    outside this object. Missing profile entries preserve the historical 1x
    behavior.
    """

    fish_hall_money: SimNumber = SimNumber.one()
    trash_material: SimNumber = SimNumber.one()
    barbell_strength: SimNumber = SimNumber.one()

    def __post_init__(self) -> None:
        values = {
            FISH_HALL_MONEY_SOURCE: SimNumber.parse(self.fish_hall_money),
            TRASH_MATERIAL_SOURCE: SimNumber.parse(self.trash_material),
            BARBELL_STRENGTH_SOURCE: SimNumber.parse(self.barbell_strength),
        }
        for source_id, value in values.items():
            if value < SimNumber.zero():
                raise ValueError(
                    f"Fish reward multiplier '{source_id}' must be non-negative"
                )
        object.__setattr__(
            self,
            "fish_hall_money",
            values[FISH_HALL_MONEY_SOURCE],
        )
        object.__setattr__(
            self,
            "trash_material",
            values[TRASH_MATERIAL_SOURCE],
        )
        object.__setattr__(
            self,
            "barbell_strength",
            values[BARBELL_STRENGTH_SOURCE],
        )

    @classmethod
    def from_profile(cls, profile: PlayerProfile) -> "FishRewardMultipliers":
        if not isinstance(profile, PlayerProfile):
            raise TypeError("profile must be a PlayerProfile")
        return cls(
            fish_hall_money=profile.source_efficiency.get(
                FISH_HALL_MONEY_SOURCE,
                SimNumber.one(),
            ),
            trash_material=profile.source_efficiency.get(
                TRASH_MATERIAL_SOURCE,
                SimNumber.one(),
            ),
            barbell_strength=profile.source_efficiency.get(
                BARBELL_STRENGTH_SOURCE,
                SimNumber.one(),
            ),
        )

    def manifest_parameters(self) -> dict[str, str]:
        return {
            FISH_HALL_MONEY_SOURCE: (
                self.fish_hall_money.to_decimal_string()
            ),
            TRASH_MATERIAL_SOURCE: (
                self.trash_material.to_decimal_string()
            ),
            BARBELL_STRENGTH_SOURCE: (
                self.barbell_strength.to_decimal_string()
            ),
        }
