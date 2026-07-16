"""Command-line adapter for incremental model authoring."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import NoReturn

from .response import CommandResponse
from .service import AuthoringService


_EXIT_CODES = (
    "Exit codes:\n"
    "  0  Command completed successfully.\n"
    "  1  Command failed.\n"
    "  2  Command-line usage error."
)


class _ModelHelpFormatter(argparse.RawDescriptionHelpFormatter):
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


def add_model_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    """Register the complete nested ``igess model`` command surface."""

    model = subparsers.add_parser(
        "model",
        help="Author game economy rules incrementally",
        description="Author a game economy one validated rule at a time.",
        epilog=(
            "Examples:\n"
            "  igess model init --out projects/my-game\n"
            "  igess model status --project projects/my-game\n\n"
            f"{_EXIT_CODES}"
        ),
        formatter_class=_ModelHelpFormatter,
    )
    commands = model.add_subparsers(
        dest="model_command",
        required=True,
        title="Model commands",
        metavar="<model-command>",
    )

    def add_command(
        name: str,
        summary: str,
        example: str,
    ) -> argparse.ArgumentParser:
        return commands.add_parser(
            name,
            help=summary,
            description=f"{summary}.",
            epilog=f"Examples:\n  {example}\n\n{_EXIT_CODES}",
            formatter_class=_ModelHelpFormatter,
        )

    init = add_command(
        "init",
        "Initialize a blank incremental authoring project",
        "igess model init --out projects/my-game --id my_game",
    )
    init.add_argument("--out", required=True, help="Directory to initialize.")
    init.add_argument(
        "--id",
        dest="model_id",
        help="Stable model id; defaults to the sanitized output directory name.",
    )
    init.add_argument(
        "--json",
        action="store_true",
        help="Emit one machine-readable JSON response.",
    )

    status = add_command(
        "status",
        "Inspect current model validity and completeness",
        "igess model status --project projects/my-game --json",
    )
    _add_project_argument(status)
    status.add_argument(
        "--json",
        action="store_true",
        help="Emit one machine-readable JSON response.",
    )

    apply = add_command(
        "apply",
        "Apply one validated and auditable model change",
        "igess model apply --project projects/my-game --change changes/resource.yaml --json",
    )
    _add_project_argument(apply)
    source = apply.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--change",
        help="YAML or JSON change document; the file extension selects its format.",
    )
    source.add_argument(
        "--stdin",
        action="store_true",
        help="Read the change document from standard input.",
    )
    apply.add_argument(
        "--format",
        dest="format_name",
        choices=("yaml", "json"),
        help="Input format override; standard input defaults to yaml.",
    )
    apply.add_argument(
        "--json",
        action="store_true",
        help="Emit one machine-readable JSON response.",
    )

    simulate = add_command(
        "simulate",
        "Run a registered model scenario with standard artifacts",
        "igess model simulate --project projects/my-game --scenario smoke --json",
    )
    _add_project_argument(simulate)
    simulate.add_argument(
        "--scenario",
        default="smoke",
        help="Scenario identifier to simulate.",
    )
    simulate.add_argument(
        "--json",
        action="store_true",
        help="Emit one machine-readable JSON response.",
    )
    return model


def dispatch_model(args: argparse.Namespace) -> int:
    """Invoke one authoring service method and render its typed response."""

    command = args.model_command
    if command == "init":
        response = AuthoringService().init(args.out, args.model_id)
    elif command == "status":
        response = AuthoringService(args.project).status()
    elif command == "apply":
        document = _read_change_document(args)
        if isinstance(document, CommandResponse):
            response = document
        else:
            text, format_name = document
            response = AuthoringService(args.project).apply(
                text,
                format_name=format_name,
            )
    elif command == "simulate":
        response = AuthoringService(args.project).simulate(args.scenario)
    else:  # pragma: no cover - argparse owns the closed command set.
        _unreachable_model_command(command)
    return _render_response(response, args.json)


def _add_project_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--project",
        default=".",
        help="Authoring project root directory.",
    )


def _read_change_document(
    args: argparse.Namespace,
) -> tuple[str, str] | CommandResponse:
    if args.change is None:
        return sys.stdin.read(), args.format_name or "yaml"

    path = Path(args.change)
    format_name = args.format_name or _format_from_suffix(path)
    if format_name is None:
        return _cli_error(
            "invalid_change",
            "Change file extension must be .yaml, .yml, or .json",
            {"path": str(path), "allowed": [".yaml", ".yml", ".json"]},
        )
    try:
        return path.read_text(encoding="utf-8"), format_name
    except (OSError, UnicodeError) as error:
        return _cli_error(
            "change_read_failed",
            f"Could not read change document: {path}",
            {"path": str(path), "error_type": type(error).__name__},
        )


def _format_from_suffix(path: Path) -> str | None:
    suffix = path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        return "yaml"
    if suffix == ".json":
        return "json"
    return None


def _cli_error(
    code: str,
    message: str,
    details: dict[str, object],
) -> CommandResponse:
    return CommandResponse(
        command="model.apply",
        ok=False,
        code=code,
        message=message,
        details=details,
    )


def _render_response(response: CommandResponse, json_output: bool) -> int:
    if json_output:
        print(response.to_json())
    else:
        print("\n".join(response.human_lines()))
    return 0 if response.ok else 1


def _unreachable_model_command(command: object) -> NoReturn:
    raise RuntimeError(f"unreachable model command: {command!r}")


__all__ = ["add_model_parser", "dispatch_model"]
