from __future__ import annotations

import json
from pathlib import Path
import threading
import time
from urllib.request import urlopen

import yaml

from igess.authoring.live_report import (
    LiveReportState,
    LiveRun,
    changed_files,
    discover_watch_files,
    fingerprint_files,
    start_live_server,
    validate_live_run,
    run_live_report,
)
from igess.authoring.response import CommandResponse


def test_discovers_project_and_configured_production_inputs(tmp_path: Path) -> None:
    root = tmp_path / "model"
    datas = root / "Datas"
    production = tmp_path / "production" / "json"
    schema = tmp_path / "production" / "python" / "schema.py"
    datas.mkdir(parents=True)
    production.mkdir(parents=True)
    schema.parent.mkdir(parents=True)
    (datas / "__tables__.xlsx").write_bytes(b"registry")
    (datas / "values.xlsx").write_bytes(b"values")
    (datas / "~$values.xlsx").write_bytes(b"temporary")
    schema.write_text("class cfg_Tables: pass\n", encoding="utf-8")
    (production / "tbfish.json").write_text("[]\n", encoding="utf-8")
    (production / "ignored.json").write_text("[]\n", encoding="utf-8")
    config = {
        "engine": {
            "data_root": str(production),
            "python_schema": str(schema),
            "required_tables": ["tbfish"],
        }
    }
    (root / "economy.yaml").write_text(
        yaml.safe_dump(config), encoding="utf-8"
    )

    watched = set(discover_watch_files(root))

    assert watched == {
        (root / "economy.yaml").resolve(),
        (datas / "__tables__.xlsx").resolve(),
        (datas / "values.xlsx").resolve(),
        schema.resolve(),
        (production / "tbfish.json").resolve(),
    }


def test_content_fingerprints_report_changed_added_and_removed_files(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    first.write_text("1", encoding="utf-8")
    before = fingerprint_files((first, second))

    first.write_text("2", encoding="utf-8")
    second.write_text("3", encoding="utf-8")
    after = fingerprint_files((first, second))

    assert changed_files(before, after) == tuple(
        sorted((str(first.resolve()), str(second.resolve())), key=str.casefold)
    )


def test_live_server_keeps_one_url_and_switches_report_root(tmp_path: Path) -> None:
    report = tmp_path / "report"
    report.mkdir()
    (report / "index.html").write_text("<h1>current report</h1>", encoding="utf-8")
    state = LiveReportState("week_1_growth")
    state.publish(
        LiveRun(
            run_id="run-1",
            scenario_id="week_1_growth",
            model_digest="sha256:abc",
            output_dir=tmp_path / "output",
            report_index=report / "index.html",
        )
    )
    server, thread, url = start_live_server(state)
    try:
        with urlopen(url, timeout=2) as response:
            shell = response.read().decode("utf-8")
        with urlopen(url + "api/status", timeout=2) as response:
            status = json.loads(response.read().decode("utf-8"))
        with urlopen(url + "report/index.html", timeout=2) as response:
            rendered = response.read().decode("utf-8")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert "第一轮正式模拟" in shell
    assert status["revision"] == 1
    assert status["run_id"] == "run-1"
    assert rendered == "<h1>current report</h1>"


def test_validates_complete_fish_production_run(tmp_path: Path) -> None:
    root = tmp_path / "model"
    output = root / "runs" / "run-1" / "output"
    report = root / "runs" / "run-1" / "report"
    production = tmp_path / "production" / "json"
    schema = tmp_path / "production" / "python" / "schema.py"
    output.mkdir(parents=True)
    report.mkdir(parents=True)
    production.mkdir(parents=True)
    schema.parent.mkdir(parents=True)
    schema.write_text("# generated\n", encoding="utf-8")
    (root / "economy.yaml").write_text(
        yaml.safe_dump(
            {
                "engine": {
                    "production_data": True,
                    "data_root": str(production),
                    "python_schema": str(schema),
                }
            }
        ),
        encoding="utf-8",
    )
    (report / "index.html").write_text("report", encoding="utf-8")
    artifact_names = [
        "analysis.json",
        "analysis.md",
        "events.csv",
        "events.json",
        "final_checkpoint.json",
        "timeline.csv",
        "timeline.json",
        "behavior_progression.csv",
        "behavior_progression.json",
        "luck_progression.csv",
        "luck_progression.json",
    ]
    for name in artifact_names:
        (output / name).write_text("{}\n", encoding="utf-8")
    manifest = {
        "artifacts": artifact_names,
        "engine_id": "fish",
        "scenario_id": "week_1_growth",
        "model_digest": "sha256:abc",
        "production_data": True,
        "matches_production_data": True,
        "data_root": str(production),
        "loader_files": [{"file": str(schema), "sha256": "sha256:def"}],
    }
    (output / "run_manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    response = CommandResponse(
        "model.simulate",
        True,
        "simulated",
        "done",
        result={
            "run_id": "run-1",
            "scenario_id": "week_1_growth",
            "model_digest": "sha256:abc",
            "output_dir": str(output),
            "report_index": str(report / "index.html"),
        },
    )

    run = validate_live_run(
        response,
        project_root=root,
        scenario_id="week_1_growth",
    )

    assert run.run_id == "run-1"
    assert run.report_index == (report / "index.html").resolve()


def test_watcher_reruns_after_an_input_change(tmp_path: Path) -> None:
    root = tmp_path / "model"
    output = root / "runs" / "run-1" / "output"
    report = root / "runs" / "run-1" / "report"
    output.mkdir(parents=True)
    report.mkdir(parents=True)
    config = root / "economy.yaml"
    config.write_text("model: {id: test}\n", encoding="utf-8")
    (report / "index.html").write_text("report", encoding="utf-8")
    artifacts = [
        "analysis.json",
        "analysis.md",
        "events.csv",
        "events.json",
        "final_checkpoint.json",
        "timeline.csv",
        "timeline.json",
    ]
    for name in artifacts:
        (output / name).write_text("{}\n", encoding="utf-8")
    (output / "run_manifest.json").write_text(
        json.dumps(
            {
                "artifacts": artifacts,
                "scenario_id": "smoke",
                "model_digest": "sha256:abc",
            }
        ),
        encoding="utf-8",
    )
    response = CommandResponse(
        "model.simulate",
        True,
        "simulated",
        "done",
        result={
            "run_id": "run-1",
            "scenario_id": "smoke",
            "model_digest": "sha256:abc",
            "output_dir": str(output),
            "report_index": str(report / "index.html"),
        },
    )
    second_run = threading.Event()
    stop = threading.Event()

    class FakeService:
        calls = 0

        def simulate(self, scenario_id: str) -> CommandResponse:
            assert scenario_id == "smoke"
            self.calls += 1
            if self.calls == 2:
                second_run.set()
                stop.set()
            return response

    service = FakeService()
    watcher = threading.Thread(
        target=run_live_report,
        kwargs={
            "project_root": root,
            "scenario_id": "smoke",
            "poll_seconds": 0.01,
            "debounce_seconds": 0.02,
            "open_browser": False,
            "service_factory": lambda _root: service,
            "stop_event": stop,
        },
    )
    watcher.start()
    deadline = time.monotonic() + 2
    while service.calls < 1 and time.monotonic() < deadline:
        time.sleep(0.01)

    config.write_text("model: {id: changed}\n", encoding="utf-8")

    assert second_run.wait(2)
    watcher.join(timeout=2)
    assert not watcher.is_alive()
    assert service.calls == 2
