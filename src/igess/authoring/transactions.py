"""Recoverable publication of authoring sources, exports, and artifacts."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
from typing import Any, NoReturn

from .project import AuthoringProject
from .response import AuthoringError


JOURNAL_SCHEMA_VERSION = 1
_PHASES = {"prepared", "committing", "committed"}
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
        self._active_checkpoint = "prepared"
        self._prepared = False
        self._journal: dict[str, Any] = {
            "schema_version": JOURNAL_SCHEMA_VERSION,
            "change_id": change_id,
            "phase": "prepared",
            "pre_digest": pre_digest,
            "targets": [],
            "staged_run": None,
            "staged_change": None,
            "last_completed_checkpoint": "prepared",
        }

        try:
            project.transactions.mkdir(parents=True, exist_ok=True)
            self.root.mkdir()
            self.backups_dir.mkdir()
            self.staged_artifacts_dir.mkdir()
            _write_journal(self.journal_path, self._journal)
        except FileExistsError:
            _transaction_error(
                "transaction_exists",
                "A transaction with this change id already exists",
                change_id=change_id,
                path=str(self.root),
            )
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
        self._journal["targets"] = ordered
        self._journal["staged_run"] = staged_run
        self._journal["staged_change"] = staged_change
        _write_journal(self.journal_path, self._journal)
        self._prepared = True

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
            self._rollback_after_failure(error)
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

    def _rollback_after_failure(self, primary: Exception) -> None:
        try:
            _rollback(self.project.root, self.root, self._journal)
        except Exception as rollback_error:
            primary.add_note(
                "Transaction rollback failed: "
                f"{type(rollback_error).__name__}: {rollback_error}"
            )
            return
        try:
            _cleanup_transaction(self.root)
        except Exception as cleanup_error:
            primary.add_note(
                "Rolled-back transaction cleanup failed: "
                f"{type(cleanup_error).__name__}: {cleanup_error}"
            )

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
        roots = sorted(
            (path for path in project.transactions.iterdir() if path.is_dir()),
            key=lambda path: path.name,
        )
    except Exception as error:
        _recovery_error(
            "Transaction registry could not be inspected",
            project.transactions,
            error,
        )

    warnings: list[dict[str, str]] = []
    for root in roots:
        try:
            journal = _load_journal(project, root)
            if journal["phase"] == "committed":
                _cleanup_transaction(root)
                continue
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
    try:
        relative = path.relative_to(allowed_root)
    except ValueError:
        _transaction_error(
            "transaction_artifact_destination_unsafe",
            "A transaction artifact destination is outside its registry",
            role=role,
            path=str(path),
        )
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        _transaction_error(
            "transaction_artifact_destination_unsafe",
            "A transaction artifact destination is unsafe",
            role=role,
            path=str(path),
        )
    return path


def _replace_target(project_root: Path, transaction_root: Path, target: Mapping[str, Any]) -> None:
    live = _journal_path(project_root, target["live"])
    candidate = _journal_path(transaction_root, target["candidate"])
    backup = _journal_path(transaction_root, target["backup"])
    backup.parent.mkdir(parents=True, exist_ok=True)
    if target["live_existed"]:
        os.replace(live, backup)
    elif _lstat_or_none(live) is not None:
        raise OSError(f"live target appeared before commit: {live}")
    try:
        os.replace(candidate, live)
    except BaseException:
        if target["live_existed"] and _lstat_or_none(backup) is not None:
            if _lstat_or_none(live) is not None:
                _remove_path(live)
            os.replace(backup, live)
        raise
    _fsync_directory(live.parent)


def _move_artifact(
    project_root: Path,
    transaction_root: Path,
    artifact: Mapping[str, str],
) -> None:
    staged = _journal_path(transaction_root, artifact["staged"])
    destination = _journal_path(project_root, artifact["destination"])
    destination.parent.mkdir(parents=True, exist_ok=True)
    if _lstat_or_none(destination) is not None:
        raise OSError(f"artifact destination already exists: {destination}")
    os.replace(staged, destination)
    _fsync_tree(destination)
    _fsync_directory(destination.parent)


def _rollback(project_root: Path, transaction_root: Path, journal: Mapping[str, Any]) -> None:
    for artifact_name in ("staged_change", "staged_run"):
        artifact = journal.get(artifact_name)
        if artifact is None:
            continue
        destination = _journal_path(project_root, artifact["destination"])
        if _lstat_or_none(destination) is not None:
            _remove_path(destination)
            _fsync_directory(destination.parent)

    for target in reversed(journal["targets"]):
        live = _journal_path(project_root, target["live"])
        backup = _journal_path(transaction_root, target["backup"])
        backup_identity = _lstat_or_none(backup)
        if backup_identity is not None:
            if _lstat_or_none(live) is not None:
                _remove_path(live)
            live.parent.mkdir(parents=True, exist_ok=True)
            os.replace(backup, live)
            _fsync_directory(live.parent)
        elif not target["live_existed"] and _lstat_or_none(live) is not None:
            _remove_path(live)
            _fsync_directory(live.parent)


def _write_journal(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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
        os.replace(temporary, path)
        _fsync_directory(path.parent)
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
        _validate_journal_artifact(value.get("staged_run"), "runs", required=False)
        _validate_journal_artifact(value.get("staged_change"), "changes", required=True)
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
    if staged.parts[0] != "staged_artifacts":
        raise ValueError("staged artifact escapes its directory")
    if destination.parts[0] != root_name:
        raise ValueError("artifact destination escapes its registry")


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
        or (len(relative.parts) >= 2 and relative.parts[0] == "Datas")
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


def _remove_path(path: Path) -> None:
    identity = path.lstat()
    if stat.S_ISDIR(identity.st_mode) and not stat.S_ISLNK(identity.st_mode):
        shutil.rmtree(path)
    else:
        path.unlink()


def _cleanup_transaction(root: Path) -> None:
    shutil.rmtree(root)
    _fsync_directory(root.parent)


def _fsync_tree(path: Path) -> None:
    identity = path.lstat()
    if stat.S_ISREG(identity.st_mode):
        _fsync_file(path)
        return
    if stat.S_ISDIR(identity.st_mode):
        for child in sorted(path.rglob("*")):
            child_identity = child.lstat()
            if stat.S_ISREG(child_identity.st_mode):
                _fsync_file(child)
        for directory in sorted(
            (item for item in path.rglob("*") if item.is_dir()),
            key=lambda item: len(item.parts),
            reverse=True,
        ):
            _fsync_directory(directory)
        _fsync_directory(path)


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
    except (OSError, ValueError):
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


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
