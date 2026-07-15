"""Canonical entity metadata and exact field validation for authoring changes."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import math
import re
from types import MappingProxyType
from typing import Any, Literal, Mapping, NoReturn

from ..formula import FormulaCompileError, FormulaEngine
from ..numbers import SimNumber
from .response import AuthoringError


_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_DECIMAL_RE = re.compile(r"^-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?$")
_CONDITION_RE = re.compile(
    r"^owned\(([A-Za-z0-9_.-]+)\)\s*(>=|<=|==|>|<)\s*(\d+)$"
)
_UPGRADE_TARGET_RE = re.compile(
    r"^generator:(?:\*|[A-Za-z0-9_.-]+)\.output$"
)

_MODIFIER_STAGES = ("flat", "add_pct", "mult", "exp")
_BEHAVIOR_POLICY_TYPES = (
    "cheap_unlock_first",
    "fastest_payback",
    "new_content_bias",
)
_PRESTIGE_POLICIES = ("conservative", "efficient_reset", "milestone_based")
_TIME_MODES = ("tick", "analytic")
_SCENARIO_OUTPUTS = (
    "resource_curve",
    "purchase_timeline",
    "unlock_timeline",
    "prestige_timeline",
    "bottleneck_report",
)


@dataclass(frozen=True, slots=True)
class FieldSpec:
    """One ordered field in an authoring entity contract."""

    name: str
    value_type: str
    required: bool = True
    allowed: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EntitySchema:
    """Immutable storage and field metadata for an authoring entity."""

    entity: str
    storage_kind: Literal["workbook", "yaml"]
    storage_name: str
    fields: tuple[FieldSpec, ...]

    @property
    def field_names(self) -> tuple[str, ...]:
        return tuple(item.name for item in self.fields)

    @property
    def required_fields(self) -> tuple[str, ...]:
        return tuple(item.name for item in self.fields if item.required)

    @property
    def optional_fields(self) -> tuple[str, ...]:
        return tuple(item.name for item in self.fields if not item.required)


@dataclass(frozen=True, slots=True)
class ValidationContext:
    """Existing source fields needed for cross-entity field validation."""

    rng_tables: Mapping[str, Mapping[str, Any]] = field(
        default_factory=lambda: MappingProxyType({})
    )


def _field(
    name: str,
    value_type: str,
    *,
    required: bool = True,
    allowed: tuple[str, ...] = (),
) -> FieldSpec:
    return FieldSpec(name, value_type, required, allowed)


def _schema(
    entity: str,
    storage_kind: Literal["workbook", "yaml"],
    storage_name: str,
    *fields: FieldSpec,
) -> EntitySchema:
    return EntitySchema(entity, storage_kind, storage_name, tuple(fields))


_SCHEMAS = (
    _schema(
        "resource",
        "workbook",
        "resources.xlsx",
        _field("name", "text"),
        _field("dimension", "id"),
    ),
    _schema(
        "generator",
        "workbook",
        "generators.xlsx",
        _field("name", "text"),
        _field("generator_type", "id"),
        _field("output_resource", "id"),
        _field("source_type", "id"),
        _field("base_output", "nonnegative_decimal"),
        _field("base_cost", "nonnegative_decimal"),
        _field("cost_resource", "id"),
        _field("cost_growth", "positive_decimal"),
        _field("unlock_condition", "condition"),
    ),
    _schema(
        "activity",
        "workbook",
        "activities.xlsx",
        _field("name", "text"),
        _field("source_type", "id"),
        _field("unlock_condition", "condition"),
    ),
    _schema(
        "activity_output",
        "workbook",
        "activity_outputs.xlsx",
        _field("activity_id", "id"),
        _field("output_resource", "id"),
        _field("amount_per_second", "positive_decimal"),
    ),
    _schema(
        "upgrade",
        "workbook",
        "upgrades.xlsx",
        _field("name", "text"),
        _field("target", "upgrade_target"),
        _field("modifier_type", "id"),
        _field("value", "decimal"),
        _field("cost_resource", "id"),
        _field("base_cost", "nonnegative_decimal"),
        _field("unlock_condition", "condition"),
    ),
    _schema(
        "constant",
        "workbook",
        "constants.xlsx",
        _field("value", "decimal"),
    ),
    _schema(
        "milestone",
        "workbook",
        "milestones.xlsx",
        _field("name", "text"),
        _field("condition", "condition"),
        _field("reward_resource", "id"),
        _field("reward_amount", "decimal"),
    ),
    _schema(
        "prestige_layer",
        "workbook",
        "prestige_layers.xlsx",
        _field("name", "text"),
        _field("trigger_resource", "id"),
        _field("reward_resource", "id"),
        _field("formula", "id"),
        _field("divisor", "positive_decimal"),
        _field("exponent", "positive_decimal"),
        _field("min_gain", "nonnegative_decimal"),
        _field("reset_resources", "list_id"),
        _field("unlock_condition", "condition"),
    ),
    _schema(
        "formula",
        "yaml",
        "formulas",
        _field("args", "list_id"),
        _field("expr", "text"),
    ),
    _schema(
        "generator_type",
        "yaml",
        "generator_types",
        _field("cost_formula", "id"),
        _field("production_formula", "id"),
    ),
    _schema(
        "source_type",
        "yaml",
        "source_types",
        _field("description", "text"),
    ),
    _schema(
        "modifier_type",
        "yaml",
        "modifier_types",
        _field("stage", "enum", allowed=_MODIFIER_STAGES),
    ),
    _schema(
        "behavior_policy",
        "yaml",
        "behavior_policies",
        _field("type", "enum", allowed=_BEHAVIOR_POLICY_TYPES),
        _field("lookahead_depth", "nonnegative_int", required=False),
        _field("include_unlock_chain_value", "bool", required=False),
    ),
    _schema(
        "session_pattern",
        "yaml",
        "session_patterns",
        _field("offline_every_seconds", "positive_int"),
        _field("offline_duration_seconds", "nonnegative_int"),
    ),
    _schema(
        "player_profile",
        "yaml",
        "player_profiles",
        _field("source_efficiency", "map_id_nonnegative_decimal"),
        _field("behavior_policy", "id"),
        _field("session_pattern", "id"),
        _field("prestige_policy", "enum", allowed=_PRESTIGE_POLICIES),
        _field("activity_weights", "map_id_nonnegative_decimal", required=False),
        _field("luck", "positive_decimal", required=False),
    ),
    _schema(
        "scenario",
        "yaml",
        "scenarios",
        _field("duration_hours", "positive_decimal"),
        _field("time_mode", "enum", allowed=_TIME_MODES),
        _field("profiles", "nonempty_list_id"),
        _field("start_state", "enum", allowed=("new_player",)),
        _field("record_interval_seconds", "positive_int"),
        _field("outputs", "output_list"),
    ),
    _schema(
        "rng_table",
        "yaml",
        "rng_tables",
        _field("algorithm", "enum", allowed=("rarity_score",)),
        _field("rarities", "rng_rarities"),
    ),
    _schema(
        "rng_scenario",
        "yaml",
        "rng_scenarios",
        _field("table", "id"),
        _field("rolls", "positive_int"),
        _field("trials", "positive_int"),
        _field("profiles", "nonempty_list_id"),
        _field("event_threshold", "id", required=False),
    ),
    _schema(
        "regression_gate",
        "yaml",
        "regression_gates",
        _field("max_unlock_delay_pct", "map_text_nonnegative_decimal", required=False),
        _field("max_payback_seconds", "map_text_nonnegative_decimal", required=False),
        _field("min_prestige_gain", "map_id_nonnegative_decimal", required=False),
    ),
)

ENTITY_SCHEMAS: Mapping[str, EntitySchema] = MappingProxyType(
    {schema.entity: schema for schema in _SCHEMAS}
)


def get_entity_schema(entity: str) -> EntitySchema:
    """Return immutable metadata for a supported version-1 entity."""

    schema = ENTITY_SCHEMAS.get(entity)
    if schema is None:
        _invalid(
            entity=entity,
            entity_id=None,
            field="entity",
            value=entity,
            allowed=tuple(ENTITY_SCHEMAS),
            message=f"Unsupported authoring entity: {entity!r}",
        )
    return schema


def validate_entity_fields(
    entity: str,
    entity_id: str,
    fields: Mapping[str, Any],
    *,
    context: ValidationContext | None = None,
    require_complete: bool = True,
) -> dict[str, Any]:
    """Validate and normalize one entity's fields without mutating the input."""

    schema = ENTITY_SCHEMAS.get(entity)
    if schema is None:
        _invalid(
            entity=entity,
            entity_id=entity_id,
            field="entity",
            value=entity,
            allowed=tuple(ENTITY_SCHEMAS),
            message=f"Unsupported authoring entity: {entity!r}",
        )
    if not _is_id(entity_id):
        _invalid(
            entity=entity,
            entity_id=entity_id,
            field="id",
            value=entity_id,
            allowed=("[A-Za-z0-9_.-]+",),
            message="Entity id must match [A-Za-z0-9_.-]+",
        )
    if type(fields) is not dict:
        _invalid(
            entity=entity,
            entity_id=entity_id,
            field="fields",
            value=fields,
            allowed=("mapping",),
            message="Entity fields must be a native mapping",
        )
    if "id" in fields:
        _invalid(
            entity=entity,
            entity_id=entity_id,
            field="id",
            value=fields["id"],
            allowed=("envelope id only",),
            message="The id belongs in the change envelope, not fields",
        )

    specifications = {item.name: item for item in schema.fields}
    for name, value in fields.items():
        if name not in specifications:
            _invalid(
                entity=entity,
                entity_id=entity_id,
                field=str(name),
                value=value,
                allowed=schema.field_names,
                message=f"Unknown field {name!r} for {entity}",
            )

    if require_complete:
        for name in schema.required_fields:
            if name not in fields:
                _invalid(
                    entity=entity,
                    entity_id=entity_id,
                    field=name,
                    value=None,
                    allowed=("required field",),
                    message=f"Missing required field {name!r} for {entity}",
                )

    normalized: dict[str, Any] = {}
    for name, value in fields.items():
        spec = specifications[name]
        normalized[name] = _validate_value(entity, entity_id, spec, value)

    _validate_formula(entity, entity_id, normalized)
    _validate_rng_threshold(entity, entity_id, normalized, context)
    if entity == "regression_gate" and require_complete:
        if not any(type(value) is dict and value for value in normalized.values()):
            _invalid(
                entity=entity,
                entity_id=entity_id,
                field="fields",
                value=fields,
                allowed=(
                    "at least one non-empty max_unlock_delay_pct, "
                    "max_payback_seconds, or min_prestige_gain map"
                ,),
                message="Regression gate requires at least one non-empty rule map",
            )
    return normalized


def _validate_value(
    entity: str,
    entity_id: str,
    spec: FieldSpec,
    value: Any,
) -> Any:
    kind = spec.value_type
    if kind == "id":
        if _is_id(value):
            return value
        allowed: tuple[str, ...] = ("[A-Za-z0-9_.-]+",)
    elif kind == "text":
        if _is_text(value):
            return value
        allowed = ("non-empty UTF-8 string",)
    elif kind == "bool":
        if type(value) is bool:
            return value
        allowed = ("true", "false")
    elif kind in {"positive_int", "nonnegative_int"}:
        minimum = 1 if kind == "positive_int" else 0
        if type(value) is int and value >= minimum:
            return value
        allowed = (f"native integer >= {minimum}",)
    elif kind in {"decimal", "positive_decimal", "nonnegative_decimal"}:
        minimum = None
        strict = False
        if kind == "positive_decimal":
            minimum, strict = SimNumber.zero(), True
        elif kind == "nonnegative_decimal":
            minimum = SimNumber.zero()
        parsed = _parse_exact_decimal(value)
        if parsed is not None and (
            minimum is None
            or parsed > minimum
            or (not strict and parsed == minimum)
        ):
            return str(value) if type(value) is int else value
        allowed = {
            "decimal": ("integer token or exact base-10 decimal string",),
            "positive_decimal": ("exact decimal > 0",),
            "nonnegative_decimal": ("exact decimal >= 0",),
        }[kind]
    elif kind == "condition":
        if value == "always" or (
            isinstance(value, str) and _CONDITION_RE.fullmatch(value) is not None
        ):
            return value
        allowed = ("always", "owned(<generator_id>) <op> <non-negative integer>")
    elif kind == "upgrade_target":
        if isinstance(value, str) and _UPGRADE_TARGET_RE.fullmatch(value):
            return value
        allowed = ("generator:<id>.output", "generator:*.output")
    elif kind == "enum":
        if isinstance(value, str) and value in spec.allowed:
            return value
        allowed = spec.allowed
    elif kind in {"list_id", "nonempty_list_id"}:
        if type(value) is list and (
            kind == "list_id" or bool(value)
        ) and all(_is_id(item) for item in value):
            return list(value)
        allowed = (("non-empty " if kind == "nonempty_list_id" else "") + "native list[id]",)
    elif kind == "output_list":
        if type(value) is list and all(
            isinstance(item, str) and item in _SCENARIO_OUTPUTS for item in value
        ):
            return list(value)
        allowed = _SCENARIO_OUTPUTS
    elif kind in {"map_id_nonnegative_decimal", "map_text_nonnegative_decimal"}:
        normalized = _validate_decimal_map(value, id_keys=kind.startswith("map_id"))
        if normalized is not None:
            return normalized
        allowed = (
            "native map[id, exact decimal >= 0]"
            if kind.startswith("map_id")
            else "native map[non-empty text, exact decimal >= 0]",
        )
    elif kind == "rng_rarities":
        normalized = _validate_rng_rarities(value)
        if normalized is not None:
            return normalized
        allowed = ("non-empty native map[id, unique exact decimal > 0]",)
    else:  # pragma: no cover - schema construction is tested exhaustively
        raise RuntimeError(f"Unknown field validator: {kind}")

    _invalid(
        entity=entity,
        entity_id=entity_id,
        field=spec.name,
        value=value,
        allowed=allowed,
        message=f"Invalid value for {entity}.{spec.name}",
    )


def _is_id(value: Any) -> bool:
    return isinstance(value, str) and _ID_RE.fullmatch(value) is not None


def _is_text(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _parse_exact_decimal(value: Any) -> SimNumber | None:
    if type(value) is int:
        text = str(value)
    elif isinstance(value, str) and _DECIMAL_RE.fullmatch(value):
        text = value
    else:
        return None
    try:
        return SimNumber.parse(text)
    except (ArithmeticError, ValueError):
        return None


def _exact_decimal_value(value: Any) -> Decimal | None:
    if type(value) is int:
        text = str(value)
    elif isinstance(value, str) and _DECIMAL_RE.fullmatch(value):
        text = value
    else:
        return None
    try:
        parsed = Decimal(text)
    except InvalidOperation:
        return None
    return parsed if parsed.is_finite() else None


def _validate_decimal_map(value: Any, *, id_keys: bool) -> dict[str, str] | None:
    if type(value) is not dict:
        return None
    normalized: dict[str, str] = {}
    for key, item in value.items():
        valid_key = _is_id(key) if id_keys else _is_text(key)
        parsed = _parse_exact_decimal(item)
        if not valid_key or parsed is None or parsed < SimNumber.zero():
            return None
        normalized[key] = str(item) if type(item) is int else item
    return normalized


def _validate_rng_rarities(value: Any) -> dict[str, str] | None:
    if type(value) is not dict or not value:
        return None
    parsed_rows: list[tuple[Decimal, str, str]] = []
    seen: set[Decimal] = set()
    for rarity_id, denominator in value.items():
        domain_value = _parse_exact_decimal(denominator)
        exact_value = _exact_decimal_value(denominator)
        if (
            not _is_id(rarity_id)
            or domain_value is None
            or domain_value <= SimNumber.zero()
            or exact_value is None
            or exact_value in seen
        ):
            return None
        seen.add(exact_value)
        normalized = str(denominator) if type(denominator) is int else denominator
        parsed_rows.append((exact_value, rarity_id, normalized))
    parsed_rows.sort(key=lambda row: row[0])
    return {rarity_id: denominator for _, rarity_id, denominator in parsed_rows}


def _validate_formula(entity: str, entity_id: str, fields: Mapping[str, Any]) -> None:
    if entity != "formula" or "args" not in fields or "expr" not in fields:
        return
    args = fields["args"]
    try:
        FormulaEngine.compile(entity_id, args, fields["expr"])
    except FormulaCompileError as exc:
        _invalid(
            entity=entity,
            entity_id=entity_id,
            field="expr",
            value=fields["expr"],
            allowed=("safe arithmetic formula using declared args",),
            message=str(exc),
        )


def _validate_rng_threshold(
    entity: str,
    entity_id: str,
    fields: Mapping[str, Any],
    context: ValidationContext | None,
) -> None:
    if (
        entity != "rng_scenario"
        or context is None
        or "table" not in fields
        or "event_threshold" not in fields
    ):
        return
    table_fields = context.rng_tables.get(fields["table"])
    if table_fields is None:
        return
    rarities = table_fields.get("rarities")
    if isinstance(rarities, Mapping):
        allowed = tuple(rarities)
    else:
        allowed = ()
    if fields["event_threshold"] not in allowed:
        _invalid(
            entity=entity,
            entity_id=entity_id,
            field="event_threshold",
            value=fields["event_threshold"],
            allowed=allowed,
            message=(
                f"Event threshold {fields['event_threshold']!r} is not a rarity "
                f"in RNG table {fields['table']!r}"
            ),
        )


def _invalid(
    *,
    entity: Any,
    entity_id: Any,
    field: str,
    value: Any,
    allowed: tuple[Any, ...],
    message: str,
) -> NoReturn:
    raise AuthoringError(
        "invalid_change",
        message,
        {
            "entity": _json_safe_diagnostic(entity),
            "id": _json_safe_diagnostic(entity_id),
            "field": _json_safe_diagnostic(field),
            "value": _json_safe_diagnostic(value),
            "allowed": [_json_safe_diagnostic(item) for item in allowed],
        },
    )


def _json_safe_diagnostic(
    value: Any,
    *,
    _seen: set[int] | None = None,
    _depth: int = 0,
) -> Any:
    """Return a bounded, strict-JSON-safe representation of diagnostic input."""

    if value is None or type(value) in {bool, int, str}:
        return value
    if type(value) is float:
        if math.isnan(value):
            return "NaN"
        if math.isinf(value):
            return "Infinity" if value > 0 else "-Infinity"
        return value
    if isinstance(value, Decimal):
        return str(value)
    if _depth >= 16:
        return f"<{type(value).__name__}:max-depth>"

    if type(value) in {dict, list}:
        seen = _seen if _seen is not None else set()
        marker = id(value)
        if marker in seen:
            return f"<{type(value).__name__}:cycle>"
        seen.add(marker)
        try:
            if type(value) is list:
                items = [
                    _json_safe_diagnostic(item, _seen=seen, _depth=_depth + 1)
                    for item in value[:100]
                ]
                if len(value) > 100:
                    items.append(f"<{len(value) - 100} more items>")
                return items

            result: dict[str, Any] = {}
            for index, (key, item) in enumerate(value.items()):
                if index >= 100:
                    result["<truncated>"] = f"{len(value) - 100} more items"
                    break
                safe_key = key if isinstance(key, str) else str(_json_safe_diagnostic(key))
                result[safe_key] = _json_safe_diagnostic(
                    item,
                    _seen=seen,
                    _depth=_depth + 1,
                )
            return result
        finally:
            seen.remove(marker)

    return f"<{type(value).__name__}>"


__all__ = [
    "ENTITY_SCHEMAS",
    "EntitySchema",
    "FieldSpec",
    "ValidationContext",
    "get_entity_schema",
    "validate_entity_fields",
]
