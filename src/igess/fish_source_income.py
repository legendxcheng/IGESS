"""Account for observed source income without evaluating game production rules."""

from __future__ import annotations

from decimal import Decimal, localcontext
from typing import Any


def _number(dto: dict[str, Any]) -> Decimal:
    if dto["sign"] == 0:
        return Decimal(0)
    parts = Decimal(str(dto["coeff"])).as_tuple()
    return Decimal((int(dto["sign"] < 0), parts.digits, parts.exponent + int(dto["exp"])))


def _sum(*values: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = max(
            80,
            max(value.adjusted() for value in values)
            - min(int(value.as_tuple().exponent) for value in values) + 4,
        )
        return sum(values, Decimal(0))


class SourceIncome:
    def __init__(self, saved: dict[str, str] | None = None) -> None:
        self.totals = {
            key: Decimal((saved or {}).get(key, "0"))
            for key in ("money", "material", "fish_sale_material", "codex_money", "codex_material", "tide_reload_material")
        }

    def observe(
        self, before: dict[str, Any], after: dict[str, Any],
        *, op: str = "advance", receipt: dict[str, Any] | None = None,
    ) -> None:
        if not before["online"] or op == "claim_offline_reward":
            return
        receipt = receipt or {}
        for currency in ("money", "material"):
            values = [
                _number(after["wallet"][currency]),
                _number(before["wallet"][currency]).copy_negate(),
            ]
            # Collecting slot money transfers it to the wallet; it is not new income.
            if currency == "money":
                values.extend([
                    _number(after["unclaimedMoney"]),
                    _number(before["unclaimedMoney"]).copy_negate(),
                ])
            if currency + "Spent" in receipt:
                values.append(_number(receipt[currency + "Spent"]))
            if currency + "Refunded" in receipt:
                values.append(_number(receipt[currency + "Refunded"]).copy_negate())
            gained = max(Decimal(0), _sum(*values))
            self.totals[currency] = _sum(self.totals[currency], gained)
        if (op == "claim_fish_reward" and receipt.get("committed")
                and receipt["rewardId"] not in before.get("codex", {}).get("claimedRewardIds", [])):
            for grant in receipt["grants"]:
                key = "codex_" + grant["type"]
                self.totals[key] = _sum(self.totals[key], _number(grant["amount"]))
        if op == "start_tide" and "materialSpent" in receipt:
            refund = _number(receipt["materialRefunded"]) if "materialRefunded" in receipt else Decimal(0)
            self.totals["tide_reload_material"] = _sum(
                self.totals["tide_reload_material"], _number(receipt["materialSpent"]), refund.copy_negate(),
            )
        if op == "sell_fish" and "materialAdded" in receipt:
            self.totals["fish_sale_material"] = _sum(
                self.totals["fish_sale_material"], _number(receipt["materialAdded"]),
            )

    def save(self) -> dict[str, str]:
        return {key: str(value) for key, value in self.totals.items()}
