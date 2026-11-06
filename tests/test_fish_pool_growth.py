"""New-pool stimuli, source boundaries and formal continuation."""
from dataclasses import asdict
from decimal import Decimal
import pytest

from igess.fish_source_pools import PoolMilestones
from test_fish_collection_reporting import report
from test_source_fish_reporting import _dto


def state(strength, pool=1, time=0):
    return {"wallet": {"strength": _dto(strength)}, "luck": {"fishPoolId": pool}, "time": time}


def test_pool_boundaries_leaps_rebirth_and_checkpoint():
    pools = [{"pool_id": i, "previous_upper_bound": bound, "display_name": f"池{i}"}
             for i, bound in ((2, "50"), (3, "2000"), (4, "30000"))]
    observer = PoolMilestones(pools, state("2"))
    events = []
    def observe(strength, time, pool=1):
        observer.observe(state(strength, pool, time), time, "smoke", "default", events)
    observe("50", 1)
    assert not events  # Inclusive upper bound belongs to the old pool.
    observe("2001", 2, 3)
    assert [e.item_id for e in events] == ["2", "3"]
    observe("0", 3)
    saved = observer.save()
    observer = PoolMilestones(pools, state("0"), saved)
    observe("30000", 4, 3)
    assert len(events) == 2
    observe("30001", 5, 4)
    assert [e.time_seconds for e in events] == [2, 2, 5]
    assert observer.scope["initial_seen_pool_ids"] == [2, 3]
    baseline = PoolMilestones(pools, state("2001", 3))
    assert baseline.scope["initial_seen_pool_ids"] == [2, 3]


def test_large_strength_threshold_is_exact_and_report_counts_one_point(tmp_path):
    bound = "1" + "0" * 119
    above = "1" + "0" * 118 + "1"
    pools = [{"pool_id": 2, "previous_upper_bound": bound, "display_name": "冻结池名"}]
    observer = PoolMilestones(pools, state("2"))
    events = []
    for time, strength in enumerate((bound, above), 1):
        observer.observe(state(strength, time, time), time, "smoke", "default", events)
    assert len(events) == 1
    data = report(tmp_path, [asdict(events[0]), asdict(events[0])], {"pool_growth": observer.scope})
    growth = data["fish_progression"]["persistent"]["profiles"]["default"]
    assert len(growth["rows"]) == 1
    row = growth["rows"][0]
    assert row["progression_category"] == "fish_pool" and row["pool_id"] == 2
    assert row["display_name"] == "冻结池名" and row["strength"] == above
    assert row["active_time_seconds"] == 2
    assert growth["summary"]["total_progression_count"]["exact_value"] == "1"
    assert growth["days"][0]["event_count"]["exact_value"] == "1"
    assert growth["weeks"][0]["event_count"]["exact_value"] == "1"
    assert growth["pool_coverage"]["recorded"]
    assert "fish_pool_entered" not in data["fish_progression"]["actions"]["default"]["accepted_commands"]


def test_legacy_report_does_not_invent_pool_first_times(tmp_path):
    data = report(tmp_path, [])
    growth = data["fish_progression"]["persistent"]["profiles"]["default"]
    assert not growth["pool_coverage"]["recorded"]
    assert "重新模拟" in growth["pool_coverage"]["note"]
    assert not growth["rows"]


@pytest.mark.parametrize("strength,expected", [("50", 1), ("51", 2), ("2000", 2), ("2001", 3)])
def test_source_query_defines_pool_boundary(strength, expected):
    from igess.fish_source_runtime import FishSourceRuntime
    from test_fish_source_joint import SOURCE, archive
    initial = archive()
    coefficient = strength.rstrip("0")
    initial["wallet"]["strength"] = {"sign": 1, "coeff": coefficient, "exp": len(strength) - len(coefficient)}
    with FishSourceRuntime(SOURCE, SOURCE / "igess_export/json") as runtime:
        current = runtime.create(start_at=0, random_seed=1, initial_state=initial)
        assert current["luck"]["fishPoolId"] == expected
        observer = PoolMilestones(runtime.pool_growth_thresholds(), current)
        assert observer.scope["initial_seen_pool_ids"] == list(range(2, expected + 1))


def test_formal_pool_growth_and_split_run_match(tmp_path, monkeypatch):
    from test_fish_source_joint import archive, initial, project, run
    initial(monkeypatch, archive("s.wallet.strength={sign=1,coeff='49',exp=0}"))
    target = project(tmp_path, duration=120, weights={"exercise_barbell": "1"})
    _, full, full_report = run(target)
    segment, first, first_report = run(target, until_seconds=60)
    _, second, second_report = run(target, checkpoint_input=segment / "final_checkpoint.json")
    def facts(data):
        return [r for r in data["fish_progression"]["persistent"]["profiles"]["default"]["rows"]
                if r["progression_category"] == "fish_pool"]
    rows = facts(full_report)
    assert rows and rows[0]["pool_id"] == 2
    assert rows[0]["display_name"] == "洗脚大盆"
    assert Decimal(rows[0]["strength"]) > 50
    identities = lambda rs: [(r["event_identity"], r["active_time_seconds"]) for r in rs]
    assert identities(rows) == identities(facts(first_report) + facts(second_report))
    assert full("timeline.json")[-1] == second("timeline.json")[-1]
    assert full("final_checkpoint.json")["behavior_state"] == second("final_checkpoint.json")["behavior_state"]
    scope = full("run_manifest.json")["source_profiles"]["default"]["pool_growth"]
    assert full("source_behavior.json")["profiles"]["default"]["pool_growth"] == scope
