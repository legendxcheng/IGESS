from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from openpyxl import load_workbook


_TEN = Decimal(10)


@dataclass(frozen=True)
class AttributeDefinition:
    key: str
    value_type: str
    power_value: Decimal
    enabled: bool


@dataclass(frozen=True)
class RoleLevelRow:
    level: int
    exp_req: Decimal
    cumulative_exp_to_level_start: Decimal
    cumulative_exp_to_next_level: Decimal
    combat_power: Decimal
    combat_power_delta: Decimal | None


@dataclass(frozen=True)
class RoleLevelCurve:
    role_lv_path: Path
    attribute_def_path: Path
    rows: list[RoleLevelRow]


@dataclass(frozen=True)
class _ColumnSpec:
    key: str
    value_type: str
    indexes: tuple[int, ...]


def build_role_level_curve(
    role_lv_path: str | Path,
    attribute_def_path: str | Path,
) -> RoleLevelCurve:
    role_lv = Path(role_lv_path)
    attribute_def = Path(attribute_def_path)
    definitions = _load_attribute_definitions(attribute_def)
    role_rows = _load_role_level_rows(role_lv)
    curve_rows: list[RoleLevelRow] = []
    cumulative_exp = Decimal(0)
    previous_power: Decimal | None = None
    for values in role_rows:
        level = int(values["id"])
        exp_req = values["expReq"]
        combat_power = _calculate_combat_power(values, definitions)
        curve_rows.append(
            RoleLevelRow(
                level=level,
                exp_req=exp_req,
                cumulative_exp_to_level_start=cumulative_exp,
                cumulative_exp_to_next_level=cumulative_exp + exp_req,
                combat_power=combat_power,
                combat_power_delta=None
                if previous_power is None
                else combat_power - previous_power,
            )
        )
        cumulative_exp += exp_req
        previous_power = combat_power
    return RoleLevelCurve(
        role_lv_path=role_lv,
        attribute_def_path=attribute_def,
        rows=curve_rows,
    )


def write_role_level_artifacts(result: RoleLevelCurve, output_dir: str | Path) -> dict[str, Path]:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    curve_json = output_path / "role_level_curve.json"
    curve_csv = output_path / "role_level_curve.csv"
    summary_md = output_path / "role_level_summary.md"
    manifest_json = output_path / "source_manifest.json"

    payload = [_row_payload(row) for row in result.rows]
    curve_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    with curve_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "level",
                "exp_req",
                "cumulative_exp_to_level_start",
                "cumulative_exp_to_next_level",
                "combat_power",
                "combat_power_delta",
            ],
        )
        writer.writeheader()
        writer.writerows(payload)

    summary_md.write_text(_summary_markdown(result), encoding="utf-8", newline="\n")
    manifest_json.write_text(
        json.dumps(_source_manifest(result), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return {
        "curve_json": curve_json,
        "curve_csv": curve_csv,
        "summary_md": summary_md,
        "manifest_json": manifest_json,
    }


def _load_attribute_definitions(path: Path) -> dict[str, AttributeDefinition]:
    rows = _read_workbook_rows(path)
    if len(rows) < 4:
        raise ValueError(f"{path} does not contain attribute definition rows")
    headers = [str(value) if value is not None else "" for value in rows[0]]
    definitions: dict[str, AttributeDefinition] = {}
    for row in rows[3:]:
        data = dict(zip(headers, row))
        key = data.get("key")
        if key in (None, ""):
            continue
        definitions[str(key)] = AttributeDefinition(
            key=str(key),
            value_type=str(data.get("valueType") or ""),
            power_value=_decimal(data.get("powerValue")),
            enabled=int(data.get("enabled") or 0) == 1,
        )
    return definitions


def _load_role_level_rows(path: Path) -> list[dict[str, Decimal]]:
    rows = _read_workbook_rows(path)
    if len(rows) < 6:
        raise ValueError(f"{path} does not contain RoleLv data rows")
    column_specs = _role_level_column_specs(rows[0], rows[2])
    parsed_rows: list[dict[str, Decimal]] = []
    for row in rows[5:]:
        if all(value in (None, "") for value in row[1:]):
            continue
        values: dict[str, Decimal] = {}
        for spec in column_specs:
            if spec.value_type == "BigNumberParts":
                sign_index, coeff_index, exp_index = spec.indexes
                values[spec.key] = _big_number_parts(
                    row[sign_index],
                    row[coeff_index],
                    row[exp_index],
                )
            else:
                values[spec.key] = _decimal(row[spec.indexes[0]])
        parsed_rows.append(values)
    return parsed_rows


def _role_level_column_specs(header_row: tuple[Any, ...], type_row: tuple[Any, ...]) -> list[_ColumnSpec]:
    specs: list[_ColumnSpec] = []
    index = 1
    while index < len(header_row):
        key = header_row[index]
        field_type = type_row[index]
        if key in (None, ""):
            index += 1
            continue
        if field_type == "BigNumberParts":
            specs.append(
                _ColumnSpec(
                    key=str(key),
                    value_type="BigNumberParts",
                    indexes=(index, index + 1, index + 2),
                )
            )
            index += 3
        else:
            specs.append(
                _ColumnSpec(
                    key=str(key),
                    value_type=str(field_type or ""),
                    indexes=(index,),
                )
            )
            index += 1
    return specs


def _calculate_combat_power(
    values: dict[str, Decimal],
    definitions: dict[str, AttributeDefinition],
) -> Decimal:
    power = Decimal(0)
    for key, value in values.items():
        definition = definitions.get(key)
        if definition is None or not definition.enabled or definition.power_value <= 0:
            continue
        normalized = value / Decimal(10000) if definition.value_type == "ratio_bps" else value
        power += normalized * definition.power_value
    return power


def _row_payload(row: RoleLevelRow) -> dict[str, int | str | None]:
    return {
        "level": row.level,
        "exp_req": _format_decimal(row.exp_req),
        "cumulative_exp_to_level_start": _format_decimal(row.cumulative_exp_to_level_start),
        "cumulative_exp_to_next_level": _format_decimal(row.cumulative_exp_to_next_level),
        "combat_power": _format_decimal(row.combat_power),
        "combat_power_delta": None
        if row.combat_power_delta is None
        else _format_decimal(row.combat_power_delta),
    }


def _summary_markdown(result: RoleLevelCurve) -> str:
    level_count = len(result.rows)
    first = result.rows[0] if result.rows else None
    last = result.rows[-1] if result.rows else None
    lines = [
        "# Stone Role Level Baseline",
        "",
        f"RoleLv source: `{result.role_lv_path}`",
        f"Attribute definition source: `{result.attribute_def_path}`",
        "",
        f"Level count: {level_count}",
    ]
    if first is not None and last is not None:
        lines.extend(
            [
                f"Min level: {first.level}",
                f"Max level: {last.level}",
                f"Level 1 combat power: {_format_decimal(first.combat_power)}",
                f"Level {last.level} combat power: {_format_decimal(last.combat_power)}",
                "Cumulative exp to max level start: "
                f"{_format_decimal(last.cumulative_exp_to_level_start)}",
            ]
        )
    lines.extend(
        [
            "",
            "Formula:",
            "",
            "- `BigNumberParts = sign * coeff * 10^exp`",
            "- `big_number/integer contribution = value * powerValue`",
            "- `ratio_bps contribution = value / 10000 * powerValue`",
            "- `combat_power = sum(contributions)`",
            "",
        ]
    )
    return "\n".join(lines)


def _source_manifest(result: RoleLevelCurve) -> dict[str, Any]:
    return {
        "project": "stone",
        "model": "role_level_baseline",
        "sources": {
            "role_lv": str(result.role_lv_path),
            "attribute_def": str(result.attribute_def_path),
        },
        "artifacts": [
            "role_level_curve.json",
            "role_level_curve.csv",
            "role_level_summary.md",
            "source_manifest.json",
        ],
        "formula": {
            "big_number_parts": "sign * coeff * 10^exp",
            "big_number_or_integer": "value * powerValue",
            "ratio_bps": "value / 10000 * powerValue",
        },
        "level_count": len(result.rows),
        "max_level": result.rows[-1].level if result.rows else None,
    }


def _big_number_parts(sign: Any, coeff: Any, exponent: Any) -> Decimal:
    return _decimal(sign) * _decimal(coeff) * (_TEN ** int(_decimal(exponent)))


def _decimal(value: Any) -> Decimal:
    if value in (None, ""):
        return Decimal(0)
    return Decimal(str(value))


def _format_decimal(value: Decimal) -> str:
    if value == 0:
        return "0"
    normalized = value.normalize()
    text = format(normalized, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _read_workbook_rows(path: Path) -> list[tuple[Any, ...]]:
    workbook = load_workbook(path, data_only=True, read_only=True)
    sheet = workbook.active
    return list(sheet.iter_rows(values_only=True))
