"""Exercise source artifacts through the same static report entry as formal runs."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from igess.reporting.static import generate_static_report


def _dto(value: str) -> dict:
    return {"sign": 1, "coeff": value, "exp": 0}


def _source_run(tmp_path: Path) -> Path:
    def event(time, kind, receipt):
        return {
            "profile_id": "default",
            "time_seconds": time,
            "kind": kind,
            "item_id": "",
            "details": {"receipt": json.dumps(receipt)},
        }

    run = tmp_path / "run"
    run.mkdir()
    samples = [
        {
            "time_seconds": time,
            "strength": strength,
            "fish_luck": luck,
            "trash_luck": luck,
            "spendable_money": "10",
            "unclaimed_money": "20",
            "collected_money": "30",
            "generated_money": "50",
            "material": "4",
            "trash_realm": "2",
            "total_throws": "1",
            "strength_rebirth_count": "1",
            "trash_man_rebirth_count": "0",
        }
        for time, strength, luck in [(0, "2", "1"), (60, "0", None), (86460, "5", "2")]
    ]
    events = [
        event(1, "prepare_throw", {"fishRollPower": _dto("9" * 200)}),
        event(2, "complete_throw", {"newFishInstanceIds": [1]}),
        event(
            10, "upgrade_fish", {"moneySpent": _dto("123456789012345678901234567890")}
        ),
        event(15, "sell_fish", {"materialAdded": _dto("40")}),
        event(
            20,
            "synthesize_barbell",
            {
                "barbellId": 2,
                "previousCount": 0,
                "currentCount": 1,
                "moneySpent": _dto("75"),
            },
        ),
        event(
            30,
            "rebirth_strength",
            {
                "oldCompletedCount": 0,
                "newCompletedCount": 1,
                "strengthBefore": _dto("100"),
                "strengthAfter": _dto("0"),
            },
        ),
        event(
            40,
            "start_breakthrough",
            {"instant": False, "fromRealmId": 1, "toRealmId": 2},
        ),
        event(60, "go_offline", {"online": False}),
        event(86400, "go_online", {"online": True}),
        event(86400, "claim_offline_reward", {"materialAwarded": _dto("500")}),
        event(86420, "purchase_torpedo", {"torpedoId": 2, "ownedIds": [1, 2]}),
        event(86460, "go_offline", {"online": False}),
    ]
    artifacts = {
        "run_manifest.json": {
            "engine_id": "fish_source",
            "scenario_id": "fixture",
            "profiles": ["default"],
            "source_runtime": {},
        },
        "timeline.json": [
            {
                "profile_id": "default",
                "time_seconds": row["time_seconds"],
                "resources": {
                    "money": row["spendable_money"],
                    "strength": row["strength"],
                },
                "total_cps": "2",
            }
            for row in samples
        ],
        "events.json": events,
        "analysis.json": {},
        "source_progression.json": {
            "schema_version": 1,
            "profiles": {"default": samples},
        },
        "source_behavior.json": {
            "schema_version": 1,
            "profiles": {
                "default": {
                    "accepted_commands": {"complete_throw": 1},
                    "rejected_commands": {},
                }
            },
        },
    }
    for name, payload in artifacts.items():
        (run / name).write_text(json.dumps(payload), encoding="utf-8")
    return run


def test_source_report_restores_readable_panels_without_inventing_metrics(tmp_path):
    run = _source_run(tmp_path)
    index = generate_static_report(run, tmp_path / "report")
    report = json.loads((index.parent / "report_data.json").read_text(encoding="utf-8"))
    fish = report["fish_progression"]
    assert fish["available"] is True
    core = fish["core"]["profiles"]["default"]
    assert core["summary"]["active_duration_seconds"]["exact_value"] == "120"
    assert core["rows"][1]["fish_luck_current"]["exact_value"] is None
    assert core["summary"]["longest_fish_luck_stagnation_seconds"] is None
    growth = fish["persistent"]["profiles"]["default"]
    assert growth["summary"]["total_progression_count"]["exact_value"] == "4"
    assert [len(day["rows"]) for day in growth["days"]] == [3, 1]
    assert growth["rows"][-1]["active_time_seconds"] == 80
    assert growth["rows"][2]["progression_category"] == "breakthrough_funding"
    investment = fish["investment"]["profiles"]["default"]
    assert investment["coin_spent"]["exact_value"] == "123456789012345678901234567890"
    assert investment["sale_material"]["exact_value"] == "40"
    assert investment["hall_income_gain"]["exact_value"] is None
    assert investment["trash_material"]["exact_value"] is None
    assert report["overview"]["purchase_count"]["exact_value"] == "2"
    assert report["overview"]["prestige_reset_count"]["exact_value"] == "1"
    assert all("receipt" not in row["details"] for row in report["series"]["events"])
    assert "source_progression" in report["artifacts"]
    assert "采样" in fish["notes"]["core"]


def test_source_report_does_not_turn_missing_artifacts_into_zero_metrics(tmp_path):
    run = _source_run(tmp_path)
    (run / "source_progression.json").unlink()
    index = generate_static_report(run, tmp_path / "report")
    report = json.loads((index.parent / "report_data.json").read_text(encoding="utf-8"))
    assert "source_progression.json" in report["overview"]["missing_artifacts"]
    assert report["fish_progression"]["core"]["profiles"] == {}
    assert report["fish_progression"]["persistent"]["profiles"]["default"]["rows"]


@pytest.mark.parametrize("asset", ["report.js", "report.min.js"])
def test_source_report_browser_renderer_shows_charts_and_chinese_summary(
    tmp_path, asset
):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for the report frontend")
    index = generate_static_report(_source_run(tmp_path), tmp_path / "report")
    harness = r"""
const fs = require('fs');
const vm = require('vm');
const data = JSON.parse(fs.readFileSync(process.argv[1], 'utf8'));
const elements = {};
const options = {};
const element = key => elements[key] || (elements[key] = {
  id: key, hidden: true, innerHTML: '', textContent: '',
  querySelector(selector) { return element(key + ' ' + selector); },
  querySelectorAll() { return []; },
  closest() { return element(key + ' section'); },
});
vm.runInNewContext(fs.readFileSync(process.argv[2], 'utf8'), {
  document: {
    querySelector: element,
    getElementById: id => id === 'igess-report-data' ? {textContent: JSON.stringify(data)} : element(id),
  },
  window: {addEventListener() {}}, console,
  echarts: {init: target => ({setOption: option => {options[target.id] = option;}, dispose() {}, resize() {}})},
});
setImmediate(() => console.log(JSON.stringify({elements, options})));
"""
    result = subprocess.run(
        [
            node,
            "--unhandled-rejections=strict",
            "-e",
            harness,
            str(index.parent / "report_data.json"),
            str(Path("src/igess/reporting/assets") / asset),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    rendered = json.loads(result.stdout)
    elements = rendered["elements"]
    for selector in (
        "data-fish-core-section",
        "data-fish-investment-section",
        "data-fish-persistent-section",
        "data-source-actions-section",
    ):
        assert elements[f"[{selector}]"]["hidden"] is False
    assert "完整投掷" in elements["[data-overview-kpis]"]["innerHTML"]
    assert (
        "prepare_throw"
        not in elements["[data-source-actions-section] [data-source-actions]"][
            "innerHTML"
        ]
    )
    assert (
        "突破资助（非完成）" in elements["[data-daily-progression-charts]"]["innerHTML"]
    )
    assert "../run/events.json" in elements["[data-evidence]"]["innerHTML"]
    assert (
        rendered["options"]["luck-progression-chart"]["series"][0]["data"][1]["value"][
            1
        ]
        is None
    )
    assert "采样峰值" in rendered["options"]["core-strength-chart"]["title"]["text"]
