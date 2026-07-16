"""Command-line adapter for incremental model authoring."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import stat
import sys
from typing import NoReturn

from .change import MAX_CHANGE_SOURCE_BYTES
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
        help=(
            "Standard-input format; defaults to yaml. "
            "File input always uses its extension."
        ),
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
        return _read_stdin_change(args.format_name or "yaml")

    path = Path(args.change)
    format_name = _format_from_suffix(path)
    if format_name is None:
        return _cli_error(
            "invalid_change",
            "Change file extension must be .yaml, .yml, or .json",
            {"path": str(path), "allowed": [".yaml", ".yml", ".json"]},
        )
    return _read_file_change(path, format_name)


def _read_stdin_change(format_name: str) -> tuple[str, str] | CommandResponse:
    try:
        binary_stream = getattr(sys.stdin, "buffer", None)
        if binary_stream is not None:
            source = binary_stream.read(MAX_CHANGE_SOURCE_BYTES + 1)
            if not isinstance(source, bytes):
                return _change_read_error(
                    "Standard input did not provide bytes",
                    path="<stdin>",
                    reason="invalid_stream",
                )
            if len(source) > MAX_CHANGE_SOURCE_BYTES:
                return _change_budget_error(len(source))
            return _decode_change(source, format_name, "<stdin>")

        text = sys.stdin.read(MAX_CHANGE_SOURCE_BYTES + 1)
        if not isinstance(text, str):
            return _change_read_error(
                "Standard input did not provide text",
                path="<stdin>",
                reason="invalid_stream",
            )
        try:
            source_bytes = len(text.encode("utf-8"))
        except UnicodeError:
            return _invalid_utf8_change(format_name, "<stdin>")
        if source_bytes > MAX_CHANGE_SOURCE_BYTES:
            return _change_budget_error(source_bytes)
        return text, format_name
    except (OSError, UnicodeError) as error:
        return _change_read_error(
            "Could not read change document from standard input",
            path="<stdin>",
            reason="read_error",
            error=error,
        )


def _read_file_change(
    path: Path,
    format_name: str,
) -> tuple[str, str] | CommandResponse:
    try:
        before = path.lstat()
    except OSError as error:
        return _change_read_error(
            f"Could not inspect change document: {path}",
            path=str(path),
            reason="access_error",
            error=error,
        )
    if _unsafe_file_identity(before) or not stat.S_ISREG(before.st_mode):
        return _change_read_error(
            f"Change document must be a real regular file: {path}",
            path=str(path),
            reason="unsafe_file",
        )
    if before.st_size > MAX_CHANGE_SOURCE_BYTES:
        return _change_budget_error(before.st_size)

    flags = os.O_RDONLY
    for name in ("O_BINARY", "O_CLOEXEC", "O_NOINHERIT", "O_NOFOLLOW", "O_NONBLOCK"):
        flags |= getattr(os, name, 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        return _change_read_error(
            f"Could not open change document: {path}",
            path=str(path),
            reason="open_error",
            error=error,
        )

    close_error: OSError | None = None
    try:
        result = _read_open_change_file(path, descriptor, before, format_name)
    except OSError as error:
        result = _change_read_error(
            f"Could not read change document: {path}",
            path=str(path),
            reason="read_error",
            error=error,
        )
    finally:
        try:
            os.close(descriptor)
        except OSError as error:
            close_error = error
    if close_error is not None:
        return _change_read_error(
            f"Could not close change document safely: {path}",
            path=str(path),
            reason="close_error",
            error=close_error,
        )
    return result


def _read_open_change_file(
    path: Path,
    descriptor: int,
    before: os.stat_result,
    format_name: str,
) -> tuple[str, str] | CommandResponse:
    opened = os.fstat(descriptor)
    if _unsafe_file_identity(opened) or not stat.S_ISREG(opened.st_mode):
        return _change_read_error(
            f"Change document must remain a regular file: {path}",
            path=str(path),
            reason="unsafe_file",
        )
    if not os.path.samestat(before, opened) or not _same_file_version(before, opened):
        return _source_changed_error(path)
    if opened.st_size > MAX_CHANGE_SOURCE_BYTES:
        return _change_budget_error(opened.st_size)

    source = _read_descriptor_bounded(descriptor)
    after_descriptor = os.fstat(descriptor)
    try:
        after_path = path.lstat()
    except OSError:
        return _source_changed_error(path)

    observed_size = max(len(source), after_descriptor.st_size, after_path.st_size)
    if observed_size > MAX_CHANGE_SOURCE_BYTES:
        return _change_budget_error(observed_size)
    if (
        _unsafe_file_identity(after_descriptor)
        or _unsafe_file_identity(after_path)
        or not stat.S_ISREG(after_descriptor.st_mode)
        or not stat.S_ISREG(after_path.st_mode)
        or not os.path.samestat(opened, after_descriptor)
        or not os.path.samestat(opened, after_path)
        or not _same_file_version(opened, after_descriptor)
        or not _same_file_version(opened, after_path)
        or len(source) != after_descriptor.st_size
    ):
        return _source_changed_error(path)
    return _decode_change(source, format_name, str(path))


def _read_descriptor_bounded(descriptor: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while total <= MAX_CHANGE_SOURCE_BYTES:
        chunk = os.read(
            descriptor,
            min(65_536, MAX_CHANGE_SOURCE_BYTES + 1 - total),
        )
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
    return b"".join(chunks)


def _same_file_version(left: os.stat_result, right: os.stat_result) -> bool:
    return (
        left.st_size == right.st_size
        and left.st_mtime_ns == right.st_mtime_ns
    )


def _unsafe_file_identity(identity: os.stat_result) -> bool:
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    attributes = getattr(identity, "st_file_attributes", 0)
    return stat.S_ISLNK(identity.st_mode) or bool(attributes & reparse)


def _decode_change(
    source: bytes,
    format_name: str,
    path: str,
) -> tuple[str, str] | CommandResponse:
    try:
        return source.decode("utf-8", errors="strict"), format_name
    except UnicodeDecodeError:
        return _invalid_utf8_change(format_name, path)


def _invalid_utf8_change(format_name: str, path: str) -> CommandResponse:
    return _cli_error(
        "invalid_change",
        "Change document must use valid UTF-8 text",
        {
            "reason": "invalid_syntax",
            "format": format_name,
            "path": path,
        },
    )


def _change_budget_error(actual: int) -> CommandResponse:
    return _cli_error(
        "invalid_change",
        "Change document exceeds a structural safety budget",
        {
            "reason": "budget_exceeded",
            "budget": "source_bytes",
            "limit": MAX_CHANGE_SOURCE_BYTES,
            "actual": actual,
            "path": "$",
        },
    )


def _source_changed_error(path: Path) -> CommandResponse:
    return _change_read_error(
        f"Change document changed while it was being read: {path}",
        path=str(path),
        reason="source_changed",
    )


def _change_read_error(
    message: str,
    *,
    path: str,
    reason: str,
    error: OSError | UnicodeError | None = None,
) -> CommandResponse:
    details: dict[str, object] = {"path": path, "reason": reason}
    if error is not None:
        details["error_type"] = type(error).__name__
    return _cli_error("change_read_failed", message, details)


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
