"""Time formal runs; optional *profile* tags are diagnostic, not benchmarks."""

import cProfile
import json
import sys
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from igess.authoring.service import AuthoringService
from igess.fish_source_runtime import FishSourceRuntime
from igess.outputs import OutputWriter
from igess.reporting.static import generate_static_report
from igess.run_registry import RunRegistry
from igess.workflows import WorkflowService

project = Path("projects/fish_source").resolve()
scenario = sys.argv[1] if len(sys.argv) > 1 else "month_1_growth"
timings = {}
tag = sys.argv[2] if len(sys.argv) > 2 else "baseline"
request_stats = defaultdict(lambda: {"count": 0, "seconds": 0.0})
original_request = FishSourceRuntime.request
original_freeze = FishSourceRuntime._freeze_source


def instrument_lua(self):
    root = original_freeze(self)
    entry = root / "simulation" / "cli.lua"
    source = entry.read_text(encoding="utf-8")
    probe = (Path(__file__).parent / "debug" / "lua_probe.lua").read_text(encoding="utf-8")
    source = source.replace("for line in io.lines() do", probe + "\nfor line in io.lines() do")
    result_path = (Path(__file__).parent / "debug" / f"{tag}-{scenario}-lua.json").resolve().as_posix()
    source += '\ndebug.sethook()\nlocal f = assert(io.open(' + json.dumps(result_path) + ', "w"))\nf:write(Json.Encode(probeStats))\nf:close()\n'
    entry.write_text(source, encoding="utf-8")
    return root


def measured_request(self, payload, **kwargs):
    started = time.perf_counter()
    try:
        return original_request(self, payload, **kwargs)
    finally:
        entry = request_stats[payload["op"]]
        entry["count"] += 1
        entry["seconds"] += time.perf_counter() - started


if "profile" in tag:
    FishSourceRuntime.request = measured_request
if "lua" in tag:
    FishSourceRuntime._freeze_source = instrument_lua


def timed_output(*args, **kwargs):
    started = time.perf_counter()
    print("Writing simulation artifacts", flush=True)
    result = OutputWriter.write_all(*args, **kwargs)
    timings["artifacts_seconds"] = round(time.perf_counter() - started, 3)
    return result


def timed_report(*args, **kwargs):
    started = time.perf_counter()
    print("Generating report", flush=True)
    result = generate_static_report(*args, **kwargs)
    timings["report_seconds"] = round(time.perf_counter() - started, 3)
    return result


started_at = datetime.now(UTC).isoformat()
started = time.perf_counter()
workflow = WorkflowService(
    project,
    authoring_service=AuthoringService(
        project, output_writer=timed_output, report_writer=timed_report,
    ),
    registry=RunRegistry(project / "runs"),
)
print(f"Starting {scenario} at {started_at}", flush=True)
profiler = cProfile.Profile()
if "profile" in tag:
    profiler.enable()
response = workflow.run_authoring_scenario(scenario)
if "profile" in tag:
    profiler.disable()
    profiler.dump_stats(str(Path(__file__).parent / "debug" / f"{tag}-{scenario}.prof"))
timings["formal_workflow_seconds"] = round(time.perf_counter() - started, 3)
payload = {
    "started_at": started_at,
    "finished_at": datetime.now(UTC).isoformat(),
    "timings": timings,
    "requests": dict(request_stats),
    "response": response.to_payload(),
}
output_dir = response.result.get("output_dir")
if output_dir:
    (Path(output_dir).parent / "wall_clock_timing.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n",
    )
(Path(__file__).parent / f"{tag}-{scenario}-timing.json").write_text(
    json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n",
)
print(json.dumps(payload, ensure_ascii=False), flush=True)
sys.exit(0 if response.ok else 1)
