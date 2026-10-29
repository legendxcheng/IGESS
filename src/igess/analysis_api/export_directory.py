"""Create analysis files through a bound directory, not a re-resolved pathname."""
from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import stat

from .contracts import AnalysisError
from .snapshot import safe_path


def _windows_lock_directory(path: Path) -> int:
    import ctypes
    from ctypes import wintypes
    import msvcrt

    before = path.lstat()
    create = ctypes.windll.kernel32.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                       wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    # Bind identity and minimize concurrent replacement; writes still use relative handles.
    handle = create(str(path), 0x80, 0x3, None, 3, 0x02000000 | 0x00200000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError()
    try:
        fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    except BaseException:
        ctypes.windll.kernel32.CloseHandle(handle)
        raise
    opened = os.fstat(fd)
    if (not stat.S_ISDIR(opened.st_mode) or getattr(opened, "st_file_attributes", 0) & 0x400
            or not os.path.samestat(before, opened)):
        os.close(fd)
        raise AnalysisError("input_changed", "Export directory changed while binding")
    return fd


@contextmanager
def new_export_directory(path: Path):
    """Parent must exist. Lock Windows ancestry; traverse POSIX ancestry via dir_fd."""
    handles = []
    try:
        if os.name == "nt":
            for parent in reversed(path.parents):
                handles.append(_windows_lock_directory(parent))
            handles.append(_windows_create_relative(handles[-1], path.name, directory=True))
        else:
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            handles.append(os.open(path.anchor, flags))
            for component in path.parent.parts[1:]:
                handles.append(os.open(component, flags, dir_fd=handles[-1]))
            os.mkdir(path.name, dir_fd=handles[-1])
            handles.append(os.open(path.name, flags, dir_fd=handles[-1]))
        directory_fd = handles[-1]
        identity = os.fstat(directory_fd)
        yield directory_fd
        safe_path(path, path)
        if not os.path.samestat(identity, path.stat()):
            raise AnalysisError("input_changed", "Export directory moved during write")
    finally:
        for fd in reversed(handles):
            os.close(fd)


def write_export_file(path: Path, directory_fd: int, name: str, body: str) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    if os.name == "nt":
        fd = _windows_create_relative(directory_fd, name)
    else:
        fd = os.open(name, flags, 0o600, dir_fd=directory_fd)
    with os.fdopen(fd, "wb") as stream:
        stream.write(body.encode("utf-8"))
        stream.flush()
        os.fsync(stream.fileno())


def _windows_create_relative(directory_fd: int, name: str, *, directory: bool = False) -> int:
    """NtCreateFile binds creation to the actual directory even if its path moves."""
    import ctypes
    from ctypes import wintypes
    import msvcrt

    class UnicodeString(ctypes.Structure):
        _fields_ = [("Length", wintypes.USHORT), ("MaximumLength", wintypes.USHORT),
                    ("Buffer", wintypes.LPWSTR)]

    class ObjectAttributes(ctypes.Structure):
        _fields_ = [("Length", wintypes.ULONG), ("RootDirectory", wintypes.HANDLE),
                    ("ObjectName", ctypes.POINTER(UnicodeString)), ("Attributes", wintypes.ULONG),
                    ("SecurityDescriptor", wintypes.LPVOID), ("SecurityQualityOfService", wintypes.LPVOID)]

    class IoStatus(ctypes.Structure):
        _fields_ = [("Status", ctypes.c_void_p), ("Information", ctypes.c_size_t)]

    buffer = ctypes.create_unicode_buffer(name)
    text = UnicodeString(len(name.encode("utf-16-le")), ctypes.sizeof(buffer), ctypes.cast(buffer, wintypes.LPWSTR))
    attributes = ObjectAttributes(ctypes.sizeof(ObjectAttributes), msvcrt.get_osfhandle(directory_fd),
                                  ctypes.pointer(text), 0x40, None, None)
    handle, io = wintypes.HANDLE(), IoStatus()
    create = ctypes.windll.ntdll.NtCreateFile
    create.argtypes = [ctypes.POINTER(wintypes.HANDLE), wintypes.ULONG, ctypes.POINTER(ObjectAttributes),
                       ctypes.POINTER(IoStatus), ctypes.c_void_p, wintypes.ULONG, wintypes.ULONG,
                       wintypes.ULONG, wintypes.ULONG, ctypes.c_void_p, wintypes.ULONG]
    create.restype = wintypes.LONG
    # Write + synchronize, exclusive create, synchronous non-directory, no link following.
    access = 0x00100081 if directory else 0x00100002
    options = 0x20 | (0x1 if directory else 0x40) | 0x00200000
    status = create(ctypes.byref(handle), access, ctypes.byref(attributes), ctypes.byref(io),
                    None, 0x80, 0x3 if directory else 0, 2, options, None, 0)
    if status < 0:
        raise ctypes.WinError(ctypes.windll.ntdll.RtlNtStatusToDosError(status))
    if handle.value is None:
        raise AnalysisError("unsafe_output", "Native file creation returned no handle")
    try:
        return msvcrt.open_osfhandle(handle.value, (os.O_RDONLY if directory else os.O_WRONLY) | os.O_BINARY)
    except BaseException:
        ctypes.windll.kernel32.CloseHandle(handle)
        raise
