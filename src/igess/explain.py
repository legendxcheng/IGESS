from __future__ import annotations

from pathlib import Path

from .reporting.loader import load_report_data


def explain_event(run_dir: str | Path, event: str) -> dict[str, str | int]:
    data = load_report_data(run_dir)
    index = int(event)
    try:
        selected = data.events[index]
    except IndexError as exc:
        raise ValueError(f"Event {event} not found") from exc
    details = selected.get("details", {})
    source = ""
    if isinstance(details, dict) and details.get("source_workbook"):
        source = f"{details.get('source_workbook')}:{details.get('source_row')}"
    return {
        "event_index": index,
        "scenario_id": str(selected.get("scenario_id")),
        "profile_id": str(selected.get("profile_id")),
        "time_seconds": int(selected.get("time_seconds", 0)),
        "kind": str(selected.get("kind")),
        "item_id": str(selected.get("item_id")),
        "source": source,
        "trace": str(details.get("formula_trace", "")) if isinstance(details, dict) else "",
    }


def format_event_explanation(explanation: dict[str, str | int]) -> str:
    lines = [
        f"Event {explanation['event_index']}",
        "",
        f"- Scenario: {explanation['scenario_id']}",
        f"- Profile: {explanation['profile_id']}",
        f"- Time: {explanation['time_seconds']}s",
        f"- Kind: {explanation['kind']}",
        f"- Item: {explanation['item_id']}",
        f"- Source: {explanation['source'] or 'n/a'}",
        f"- Trace: {explanation['trace'] or 'n/a'}",
        "",
    ]
    return "\n".join(lines)
