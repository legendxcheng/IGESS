from igess.analyzer import Analyzer
from igess.builder import ModelBuilder
from igess.loader import ConfigLoader
from igess.numbers import SimNumber
from igess.schema import SimulationResult, TimelineRow


CONFIG = "examples/shelldiver_v0/economy.yaml"
TABLES = "examples/shelldiver_v0/luban_exports"


def _targeted_human_number_analysis():
    model = ModelBuilder.build(ConfigLoader.load(CONFIG, TABLES))
    model.generators["fisherman"].base_cost = "739.864019013290554"
    model.generators["fisherman"].cost_growth = "1"
    model.generators["fisherman"].base_output = "1"
    model.generators["boat"].base_output = "0"
    model.player_profiles["casual"].source_efficiency["generator"] = SimNumber.one()
    resources = {
        "tiny": "0.0000123456789",
        "huge": "1234567890123456789",
    }
    result = SimulationResult(
        scenario_id="human-number-display",
        events=[],
        timeline=[
            TimelineRow(
                scenario_id="human-number-display",
                profile_id="casual",
                time_seconds=1_234_567,
                resources=resources,
                generators_owned={"boat": 0, "fisherman": 5, "net": 0},
                upgrades_purchased=[],
                total_cps="1",
            )
        ],
    )
    return model, result, resources


def test_markdown_compacts_human_facing_analysis_numbers():
    model, result, _resources = _targeted_human_number_analysis()

    markdown = Analyzer.markdown(result, model)

    assert "- Final time: 1.23457e6s" in markdown
    assert (
        "- Final resources: {'huge': 1.23457e18, 'tiny': 1.23457e-5}"
    ) in markdown
    assert "generator `fisherman`: 739.864s" in markdown
    assert "generator `boat`: Infinitys" in markdown
    assert "739.864019013290554" not in markdown


def test_report_keeps_exact_analysis_values_for_machine_consumers():
    model, result, resources = _targeted_human_number_analysis()

    report = Analyzer.report(result, model)
    fisherman = next(
        row
        for row in report["payback_report"]
        if row["profile_id"] == "casual" and row["item_id"] == "fisherman"
    )

    assert report["profile_summaries"]["casual"]["final_time_seconds"] == 1_234_567
    assert report["profile_summaries"]["casual"]["final_resources"] is resources
    assert fisherman["payback_seconds"] == "739.864019013290554"
    assert any(row["payback_seconds"] == "Infinity" for row in report["payback_report"])


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
