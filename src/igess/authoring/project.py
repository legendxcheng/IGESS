"""Authoring project discovery, canonical paths, and source digests."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
from typing import Any, NoReturn

from openpyxl import load_workbook

from .response import AuthoringError


_PROJECT_PATHS = (
    ("economy.yaml", "file", "project config", "project_config"),
    ("Datas", "directory", "source tables", "source_tables"),
    ("luban_exports", "directory", "runtime exports", "runtime_exports"),
)


@dataclass(frozen=True, slots=True)
class AuthoringProject:
    """The canonical locations belonging to one incremental-authoring project."""

    root: Path
    config: Path
    datas: Path
    exports: Path
    runs: Path
    legacy_runs: Path
    reports: Path
    changes: Path
    transactions: Path
    lock: Path

    @classmethod
    def discover(cls, root: str | Path) -> AuthoringProject:
        """Discover a project without recursively searching below ``root``."""

        canonical_root = Path(root).expanduser().resolve()
        discovered = {
            name: _require_project_path(canonical_root / name, expected, role, code_prefix)
            for name, expected, role, code_prefix in _PROJECT_PATHS
        }
        metadata = canonical_root / ".igess"
        return cls(
            root=canonical_root,
            config=discovered["economy.yaml"],
            datas=discovered["Datas"],
            exports=discovered["luban_exports"],
            runs=canonical_root / "runs",
            legacy_runs=metadata / "runs",
            reports=canonical_root / "reports",
            changes=canonical_root / "changes",
            transactions=metadata / "transactions",
            lock=metadata / "model.lock",
        )

    def read_run_roots(self) -> list[Path]:
        """Return readable run registries, preferring the modern root."""

        result: list[Path] = []
        identities: set[str] = set()
        for candidate in (self.runs, self.legacy_runs):
            if not candidate.is_dir():
                continue
            identity = os.path.normcase(str(candidate.resolve()))
            if identity in identities or any(_same_file(candidate, existing) for existing in result):
                continue
            identities.add(identity)
            result.append(candidate)
        return result

    def model_digest(self) -> str:
        """Hash exactly the config, registry, and registered source workbooks."""

        registry = self.datas / "__tables__.xlsx"
        registrations = _read_registration_paths(registry)
        source_paths = _validate_registration_paths(self, registry, registrations)
        digest = hashlib.sha256()
        paths = [self.config, registry, *source_paths]
        for path in sorted(paths, key=lambda item: _root_relative_posix(self.root, item)):
            relative = _root_relative_posix(self.root, path)
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            try:
                digest.update(path.read_bytes())
            except OSError as error:
                _registry_error(
                    "Unable to read a model source file",
                    "source_read_error",
                    registry,
                    source_path=str(path),
                    error_type=type(error).__name__,
                )
        return f"sha256:{digest.hexdigest()}"


def _require_project_path(path: Path, expected: str, role: str, code_prefix: str) -> Path:
    if not path.exists():
        raise AuthoringError(
            f"{code_prefix}_missing",
            f"Required {role} is missing: {path}",
            {
                "expected": expected,
                "path": str(path),
                "reason": "missing",
                "role": role,
            },
        )
    matches = path.is_file() if expected == "file" else path.is_dir()
    if not matches:
        raise AuthoringError(
            f"{code_prefix}_wrong_type",
            f"Required {role} is not a {expected}: {path}",
            {
                "expected": expected,
                "path": str(path),
                "reason": "wrong_type",
                "role": role,
            },
        )
    return path


def _same_file(first: Path, second: Path) -> bool:
    try:
        return os.path.samefile(first, second)
    except OSError:
        return False


def _read_registration_paths(registry: Path) -> list[tuple[int, Any]]:
    if not registry.exists():
        _registry_error("Source registry is missing", "registry_missing", registry)
    if not registry.is_file():
        _registry_error("Source registry is not a file", "registry_wrong_type", registry)

    workbook = None
    try:
        workbook = load_workbook(registry, read_only=True, data_only=True)
        sheet = workbook.active
        if (
            sheet["A1"].value != "##var"
            or sheet["A2"].value != "##"
            or sheet["A3"].value != "##type"
        ):
            _registry_error(
                "Source registry has invalid Luban marker rows",
                "malformed_registry",
                registry,
            )
        headers = [cell.value for cell in sheet[1]][1:]
        try:
            path_index = headers.index("path") + 1
        except ValueError:
            _registry_error(
                "Source registry is missing the path column",
                "malformed_registry",
                registry,
            )

        registrations: list[tuple[int, Any]] = []
        table_index = headers.index("table") + 1 if "table" in headers else None
        for row_number, values in enumerate(
            sheet.iter_rows(min_row=4, values_only=True),
            start=4,
        ):
            if table_index is not None and values[table_index] in (None, ""):
                continue
            registrations.append((row_number, values[path_index]))
        return registrations
    except AuthoringError:
        raise
    except Exception as error:
        _registry_error(
            "Source registry could not be read",
            "malformed_registry",
            registry,
            error_type=type(error).__name__,
        )
    finally:
        if workbook is not None:
            workbook.close()


def _validate_registration_paths(
    project: AuthoringProject,
    registry: Path,
    registrations: list[tuple[int, Any]],
) -> list[Path]:
    datas_root = project.datas.resolve()
    identities: set[str] = set()
    result: list[Path] = []
    for row, value in registrations:
        if not isinstance(value, str) or not value.strip():
            _registry_error(
                "A source registration has no workbook path",
                "missing_registration_path",
                registry,
                row=row,
            )
        try:
            relative = Path(value)
        except (TypeError, ValueError) as error:
            _registry_error(
                "A source registration path is invalid",
                "unsafe_registration_path",
                registry,
                row=row,
                registration_path=str(value),
                error_type=type(error).__name__,
            )
        if relative.is_absolute() or ".." in relative.parts:
            _registry_error(
                "A source registration path must stay below Datas",
                "unsafe_registration_path",
                registry,
                row=row,
                registration_path=value,
            )

        try:
            source = (project.datas / relative).resolve()
            source.relative_to(datas_root)
        except (OSError, ValueError) as error:
            _registry_error(
                "A source registration path escapes Datas",
                "unsafe_registration_path",
                registry,
                row=row,
                registration_path=value,
                error_type=type(error).__name__,
            )

        identity = os.path.normcase(str(source))
        if identity in identities:
            _registry_error(
                "A workbook path is registered more than once",
                "duplicate_registration_path",
                registry,
                row=row,
                registration_path=value,
            )
        identities.add(identity)
        if not source.exists():
            _registry_error(
                "A registered source workbook is missing",
                "registered_source_missing",
                registry,
                row=row,
                registration_path=value,
                source_path=str(source),
            )
        if not source.is_file():
            _registry_error(
                "A registered source workbook is not a file",
                "registered_source_wrong_type",
                registry,
                row=row,
                registration_path=value,
                source_path=str(source),
            )
        result.append(source)
    return result


def _root_relative_posix(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root).as_posix()


def _registry_error(
    message: str,
    reason: str,
    registry: Path,
    **details: str | int,
) -> NoReturn:
    raise AuthoringError(
        "invalid_source_registry",
        message,
        {
            "path": str(registry),
            "reason": reason,
            "role": "source registry",
            **details,
        },
    )
