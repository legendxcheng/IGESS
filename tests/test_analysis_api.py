"""Read-only analysis through the agreed public service and CLI seams."""
import json
from pathlib import Path

import pytest

from igess.analysis_api import AnalysisService
from igess.cli import main
from igess.run_registry import RunRegistry


def run_fixture(project: Path, run_id="run-a", *, engine="generic", status="success",
                start=0, end=86400, events=None, scope=None, resources=None):
    root = project / "runs" / run_id
    output = root / "output"
    output.mkdir(parents=True)
    files = {
        "run_manifest.json": {"schema_version": 1, "model_id": "fixture", "engine_id": engine,
            "scenario_id": "day", "profiles": ["default"], "model_digest": "sha256:" + "a" * 64,
            "execution_window": {"start_seconds": start, "end_seconds": end},
            "source_profiles": {"default": scope or {}},
            "artifacts": ["timeline.json", "events.json", "analysis.json"]},
        "timeline.json": [{"scenario_id": "day", "profile_id": "default", "time_seconds": t,
            "resources": resources or {"money": "123.5"}, "total_cps": "1"} for t in (start, end)],
        "events.json": events or [], "analysis.json": {},
    }
    for name, value in files.items():
        (output / name).write_text(json.dumps(value), encoding="utf-8")
    RunRegistry(project / "runs").write_status(root, status=status, scenario_id="day", message="fixture",
        output_dir=output, report_dir=root / "report", report_index=root / "report/index.html",
        kind="formal", engine_id=engine, model_digest="sha256:" + "a" * 64)
    return output


def result(service, command, **kwargs):
    response = service.execute(command, **kwargs).to_payload()
    assert response["ok"], response
    return response["result"]


def test_runs_are_queryable_without_model_inputs_and_cli_returns_same_identity(tmp_path, capsys):
    run_fixture(tmp_path)
    service = AnalysisService(tmp_path)
    listing = result(service, "runs.list", limit=1)
    assert listing["total"] == 1
    assert listing["items"][0]["run_id"] == "run-a"
    detail = result(service, "runs.show", run_id="run-a")
    assert detail["manifest"]["profiles"] == ["default"]
    assert main(["runs", "show", "--project", str(tmp_path), "--run-id", "run-a", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["result"] == detail


def test_query_rejects_conflicting_identity_and_unsafe_artifact(tmp_path):
    output = run_fixture(tmp_path)
    path = output / "run_manifest.json"
    manifest = json.loads(path.read_text())
    manifest["scenario_id"] = "another"
    path.write_text(json.dumps(manifest))
    service = AnalysisService(tmp_path)
    assert service.execute("runs.show", run_id="run-a").code == "identity_conflict"
    manifest["scenario_id"] = "day"
    manifest["artifacts"].append("../../outside.json")
    path.write_text(json.dumps(manifest))
    assert service.execute("runs.artifacts", run_id="run-a").code == "unsafe_path"


def test_failed_run_remains_queryable_and_missing_manifest_is_explicit(tmp_path):
    output = run_fixture(tmp_path, status="failed")
    (output / "run_manifest.json").unlink()
    service = AnalysisService(tmp_path)
    detail = result(service, "runs.show", run_id="run-a")
    assert detail["status"] == "failed"
    assert detail["identity_complete"] is False
    assert any(item["name"] == "run_manifest.json" and not item["exists"]
               for item in result(service, "runs.artifacts", run_id="run-a")["items"])


def test_generic_metric_catalog_and_exact_values_with_missing_and_zero(tmp_path):
    amount = "1" + "0" * 90 + ".125"
    run_fixture(tmp_path, resources={"money": amount})
    service = AnalysisService(tmp_path)
    catalog = result(service, "metrics.describe", engine_id="generic")
    assert "resource.final" in {m["metric_id"] for m in catalog["metrics"]}
    value = result(service, "metrics.extract", run_id="run-a", metric_id="resource.final",
                   profile_id="default", dimensions={"resource": "money"})["metrics"][0]
    assert value["value"] == amount
    assert value["value_status"] == "recorded"
    assert value["evidence"][0]["artifact"] == "timeline.json"
    zero = result(service, "metrics.extract", run_id="run-a", metric_id="purchase.count",
                  profile_id="default", dimensions={})["metrics"][0]
    assert zero["value"] == 0
    missing = result(service, "metrics.extract", run_id="run-a", metric_id="payback.seconds",
                     profile_id="default", dimensions={"item": "generator:mine"})["metrics"][0]
    assert missing["value_status"] == "not_recorded"
    assert "value" not in missing
    assert service.execute("metrics.extract", run_id="run-a", metric_id="typo",
                           profile_id="default").code == "unknown_metric"


def fish_scope():
    return {"initial_online": True, "initial_active_time_seconds": 0,
            "collection_growth": {"version": 1, "initial_unlocked_entries": [], "initial_gun_facts": []},
            "pool_growth": {"version": 1, "initial_seen_pool_ids": []}}


def fish_event(time, kind="codex_fish_unlocked", fish=101, mutation=2):
    return {"profile_id": "default", "time_seconds": time, "kind": kind, "item_id": "",
            "details": {"receipt": json.dumps({"fishId": fish, "mutationId": mutation})}}


def test_fish_counts_dual_labels_once_and_marks_boundary_day_partial(tmp_path):
    run_fixture(tmp_path, engine="fish_source", scope=fish_scope(),
                events=[fish_event(10), fish_event(20), fish_event(86400, fish=102)])
    service = AnalysisService(tmp_path)
    total = result(service, "metrics.extract", run_id="run-a", metric_id="growth.count",
                   profile_id="default")["metrics"][0]
    assert total["value"] == 2
    tags = result(service, "metrics.extract", run_id="run-a", metric_id="growth.labels",
                  profile_id="default", dimensions={"categories": ["new_fish_species", "new_fish_variant"]})["metrics"][0]
    assert tags["value"] == 4
    day1 = result(service, "metrics.extract", run_id="run-a", metric_id="growth.count",
                  profile_id="default", dimensions={"day": 1})["metrics"][0]
    assert day1["value"] == 1 and day1["coverage"]["complete"]
    day2 = result(service, "metrics.extract", run_id="run-a", metric_id="growth.count",
                  profile_id="default", dimensions={"day": 2})["metrics"][0]
    assert day2["value"] == 1 and not day2["coverage"]["complete"]


def test_fish_gaps_exclude_offline_and_node_reports_observation_time(tmp_path):
    events = [fish_event(10), fish_event(30, "go_offline"), fish_event(86390, "go_online"),
              fish_event(86395, fish=102)]
    run_fixture(tmp_path, engine="fish_source", scope=fish_scope(), events=events)
    service = AnalysisService(tmp_path)
    for metric, expected in [("growth.first_wait", 10), ("growth.max_interval", 25),
                             ("growth.tail_wait", 5), ("growth.max_gap", 25)]:
        item = result(service, "metrics.extract", run_id="run-a", metric_id=metric,
                      profile_id="default", time_basis="online")["metrics"][0]
        assert item["value"] == expected
    node = result(service, "metrics.extract", run_id="run-a", metric_id="growth.node_seconds",
                  profile_id="default", time_basis="online",
                  dimensions={"identity": "fish_collection:102:2"})["metrics"][0]
    assert node["value"] == 35


def test_no_growth_wait_and_single_event_interval_are_not_confused(tmp_path):
    run_fixture(tmp_path, engine="fish_source", scope=fish_scope(), end=100)
    service = AnalysisService(tmp_path)
    wait = result(service, "metrics.extract", run_id="run-a", metric_id="growth.max_gap",
                  profile_id="default", time_basis="online")["metrics"][0]
    assert wait["value"] == 100
    interval = result(service, "metrics.extract", run_id="run-a", metric_id="growth.max_interval",
                      profile_id="default", time_basis="online")["metrics"][0]
    assert interval["value_status"] == "not_applicable" and "value" not in interval


def target_file(project, targets):
    path = project / "targets.json"
    path.write_text(json.dumps({"schema_version": 1, "target_set_id": "demo", "version": "1",
                               "source": "test example", "targets": targets}), encoding="utf-8")
    return path


def target(metric="resource.final", value="124", **changes):
    return {"target_id": "money", "metric_id": metric, "profile_id": "default",
            "dimensions": {"resource": "money"}, "unit": "resource", "time_basis": "wall",
            "scope": "segment", "aggregation": "value", "operator": "gte", "value": value, **changes}


def test_target_failure_is_successful_evaluation_with_exact_negative_delta(tmp_path, capsys):
    run_fixture(tmp_path)
    path = target_file(tmp_path, [target()])
    evaluation = result(AnalysisService(tmp_path), "targets.evaluate", run_id="run-a", target_file=path)
    assert evaluation["evaluation_status"] == "failed"
    assert evaluation["targets"][0]["delta"] == "-0.5"
    assert evaluation["targets"][0]["status"] == "failed"
    assert main(["targets", "evaluate", "--project", str(tmp_path), "--run-id", "run-a",
                 "--target-file", str(path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["ok"]


@pytest.mark.parametrize("change,expected", [
    ({"operator": "eq", "value": "123.5"}, "passed"),
    ({"operator": "between", "value": ["123.5", "124"]}, "passed"),
    ({"operator": "lte", "value": "123", "tolerance": "0.5"}, "passed"),
    ({"operator": "gte", "value": "124", "tolerance": "0.49"}, "failed"),
])
def test_targets_use_closed_bounds_and_explicit_tolerance(tmp_path, change, expected):
    run_fixture(tmp_path)
    evaluation = result(AnalysisService(tmp_path), "targets.evaluate", run_id="run-a",
                        target_file=target_file(tmp_path, [target(**change)]))
    assert evaluation["evaluation_status"] == expected


def test_invalid_targets_are_rejected_instead_of_silently_skipped(tmp_path):
    run_fixture(tmp_path)
    service = AnalysisService(tmp_path)
    for targets in ([], [target(), target()], [target(unit="seconds")], [target(dimensions={"typo": "money"})]):
        response = service.execute("targets.evaluate", run_id="run-a", target_file=target_file(tmp_path, targets))
        assert not response.ok


def test_export_preserves_inputs_and_refuses_existing_or_authoritative_destinations(tmp_path):
    run_fixture(tmp_path)
    path = target_file(tmp_path, [target()])
    before = {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    service = AnalysisService(tmp_path)
    out = tmp_path / "analysis-export"
    evaluation = result(service, "targets.evaluate", run_id="run-a", target_file=path, out=out)
    saved = json.loads((out / "evaluation.json").read_text(encoding="utf-8"))
    assert saved["evaluation_status"] == "failed"
    assert saved["input_digests"] == evaluation["input_digests"]
    assert "-0.5" in (out / "evaluation.md").read_text(encoding="utf-8")
    assert all(Path(p).read_bytes() == content for p, content in before.items())
    again = result(service, "targets.evaluate", run_id="run-a", target_file=path)
    assert again["targets"] == evaluation["targets"]
    assert service.execute("targets.evaluate", run_id="run-a", target_file=path, out=out).code == "output_exists"
    assert service.execute("targets.evaluate", run_id="run-a", target_file=path,
                           out=tmp_path / "runs/new-analysis").code == "unsafe_output"


def test_fish_targets_score_explicit_overlap_and_partial_periods(tmp_path):
    run_fixture(tmp_path, engine="fish_source", scope=fish_scope(), events=[fish_event(10)], end=100)
    selected = ["new_fish_species", "new_fish_variant"]
    entries = [
        target("growth.score", "5", target_id="labels", unit="points", dimensions={
            "categories": selected, "scoring": "per_label", "weights": {selected[0]: "2", selected[1]: "3"}}),
        target("growth.score", "2", target_id="events", unit="points", dimensions={
            "categories": selected, "scoring": "per_event", "event_weight": "2"}),
        target("growth.count", "1", target_id="day", unit="count", dimensions={"day": 1}),
    ]
    evaluation = result(AnalysisService(tmp_path), "targets.evaluate", run_id="run-a",
                        target_file=target_file(tmp_path, entries))
    assert [r["actual"]["value"] for r in evaluation["targets"]] == ["5", "2", 1]
    assert [r["status"] for r in evaluation["targets"]] == ["passed", "passed", "not_evaluable"]
    assert evaluation["evaluation_status"] == "incomplete"
    entries[0]["value"] = "6"
    negative = result(AnalysisService(tmp_path), "targets.evaluate", run_id="run-a",
                      target_file=target_file(tmp_path, entries))
    assert negative["evaluation_status"] == "failed"
    assert negative["summary"]["not_evaluable"] == 1


def test_unreached_node_fails_only_when_deadline_is_observed(tmp_path):
    run_fixture(tmp_path, engine="fish_source", scope=fish_scope(), end=100)
    entries = [target("growth.node_seconds", "50", target_id="past", unit="seconds", operator="lte",
                      time_basis="online", dimensions={"identity": "gun_owned:1"}),
               target("growth.node_seconds", "101", target_id="future", unit="seconds", operator="lte",
                      time_basis="online", dimensions={"identity": "gun_owned:1"})]
    evaluation = result(AnalysisService(tmp_path), "targets.evaluate", run_id="run-a",
                        target_file=target_file(tmp_path, entries))
    assert [r["status"] for r in evaluation["targets"]] == ["failed", "not_evaluable"]


@pytest.mark.parametrize("status", ["failed", "running"])
def test_non_successful_run_cannot_be_analyzed(tmp_path, status):
    run_fixture(tmp_path, status=status)
    service = AnalysisService(tmp_path)
    assert result(service, "runs.show", run_id="run-a")["status"] == status
    response = service.execute("metrics.extract", run_id="run-a", metric_id="resource.final",
                               profile_id="default", dimensions={"resource": "money"})
    assert response.code == "run_not_successful"


def test_unknown_named_generic_entity_is_not_a_zero_purchase(tmp_path):
    run_fixture(tmp_path)
    item = result(AnalysisService(tmp_path), "metrics.extract", run_id="run-a", metric_id="purchase.count",
                  profile_id="default", dimensions={"item": "generator:nonexistent"})["metrics"][0]
    assert item["value_status"] == "not_recorded"


def test_yaml_syntax_errors_are_structured_and_yaml_decimals_preserve_precision(tmp_path):
    run_fixture(tmp_path, resources={"money": "123456789012345678901234567890.125"})
    json_path = target_file(tmp_path, [target(value="123456789012345678901234567890.125", operator="eq")])
    import yaml
    path = tmp_path / "targets.yaml"
    path.write_text(yaml.safe_dump(json.loads(json_path.read_text())).replace("'123456789012345678901234567890.125'", "123456789012345678901234567890.125"), encoding="utf-8")
    service = AnalysisService(tmp_path)
    assert result(service, "targets.evaluate", run_id="run-a", target_file=path)["evaluation_status"] == "passed"
    path.write_text("targets: [broken", encoding="utf-8")
    response = service.execute("targets.evaluate", run_id="run-a", target_file=path)
    assert not response.ok


def test_target_delta_keeps_more_than_eighty_digits(tmp_path):
    number = "1" + "0" * 90
    run_fixture(tmp_path, resources={"money": number + ".125"})
    evaluation = result(AnalysisService(tmp_path), "targets.evaluate", run_id="run-a",
                        target_file=target_file(tmp_path, [target(value=number + ".25")]))
    assert evaluation["targets"][0]["delta"] == "-0.125"


def test_resume_does_not_invent_lifecycle_first_or_full_day(tmp_path):
    scope = fish_scope()
    scope.update(initial_active_time_seconds=10)
    scope["collection_growth"]["initial_unlocked_entries"] = [{"fishId": 101, "mutationId": 2}]
    scope["first_times"] = {"treasure_beast_unlocked": {"time_seconds": 5, "online_time_seconds": "5"}}
    run_fixture(tmp_path, engine="fish_source", start=50, end=100, scope=scope,
                events=[fish_event(60), fish_event(70, fish=102)])
    service = AnalysisService(tmp_path)
    count = result(service, "metrics.extract", run_id="run-a", metric_id="growth.count",
                   profile_id="default")["metrics"][0]
    assert count["value"] == 1
    node = result(service, "metrics.extract", run_id="run-a", metric_id="growth.node_seconds",
                  profile_id="default", scope="lifecycle", dimensions={"identity": "treasure_beast_unlocked"})["metrics"][0]
    assert node["value"] == 5
    unknown = result(service, "metrics.extract", run_id="run-a", metric_id="growth.node_seconds",
                     profile_id="default", scope="lifecycle", dimensions={"identity": "fish_collection:102:2"})["metrics"][0]
    assert unknown["value_status"] == "not_recorded"
    day = result(service, "metrics.extract", run_id="run-a", metric_id="growth.count",
                 profile_id="default", dimensions={"through_day": 1})["metrics"][0]
    assert not day["coverage"]["complete"]


def test_consumer_provider_cannot_silently_mix_changed_artifacts(tmp_path):
    from igess.analysis_api.metrics import GenericMetrics
    output = run_fixture(tmp_path)
    class ChangingProvider(GenericMetrics):
        def extract(self, data, query):
            item = super().extract(data, query)
            (output / "events.json").write_text('[{"changed": true}]')
            return item
    response = AnalysisService(tmp_path, providers={"generic": ChangingProvider()}).execute(
        "metrics.extract", run_id="run-a", metric_id="resource.final", profile_id="default",
        dimensions={"resource": "money"})
    assert response.code == "input_changed"


def test_list_uses_registry_priority_and_filters_without_changing_history(tmp_path):
    output = run_fixture(tmp_path, run_id="same")
    import shutil
    shutil.copytree(output.parent, tmp_path / ".igess/runs/same")
    run_fixture(tmp_path, run_id="other", status="failed")
    service = AnalysisService(tmp_path)
    listing = result(service, "runs.list", limit=1)
    assert listing["total"] == 2 and listing["has_more"]
    assert len(result(service, "runs.list", limit=1, offset=1)["items"]) == 1
    assert result(service, "runs.list", status="success")["total"] == 1
    assert result(service, "runs.show", run_id="same")["output_dir"] == str(output)
    assert service.execute("runs.show", run_id="../outside").code == "run_not_found"


def test_execution_window_conflict_is_not_used_as_coverage(tmp_path):
    output = run_fixture(tmp_path)
    path = output / "run_manifest.json"
    value = json.loads(path.read_text())
    value["execution_window"]["end_seconds"] = 100
    path.write_text(json.dumps(value))
    response = AnalysisService(tmp_path).execute("metrics.extract", run_id="run-a", metric_id="purchase.count",
                                               profile_id="default")
    assert response.code == "identity_conflict"


def test_linked_artifact_is_rejected(tmp_path):
    output = run_fixture(tmp_path)
    outside = tmp_path / "outside.json"
    outside.write_text("[]")
    events = output / "events.json"
    events.unlink()
    try:
        events.symlink_to(outside)
    except OSError:
        pytest.skip("Symlink creation unavailable")
    response = AnalysisService(tmp_path).execute("metrics.extract", run_id="run-a", metric_id="purchase.count",
                                               profile_id="default")
    assert response.code == "unsafe_path"


def test_fish_growth_agrees_with_existing_static_report_and_demo_targets_run(tmp_path):
    from test_source_fish_reporting import _source_run
    from igess.reporting.static import generate_static_report
    output = _source_run(tmp_path)
    manifest_path = output / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["source_profiles"] = {"default": fish_scope()}
    manifest_path.write_text(json.dumps(manifest))
    root = tmp_path / "runs/real-shape"
    root.mkdir(parents=True)
    import shutil
    shutil.move(str(output), str(root / "output"))
    output = root / "output"
    RunRegistry(tmp_path / "runs").write_status(root, status="success", scenario_id="fixture", message="fixture",
        output_dir=output, report_dir=root / "report", report_index=root / "report/index.html",
        kind="formal", engine_id="fish_source", model_digest="sha256:" + "a" * 64)
    index = generate_static_report(output, root / "report")
    report = json.loads((index.parent / "report_data.json").read_text(encoding="utf-8"))
    value = result(AnalysisService(tmp_path), "metrics.extract", run_id="real-shape", metric_id="growth.count",
                   profile_id="default")["metrics"][0]
    assert value["value"] == 5
    assert str(value["value"]) == report["fish_progression"]["persistent"]["profiles"]["default"]["summary"]["total_progression_count"]["exact_value"]
    demo = result(AnalysisService(tmp_path), "targets.evaluate", run_id="real-shape",
                  target_file=Path("examples/analysis/fish-targets-demo.yaml"))
    assert demo["summary"]["total"] == 3


@pytest.mark.parametrize("time_basis", ["wall", "online"])
def test_node_deadline_before_resume_window_is_not_evaluable(tmp_path, time_basis):
    scope = fish_scope()
    scope["initial_active_time_seconds"] = 50
    run_fixture(tmp_path, engine="fish_source", scope=scope, start=50, end=100)
    entry = target("growth.node_seconds", "40", unit="seconds", operator="lte", time_basis=time_basis,
                   dimensions={"identity": "gun_owned:1"})
    item = result(AnalysisService(tmp_path), "targets.evaluate", run_id="run-a",
                  target_file=target_file(tmp_path, [entry]))["targets"][0]
    assert item["status"] == "not_evaluable"


def test_recorded_gun_node_does_not_depend_on_pool_coverage(tmp_path):
    from test_fish_collection_reporting import gun
    scope = fish_scope()
    del scope["pool_growth"]
    run_fixture(tmp_path, engine="fish_source", scope=scope, events=[gun(10, "gun_owned", 1)])
    item = result(AnalysisService(tmp_path), "metrics.extract", run_id="run-a", metric_id="growth.node_seconds",
                  profile_id="default", dimensions={"identity": "gun_owned:1"})["metrics"][0]
    assert item["value"] == 10 and item["coverage"]["complete"]


def test_malformed_nested_scope_and_export_config_return_errors(tmp_path):
    output = run_fixture(tmp_path, engine="fish_source")
    path = output / "run_manifest.json"
    document = json.loads(path.read_text())
    document["source_profiles"]["default"] = []
    path.write_text(json.dumps(document))
    response = AnalysisService(tmp_path).execute("metrics.extract", run_id="run-a", metric_id="growth.count",
                                               profile_id="default")
    assert response.code == "invalid_artifact"
    run_fixture(tmp_path, run_id="generic")
    (tmp_path / "economy.yaml").write_text("engine: null")
    response = AnalysisService(tmp_path).execute("targets.evaluate", run_id="generic",
        target_file=target_file(tmp_path, [target()]), out=tmp_path / "export")
    assert not response.ok


def test_export_directory_swap_cannot_write_into_datas(tmp_path, monkeypatch):
    import os
    run_fixture(tmp_path)
    target_path = target_file(tmp_path, [target()])
    out = tmp_path / "export"
    protected = tmp_path / "Datas"
    protected.mkdir()
    original_open = os.open
    original_fdopen = os.fdopen
    attempted = []
    def swap_directory():
        if not attempted:
            attempted.append(True)
            try:
                out.rename(tmp_path / "moved-export")
                out.symlink_to(protected, target_is_directory=True)
            except PermissionError:
                pass  # Windows bound-directory handle must prevent the replacement.
    def swap_then_open(path, flags, *args, **kwargs):
        if str(path).endswith("evaluation.json"):
            swap_directory()
        return original_open(path, flags, *args, **kwargs)
    def swap_then_fdopen(fd, *args, **kwargs):
        swap_directory()
        return original_fdopen(fd, *args, **kwargs)
    monkeypatch.setattr(os, "fdopen" if os.name == "nt" else "open",
                        swap_then_fdopen if os.name == "nt" else swap_then_open)
    response = AnalysisService(tmp_path).execute("targets.evaluate", run_id="run-a", target_file=target_path, out=out)
    assert not list(protected.iterdir())
    assert attempted
    assert response.ok or response.code in {"unsafe_path", "input_changed"}


def test_invalid_event_kind_has_structured_error_in_service_and_cli(tmp_path, capsys):
    run_fixture(tmp_path, events=[{"profile_id": "default", "time_seconds": 10, "kind": [], "item_id": "x"}])
    response = AnalysisService(tmp_path).execute("metrics.extract", run_id="run-a", metric_id="purchase.count", profile_id="default")
    assert response.code == "invalid_artifact"
    assert main(["metrics", "extract", "--project", str(tmp_path), "--run-id", "run-a", "--metric-id", "purchase.count", "--profile-id", "default", "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["code"] == "invalid_artifact"


def test_tail_wait_evidence_includes_actual_last_event_after_hundred_events(tmp_path):
    run_fixture(tmp_path, engine="fish_source", scope=fish_scope(), end=110,
                events=[fish_event(t, fish=1000+t) for t in range(1, 102)])
    item = result(AnalysisService(tmp_path), "metrics.extract", run_id="run-a", metric_id="growth.tail_wait",
                  profile_id="default", time_basis="online")["metrics"][0]
    assert item["value"] == 9
    assert any(e.get("wall_time_seconds") == 101 for e in item["evidence"])
    assert item["evidence_selection"]["observed_event_count"] == 101


@pytest.mark.parametrize("replaced", ["artifact", "target"])
def test_replaced_input_with_same_bytes_is_still_a_snapshot_change(tmp_path, replaced):
    from igess.analysis_api.metrics import GenericMetrics
    output = run_fixture(tmp_path)
    targets = target_file(tmp_path, [target()])
    class ReplacingProvider(GenericMetrics):
        def extract(self, data, query):
            item = super().extract(data, query)
            original = output / "events.json" if replaced == "artifact" else targets
            replacement = original.with_name("replacement.json")
            replacement.write_bytes(original.read_bytes())
            replacement.replace(original)
            return item
    response = AnalysisService(tmp_path, providers={"generic": ReplacingProvider()}).execute(
        "targets.evaluate", run_id="run-a", target_file=targets)
    assert response.code == "input_changed"
