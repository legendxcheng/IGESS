from __future__ import annotations

from collections import Counter

from .conditions import evaluate
from .human_numbers import format_human_number
from .numbers import SimNumber
from .modifiers import ModifierStack
from .schema import EconomyModel, SimulationResult, SimulationState, TimelineRow
from .trace import action_formula_trace, source_ref_label


class Analyzer:
    @classmethod
    def report(cls, result: SimulationResult, model: EconomyModel | None = None) -> dict:
        profiles = sorted({row.profile_id for row in result.timeline})
        event_counts = Counter(event.kind for event in result.events)
        purchase_events = [event for event in result.events if event.kind.startswith("buy_")]
        item_purchase_counts = Counter(
            f"{event.kind.removeprefix('buy_')}:{event.item_id}" for event in purchase_events
        )
        profile_summaries = {}
        for profile in profiles:
            final = cls._final_row(result, profile)
            profile_summaries[profile] = {
                "final_time_seconds": final.time_seconds,
                "final_resources": final.resources,
                "generators_owned": final.generators_owned,
                "upgrades_purchased": final.upgrades_purchased,
                "purchase_count": sum(
                    1 for event in purchase_events if event.profile_id == profile
                ),
            }

        report = {
            "scenario_id": result.scenario_id,
            "profile_summaries": profile_summaries,
            "event_counts": dict(sorted(event_counts.items())),
            "bottleneck_report": cls.bottleneck_report(result),
            "invalid_content_report": cls.invalid_content_report(result, model),
            "overpowered_content_report": cls.overpowered_content_report(item_purchase_counts),
        }
        report["payback_report"] = cls.payback_report(result, model) if model is not None else []
        return report

    @classmethod
    def markdown(cls, result: SimulationResult, model: EconomyModel | None = None) -> str:
        report = cls.report(result, model)
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
            final_resources = "{" + ", ".join(
                f"{resource_id!r}: {format_human_number(value)}"
                for resource_id, value in sorted(final.resources.items())
            ) + "}"
            lines.extend(
                [
                    f"### {profile}",
                    "",
                    f"- Final time: {format_human_number(final.time_seconds)}s",
                    f"- Final resources: {final_resources}",
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
                "## Payback Report",
                "",
            ]
        )
        payback = report.get("payback_report", [])
        if payback:
            for row in payback[:20]:
                lines.append(
                    f"- `{row['profile_id']}` {row['kind']} `{row['item_id']}`: "
                    f"{format_human_number(row['payback_seconds'])}s, "
                    f"source `{row['source_ref']}`"
                )
            if len(payback) > 20:
                lines.append(f"- ... {len(payback) - 20} more")
            lines.append("")
        else:
            lines.extend(["- Not generated; pass an EconomyModel to include payback.", ""])
        lines.extend(["## Invalid Content Report", ""])
        invalid = report["invalid_content_report"]
        lines.append(f"- Never purchased: {invalid['never_purchased']}")
        lines.append(f"- Never unlocked: {invalid['never_unlocked']}")
        lines.append("")
        lines.extend(["## Overpowered Content Report", ""])
        overpowered = report["overpowered_content_report"]
        if overpowered:
            for item in overpowered:
                lines.append(
                    f"- `{item['item_id']}` purchase share {item['purchase_share']}"
                )
        else:
            lines.append("- None")
        lines.append("")
        return "\n".join(lines)

    @classmethod
    def payback_report(cls, result: SimulationResult, model: EconomyModel) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for profile_id in sorted({row.profile_id for row in result.timeline}):
            state = cls._state_from_final_row(model, cls._final_row(result, profile_id))
            actions = cls._candidate_payback_actions(model, state)
            for action in actions:
                benefit = cls._profile_adjusted_action_benefit(model, profile_id, action, state)
                payback = "Infinity"
                if benefit > SimNumber.zero():
                    payback = (action.cost / benefit).to_decimal_string()
                rows.append(
                    {
                        "profile_id": profile_id,
                        "kind": action.kind.removeprefix("buy_"),
                        "item_id": action.item_id,
                        "cost": action.cost.to_decimal_string(),
                        "delta_cps": benefit.to_decimal_string(),
                        "payback_seconds": payback,
                        **model.source_details(action.kind, action.item_id),
                        "source_ref": source_ref_label(model, action.kind, action.item_id),
                        "formula_trace": action_formula_trace(model, action, state),
                    }
                )
        return sorted(rows, key=lambda row: (row["profile_id"], row["kind"], row["item_id"]))

    @classmethod
    def _profile_adjusted_action_benefit(
        cls, model: EconomyModel, profile_id: str, action, state: SimulationState
    ) -> SimNumber:
        if action.kind == "buy_generator":
            before = cls._profile_adjusted_generator_output(
                model, profile_id, action.item_id, state
            )
            simulated = state.copy()
            simulated.generators_owned[action.item_id] += 1
            after = cls._profile_adjusted_generator_output(
                model, profile_id, action.item_id, simulated
            )
            return after - before
        if action.kind == "buy_upgrade":
            upgrade = model.upgrades[action.item_id]
            target = upgrade.target.removeprefix("generator:").removesuffix(".output")
            generator_ids = sorted(model.generators) if target == "*" else [target]
            before = sum(
                (
                    cls._profile_adjusted_generator_output(model, profile_id, item_id, state)
                    for item_id in generator_ids
                ),
                SimNumber.zero(),
            )
            simulated = state.copy()
            simulated.upgrades_purchased.add(action.item_id)
            after = sum(
                (
                    cls._profile_adjusted_generator_output(model, profile_id, item_id, simulated)
                    for item_id in generator_ids
                ),
                SimNumber.zero(),
            )
            return after - before
        return SimNumber.zero()

    @classmethod
    def _profile_adjusted_generator_output(
        cls, model: EconomyModel, profile_id: str, generator_id: str, state: SimulationState
    ) -> SimNumber:
        owned = state.generators_owned.get(generator_id, 0)
        if owned <= 0:
            return SimNumber.zero()
        raw = ModifierStack.apply_generator_output(model, state, generator_id, owned)
        generator = model.generators[generator_id]
        profile = model.player_profiles[profile_id]
        return raw * profile.source_efficiency.get(generator.source_type, SimNumber.one())

    @classmethod
    def bottleneck_report(cls, result: SimulationResult) -> dict[str, list[dict[str, int | str]]]:
        interesting = {
            "buy_generator",
            "buy_upgrade",
            "unlock_generator",
            "unlock_upgrade",
            "milestone_reward",
            "prestige_reset",
        }
        by_profile: dict[str, list[int]] = {}
        for event in result.events:
            if event.kind in interesting:
                by_profile.setdefault(event.profile_id, []).append(event.time_seconds)
        report: dict[str, list[dict[str, int | str]]] = {}
        for profile_id, times in sorted(by_profile.items()):
            sorted_times = sorted(set(times))
            gaps = []
            previous = 0
            for current in sorted_times:
                gap = current - previous
                if gap >= 60:
                    gaps.append({"start": previous, "end": current, "duration": gap})
                previous = current
            report[profile_id] = gaps
        return report

    @classmethod
    def invalid_content_report(
        cls, result: SimulationResult, model: EconomyModel | None
    ) -> dict[str, list[str]]:
        if model is None:
            return {"never_purchased": [], "never_unlocked": []}
        purchased = {
            f"{event.kind.removeprefix('buy_')}:{event.item_id}"
            for event in result.events
            if event.kind.startswith("buy_")
        }
        unlocked = {
            f"{event.kind.removeprefix('unlock_')}:{event.item_id}"
            for event in result.events
            if event.kind.startswith("unlock_")
        }
        all_items = {
            *(f"generator:{item_id}" for item_id in model.generators),
            *(f"upgrade:{item_id}" for item_id in model.upgrades),
        }
        return {
            "never_purchased": sorted(all_items - purchased),
            "never_unlocked": sorted(all_items - unlocked),
        }

    @classmethod
    def overpowered_content_report(cls, item_purchase_counts: Counter[str]) -> list[dict[str, str]]:
        total = sum(item_purchase_counts.values())
        if total == 0:
            return []
        rows = []
        for item_id, count in sorted(item_purchase_counts.items()):
            share = count / total
            if share >= 0.5:
                rows.append(
                    {
                        "item_id": item_id,
                        "purchase_count": str(count),
                        "purchase_share": f"{share:.4f}",
                    }
                )
        return rows

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

    @classmethod
    def _final_row(cls, result: SimulationResult, profile_id: str) -> TimelineRow:
        rows = [row for row in result.timeline if row.profile_id == profile_id]
        return max(rows, key=lambda row: row.time_seconds)

    @classmethod
    def _state_from_final_row(cls, model: EconomyModel, row: TimelineRow) -> SimulationState:
        state = SimulationState.new(model)
        state.resources = {
            resource_id: SimNumber.parse(value) for resource_id, value in row.resources.items()
        }
        state.generators_owned = dict(row.generators_owned)
        state.upgrades_purchased = set(row.upgrades_purchased)
        return state

    @classmethod
    def _candidate_payback_actions(cls, model: EconomyModel, state: SimulationState):
        from .schema import Action

        actions = []
        for generator_id, generator in model.generators.items():
            if not evaluate(generator.unlock_condition, lambda item_id: state.generators_owned.get(item_id, 0)):
                continue
            cost = model.generator_cost(generator_id, state.generators_owned[generator_id])
            actions.append(
                Action("buy_generator", generator_id, generator.cost_resource, cost, cost)
            )
        for upgrade_id, upgrade in model.upgrades.items():
            if upgrade_id in state.upgrades_purchased:
                continue
            if not evaluate(upgrade.unlock_condition, lambda item_id: state.generators_owned.get(item_id, 0)):
                continue
            cost = model.upgrade_cost(upgrade_id)
            actions.append(Action("buy_upgrade", upgrade_id, upgrade.cost_resource, cost, cost))
        return sorted(actions, key=lambda action: (action.kind, action.item_id))
