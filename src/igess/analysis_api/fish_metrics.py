"""Fish observations use the same growth facts as the static report."""
from __future__ import annotations

from typing import Any
from dataclasses import replace
from decimal import Decimal, localcontext

from ..reporting.loader import ReportData
from ..reporting.source_fish import build_source_projection
from .contracts import AnalysisError
from .metrics import MetricDefinition, MetricQuery, decimal, precision, find_definition, metric_value, validate_query, window

CATEGORIES = ("treasure_beast", "torpedo", "barbell", "fish_hall", "strength_rebirth",
              "trash_man_rebirth", "breakthrough_funding", "normal_codex_completed", "gun_owned",
              "gun_upgraded", "fish_tide_unlocked", "new_fish_species", "new_fish_variant", "fish_pool")
COLLECTION = {"normal_codex_completed", "gun_owned", "gun_upgraded", "fish_tide_unlocked",
              "new_fish_species", "new_fish_variant"}


def categories(row: dict[str, Any]) -> list[str]:
    return row.get("progression_categories", [row["progression_category"]])


def select_growth(data: ReportData, query: MetricQuery) -> dict[str, Any]:
    start, end = window(data, query.profile_id)
    scope = data.manifest.get("source_profiles", {}).get(query.profile_id, {})
    growth = build_source_projection(data)["persistent"]["profiles"][query.profile_id]
    selected = query.dimensions.get("categories", list(CATEGORIES))
    if (not isinstance(selected, list) or not selected or any(not isinstance(c, str) or c not in CATEGORIES for c in selected)
            or len(selected) != len(set(selected))):
        raise AnalysisError("invalid_selector", "Unknown or duplicate growth categories")
    periods = [key for key in ("day", "week", "through_day") if key in query.dimensions]
    if len(periods) > 1:
        raise AnalysisError("invalid_selector", "Select at most one period")
    left, right, bounded = start, end, False
    if periods:
        key = periods[0]
        period = query.dimensions[key]
        if type(period) is not int or period < 1:
            raise AnalysisError("invalid_selector", "Periods are positive integers")
        size = 604800 if key == "week" else 86400
        left = 0 if key == "through_day" else (period - 1) * size
        right, bounded = period * size, True
    complete = start <= left and end >= right
    reasons = []
    if not complete:
        reasons.append("Requested period is not fully observed")
    if set(selected) & COLLECTION:
        baseline = scope.get("collection_growth", {})
        collection_complete = baseline.get("version") == 1 or (start == 0 and growth["collection_coverage"]["first_species_complete"])
        if not collection_complete:
            complete = False
            reasons.append("Collection baseline/records incomplete")
    if "fish_pool" in selected and not growth.get("pool_coverage", {}).get("recorded", False):
        complete = False
        reasons.append("Pool growth not recorded")
    rows = [r for r in growth["rows"] if set(categories(r)) & set(selected)
            and left <= r["wall_time_seconds"] and (r["wall_time_seconds"] < right if bounded else r["wall_time_seconds"] <= right)]
    return {"rows": rows, "growth": growth, "selected": selected, "complete": complete,
            "reason": "; ".join(reasons), "requested_start_seconds": left, "requested_end_seconds": right,
            "scope": scope, "start": start, "end": end}


def growth_evidence(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"artifact": "events.json", "event_identity": r.get("event_identity", r["item_id"]),
             "source_event_kind": r["source_event_kind"], "wall_time_seconds": r["wall_time_seconds"],
             "display_name": r.get("display_name"), "categories": categories(r)} for r in rows[:100]]


class FishMetrics:
    def describe(self) -> list[MetricDefinition]:
        return [MetricDefinition("growth.count", "Distinct observed growth events", "count", "integer",
                                 ("categories", "day", "week", "through_day")),
                MetricDefinition("growth.labels", "Growth category labels (may overlap)", "count", "integer",
                                 ("categories", "day", "week", "through_day")),
                MetricDefinition("growth.score", "Explicitly weighted growth stimulus", "points", "decimal",
                                 ("categories", "day", "week", "through_day", "scoring", "weights", "event_weight")),
                MetricDefinition("growth.node_seconds", "Observed growth node time", "seconds", "integer",
                                 ("identity", "categories"), ("wall", "online"), ("segment", "lifecycle")),
                *[MetricDefinition("growth." + metric, name, "seconds", "integer", ("categories",), ("online",))
                  for metric, name in (("first_wait", "First growth wait"), ("max_interval", "Longest adjacent growth interval"),
                                       ("tail_wait", "Tail growth wait"), ("max_gap", "Longest online growth gap"))]]

    def extract(self, data: ReportData, query: MetricQuery) -> dict[str, Any]:
        definition = find_definition(self, query.metric_id)
        validate_query(definition, query, data)
        selection = query
        if query.metric_id == "growth.node_seconds" and "categories" not in query.dimensions:
            identity = query.dimensions.get("identity", "")
            node_category = identity.split(":", 1)[0] if isinstance(identity, str) else ""
            aliases = {"fish_collection": ["new_fish_species", "new_fish_variant"],
                       "fish_pool_entered": ["fish_pool"], "treasure_beast_unlocked": ["treasure_beast"],
                       "owned_torpedo_count": ["torpedo"], "owned_barbell_count": ["barbell"],
                       "fish_hall_level": ["fish_hall"], "strength_rebirth_count": ["strength_rebirth"],
                       "trash_man_rebirth_count": ["trash_man_rebirth"], "target_realm_id": ["breakthrough_funding"]}
            relevant = [node_category] if node_category in CATEGORIES else aliases.get(node_category)
            if relevant:
                selection = replace(query, dimensions={**query.dimensions, "categories": relevant})
        chosen = select_growth(data, selection)
        rows = chosen["rows"]
        if query.metric_id == "growth.node_seconds":
            return self._node(data, query, definition, chosen)
        if query.time_basis == "online":
            return self._gap(data, query, definition, chosen)
        value = len(rows) if query.metric_id == "growth.count" else sum(
            len(set(categories(r)) & set(chosen["selected"])) for r in rows)
        if query.metric_id == "growth.score":
            value = self._score(query, chosen)
        result = metric_value(definition, query, data, value, complete=chosen["complete"],
                              reason=chosen["reason"], evidence=growth_evidence(rows))
        result["coverage"].update({k: chosen[k] for k in ("requested_start_seconds", "requested_end_seconds")})
        result["evidence_selection"] = {"dimensions": query.dimensions, "matched_count": len(rows), "truncated": len(rows) > 100}
        return result

    @staticmethod
    def _score(query, chosen):
        dimensions = query.dimensions
        mode = dimensions.get("scoring")
        if mode == "per_label":
            weights = dimensions.get("weights")
            if (not isinstance(weights, dict) or set(weights) != set(chosen["selected"])
                    or "event_weight" in dimensions):
                raise AnalysisError("invalid_selector", "Declare exactly one weight per selected category")
            parsed = {key: decimal(value) for key, value in weights.items()}
            if any(value < 0 for value in parsed.values()):
                raise AnalysisError("invalid_selector", "Weights must be nonnegative")
            terms = [parsed[c] for row in chosen["rows"] for c in categories(row) if c in parsed]
        elif mode == "per_event":
            if "event_weight" not in dimensions or "weights" in dimensions:
                raise AnalysisError("invalid_selector", "Declare one explicit event weight")
            weight = decimal(dimensions["event_weight"])
            if weight < 0:
                raise AnalysisError("invalid_selector", "Weight must be nonnegative")
            terms = [weight] * len(chosen["rows"])
        else:
            raise AnalysisError("invalid_selector", "Explicit per_label or per_event scoring is required")
        with localcontext() as context:
            context.prec = precision(terms)
            return str(sum(terms, Decimal(0)))

    def _gap(self, data, query, definition, chosen):
        rows, scope = chosen["rows"], chosen["scope"]
        initial = scope.get("initial_active_time_seconds")
        known = isinstance(initial, int) and isinstance(scope.get("initial_online"), bool)
        if not known:
            return metric_value(definition, query, data, status="not_recorded", complete=False,
                                reason="Initial online state/time not recorded")
        active = chosen["growth"]["summary"]["active_duration_seconds"]
        times = [r["active_time_seconds"] for r in rows]
        first = times[0] - initial if times else active
        tail = initial + active - times[-1] if times else active
        adjacent = max((b - a for a, b in zip(times, times[1:])), default=None)
        values = {"growth.first_wait": first, "growth.tail_wait": tail,
                  "growth.max_interval": adjacent, "growth.max_gap": max(first, tail, adjacent or 0)}
        value = values[query.metric_id]
        boundaries = []
        if rows:
            if query.metric_id == "growth.first_wait" or (query.metric_id == "growth.max_gap" and value == first):
                boundaries = [rows[0]]
            elif query.metric_id == "growth.tail_wait" or (query.metric_id == "growth.max_gap" and value == tail):
                boundaries = [rows[-1]]
            elif adjacent is not None:
                index = max(range(len(times) - 1), key=lambda i: times[i + 1] - times[i])
                boundaries = rows[index:index + 2]
        evidence = growth_evidence(boundaries)
        evidence.append({"artifact": "events.json", "pointer": "", "selection": "online session boundaries"})
        evidence.append({"artifact": "run_manifest.json", "pointer": "/source_profiles", "selection": "initial online state"})
        result = metric_value(definition, query, data, value, status="recorded" if value is not None else "not_applicable",
                              complete=chosen["complete"], reason=chosen["reason"], evidence=evidence)
        result["evidence_selection"] = {"rule": query.metric_id + " determining boundaries (first maximum on ties)",
                                        "observed_event_count": len(rows), "dimensions": query.dimensions,
                                        "matched_count": len(boundaries), "truncated": False}
        return result

    def _node(self, data, query, definition, chosen):
        identity = query.dimensions.get("identity")
        if not isinstance(identity, str) or not identity:
            raise AnalysisError("invalid_selector", "Node requires a nonempty identity")
        scope = chosen["scope"]
        field = "online_time_seconds" if query.time_basis == "online" else "time_seconds"
        if query.scope == "lifecycle":
            records = scope.get("lifecycle_gun_milestones", [])
            if isinstance(records, dict):
                records = list(records.values())
            saved = scope.get("first_times", {}).get(identity)
            if saved is None:
                saved = next((r for r in records if r.get("identity") == identity), None)
            if saved is not None and saved.get(field) is not None:
                return metric_value(definition, query, data, int(saved[field]),
                                    evidence=[{"artifact": "run_manifest.json", "identity": identity,
                                               "source": "source_profiles lifecycle records"}])
            if chosen["start"] != 0:
                return metric_value(definition, query, data, status="not_recorded", complete=False,
                                    reason="Lifecycle first-time evidence not recorded")
        if query.time_basis == "online" and ("initial_active_time_seconds" not in scope or "initial_online" not in scope):
            return metric_value(definition, query, data, status="not_recorded", complete=False,
                                reason="Initial online state/time not recorded")
        matched = [r for r in chosen["rows"] if identity in (r.get("event_identity"), r["item_id"], r["metric_id"])]
        matched.sort(key=lambda r: r["wall_time_seconds"])
        row = matched[0] if matched else None
        value = row["active_time_seconds" if query.time_basis == "online" else "wall_time_seconds"] if row else None
        result = metric_value(definition, query, data, value, status="recorded" if row else "not_reached",
                              complete=chosen["complete"], reason=chosen["reason"], evidence=growth_evidence(matched[:1]))
        if query.time_basis == "online":
            result["coverage"]["online_start_seconds"] = scope["initial_active_time_seconds"]
            result["coverage"]["online_end_seconds"] = scope["initial_active_time_seconds"] + chosen["growth"]["summary"]["active_duration_seconds"]
        return result
