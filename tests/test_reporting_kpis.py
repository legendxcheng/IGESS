from __future__ import annotations

from dataclasses import replace

import pytest

from igess.reporting.kpis import build_overview
from igess.reporting.loader import ReportData


def _report_data(tmp_path) -> ReportData:
    return ReportData(
        run_dir=tmp_path,
        manifest={"scenario_id": "fixture", "profiles": ["beta", "alpha"]},
        timeline=[
            {"profile_id": "alpha", "time_seconds": 10, "resources": {"gold": "8"}},
            {"profile_id": "beta", "time_seconds": 20, "resources": {"gold": "5"}},
            {"profile_id": "alpha", "time_seconds": 30, "resources": {"gold": "12"}},
            {"profile_id": "beta", "time_seconds": 5, "resources": {"gold": "1"}},
        ],
        events=[
            {
                "profile_id": "alpha",
                "time_seconds": 0,
                "kind": "unlock_generator",
                "item_id": "zero",
            },
            {
                "profile_id": "beta",
                "time_seconds": 3,
                "kind": "unlock_upgrade",
                "item_id": "z",
            },
            {
                "profile_id": "alpha",
                "time_seconds": 3,
                "kind": "unlock_activity",
                "item_id": "b",
            },
            {
                "profile_id": "alpha",
                "time_seconds": 3,
                "kind": "unlock_activity",
                "item_id": "a",
            },
            {
                "profile_id": "alpha",
                "time_seconds": 4,
                "kind": "buy_generator",
                "item_id": "g",
            },
            {
                "profile_id": "beta",
                "time_seconds": 5,
                "kind": "buy_upgrade",
                "item_id": "u",
            },
            {
                "profile_id": "beta",
                "time_seconds": 6,
                "kind": "prestige_reset",
                "item_id": "p",
            },
        ],
        analysis={
            "invalid_content_report": {
                "never_purchased": ["generator:x"],
                "never_unlocked": ["upgrade:y"],
            },
            "overpowered_content_report": [{"item_id": "generator:g"}],
            "bottleneck_report": {"alpha": [{"start": 0, "end": 90, "duration": 90}]},
        },
        payback_rows=[
            {
                "profile_id": "alpha",
                "kind": "generator",
                "item_id": "g",
                "payback_seconds": "100",
            },
            {
                "profile_id": "beta",
                "kind": "upgrade",
                "item_id": "z",
                "payback_seconds": "Infinity",
            },
            {
                "profile_id": "alpha",
                "kind": "upgrade",
                "item_id": "b",
                "payback_seconds": "Infinity",
            },
        ],
        missing_artifacts=[],
    )


def test_build_overview_derives_decision_kpis(tmp_path):
    overview = build_overview(_report_data(tmp_path))

    assert overview["duration_seconds"] == "30"
    assert overview["profiles"] == ["beta", "alpha"]
    assert list(overview["final_resources"]) == ["beta", "alpha"]
    assert overview["final_resources"] == {
        "beta": {"gold": "5"},
        "alpha": {"gold": "12"},
    }
    assert overview["purchase_count"] == 2
    assert overview["first_key_unlock"] == {
        "time_seconds": "3",
        "profile_id": "alpha",
        "kind": "unlock_activity",
        "item_id": "a",
    }
    assert overview["prestige_reset_count"] == 1
    assert overview["worst_payback"] == {
        "profile_id": "alpha",
        "kind": "upgrade",
        "item_id": "b",
        "payback_seconds": "Infinity",
    }
    assert overview["never_purchased_count"] == 1
    assert overview["never_unlocked_count"] == 1
    assert overview["warning_category_count"] == 5


def test_first_key_unlock_ignores_non_key_unlock_events(tmp_path):
    data = replace(
        _report_data(tmp_path),
        events=[
            {
                "profile_id": "alpha",
                "time_seconds": 1,
                "kind": "unlock_milestone",
                "item_id": "chapter_one",
            },
            {
                "profile_id": "alpha",
                "time_seconds": 2,
                "kind": "unlock_other",
                "item_id": "future_kind",
            },
            {
                "profile_id": "beta",
                "time_seconds": 3,
                "kind": "unlock_generator",
                "item_id": "mine",
            },
        ],
    )

    assert build_overview(data)["first_key_unlock"] == {
        "time_seconds": "3",
        "profile_id": "beta",
        "kind": "unlock_generator",
        "item_id": "mine",
    }


@pytest.mark.parametrize(
    "category",
    [
        "never_purchased",
        "never_unlocked",
        "overpowered",
        "infinite_payback",
        "bottleneck_gaps",
    ],
)
def test_warning_count_tracks_nonempty_categories(tmp_path, category):
    data = _report_data(tmp_path)

    if category == "never_purchased":
        data.analysis["invalid_content_report"]["never_purchased"] = []
    elif category == "never_unlocked":
        data.analysis["invalid_content_report"]["never_unlocked"] = []
    elif category == "overpowered":
        data.analysis["overpowered_content_report"] = []
    elif category == "infinite_payback":
        data.payback_rows[:] = data.payback_rows[:1]
    elif category == "bottleneck_gaps":
        data.analysis["bottleneck_report"] = {"alpha": []}

    assert build_overview(data)["warning_category_count"] == 4


def test_warning_count_is_zero_when_all_warning_inputs_are_empty(tmp_path):
    data = replace(
        _report_data(tmp_path),
        analysis={
            "invalid_content_report": {"never_purchased": [], "never_unlocked": []},
            "overpowered_content_report": [],
            "bottleneck_report": {},
        },
        payback_rows=[],
    )

    assert build_overview(data)["warning_category_count"] == 0


def test_worst_finite_payback_uses_decimal_order_and_tuple_tie_break(tmp_path):
    data = replace(
        _report_data(tmp_path),
        payback_rows=[
            {
                "profile_id": "beta",
                "kind": "generator",
                "item_id": "z",
                "payback_seconds": "10",
            },
            {
                "profile_id": "alpha",
                "kind": "upgrade",
                "item_id": "b",
                "payback_seconds": "1e1",
            },
            {
                "profile_id": "alpha",
                "kind": "generator",
                "item_id": "c",
                "payback_seconds": "9.999999999999999999999999999999999999",
            },
        ],
    )

    assert build_overview(data)["worst_payback"] == {
        "profile_id": "alpha",
        "kind": "upgrade",
        "item_id": "b",
        "payback_seconds": "1e1",
    }


def test_empty_report_inputs_return_stable_defaults(tmp_path):
    data = ReportData(
        run_dir=tmp_path,
        manifest={"scenario_id": "empty", "profiles": ["beta", "alpha"]},
        timeline=[],
        events=[],
        analysis={},
        payback_rows=[],
        missing_artifacts=[],
    )

    overview = build_overview(data)

    assert overview["duration_seconds"] == "0"
    assert overview["profiles"] == ["beta", "alpha"]
    assert overview["final_resources"] == {"beta": {}, "alpha": {}}
    assert overview["purchase_count"] == 0
    assert overview["first_key_unlock"] is None
    assert overview["prestige_reset_count"] == 0
    assert overview["worst_payback"] is None
    assert overview["never_purchased_count"] == 0
    assert overview["never_unlocked_count"] == 0
    assert overview["warning_category_count"] == 0
