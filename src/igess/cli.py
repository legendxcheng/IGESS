from __future__ import annotations

import argparse
import sys

from .advice import review_run, run_advise
from .builder import ModelBuilder
from .compare import compare_runs
from .dashboard import serve_dashboard
from .doctor import format_doctor_report, run_doctor
from .explain import explain_event, format_event_explanation
from .gates import evaluate_gates
from .linter import ConfigError, ConfigLinter
from .loader import ConfigLoader
from .luban_exporter import export_registered_workbooks
from .outputs import OutputWriter
from .reporting.loader import ReportLoadError
from .reporting.static import generate_static_report
from .rng import RngSimulator
from .rng_outputs import RngOutputWriter
from .scan import run_scan
from .simulator import Simulator
from .stone_role_level import (
    build_realm_progression_curve,
    build_role_level_curve,
    write_realm_progression_artifacts,
    write_role_level_artifacts,
)
from .templates import init_project
from .verification import review_proposal, verify_edits
from .yaml_plan import PlanValidationError, apply_yaml_plan, create_yaml_plan


class _HelpFormatter(argparse.RawDescriptionHelpFormatter):
    def __init__(self, prog: str) -> None:
        super().__init__(prog, max_help_position=32)

    def _get_help_string(self, action: argparse.Action) -> str:
        help_text = action.help or ""
        if (
            "%(default)" not in help_text
            and action.default is not argparse.SUPPRESS
            and action.default is not None
        ):
            help_text += " (default: %(default)s)"
        return help_text


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="igess",
        description="Build, validate, simulate, inspect, and tune incremental-game economy models.",
        epilog=(
            "Exit codes:\n"
            "  0  Command completed successfully.\n"
            "  1  Command failed.\n"
            "  2  Command-line usage error."
        ),
        formatter_class=_HelpFormatter,
    )
    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
        title="Commands",
        metavar="<command>",
    )

    def add_command(name: str, summary: str, example: str) -> argparse.ArgumentParser:
        return subparsers.add_parser(
            name,
            help=summary,
            description=f"{summary}.",
            epilog=f"Examples:\n  {example}",
            formatter_class=_HelpFormatter,
        )

    export = add_command(
        "export-tables",
        "Export registered Luban workbooks",
        "igess export-tables --datas data-tables/Datas --out luban_exports",
    )
    export.add_argument(
        "--datas", required=True, help="Directory containing registered Luban workbooks."
    )
    export.add_argument("--out", required=True, help="Directory for exported JSON tables.")

    stone_role_level = add_command(
        "stone-role-level",
        "Build the Stone role-level curve",
        "igess stone-role-level --role-lv RoleLv.xlsx --attribute-def AttributeDef.xlsx --out artifacts/role-level",
    )
    stone_role_level.add_argument(
        "--role-lv", required=True, help="Stone role-level workbook or sheet input."
    )
    stone_role_level.add_argument(
        "--attribute-def",
        required=True,
        help="Stone attribute-definition workbook or sheet input.",
    )
    stone_role_level.add_argument(
        "--out", required=True, help="Directory for generated role-level artifacts."
    )

    stone_realm_progression = add_command(
        "stone-realm-progression",
        "Build the Stone realm progression curve",
        "igess stone-realm-progression --role-realm RoleRealm.xlsx --attribute-def AttributeDef.xlsx --out artifacts/realm",
    )
    stone_realm_progression.add_argument(
        "--role-realm", required=True, help="Stone role-realm workbook or sheet input."
    )
    stone_realm_progression.add_argument(
        "--attribute-def",
        required=True,
        help="Stone attribute-definition workbook or sheet input.",
    )
    stone_realm_progression.add_argument(
        "--out", required=True, help="Directory for generated realm artifacts."
    )

    report = add_command(
        "report",
        "Generate a static HTML report",
        "igess report --run runs/day_1 --out reports/day_1",
    )
    report.add_argument("--run", required=True, help="Simulation run directory to report on.")
    report.add_argument("--out", required=True, help="Directory for the generated static report.")
    report.add_argument("--title", help="Optional report title.")

    compare = add_command(
        "compare",
        "Compare two simulation runs",
        "igess compare --base runs/baseline --candidate runs/candidate --out reports/comparison",
    )
    compare.add_argument("--base", required=True, help="Baseline simulation run directory.")
    compare.add_argument(
        "--candidate", required=True, help="Candidate simulation run directory."
    )
    compare.add_argument("--out", required=True, help="Directory for the comparison report.")

    scan = add_command(
        "scan",
        "Scan a numeric parameter",
        "igess scan --config examples/shelldiver_v0/economy.yaml --tables examples/shelldiver_v0/luban_exports "
        "--scenario day_1_progression --param generators.fisherman.cost_growth=1.14..1.18:0.01 --out scan-out",
    )
    scan.add_argument("--config", required=True, help="Path to the economy YAML configuration.")
    scan.add_argument(
        "--tables", required=True, help="Directory containing exported Luban JSON tables."
    )
    scan.add_argument("--scenario", required=True, help="Scenario identifier to simulate.")
    scan.add_argument(
        "--param", required=True, help="Parameter scan expression PATH=START..STOP:STEP."
    )
    scan.add_argument("--out", required=True, help="Directory for scan runs and summary.")

    rng_run = add_command(
        "rng-run",
        "Run an RNG scenario",
        "igess rng-run --config economy.yaml --scenario loot_check --out runs/loot_check",
    )
    rng_run.add_argument(
        "--config", required=True, help="Path to the economy YAML configuration."
    )
    rng_run.add_argument(
        "--scenario", required=True, help="RNG scenario identifier to simulate."
    )
    rng_run.add_argument("--out", required=True, help="Directory for RNG simulation outputs.")

    gate = add_command(
        "gate",
        "Evaluate regression gates",
        "igess gate --base runs/baseline --candidate runs/candidate --config gates.yaml --out gate-results",
    )
    gate.add_argument("--base", required=True, help="Baseline simulation run directory.")
    gate.add_argument(
        "--candidate", required=True, help="Candidate simulation run directory."
    )
    gate.add_argument(
        "--config", required=True, help="Path to the regression gate YAML configuration."
    )
    gate.add_argument("--out", required=True, help="Directory for regression gate results.")

    advise = add_command(
        "advise",
        "Generate tuning advice",
        "igess advise --config economy.yaml --tables luban_exports --scenario day_1 --out advice/day_1",
    )
    advise.add_argument("--config", required=True, help="Path to the economy YAML configuration.")
    advise.add_argument(
        "--tables", required=True, help="Directory containing exported Luban JSON tables."
    )
    advise.add_argument("--scenario", required=True, help="Scenario identifier to analyze.")
    advise.add_argument("--out", required=True, help="Directory for tuning advice.")
    advise.add_argument("--baseline", help="Optional baseline simulation run directory.")

    review = add_command(
        "review-run",
        "Review an existing simulation run",
        "igess review-run --run runs/day_1 --out reviews/day_1",
    )
    review.add_argument("--run", required=True, help="Simulation run directory to review.")
    review.add_argument("--out", required=True, help="Directory for review artifacts.")
    review.add_argument("--baseline", help="Optional baseline simulation run directory.")

    proposal_review = add_command(
        "review-proposal",
        "Review a tuning proposal",
        "igess review-proposal --proposal proposal.yaml --out reviews/proposal",
    )
    proposal_review.add_argument(
        "--proposal", required=True, help="Path to the tuning proposal YAML file."
    )
    proposal_review.add_argument(
        "--out", required=True, help="Directory for proposal review artifacts."
    )

    verify = add_command(
        "verify-edits",
        "Verify proposed configuration edits",
        "igess verify-edits --config economy.yaml --proposal proposal.yaml --scenario day_1 --out verification/day_1",
    )
    verify.add_argument("--config", required=True, help="Path to the economy YAML configuration.")
    verify.add_argument(
        "--proposal", required=True, help="Path to the tuning proposal YAML file."
    )
    verify.add_argument(
        "--scenario", required=True, help="Scenario identifier used for verification."
    )
    verify.add_argument("--out", required=True, help="Directory for verification artifacts.")
    verify.add_argument("--tables", help="Optional exported Luban JSON table directory.")
    verify.add_argument("--datas", help="Optional registered Luban workbook directory.")
    verify.add_argument("--baseline", help="Optional baseline simulation run directory.")

    yaml_plan = add_command(
        "yaml-plan",
        "Create a reviewable YAML edit plan",
        'igess yaml-plan --config economy.yaml --intent "halve the first upgrade cost" --out plan.yaml',
    )
    yaml_plan.add_argument(
        "--config", required=True, help="Path to the economy YAML configuration."
    )
    yaml_plan.add_argument("--intent", required=True, help="Natural-language edit intent.")
    yaml_plan.add_argument("--out", required=True, help="Path for the generated YAML edit plan.")

    yaml_apply = add_command(
        "yaml-apply",
        "Apply an approved YAML edit plan",
        "igess yaml-apply --config economy.yaml --plan plan.yaml --approve",
    )
    yaml_apply.add_argument(
        "--config", required=True, help="Path to the economy YAML configuration."
    )
    yaml_apply.add_argument("--plan", required=True, help="Path to a generated YAML edit plan.")
    yaml_apply.add_argument(
        "--approve",
        action="store_true",
        help="Confirm that the reviewed plan may be applied.",
    )
    yaml_apply.add_argument("--tables", help="Optional exported Luban JSON table directory.")

    init = add_command(
        "init",
        "Initialize an IGESS project",
        "igess init --out my-economy",
    )
    init.add_argument(
        "--template",
        default="incremental-basic",
        help="Project template name.",
    )
    init.add_argument("--out", required=True, help="Directory to initialize.")

    doctor = add_command(
        "doctor",
        "Diagnose an IGESS project",
        "igess doctor --project my-economy --config economy.yaml --tables luban_exports",
    )
    doctor.add_argument("--project", default=".", help="IGESS project root directory.")
    doctor.add_argument(
        "--config",
        default="examples/shelldiver_v0/economy.yaml",
        help="Economy YAML path, relative to the project root by default.",
    )
    doctor.add_argument(
        "--tables",
        default="examples/shelldiver_v0/luban_exports",
        help="Exported table directory, relative to the project root by default.",
    )

    explain = add_command(
        "explain",
        "Explain one simulation event",
        "igess explain --run runs/day_1 --event 0",
    )
    explain.add_argument(
        "--run", required=True, help="Simulation run directory containing event artifacts."
    )
    explain.add_argument("--event", required=True, help="Zero-based event index to explain.")

    dashboard = add_command(
        "dashboard",
        "Serve the local simulation dashboard",
        "igess dashboard --project . --port 8765",
    )
    dashboard.add_argument("--project", default=".", help="IGESS project root directory.")
    dashboard.add_argument(
        "--config",
        default="examples/shelldiver_v0/economy.yaml",
        help="Economy YAML path, relative to the project root by default.",
    )
    dashboard.add_argument(
        "--tables",
        default="examples/shelldiver_v0/luban_exports",
        help="Exported table directory, relative to the project root by default.",
    )
    dashboard.add_argument(
        "--runs-root", help="Optional directory used to discover simulation runs."
    )
    dashboard.add_argument("--host", default="127.0.0.1", help="Dashboard bind address.")
    dashboard.add_argument("--port", type=int, default=8765, help="Dashboard TCP port.")

    lint = add_command(
        "lint",
        "Validate an economy model",
        "igess lint --config economy.yaml --tables luban_exports",
    )
    lint.add_argument("--config", required=True, help="Path to the economy YAML configuration.")
    lint.add_argument(
        "--tables", required=True, help="Directory containing exported Luban JSON tables."
    )

    run = add_command(
        "run",
        "Run a deterministic economy simulation",
        "igess run --config economy.yaml --tables luban_exports --scenario day_1 --out runs/day_1",
    )
    run.add_argument("--config", required=True, help="Path to the economy YAML configuration.")
    run.add_argument(
        "--tables", required=True, help="Directory containing exported Luban JSON tables."
    )
    run.add_argument("--scenario", required=True, help="Scenario identifier to simulate.")
    run.add_argument("--out", required=True, help="Directory for simulation outputs.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "export-tables":
            written = export_registered_workbooks(args.datas, args.out)
            print(f"Exported {len(written)} tables to {args.out}")
            return 0
        if args.command == "stone-role-level":
            curve = build_role_level_curve(args.role_lv, args.attribute_def)
            artifacts = write_role_level_artifacts(curve, args.out)
            print(
                "Wrote stone role level model to "
                f"{args.out} ({len(artifacts)} artifact(s))"
            )
            return 0
        if args.command == "stone-realm-progression":
            curve = build_realm_progression_curve(args.role_realm, args.attribute_def)
            artifacts = write_realm_progression_artifacts(curve, args.out)
            print(
                "Wrote stone realm progression model to "
                f"{args.out} ({len(artifacts)} artifact(s))"
            )
            return 0
        if args.command == "report":
            index = generate_static_report(args.run, args.out, args.title)
            print(f"Wrote static report to {index}")
            return 0
        if args.command == "compare":
            index = compare_runs(args.base, args.candidate, args.out)
            print(f"Wrote comparison report to {index}")
            return 0
        if args.command == "scan":
            summary = run_scan(args.config, args.tables, args.scenario, args.param, args.out)
            print(f"Wrote scan summary to {summary}")
            return 0
        if args.command == "rng-run":
            raw = ConfigLoader.load_rules_only(args.config)
            ConfigLinter.validate(raw)
            model = ModelBuilder.build(raw)
            result = RngSimulator(model).run_scenario(args.scenario)
            RngOutputWriter.write_all(result, args.out, model)
            print(f"Wrote RNG simulation outputs to {args.out}")
            return 0
        if args.command == "gate":
            result = evaluate_gates(args.base, args.candidate, args.config, args.out)
            if result.ok:
                print(f"Regression gates passed; wrote results to {result.output_dir}")
                return 0
            print(f"Regression gates failed; wrote results to {result.output_dir}")
            return 1
        if args.command == "advise":
            advice = run_advise(args.config, args.tables, args.scenario, args.out, args.baseline)
            print(f"Wrote advice to {args.out} ({advice['status']})")
            return 0
        if args.command == "review-run":
            advice = review_run(args.run, args.out, args.baseline)
            print(f"Wrote advice to {args.out} ({advice['status']})")
            return 0
        if args.command == "review-proposal":
            review = review_proposal(args.proposal, args.out)
            print(
                f"Wrote proposal review to {args.out} "
                f"({review['recommendation_count']} recommendation(s))"
            )
            return 0
        if args.command == "verify-edits":
            report = verify_edits(
                args.config,
                args.proposal,
                args.scenario,
                args.out,
                tables=args.tables,
                datas=args.datas,
                baseline=args.baseline,
            )
            print(f"Wrote edit verification to {args.out} ({report['status']})")
            return 0 if report["status"] in {"passed", "needs_review"} else 1
        if args.command == "yaml-plan":
            create_yaml_plan(args.config, args.intent, args.out)
            print(f"Wrote YAML plan to {args.out}")
            return 0
        if args.command == "yaml-apply":
            result = apply_yaml_plan(args.config, args.plan, approve=args.approve, tables=args.tables)
            print(f"Applied YAML plan to {result['config']}")
            return 0
        if args.command == "init":
            path = init_project(args.template, args.out)
            print(f"Initialized IGESS project at {path}")
            return 0
        if args.command == "doctor":
            report = run_doctor(args.project, args.config, args.tables)
            print(format_doctor_report(report))
            return 0 if report.ok else 1
        if args.command == "explain":
            explanation = explain_event(args.run, args.event)
            print(format_event_explanation(explanation))
            return 0
        if args.command == "dashboard":
            serve_dashboard(
                project=args.project,
                config=args.config,
                tables=args.tables,
                runs_root=args.runs_root,
                host=args.host,
                port=args.port,
            )
            return 0
        raw = ConfigLoader.load(args.config, args.tables)
        ConfigLinter.validate(raw)
        if args.command == "lint":
            print("Config OK")
            return 0
        model = ModelBuilder.build(raw)
        result = Simulator(model).run_scenario(args.scenario)
        OutputWriter.write_all(result, args.out, model)
        print(f"Wrote simulation outputs to {args.out}")
        return 0
    except (
        ConfigError,
        FileNotFoundError,
        KeyError,
        PlanValidationError,
        ReportLoadError,
        ValueError,
    ) as exc:
        print(f"igess: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
