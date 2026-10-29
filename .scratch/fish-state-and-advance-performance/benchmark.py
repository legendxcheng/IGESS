"""Run one matched formal benchmark; no profiler and no production edits."""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import sys
import time
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("variant", choices=["baseline", "candidate", "query", "production", "advance", "combined"])
    parser.add_argument("scenario")
    parser.add_argument("tag")
    parser.add_argument("--root", type=Path, default=Path(".tmp/fish-state-advance"))
    parser.add_argument("--trace", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    integration = root / (args.variant + "-igess-src")
    sys.path.insert(0, str(integration if integration.exists() else root / "igess-src"))
    import yaml
    from igess.authoring.service import AuthoringService
    from igess.outputs import OutputWriter
    from igess.reporting.static import generate_static_report
    from igess.fish_source_runtime import FishSourceRuntime

    # Observe an existing public response; no extra queries, clocks or RNG use.
    # The final formal query supersedes any preparation/readiness observation.
    last_observation = None
    trace = []
    request = FishSourceRuntime.request

    def observe_value(value, include_luck):
        nonlocal last_observation
        last_observation = value
        if args.trace:
            trace.append({"includeLuck": include_luck, "state_sha256": hashlib.sha256(
                json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()})

    def observed_request(self, payload, **kwargs):
        value = request(self, payload, **kwargs)
        if payload["op"] == "query":
            observe_value(value, payload.get("includeLuck"))
        return value

    FishSourceRuntime.request = observed_request
    observe = getattr(FishSourceRuntime, "observe", None)
    if observe is not None:
        def observed_state(self, **kwargs):
            value = observe(self, **kwargs)
            observe_value(value, kwargs.get("include_luck"))
            return value
        FishSourceRuntime.observe = observed_state

    project = root / (args.variant + "-project")
    if not project.exists():
        shutil.copytree(root / "project", project)
        config_path = project / "economy.yaml"
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        config["engine"]["source_runtime"].update(
            project_root=(root / (args.variant + "-source")).as_posix(),
            data_root=(root / "baseline-source/igess_export/json").as_posix(),
        )
        config_path.write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")
    timings: dict[str, float] = {}

    def output_writer(*a, **kw):
        start = time.perf_counter()
        result = OutputWriter.write_all(*a, **kw)
        timings["artifacts"] = time.perf_counter() - start
        return result

    def report_writer(*a, **kw):
        start = time.perf_counter()
        result = generate_static_report(*a, **kw)
        timings["report"] = time.perf_counter() - start
        return result

    start = time.perf_counter()
    response = AuthoringService(project, output_writer=output_writer,
                                report_writer=report_writer).simulate(args.scenario)
    timings["total"] = time.perf_counter() - start
    payload = {"variant": args.variant, "scenario": args.scenario, "tag": args.tag,
               "python": sys.version, "platform": platform.platform(),
               "timings": timings, "response": response.to_payload()}
    if args.trace:
        payload["observation_trace"] = trace
        payload["diagnostic_only"] = True
    if response.ok:
        output = Path(response.result["output_dir"])
        manifest = json.loads((output / "run_manifest.json").read_text(encoding="utf-8"))
        payload["source_runtime"] = manifest["source_runtime"]
        assert last_observation is not None
        observation_file = output.parent / "final_observation.json"
        observation_file.write_text(json.dumps(last_observation, sort_keys=True), encoding="utf-8")
        payload["final_observation"] = str(observation_file)
    results = Path(__file__).parent / "results"
    results.mkdir(exist_ok=True)
    path = results / f"{args.tag}-{args.variant}-{args.scenario}.json"
    if path.exists():
        raise FileExistsError(path)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": response.ok, "timings": timings, "result": dict(response.result)},
                     ensure_ascii=False), flush=True)
    if not response.ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
