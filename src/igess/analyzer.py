from __future__ import annotations

from collections import Counter

from .schema import SimulationResult


class Analyzer:
    @classmethod
    def markdown(cls, result: SimulationResult) -> str:
        profiles = sorted({row.profile_id for row in result.timeline})
        purchases = Counter(event.profile_id for event in result.events if event.kind.startswith("buy_"))
        event_counts = Counter(event.kind for event in result.events)
        lines = [
            "# Incremental Economy Analysis",
            "",
            f"Scenario: `{result.scenario_id}`",
            "",
            "## Profiles",
            "",
        ]
        for profile in profiles:
            final_rows = [row for row in result.timeline if row.profile_id == profile]
            final = final_rows[-1]
            lines.extend(
                [
                    f"### {profile}",
                    "",
                    f"- Final time: {final.time_seconds}s",
                    f"- Final resources: {final.resources}",
                    f"- Generators owned: {final.generators_owned}",
                    f"- Upgrades purchased: {final.upgrades_purchased}",
                    f"- Purchase events: {purchases[profile]}",
                    "",
                ]
            )
        lines.extend(
            [
                "## Event Counts",
                "",
                f"- Total events: {len(result.events)}",
                f"- Timeline rows: {len(result.timeline)}",
                "",
                "## Purchase Timeline",
                "",
            ]
        )
        cls._append_events(lines, result, lambda kind: kind.startswith("buy_"))
        lines.extend(["## Unlock Timeline", ""])
        cls._append_events(lines, result, lambda kind: kind.startswith("unlock_") or kind == "milestone_reward")
        lines.extend(["## Prestige Timeline", ""])
        cls._append_events(lines, result, lambda kind: kind == "prestige_reset")
        lines.extend(
            [
                "## Bottleneck Report",
                "",
                f"- Offline reward events: {event_counts['offline_reward']}",
                f"- Milestone reward events: {event_counts['milestone_reward']}",
                f"- Prestige reset events: {event_counts['prestige_reset']}",
                "",
            ]
        )
        return "\n".join(lines)

    @classmethod
    def _append_events(cls, lines: list[str], result: SimulationResult, predicate) -> None:
        matched = [event for event in result.events if predicate(event.kind)]
        if not matched:
            lines.extend(["- None", ""])
            return
        for event in matched[:20]:
            lines.append(
                f"- `{event.time_seconds}s` `{event.profile_id}` {event.kind}: `{event.item_id}`"
            )
        if len(matched) > 20:
            lines.append(f"- ... {len(matched) - 20} more")
        lines.append("")
