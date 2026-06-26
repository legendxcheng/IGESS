from __future__ import annotations

import argparse
import sys

from .builder import ModelBuilder
from .linter import ConfigError, ConfigLinter
from .loader import ConfigLoader
from .outputs import OutputWriter
from .simulator import Simulator


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="igess")
    subparsers = parser.add_subparsers(dest="command", required=True)
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
        raw = ConfigLoader.load(args.config, args.tables)
        ConfigLinter.validate(raw)
        if args.command == "lint":
            print("Config OK")
            return 0
        model = ModelBuilder.build(raw)
        result = Simulator(model).run_scenario(args.scenario)
        OutputWriter.write_all(result, args.out)
        print(f"Wrote simulation outputs to {args.out}")
        return 0
    except (ConfigError, FileNotFoundError, KeyError, ValueError) as exc:
        print(f"igess: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
