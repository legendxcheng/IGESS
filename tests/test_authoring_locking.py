from __future__ import annotations

from multiprocessing.context import SpawnContext
from multiprocessing.synchronize import Event
from pathlib import Path
import multiprocessing

import pytest

from igess.authoring.locking import project_lock, recovered_shared_snapshot
from igess.authoring.project import AuthoringProject


_PROCESS_TIMEOUT_SECONDS = 4.0
_BLOCKED_OBSERVATION_SECONDS = 0.3


def _make_project(root: Path) -> AuthoringProject:
    root.mkdir()
    (root / "economy.yaml").write_text("version: 1\n", encoding="utf-8")
    (root / "Datas").mkdir()
    (root / "luban_exports").mkdir()
    return AuthoringProject.discover(root)


def _hold_project_lock(
    root: str,
    exclusive: bool,
    attempting: Event,
    ready: Event,
    release: Event,
) -> None:
    project = AuthoringProject.discover(root)
    attempting.set()
    with project_lock(project, exclusive=exclusive):
        ready.set()
        release.wait(_PROCESS_TIMEOUT_SECONDS)


def _spawn_holder(
    context: SpawnContext,
    project: AuthoringProject,
    *,
    exclusive: bool,
) -> tuple[multiprocessing.Process, Event, Event, Event]:
    attempting = context.Event()
    ready = context.Event()
    release = context.Event()
    process = context.Process(
        target=_hold_project_lock,
        args=(str(project.root), exclusive, attempting, ready, release),
    )
    process.start()
    return process, attempting, ready, release


def _finish(process: multiprocessing.Process, release: Event) -> None:
    release.set()
    process.join(_PROCESS_TIMEOUT_SECONDS)
    if process.is_alive():
        process.terminate()
        process.join(_PROCESS_TIMEOUT_SECONDS)
    assert process.exitcode == 0


def test_shared_processes_overlap(tmp_path: Path) -> None:
    project = _make_project(tmp_path / "model")
    context = multiprocessing.get_context("spawn")
    first, _, first_acquired, first_release = _spawn_holder(
        context, project, exclusive=False
    )
    second = None
    second_release = None
    try:
        assert first_acquired.wait(_PROCESS_TIMEOUT_SECONDS)
        second, _, second_acquired, second_release = _spawn_holder(
            context, project, exclusive=False
        )

        assert second_acquired.wait(_PROCESS_TIMEOUT_SECONDS)
        assert first.is_alive()
        assert not first_release.is_set()
    finally:
        _finish(first, first_release)
        if second is not None and second_release is not None:
            _finish(second, second_release)


@pytest.mark.parametrize("waiting_exclusive", [False, True])
def test_exclusive_process_blocks_other_locks(
    tmp_path: Path,
    waiting_exclusive: bool,
) -> None:
    project = _make_project(tmp_path / "model")
    context = multiprocessing.get_context("spawn")
    first, _, first_acquired, first_release = _spawn_holder(
        context, project, exclusive=True
    )
    second = None
    second_release = None
    try:
        assert first_acquired.wait(_PROCESS_TIMEOUT_SECONDS)
        second, second_attempting, second_acquired, second_release = _spawn_holder(
            context, project, exclusive=waiting_exclusive
        )
        assert second_attempting.wait(_PROCESS_TIMEOUT_SECONDS)
        assert not second_acquired.wait(_BLOCKED_OBSERVATION_SECONDS)

        first_release.set()
        assert second_acquired.wait(_PROCESS_TIMEOUT_SECONDS)
    finally:
        _finish(first, first_release)
        if second is not None and second_release is not None:
            _finish(second, second_release)


def test_terminated_process_releases_lock(tmp_path: Path) -> None:
    project = _make_project(tmp_path / "model")
    context = multiprocessing.get_context("spawn")
    holder, _, holder_acquired, holder_release = _spawn_holder(
        context, project, exclusive=True
    )
    waiter = None
    waiter_release = None
    try:
        assert holder_acquired.wait(_PROCESS_TIMEOUT_SECONDS)
        waiter, waiter_attempting, waiter_acquired, waiter_release = _spawn_holder(
            context, project, exclusive=True
        )
        assert waiter_attempting.wait(_PROCESS_TIMEOUT_SECONDS)
        assert not waiter_acquired.wait(_BLOCKED_OBSERVATION_SECONDS)

        holder.terminate()
        holder.join(_PROCESS_TIMEOUT_SECONDS)
        assert not holder.is_alive()
        assert waiter_acquired.wait(_PROCESS_TIMEOUT_SECONDS)
    finally:
        if holder.is_alive():
            holder.terminate()
            holder.join(_PROCESS_TIMEOUT_SECONDS)
        if waiter is not None and waiter_release is not None:
            _finish(waiter, waiter_release)


def test_context_exception_releases_lock(tmp_path: Path) -> None:
    project = _make_project(tmp_path / "model")
    context = multiprocessing.get_context("spawn")

    with pytest.raises(RuntimeError, match="stop snapshot"):
        with project_lock(project, exclusive=True):
            raise RuntimeError("stop snapshot")

    waiter, _, waiter_acquired, waiter_release = _spawn_holder(
        context, project, exclusive=True
    )
    try:
        assert waiter_acquired.wait(_PROCESS_TIMEOUT_SECONDS)
    finally:
        _finish(waiter, waiter_release)


def test_recovered_shared_snapshot_recovers_exclusively_then_holds_shared(
    tmp_path: Path,
) -> None:
    project = _make_project(tmp_path / "model")
    context = multiprocessing.get_context("spawn")
    recovery_waiter = None
    recovery_attempting = None
    recovery_acquired = None
    recovery_release = None

    def recover() -> list[str]:
        nonlocal recovery_waiter, recovery_attempting, recovery_acquired
        nonlocal recovery_release
        (
            recovery_waiter,
            recovery_attempting,
            recovery_acquired,
            recovery_release,
        ) = _spawn_holder(context, project, exclusive=False)
        assert recovery_attempting.wait(_PROCESS_TIMEOUT_SECONDS)
        assert not recovery_acquired.wait(_BLOCKED_OBSERVATION_SECONDS)
        return ["recovered_transaction"]

    writer = None
    writer_release = None
    try:
        with recovered_shared_snapshot(project, recover) as warnings:
            assert warnings == ["recovered_transaction"]
            assert recovery_waiter is not None
            assert recovery_attempting is not None
            assert recovery_acquired is not None
            assert recovery_release is not None
            assert recovery_acquired.wait(_PROCESS_TIMEOUT_SECONDS)

            writer, writer_attempting, writer_acquired, writer_release = _spawn_holder(
                context, project, exclusive=True
            )
            assert writer_attempting.wait(_PROCESS_TIMEOUT_SECONDS)
            assert not writer_acquired.wait(_BLOCKED_OBSERVATION_SECONDS)
            recovery_release.set()

        assert writer_acquired.wait(_PROCESS_TIMEOUT_SECONDS)
    finally:
        if recovery_waiter is not None and recovery_release is not None:
            _finish(recovery_waiter, recovery_release)
        if writer is not None and writer_release is not None:
            _finish(writer, writer_release)
