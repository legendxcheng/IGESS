from __future__ import annotations

import csv
import copy
import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from .builder import ModelBuilder
from .linter import ConfigLinter
from .loader import ConfigLoader
from .outputs import OutputWriter
from .reporting.static import generate_static_report
from .simulator import Simulator


MAX_SCAN_VARIANTS = 1000


@dataclass(frozen=True)
class ScanParameter:
    table: str
    row_id: str
    field: str
    values: list[str]

    def override_label(self, value: str) -> str:
        return f"{self.table}.{self.row_id}.{self.field}={value}"


def parse_scan_parameter(text: str, max_variants: int = MAX_SCAN_VARIANTS) -> ScanParameter:
    path, range_text = text.split("=", 1)
    table, row_id, field = path.split(".", 2)
    bounds, step_text = range_text.split(":", 1)
    start_text, end_text = bounds.split("..", 1)
    start = Decimal(start_text)
    end = Decimal(end_text)
    step = Decimal(step_text)
    if step <= 0:
        raise ValueError("scan step must be positive")
    precision = max(_decimal_places(start_text), _decimal_places(end_text), _decimal_places(step_text))
    values = []
    current = start
    while current <= end:
        if len(values) >= max_variants:
            raise ValueError(f"scan parameter expands to too many variants (>{max_variants})")
        values.append(f"{current:.{precision}f}")
        current += step
    return ScanParameter(table=table, row_id=row_id, field=field, values=values)


def run_scan(
    config: str | Path,
    tables: str | Path,
    scenario_id: str,
    param: str,
    output_dir: str | Path,
) -> Path:
    parameter = parse_scan_parameter(param)
    raw = ConfigLoader.load(config, tables)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    variants = []
    summary_rows = []
    for value in parameter.values:
        variant_raw = copy.deepcopy(raw)
        _apply_override(variant_raw, parameter, value)
        ConfigLinter.validate(variant_raw)
        model = ModelBuilder.build(variant_raw)
        result = Simulator(model).run_scenario(scenario_id)
        variant_id = f"variant_{value.replace('.', '_').replace('-', 'm')}"
        variant_dir = output_dir / variant_id
        OutputWriter.write_all(result, variant_dir, model, overrides=[parameter.override_label(value)])
        generate_static_report(variant_dir, variant_dir / "report")
        variants.append(
            {
                "variant_id": variant_id,
                "value": value,
                "run_dir": str(variant_dir),
                "override": parameter.override_label(value),
            }
        )
        for profile in sorted({row.profile_id for row in result.timeline}):
            final = max(
                (row for row in result.timeline if row.profile_id == profile),
                key=lambda row: row.time_seconds,
            )
            summary_rows.append(
                {
                    "variant_id": variant_id,
                    "value": value,
                    "profile_id": profile,
                    "final_total_cps": final.total_cps,
                }
            )
    summary = {
        "schema_version": 1,
        "scenario_id": scenario_id,
        "parameter": {
            "table": parameter.table,
            "row_id": parameter.row_id,
            "field": parameter.field,
        },
        "variants": variants,
    }
    (output_dir / "scan.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    summary_path = output_dir / "summary.csv"
    with summary_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["variant_id", "value", "profile_id", "final_total_cps"],
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(summary_rows)
    return summary_path


def _apply_override(raw, parameter: ScanParameter, value: str) -> None:
    rows = getattr(raw, parameter.table)
    for row in rows:
        if row.id == parameter.row_id:
            if not hasattr(row, parameter.field):
                raise ValueError(f"{parameter.table}.{parameter.row_id} has no field {parameter.field}")
            setattr(row, parameter.field, value)
            return
    raise ValueError(f"{parameter.table}.{parameter.row_id} not found")


def _decimal_places(text: str) -> int:
    if "." not in text:
        return 0
    return len(text.split(".", 1)[1])
