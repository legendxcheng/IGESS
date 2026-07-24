from __future__ import annotations

from dataclasses import dataclass

from .fish_barbell import BarbellProductionSnapshot
from .fish_hall import FishHallIncomeSnapshot, FishIncomeTrace
from .fish_state import FISH_MAX_LEVEL, PlayerState
from .numbers import SimNumber


class FishCommandError(ValueError):
    """Raised when a Fish domain command cannot be committed."""


@dataclass(frozen=True)
class AppliedThrowResolution:
    """Committed state and stable facts produced by one throw transaction."""

    state: PlayerState
    fish_instance_id: int
    trash_stock_count: int
    fish_hall: FishHallIncomeSnapshot

    def event_details(self) -> dict[str, str]:
        details = {
            "reward_application": "applied_to_player_state",
            "fish_instance_id": str(self.fish_instance_id),
            "trash_stock_count": str(self.trash_stock_count),
            "player_state_revision": str(self.state.meta.revision),
        }
        details.update(self.fish_hall.event_details(suffix="after_throw"))
        return details


@dataclass(frozen=True)
class AppliedFishHallSettlement:
    state: PlayerState
    from_time_seconds: int
    to_time_seconds: int
    elapsed_seconds: int
    money_added: SimNumber
    fish_hall: FishHallIncomeSnapshot

    def event_details(self) -> dict[str, str]:
        details = {
            "fish_hall_settlement_from_seconds": str(self.from_time_seconds),
            "fish_hall_settlement_to_seconds": str(self.to_time_seconds),
            "fish_hall_settlement_elapsed_seconds": str(self.elapsed_seconds),
            "fish_hall_money_added": self.money_added.to_decimal_string(),
        }
        details.update(self.fish_hall.event_details(suffix="before_throw"))
        return details


@dataclass(frozen=True)
class AppliedFishUpgrade:
    state: PlayerState
    instance_id: int
    from_level: int
    to_level: int
    price: SimNumber
    money_before: SimNumber
    money_after: SimNumber
    income_before: FishIncomeTrace
    income_after: FishIncomeTrace
    fish_hall_before: FishHallIncomeSnapshot
    fish_hall_after: FishHallIncomeSnapshot

    def event_details(self) -> dict[str, str]:
        details = {
            "fish_instance_id": str(self.instance_id),
            "fish_level_before": str(self.from_level),
            "fish_level_after": str(self.to_level),
            "fish_max_level": str(FISH_MAX_LEVEL),
            "fish_upgrade_price": self.price.to_decimal_string(),
            "fish_upgrade_price_formula": (
                "base_money_per_second*1.5^(current_level-1)"
            ),
            "fish_upgrade_price_uses_mutation": "false",
            "fish_income_formula": (
                "base_money_per_second*1.25^(level-1)"
                "*mutation_income_multiplier"
            ),
            "fish_income_per_second_before": (
                self.income_before.income_per_second.to_decimal_string()
            ),
            "fish_income_per_second_after": (
                self.income_after.income_per_second.to_decimal_string()
            ),
            "money_before_fish_upgrade": (
                self.money_before.to_decimal_string()
            ),
            "money_after_fish_upgrade": self.money_after.to_decimal_string(),
            "player_state_revision": str(self.state.meta.revision),
        }
        details.update(
            self.fish_hall_before.event_details(suffix="before_upgrade")
        )
        details.update(
            self.fish_hall_after.event_details(suffix="after_upgrade")
        )
        return details


@dataclass(frozen=True)
class AppliedFishHallUpgrade:
    state: PlayerState
    from_level: int
    to_level: int
    price: SimNumber
    material_before: SimNumber
    material_after: SimNumber
    max_level: int
    fish_hall_before: FishHallIncomeSnapshot
    fish_hall_after: FishHallIncomeSnapshot

    def event_details(self) -> dict[str, str]:
        details = {
            "fish_hall_upgrade_level_before": str(self.from_level),
            "fish_hall_upgrade_level_after": str(self.to_level),
            "fish_hall_upgrade_price": self.price.to_decimal_string(),
            "fish_hall_upgrade_price_resource": "material",
            "fish_hall_upgrade_price_source": (
                "tbfishhallupgrade[current_upgrade_level].upgradePrice"
            ),
            "fish_hall_upgrade_max_level": str(self.max_level),
            "fish_hall_upgrade_layout_policy": "fixed_max_income",
            "material_before_fish_hall_upgrade": (
                self.material_before.to_decimal_string()
            ),
            "material_after_fish_hall_upgrade": (
                self.material_after.to_decimal_string()
            ),
            "player_state_revision": str(self.state.meta.revision),
        }
        details.update(
            self.fish_hall_before.event_details(
                suffix="before_hall_upgrade"
            )
        )
        details.update(
            self.fish_hall_after.event_details(
                suffix="after_hall_upgrade"
            )
        )
        return details


@dataclass(frozen=True)
class AppliedStrengthRebirth:
    state: PlayerState
    from_completed_count: int
    to_completed_count: int
    strength_requirement: SimNumber
    strength_before: SimNumber
    strength_after: SimNumber
    fish_hall_before: FishHallIncomeSnapshot
    fish_hall_after: FishHallIncomeSnapshot

    def event_details(self) -> dict[str, str]:
        details = {
            "strength_rebirth_completed_count_before": str(
                self.from_completed_count
            ),
            "strength_rebirth_completed_count_after": str(
                self.to_completed_count
            ),
            "strength_rebirth_table_id": str(self.to_completed_count),
            "strength_rebirth_requirement": (
                self.strength_requirement.to_decimal_string()
            ),
            "strength_rebirth_requirement_source": (
                "tbstrengthrebirth"
                f"[id={self.to_completed_count}].strengthRequirement"
            ),
            "strength_before_rebirth": (
                self.strength_before.to_decimal_string()
            ),
            "strength_after_rebirth": (
                self.strength_after.to_decimal_string()
            ),
            "strength_rebirth_reset_fields": "wallet.strength",
            "strength_rebirth_preserved_fields": (
                "fish,trash,money,material,torpedo,barbell,fish_hall,"
                "trash_man,collection,automation,statistics"
            ),
            "strength_rebirth_multiplier_before": (
                self.fish_hall_before.strength_rebirth_multiplier
                .to_decimal_string()
            ),
            "strength_rebirth_multiplier_after": (
                self.fish_hall_after.strength_rebirth_multiplier
                .to_decimal_string()
            ),
            "strength_rebirth_multiplier_source": (
                "completed_count_0_is_default_1x_not_in_table;"
                "completed_count_n_uses_tbstrengthrebirth_id_n"
            ),
            "player_state_revision": str(self.state.meta.revision),
        }
        details.update(
            self.fish_hall_before.event_details(
                suffix="before_strength_rebirth"
            )
        )
        details.update(
            self.fish_hall_after.event_details(
                suffix="after_strength_rebirth"
            )
        )
        return details


@dataclass(frozen=True)
class AppliedBarbellSynthesis:
    state: PlayerState
    barbell_id: int
    price: SimNumber
    material_before: SimNumber
    material_after: SimNumber
    count_before: int
    count_after: int
    production_before: BarbellProductionSnapshot
    production_after: BarbellProductionSnapshot

    def event_details(self) -> dict[str, str]:
        details = {
            "barbell_id": str(self.barbell_id),
            "barbell_synthesis_price": self.price.to_decimal_string(),
            "barbell_synthesis_price_resource": "material",
            "barbell_synthesis_price_source": "tbbarbell.price",
            "barbell_count_before": str(self.count_before),
            "barbell_count_after": str(self.count_after),
            "barbell_auto_equip_policy": "highest_strength_per_second",
            "material_before_barbell_synthesis": (
                self.material_before.to_decimal_string()
            ),
            "material_after_barbell_synthesis": (
                self.material_after.to_decimal_string()
            ),
            "player_state_revision": str(self.state.meta.revision),
        }
        details.update(
            self.production_before.event_details(
                suffix="before_synthesis"
            )
        )
        details.update(
            self.production_after.event_details(
                suffix="after_synthesis"
            )
        )
        return details


@dataclass(frozen=True)
class AppliedBarbellEquip:
    state: PlayerState
    barbell_id: int
    production_before: BarbellProductionSnapshot
    production_after: BarbellProductionSnapshot

    def event_details(self) -> dict[str, str]:
        details = {
            "barbell_id": str(self.barbell_id),
            "barbell_equip_source": "explicit_domain_command",
            "player_state_revision": str(self.state.meta.revision),
        }
        details.update(
            self.production_before.event_details(suffix="before_equip")
        )
        details.update(
            self.production_after.event_details(suffix="after_equip")
        )
        return details
