"""Marker-aware, loss-minimizing persistence for workbook-backed entities.

The adapter treats the Luban marker rows as the table schema, rather than
assuming that they occupy rows one through three.  Inspection results contain
only immutable primitives so authoring services can safely use them as a
snapshot of the current source.
"""

from __future__ import annotations

from copy import copy
from dataclasses import dataclass
import os
from pathlib import Path
import stat
import tempfile
from typing import Any, NoReturn
from zipfile import BadZipFile, ZipFile

from openpyxl import load_workbook
from openpyxl.workbook.workbook import Workbook
from openpyxl.worksheet.worksheet import Worksheet

from .change import ModelChange
from .entity_schema import (
    ENTITY_SCHEMAS,
    EntitySchema,
    validate_entity_fields,
)
from .response import AuthoringError


_MARKERS = ("##var", "##", "##type")
_MAX_SOURCE_BYTES = 32 * 1024 * 1024
_MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
_MAX_ARCHIVE_MEMBER_BYTES = 64 * 1024 * 1024
_MAX_ARCHIVE_MEMBERS = 2_048
_MAX_ROWS = 100_000
_MAX_COLUMNS = 1_024
_MAX_CELLS = 2_000_000


@dataclass(frozen=True, slots=True)
class WorkbookRecord:
    """One validated table row represented with immutable ordered fields."""

    entity_id: str
    row: int
    fields: tuple[tuple[str, Any], ...]


@dataclass(frozen=True, slots=True)
class TableInspection:
    """An immutable marker, column, and entity snapshot of one workbook."""

    path: Path
    entity: str
    sheet_name: str
    marker_column: int
    var_row: int
    description_row: int
    type_row: int
    columns: tuple[tuple[str, int], ...]
    records: tuple[WorkbookRecord, ...]
    duplicate_ids: tuple[str, ...]


def inspect_table(path: str | os.PathLike[str]) -> TableInspection:
    """Inspect and validate one canonical workbook without mutating it."""

    source = _coerce_path(path)
    schema = _schema_for_path(source)
    return _inspect_path(source, schema)


def find_duplicate_ids(path: str | os.PathLike[str]) -> list[str]:
    """Return duplicated entity ids once each, in first duplicate order."""

    return list(inspect_table(path).duplicate_ids)


def upsert_workbook_entity(
    path: str | os.PathLike[str],
    change: ModelChange,
) -> bool:
    """Create or update one complete workbook entity and replace atomically.

    The return value is ``False`` for a semantic no-op, in which case the
    workbook is never saved and its bytes remain untouched.
    """

    source = _coerce_path(path)
    schema = _schema_for_path(source)
    if change.entity != schema.entity:
        _source_error(
            "The change entity does not match the workbook",
            "entity_path_mismatch",
            change_entity=change.entity,
            entity=schema.entity,
            path=str(source),
        )

    _check_archive_budget(source)
    workbook = _load(source, read_only=False)
    try:
        inspected = _inspect_open(workbook, source, schema)
        if inspected.duplicate_ids:
            _source_error(
                "Workbook contains duplicate entity ids",
                "duplicate_ids",
                duplicate_ids=list(inspected.duplicate_ids),
                entity=schema.entity,
                path=str(source),
            )

        normalized = validate_entity_fields(
            schema.entity,
            change.id,
            _mutable_workbook_fields(schema, change.fields),
        )
        selected = [record for record in inspected.records if record.entity_id == change.id]
        if selected and _semantic_fields(selected[0].fields) == _semantic_fields(
            tuple(normalized.items())
        ):
            return False

        sheet = workbook.active
        if sheet is None:
            _source_error(
                "Workbook does not contain an active worksheet",
                "missing_active_sheet",
                path=str(source),
            )
        columns = dict(inspected.columns)
        if selected:
            target_row = selected[0].row
        else:
            target_row = max(sheet.max_row, inspected.type_row) + 1
            if target_row > _MAX_ROWS:
                _source_error(
                    "Appending an entity would exceed the workbook row limit",
                    "dimension_limit",
                    actual_rows=target_row,
                    limit_rows=_MAX_ROWS,
                    path=str(source),
                )
            style_row = (
                max((record.row for record in inspected.records if record.row < target_row), default=0)
                or inspected.type_row
            )
            for field in ("id", *schema.field_names):
                column = columns[field]
                sheet.cell(target_row, column)._style = copy(
                    sheet.cell(style_row, column)._style
                )
            sheet.cell(target_row, columns["id"], change.id)

        current = dict(selected[0].fields) if selected else {}
        for field in schema.field_names:
            if selected and _semantic_value(field, current[field]) == _semantic_value(
                field, normalized[field]
            ):
                continue
            sheet.cell(
                target_row,
                columns[field],
                _encode_value(field, normalized[field]),
            )

        _replace_atomically(source, workbook, schema, change)
        return True
    finally:
        workbook.close()


def _coerce_path(path: str | os.PathLike[str]) -> Path:
    if not isinstance(path, (str, os.PathLike)):
        raise AuthoringError(
            "workbook_read_failed",
            "Workbook path must be path-like",
            {"reason": "invalid_path", "value_type": type(path).__name__},
        )
    return Path(path)


def _schema_for_path(path: Path) -> EntitySchema:
    for schema in ENTITY_SCHEMAS.values():
        if schema.storage_kind == "workbook" and schema.storage_name == path.name:
            return schema
    _source_error(
        "Workbook filename does not identify a supported authoring table",
        "unknown_table",
        path=str(path),
        supported=sorted(
            schema.storage_name
            for schema in ENTITY_SCHEMAS.values()
            if schema.storage_kind == "workbook"
        ),
    )


def _inspect_path(path: Path, schema: EntitySchema) -> TableInspection:
    _check_archive_budget(path)
    workbook = _load(path, read_only=True)
    try:
        return _inspect_open(workbook, path, schema)
    finally:
        workbook.close()


def _check_archive_budget(path: Path) -> None:
    try:
        source_size = path.stat().st_size
    except (OSError, ValueError) as error:
        raise AuthoringError(
            "workbook_read_failed",
            "Workbook could not be read",
            {
                "error_type": type(error).__name__,
                "path": str(path),
                "reason": "read_error",
            },
        ) from None
    if source_size > _MAX_SOURCE_BYTES:
        _source_error(
            "Workbook exceeds the compressed source size limit",
            "source_too_large",
            actual_bytes=source_size,
            limit_bytes=_MAX_SOURCE_BYTES,
            path=str(path),
        )
    try:
        with ZipFile(path) as archive:
            members = archive.infolist()
            if len(members) > _MAX_ARCHIVE_MEMBERS:
                _source_error(
                    "Workbook archive contains too many members",
                    "archive_limit",
                    actual_members=len(members),
                    limit_members=_MAX_ARCHIVE_MEMBERS,
                    path=str(path),
                )
            total_size = 0
            for member in members:
                if member.flag_bits & 0x1:
                    _source_error(
                        "Encrypted workbook members are not supported",
                        "unsafe_archive",
                        member=member.filename,
                        path=str(path),
                    )
                if member.file_size > _MAX_ARCHIVE_MEMBER_BYTES:
                    _source_error(
                        "Workbook archive member exceeds the size limit",
                        "archive_limit",
                        actual_bytes=member.file_size,
                        limit_bytes=_MAX_ARCHIVE_MEMBER_BYTES,
                        member=member.filename,
                        path=str(path),
                    )
                total_size += member.file_size
                if total_size > _MAX_ARCHIVE_BYTES:
                    _source_error(
                        "Workbook expanded archive exceeds the size limit",
                        "archive_limit",
                        actual_bytes=total_size,
                        limit_bytes=_MAX_ARCHIVE_BYTES,
                        path=str(path),
                    )
    except AuthoringError:
        raise
    except (BadZipFile, OSError, ValueError, RuntimeError) as error:
        raise AuthoringError(
            "invalid_workbook_source",
            "Workbook is not a readable OOXML archive",
            {
                "error_type": type(error).__name__,
                "path": str(path),
                "reason": "corrupt_workbook",
            },
        ) from None


def _load(path: Path, *, read_only: bool) -> Workbook:
    try:
        return load_workbook(
            path,
            read_only=read_only,
            data_only=False,
            keep_links=False,
        )
    except Exception as error:
        raise AuthoringError(
            "invalid_workbook_source",
            "Workbook could not be opened safely",
            {
                "error_type": type(error).__name__,
                "path": str(path),
                "reason": "corrupt_workbook",
            },
        ) from None


def _inspect_open(
    workbook: Workbook,
    path: Path,
    schema: EntitySchema,
) -> TableInspection:
    sheet = workbook.active
    if sheet is None:
        _source_error(
            "Workbook does not contain an active worksheet",
            "missing_active_sheet",
            path=str(path),
        )
    _validate_dimensions(sheet, path)
    marker_positions: dict[str, list[tuple[int, int]]] = {
        marker: [] for marker in _MARKERS
    }
    for row in sheet.iter_rows():
        for cell in row:
            if cell.value in marker_positions:
                marker_positions[cell.value].append((cell.row, cell.column))

    for marker in _MARKERS:
        positions = marker_positions[marker]
        if not positions:
            _source_error(
                "Workbook is missing a Luban marker",
                "missing_marker",
                marker=marker,
                path=str(path),
            )
        if len(positions) != 1:
            _source_error(
                "Workbook contains a duplicate Luban marker",
                "duplicate_marker",
                marker=marker,
                path=str(path),
                positions=[list(position) for position in positions[:16]],
            )

    var_row, marker_column = marker_positions["##var"][0]
    description_row, description_column = marker_positions["##"][0]
    type_row, type_column = marker_positions["##type"][0]
    if not (
        marker_column == description_column == type_column
        and var_row < description_row < type_row
    ):
        _source_error(
            "Workbook marker rows do not form one coherent table schema",
            "incoherent_markers",
            marker_positions=[
                [marker, *marker_positions[marker][0]] for marker in _MARKERS
            ],
            path=str(path),
        )

    header_columns: dict[str, int] = {}
    for column in range(1, sheet.max_column + 1):
        if column == marker_column:
            continue
        raw_header = sheet.cell(var_row, column).value
        if raw_header in (None, ""):
            continue
        header = str(raw_header)
        if header in header_columns:
            _source_error(
                "Workbook contains a duplicate header",
                "duplicate_header",
                column=column,
                first_column=header_columns[header],
                header=header,
                path=str(path),
            )
        header_columns[header] = column

    expected_fields = ("id", *schema.field_names)
    for field in expected_fields:
        if field not in header_columns:
            _source_error(
                "Workbook is missing a required schema column",
                "missing_column",
                column=field,
                entity=schema.entity,
                path=str(path),
            )
        column = header_columns[field]
        actual_type = sheet.cell(type_row, column).value
        expected_type = _expected_column_type(schema.entity, field)
        if actual_type != expected_type:
            _source_error(
                "Workbook schema column has the wrong Luban type",
                "wrong_column_type",
                actual=actual_type if isinstance(actual_type, (str, int, bool)) else None,
                column=field,
                expected=expected_type,
                path=str(path),
            )

    columns = tuple((field, header_columns[field]) for field in expected_fields)
    records: list[WorkbookRecord] = []
    duplicates: list[str] = []
    reported: set[str] = set()
    seen: set[str] = set()
    id_column = header_columns["id"]
    field_columns = {field: header_columns[field] for field in schema.field_names}
    for row_index in range(type_row + 1, sheet.max_row + 1):
        raw_id = sheet.cell(row_index, id_column).value
        raw_fields = {
            field: sheet.cell(row_index, column).value
            for field, column in field_columns.items()
        }
        if raw_id in (None, ""):
            if any(value not in (None, "") for value in raw_fields.values()):
                _source_error(
                    "Workbook row has schema values but no entity id",
                    "missing_id",
                    entity=schema.entity,
                    path=str(path),
                    row=row_index,
                )
            continue
        entity_id = str(raw_id)
        decoded = {
            field: _decode_value(field, raw_fields[field])
            for field in schema.field_names
        }
        try:
            normalized = validate_entity_fields(schema.entity, entity_id, decoded)
        except AuthoringError as error:
            _source_error(
                "Workbook contains an invalid entity row",
                "invalid_entity_row",
                allowed=error.details.get("allowed", ()),
                entity=schema.entity,
                field=error.details.get("field"),
                id=entity_id,
                path=str(path),
                row=row_index,
                validation_code=error.code,
                validation_message=error.message,
                value=error.details.get("value"),
            )
        record_fields = tuple(
            (field, _immutable_value(field, normalized[field]))
            for field in schema.field_names
        )
        records.append(WorkbookRecord(entity_id, row_index, record_fields))
        if entity_id in seen and entity_id not in reported:
            duplicates.append(entity_id)
            reported.add(entity_id)
        seen.add(entity_id)

    return TableInspection(
        path=path,
        entity=schema.entity,
        sheet_name=sheet.title,
        marker_column=marker_column,
        var_row=var_row,
        description_row=description_row,
        type_row=type_row,
        columns=columns,
        records=tuple(records),
        duplicate_ids=tuple(duplicates),
    )


def _validate_dimensions(sheet: Worksheet, path: Path) -> None:
    rows = sheet.max_row
    columns = sheet.max_column
    if rows > _MAX_ROWS or columns > _MAX_COLUMNS or rows * columns > _MAX_CELLS:
        _source_error(
            "Workbook dimensions exceed the authoring safety limit",
            "dimension_limit",
            actual_columns=columns,
            actual_rows=rows,
            limit_cells=_MAX_CELLS,
            limit_columns=_MAX_COLUMNS,
            limit_rows=_MAX_ROWS,
            path=str(path),
        )


def _expected_column_type(entity: str, field: str) -> str:
    if entity == "prestige_layer" and field == "reset_resources":
        return "(list#sep=;),string"
    return "string"


def _decode_value(field: str, value: Any) -> Any:
    if field == "reset_resources":
        if value in (None, ""):
            return []
        return [item for item in str(value).split(";") if item]
    if value is None:
        return ""
    return str(value)


def _encode_value(field: str, value: Any) -> str:
    if field == "reset_resources":
        return ";".join(value)
    return str(value)


def _immutable_value(field: str, value: Any) -> Any:
    if field == "reset_resources":
        return tuple(value)
    return value


def _mutable_workbook_fields(
    schema: EntitySchema,
    fields: Any,
) -> dict[str, Any]:
    """Thaw the one list-valued workbook field frozen by ``ModelChange``."""

    result = dict(fields)
    if schema.entity == "prestige_layer" and "reset_resources" in result:
        result["reset_resources"] = list(result["reset_resources"])
    return result


def _semantic_value(field: str, value: Any) -> Any:
    if field == "reset_resources":
        return tuple(value)
    return str(value)


def _semantic_fields(fields: tuple[tuple[str, Any], ...]) -> tuple[tuple[str, Any], ...]:
    return tuple((field, _semantic_value(field, value)) for field, value in fields)


def _replace_atomically(
    path: Path,
    workbook: Workbook,
    schema: EntitySchema,
    change: ModelChange,
) -> None:
    temporary: Path | None = None
    phase = "temp_write"
    candidate_bytes: bytes | None = None
    try:
        source_mode = stat.S_IMODE(path.stat().st_mode)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp.xlsx",
            dir=path.parent,
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        workbook.save(temporary)
        os.chmod(temporary, source_mode)
        candidate_bytes = temporary.read_bytes()

        phase = "reload"
        reloaded = _inspect_path(temporary, schema)
        matches = [record for record in reloaded.records if record.entity_id == change.id]
        if len(matches) != 1 or _semantic_fields(matches[0].fields) != _semantic_fields(
            tuple(change.fields.items())
        ):
            _source_error(
                "Reloaded workbook does not contain the exact upserted entity",
                "reload_mismatch",
                entity=change.entity,
                id=change.id,
                path=str(path),
            )

        phase = "replace"
        try:
            os.replace(temporary, path)
        except BaseException:
            if candidate_bytes is not None and _path_has_exact_bytes(path, candidate_bytes):
                return
            raise
        temporary = None
    except Exception as error:
        reason = {
            "temp_write": "temp_write_error",
            "reload": "reload_error",
            "replace": "replace_error",
        }[phase]
        raise AuthoringError(
            "workbook_write_failed",
            "Workbook candidate could not be replaced atomically",
            {
                "error_type": type(error).__name__,
                "path": str(path),
                "reason": reason,
            },
        ) from None
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def _path_has_exact_bytes(path: Path, expected: bytes) -> bool:
    try:
        return path.stat().st_size == len(expected) and path.read_bytes() == expected
    except (OSError, MemoryError, ValueError):
        return False


def _source_error(message: str, reason: str, **details: Any) -> NoReturn:
    raise AuthoringError(
        "invalid_workbook_source",
        message,
        {"reason": reason, **details},
    )


__all__ = [
    "TableInspection",
    "WorkbookRecord",
    "find_duplicate_ids",
    "inspect_table",
    "upsert_workbook_entity",
]
