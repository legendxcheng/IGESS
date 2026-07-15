"""Recoverable publication of authoring sources, exports, and artifacts."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import errno
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
from typing import Any, NoReturn
import uuid

from .project import AuthoringProject
from .response import AuthoringError


JOURNAL_SCHEMA_VERSION = 1
_PHASES = {"staging", "prepared", "committing", "committed"}
_CLEANUP_TOMBSTONE_PREFIX = ".cleanup-"
_Checkpoint = Callable[[str], None]
_DigestReader = Callable[[], str]


class Transaction:
    """One same-volume, journaled model publication.

    The caller stages sources below :attr:`candidate_dir` and the optional run
    and mandatory success audit at the exposed staging paths. ``prepare`` then
    records the exact destinations, and ``commit`` performs the ordered swaps.
    An exclusive project lock must be held by the service around this object.
    """

    def __init__(
        self,
        project: AuthoringProject,
        change_id: str,
        pre_digest: str,
        *,
        checkpoint: _Checkpoint | None = None,
        digest_reader: _DigestReader | None = None,
    ) -> None:
        if not isinstance(project, AuthoringProject):
            raise TypeError("project must be an AuthoringProject")
        _require_component(change_id, "change id")
        if not isinstance(pre_digest, str) or not pre_digest:
            raise TypeError("pre_digest must be a non-empty string")
        if checkpoint is not None and not callable(checkpoint):
            raise TypeError("checkpoint must be callable")
        if digest_reader is not None and not callable(digest_reader):
            raise TypeError("digest_reader must be callable")

        self.project = project
        self.change_id = change_id
        self.pre_digest = pre_digest
        self.root = project.transactions / change_id
        self.candidate_dir = self.root / "candidate"
        self.backups_dir = self.root / "backups"
        self.staged_artifacts_dir = self.root / "staged_artifacts"
        self.staged_run_dir = self.staged_artifacts_dir / "run"
        self.staged_change_path = self.staged_artifacts_dir / "change.json"
        self.journal_path = self.root / "journal.json"
        self._checkpoint = checkpoint or (lambda _name: None)
        self._digest_reader = digest_reader or project.model_digest
        self._active_checkpoint = "staging"
        self._prepared = False
        self._journal: dict[str, Any] = {
            "schema_version": JOURNAL_SCHEMA_VERSION,
            "change_id": change_id,
            "phase": "staging",
            "pre_digest": pre_digest,
            "targets": [],
            "staged_run": None,
            "staged_change": None,
            "last_completed_checkpoint": "staging",
        }

        try:
            _ensure_owned_directory(project.root, project.transactions)
            self.root.mkdir()
        except FileExistsError:
            _transaction_error(
                "transaction_exists",
                "A transaction with this change id already exists",
                change_id=change_id,
                path=str(self.root),
            )
        except Exception as error:
            _transaction_error(
                "transaction_prepare_failed",
                "Transaction storage could not be created",
                change_id=change_id,
                error_type=type(error).__name__,
                path=str(self.root),
            )

        try:
            self.backups_dir.mkdir()
            self.staged_artifacts_dir.mkdir()
            _write_journal(self.journal_path, self._journal)
        except AuthoringError:
            raise
        except Exception as error:
            try:
                _cleanup_transaction(self.root)
            except Exception:
                pass
            _transaction_error(
                "transaction_prepare_failed",
                "Transaction storage could not be created",
                change_id=change_id,
                error_type=type(error).__name__,
                path=str(self.root),
            )

    def prepare(
        self,
        *,
        targets: Sequence[str | os.PathLike[str]],
        run_destination: str | os.PathLike[str] | None,
        change_destination: str | os.PathLike[str],
    ) -> None:
        """Freeze ordered live targets and staged artifact destinations."""

        if self._prepared:
            _transaction_error(
                "transaction_already_prepared",
                "Transaction destinations were already prepared",
                change_id=self.change_id,
            )
        if not isinstance(targets, Sequence) or isinstance(
            targets, (str, bytes, bytearray)
        ):
            raise TypeError("targets must be a sequence of relative paths")
        if not targets:
            _transaction_error(
                "transaction_targets_missing",
                "A transaction must publish at least one target",
                change_id=self.change_id,
            )

        ordered: list[dict[str, Any]] = []
        seen: set[str] = set()
        for value in targets:
            relative = _coerce_project_target(value)
            relative_text = relative.as_posix()
            if relative_text in seen:
                _transaction_error(
                    "transaction_target_duplicate",
                    "A transaction target was listed more than once",
                    change_id=self.change_id,
                    target=relative_text,
                )
            seen.add(relative_text)
            live = self.project.root.joinpath(*relative.parts)
            candidate = self.candidate_dir.joinpath(*relative.parts)
            backup = self.backups_dir.joinpath(*relative.parts)
            _require_owned_path(
                self.root,
                candidate,
                role="candidate target",
                allow_missing_leaf=False,
            )
            _require_owned_path(
                self.project.root,
                live,
                role="live target",
                allow_missing_leaf=True,
            )
            _require_owned_path(
                self.root,
                backup,
                role="backup target",
                allow_missing_leaf=True,
                allow_missing_parents=True,
            )
            candidate_identity = _lstat_or_none(candidate)
            if candidate_identity is None or not (
                stat.S_ISREG(candidate_identity.st_mode)
                or stat.S_ISDIR(candidate_identity.st_mode)
            ):
                _transaction_error(
                    "transaction_candidate_missing",
                    "A candidate commit target is missing or has an unsafe type",
                    change_id=self.change_id,
                    target=relative_text,
                )
            live_identity = _lstat_or_none(live)
            if live_identity is not None and not (
                stat.S_ISREG(live_identity.st_mode) or stat.S_ISDIR(live_identity.st_mode)
            ):
                _transaction_error(
                    "transaction_live_target_unsafe",
                    "A live commit target has an unsafe type",
                    change_id=self.change_id,
                    target=relative_text,
                )
            if live_identity is not None and (
                stat.S_ISDIR(live_identity.st_mode)
                != stat.S_ISDIR(candidate_identity.st_mode)
            ):
                _transaction_error(
                    "transaction_target_type_changed",
                    "Candidate and live target types do not match",
                    change_id=self.change_id,
                    target=relative_text,
                )
            ordered.append(
                {
                    "live": relative_text,
                    "candidate": f"candidate/{relative_text}",
                    "backup": f"backups/{relative_text}",
                    "live_existed": live_identity is not None,
                }
            )

        staged_run = _prepare_artifact(
            self,
            staged=self.staged_run_dir,
            destination=run_destination,
            required=False,
            allowed_root=self.project.runs,
            role="run",
        )
        staged_change = _prepare_artifact(
            self,
            staged=self.staged_change_path,
            destination=change_destination,
            required=True,
            allowed_root=self.project.changes,
            role="change",
        )
        self._journal["phase"] = "prepared"
        self._journal["targets"] = ordered
        self._journal["staged_run"] = staged_run
        self._journal["staged_change"] = staged_change
        self._journal["last_completed_checkpoint"] = "prepared"
        _write_journal(self.journal_path, self._journal)
        self._prepared = True

    def abort(self) -> None:
        """Discard a staging/prepared transaction before commit starts."""

        if self._journal["phase"] not in {"staging", "prepared"}:
            _transaction_error(
                "transaction_abort_unsafe",
                "A committing or committed transaction must be recovered",
                change_id=self.change_id,
                phase=self._journal["phase"],
            )
        try:
            _cleanup_transaction(self.root)
        except Exception as error:
            raise AuthoringError(
                "recovery_required",
                "Transaction abort cleanup is incomplete; recovery required",
                {
                    "change_id": self.change_id,
                    "error_type": type(error).__name__,
                    "path": str(self.root),
                },
            ) from None

    def commit(self) -> tuple[dict[str, str], ...]:
        """Publish all prepared targets or restore their exact prior state."""

        if not self._prepared:
            _transaction_error(
                "transaction_not_prepared",
                "Transaction destinations must be prepared before commit",
                change_id=self.change_id,
            )

        committed_durable = False
        try:
            self._active_checkpoint = "stale_digest_recheck"
            current_digest = self._digest_reader()
            if current_digest != self.pre_digest:
                raise AuthoringError(
                    "stale_model",
                    "The model changed after this proposal was prepared",
                    {
                        "actual": current_digest,
                        "change_id": self.change_id,
                        "expected": self.pre_digest,
                    },
                )
            self._complete("stale_digest_recheck")

            self._journal["phase"] = "committing"
            self._complete("journal_committing")

            for index, target in enumerate(self._journal["targets"]):
                name = f"target:{index}:{target['live']}"
                self._active_checkpoint = name
                _replace_target(self.project.root, self.root, target)
                self._complete(name)

            if self._journal["staged_run"] is not None:
                self._active_checkpoint = "staged_run"
                _move_artifact(self.project.root, self.root, self._journal["staged_run"])
                self._complete("staged_run")

            self._active_checkpoint = "staged_change"
            _move_artifact(
                self.project.root,
                self.root,
                self._journal["staged_change"],
            )
            self._complete("staged_change")

            self._active_checkpoint = "journal_committed"
            self._journal["phase"] = "committed"
            self._journal["last_completed_checkpoint"] = "journal_committed"
            _write_journal(self.journal_path, self._journal)
            committed_durable = True
            self._checkpoint("journal_committed")
        except Exception as error:
            if committed_durable:
                return (self._cleanup_warning(),)
            rollback_error = self._rollback_after_failure(error)
            if rollback_error is not None:
                uncertain = AuthoringError(
                    "recovery_required",
                    "Commit failed and automatic rollback is incomplete; recovery required",
                    {
                        "change_id": self.change_id,
                        "checkpoint": self._active_checkpoint,
                        "error_type": type(error).__name__,
                        "path": str(self.root),
                        "rollback_error_type": type(rollback_error).__name__,
                    },
                )
                uncertain.add_note(
                    "Automatic rollback failed: "
                    f"{type(rollback_error).__name__}: {rollback_error}"
                )
                raise uncertain from None
            if isinstance(error, AuthoringError) and error.code == "stale_model":
                raise
            raise AuthoringError(
                "commit_failed",
                "Authoring transaction commit failed and was rolled back",
                {
                    "change_id": self.change_id,
                    "checkpoint": self._active_checkpoint,
                    "error_type": type(error).__name__,
                },
            ) from None

        try:
            _cleanup_transaction(self.root)
        except Exception:
            return (self._cleanup_warning(),)
        return ()

    def _complete(self, name: str) -> None:
        self._active_checkpoint = name
        self._journal["last_completed_checkpoint"] = name
        _write_journal(self.journal_path, self._journal)
        self._checkpoint(name)

    def _rollback_after_failure(self, primary: Exception) -> Exception | None:
        try:
            _rollback(self.project.root, self.root, self._journal)
        except Exception as rollback_error:
            primary.add_note(
                "Transaction rollback failed: "
                f"{type(rollback_error).__name__}: {rollback_error}"
            )
            return rollback_error
        try:
            _cleanup_transaction(self.root)
        except Exception as cleanup_error:
            primary.add_note(
                "Rolled-back transaction cleanup failed: "
                f"{type(cleanup_error).__name__}: {cleanup_error}"
            )
        return None

    def _cleanup_warning(self) -> dict[str, str]:
        return {
            "code": "transaction_cleanup_pending",
            "message": (
                f"Committed transaction {self.change_id} requires cleanup recovery"
            ),
            "change_id": self.change_id,
        }


def recover_transactions(project: AuthoringProject) -> list[dict[str, str]]:
    """Recover every durable transaction journal under the exclusive lock."""

    if not isinstance(project, AuthoringProject):
        raise TypeError("project must be an AuthoringProject")
    try:
        if not project.transactions.exists():
            return []
        _require_owned_path(
            project.root,
            project.transactions,
            role="transaction registry",
            allow_missing_leaf=False,
        )
        entries = sorted(project.transactions.iterdir(), key=lambda path: path.name)
    except Exception as error:
        _recovery_error(
            "Transaction registry could not be inspected",
            project.transactions,
            error,
        )

    warnings: list[dict[str, str]] = []
    for entry in entries:
        if entry.name.startswith(_CLEANUP_TOMBSTONE_PREFIX):
            try:
                _delete_tombstone(entry)
            except Exception as error:
                _recovery_error("Transaction tombstone cleanup failed", entry, error)
    roots = [
        entry
        for entry in entries
        if not entry.name.startswith(_CLEANUP_TOMBSTONE_PREFIX)
        and _lstat_or_none(entry) is not None
    ]
    for root in roots:
        try:
            _require_real_directory(root, role="transaction directory")
            journal = _load_journal(project, root)
            if journal["phase"] == "committed":
                _cleanup_transaction(root)
                continue
            if journal["phase"] != "staging":
                _rollback(project.root, root, journal)
            _cleanup_transaction(root)
            change_id = journal["change_id"]
            warnings.append(
                {
                    "code": "recovered_transaction",
                    "message": f"Recovered interrupted transaction {change_id}",
                    "change_id": change_id,
                }
            )
        except AuthoringError:
            raise
        except Exception as error:
            _recovery_error("Transaction recovery failed", root, error)
    return warnings


def _prepare_artifact(
    transaction: Transaction,
    *,
    staged: Path,
    destination: str | os.PathLike[str] | None,
    required: bool,
    allowed_root: Path,
    role: str,
) -> dict[str, str] | None:
    if destination is None:
        if required:
            _transaction_error(
                "transaction_audit_missing",
                "A staged success audit destination is required",
                change_id=transaction.change_id,
            )
        if staged.exists():
            _transaction_error(
                "transaction_artifact_destination_missing",
                "A staged artifact has no final destination",
                change_id=transaction.change_id,
                role=role,
            )
        return None
    staged_identity = _lstat_or_none(staged)
    if staged_identity is None or not (
        stat.S_ISREG(staged_identity.st_mode) or stat.S_ISDIR(staged_identity.st_mode)
    ):
        _transaction_error(
            "transaction_artifact_missing",
            "A staged transaction artifact is missing or has an unsafe type",
            change_id=transaction.change_id,
            role=role,
            path=str(staged),
        )
    final = _coerce_destination(transaction.project, destination, allowed_root, role)
    if _lstat_or_none(final) is not None:
        _transaction_error(
            "transaction_artifact_exists",
            "A final transaction artifact destination already exists",
            change_id=transaction.change_id,
            role=role,
            path=str(final),
        )
    return {
        "staged": staged.relative_to(transaction.root).as_posix(),
        "destination": final.relative_to(transaction.project.root).as_posix(),
    }


def _coerce_destination(
    project: AuthoringProject,
    value: str | os.PathLike[str],
    allowed_root: Path,
    role: str,
) -> Path:
    if not isinstance(value, (str, os.PathLike)):
        raise TypeError(f"{role}_destination must be path-like")
    path = Path(value)
    if not path.is_absolute():
        path = project.root / path
    if allowed_root.parent != project.root or allowed_root.name not in {"runs", "changes"}:
        _transaction_error(
            "transaction_artifact_destination_unsafe",
            "A transaction artifact registry is not a direct project child",
            role=role,
            path=str(allowed_root),
        )
    try:
        relative = path.relative_to(allowed_root)
    except ValueError:
        _transaction_error(
            "transaction_artifact_destination_unsafe",
            "A transaction artifact destination is outside its registry",
            role=role,
            path=str(path),
        )
    if len(relative.parts) != 1 or any(
        part in {"", ".", ".."} for part in relative.parts
    ):
        _transaction_error(
            "transaction_artifact_destination_unsafe",
            "A transaction artifact destination must be one safe registry child",
            role=role,
            path=str(path),
        )
    _require_component(relative.parts[0], f"{role} destination")
    _require_owned_path(
        project.root,
        allowed_root,
        role=f"{role} registry",
        allow_missing_leaf=True,
    )
    return path


def _replace_target(project_root: Path, transaction_root: Path, target: Mapping[str, Any]) -> None:
    live = _journal_path(project_root, target["live"])
    candidate = _journal_path(transaction_root, target["candidate"])
    backup = _journal_path(transaction_root, target["backup"])
    _require_owned_path(
        transaction_root,
        candidate,
        role="candidate target",
        allow_missing_leaf=False,
    )
    _require_owned_path(
        project_root,
        live,
        role="live target",
        allow_missing_leaf=not target["live_existed"],
    )
    _ensure_owned_directory(transaction_root, backup.parent)
    _require_owned_path(
        transaction_root,
        backup,
        role="backup target",
        allow_missing_leaf=True,
    )
    _fsync_tree(candidate)
    if target["live_existed"]:
        _durable_replace(live, backup)
    elif _lstat_or_none(live) is not None:
        raise OSError(f"live target appeared before commit: {live}")
    try:
        _durable_replace(candidate, live)
    except BaseException:
        if target["live_existed"] and _lstat_or_none(backup) is not None:
            if _lstat_or_none(live) is not None:
                _remove_owned_path(project_root, live)
            _durable_replace(backup, live)
        raise


def _move_artifact(
    project_root: Path,
    transaction_root: Path,
    artifact: Mapping[str, str],
) -> None:
    staged = _journal_path(transaction_root, artifact["staged"])
    destination = _journal_path(project_root, artifact["destination"])
    _require_owned_path(
        transaction_root,
        staged,
        role="staged artifact",
        allow_missing_leaf=False,
    )
    _ensure_owned_directory(project_root, destination.parent)
    _require_owned_path(
        project_root,
        destination,
        role="artifact destination",
        allow_missing_leaf=True,
    )
    if _lstat_or_none(destination) is not None:
        raise OSError(f"artifact destination already exists: {destination}")
    _fsync_tree(staged)
    _durable_replace(staged, destination)
    _fsync_tree(destination)


def _rollback(project_root: Path, transaction_root: Path, journal: Mapping[str, Any]) -> None:
    errors: list[Exception] = []
    for artifact_name in ("staged_change", "staged_run"):
        artifact = journal.get(artifact_name)
        if artifact is None:
            continue
        try:
            destination = _journal_path(project_root, artifact["destination"])
            _require_owned_path(
                project_root,
                destination.parent,
                role="artifact registry",
                allow_missing_leaf=True,
            )
            if _lstat_or_none(destination.parent) is None:
                continue
            _require_owned_path(
                project_root,
                destination,
                role="artifact destination",
                allow_missing_leaf=True,
            )
            if _lstat_or_none(destination) is not None:
                _remove_owned_path(project_root, destination)
                _fsync_directory(destination.parent)
        except Exception as error:
            errors.append(error)

    for target in reversed(journal["targets"]):
        try:
            live = _journal_path(project_root, target["live"])
            backup = _journal_path(transaction_root, target["backup"])
            _require_owned_path(
                project_root,
                live,
                role="live rollback target",
                allow_missing_leaf=True,
            )
            _require_owned_path(
                transaction_root,
                backup,
                role="backup rollback target",
                allow_missing_leaf=True,
                allow_missing_parents=True,
            )
            backup_identity = _lstat_or_none(backup)
            if backup_identity is not None:
                if _lstat_or_none(live) is not None:
                    _remove_owned_path(project_root, live)
                _ensure_owned_directory(project_root, live.parent)
                _durable_replace(backup, live)
            elif not target["live_existed"] and _lstat_or_none(live) is not None:
                _remove_owned_path(project_root, live)
                _fsync_directory(live.parent)
        except Exception as error:
            errors.append(error)
    if errors:
        raise OSError(
            f"transaction rollback has {len(errors)} unsafe or failed operation(s): "
            f"{errors[0]}"
        ) from errors[0]


def _write_journal(path: Path, payload: Mapping[str, Any]) -> None:
    _require_real_directory(path.parent, role="transaction journal directory")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        _durable_replace(temporary, path)
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        try:
            temporary.unlink()
        except OSError:
            pass
        raise


def _load_journal(project: AuthoringProject, root: Path) -> dict[str, Any]:
    path = root / "journal.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as error:
        _recovery_error("Transaction journal could not be read", path, error)
    try:
        if not isinstance(value, dict):
            raise ValueError("journal is not an object")
        if value.get("schema_version") != JOURNAL_SCHEMA_VERSION:
            raise ValueError("unsupported journal schema")
        change_id = value["change_id"]
        _require_component(change_id, "change id")
        if change_id != root.name:
            raise ValueError("journal change id does not match its directory")
        if value["phase"] not in _PHASES:
            raise ValueError("invalid journal phase")
        if not isinstance(value["pre_digest"], str) or not value["pre_digest"]:
            raise ValueError("invalid pre-digest")
        if not isinstance(value["last_completed_checkpoint"], str):
            raise ValueError("invalid checkpoint")
        targets = value["targets"]
        if not isinstance(targets, list):
            raise ValueError("targets are not ordered")
        for target in targets:
            _validate_journal_target(target)
        if value["phase"] == "staging":
            if (
                targets
                or value.get("staged_run") is not None
                or value.get("staged_change") is not None
            ):
                raise ValueError("staging journal contains prepared destinations")
        else:
            _validate_journal_artifact(value.get("staged_run"), "runs", required=False)
            _validate_journal_artifact(
                value.get("staged_change"), "changes", required=True
            )
    except (KeyError, TypeError, ValueError) as error:
        _recovery_error("Transaction journal is malformed", path, error)
    return value


def _validate_journal_target(target: Any) -> None:
    if not isinstance(target, dict) or set(target) != {
        "live",
        "candidate",
        "backup",
        "live_existed",
    }:
        raise ValueError("invalid transaction target")
    if type(target["live_existed"]) is not bool:
        raise ValueError("invalid live_existed marker")
    live = _safe_relative(target["live"])
    if not _is_allowed_target(live):
        raise ValueError("unsafe live target")
    candidate = _safe_relative(target["candidate"])
    backup = _safe_relative(target["backup"])
    if candidate != PurePosixPath("candidate") / live:
        raise ValueError("candidate path does not match live target")
    if backup != PurePosixPath("backups") / live:
        raise ValueError("backup path does not match live target")


def _validate_journal_artifact(value: Any, root_name: str, *, required: bool) -> None:
    if value is None:
        if required:
            raise ValueError("required staged artifact is absent")
        return
    if not isinstance(value, dict) or set(value) != {"staged", "destination"}:
        raise ValueError("invalid staged artifact")
    staged = _safe_relative(value["staged"])
    destination = _safe_relative(value["destination"])
    expected_staged = (
        PurePosixPath("staged_artifacts/run")
        if root_name == "runs"
        else PurePosixPath("staged_artifacts/change.json")
    )
    if staged != expected_staged:
        raise ValueError("staged artifact escapes its directory")
    if len(destination.parts) != 2 or destination.parts[0] != root_name:
        raise ValueError("artifact destination escapes its registry")
    _require_component(destination.parts[1], "artifact destination")


def _coerce_project_target(value: str | os.PathLike[str]) -> PurePosixPath:
    if not isinstance(value, (str, os.PathLike)):
        raise TypeError("transaction target must be path-like")
    raw = os.fspath(value)
    if not isinstance(raw, str):
        raise TypeError("transaction target must be text")
    relative = _safe_relative(raw.replace("\\", "/"))
    if not _is_allowed_target(relative):
        _transaction_error(
            "transaction_target_unsafe",
            "A transaction target is outside authoring sources and exports",
            target=relative.as_posix(),
        )
    return relative


def _is_allowed_target(relative: PurePosixPath) -> bool:
    return (
        relative == PurePosixPath("economy.yaml")
        or relative == PurePosixPath("luban_exports")
        or (len(relative.parts) == 2 and relative.parts[0] == "Datas")
    )


def _safe_relative(value: Any) -> PurePosixPath:
    if not isinstance(value, str) or not value:
        raise ValueError("relative path must be non-empty text")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(
        part in {"", ".", ".."} for part in path.parts
    ):
        raise ValueError("unsafe relative path")
    return path


def _journal_path(root: Path, relative: str) -> Path:
    safe = _safe_relative(relative)
    return root.joinpath(*safe.parts)


def _require_component(value: Any, role: str) -> None:
    if not isinstance(value, str) or not value or value in {".", ".."}:
        raise TypeError(f"{role} must be a non-empty safe string")
    if Path(value).name != value or "/" in value or "\\" in value:
        raise ValueError(f"{role} must be one path component")


def _lstat_or_none(path: Path) -> os.stat_result | None:
    try:
        return path.lstat()
    except FileNotFoundError:
        return None


def _is_indirection(identity: os.stat_result) -> bool:
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    file_attributes = getattr(identity, "st_file_attributes", 0)
    return stat.S_ISLNK(identity.st_mode) or bool(file_attributes & reparse_flag)


def _require_real_directory(path: Path, *, role: str) -> os.stat_result:
    identity = _lstat_or_none(path)
    if identity is None:
        raise OSError(f"{role} is missing: {path}")
    if _is_indirection(identity) or not stat.S_ISDIR(identity.st_mode):
        raise OSError(f"{role} is an indirection or not a directory: {path}")
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as error:
        raise OSError(f"{role} could not be resolved safely: {path}") from error
    if resolved != path:
        raise OSError(f"{role} resolves through an indirection: {path}")
    return identity


def _require_owned_path(
    root: Path,
    path: Path,
    *,
    role: str,
    allow_missing_leaf: bool,
    allow_missing_parents: bool = False,
) -> os.stat_result | None:
    _require_real_directory(root, role=f"{role} boundary")
    try:
        relative = path.relative_to(root)
    except ValueError as error:
        raise OSError(f"{role} escapes its boundary: {path}") from error
    if not relative.parts:
        return root.lstat()
    resolved_root = root.resolve(strict=True)
    current = root
    for index, part in enumerate(relative.parts):
        if part in {"", ".", ".."}:
            raise OSError(f"{role} contains an unsafe path component: {path}")
        current = current / part
        identity = _lstat_or_none(current)
        is_leaf = index == len(relative.parts) - 1
        if identity is None:
            if (is_leaf and allow_missing_leaf) or allow_missing_parents:
                return None
            raise OSError(f"{role} is missing: {current}")
        if _is_indirection(identity):
            raise OSError(f"{role} crosses an indirection: {current}")
        if not is_leaf and not stat.S_ISDIR(identity.st_mode):
            raise OSError(f"{role} ancestor is not a directory: {current}")
        try:
            resolved = current.resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as error:
            raise OSError(f"{role} could not be resolved safely: {current}") from error
        if not resolved.is_relative_to(resolved_root):
            raise OSError(f"{role} resolves outside its boundary: {current}")
    return identity


def _ensure_owned_directory(root: Path, path: Path) -> None:
    _require_real_directory(root, role="directory boundary")
    try:
        relative = path.relative_to(root)
    except ValueError as error:
        raise OSError(f"directory escapes its boundary: {path}") from error
    current = root
    for part in relative.parts:
        if part in {"", ".", ".."}:
            raise OSError(f"directory contains an unsafe path component: {path}")
        current = current / part
        identity = _lstat_or_none(current)
        if identity is None:
            current.mkdir()
            _fsync_directory(current.parent)
        _require_real_directory(current, role="owned directory")


def _remove_owned_path(root: Path, path: Path) -> None:
    identity = _require_owned_path(
        root,
        path,
        role="removal target",
        allow_missing_leaf=False,
    )
    assert identity is not None
    if stat.S_ISDIR(identity.st_mode):
        shutil.rmtree(path)
    else:
        path.unlink()


def _cleanup_transaction(root: Path) -> None:
    _require_real_directory(root.parent, role="transaction registry")
    _require_real_directory(root, role="transaction cleanup root")
    _require_component(root.name, "transaction cleanup id")
    tombstone = root.parent / (
        f"{_CLEANUP_TOMBSTONE_PREFIX}{root.name}-{uuid.uuid4().hex}"
    )
    _durable_replace(root, tombstone)
    _delete_tombstone(tombstone)


def _delete_tombstone(tombstone: Path) -> None:
    if (
        tombstone.parent == tombstone
        or not tombstone.name.startswith(_CLEANUP_TOMBSTONE_PREFIX)
    ):
        raise OSError(f"invalid transaction cleanup tombstone: {tombstone}")
    _require_real_directory(tombstone.parent, role="transaction registry")
    _require_real_directory(tombstone, role="transaction cleanup tombstone")
    shutil.rmtree(tombstone)
    _fsync_directory(tombstone.parent)


def _durable_replace(source: Path, destination: Path) -> None:
    source_parent = source.parent
    destination_parent = destination.parent
    os.replace(source, destination)
    _fsync_directory(source_parent)
    _fsync_directory(destination_parent)


def _fsync_tree(path: Path) -> None:
    identity = path.lstat()
    if _is_indirection(identity):
        raise OSError(f"cannot fsync an indirection: {path}")
    if stat.S_ISREG(identity.st_mode):
        _fsync_file(path)
        return
    if stat.S_ISDIR(identity.st_mode):
        directories: list[Path] = []
        for child in sorted(path.iterdir()):
            child_identity = child.lstat()
            if _is_indirection(child_identity):
                raise OSError(f"cannot fsync a tree containing an indirection: {child}")
            if stat.S_ISREG(child_identity.st_mode):
                _fsync_file(child)
            elif stat.S_ISDIR(child_identity.st_mode):
                _fsync_tree(child)
                directories.append(child)
            else:
                raise OSError(f"cannot fsync an unsupported artifact type: {child}")
        for directory in reversed(directories):
            _fsync_directory(directory)
        _fsync_directory(path)
        return
    raise OSError(f"cannot fsync an unsupported artifact type: {path}")


def _fsync_file(path: Path) -> None:
    # Windows requires a writable descriptor for ``os.fsync`` even when no
    # bytes are changed.  The staged authoring artifacts are owned by this
    # transaction, so opening them read/write is safe and preserves content.
    with path.open("r+b") as handle:
        os.fsync(handle.fileno())


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        if _is_unsupported_directory_fsync(error):
            return
        raise
    try:
        os.fsync(descriptor)
    except OSError as error:
        if not _is_unsupported_directory_fsync(error):
            raise
    finally:
        os.close(descriptor)


def _is_unsupported_directory_fsync(error: OSError) -> bool:
    unsupported = {
        errno.EINVAL,
        getattr(errno, "ENOTSUP", errno.EINVAL),
        getattr(errno, "EOPNOTSUPP", errno.EINVAL),
    }
    if os.name == "nt":
        unsupported.update({errno.EACCES, errno.EBADF, errno.EPERM})
    return error.errno in unsupported


def _transaction_error(code: str, message: str, **details: Any) -> NoReturn:
    raise AuthoringError(code, message, details)


def _recovery_error(message: str, path: Path, error: Exception) -> NoReturn:
    raise AuthoringError(
        "recovery_failed",
        message,
        {
            "error_type": type(error).__name__,
            "path": str(path),
        },
    ) from None


__all__ = ["JOURNAL_SCHEMA_VERSION", "Transaction", "recover_transactions"]
