"""Player growth intent and tide limits from source quotes and current wallet."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, localcontext
from typing import Any

from .engines import EngineAdapterError
from .fish_source_numbers import source_decimal

GROWTH_TIDE_POLICY = {
    "policy": "growth_first_wallet_fraction_daily_income_near_term_reserve_v2",
    "max_material_fraction": "0.25",
    "max_daily_income_fraction": "0.15",
    "daily_income": "observed_online_material_including_sales_and_codex_excluding_offline",
    "daily_window": "simulation_wall_day_86400_seconds_no_carry",
    "daily_spending": "source_paid_reload_receipts_plus_full_round_quote",
    "horizon_online_seconds": 1800,
    "income_window_online_seconds": 1800,
    "income": "observed_online_material_excluding_codex_and_offline",
    "reservation": "one_next_source_quoted_target_existing_weights_and_turn",
    "budget_basis": "current_material_wallet_before_admission",
    "cost_basis": "source_round_damage_hp_ammunition_quote",
}

REBIRTH_POLICY = "source_eligible_trash_then_strength_first_v1"

FISH_UPGRADE_POLICY = {
    "policy": "top_two_potential_spend_all_batch_v1",
    "targets": "source_selected_deployed_ordinary_top_two_in_potential_order",
    "selection": "strongest_affordable_then_second",
    "batch_seconds": 3,
    "barbell_horizon_seconds": 1800,
    "barbell_budget": "wallet_plus_unclaimed_plus_current_hall_cps_times_horizon",
    "reservation_check": "before_batch_only",
    "settlement": "source_single_level_commands_at_batch_start",
}


def fish_upgrade_quote(state, actions, allowed):
    """Use the source potential ranking, including max-level fish in the top two."""
    ordinary = {row["instanceId"] for row in actions["hallCandidates"] if not row["isBeast"]}
    ranked = [key for key in actions["bestPotentialLayout"]["selectedInstanceIds"] if key in ordinary][:2]
    deployed = {row["instanceId"] for row in state["inventory"]["items"] if row["hallSlot"] > 0}
    quotes = {row["instanceId"]: row for row in actions["fishUpgrades"]}
    money = source_decimal(state["wallet"]["money"])
    for key in ranked:
        quote = quotes.get(key)
        if (key in deployed and quote is not None and allowed("upgrade_fish", str(key))
                and money >= source_decimal(quote["cost"])):
            return quote
    return None


def reserve_money_for_barbell(state, actions, weights, allowed):
    """Reserve for the next numeric catalog entry using current source production."""
    weight = weights.get("synthesize_barbell")
    if weight is None or Decimal(weight.to_decimal_string()) <= 0:
        return False
    owned = {row["barbellId"] for row in state["barbell"]["owned"]}
    target = min((row for row in actions["barbells"] if row["barbellId"] not in owned),
                 key=lambda row: row["barbellId"], default=None)
    if target is None or not allowed("synthesize_barbell", str(target["barbellId"])):
        return False
    price = source_decimal(target["cost"])
    money = source_decimal(state["wallet"]["money"])
    unclaimed = source_decimal(state["unclaimedMoney"])
    cps = source_decimal(state["hall"]["currentRatePerSecond"])
    values = [price, money, unclaimed, cps]
    with localcontext() as ctx:
        ctx.prec = max(80, max(v.adjusted() for v in values) - min(v.as_tuple().exponent for v in values) + 8)
        return price <= money + unclaimed + cps * FISH_UPGRADE_POLICY["barbell_horizon_seconds"]


def immediate_rebirth(state, weights, allowed):
    """At an idle decision boundary, execute a source-legal rebirth first."""
    for behavior, section, op in (
        ("trash_man_rebirth", "trashMan", "rebirth_trash_man"),
        ("strength_rebirth", "strength", "rebirth_strength"),
    ):
        weight = weights.get(behavior)
        if (weight is not None and Decimal(weight.to_decimal_string()) > 0
                and state.get("rebirth", {}).get(section, {}).get("eligible", False)
                and allowed(op, "")):
            return behavior, "", {"op": op}
    return None



@dataclass(frozen=True)
class GrowthOption:
    behavior: str
    target: str
    payload: dict[str, Any]
    quote: dict[str, Any] | None = None

    def affordable(self, wallet):
        return self.quote is None or source_decimal(wallet[self.quote["resource"]]) >= source_decimal(self.quote["cost"])


def target_order(behavior: str, target: str):
    """Compare catalog IDs numerically; keep action/checkpoint identities strings."""
    if behavior in {"purchase_torpedo", "synthesize_barbell"}:
        return (0, int(target))
    return (1, target)


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
        previous = quote.get("previousTorpedoId")
        if type(previous) is not int or previous < 0:
            raise EngineAdapterError("fish_source_torpedo_prerequisite_missing", "Source quotes must provide previousTorpedoId")
        if quote["torpedoId"] not in owned and (previous == 0 or previous in owned):
            add("purchase_torpedo", "purchase_torpedo", str(quote["torpedoId"]), quote, torpedoId=quote["torpedoId"])
    owned = {row["barbellId"] for row in state["barbell"]["owned"]}
    for quote in actions["barbells"]:
        if quote["barbellId"] not in owned:
            add("synthesize_barbell", "synthesize_barbell", str(quote["barbellId"]), quote, barbellId=quote["barbellId"])
    return options


class GrowthTideBudget:
    def __init__(self, saved=None):
        self.samples = [list(row) for row in (saved or {}).get("samples", [])]
        self.daily = dict((saved or {}).get("daily", {}))

    def save(self):
        return {"samples": [list(row) for row in self.samples], "daily": dict(self.daily)}

    def observe_daily(self, wall_seconds, totals):
        """Track source cumulative counters; yesterday's income never buys today's budget.

        Called at initialization and after source observations. Advances stop at
        midnight, so interval income is settled before the next day's baseline.
        """
        day = int(wall_seconds) // 86400
        income, spent = totals["material"], totals["tide_reload_material"]
        if self.daily.get("day_index") != day:
            self.daily = {"day_index": day, "income_start": str(income), "spending_start": str(spent)}
        values = [income, spent, Decimal(self.daily["income_start"]), Decimal(self.daily["spending_start"])]
        with localcontext() as ctx:
            ctx.prec = max(80, max(v.adjusted() for v in values) - min(v.as_tuple().exponent for v in values) + 8)
            self.daily["income"] = str(max(Decimal(0), income - values[2]))
            self.daily["spent"] = str(max(Decimal(0), spent - values[3]))

    def skip_daily(self, tide_quote):
        if not tide_quote["available"]:
            return {"reason": tide_quote["reason"]}
        if not self.daily:
            raise EngineAdapterError("fish_source_daily_tide_budget_missing", "Daily income baseline is required")
        income, spent = Decimal(self.daily["income"]), Decimal(self.daily["spent"])
        cost = source_decimal(tide_quote["materialCost"])
        fraction = Decimal(GROWTH_TIDE_POLICY["max_daily_income_fraction"])
        values = [income, spent, cost, fraction]
        with localcontext() as ctx:
            ctx.prec = max(80, max(v.adjusted() for v in values) - min(v.as_tuple().exponent for v in values) + 8)
            limit = income * fraction
            if spent + cost > limit:
                return {"reason": "tide_daily_income_budget_exceeded",
                        "dayIndex": self.daily["day_index"], "dailyOnlineMaterialIncome": str(income),
                        "dailyTideMaterialSpent": str(spent), "tideMaterialCost": str(cost),
                        "dailyMaterialBudget": str(limit), "maxDailyIncomeFraction": str(fraction)}
        return None

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

    def skip(self, state, options, weights, allowed, turn, remaining_online, *, tide_quote=None):
        rebirth = immediate_rebirth(state, weights, allowed)
        if rebirth is not None:
            return {"reason": "growth_action_ready", "growthBehavior": rebirth[0], "growthTarget": rebirth[1]}
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

        wallet = source_decimal(state["wallet"]["material"])
        gun = next((row for row in state["guns"]["owned"] if row["id"] == state["guns"]["combat"]["equippedGunId"]), None)
        if gun is None:
            return None  # Let the source report its normal admission rejection.
        if tide_quote is None:
            raise EngineAdapterError("fish_source_tide_quote_missing", "A source quote for this round is required")
        if not tide_quote["available"]:
            return {"reason": tide_quote["reason"]}
        cost = source_decimal(tide_quote["materialCost"])
        fraction = Decimal(GROWTH_TIDE_POLICY["max_material_fraction"])
        with localcontext() as ctx:
            values = [wallet, cost, fraction]
            ctx.prec = max(80, sum(len(v.as_tuple().digits) for v in values) + 8)
            limit = wallet * fraction
            if cost > limit:
                return {"reason": "tide_material_budget_exceeded",
                        "materialBalance": str(wallet), "tideMaterialCost": str(cost),
                        "materialBudget": str(limit), "maxMaterialFraction": str(fraction)}

        # Only the next quoted target in each material line can reserve money.
        next_by_behavior = {}
        for weight, option in sorted(enabled, key=lambda row: (row[1].behavior, target_order(row[1].behavior, row[1].target))):
            if option.quote and option.quote["resource"] == "material":
                next_by_behavior.setdefault(option.behavior, (weight, option))
        if not next_by_behavior or len(self.samples) < 2:
            return None
        elapsed = self.samples[-1][0] - self.samples[0][0]
        if elapsed <= 0:
            return None
        previous, current = Decimal(self.samples[0][1]), Decimal(self.samples[-1][1])
        values = [wallet, cost, previous, current] + [source_decimal(o.quote["cost"]) for _, o in next_by_behavior.values()]
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
            if wallet < reserve + cost:
                return {"reason": "growth_material_reserved", "growthBehavior": option.behavior,
                        "growthTarget": option.target, "reservedMaterial": str(reserve),
                        "observedMaterial": str(gained), "observedOnlineSeconds": elapsed,
                        "reserveHorizonOnlineSeconds": horizon}
        return None

    @staticmethod
    def _select(candidates, turn):
        maximum = max(weight for weight, _ in candidates)
        tied = sorted((o for weight, o in candidates if weight == maximum), key=lambda o: (o.behavior, target_order(o.behavior, o.target)))
        behaviors = list(dict.fromkeys(o.behavior for o in tied))
        chosen = behaviors[turn % len(behaviors)]
        return next(o for o in tied if o.behavior == chosen)
