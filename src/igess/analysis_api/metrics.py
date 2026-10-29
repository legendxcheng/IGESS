"""Metric definitions and engine-owned projections of frozen report data."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any, Protocol

from ..reporting.loader import ReportData
from .contracts import AnalysisError


def decimal(value: Any) -> Decimal:
    if isinstance(value, (bool, float)) or not isinstance(value, (str, int, Decimal)):
        raise AnalysisError("invalid_number", "Use integer or exact decimal string")
    try:
        number = Decimal(value)
    except InvalidOperation as error:
        raise AnalysisError("invalid_number", "Invalid decimal") from error
    if not number.is_finite() or abs(number.adjusted()) > 10000:
        raise AnalysisError("invalid_number", "Expected finite decimal within supported magnitude")
    return number


def precision(values: list[Decimal]) -> int:
    return max(80, max((v.adjusted() for v in values), default=0)
               - min((int(v.as_tuple().exponent) for v in values), default=0)
               + len(str(len(values))) + 8)


@dataclass(frozen=True)
class MetricDefinition:
    metric_id: str
    name: str
    unit: str
    value_type: str
    dimensions: tuple[str, ...] = ()
    time_bases: tuple[str, ...] = ("wall",)
    scopes: tuple[str, ...] = ("segment",)
    required_artifacts: tuple[str, ...] = ("timeline.json", "events.json")
    definition_version: int = 1
    aggregations: tuple[str, ...] = ("value",)
    coverage_requirement: str = "complete observation of selected window"


@dataclass(frozen=True)
class MetricQuery:
    metric_id: str
    profile_id: str
    dimensions: dict[str, Any]
    time_basis: str = "wall"
    scope: str = "segment"
    aggregation: str = "value"


def definition_payload(definition: MetricDefinition) -> dict[str, Any]:
    return asdict(definition)


def validate_query(definition: MetricDefinition, query: MetricQuery, data: ReportData) -> None:
    if not isinstance(query.dimensions, dict):
        raise AnalysisError("invalid_selector", "Dimensions must be an object")
    if query.profile_id not in data.profiles:
        raise AnalysisError("invalid_selector", "Unknown profile", profile_id=query.profile_id)
    if set(query.dimensions) - set(definition.dimensions):
        raise AnalysisError("invalid_selector", "Unsupported metric dimensions")
    if (query.time_basis not in definition.time_bases or query.scope not in definition.scopes
            or query.aggregation not in definition.aggregations):
        raise AnalysisError("invalid_selector", "Unsupported time basis, scope or aggregation")


def window(data: ReportData, profile: str) -> tuple[int, int]:
    rows = [row for row in data.timeline if row["profile_id"] == profile]
    if not rows:
        raise AnalysisError("artifact_missing", "No timeline for requested profile")
    return min(r["time_seconds"] for r in rows), max(r["time_seconds"] for r in rows)


def metric_value(definition: MetricDefinition, query: MetricQuery, data: ReportData,
                 value: Any = None, *, status="recorded", complete=True, reason="",
                 evidence: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    start, end = window(data, query.profile_id)
    item = {"metric_id": definition.metric_id, "definition_version": definition.definition_version,
            "profile_id": query.profile_id, "dimensions": query.dimensions, "unit": definition.unit,
            "value_type": definition.value_type, "value_status": status,
            "coverage": {"complete": complete, "start_seconds": start, "end_seconds": end},
            "time_basis": query.time_basis, "scope": query.scope, "reason": reason,
            "evidence": evidence or []}
    if status == "recorded" and value is not None:
        item["value"] = value
    return item


class MetricProvider(Protocol):
    def describe(self) -> list[MetricDefinition]: ...
    def extract(self, data: ReportData, query: MetricQuery) -> dict[str, Any]: ...


class GenericMetrics:
    def describe(self) -> list[MetricDefinition]:
        return [
            MetricDefinition("resource.final", "Final sampled resource balance", "resource", "decimal", ("resource",)),
            MetricDefinition("unlock.first_seconds", "First recorded unlock", "seconds", "integer", ("item",)),
            MetricDefinition("purchase.count", "Recorded purchases", "count", "integer", ("item",)),
            MetricDefinition("prestige.count", "Recorded prestige resets", "count", "integer"),
            MetricDefinition("payback.seconds", "Recorded payback estimate", "seconds", "decimal", ("item",),
                             required_artifacts=("payback.csv",)),
        ]

    def extract(self, data: ReportData, query: MetricQuery) -> dict[str, Any]:
        definition = find_definition(self, query.metric_id)
        validate_query(definition, query, data)
        selected = query.dimensions.get("resource" if query.metric_id == "resource.final" else "item")
        if query.metric_id in {"resource.final", "unlock.first_seconds", "payback.seconds"} and not isinstance(selected, str):
            raise AnalysisError("invalid_selector", "Metric requires a resource or item dimension")
        if selected is not None and (not isinstance(selected, str) or not selected):
            raise AnalysisError("invalid_selector", "Entity identifier must be nonempty text")
        rows = [(i, r) for i, r in enumerate(data.timeline) if r["profile_id"] == query.profile_id]
        if query.metric_id == "resource.final":
            index, row = max(rows, key=lambda pair: pair[1]["time_seconds"])
            amount = row.get("resources", {}).get(selected)
            return metric_value(definition, query, data, str(decimal(amount)) if amount is not None else None,
                status="recorded" if amount is not None else "not_recorded", complete=amount is not None,
                reason="" if amount is not None else "Resource absent from final sample",
                evidence=[{"artifact": "timeline.json", "pointer": f"/{index}/resources"}])
        if query.metric_id == "payback.seconds":
            matches = [(i, r) for i, r in enumerate(data.payback_rows) if r.get("profile_id") == query.profile_id
                       and f"{r.get('kind')}:{r.get('item_id')}" == selected]
            if not matches:
                return metric_value(definition, query, data, status="not_recorded", complete=False,
                                    reason="Payback estimate not recorded")
            index, row = matches[-1]
            amount = row.get("payback_seconds")
            if amount in ("Infinity", "", None):
                return metric_value(definition, query, data, status="not_applicable", reason="No finite payback")
            return metric_value(definition, query, data, str(decimal(amount)),
                                evidence=[{"artifact": "payback.csv", "row": index + 2}])
        kind = {"unlock.first_seconds": "unlock_", "purchase.count": "buy_", "prestige.count": "prestige_reset"}[query.metric_id]
        matches = [(i, e) for i, e in enumerate(data.events) if e["profile_id"] == query.profile_id
                   and (e["kind"] == kind if kind == "prestige_reset" else e["kind"].startswith(kind))
                   and (selected is None or f"{e['kind'].removeprefix(kind)}:{e['item_id']}" == selected)]
        if selected is not None and not matches and not _known_entity(data, query.profile_id, selected):
            return metric_value(definition, query, data, status="not_recorded", complete=False,
                                reason="Entity identity is absent from saved artifacts")
        evidence = [{"artifact": "events.json", "pointer": f"/{i}"} for i, _ in matches[:100]] or [
            {"artifact": "events.json", "pointer": "", "query": asdict(query), "matched_count": 0}]
        status = "not_reached" if query.metric_id == "unlock.first_seconds" and not matches else "recorded"
        value = min((e["time_seconds"] for _, e in matches), default=None) if query.metric_id == "unlock.first_seconds" else len(matches)
        item = metric_value(definition, query, data, value, status=status, evidence=evidence)
        item["evidence_selection"] = {"query": asdict(query), "matched_count": len(matches), "truncated": len(matches) > 100}
        return item


def _known_entity(data: ReportData, profile: str, identity: str) -> bool:
    for row in data.timeline:
        if row["profile_id"] != profile:
            continue
        if identity in {"generator:" + str(key) for key in row.get("generators_owned", {})}:
            return True
        if identity in {"upgrade:" + str(key) for key in row.get("upgrades_purchased", [])}:
            return True
    for event in data.events:
        if event["profile_id"] == profile and event["kind"].startswith(("buy_", "unlock_")):
            if f"{event['kind'].split('_', 1)[1]}:{event['item_id']}" == identity:
                return True
    return any(row.get("profile_id") == profile and f"{row.get('kind')}:{row.get('item_id')}" == identity
               for row in data.payback_rows)


def find_definition(provider: MetricProvider, metric_id: str) -> MetricDefinition:
    for item in provider.describe():
        if item.metric_id == metric_id:
            return item
    raise AnalysisError("unknown_metric", "Metric is not supported", metric_id=metric_id)


def default_providers() -> dict[str, MetricProvider]:
    from .fish_metrics import FishMetrics
    return {"generic": GenericMetrics(), "fish_source": FishMetrics()}
