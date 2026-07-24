from __future__ import annotations

import math
from typing import Any, Mapping

from .fish_state_model import (
    FishStateValidationContext,
    PlayerState,
    _expect_object,
    _fail,
)


def player_state_to_dict(
    self: PlayerState,
    *,
    context: FishStateValidationContext | None = None,
) -> dict[str, Any]:
    self.validate(context)
    return {
        "meta": {
            "createdAt": self.meta.created_at,
            "revision": self.meta.revision,
        },
        "production": {
            "lastSettledAt": self.production.last_settled_at,
        },
        "wallet": {
            "money": self.wallet.money.to_dict(),
            "material": self.wallet.material.to_dict(),
            "strength": self.wallet.strength.to_dict(),
        },
        "torpedo": {
            "selectedId": self.torpedo.selected_id,
            "ownedIds": sorted(self.torpedo.owned_ids),
        },
        "barbell": {
            "equippedId": self.barbell.equipped_id,
            "owned": [
                {"barbellId": entry.barbell_id, "count": entry.count}
                for entry in sorted(
                    self.barbell.owned,
                    key=lambda entry: entry.barbell_id,
                )
            ],
        },
        "fishHall": {
            "upgradeLevel": self.fish_hall.upgrade_level,
        },
        "fish": {
            "nextInstanceId": self.fish.next_instance_id,
            "items": [
                {
                    "instanceId": item.instance_id,
                    "fishId": item.fish_id,
                    "mutationId": item.mutation_id,
                    "level": item.level,
                    "weightGram": item.weight_gram,
                    "hallSlot": item.hall_slot,
                }
                for item in sorted(
                    self.fish.items,
                    key=lambda item: item.instance_id,
                )
            ],
        },
        "trashMan": {
            "realmId": self.trash_man.realm_id,
            "highestRealmId": self.trash_man.highest_realm_id,
            "upgrades": [
                {
                    "upgradeId": upgrade.upgrade_id,
                    "level": upgrade.level,
                }
                for upgrade in sorted(
                    self.trash_man.upgrades,
                    key=lambda upgrade: upgrade.upgrade_id,
                )
            ],
            "trainingProgressSeconds": (
                self.trash_man.training_progress_seconds
            ),
            "breakthrough": {
                "active": self.trash_man.breakthrough.active,
                "targetRealmId": (
                    self.trash_man.breakthrough.target_realm_id
                ),
                "progressSeconds": (
                    self.trash_man.breakthrough.progress_seconds
                ),
            },
            "processing": {
                "activeTrashId": (
                    self.trash_man.processing.active_trash_id
                ),
                "activeProgressSeconds": (
                    self.trash_man.processing.active_progress_seconds
                ),
                "stocks": [
                    {"trashId": stock.trash_id, "count": stock.count}
                    for stock in sorted(
                        self.trash_man.processing.stocks,
                        key=lambda stock: stock.trash_id,
                    )
                ],
            },
        },
        "rebirth": {
            "strengthCompletedCount": (
                self.rebirth.strength_completed_count
            ),
            "trashManCompletedCount": (
                self.rebirth.trash_man_completed_count
            ),
        },
        "collection": {
            "unlockedKeys": sorted(self.collection.unlocked_keys),
            "viewedKeys": sorted(self.collection.viewed_keys),
            "claimedRewardIds": sorted(
                self.collection.claimed_reward_ids
            ),
        },
        "automation": {
            "autoThrowUnlocked": self.automation.auto_throw_unlocked,
            "autoThrowEnabled": self.automation.auto_throw_enabled,
        },
        "statistics": {
            "totalThrows": self.statistics.total_throws,
            "totalFishCaught": self.statistics.total_fish_caught,
            "maxDistanceCm": self.statistics.max_distance_cm,
        },
    }


def normalize_player_state(
    value: Mapping[str, Any],
    *,
    now: int = 0,
    context: FishStateValidationContext | None = None,
) -> tuple[PlayerState, bool]:
    """Fill missing v1 fields only for new archives or explicit migrations."""

    payload = _deep_copy_plain(_expect_object(value, "$"))
    defaults = PlayerState.new(now).to_dict()
    changed = _merge_missing(payload, defaults)
    effective_context = context or FishStateValidationContext(now=now)
    return PlayerState.from_dict(payload, context=effective_context), changed


def _deep_copy_plain(value: Any) -> Any:
    if type(value) is dict:
        return {key: _deep_copy_plain(item) for key, item in value.items()}
    if type(value) is list:
        return [_deep_copy_plain(item) for item in value]
    if value is None or type(value) in {bool, int, str}:
        return value
    if type(value) is float and math.isfinite(value):
        return value
    _fail("archive_schema_non_plain_data", "$")


def _merge_missing(target: dict[str, Any], defaults: dict[str, Any]) -> bool:
    changed = False
    for key, default in defaults.items():
        if key not in target:
            target[key] = _deep_copy_plain(default)
            changed = True
        elif type(target[key]) is dict and type(default) is dict:
            if _merge_missing(target[key], default):
                changed = True
    return changed
