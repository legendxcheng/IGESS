"""Isolated source candidates and deterministic runtime exports."""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
import gc
import hashlib
import os
from pathlib import Path
import shutil
import stat
import tempfile
from typing import BinaryIO, Iterator, NoReturn

from .change import ModelChange
from .entity_schema import get_entity_schema
from . import project as _project_module
from ..luban_exporter import export_registered_workbooks
from .project import AuthoringProject
from .response import AuthoringError
from .workbook_source import upsert_workbook_entity
from .yaml_source import upsert_yaml_entity


_COPY_CHUNK_SIZE = 1024 * 1024
_MAX_EXPORT_FILES = 4_096
_MAX_EXPORT_BYTES = 512 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class StagedSources:
    """One isolated, validated copy of the model's authoritative sources."""

    root: Path
    origin_root: Path
    origin_config: Path
    origin_datas: Path
    committed_exports: Path
    config: Path
    datas: Path
    exports: Path
    source_paths: tuple[str, ...]
    source_digest: str


@dataclass(frozen=True, slots=True)
class ExportResult:
    """One atomically published runtime export tree."""

    root: Path
    written_paths: tuple[Path, ...]
    digest: str


@dataclass(frozen=True, slots=True)
class EphemeralExport:
    """Paths and digests kept alive by :func:`ephemeral_export`."""

    workspace: Path
    candidate_root: Path
    candidate_config: Path
    candidate_datas: Path
    export_root: Path
    source_digest: str
    export_digest: str
    written_paths: tuple[Path, ...]


def apply_to_candidate(
    candidate: StagedSources,
    change: ModelChange,
) -> tuple[str, ...]:
    """Apply one validated change to an isolated candidate.

    The tuple is empty for a semantic no-op.  Otherwise it contains exactly
    one canonical, candidate-root-relative POSIX path.
    """

    if not isinstance(candidate, StagedSources):
        raise TypeError("candidate must be StagedSources returned by stage_sources")
    if not isinstance(change, ModelChange):
        raise TypeError("change must be a ModelChange")
    _require_candidate_layout(candidate)
    schema = get_entity_schema(change.entity)
    if schema.storage_kind == "yaml":
        changed = upsert_yaml_entity(candidate.config, change)
        relative = "economy.yaml"
    elif schema.storage_kind == "workbook":
        path = candidate.datas / schema.storage_name
        changed = upsert_workbook_entity(path, change)
        relative = f"Datas/{schema.storage_name}"
    else:  # pragma: no cover - immutable entity metadata is exhaustive
        _export_error(
            "unknown_storage_kind",
            "The change entity uses an unsupported storage kind",
            entity=change.entity,
            storage_kind=schema.storage_kind,
        )
    return (relative,) if changed else ()


def export_candidate(
    candidate: StagedSources,
    out: str | os.PathLike[str],
) -> ExportResult:
    """Run the real Luban exporter and atomically publish a complete tree.

    Replacing an existing output first renames the old tree to a uniquely
    named sibling backup.  Once the new tree is published, a backup that
    cannot be cleaned is deliberately retained for later recovery without
    turning the already-committed publication into a false command failure.
    """

    if not isinstance(candidate, StagedSources):
        raise TypeError("candidate must be StagedSources returned by stage_sources")
    _require_candidate_layout(candidate)
    _reject_protected_output(candidate, out)
    candidate_project = AuthoringProject.discover(candidate.root)
    source_identities_before = _candidate_source_identities(candidate)
    source_digest_before = candidate_project.model_digest()
    output, output_existed, output_identity = _prepare_export_target(out)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{output.name}-export-", dir=output.parent)
    )
    published = False
    try:
        try:
            try:
                raw_written = export_registered_workbooks(candidate.datas, temporary)
            except AuthoringError:
                raise
            except Exception as error:
                _export_error(
                    "exporter_error",
                    "Registered workbooks could not be exported",
                    error_type=type(error).__name__,
                    path=str(candidate.datas),
                )
        finally:
            # The legacy exporter does not own an explicit workbook close in
            # every path.  Collect its short-lived openpyxl object cycles now
            # so Windows never retains handles past this command boundary.
            gc.collect()

        written_relative = _validate_export_output(temporary, raw_written)
        source_digest_after = candidate_project.model_digest()
        source_identities_after = _candidate_source_identities(candidate)
        if (
            source_digest_after != source_digest_before
            or source_identities_after != source_identities_before
        ):
            _export_error(
                "source_identity_changed",
                "Candidate sources changed while runtime exports were generated",
                after=source_digest_after,
                before=source_digest_before,
                path=str(candidate.root),
            )
        digest = compute_export_digest(temporary)
        _publish_export_tree(
            temporary,
            output,
            output_existed=output_existed,
            output_identity=output_identity,
        )
        published = True
        return ExportResult(
            root=output,
            written_paths=tuple(output.joinpath(*Path(path).parts) for path in written_relative),
            digest=digest,
        )
    finally:
        if not published:
            try:
                shutil.rmtree(temporary)
            except FileNotFoundError:
                pass


def compute_export_digest(root: str | os.PathLike[str]) -> str:
    """Hash sorted export-relative POSIX paths and bytes using bounded streams."""

    export_root = _require_real_directory(root, role="export root")
    files = _walk_export_files(export_root)
    digest = hashlib.sha256()
    total_bytes = 0
    for relative, path, identity in files:
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        try:
            with path.open("rb") as handle:
                opened = os.fstat(handle.fileno())
                if not _same_source_identity(identity, opened):
                    _export_error(
                        "export_identity_changed",
                        "An export file changed before it could be hashed",
                        path=str(path),
                    )
                while True:
                    chunk = handle.read(_COPY_CHUNK_SIZE)
                    if not chunk:
                        break
                    total_bytes += len(chunk)
                    if total_bytes > _MAX_EXPORT_BYTES:
                        _export_error(
                            "export_budget_exceeded",
                            "Export tree exceeds the byte budget",
                            actual_bytes=total_bytes,
                            limit_bytes=_MAX_EXPORT_BYTES,
                            path=str(export_root),
                        )
                    digest.update(chunk)
                after = os.fstat(handle.fileno())
            current = path.stat()
        except AuthoringError:
            raise
        except (OSError, MemoryError, ValueError) as error:
            _export_error(
                "export_read_failed",
                "An export file could not be read safely",
                error_type=type(error).__name__,
                path=str(path),
            )
        if not (
            _same_source_identity(identity, after)
            and _same_source_identity(identity, current)
        ):
            _export_error(
                "export_identity_changed",
                "An export file changed while it was being hashed",
                path=str(path),
            )
    return f"sha256:{digest.hexdigest()}"


@contextmanager
def ephemeral_export(project: AuthoringProject) -> Iterator[EphemeralExport]:
    """Yield a disposable current-source export, then remove every artifact."""

    if not isinstance(project, AuthoringProject):
        raise TypeError("project must be an AuthoringProject")
    with tempfile.TemporaryDirectory(prefix="igess-authoring-export-") as temporary:
        workspace = Path(temporary)
        staged = stage_sources(project, workspace / "transaction")
        exported = export_candidate(staged, staged.exports)
        yield EphemeralExport(
            workspace=workspace,
            candidate_root=staged.root,
            candidate_config=staged.config,
            candidate_datas=staged.datas,
            export_root=exported.root,
            source_digest=staged.source_digest,
            export_digest=exported.digest,
            written_paths=exported.written_paths,
        )


def stage_sources(
    project: AuthoringProject,
    transaction_dir: str | os.PathLike[str],
) -> StagedSources:
    """Copy exactly the current authoritative source snapshot into a candidate.

    The returned candidate is rooted at ``transaction_dir/candidate``.  A
    failure removes that newly-created directory but leaves both the live
    project and every pre-existing transaction artifact untouched.
    """

    if not isinstance(project, AuthoringProject):
        raise TypeError("project must be an AuthoringProject")
    transaction = _prepare_transaction_directory(transaction_dir)
    candidate = transaction / "candidate"
    try:
        candidate.mkdir()
    except FileExistsError:
        _export_error(
            "candidate_exists",
            "Candidate source directory already exists",
            path=str(candidate),
        )
    except (OSError, ValueError) as error:
        _export_error(
            "candidate_create_failed",
            "Candidate source directory could not be created",
            error_type=type(error).__name__,
            path=str(candidate),
        )

    try:
        sources = _copy_authoritative_sources(project, candidate)
        (candidate / "luban_exports").mkdir()
        staged_project = AuthoringProject.discover(candidate)
        if staged_project.model_digest() != sources.source_digest:
            _export_error(
                "candidate_verification_failed",
                "Staged sources do not reproduce the validated source digest",
                path=str(candidate),
                reason="digest_mismatch",
            )
        return sources
    except BaseException as primary:
        try:
            shutil.rmtree(candidate)
        except FileNotFoundError:
            pass
        except BaseException as cleanup_error:
            primary.add_note(
                "Candidate cleanup failed: "
                f"{type(cleanup_error).__name__}: {cleanup_error}"
            )
        raise


def _prepare_transaction_directory(value: str | os.PathLike[str]) -> Path:
    if not isinstance(value, (str, os.PathLike)):
        _export_error(
            "invalid_transaction_path",
            "Transaction directory must be path-like",
            value_type=type(value).__name__,
        )
    path = Path(value).expanduser()
    try:
        path.mkdir(parents=True, exist_ok=True)
        identity = path.lstat()
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as error:
        _export_error(
            "invalid_transaction_path",
            "Transaction directory could not be prepared safely",
            error_type=type(error).__name__,
            path=str(path),
        )
    if stat.S_ISLNK(identity.st_mode) or not stat.S_ISDIR(identity.st_mode):
        _export_error(
            "invalid_transaction_path",
            "Transaction path must be a real directory",
            path=str(path),
            reason="indirection_or_wrong_type",
        )
    return resolved


def _require_candidate_layout(candidate: StagedSources) -> None:
    try:
        root_identity = candidate.root.lstat()
        resolved_root = candidate.root.resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as error:
        _export_error(
            "candidate_invalid",
            "Candidate root could not be resolved safely",
            error_type=type(error).__name__,
            path=str(candidate.root),
            role="root",
        )
    if stat.S_ISLNK(root_identity.st_mode) or not stat.S_ISDIR(root_identity.st_mode):
        _export_error(
            "candidate_invalid",
            "Candidate root must be a real directory",
            path=str(candidate.root),
            reason="indirection_or_wrong_type",
            role="root",
        )
    expected = {
        "config": (candidate.root / "economy.yaml", "file"),
        "datas": (candidate.root / "Datas", "directory"),
        "exports": (candidate.root / "luban_exports", "directory"),
    }
    for name, (expected_path, expected_kind) in expected.items():
        actual = getattr(candidate, name)
        if actual != expected_path:
            _export_error(
                "candidate_invalid",
                "Candidate path was retargeted outside its canonical layout",
                path=str(actual),
                reason="path_retargeted",
                role=name,
            )
        try:
            identity = actual.lstat()
            resolved_actual = actual.resolve(strict=True)
            resolved_expected = expected_path.resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as error:
            _export_error(
                "candidate_invalid",
                "Candidate layout could not be resolved safely",
                error_type=type(error).__name__,
                path=str(actual),
                role=name,
            )
        matches_kind = (
            stat.S_ISREG(identity.st_mode)
            if expected_kind == "file"
            else stat.S_ISDIR(identity.st_mode)
        )
        if (
            stat.S_ISLNK(identity.st_mode)
            or not matches_kind
            or resolved_actual != resolved_expected
            or not resolved_actual.is_relative_to(resolved_root)
        ):
            _export_error(
                "candidate_invalid",
                "Candidate path was retargeted outside its canonical layout",
                path=str(actual),
                reason="path_retargeted",
                role=name,
            )


def _prepare_export_target(
    value: str | os.PathLike[str],
) -> tuple[Path, bool, os.stat_result | None]:
    if not isinstance(value, (str, os.PathLike)):
        _export_error(
            "invalid_output_path",
            "Export output must be path-like",
            value_type=type(value).__name__,
        )
    raw = Path(value).expanduser()
    if not raw.name:
        _export_error(
            "invalid_output_path",
            "Export output must name a child directory",
            path=str(raw),
            reason="root_target",
        )
    try:
        raw.parent.mkdir(parents=True, exist_ok=True)
        parent = raw.parent.resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as error:
        _export_error(
            "invalid_output_path",
            "Export output parent could not be prepared safely",
            error_type=type(error).__name__,
            path=str(raw),
        )
    output = parent / raw.name
    try:
        identity = output.lstat()
    except FileNotFoundError:
        return output, False, None
    except OSError as error:
        _export_error(
            "invalid_output_path",
            "Export output could not be inspected",
            error_type=type(error).__name__,
            path=str(output),
        )
    if stat.S_ISLNK(identity.st_mode) or not stat.S_ISDIR(identity.st_mode):
        _export_error(
            "invalid_output_path",
            "Existing export output must be a real directory",
            path=str(output),
            reason="indirection_or_wrong_type",
        )
    try:
        if output.resolve(strict=True).parent != parent:
            _export_error(
                "invalid_output_path",
                "Export output resolves outside its requested parent",
                path=str(output),
                reason="path_escape",
            )
    except (OSError, RuntimeError, ValueError) as error:
        _export_error(
            "invalid_output_path",
            "Export output could not be resolved safely",
            error_type=type(error).__name__,
            path=str(output),
        )
    return output, True, identity


def _reject_protected_output(
    candidate: StagedSources,
    value: str | os.PathLike[str],
) -> None:
    if not isinstance(value, (str, os.PathLike)):
        return
    try:
        requested = Path(value).expanduser().resolve(strict=False)
        intended_exports = candidate.exports.resolve(strict=True)
        protected = (
            ("committed_exports", candidate.committed_exports.resolve(strict=True)),
            ("origin_config", candidate.origin_config.resolve(strict=True)),
            ("origin_datas", candidate.origin_datas.resolve(strict=True)),
            ("candidate_config", candidate.config.resolve(strict=True)),
            ("candidate_datas", candidate.datas.resolve(strict=True)),
        )
    except (OSError, RuntimeError, ValueError) as error:
        _export_error(
            "invalid_output_path",
            "Export output protection boundary could not be resolved",
            error_type=type(error).__name__,
            path=str(value),
        )
    if requested == intended_exports:
        return
    for role, source in protected:
        if _paths_overlap(requested, source):
            _export_error(
                "protected_source_target",
                "Runtime exports may not overlap original or candidate sources",
                path=str(requested),
                protected_path=str(source),
                protected_role=role,
            )


def _paths_overlap(first: Path, second: Path) -> bool:
    return (
        first == second
        or first.is_relative_to(second)
        or second.is_relative_to(first)
    )


def _validate_export_output(
    root: Path,
    raw_written: object,
) -> tuple[str, ...]:
    if not isinstance(raw_written, list):
        _export_error(
            "invalid_export_result",
            "The workbook exporter returned an invalid written-path list",
            result_type=type(raw_written).__name__,
        )
    written: list[str] = []
    for value in raw_written:
        if not isinstance(value, (str, os.PathLike)):
            _export_error(
                "invalid_export_result",
                "The workbook exporter returned a non-path output",
                value_type=type(value).__name__,
            )
        path = Path(value)
        try:
            resolved = path.resolve(strict=True)
            relative = resolved.relative_to(root).as_posix()
            identity = path.lstat()
        except (OSError, RuntimeError, ValueError) as error:
            _export_error(
                "unsafe_export_output",
                "A reported export output is missing or escapes its root",
                error_type=type(error).__name__,
                path=str(path),
            )
        if (
            stat.S_ISLNK(identity.st_mode)
            or not stat.S_ISREG(identity.st_mode)
            or resolved.parent != root
        ):
            _export_error(
                "unsafe_export_output",
                "A reported export output must be a direct regular file",
                path=str(path),
            )
        written.append(relative)
    if len(set(written)) != len(written):
        _export_error(
            "invalid_export_result",
            "The workbook exporter reported a file more than once",
            paths=written,
        )
    try:
        with os.scandir(root) as entries:
            unexpected = [
                entry.name
                for entry in entries
                if entry.is_symlink() or not entry.is_file(follow_symlinks=False)
            ]
    except OSError as error:
        _export_error(
            "export_read_failed",
            "Export root could not be inspected safely",
            error_type=type(error).__name__,
            path=str(root),
        )
    if unexpected:
        _export_error(
            "unexpected_export_output",
            "The workbook exporter created an unexpected non-file output",
            outputs=sorted(unexpected),
            path=str(root),
        )
    actual = tuple(relative for relative, _, _ in _walk_export_files(root))
    if tuple(sorted(written)) != actual:
        _export_error(
            "unexpected_export_output",
            "The export tree contains files not reported by the exporter",
            actual=list(actual),
            reported=sorted(written),
        )
    return actual


def _candidate_source_identities(
    candidate: StagedSources,
) -> tuple[tuple[str, int, int, int, int, int], ...]:
    identities: list[tuple[str, int, int, int, int, int]] = []
    for relative in candidate.source_paths:
        relative_path = Path(relative)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            _export_error(
                "candidate_invalid",
                "Candidate source list contains an unsafe relative path",
                path=relative,
            )
        path = candidate.root.joinpath(*relative_path.parts)
        try:
            identity = path.lstat()
            resolved = path.resolve(strict=True)
            resolved.relative_to(candidate.root)
        except (OSError, RuntimeError, ValueError) as error:
            _export_error(
                "candidate_invalid",
                "Candidate source identity could not be captured safely",
                error_type=type(error).__name__,
                path=str(path),
            )
        if stat.S_ISLNK(identity.st_mode) or not stat.S_ISREG(identity.st_mode):
            _export_error(
                "candidate_invalid",
                "Candidate source must be a regular file",
                path=str(path),
            )
        identities.append(
            (
                relative_path.as_posix(),
                identity.st_dev,
                identity.st_ino,
                identity.st_size,
                identity.st_mtime_ns,
                stat.S_IMODE(identity.st_mode),
            )
        )
    return tuple(identities)


def _walk_export_files(root: Path) -> tuple[tuple[str, Path, os.stat_result], ...]:
    pending = [root]
    files: list[tuple[str, Path, os.stat_result]] = []
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as entries:
                children = sorted(entries, key=lambda entry: entry.name, reverse=True)
        except OSError as error:
            _export_error(
                "export_read_failed",
                "Export directory could not be enumerated safely",
                error_type=type(error).__name__,
                path=str(directory),
            )
        for entry in children:
            path = Path(entry.path)
            try:
                # ``DirEntry.stat`` reports zero device/inode values on some
                # Windows Python builds; Path.lstat remains comparable to the
                # subsequently opened file descriptor.
                identity = path.lstat()
            except OSError as error:
                _export_error(
                    "export_read_failed",
                    "Export entry could not be inspected safely",
                    error_type=type(error).__name__,
                    path=str(path),
                )
            if entry.is_symlink():
                _export_error(
                    "unsafe_export_output",
                    "Export trees may not contain symbolic links",
                    path=str(path),
                )
            if stat.S_ISDIR(identity.st_mode):
                try:
                    resolved = path.resolve(strict=True)
                    resolved.relative_to(root)
                except (OSError, RuntimeError, ValueError) as error:
                    _export_error(
                        "unsafe_export_output",
                        "An export directory escapes its root",
                        error_type=type(error).__name__,
                        path=str(path),
                    )
                pending.append(path)
                continue
            if not stat.S_ISREG(identity.st_mode):
                _export_error(
                    "unsafe_export_output",
                    "Export trees may contain only directories and regular files",
                    path=str(path),
                )
            try:
                resolved = path.resolve(strict=True)
                relative = resolved.relative_to(root).as_posix()
            except (OSError, RuntimeError, ValueError) as error:
                _export_error(
                    "unsafe_export_output",
                    "An export file escapes its root",
                    error_type=type(error).__name__,
                    path=str(path),
                )
            files.append((relative, resolved, identity))
            if len(files) > _MAX_EXPORT_FILES:
                _export_error(
                    "export_budget_exceeded",
                    "Export tree exceeds the file-count budget",
                    actual_files=len(files),
                    limit_files=_MAX_EXPORT_FILES,
                    path=str(root),
                )
    files.sort(key=lambda item: item[0])
    return tuple(files)


def _require_real_directory(
    value: str | os.PathLike[str], *, role: str
) -> Path:
    if not isinstance(value, (str, os.PathLike)):
        _export_error(
            "invalid_output_path",
            f"{role.title()} must be path-like",
            value_type=type(value).__name__,
        )
    path = Path(value)
    try:
        identity = path.lstat()
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as error:
        _export_error(
            "invalid_output_path",
            f"{role.title()} could not be resolved safely",
            error_type=type(error).__name__,
            path=str(path),
        )
    if stat.S_ISLNK(identity.st_mode) or not stat.S_ISDIR(identity.st_mode):
        _export_error(
            "invalid_output_path",
            f"{role.title()} must be a real directory",
            path=str(path),
            reason="indirection_or_wrong_type",
        )
    return resolved


def _publish_export_tree(
    temporary: Path,
    output: Path,
    *,
    output_existed: bool,
    output_identity: os.stat_result | None,
) -> None:
    if output_existed:
        try:
            current = output.lstat()
        except OSError as error:
            _export_error(
                "output_identity_changed",
                "Export output changed before publication",
                error_type=type(error).__name__,
                path=str(output),
            )
        if output_identity is None or not _same_source_identity(output_identity, current):
            _export_error(
                "output_identity_changed",
                "Export output changed before publication",
                path=str(output),
            )
        descriptor, backup_name = tempfile.mkstemp(
            prefix=f".{output.name}-backup-", dir=output.parent
        )
        os.close(descriptor)
        backup = Path(backup_name)
        backup.unlink()
        moved_old = False
        try:
            os.replace(output, backup)
            moved_old = True
            os.replace(temporary, output)
        except BaseException:
            if moved_old and not output.exists():
                os.replace(backup, output)
            raise
        try:
            shutil.rmtree(backup)
        except FileNotFoundError:
            pass
        except Exception:
            # Publication is already committed.  Keep the uniquely named old
            # tree intact for manual/later recovery instead of reporting the
            # successful export as failed or risking deletion of another path.
            pass
        return

    if output.exists() or output.is_symlink():
        _export_error(
            "output_identity_changed",
            "Export output appeared before publication",
            path=str(output),
        )
    try:
        os.replace(temporary, output)
    except (OSError, ValueError) as error:
        _export_error(
            "output_publish_failed",
            "Complete export tree could not be published atomically",
            error_type=type(error).__name__,
            path=str(output),
        )
def _copy_authoritative_sources(
    project: AuthoringProject,
    candidate: Path,
) -> StagedSources:
    config = _project_module._current_required_path(
        project,
        "economy.yaml",
        "file",
        "project config",
        "project_config",
    )
    datas = _project_module._current_required_path(
        project,
        "Datas",
        "directory",
        "source tables",
        "source_tables",
    )
    registry = _project_module._resolve_registry(datas / "__tables__.xlsx", datas)
    config_snapshot = _project_module._snapshot_source("config", config)
    registry_snapshot = _project_module._snapshot_source(
        "registry", registry, registry=registry
    )

    with ExitStack() as stack:
        opened_config = stack.enter_context(
            _project_module._open_validated_source(
                config_snapshot,
                root=project.root,
                boundary=project.root,
                direct=True,
            )
        )
        opened_registry = stack.enter_context(
            _project_module._open_validated_source(
                registry_snapshot,
                root=project.root,
                boundary=datas,
                direct=True,
            )
        )
        registrations = _project_module._read_registration_paths(
            opened_registry.handle, registry
        )
        snapshots = _project_module._validate_registration_paths(
            datas, registry, registrations
        )
        opened_workbooks = [
            stack.enter_context(
                _project_module._open_validated_source(
                    snapshot,
                    root=project.root,
                    boundary=datas,
                    direct=False,
                )
            )
            for snapshot in snapshots
        ]
        _project_module._reject_duplicate_opened_sources(opened_workbooks, registry)

        opened_sources = [opened_config, opened_registry, *opened_workbooks]
        ordered = sorted(
            opened_sources,
            key=lambda item: _project_module._root_relative_posix(
                project.root, item.path
            ),
        )
        digest = hashlib.sha256()
        relative_paths: list[str] = []
        for opened in ordered:
            relative = _project_module._root_relative_posix(project.root, opened.path)
            relative_paths.append(relative)
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            destination = candidate.joinpath(*Path(relative).parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            _copy_opened_source(opened.handle, destination, digest, opened.identity)
            _require_unchanged_opened_source(opened)

    return StagedSources(
        root=candidate,
        origin_root=project.root,
        origin_config=project.config,
        origin_datas=project.datas,
        committed_exports=project.exports,
        config=candidate / "economy.yaml",
        datas=candidate / "Datas",
        exports=candidate / "luban_exports",
        source_paths=tuple(relative_paths),
        source_digest=f"sha256:{digest.hexdigest()}",
    )


def _copy_opened_source(
    source: BinaryIO,
    destination: Path,
    digest: "hashlib._Hash",
    identity: os.stat_result,
) -> None:
    try:
        source.seek(0)
        with destination.open("xb") as target:
            while True:
                chunk = source.read(_COPY_CHUNK_SIZE)
                if not chunk:
                    break
                target.write(chunk)
                digest.update(chunk)
            target.flush()
        os.chmod(destination, stat.S_IMODE(identity.st_mode))
    except (OSError, MemoryError, ValueError) as error:
        _export_error(
            "source_copy_failed",
            "An authoritative source could not be copied to the candidate",
            error_type=type(error).__name__,
            path=str(destination),
        )


def _require_unchanged_opened_source(opened: object) -> None:
    snapshot = opened.snapshot
    expected = snapshot.identity
    try:
        handle_identity = os.fstat(opened.handle.fileno())
        path_identity = opened.path.stat()
    except (OSError, ValueError) as error:
        _export_error(
            "source_identity_changed",
            "An authoritative source could not be revalidated after copying",
            error_type=type(error).__name__,
            path=str(opened.path),
        )
    if expected is None or not (
        _same_source_identity(expected, handle_identity)
        and _same_source_identity(expected, path_identity)
    ):
        _export_error(
            "source_identity_changed",
            "An authoritative source changed while it was being staged",
            path=str(opened.path),
        )


def _same_source_identity(first: os.stat_result, second: os.stat_result) -> bool:
    return (
        os.path.samestat(first, second)
        and first.st_size == second.st_size
        and first.st_mtime_ns == second.st_mtime_ns
        and stat.S_IMODE(first.st_mode) == stat.S_IMODE(second.st_mode)
    )


def _export_error(default_reason: str, message: str, **details: object) -> NoReturn:
    details.setdefault("reason", default_reason)
    raise AuthoringError(
        "authoring_export_failed",
        message,
        details,
    )


__all__ = [
    "EphemeralExport",
    "ExportResult",
    "StagedSources",
    "apply_to_candidate",
    "compute_export_digest",
    "ephemeral_export",
    "export_candidate",
    "stage_sources",
]
