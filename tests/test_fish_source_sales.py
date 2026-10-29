"""Keep thirty owned fish and sell the lowest level-one CPS backpack fish."""
import json
from decimal import Decimal

import pytest
import yaml

from igess.fish_source_engine import _unpack_session
from igess.fish_source_numbers import source_decimal
from igess.fish_source_runtime import FishSourceRejection, FishSourceRuntime
from test_fish_source_joint import SOURCE, archive, initial, project, run


pytestmark = pytest.mark.skipif(
    not (SOURCE / "simulation/cli.lua").is_file(), reason="Fish source checkout unavailable",
)


def sales_project(tmp_path, monkeypatch, *, count=32, duration=30, body="", weights=None):
    state = archive(f"""
for i=1,{count} do
    s.fish.items[i]={{instanceId=i,fishId=102,mutationId=1,weightGram=1000,level=1,hallSlot=i<=5 and i or 0}}
end
s.fish.nextInstanceId={count + 1}
{body}
""")
    initial(monkeypatch, state)
    target = project(tmp_path, duration=duration, weights=weights or {"sell_fish": "1"})
    path = target / "economy.yaml"
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    config["engine"]["source_runtime"].update(idle_seconds=1, room_origin_seconds=1000)
    config["scenarios"]["smoke"]["record_interval_seconds"] = 1
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return target


def sales(events):
    return [json.loads(e["details"]["receipt"]) for e in events if e["kind"] == "sell_fish"]


@pytest.mark.parametrize("count,expected", [(29, 0), (30, 0), (31, 1), (32, 2)])
def test_sales_count_hall_fish_and_stop_at_thirty(tmp_path, monkeypatch, count, expected):
    target = sales_project(tmp_path, monkeypatch, count=count)
    _, read, report = run(target)
    sold = sales(read("events.json"))
    assert [s["instanceId"] for s in sold] == list(range(6, 6 + expected))
    final = read("timeline.json")[-1]
    assert int(final["resources"]["fish_inventory_count"]) == min(count, 30)
    assert final["generators_owned"]["deployed_fish"] == 5
    earned = sum((source_decimal(s["materialAdded"]) for s in sold), Decimal(0))
    for key in ("material", "online_fish_sale_material_cumulative", "online_resource_acquired_cumulative"):
        assert Decimal(final["resources"][key]) == earned
    assert Decimal(report["fish_progression"]["investment"]["profiles"]["default"]["sale_material"]["exact_value"]) == earned
    metadata = read("run_manifest.json")["source_runtime"]
    assert metadata["fish_sell_policy"] == "over_30_lowest_level_one_cps_backpack_v1"
    assert metadata["fish_keep_count"] == 30


def test_sales_rank_level_one_cps_with_mutation_and_ignore_current_level(tmp_path, monkeypatch):
    target = sales_project(tmp_path, monkeypatch, body="""
s.fish.items[1].fishId=101
s.fish.items[6].fishId=101
s.fish.items[6].mutationId=3
s.fish.items[7].fishId=101
s.fish.items[7].level=50
""")
    _, read, _ = run(target)
    # Normal 101 has CPS 2 despite its upgrades; jade 101 beats normal 102.
    # Hall fish 1 has the lowest quality too, but remains deployed.
    assert [s["instanceId"] for s in sales(read("events.json"))] == [7, 8]


def test_sale_selection_uses_exact_source_prices_across_all_inventory_pages(tmp_path, monkeypatch):
    target = sales_project(tmp_path, monkeypatch, count=51, duration=3, body="""
s.fish.items[51].fishId=101
""")
    path = target / "selected/tbfish.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    for row in rows:
        if row["id"] in (101, 102):
            row["baseMoneyPerSecond"] = {
                "sign": 1, "digits": "1" + "0" * 100 + str(row["id"] - 100), "scale": 0,
            }
    path.write_text(json.dumps(rows), encoding="utf-8")
    _, read, _ = run(target)
    assert [s["instanceId"] for s in sales(read("events.json"))] == [51]


@pytest.mark.parametrize("cutoff", [1, 3, 14])
def test_sale_resume_preserves_income_and_does_not_sell_twice(tmp_path, monkeypatch, cutoff):
    target = sales_project(tmp_path, monkeypatch)
    _, expected, _ = run(target)
    first, before, _ = run(target, until_seconds=cutoff)
    _, after, _ = run(target, checkpoint_input=first / "final_checkpoint.json")
    assert before("events.json") + after("events.json") == expected("events.json")
    actual = after("final_checkpoint.json")
    baseline = expected("final_checkpoint.json")
    assert actual["behavior_state"] == baseline["behavior_state"]
    assert _unpack_session(actual["engine_state"]) == _unpack_session(baseline["engine_state"])
    assert after("timeline.json")[-1] == expected("timeline.json")[-1]


def test_rejected_sale_uses_next_eligible_fish(tmp_path, monkeypatch):
    target = sales_project(tmp_path, monkeypatch, count=31)
    request = FishSourceRuntime.request

    def reject(self, payload, **kwargs):
        if payload["op"] == "sell_fish" and payload["instanceId"] == 6:
            raise FishSourceRejection("fixture_sale_rejected")
        return request(self, payload, **kwargs)

    monkeypatch.setattr(FishSourceRuntime, "request", reject)
    _, read, _ = run(target)
    assert [s["instanceId"] for s in sales(read("events.json"))] == [7]
    assert len([e for e in read("events.json") if e["kind"] == "source_rejected"]) == 1


def test_sale_weight_zero_keeps_behavior_disabled(tmp_path, monkeypatch):
    target = sales_project(tmp_path, monkeypatch, weights={"sell_fish": "0"})
    _, read, _ = run(target)
    assert not sales(read("events.json"))


def test_source_sale_quotes_are_read_only_and_refresh_after_deployment_and_sale():
    state = archive("""
s.fish.items={
    {instanceId=1,fishId=101,mutationId=1,weightGram=1000,level=50,hallSlot=0},
    {instanceId=2,fishId=101,mutationId=2,weightGram=1000,level=1,hallSlot=0},
    {instanceId=3,fishId=2001,mutationId=1,weightGram=1000,level=1,hallSlot=0}
}
s.fish.nextInstanceId=4
""")
    with FishSourceRuntime(SOURCE, SOURCE / "igess_export/json") as host:
        host.create(start_at=0, initial_state=state, in_fishing_area=True, random_seed=42)
        before = host.request({"op": "query"})
        quotes = host.request({"op": "query_actions"})["fishSales"]
        assert [q["instanceId"] for q in quotes] == [1, 2]  # Beast is not sellable.
        assert source_decimal(quotes[0]["levelOneCps"]) < source_decimal(quotes[1]["levelOneCps"])
        assert host.request({"op": "query"}) == before
        host.request({"op": "deploy_fish", "instanceId": 1, "slot": 1, "requestId": "deploy"})
        assert [q["instanceId"] for q in host.request({"op": "query_actions"})["fishSales"]] == [2]
        host.request({"op": "withdraw_fish", "instanceId": 1, "requestId": "withdraw"})
        assert host.request({"op": "query_actions"})["fishSales"] == quotes
        receipt = host.request({"op": "sell_fish", "instanceId": 1, "requestId": "sell"})
        assert receipt["materialAdded"] == quotes[0]["materialAdded"]
        assert [q["instanceId"] for q in host.request({"op": "query_actions"})["fishSales"]] == [2]
