"""Player growth intent and tide budgets from source quotes and observed income."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, localcontext
from typing import Any

from .fish_source_numbers import source_decimal

GROWTH_TIDE_POLICY = {
    "policy": "growth_first_near_term_reserve_v1",
    "horizon_online_seconds": 1800,
    "income_window_online_seconds": 1800,
    "income": "observed_online_material_excluding_codex_and_offline",
    "reservation": "one_next_source_quoted_target_existing_weights_and_turn",
}


@dataclass(frozen=True)
class GrowthOption:
    behavior: str
    target: str
    payload: dict[str, Any]
    quote: dict[str, Any] | None = None

    def affordable(self, wallet):
        return self.quote is None or source_decimal(wallet[self.quote["resource"]]) >= source_decimal(self.quote["cost"])


def growth_options(state, actions):
    """Immediate source-legal growth steps, before wallet/strategy filtering."""
    options = []
    def add(behavior, op, target="", quote=None, **args):
        options.append(GrowthOption(behavior, target, {"op": op, **args}, quote))

    if state["rebirth"]["strength"]["eligible"]:
        add("strength_rebirth", "rebirth_strength")
    beast = state["trashMan"]
    if beast["unlocked"] and state["rebirth"]["trashMan"]["eligible"]:
        add("trash_man_rebirth", "rebirth_trash_man")
    realm = beast["currentRealm"]
    if (beast["unlocked"] and not beast["breakthrough"]["active"]
            and not realm["isMax"] and beast["realmId"] == beast["highestRealmId"]):
        add("fund_trash_man_breakthrough", "start_breakthrough", quote={
            "resource": "material", "cost": realm["breakthroughMaterialCost"],
        })
    if actions.get("hallUpgrade"):
        add("upgrade_fish_hall", "upgrade_hall", quote=actions["hallUpgrade"])
    owned = set(state["torpedo"]["ownedIds"])
    for quote in actions["torpedoes"]:
        if quote["torpedoId"] not in owned:
            add("purchase_torpedo", "purchase_torpedo", str(quote["torpedoId"]), quote, torpedoId=quote["torpedoId"])
    owned = {row["barbellId"] for row in state["barbell"]["owned"]}
    for quote in actions["barbells"]:
        if quote["barbellId"] not in owned:
            add("synthesize_barbell", "synthesize_barbell", str(quote["barbellId"]), quote, barbellId=quote["barbellId"])
    return options


class GrowthTideBudget:
    def __init__(self, saved=None):
        self.samples = [list(row) for row in (saved or {}).get("samples", [])]

    def save(self):
        return {"samples": [list(row) for row in self.samples]}

    def observe(self, online_seconds, totals):
        # Called at online openings, independent of report sampling and admission.
        with localcontext() as ctx:
            values = [totals["material"], totals["codex_material"]]
            ctx.prec = max(80, max(v.adjusted() for v in values) - min(v.as_tuple().exponent for v in values) + 4)
            earned = totals["material"] - totals["codex_material"]
        row = [online_seconds, str(earned)]
        if self.samples and self.samples[-1][0] == online_seconds:
            self.samples[-1] = row
        else:
            self.samples.append(row)
        cutoff = online_seconds - GROWTH_TIDE_POLICY["income_window_online_seconds"]
        while len(self.samples) > 1 and self.samples[1][0] <= cutoff:
            self.samples.pop(0)

    def skip(self, state, options, weights, allowed, turn, remaining_online):
        enabled = []
        for option in options:
            configured = weights.get(option.behavior)
            if configured is None:
                continue
            weight = Decimal(configured.to_decimal_string())
            if weight > 0 and allowed(option.payload["op"], option.target):
                enabled.append((weight, option))
        ready = [(weight, option) for weight, option in enabled if option.affordable(state["wallet"])]
        if ready:
            option = self._select(ready, turn)
            return {"reason": "growth_action_ready", "growthBehavior": option.behavior, "growthTarget": option.target}

        # Only the next quoted target in each material line can reserve money.
        next_by_behavior = {}
        for weight, option in enabled:
            if option.quote and option.quote["resource"] == "material":
                next_by_behavior.setdefault(option.behavior, (weight, option))
        if not next_by_behavior or len(self.samples) < 2:
            return None
        elapsed = self.samples[-1][0] - self.samples[0][0]
        if elapsed <= 0:
            return None
        wallet = source_decimal(state["wallet"]["material"])
        gun = next((row for row in state["guns"]["owned"] if row["id"] == state["guns"]["combat"]["equippedGunId"]), None)
        if gun is None:
            return None  # Let the source report its normal admission rejection.
        reload_cost = source_decimal(gun["reloadResourceCost"])
        previous, current = Decimal(self.samples[0][1]), Decimal(self.samples[-1][1])
        values = [wallet, reload_cost, previous, current] + [source_decimal(o.quote["cost"]) for _, o in next_by_behavior.values()]
        with localcontext() as ctx:
            ctx.prec = max(80, max(v.adjusted() for v in values) - min(v.as_tuple().exponent for v in values) + 16)
            gained = max(Decimal(0), current - previous)
            horizon = min(GROWTH_TIDE_POLICY["horizon_online_seconds"], remaining_online)
            nearby = [(weight, option) for weight, option in next_by_behavior.values()
                      if (source_decimal(option.quote["cost"]) - wallet) * elapsed <= gained * horizon]
            if not nearby:
                return None
            option = self._select(nearby, turn)
            reserve = source_decimal(option.quote["cost"])
            if wallet < reserve + reload_cost * state["tides"]["policy"]["reloads"]:
                return {"reason": "growth_material_reserved", "growthBehavior": option.behavior,
                        "growthTarget": option.target, "reservedMaterial": str(reserve),
                        "observedMaterial": str(gained), "observedOnlineSeconds": elapsed,
                        "reserveHorizonOnlineSeconds": horizon}
        return None

    @staticmethod
    def _select(candidates, turn):
        maximum = max(weight for weight, _ in candidates)
        tied = sorted((o for weight, o in candidates if weight == maximum), key=lambda o: (o.behavior, o.target))
        behaviors = list(dict.fromkeys(o.behavior for o in tied))
        chosen = behaviors[turn % len(behaviors)]
        return next(o for o in tied if o.behavior == chosen)
