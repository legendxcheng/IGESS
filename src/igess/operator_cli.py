"""Minimal entry point shipped with the execution-planner toolkit."""

from __future__ import annotations

import argparse
from pathlib import Path
import struct
import sys

from .operator_dashboard import serve_operator_dashboard
from .operator_runtime import OperatorError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="igess-operator")
    parser.add_argument("--bundle", default=".", help="Execution toolkit root.")
    parser.add_argument("--port", type=int, default=0, help="Loopback port; zero selects a free port.")
    parser.add_argument("--no-browser", action="store_true", help="Do not open the default browser.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if sys.version_info[:2] != (3, 11) or struct.calcsize("P") != 8:
        print("IGESS 执行工具包仅支持 Windows x64 + Python 3.11 x64。", file=sys.stderr)
        return 1
    if not 0 <= args.port <= 65535:
        print("端口必须在 0 到 65535 之间。", file=sys.stderr)
        return 1
    try:
        serve_operator_dashboard(
            Path(args.bundle),
            port=args.port,
            open_browser=not args.no_browser,
        )
    except OperatorError as error:
        print(f"IGESS 启动失败 [{error.code}]：{error}", file=sys.stderr)
        return 1
    except OSError as error:
        print(f"IGESS 启动失败：{type(error).__name__}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
