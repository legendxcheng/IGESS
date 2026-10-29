"""CLI transport for the analysis service; no business calculations here."""
import argparse
import json

from .service import AnalysisService


def add_analysis_parsers(subparsers):
    group = subparsers.add_parser("runs", help="Inspect registered simulation runs")
    commands = group.add_subparsers(dest="analysis_action", required=True)
    for action in ("list", "show", "artifacts"):
        parser = commands.add_parser(action)
        parser.add_argument("--project", required=True)
        parser.add_argument("--runs-root")
        parser.add_argument("--json", action="store_true")
        if action == "list":
            for option in ("scenario-id", "status", "engine-id"):
                parser.add_argument("--" + option)
            parser.add_argument("--kind", choices=("formal", "smoke", "all"), default="formal")
            parser.add_argument("--limit", type=int, default=50)
            parser.add_argument("--offset", type=int, default=0)
        else:
            parser.add_argument("--run-id", required=True)
    group = subparsers.add_parser("metrics", help="Describe and extract recorded metrics")
    commands = group.add_subparsers(dest="analysis_action", required=True)
    for action in ("describe", "extract"):
        parser = commands.add_parser(action)
        parser.add_argument("--project", required=True)
        parser.add_argument("--runs-root")
        parser.add_argument("--json", action="store_true")
        if action == "describe":
            parser.add_argument("--engine-id", required=True)
        else:
            parser.add_argument("--run-id", required=True)
            parser.add_argument("--metric-id", required=True)
            parser.add_argument("--profile-id", required=True)
            parser.add_argument("--dimensions", type=json.loads, default={})
            parser.add_argument("--time-basis", choices=("wall", "online"), default="wall")
            parser.add_argument("--scope", choices=("segment", "lifecycle"), default="segment")
            parser.add_argument("--aggregation", default="value")
    group = subparsers.add_parser("targets", help="Evaluate versioned targets against a recorded run")
    commands = group.add_subparsers(dest="analysis_action", required=True)
    parser = commands.add_parser("evaluate")
    parser.add_argument("--project", required=True)
    parser.add_argument("--runs-root")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--target-file", required=True)
    parser.add_argument("--out")
    parser.add_argument("--json", action="store_true")


def dispatch_analysis(args: argparse.Namespace) -> int:
    options = vars(args).copy()
    command = options.pop("command") + "." + options.pop("analysis_action")
    json_output = options.pop("json")
    service = AnalysisService(options.pop("project"), runs_root=options.pop("runs_root"))
    response = service.execute(command, **options)
    print(response.to_json() if json_output else json.dumps(response.to_payload(), ensure_ascii=False, indent=2))
    return 0 if response.ok else 1
