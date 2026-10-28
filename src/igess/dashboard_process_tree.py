"""Own a task's descendants, including the Windows virtualenv launcher."""

from __future__ import annotations

import os
import signal
from threading import Lock


class TaskProcessTree:
    def __init__(self, process, worker_pid):
        self.process = process
        self._lock = Lock()
        self._closed = False
        self._job = None
        if os.name == "nt":
            self._create_windows_job(worker_pid)

    def _create_windows_job(self, worker_pid):
        import ctypes
        from ctypes import wintypes

        class BasicLimits(ctypes.Structure):
            _fields_ = [("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
                        ("flags", wintypes.DWORD), ("minimum_working_set", ctypes.c_size_t),
                        ("maximum_working_set", ctypes.c_size_t), ("active_processes", wintypes.DWORD),
                        ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD),
                        ("scheduling", wintypes.DWORD)]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [("basic", BasicLimits), ("io_counters", ctypes.c_uint64 * 6),
                        ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
                        ("peak_process_memory", ctypes.c_size_t), ("peak_job_memory", ctypes.c_size_t)]

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        signatures = {
            "CreateJobObjectW": ([ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE),
            "SetInformationJobObject": ([wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD], wintypes.BOOL),
            "AssignProcessToJobObject": ([wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL),
            "OpenProcess": ([wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
            "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
        }
        for name, (args, result) in signatures.items():
            function = getattr(kernel, name)
            function.argtypes, function.restype = args, result
        job = kernel.CreateJobObjectW(None, None)
        if not job:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            limits = ExtendedLimits()
            limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
                raise ctypes.WinError(ctypes.get_last_error())
            # Virtualenv launchers can already own a separate job. Attach the
            # real interpreter to an empty nested job, not its launcher first.
            # It waits on stdin, so no business descendants exist yet.
            for pid in (worker_pid,):
                handle = kernel.OpenProcess(0x0101, False, pid)  # SET_QUOTA | TERMINATE
                if not handle:
                    raise ctypes.WinError(ctypes.get_last_error())
                try:
                    if not kernel.AssignProcessToJobObject(job, handle):
                        raise ctypes.WinError(ctypes.get_last_error())
                finally:
                    kernel.CloseHandle(handle)
        except BaseException:
            kernel.CloseHandle(job)
            raise
        self._kernel, self._job = kernel, job

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            if self._job is not None:
                self._kernel.CloseHandle(self._job)
                self._job = None
            elif os.name != "nt":
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            elif self.process.poll() is None:
                self.process.terminate()
