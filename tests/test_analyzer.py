from igess.analyzer import Analyzer
from igess.builder import ModelBuilder
from igess.loader import ConfigLoader
from igess.schema import SimulationResult, TimelineRow


CONFIG = "examples/shelldiver_v0/economy.yaml"
TABLES = "examples/shelldiver_v0/luban_exports"


def test_payback_report_uses_profile_source_efficiency():
    model = ModelBuilder.build(ConfigLoader.load(CONFIG, TABLES))
    result = SimulationResult(
        scenario_id="synthetic",
        events=[],
        timeline=[
            TimelineRow(
                scenario_id="synthetic",
                profile_id="casual",
                time_seconds=10,
                resources={"fish": "10000", "prestige_point": "0"},
                generators_owned={"boat": 0, "fisherman": 1, "net": 0},
                upgrades_purchased=[],
                total_cps="1",
            ),
            TimelineRow(
                scenario_id="synthetic",
                profile_id="optimizer",
                time_seconds=10,
                resources={"fish": "10000", "prestige_point": "0"},
                generators_owned={"boat": 0, "fisherman": 1, "net": 0},
                upgrades_purchased=[],
                total_cps="1",
            ),
        ],
    )

    rows = {
        (row["profile_id"], row["item_id"]): row
        for row in Analyzer.payback_report(result, model)
        if row["kind"] == "generator" and row["item_id"] == "fisherman"
    }

    assert rows[("casual", "fisherman")]["delta_cps"] == "0.9"
    assert rows[("optimizer", "fisherman")]["delta_cps"] == "1.05"
