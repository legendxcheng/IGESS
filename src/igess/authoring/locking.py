"""Cross-process locking for consistent authoring project snapshots."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
import errno
import os
from pathlib import Path
import time
from typing import BinaryIO, TypeVar

from .project import AuthoringProject


_WINDOWS_LOCK_BYTE_COUNT = 256
_WINDOWS_RETRY_SECONDS = 0.05
_RETRYABLE_LOCK_ERRORS = {errno.EACCES, errno.EAGAIN, errno.EDEADLK}
_RecoveryResult = TypeVar("_RecoveryResult")
_LockRegion = tuple[int, int] | None


@contextmanager
def project_lock(
    project: AuthoringProject,
    exclusive: bool,
) -> Iterator[None]:
    """Hold the project's shared or exclusive OS lock for this context."""

    project.lock.parent.mkdir(parents=True, exist_ok=True)
    with project.lock.open("a+b") as initializer:
        _ensure_lock_bytes(initializer)
    with project.lock.open("r+b") as handle:
        region = _acquire(handle, exclusive=exclusive)
        try:
            yield
        finally:
            _release(handle, region)


@contextmanager
def recovered_shared_snapshot(
    project: AuthoringProject,
    recover_callback: Callable[[], _RecoveryResult],
) -> Iterator[_RecoveryResult]:
    """Recover exclusively, then hold a shared lock around snapshot loading.

    The two lock contexts are deliberately separate. A waiting writer may acquire
    the lock after recovery and completes before this command takes its snapshot.
    """

    with project_lock(project, exclusive=True):
        recovery_result = recover_callback()
    with project_lock(project, exclusive=False):
        yield recovery_result


def _ensure_lock_bytes(handle: BinaryIO) -> None:
    handle.seek(0, os.SEEK_END)
    missing = _WINDOWS_LOCK_BYTE_COUNT - handle.tell()
    if missing > 0:
        handle.write(b"\0" * missing)
        handle.flush()
    handle.seek(0)


def _acquire(handle: BinaryIO, *, exclusive: bool) -> _LockRegion:
    if os.name == "nt":
        import msvcrt

        if exclusive:
            region_candidates = ((0, _WINDOWS_LOCK_BYTE_COUNT),)
            mode = msvcrt.LK_NBLCK
        else:
            first = os.getpid() % _WINDOWS_LOCK_BYTE_COUNT
            region_candidates = tuple(
                ((first + offset) % _WINDOWS_LOCK_BYTE_COUNT, 1)
                for offset in range(_WINDOWS_LOCK_BYTE_COUNT)
            )
            mode = msvcrt.LK_NBRLCK
        while True:
            for offset, length in region_candidates:
                os.lseek(handle.fileno(), offset, os.SEEK_SET)
                try:
                    msvcrt.locking(handle.fileno(), mode, length)
                    return offset, length
                except OSError as error:
                    if error.errno not in _RETRYABLE_LOCK_ERRORS:
                        raise
            time.sleep(_WINDOWS_RETRY_SECONDS)
    else:
        import fcntl

        mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        fcntl.flock(handle.fileno(), mode)
        return None


def _release(handle: BinaryIO, region: _LockRegion) -> None:
    if os.name == "nt":
        import msvcrt

        assert region is not None
        offset, length = region
        os.lseek(handle.fileno(), offset, os.SEEK_SET)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, length)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
