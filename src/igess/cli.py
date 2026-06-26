from __future__ import annotations

import argparse
import sys

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
from .scan import run_scan
from .simulator import Simulator
from .templates import init_project


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="igess")
    subparsers = parser.add_subparsers(dest="command", required=True)
    export = subparsers.add_parser("export-tables")
    export.add_argument("--datas", required=True)
    export.add_argument("--out", required=True)
    report = subparsers.add_parser("report")
    report.add_argument("--run", required=True)
    report.add_argument("--out", required=True)
    report.add_argument("--title")
    compare = subparsers.add_parser("compare")
    compare.add_argument("--base", required=True)
    compare.add_argument("--candidate", required=True)
    compare.add_argument("--out", required=True)
    scan = subparsers.add_parser("scan")
    scan.add_argument("--config", required=True)
    scan.add_argument("--tables", required=True)
    scan.add_argument("--scenario", required=True)
    scan.add_argument("--param", required=True)
    scan.add_argument("--out", required=True)
    gate = subparsers.add_parser("gate")
    gate.add_argument("--base", required=True)
    gate.add_argument("--candidate", required=True)
    gate.add_argument("--config", required=True)
    gate.add_argument("--out", required=True)
    init = subparsers.add_parser("init")
    init.add_argument("--template", default="incremental-basic")
    init.add_argument("--out", required=True)
    doctor = subparsers.add_parser("doctor")
    doctor.add_argument("--project", default=".")
    doctor.add_argument("--config", default="examples/shelldiver_v0/economy.yaml")
    doctor.add_argument("--tables", default="examples/shelldiver_v0/luban_exports")
    explain = subparsers.add_parser("explain")
    explain.add_argument("--run", required=True)
    explain.add_argument("--event", required=True)
    dashboard = subparsers.add_parser("dashboard")
    dashboard.add_argument("--project", default=".")
    dashboard.add_argument("--config", default="examples/shelldiver_v0/economy.yaml")
    dashboard.add_argument("--tables", default="examples/shelldiver_v0/luban_exports")
    dashboard.add_argument("--runs-root")
    dashboard.add_argument("--host", default="127.0.0.1")
    dashboard.add_argument("--port", type=int, default=8765)
    for command in ("lint", "run"):
        sub = subparsers.add_parser(command)
        sub.add_argument("--config", required=True)
        sub.add_argument("--tables", required=True)
        if command == "run":
            sub.add_argument("--scenario", required=True)
            sub.add_argument("--out", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "export-tables":
            written = export_registered_workbooks(args.datas, args.out)
            print(f"Exported {len(written)} tables to {args.out}")
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
        if args.command == "gate":
            result = evaluate_gates(args.base, args.candidate, args.config, args.out)
            if result.ok:
                print(f"Regression gates passed; wrote results to {result.output_dir}")
                return 0
            print(f"Regression gates failed; wrote results to {result.output_dir}")
            return 1
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
    except (ConfigError, FileNotFoundError, KeyError, ReportLoadError, ValueError) as exc:
        print(f"igess: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
