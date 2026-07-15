from __future__ import annotations

import csv
import copy
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .builder import ModelBuilder
from .linter import ConfigLinter
from .loader import ConfigLoader
from .outputs import OutputWriter
from .reporting.static import generate_static_report
from .simulator import Simulator


MAX_SCAN_VARIANTS = 1000
# Bound fixed-width values before allocating powers of ten or result strings.
MAX_SCAN_VALUE_CHARS = 4096
# Bound the aggregate payload produced by one parameter expansion.
MAX_SCAN_OUTPUT_CHARS = 1_000_000


@dataclass(frozen=True)
class ScanParameter:
    table: str
    row_id: str
    field: str
    values: list[str]

    def override_label(self, value: str) -> str:
        return f"{self.table}.{self.row_id}.{self.field}={value}"


def parse_scan_parameter(text: str, max_variants: int = MAX_SCAN_VARIANTS) -> ScanParameter:
    assignment_parts = text.split("=")
    if len(assignment_parts) != 2:
        raise _invalid_scan_parameter(text, "the expression must contain exactly one '='")
    path, range_text = assignment_parts

    path_parts = path.split(".")
    if len(path_parts) != 3 or any(not part for part in path_parts):
        raise _invalid_scan_parameter(text, "the path must be table.row_id.field")
    table, row_id, field = path_parts

    step_parts = range_text.split(":")
    if len(step_parts) != 2:
        raise _invalid_scan_parameter(text, "the range must contain exactly one ':'")
    bounds, step_text = step_parts

    separator_index = bounds.find("..")
    if separator_index < 0 or separator_index != bounds.rfind(".."):
        raise _invalid_scan_parameter(text, "the range must contain exactly one '..'")
    start_text = bounds[:separator_index]
    end_text = bounds[separator_index + 2 :]

    try:
        start = Decimal(start_text)
        end = Decimal(end_text)
        step = Decimal(step_text)
    except (InvalidOperation, ValueError):
        raise _invalid_scan_parameter(text, "start, stop, and step must be decimal numbers") from None

    if not all(number.is_finite() for number in (start, end, step)):
        raise _invalid_scan_parameter(text, "start, stop, and step must be finite")
    if step == 0:
        raise _invalid_scan_parameter(text, "step must not be zero")
    if start < end and step < 0:
        raise _invalid_scan_parameter(text, "step must be positive for an ascending range")
    if start > end and step > 0:
        raise _invalid_scan_parameter(text, "step must be negative for a descending range")

    common_exponent = min(
        start.as_tuple().exponent,
        end.as_tuple().exponent,
        step.as_tuple().exponent,
    )
    estimated_value_chars = max(
        _fixed_width_estimate(start, common_exponent),
        _fixed_width_estimate(end, common_exponent),
    )
    estimated_scaled_digits = max(
        _scaled_integer_digits(start, common_exponent),
        _scaled_integer_digits(end, common_exponent),
        _scaled_integer_digits(step, common_exponent),
    )
    if max(estimated_value_chars, estimated_scaled_digits) > MAX_SCAN_VALUE_CHARS:
        raise _invalid_scan_parameter(
            text,
            f"expanded values are too large (limit: {MAX_SCAN_VALUE_CHARS} characters each)",
        )

    start_integer = _to_scaled_integer(start, common_exponent)
    end_integer = _to_scaled_integer(end, common_exponent)
    step_integer = _to_scaled_integer(step, common_exponent)
    distance = abs(end_integer - start_integer)
    count = distance // abs(step_integer) + 1
    if count > max_variants:
        raise ValueError(
            f"scan parameter {text!r} expands to too many variants (>{max_variants}); "
            "increase the step or narrow the range"
        )
    if count * estimated_value_chars > MAX_SCAN_OUTPUT_CHARS:
        raise _invalid_scan_parameter(
            text,
            f"expanded output is too large (limit: {MAX_SCAN_OUTPUT_CHARS} characters total)",
        )

    values = [
        _format_scaled_integer(start_integer + index * step_integer, common_exponent)
        for index in range(count)
    ]
    return ScanParameter(table=table, row_id=row_id, field=field, values=values)


def _invalid_scan_parameter(text: str, reason: str) -> ValueError:
    return ValueError(
        f"rejected scan parameter {text!r}: {reason}. "
        "Expected PATH=START..STOP:STEP; for example, "
        "generators.fisherman.cost_growth=1.14..1.18:0.01"
    )


def _fixed_width_estimate(value: Decimal, exponent: int) -> int:
    if value == 0:
        return 1 if exponent >= 0 else 2 - exponent
    integer_digits = max(1, value.adjusted() + 1)
    sign_chars = 1 if value.is_signed() and value != 0 else 0
    if exponent >= 0:
        return sign_chars + integer_digits
    return sign_chars + integer_digits + 1 - exponent


def _scaled_integer_digits(value: Decimal, exponent: int) -> int:
    if value == 0:
        return 1
    value_tuple = value.as_tuple()
    return len(value_tuple.digits) + value_tuple.exponent - exponent


def _to_scaled_integer(value: Decimal, exponent: int) -> int:
    value_tuple = value.as_tuple()
    coefficient = 0
    for digit in value_tuple.digits:
        coefficient = coefficient * 10 + digit
    if coefficient == 0:
        return 0
    coefficient *= 10 ** (value_tuple.exponent - exponent)
    return -coefficient if value_tuple.sign else coefficient


def _format_scaled_integer(value: int, exponent: int) -> str:
    if value == 0:
        return "0" if exponent >= 0 else "0." + "0" * -exponent
    sign = "-" if value < 0 else ""
    digits = str(abs(value))
    if exponent >= 0:
        return sign + digits + "0" * exponent

    precision = -exponent
    if len(digits) <= precision:
        digits = "0" * (precision - len(digits) + 1) + digits
    split_at = len(digits) - precision
    return sign + digits[:split_at] + "." + digits[split_at:]


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
