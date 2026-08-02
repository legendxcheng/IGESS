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
    fish_hall_before: FishHallIncomeSnapshot
    fish_hall: FishHallIncomeSnapshot

    def event_details(self) -> dict[str, str]:
        cps_before = self.fish_hall_before.total_income_per_second
        cps_after = self.fish_hall.total_income_per_second
        cps_delta = cps_after - cps_before
        changed_layout = (
            self.fish_hall_before.deployed_instance_ids
            != self.fish_hall.deployed_instance_ids
        )
        details = {
            "reward_application": "applied_to_player_state",
            "fish_instance_id": str(self.fish_instance_id),
            "trash_stock_count": str(self.trash_stock_count),
            "player_state_revision": str(self.state.meta.revision),
            "fish_hall_cps_before": cps_before.to_decimal_string(),
            "fish_hall_cps_after": cps_after.to_decimal_string(),
            "fish_hall_cps_delta": cps_delta.to_decimal_string(),
            "changed_best_hall_layout": str(changed_layout).lower(),
            "is_persistent_progression": str(
                cps_delta > SimNumber.zero()
            ).lower(),
        }
        details.update(
            self.fish_hall_before.event_details(suffix="before_throw")
        )
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
    material_before: SimNumber
    material_after: SimNumber
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
                "base_money_per_second*mutation_income_multiplier"
                "*1.5^(current_level-1)"
            ),
            "fish_upgrade_price_resource": "material",
            "fish_upgrade_price_uses_mutation": "true",
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
            "material_before_fish_upgrade": (
                self.material_before.to_decimal_string()
            ),
            "material_after_fish_upgrade": (
                self.material_after.to_decimal_string()
            ),
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
    material_multiplier_before: SimNumber
    material_multiplier_after: SimNumber

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
            "strength_rebirth_material_multiplier_before": (
                self.material_multiplier_before.to_decimal_string()
            ),
            "strength_rebirth_material_multiplier_after": (
                self.material_multiplier_after.to_decimal_string()
            ),
            "strength_rebirth_material_multiplier_source": (
                "completed_count_0_is_default_1x_not_in_table;"
                "completed_count_n_uses_"
                "tbstrengthrebirth[id=n].materialOutputMultiplier"
            ),
            "player_state_revision": str(self.state.meta.revision),
        }
        return details


@dataclass(frozen=True)
class AppliedTrashManRebirth:
    state: PlayerState
    from_completed_count: int
    to_completed_count: int
    realm_requirement: int
    realm_before: int
    realm_after: int
    highest_realm_id: int
    training_progress_seconds_before: int
    training_progress_seconds_after: int
    fish_hall_multiplier_before: SimNumber
    fish_hall_multiplier_after: SimNumber

    def event_details(self) -> dict[str, str]:
        return {
            "trash_man_rebirth_completed_count_before": str(
                self.from_completed_count
            ),
            "trash_man_rebirth_completed_count_after": str(
                self.to_completed_count
            ),
            "trash_man_rebirth_table_id": str(self.to_completed_count),
            "trash_man_rebirth_realm_requirement": str(
                self.realm_requirement
            ),
            "trash_man_rebirth_realm_requirement_source": (
                "tbtrashmanrebirth"
                f"[id={self.to_completed_count}].realmRequirement"
            ),
            "trash_man_rebirth_realm_requirement_check": (
                "current_realm_id>=realmRequirement"
            ),
            "trash_man_rebirth_realm_before": str(self.realm_before),
            "trash_man_rebirth_realm_after": str(self.realm_after),
            "trash_man_rebirth_highest_realm_preserved": str(
                self.highest_realm_id
            ),
            "trash_man_training_progress_seconds_before_rebirth": str(
                self.training_progress_seconds_before
            ),
            "trash_man_training_progress_seconds_after_rebirth": str(
                self.training_progress_seconds_after
            ),
            "trash_man_rebirth_reset_fields": (
                "trashMan.realmId,trashMan.trainingProgressSeconds"
            ),
            "trash_man_rebirth_preserved_fields": (
                "fish,trash,money,material,strength,torpedo,barbell,"
                "fish_hall,trash_man.highest_realm_id,"
                "trash_man.upgrades,trash_man.processing,collection,"
                "automation,statistics,strength_rebirth"
            ),
            "trash_man_rebirth_fish_hall_multiplier_before": (
                self.fish_hall_multiplier_before.to_decimal_string()
            ),
            "trash_man_rebirth_fish_hall_multiplier_after": (
                self.fish_hall_multiplier_after.to_decimal_string()
            ),
            "trash_man_rebirth_fish_hall_multiplier_source": (
                "completed_count_0_is_default_1x_not_in_table;"
                "completed_count_n_uses_"
                "tbtrashmanrebirth[id=n].fishHallOutputMultiplier"
            ),
            "player_state_revision": str(self.state.meta.revision),
        }


@dataclass(frozen=True)
class AppliedTrashManBreakthroughFunding:
    state: PlayerState
    from_realm_id: int
    target_realm_id: int
    price: SimNumber
    required_online_seconds: int
    material_before: SimNumber
    material_after: SimNumber

    def event_details(self) -> dict[str, str]:
        return {
            "trash_man_breakthrough_realm_before": str(self.from_realm_id),
            "trash_man_breakthrough_target_realm_id": str(
                self.target_realm_id
            ),
            "trash_man_breakthrough_price": self.price.to_decimal_string(),
            "trash_man_breakthrough_price_resource": "material",
            "trash_man_breakthrough_price_source": (
                "tbtrashmanrealm"
                f"[id={self.from_realm_id}].materialRequireToNextRealm"
            ),
            "trash_man_breakthrough_required_online_seconds": str(
                self.required_online_seconds
            ),
            "trash_man_breakthrough_duration_source": (
                "tbtrashmanrealm"
                f"[id={self.from_realm_id}]"
                ".breakthroughSecondsToNextRealm"
            ),
            "material_before_trash_man_breakthrough": (
                self.material_before.to_decimal_string()
            ),
            "material_after_trash_man_breakthrough": (
                self.material_after.to_decimal_string()
            ),
            "trash_man_breakthrough_online_only": "true",
            "trash_man_breakthrough_processing_continues": "true",
            "player_state_revision": str(self.state.meta.revision),
        }


@dataclass(frozen=True)
class AppliedBarbellSynthesis:
    state: PlayerState
    barbell_id: int
    price: SimNumber
    money_before: SimNumber
    money_after: SimNumber
    count_before: int
    count_after: int
    production_before: BarbellProductionSnapshot
    production_after: BarbellProductionSnapshot

    def event_details(self) -> dict[str, str]:
        details = {
            "barbell_id": str(self.barbell_id),
            "barbell_synthesis_price": self.price.to_decimal_string(),
            "barbell_synthesis_price_resource": "money",
            "barbell_synthesis_price_source": "tbbarbell.price",
            "barbell_count_before": str(self.count_before),
            "barbell_count_after": str(self.count_after),
            "barbell_auto_equip_policy": "highest_strength_per_second",
            "money_before_barbell_synthesis": (
                self.money_before.to_decimal_string()
            ),
            "money_after_barbell_synthesis": (
                self.money_after.to_decimal_string()
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


@dataclass(frozen=True)
class AppliedTorpedoPurchase:
    state: PlayerState
    from_torpedo_id: int
    to_torpedo_id: int
    price: SimNumber
    material_before: SimNumber
    material_after: SimNumber
    power_before: SimNumber
    power_after: SimNumber
    trash_luck_before: float
    trash_luck_after: float

    def event_details(self) -> dict[str, str]:
        before_luck = format(self.trash_luck_before, ".17g")
        after_luck = format(self.trash_luck_after, ".17g")
        return {
            "torpedo_id_before": str(self.from_torpedo_id),
            "torpedo_id_after": str(self.to_torpedo_id),
            "torpedo_purchase_price": self.price.to_decimal_string(),
            "torpedo_purchase_price_resource": "material",
            "torpedo_purchase_price_source": "tbtorpedo.price",
            "torpedo_power_before": self.power_before.to_decimal_string(),
            "torpedo_power_after": self.power_after.to_decimal_string(),
            "trash_luck_before": before_luck,
            "trash_luck_after": after_luck,
            "trash_luck": after_luck,
            "trash_luck_delta": format(
                self.trash_luck_after - self.trash_luck_before,
                ".17g",
            ),
            "material_before_torpedo_purchase": (
                self.material_before.to_decimal_string()
            ),
            "material_after_torpedo_purchase": (
                self.material_after.to_decimal_string()
            ),
            "torpedo_auto_select_policy": "purchased_torpedo",
            "player_state_revision": str(self.state.meta.revision),
        }
