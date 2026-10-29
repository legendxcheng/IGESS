from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import yaml

from ..authoring.response import CommandResponse
from ..run_registry import RunRecord, RunRegistry
from .contracts import AnalysisError
from .snapshot import RunSnapshot, safe_path
from .metrics import MetricQuery, default_providers, definition_payload, find_definition


class AnalysisService:
    """No model loading, recovery, simulation or writes during construction/queries."""

    def __init__(self, project: str | Path, *, runs_root: str | Path | None = None, providers=None):
        self.project = Path(project).absolute()
        self.registry = RunRegistry(runs_root or self.project / "runs",
                                   read_roots=[self.project / ".igess/runs"])
        self.providers = default_providers() if providers is None else providers

    def execute(self, command: str, **options: Any) -> CommandResponse:
        operations = {"runs.list": self.list_runs, "runs.show": self.get_run,
                      "runs.artifacts": self.artifacts, "metrics.describe": self.describe_metrics,
                      "metrics.extract": self.extract_metrics, "targets.evaluate": self.evaluate_targets}
        try:
            if command not in operations:
                raise AnalysisError("unknown_command", command)
            payload = operations[command](**options)
            return CommandResponse(command, True, "ok", "Analysis complete", result=payload)
        except AnalysisError as error:
            return CommandResponse(command, False, error.code, str(error), details=error.details)
        except (OSError, ValueError, TypeError, KeyError, yaml.YAMLError) as error:
            return CommandResponse(command, False, "analysis_invalid", str(error))

    def list_runs(self, *, scenario_id=None, status=None, engine_id=None, kind="formal",
                  limit=50, offset=0) -> dict[str, Any]:
        if type(limit) is not int or not 1 <= limit <= 1000 or type(offset) is not int or offset < 0:
            raise AnalysisError("invalid_pagination", "limit must be 1..1000 and offset nonnegative")
        if kind not in {"formal", "smoke", "all"}:
            raise AnalysisError("invalid_filter", "Unknown run kind")
        rows = [r for r in self.registry.list_runs()
                if (scenario_id is None or r.scenario_id == scenario_id)
                and (status is None or r.status == status)
                and (engine_id is None or r.engine_id == engine_id)
                and (kind == "all" or r.kind == kind)]
        rows.sort(key=_sort_key, reverse=True)
        return {"schema_version": 1, "items": [_record(r) for r in rows[offset:offset + limit]],
                "total": len(rows), "offset": offset, "limit": limit,
                "has_more": offset + limit < len(rows)}

    def _record(self, run_id: str) -> RunRecord:
        for record in self.registry.list_runs():
            if record.run_id == run_id:
                return record
        raise AnalysisError("run_not_found", "Registered run not found", run_id=run_id)

    def get_run(self, run_id: str) -> dict[str, Any]:
        record = self._record(run_id)
        snapshot = RunSnapshot(record)
        snapshot.verify()
        return {"schema_version": 1, **_record(record), "manifest": snapshot.manifest or None,
                "identity_complete": all(snapshot.manifest.get(k) for k in
                    ("scenario_id", "model_digest", "engine_id"))}

    def artifacts(self, run_id: str) -> dict[str, Any]:
        record = self._record(run_id)
        snapshot = RunSnapshot(record)
        items = []
        for name in dict.fromkeys(["run_manifest.json", *snapshot.manifest.get("artifacts", [])]):
            path = snapshot.artifact_path(name)
            items.append({"name": name, "role": "simulation", "source": "manifest",
                          "path": str(path), "exists": path.is_file()})
        for name, path in (("run_status.json", record.status_path), ("report", record.report_index)):
            safe_path(record.run_dir, path)
            items.append({"name": name, "role": name, "source": "registry",
                          "path": str(path), "exists": path.is_file()})
        diagnostic = self.project / ".igess/diagnostics" / (record.run_id + ".json")
        safe_path(self.project, diagnostic)
        if diagnostic.is_file():
            items.append({"name": "diagnostic", "role": "development_diagnostic", "source": "project",
                          "path": str(diagnostic), "exists": True})
        snapshot.verify()
        return {"schema_version": 1, "run_id": run_id, "items": items}

    def _provider(self, engine_id):
        if engine_id not in self.providers:
            raise AnalysisError("engine_unsupported", "No metric provider", engine_id=engine_id)
        return self.providers[engine_id]

    def describe_metrics(self, engine_id: str) -> dict[str, Any]:
        result = {"schema_version": 1, "engine_id": engine_id,
                  "metrics": [definition_payload(d) for d in self._provider(engine_id).describe()]}
        if engine_id == "fish_source":
            from .fish_metrics import CATEGORIES
            result["categories"] = list(CATEGORIES)
        return result

    def extract_metrics(self, run_id: str, metric_id: str, profile_id: str,
                        dimensions=None, time_basis="wall", scope="segment", aggregation="value"):
        snapshot = RunSnapshot(self._record(run_id))
        data = snapshot.report_data()
        provider = self._provider(data.manifest.get("engine_id", snapshot.record.engine_id or "generic"))
        query = MetricQuery(metric_id, profile_id, {} if dimensions is None else dimensions, time_basis, scope, aggregation)
        value = provider.extract(data, query)
        self._evidence(snapshot, value)
        snapshot.verify()
        return {"schema_version": 1, **snapshot.provenance(), "metrics": [value]}

    @staticmethod
    def _evidence(snapshot, value):
        from .snapshot import digest
        for evidence in value["evidence"]:
            content = snapshot.read(snapshot.artifact_path(evidence["artifact"]))
            evidence["run_id"] = snapshot.record.run_id
            if content is not None:
                evidence["content_digest"] = digest(content)

    def evaluate_targets(self, run_id: str, target_file: str | Path, out: str | Path | None = None):
        from .targets import TargetSet, evaluate, summarize
        targets = TargetSet(target_file)
        snapshot = RunSnapshot(self._record(run_id))
        data = snapshot.report_data()
        provider = self._provider(data.manifest.get("engine_id", snapshot.record.engine_id or "generic"))
        results = []
        for target in targets.targets:
            try:
                definition = find_definition(provider, target.query.metric_id)
                if target.unit != definition.unit:
                    raise AnalysisError("unit_mismatch", "Target unit does not match metric")
                metric = provider.extract(data, target.query)
                self._evidence(snapshot, metric)
                results.append(evaluate(target, metric))
            except AnalysisError as error:
                raise AnalysisError("invalid_target", str(error), target_id=target.target_id,
                                    cause=error.code) from error
        snapshot.verify()
        targets.verify()
        result = {"schema_version": 1, **snapshot.provenance(), "target_set": targets.provenance(),
                  "generated_at": datetime.now(timezone.utc).isoformat(), **summarize(results)}
        if out is not None:
            from .export import export_evaluation
            result["exports"] = export_evaluation(result, out, project=self.project,
                history_roots=self.registry.read_roots, target_path=targets.path)
        return result


def _record(record: RunRecord) -> dict[str, Any]:
    return {**{name: str(value) if isinstance(value, Path) else value
               for name, value in vars(record).items()},
            **{key: getattr(record, key, None) for key in ("started_at", "finished_at", "duration_seconds")}}


def _sort_key(record: RunRecord) -> tuple[bool, float, str]:
    try:
        value = datetime.fromisoformat(getattr(record, "started_at", None) or "")
        stamp = value.timestamp() if value.tzinfo else float("-inf")
    except ValueError:
        stamp = float("-inf")
    return stamp != float("-inf"), stamp, record.run_id
