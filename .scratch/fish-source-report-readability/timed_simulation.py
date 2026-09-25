"""Time the existing formal workflow without changing simulation behavior."""

import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from igess.authoring.service import AuthoringService
from igess.outputs import OutputWriter
from igess.reporting.static import generate_static_report
from igess.run_registry import RunRegistry
from igess.workflows import WorkflowService

project = Path("projects/fish_source").resolve()
scenario = sys.argv[1] if len(sys.argv) > 1 else "month_1_growth"
timings = {}


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
response = workflow.run_authoring_scenario(scenario)
timings["formal_workflow_seconds"] = round(time.perf_counter() - started, 3)
payload = {
    "started_at": started_at,
    "finished_at": datetime.now(UTC).isoformat(),
    "timings": timings,
    "response": response.to_payload(),
}
output_dir = response.result.get("output_dir")
if output_dir:
    (Path(output_dir).parent / "wall_clock_timing.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8",
    )
(Path(__file__).parent / f"latest-{scenario}-timing.json").write_text(
    json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8",
)
print(json.dumps(payload, ensure_ascii=False), flush=True)
sys.exit(0 if response.ok else 1)
