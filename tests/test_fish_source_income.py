from decimal import Decimal

from igess.fish_source_income import SourceIncome


def _dto(value: str) -> dict:
    parts = Decimal(value).as_tuple()
    return {"sign": -1 if parts.sign else 1, "coeff": ''.join(map(str, parts.digits)), "exp": parts.exponent}


def _state(money="0", material="0", unclaimed="0", *, online=True):
    return {"online": online, "wallet": {"money": _dto(money), "material": _dto(material)},
            "unclaimedMoney": _dto(unclaimed)}


def test_source_income_counts_production_and_sale_without_counting_transfers_or_spending():
    income = SourceIncome()
    before = _state()
    after = _state(material="40", unclaimed="100")
    income.observe(before, after)
    collected = _state(money="100", material="40")
    income.observe(after, collected, op="collect_slot", receipt={"moneyCollected": _dto("100")})
    spent = _state(money="75", material="30")
    income.observe(collected, spent, op="upgrade_fish", receipt={
        "moneySpent": _dto("25"), "materialSpent": _dto("10"),
    })
    sold = _state(money="75", material="37")
    income.observe(spent, sold, op="sell_fish", receipt={"materialAdded": _dto("7")})
    assert income.save() == {"money": "100", "material": "47", "fish_sale_material": "7", "codex_money": "0", "codex_material": "0"}
    resumed = SourceIncome(income.save())
    resumed.observe(sold, _state(money="75", material="40", unclaimed="5"))
    assert resumed.save() == {"money": "105", "material": "50", "fish_sale_material": "7", "codex_money": "0", "codex_material": "0"}


def test_source_income_excludes_offline_claims_and_lost_pending_money():
    income = SourceIncome()
    income.observe(_state(online=False), _state("500", "600", online=False))
    income.observe(_state(), _state("500", "600"), op="claim_offline_reward")
    income.observe(_state(unclaimed="10"), _state(), op="deploy_fish")
    assert all(value == "0" for value in income.save().values())


def test_source_income_retains_small_gains_next_to_hundred_digit_balances():
    income = SourceIncome()
    huge = "1" + "0" * 100
    income.observe(_state(money=huge, material=huge),
                   _state(money=huge + ".25", material=huge + ".125"))
    assert Decimal(income.save()["money"]) == Decimal(".25")
    assert Decimal(income.save()["material"]) == Decimal(".125")
