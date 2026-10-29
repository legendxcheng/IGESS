"""Validate target documents and evaluate already-extracted measurements."""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any

import yaml

from .contracts import AnalysisError
from .metrics import MetricQuery, decimal, precision
from .snapshot import digest, json_value, read_capture


class TargetLoader(yaml.SafeLoader):
    pass


def _yaml_mapping(loader, node):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if key in result:
            raise AnalysisError("invalid_target", "Duplicate YAML key")
        result[key] = loader.construct_object(value_node)
    return result


TargetLoader.add_constructor("tag:yaml.org,2002:map", _yaml_mapping)
# Preserve literal decimal precision, instead of routing YAML decimals through float.
def _yaml_decimal(loader, node):
    return loader.construct_scalar(node)


TargetLoader.add_constructor("tag:yaml.org,2002:float", _yaml_decimal)


@dataclass(frozen=True)
class Target:
    target_id: str
    query: MetricQuery
    unit: str
    operator: str
    bounds: tuple[Decimal, ...]
    tolerance: Decimal
    raw: dict[str, Any]


class TargetSet:
    def __init__(self, path: str | Path):
        self.path = Path(path).absolute()
        content, self.identity = read_capture(self.path.parent, self.path)
        if content is None:
            raise AnalysisError("target_missing", "Target file not found")
        self.content: bytes = content
        if self.path.suffix.lower() == ".json":
            document = json_value(self.content, dict)
        elif self.path.suffix.lower() in {".yaml", ".yml"}:
            document = yaml.load(self.content.decode("utf-8-sig"), Loader=TargetLoader)
        else:
            raise AnalysisError("invalid_target", "Expected JSON or YAML target file")
        if not isinstance(document, dict) or type(document.get("schema_version")) is not int or document["schema_version"] != 1:
            raise AnalysisError("invalid_target", "Target schema_version must be 1")
        for key in ("target_set_id", "version", "source"):
            if not isinstance(document.get(key), str) or not document[key]:
                raise AnalysisError("invalid_target", "Target metadata must be nonempty text", field=key)
        entries = document.get("targets")
        if not isinstance(entries, list) or not entries:
            raise AnalysisError("invalid_target", "Target set must be nonempty")
        self.document = document
        self.targets: list[Target] = []
        seen = set()
        for entry in entries:
            identity = entry.get("target_id") if isinstance(entry, dict) else None
            try:
                item = self._parse(entry)
                if item.target_id in seen:
                    raise AnalysisError("invalid_target", "Duplicate target ID")
                seen.add(item.target_id)
                self.targets.append(item)
            except (AnalysisError, KeyError, TypeError, ValueError) as error:
                raise AnalysisError("invalid_target", str(error), target_id=identity) from error

    @staticmethod
    def _parse(entry) -> Target:
        required = {"target_id", "metric_id", "profile_id", "dimensions", "unit", "time_basis",
                    "scope", "aggregation", "operator", "value"}
        if not isinstance(entry, dict) or required - set(entry) or set(entry) - required - {"tolerance"}:
            raise AnalysisError("invalid_target", "Missing or unknown target fields")
        for key in required - {"dimensions", "value"}:
            if not isinstance(entry[key], str) or not entry[key]:
                raise AnalysisError("invalid_target", "Expected nonempty text: " + key)
        if not isinstance(entry["dimensions"], dict):
            raise AnalysisError("invalid_target", "Dimensions must be an object")
        operator = entry["operator"]
        if operator not in {"eq", "gte", "lte", "between"}:
            raise AnalysisError("invalid_target", "Unsupported comparison operator")
        values = entry["value"] if operator == "between" else [entry["value"]]
        if not isinstance(values, list) or len(values) != (2 if operator == "between" else 1):
            raise AnalysisError("invalid_target", "Invalid comparison bounds")
        bounds = tuple(decimal(v) for v in values)
        tolerance = decimal(entry.get("tolerance", "0"))
        if tolerance < 0 or (len(bounds) == 2 and bounds[0] > bounds[1]):
            raise AnalysisError("invalid_target", "Invalid range or negative tolerance")
        query = MetricQuery(entry["metric_id"], entry["profile_id"], entry["dimensions"],
                            entry["time_basis"], entry["scope"], entry["aggregation"])
        return Target(entry["target_id"], query, entry["unit"], operator, bounds, tolerance, entry)

    def verify(self):
        if read_capture(self.path.parent, self.path) != (self.content, self.identity):
            raise AnalysisError("input_changed", "Target file changed during evaluation")

    def provenance(self):
        normalized = json.dumps(self.document, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return {"target_set_id": self.document["target_set_id"], "version": self.document["version"],
                "source": self.document["source"], "source_digest": self.document.get("source_digest"),
                "file_digest": digest(self.content), "normalized_digest": digest(normalized.encode("utf-8")),
                "definition": self.document}


def evaluate(target: Target, metric: dict[str, Any]) -> dict[str, Any]:
    result = {"target_id": target.target_id, "target": target.raw, "actual": metric,
              "status": "not_evaluable", "reason": metric["reason"]}
    if not metric["coverage"]["complete"]:
        result["reason"] = metric["reason"] or "Requested observation is incomplete"
        return result
    status = metric["value_status"]
    if status == "not_applicable":
        result["status"] = "not_applicable"
        return result
    if status == "not_reached":
        deadline = target.bounds[-1]
        end_key = "online_end_seconds" if target.query.time_basis == "online" else "end_seconds"
        start_key = "online_start_seconds" if target.query.time_basis == "online" else "start_seconds"
        observed_end = metric["coverage"].get(end_key)
        observed_start = metric["coverage"].get(start_key)
        if target.operator in {"lte", "between"} and observed_end is not None and observed_start is not None:
            with localcontext() as ctx:
                ctx.prec = precision([*target.bounds, target.tolerance, decimal(observed_end)])
                if decimal(observed_start) <= deadline and decimal(observed_end) >= deadline + target.tolerance:
                    result.update(status="failed", reason="Node not reached by the covered deadline")
        return result
    if status != "recorded" or "value" not in metric:
        return result
    value = decimal(metric["value"])
    with localcontext() as ctx:
        ctx.prec = precision([value, *target.bounds, target.tolerance])
        low, high, tolerance = target.bounds[0], target.bounds[-1], target.tolerance
        passed = {"eq": abs(value - low) <= tolerance,
                  "gte": value >= low - tolerance, "lte": value <= high + tolerance,
                  "between": low - tolerance <= value <= high + tolerance}[target.operator]
        result["status"] = "passed" if passed else "failed"
        if target.operator == "between":
            result["delta"] = {"lower": str(value - low), "upper": str(value - high)}
        else:
            result["delta"] = str(value - low)
    return result


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(row["status"] for row in results)
    status = ("failed" if counts["failed"] else "incomplete" if counts["not_evaluable"]
              else "passed" if counts["passed"] else "not_applicable")
    return {"evaluation_status": status, "targets": results,
            "summary": {"total": len(results), "evaluated": counts["passed"] + counts["failed"],
                        **{key: counts[key] for key in ("passed", "failed", "not_evaluable", "not_applicable")}}}
