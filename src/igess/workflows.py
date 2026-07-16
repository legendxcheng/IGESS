from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .advice import run_advise
from .authoring.change_records import ChangeRecordStore
from .authoring.exports import compute_export_digest, ephemeral_export
from .authoring.project import AuthoringProject
from .authoring.response import CommandResponse
from .authoring.service import AuthoringService
from .builder import ModelBuilder
from .linter import ConfigLinter
from .loader import ConfigLoader
from .outputs import OutputWriter
from .reporting.static import generate_static_report
from .run_registry import RunRecord, RunRegistry
from .simulator import Simulator


_MAX_ADVICE_BYTES = 1024 * 1024
_MAX_LEGACY_CONFIG_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True)
class WorkflowResult:
    ok: bool
    message: str


class WorkflowService:
    def __init__(
        self,
        project_root: str | Path,
        runs_root: str | Path | None = None,
        *,
        authoring: bool | None = None,
        authoring_project: AuthoringProject | None = None,
        authoring_service: AuthoringService | None = None,
        registry: RunRegistry | None = None,
        change_store: ChangeRecordStore | None = None,
        advice_runner: Callable[..., dict[str, Any]] = run_advise,
        ephemeral_exporter: Callable[[AuthoringProject], Any] = ephemeral_export,
    ):
        self.project_root = Path(project_root)
        self.authoring_project = self._discover_authoring_project(
            authoring,
            authoring_project,
        )
        self.is_authoring = self.authoring_project is not None
        if authoring_service is not None and self.authoring_project is None:
            raise ValueError("an injected authoring_service requires an authoring project")
        if authoring_service is not None and registry is None:
            raise ValueError("an injected authoring_service requires an explicit registry")

        if registry is not None:
            self.registry = registry
            if runs_root is not None and not _same_registry_root(registry, runs_root):
                raise ValueError("injected registry does not match runs_root")
        elif self.authoring_project is not None:
            write_root = (
                Path(runs_root)
                if runs_root is not None
                else self.authoring_project.runs
            )
            self.registry = RunRegistry(
                write_root,
                read_roots=self.authoring_project.read_run_roots(),
            )
        else:
            self.registry = RunRegistry(runs_root or self.project_root / ".igess" / "runs")

        if authoring_service is not None:
            self.authoring_service = authoring_service
            binder = getattr(authoring_service, "bind_run_registry", None)
            if callable(binder):
                binder(self.registry)
        elif self.authoring_project is not None:
            shared_registry = self.registry
            self.authoring_service = AuthoringService(
                self.authoring_project.root,
                registry_factory=lambda _project: shared_registry,
            )
        else:
            self.authoring_service = None
        self._advice_runner = advice_runner
        self._ephemeral_exporter = ephemeral_exporter
        self.change_store = (
            change_store
            if change_store is not None
            else ChangeRecordStore(self.authoring_project.changes)
            if self.authoring_project is not None
            else None
        )

    def model_status(self) -> CommandResponse | None:
        """Return the canonical authoring status, when this is an authoring project."""

        if self.authoring_service is None:
            return None
        return self.authoring_service.status()

    def latest_change(self) -> dict[str, Any] | None:
        """Return the latest committed rule audit without scanning project files."""

        if self.change_store is None:
            return None
        return self.change_store.latest()

    def run_authoring_scenario(self, scenario_id: str) -> CommandResponse:
        """Run a manual scenario through authoring's source-consistent snapshot."""

        if self.authoring_service is None:
            raise ValueError("authoring scenario requires an authoring project")
        return self.authoring_service.simulate(scenario_id)

    def lint(self, config: str | Path, tables: str | Path) -> WorkflowResult:
        try:
            raw = ConfigLoader.load(self._path(config), self._path(tables))
            ConfigLinter.validate(raw)
            return WorkflowResult(True, "Config OK")
        except Exception as exc:  # noqa: BLE001 - service boundary returns messages.
            return WorkflowResult(False, str(exc))

    def run_scenario(self, config: str | Path, tables: str | Path, scenario_id: str) -> RunRecord:
        run_dir = self.registry.new_run_dir(scenario_id)
        output_dir = run_dir / "output"
        report_dir = run_dir / "report"
        report_index = report_dir / "index.html"
        self.registry.write_status(
            run_dir,
            status="running",
            scenario_id=scenario_id,
            message="Running simulation",
            output_dir=output_dir,
            report_dir=report_dir,
            report_index=report_index,
        )
        try:
            raw = ConfigLoader.load(self._path(config), self._path(tables))
            ConfigLinter.validate(raw)
            model = ModelBuilder.build(raw)
            result = Simulator(model).run_scenario(scenario_id)
            OutputWriter.write_all(result, output_dir, model)
            generate_static_report(output_dir, report_dir)
            return self.registry.write_status(
                run_dir,
                status="success",
                scenario_id=scenario_id,
                message="Run complete",
                output_dir=output_dir,
                report_dir=report_dir,
                report_index=report_index,
            )
        except Exception as exc:  # noqa: BLE001 - failure is persisted for dashboard history.
            return self.registry.write_status(
                run_dir,
                status="failed",
                scenario_id=scenario_id,
                message=str(exc),
                output_dir=output_dir,
                report_dir=report_dir,
                report_index=report_index,
            )

    def run_advice(
        self,
        config: str | Path | None,
        tables: str | Path | None,
        scenario_id: str,
    ) -> RunRecord:
        if self.authoring_project is not None and config is None and tables is None:
            if self.authoring_service is None:
                raise ValueError("authoring advice requires an authoring service")
            operation = self.authoring_service.run_snapshot_operation(
                lambda project, _warnings: self._run_authoring_advice(
                    project,
                    scenario_id,
                )
            )
            return operation.result
        if config is None or tables is None:
            raise ValueError("legacy advice requires config and tables")
        resolved_config = self._path(config)
        resolved_tables = self._path(tables)
        return self._run_advice(
            resolved_config,
            resolved_tables,
            scenario_id,
            model_digest=_legacy_model_digest(resolved_config, resolved_tables),
        )

    def _run_authoring_advice(
        self,
        project: AuthoringProject,
        scenario_id: str,
    ) -> RunRecord:
        with self._ephemeral_exporter(project) as exported:
            return self._run_advice(
                exported.candidate_config,
                exported.export_root,
                scenario_id,
                model_digest=exported.source_digest,
            )

    def _run_advice(
        self,
        config: Path,
        tables: Path,
        scenario_id: str,
        *,
        model_digest: str,
    ) -> RunRecord:
        run_dir = self.registry.new_run_dir(f"advice_{scenario_id}", kind="advice")
        advice_dir = run_dir / "advice"
        output_dir = advice_dir / "run"
        report_dir = advice_dir / "report"
        report_index = report_dir / "index.html"
        metadata = {"kind": "advice", "model_digest": model_digest}
        self.registry.write_status(
            run_dir,
            status="running",
            scenario_id=scenario_id,
            message="Running Agent Analyst",
            output_dir=output_dir,
            report_dir=report_dir,
            report_index=report_index,
            **metadata,
        )
        try:
            advice = self._advice_runner(
                config,
                tables,
                scenario_id,
                advice_dir,
            )
            return self.registry.write_status(
                run_dir,
                status=advice["status"],
                scenario_id=scenario_id,
                message=advice["summary"],
                output_dir=output_dir,
                report_dir=report_dir,
                report_index=report_index,
                **metadata,
            )
        except Exception as exc:  # noqa: BLE001 - failure is persisted for dashboard history.
            return self.registry.write_status(
                run_dir,
                status="failed",
                scenario_id=scenario_id,
                message=str(exc),
                output_dir=output_dir,
                report_dir=report_dir,
                report_index=report_index,
                **metadata,
            )

    def latest_advice(self) -> dict | None:
        for record in reversed(self.registry.list_runs()):
            try:
                encoded = _read_bounded_relative_file(
                    record.run_dir,
                    ("advice", "advice.json"),
                    max_bytes=_MAX_ADVICE_BYTES,
                )
                payload = json.loads(encoded.decode("utf-8"))
                normalized = _validated_advice(payload)
                if normalized is not None:
                    return normalized
            except (
                OSError,
                UnicodeError,
                ValueError,
                TypeError,
                json.JSONDecodeError,
                MemoryError,
                RecursionError,
            ):
                continue
        return None

    def list_runs(self) -> list[RunRecord]:
        return self.registry.list_runs()

    def _path(self, value: str | Path) -> Path:
        path = Path(value)
        if path.is_absolute():
            return path
        return self.project_root / path

    def _discover_authoring_project(
        self,
        authoring: bool | None,
        supplied: AuthoringProject | None,
    ) -> AuthoringProject | None:
        if authoring is False:
            return None
        if supplied is not None:
            return supplied
        try:
            return AuthoringProject.discover(self.project_root)
        except Exception:  # noqa: BLE001 - absence means legacy dashboard mode.
            if authoring:
                raise
            return None


def _same_registry_root(registry: RunRegistry, root: str | Path) -> bool:
    return _path_key(registry.runs_root) == _path_key(Path(root))


def _path_key(path: Path) -> str:
    return os.path.normcase(str(Path(path).absolute()))


def _legacy_model_digest(config: Path, tables: Path) -> str:
    config_bytes = _read_bounded_relative_file(
        config.parent,
        (config.name,),
        max_bytes=_MAX_LEGACY_CONFIG_BYTES,
    )
    export_digest = compute_export_digest(tables).encode("ascii")
    digest = hashlib.sha256()
    digest.update(b"IGESS_LEGACY_MODEL_DIGEST_V1\0")
    digest.update(len(config_bytes).to_bytes(8, "big"))
    digest.update(config_bytes)
    digest.update(len(export_digest).to_bytes(8, "big"))
    digest.update(export_digest)
    return f"sha256:{digest.hexdigest()}"


def _validated_advice(value: object) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    status = value.get("status")
    summary = value.get("summary")
    findings = value.get("findings")
    recommendations = value.get("table_recommendations", [])
    if not isinstance(status, str) or not status:
        return None
    if not isinstance(summary, str) or not summary:
        return None
    if not _mapping_sequence(findings) or not _mapping_sequence(recommendations):
        return None
    result = dict(value)
    result["findings"] = [dict(item) for item in findings]
    result["table_recommendations"] = [dict(item) for item in recommendations]
    return result


def _mapping_sequence(value: object) -> bool:
    return (
        isinstance(value, Sequence)
        and not isinstance(value, (str, bytes, bytearray))
        and all(isinstance(item, Mapping) for item in value)
    )


def _read_bounded_relative_file(
    root: Path,
    parts: Sequence[str],
    *,
    max_bytes: int,
    before_file_open: Callable[[], None] | None = None,
) -> bytes:
    """Read one regular descendant from its validated descriptor, without links."""

    if not parts or any(
        not isinstance(part, str) or not part or part in {".", ".."}
        for part in parts
    ):
        raise ValueError("file path must contain safe relative components")
    if max_bytes < 0:
        raise ValueError("max_bytes must be non-negative")
    if os.name == "nt":
        return _read_bounded_windows(
            Path(root),
            tuple(parts),
            max_bytes,
            before_file_open,
        )
    return _read_bounded_posix(
        Path(root),
        tuple(parts),
        max_bytes,
        before_file_open,
    )


def _read_bounded_posix(
    root: Path,
    parts: tuple[str, ...],
    max_bytes: int,
    before_file_open: Callable[[], None] | None,
) -> bytes:
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    directory_flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    file_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    directory_fd = os.open(root, directory_flags)
    try:
        if not stat.S_ISDIR(os.fstat(directory_fd).st_mode):
            raise OSError("safe file root is not a directory")
        for component in parts[:-1]:
            child_fd = os.open(component, directory_flags, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = child_fd
            if not stat.S_ISDIR(os.fstat(directory_fd).st_mode):
                raise OSError("safe file parent is not a directory")
        if before_file_open is not None:
            before_file_open()
        file_fd = os.open(parts[-1], file_flags, dir_fd=directory_fd)
        try:
            return _read_bounded_fd(file_fd, max_bytes)
        finally:
            os.close(file_fd)
    finally:
        os.close(directory_fd)


def _read_bounded_windows(
    root: Path,
    parts: tuple[str, ...],
    max_bytes: int,
    before_file_open: Callable[[], None] | None,
) -> bytes:
    root_identity = root.lstat()
    if _path_is_indirection(root_identity) or not stat.S_ISDIR(root_identity.st_mode):
        raise OSError("safe file root is not a real directory")
    resolved_root = root.resolve(strict=True)
    target = root.joinpath(*parts)
    current = root
    for component in parts:
        current = current / component
        if _path_is_indirection(current.lstat()):
            raise OSError("safe file path contains an indirection")
    if before_file_open is not None:
        before_file_open()
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOINHERIT", 0)
    file_fd = os.open(target, flags)
    try:
        opened = os.fstat(file_fd)
        if not stat.S_ISREG(opened.st_mode):
            raise OSError("safe file target is not regular")
        final_path = _windows_final_path(file_fd)
        if not final_path.is_relative_to(resolved_root):
            raise OSError("opened file escaped its safe root")
        if not os.path.samestat(root_identity, root.lstat()):
            raise OSError("safe file root changed during open")
        if root.resolve(strict=True) != resolved_root:
            raise OSError("safe file root was retargeted")
        current = root
        for component in parts:
            current = current / component
            if _path_is_indirection(current.lstat()):
                raise OSError("safe file path changed to an indirection")
        if not os.path.samestat(opened, target.stat()):
            raise OSError("safe file path identity changed during open")
        return _read_bounded_fd(file_fd, max_bytes)
    finally:
        os.close(file_fd)


def _read_bounded_fd(file_fd: int, max_bytes: int) -> bytes:
    identity = os.fstat(file_fd)
    if not stat.S_ISREG(identity.st_mode) or identity.st_size > max_bytes:
        raise OSError("safe file exceeds its accepted size or is not regular")
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = os.read(file_fd, min(64 * 1024, max_bytes - total + 1))
        if not chunk:
            after = os.fstat(file_fd)
            if (
                not os.path.samestat(identity, after)
                or identity.st_size != after.st_size
                or identity.st_mtime_ns != after.st_mtime_ns
            ):
                raise OSError("safe file changed while it was read")
            return b"".join(chunks)
        total += len(chunk)
        if total > max_bytes:
            raise OSError("safe file exceeds its accepted size")
        chunks.append(chunk)


def _path_is_indirection(identity: os.stat_result) -> bool:
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(identity.st_mode) or bool(
        getattr(identity, "st_file_attributes", 0) & reparse
    )


def _windows_final_path(file_fd: int) -> Path:
    import ctypes
    import msvcrt
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_final_path = kernel32.GetFinalPathNameByHandleW
    get_final_path.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
    get_final_path.restype = wintypes.DWORD
    handle = msvcrt.get_osfhandle(file_fd)
    size = get_final_path(handle, None, 0, 0)
    if not size:
        raise ctypes.WinError(ctypes.get_last_error())
    buffer = ctypes.create_unicode_buffer(size + 1)
    written = get_final_path(handle, buffer, len(buffer), 0)
    if not written or written >= len(buffer):
        raise ctypes.WinError(ctypes.get_last_error())
    value = buffer.value
    if value.startswith("\\\\?\\UNC\\"):
        value = "\\\\" + value[8:]
    elif value.startswith("\\\\?\\"):
        value = value[4:]
    return Path(value)
