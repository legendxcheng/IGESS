from __future__ import annotations

from typing import Any, Mapping

from .fish_state_model import (
    ArchiveMeta,
    AutomationState,
    BarbellState,
    BigNumberDTO,
    BreakthroughState,
    CollectionState,
    FishHallState,
    FishInstance,
    FishInventory,
    FishStateValidationContext,
    OwnedBarbell,
    PlayerState,
    ProductionState,
    RebirthState,
    StatisticsState,
    TorpedoState,
    TrashManState,
    TrashManUpgrade,
    TrashProcessingState,
    TrashStock,
    WalletState,
    _expect_array,
    _expect_bool,
    _expect_int,
    _expect_keys,
    _expect_object,
    _expect_string,
)


def player_state_from_dict(
    value: Mapping[str, Any],
    *,
    context: FishStateValidationContext | None = None,
    state_type: type[PlayerState] = PlayerState,
) -> PlayerState:
    cls = state_type
    payload = _expect_object(value, "$")
    _expect_keys(
        payload,
        {
            "meta",
            "production",
            "wallet",
            "torpedo",
            "barbell",
            "fishHall",
            "fish",
            "trashMan",
            "rebirth",
            "collection",
            "automation",
            "statistics",
        },
        "$",
    )

    meta = _expect_object(payload["meta"], "meta")
    _expect_keys(meta, {"createdAt", "revision"}, "meta")
    production = _expect_object(payload["production"], "production")
    _expect_keys(production, {"lastSettledAt"}, "production")
    wallet = _expect_object(payload["wallet"], "wallet")
    _expect_keys(wallet, {"money", "material", "strength"}, "wallet")
    torpedo = _expect_object(payload["torpedo"], "torpedo")
    _expect_keys(torpedo, {"selectedId", "ownedIds"}, "torpedo")
    barbell = _expect_object(payload["barbell"], "barbell")
    _expect_keys(barbell, {"equippedId", "owned"}, "barbell")
    fish_hall = _expect_object(payload["fishHall"], "fishHall")
    _expect_keys(fish_hall, {"upgradeLevel"}, "fishHall")
    fish = _expect_object(payload["fish"], "fish")
    _expect_keys(fish, {"nextInstanceId", "items"}, "fish")
    trash_man = _expect_object(payload["trashMan"], "trashMan")
    _expect_keys(
        trash_man,
        {
            "realmId",
            "highestRealmId",
            "upgrades",
            "trainingProgressSeconds",
            "breakthrough",
            "processing",
        },
        "trashMan",
    )
    breakthrough = _expect_object(
        trash_man["breakthrough"],
        "trashMan.breakthrough",
    )
    _expect_keys(
        breakthrough,
        {"active", "targetRealmId", "progressSeconds"},
        "trashMan.breakthrough",
    )
    processing = _expect_object(
        trash_man["processing"],
        "trashMan.processing",
    )
    _expect_keys(
        processing,
        {"activeTrashId", "activeProgressSeconds", "stocks"},
        "trashMan.processing",
    )
    rebirth = _expect_object(payload["rebirth"], "rebirth")
    _expect_keys(
        rebirth,
        {"strengthCompletedCount", "trashManCompletedCount"},
        "rebirth",
    )
    collection = _expect_object(payload["collection"], "collection")
    _expect_keys(
        collection,
        {"unlockedKeys", "viewedKeys", "claimedRewardIds"},
        "collection",
    )
    automation = _expect_object(payload["automation"], "automation")
    _expect_keys(
        automation,
        {"autoThrowUnlocked", "autoThrowEnabled"},
        "automation",
    )
    statistics = _expect_object(payload["statistics"], "statistics")
    _expect_keys(
        statistics,
        {"totalThrows", "totalFishCaught", "maxDistanceCm"},
        "statistics",
    )

    owned_barbells: list[OwnedBarbell] = []
    for index, entry_value in enumerate(
        _expect_array(barbell["owned"], "barbell.owned"),
        start=1,
    ):
        path = f"barbell.owned[{index}]"
        entry = _expect_object(entry_value, path)
        _expect_keys(entry, {"barbellId", "count"}, path)
        owned_barbells.append(
            OwnedBarbell(
                barbell_id=_expect_int(entry["barbellId"], f"{path}.barbellId"),
                count=_expect_int(entry["count"], f"{path}.count"),
            )
        )

    fish_items: list[FishInstance] = []
    for index, item_value in enumerate(
        _expect_array(fish["items"], "fish.items"),
        start=1,
    ):
        path = f"fish.items[{index}]"
        item = _expect_object(item_value, path)
        _expect_keys(
            item,
            {
                "instanceId",
                "fishId",
                "mutationId",
                "level",
                "weightGram",
                "hallSlot",
            },
            path,
        )
        fish_items.append(
            FishInstance(
                instance_id=_expect_int(item["instanceId"], f"{path}.instanceId"),
                fish_id=_expect_int(item["fishId"], f"{path}.fishId"),
                mutation_id=_expect_int(
                    item["mutationId"],
                    f"{path}.mutationId",
                ),
                level=_expect_int(item["level"], f"{path}.level"),
                weight_gram=_expect_int(
                    item["weightGram"],
                    f"{path}.weightGram",
                ),
                hall_slot=_expect_int(item["hallSlot"], f"{path}.hallSlot"),
            )
        )

    upgrades: list[TrashManUpgrade] = []
    for index, entry_value in enumerate(
        _expect_array(trash_man["upgrades"], "trashMan.upgrades"),
        start=1,
    ):
        path = f"trashMan.upgrades[{index}]"
        entry = _expect_object(entry_value, path)
        _expect_keys(entry, {"upgradeId", "level"}, path)
        upgrades.append(
            TrashManUpgrade(
                upgrade_id=_expect_int(entry["upgradeId"], f"{path}.upgradeId"),
                level=_expect_int(entry["level"], f"{path}.level"),
            )
        )

    stocks: list[TrashStock] = []
    for index, entry_value in enumerate(
        _expect_array(processing["stocks"], "trashMan.processing.stocks"),
        start=1,
    ):
        path = f"trashMan.processing.stocks[{index}]"
        entry = _expect_object(entry_value, path)
        _expect_keys(entry, {"trashId", "count"}, path)
        stocks.append(
            TrashStock(
                trash_id=_expect_int(entry["trashId"], f"{path}.trashId"),
                count=_expect_int(entry["count"], f"{path}.count"),
            )
        )

    state = cls(
        meta=ArchiveMeta(
            created_at=_expect_int(meta["createdAt"], "meta.createdAt"),
            revision=_expect_int(meta["revision"], "meta.revision"),
        ),
        production=ProductionState(
            last_settled_at=_expect_int(
                production["lastSettledAt"],
                "production.lastSettledAt",
            )
        ),
        wallet=WalletState(
            money=BigNumberDTO.from_dict(
                wallet["money"],
                path="wallet.money",
                allow_negative=False,
            ),
            material=BigNumberDTO.from_dict(
                wallet["material"],
                path="wallet.material",
                allow_negative=False,
            ),
            strength=BigNumberDTO.from_dict(
                wallet["strength"],
                path="wallet.strength",
                allow_negative=False,
            ),
        ),
        torpedo=TorpedoState(
            selected_id=_expect_int(
                torpedo["selectedId"],
                "torpedo.selectedId",
            ),
            owned_ids=[
                _expect_int(item, f"torpedo.ownedIds[{index}]")
                for index, item in enumerate(
                    _expect_array(torpedo["ownedIds"], "torpedo.ownedIds"),
                    start=1,
                )
            ],
        ),
        barbell=BarbellState(
            equipped_id=_expect_int(
                barbell["equippedId"],
                "barbell.equippedId",
            ),
            owned=owned_barbells,
        ),
        fish_hall=FishHallState(
            upgrade_level=_expect_int(
                fish_hall["upgradeLevel"],
                "fishHall.upgradeLevel",
            )
        ),
        fish=FishInventory(
            next_instance_id=_expect_int(
                fish["nextInstanceId"],
                "fish.nextInstanceId",
            ),
            items=fish_items,
        ),
        trash_man=TrashManState(
            realm_id=_expect_int(trash_man["realmId"], "trashMan.realmId"),
            highest_realm_id=_expect_int(
                trash_man["highestRealmId"],
                "trashMan.highestRealmId",
            ),
            upgrades=upgrades,
            training_progress_seconds=_expect_int(
                trash_man["trainingProgressSeconds"],
                "trashMan.trainingProgressSeconds",
            ),
            breakthrough=BreakthroughState(
                active=_expect_bool(
                    breakthrough["active"],
                    "trashMan.breakthrough.active",
                ),
                target_realm_id=_expect_int(
                    breakthrough["targetRealmId"],
                    "trashMan.breakthrough.targetRealmId",
                ),
                progress_seconds=_expect_int(
                    breakthrough["progressSeconds"],
                    "trashMan.breakthrough.progressSeconds",
                ),
            ),
            processing=TrashProcessingState(
                active_trash_id=_expect_int(
                    processing["activeTrashId"],
                    "trashMan.processing.activeTrashId",
                ),
                active_progress_seconds=_expect_int(
                    processing["activeProgressSeconds"],
                    "trashMan.processing.activeProgressSeconds",
                ),
                stocks=stocks,
            ),
        ),
        rebirth=RebirthState(
            strength_completed_count=_expect_int(
                rebirth["strengthCompletedCount"],
                "rebirth.strengthCompletedCount",
            ),
            trash_man_completed_count=_expect_int(
                rebirth["trashManCompletedCount"],
                "rebirth.trashManCompletedCount",
            ),
        ),
        collection=CollectionState(
            unlocked_keys=[
                _expect_string(item, f"collection.unlockedKeys[{index}]")
                for index, item in enumerate(
                    _expect_array(
                        collection["unlockedKeys"],
                        "collection.unlockedKeys",
                    ),
                    start=1,
                )
            ],
            viewed_keys=[
                _expect_string(item, f"collection.viewedKeys[{index}]")
                for index, item in enumerate(
                    _expect_array(
                        collection["viewedKeys"],
                        "collection.viewedKeys",
                    ),
                    start=1,
                )
            ],
            claimed_reward_ids=[
                _expect_int(item, f"collection.claimedRewardIds[{index}]")
                for index, item in enumerate(
                    _expect_array(
                        collection["claimedRewardIds"],
                        "collection.claimedRewardIds",
                    ),
                    start=1,
                )
            ],
        ),
        automation=AutomationState(
            auto_throw_unlocked=_expect_bool(
                automation["autoThrowUnlocked"],
                "automation.autoThrowUnlocked",
            ),
            auto_throw_enabled=_expect_bool(
                automation["autoThrowEnabled"],
                "automation.autoThrowEnabled",
            ),
        ),
        statistics=StatisticsState(
            total_throws=_expect_int(
                statistics["totalThrows"],
                "statistics.totalThrows",
            ),
            total_fish_caught=_expect_int(
                statistics["totalFishCaught"],
                "statistics.totalFishCaught",
            ),
            max_distance_cm=_expect_int(
                statistics["maxDistanceCm"],
                "statistics.maxDistanceCm",
            ),
        ),
    )
    state.validate(context)
    return state
