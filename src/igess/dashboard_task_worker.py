"""Private, source-loading entry point. Run by filename before importing IGESS."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import sys
import traceback


class _CurrentSource(importlib.machinery.SourceFileLoader):
    def get_code(self, fullname):
        return self.source_to_code(self.get_data(self.path), self.path)


class _SourceFinder:
    @classmethod
    def find_spec(cls, fullname, path=None, target=None):
        if fullname != "igess" and not fullname.startswith("igess."):
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec and isinstance(spec.loader, importlib.machinery.SourceFileLoader):
            spec.loader = _CurrentSource(fullname, spec.origin)
        return spec


def write_result(path, payload):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def execute(request):
    from igess.dashboard import create_dashboard_context
    from igess.authoring.response import CommandResponse

    context = request["context"]
    service, config, tables = create_dashboard_context(
        context["project"], context["config"], context["tables"], context["runs_root"],
        strict_authoring=context["authoring"],
    )
    if service.is_authoring != context["authoring"]:
        raise ValueError("Project mode changed; reload the Dashboard service")
    from igess.run_registry import RunRegistry

    class TaskRegistry(RunRegistry):
        def write_status(self, run_dir, **kwargs):
            claim = Path(request["claim_path"])
            if kwargs.get("status") == "running" and not claim.exists():
                run_dir = Path(run_dir)
                if run_dir.parent.resolve() != self.runs_root.resolve():
                    raise ValueError("Task registration is outside its history root")
                if (run_dir / "run_status.json").exists():
                    raise ValueError("Task cannot take ownership of an existing run")
                run_dir.mkdir(parents=True, exist_ok=True)
                info = run_dir.lstat()
                if run_dir.is_symlink() or getattr(info, "st_file_attributes", 0) & 0x400:
                    raise ValueError("Task registration cannot follow a directory link")
                write_result(claim, {"task_id": request["task_id"], "run_id": run_dir.name,
                                     "device": info.st_dev, "inode": info.st_ino})
            return super().write_status(run_dir, **kwargs)

    registry = TaskRegistry(service.registry.runs_root, service.registry.read_roots)
    service.registry = registry
    if service.authoring_service is not None:
        service.authoring_service.bind_run_registry(registry)
    operation = request["operation"]
    if operation == "check":
        if service.is_authoring:
            payload = service.model_status().to_payload()
            return {"status": payload, "authoring": payload}
        lint = service.lint(config, tables)
        try:
            scenarios = list(service.available_scenarios(config))
            scenario_error = ""
        except Exception as error:
            scenarios, scenario_error = [], str(error)
        return {"status": {"ok": lint.ok, "message": lint.message},
                "authoring": None, "scenarios": scenarios, "scenario_error": scenario_error}
    scenario = request["scenario"]
    if operation == "advise":
        result = service.run_advice(None if service.is_authoring else config,
                                    None if service.is_authoring else tables, scenario)
    elif operation == "simulate":
        result = (service.run_authoring_scenario(scenario) if service.is_authoring
                  else service.run_scenario(config, tables, scenario))
    else:
        raise ValueError("Unsupported Dashboard operation")
    if isinstance(result, CommandResponse):
        return {"state": "success" if result.ok else "failed", "message": result.message,
                "diagnostic": result.to_payload(), "run_id": result.result.get("run_id")}
    return {"state": result.status, "message": result.message, "run_id": result.run_id}


def main():
    request_path, result_path = map(Path, sys.argv[1:3])
    request = json.loads(request_path.read_text(encoding="utf-8"))
    write_result(request_path.with_name("ready.json"), {"task_id": request["task_id"], "pid": os.getpid()})
    if sys.stdin.readline().strip() != request["task_id"]:
        return 1  # The owning service closed before granting execution.
    # Path execution avoids importing the package before the source-only loader.
    sys.path[0] = str(Path(__file__).resolve().parent.parent)
    sys.meta_path.insert(0, _SourceFinder)
    try:
        if request["version"] != 1:
            raise ValueError("Unsupported Dashboard task protocol")
        outcome = execute(request)
        write_result(result_path, {"version": 1, "task_id": request["task_id"], "outcome": outcome})
    except Exception:
        traceback.print_exc()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
