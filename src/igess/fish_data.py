from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence


FISH_REQUIRED_TABLES = (
    "tbbarbell",
    "tbbonusfirstlayer",
    "tbfish",
    "tbfishhallupgrade",
    "tbfishrandompool",
    "tbmutation",
    "tbstrengthrebirth",
    "tbtorpedo",
    "tbtrash",
    "tbtrashmanrealm",
    "tbtrashmanrebirth",
    "tbtrashrandompool",
)


class FishDataError(ValueError):
    """Raised when a Fish data snapshot or generated loader is unavailable."""


@dataclass(frozen=True)
class FishDataOverride:
    path: str
    original: Any
    value: Any

    def manifest_entry(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "original": self.original,
            "value": self.value,
        }


class FishLubanProvider(Protocol):
    """Adapter implemented around Luban's generated Python table classes.

    IGESS intentionally does not parse Fish JSON. The generated-code adapter
    owns deserialization, typed field access, and fixture override semantics.
    """

    def load_tables(
        self,
        data_root: Path,
        required_tables: Sequence[str],
    ) -> Mapping[str, Sequence[Any]]: ...

    def apply_overrides(
        self,
        tables: Mapping[str, Sequence[Any]],
        assignments: Sequence[str],
    ) -> tuple[Mapping[str, Sequence[Any]], Sequence[FishDataOverride]]: ...


_LUBAN_TABLE_ATTRIBUTES = {
    "tbbarbell": "TbBarbell",
    "tbbonusfirstlayer": "TbBonusFirstLayer",
    "tbfish": "TbFish",
    "tbfishhallupgrade": "TbFishHallUpgrade",
    "tbfishrandompool": "TbFishRandomPool",
    "tbmutation": "TbMutation",
    "tbstrengthrebirth": "TbStrengthRebirth",
    "tbtorpedo": "TbTorpedo",
    "tbtrash": "TbTrash",
    "tbtrashmanrealm": "TbTrashManRealm",
    "tbtrashmanrebirth": "TbTrashManRebirth",
    "tbtrashrandompool": "TbTrashRandomPool",
}


class GeneratedLubanProvider:
    """Load Fish tables through Luban's generated ``schema.py`` classes."""

    def __init__(self, schema_path: str | Path) -> None:
        self.schema_path = Path(schema_path).expanduser()

    def source_files(self) -> tuple[Path, ...]:
        return (self.schema_path,)

    def load_tables(
        self,
        data_root: Path,
        required_tables: Sequence[str],
    ) -> Mapping[str, Sequence[Any]]:
        schema_path = self._resolved_schema_path()
        module_name = (
            "_igess_fish_luban_"
            + hashlib.sha256(str(schema_path).encode("utf-8")).hexdigest()
        )
        spec = importlib.util.spec_from_file_location(module_name, schema_path)
        if spec is None or spec.loader is None:
            raise FishDataError(f"unable to load Luban schema module: {schema_path}")
        module = importlib.util.module_from_spec(spec)
        try:
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            tables_type = getattr(module, "cfg_Tables")

            def load_json(table_name: str) -> Any:
                path = data_root / f"{table_name}.json"
                with path.open("r", encoding="utf-8") as handle:
                    return json.load(handle)

            generated = tables_type(load_json)
        except FishDataError:
            raise
        except Exception as exc:
            raise FishDataError(
                f"Luban generated loader failed: {type(exc).__name__}: {exc}"
            ) from exc
        finally:
            sys.modules.pop(module_name, None)

        result: dict[str, Sequence[Any]] = {}
        for table_name in required_tables:
            attribute = _LUBAN_TABLE_ATTRIBUTES.get(table_name)
            if attribute is None:
                raise FishDataError(
                    f"Fish table has no generated schema mapping: {table_name}"
                )
            table = getattr(generated, attribute, None)
            getter = getattr(table, "getDataList", None)
            if not callable(getter):
                raise FishDataError(
                    f"generated Fish table is missing getDataList: {attribute}"
                )
            result[table_name] = tuple(getter())
        return result

    def apply_overrides(
        self,
        tables: Mapping[str, Sequence[Any]],
        assignments: Sequence[str],
    ) -> tuple[Mapping[str, Sequence[Any]], Sequence[FishDataOverride]]:
        del tables, assignments
        raise FishDataError(
            "production Luban generated tables do not support direct overrides"
        )

    def _resolved_schema_path(self) -> Path:
        try:
            resolved = self.schema_path.resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise FishDataError(
                f"Luban generated Python schema is unavailable: {self.schema_path}"
            ) from exc
        if not resolved.is_file() or resolved.suffix.lower() != ".py":
            raise FishDataError(
                f"Luban generated Python schema is invalid: {resolved}"
            )
        return resolved


@dataclass(frozen=True)
class FishDataFile:
    name: str
    path: Path
    sha256: str
    size_bytes: int

    def manifest_entry(self, row_count: int) -> dict[str, Any]:
        return {
            "file": self.path.name,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "row_count": row_count,
        }


@dataclass(frozen=True)
class FishLoaderFile:
    path: Path
    sha256: str
    size_bytes: int

    def manifest_entry(self) -> dict[str, Any]:
        return {
            "file": str(self.path),
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }


@dataclass(frozen=True)
class FishDataSnapshot:
    root: Path
    tables: Mapping[str, Sequence[Any]]
    files: tuple[FishDataFile, ...]
    loader_files: tuple[FishLoaderFile, ...]
    production_data: bool
    overrides: tuple[FishDataOverride, ...] = field(default_factory=tuple)

    def table(self, name: str) -> Sequence[Any]:
        try:
            return self.tables[name]
        except KeyError as exc:
            raise FishDataError(f"unknown Fish data table: {name}") from exc

    def model_digest(self, source_digest: str) -> str:
        digest = hashlib.sha256()
        digest.update(b"IGESS_FISH_MODEL_DIGEST_V2\0")
        digest.update(source_digest.encode("ascii"))
        digest.update(b"\0")
        for item in self.files:
            digest.update(item.path.name.encode("utf-8"))
            digest.update(b"\0")
            digest.update(item.sha256.encode("ascii"))
            digest.update(b"\0")
        for item in self.loader_files:
            digest.update(str(item.path).encode("utf-8"))
            digest.update(b"\0")
            digest.update(item.sha256.encode("ascii"))
            digest.update(b"\0")
        digest.update(
            json.dumps(
                [item.manifest_entry() for item in self.overrides],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        )
        return f"sha256:{digest.hexdigest()}"

    def manifest_metadata(self) -> dict[str, Any]:
        table_rows = {
            item.name: len(self.tables[item.name]) for item in self.files
        }
        return {
            "data_root": str(self.root),
            "data_loader": "luban_generated_python",
            "production_data": self.production_data,
            "matches_production_data": self.production_data and not self.overrides,
            "data_files": [
                item.manifest_entry(table_rows[item.name]) for item in self.files
            ],
            "loader_files": [
                item.manifest_entry() for item in self.loader_files
            ],
            "data_summary": {
                "table_count": len(self.files),
                "row_count": sum(table_rows.values()),
                "tables": table_rows,
            },
            "override_details": [item.manifest_entry() for item in self.overrides],
        }


class FishDataLoader:
    """Hash Fish source files and delegate all decoding to generated Luban code."""

    def __init__(self, provider: FishLubanProvider | None) -> None:
        self.provider = provider

    def load(
        self,
        root: str | Path,
        *,
        production_data: bool,
        required_tables: Sequence[str] | None = None,
        overrides: Sequence[str] = (),
    ) -> FishDataSnapshot:
        source_root = Path(root).expanduser()
        try:
            source_root = source_root.resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise FishDataError(f"Fish data root is unavailable: {source_root}") from exc
        if not source_root.is_dir():
            raise FishDataError(f"Fish data root is not a directory: {source_root}")
        if self.provider is None:
            raise FishDataError(
                "Fish Luban generated Python loader is not configured"
            )

        required = tuple(required_tables or FISH_REQUIRED_TABLES)
        if not required or any(
            not isinstance(name, str) or not name or Path(name).name != name
            for name in required
        ):
            raise FishDataError("required Fish table names must be non-empty file stems")

        files: list[FishDataFile] = []
        for name in sorted(required):
            path = source_root / f"{name}.json"
            try:
                resolved = path.resolve(strict=True)
            except OSError as exc:
                raise FishDataError(f"missing required Fish data table: {name}") from exc
            if resolved.parent != source_root or not resolved.is_file():
                raise FishDataError(f"invalid Fish data file: {path}")
            encoded = resolved.read_bytes()
            files.append(
                FishDataFile(
                    name=name,
                    path=resolved,
                    sha256=f"sha256:{hashlib.sha256(encoded).hexdigest()}",
                    size_bytes=len(encoded),
                )
            )

        tables = self.provider.load_tables(source_root, required)
        missing_loaded = sorted(set(required) - set(tables))
        if missing_loaded:
            raise FishDataError(
                "Luban provider did not load required tables: "
                + ", ".join(missing_loaded)
            )
        extra_loaded = sorted(set(tables) - set(required))
        if extra_loaded:
            raise FishDataError(
                "Luban provider returned unrequested tables: "
                + ", ".join(extra_loaded)
            )

        applied: Sequence[FishDataOverride] = ()
        if overrides:
            tables, applied = self.provider.apply_overrides(tables, overrides)
            if len(applied) != len(overrides):
                raise FishDataError(
                    "Luban provider did not account for every requested override"
                )
        loader_files: list[FishLoaderFile] = []
        source_files = getattr(self.provider, "source_files", None)
        if callable(source_files):
            for path_value in source_files():
                path = Path(path_value).expanduser().resolve(strict=True)
                encoded = path.read_bytes()
                loader_files.append(
                    FishLoaderFile(
                        path=path,
                        sha256=(
                            f"sha256:{hashlib.sha256(encoded).hexdigest()}"
                        ),
                        size_bytes=len(encoded),
                    )
                )
        return FishDataSnapshot(
            root=source_root,
            tables=dict(tables),
            files=tuple(files),
            loader_files=tuple(loader_files),
            production_data=production_data,
            overrides=tuple(applied),
        )
