"""Terminate a worker process together with every child it spawned.

On Windows, QProcess.terminate() only posts WM_CLOSE to the process windows,
which does nothing for a windowless spotDL worker, and QProcess.kill() only
ends the worker itself: FFmpeg children keep running.

Two mechanisms are combined:
- The descendants of the worker are enumerated from a process snapshot and
  terminated explicitly. This always works, including when the GUI itself runs
  inside a job that lets children silently break away from nested jobs (as
  some terminals and IDEs do).
- The worker is also placed in a Job Object configured to kill its processes
  when its last handle is closed, which covers the GUI exiting or crashing.
"""

import sys


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9
    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
    _PROCESS_TERMINATE = 0x0001
    _PROCESS_SET_QUOTA = 0x0100
    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    _TH32CS_SNAPPROCESS = 0x00000002
    _INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
        )]

    class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
            ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", _IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    class _PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    def _declare(name, restype, *argtypes):
        function = getattr(_kernel32, name)
        function.restype = restype
        function.argtypes = list(argtypes)

    _declare("CreateJobObjectW", wintypes.HANDLE, wintypes.LPVOID, wintypes.LPCWSTR)
    _declare("SetInformationJobObject", wintypes.BOOL, wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD)
    _declare("AssignProcessToJobObject", wintypes.BOOL, wintypes.HANDLE, wintypes.HANDLE)
    _declare("TerminateJobObject", wintypes.BOOL, wintypes.HANDLE, wintypes.UINT)
    _declare("OpenProcess", wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    _declare("TerminateProcess", wintypes.BOOL, wintypes.HANDLE, wintypes.UINT)
    _declare("GetProcessTimes", wintypes.BOOL, wintypes.HANDLE, *[ctypes.POINTER(wintypes.FILETIME)] * 4)
    _declare("CreateToolhelp32Snapshot", wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD)
    _declare("Process32FirstW", wintypes.BOOL, wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W))
    _declare("Process32NextW", wintypes.BOOL, wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W))
    _declare("CloseHandle", wintypes.BOOL, wintypes.HANDLE)
    _declare("CreateFileW", wintypes.HANDLE, wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
             wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)

    _GENERIC_READ = 0x80000000
    _OPEN_EXISTING = 3
    _ERROR_SHARING_VIOLATION = 32

    def _creation_time(handle):
        created, exited, kernel, user = (wintypes.FILETIME() for _ in range(4))
        if not _kernel32.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited),
                                         ctypes.byref(kernel), ctypes.byref(user)):
            return None
        return (created.dwHighDateTime << 32) | created.dwLowDateTime

    def _children_by_parent():
        snapshot = _kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
        if not snapshot or snapshot == _INVALID_HANDLE_VALUE:
            return {}
        children = {}
        try:
            entry = _PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(entry)
            more = _kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
            while more:
                children.setdefault(entry.th32ParentProcessID, []).append(entry.th32ProcessID)
                more = _kernel32.Process32NextW(snapshot, ctypes.byref(entry))
        finally:
            _kernel32.CloseHandle(snapshot)
        return children


def is_file_in_use(path):
    """Return True if another process currently has the file open (Windows only).

    The file is opened without any sharing allowed: this fails with a sharing
    violation while a writer such as FFmpeg still holds it.
    """
    if sys.platform != "win32":
        return False
    handle = _kernel32.CreateFileW(str(path), _GENERIC_READ, 0, None, _OPEN_EXISTING, 0, None)
    if handle == _INVALID_HANDLE_VALUE:
        return ctypes.get_last_error() == _ERROR_SHARING_VIOLATION
    _kernel32.CloseHandle(handle)
    return False


class ProcessTree:
    """Tracks one worker process and terminates it with all its descendants."""

    def __init__(self):
        self.pid = None
        self._job = None
        # Holding a handle on the worker prevents its PID from being reused.
        self._root = None
        self._root_created = None

    def attach(self, pid):
        """Start tracking a freshly started worker. Returns False if it cannot be tracked."""
        self.pid = pid
        if sys.platform != "win32" or not pid:
            return False

        self._root = _kernel32.OpenProcess(
            _PROCESS_TERMINATE | _PROCESS_SET_QUOTA | _PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not self._root:
            return False
        self._root_created = _creation_time(self._root)

        # The job is only a safety net for when the GUI dies; failing to set it
        # up does not prevent kill() from working.
        job = _kernel32.CreateJobObjectW(None, None)
        if job:
            info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
            info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            configured = _kernel32.SetInformationJobObject(
                job, _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
                ctypes.byref(info), ctypes.sizeof(info),
            )
            if configured and _kernel32.AssignProcessToJobObject(job, self._root):
                self._job = job
            else:
                _kernel32.CloseHandle(job)
        return True

    def kill(self):
        """Forcefully terminate the worker and every process it started."""
        if sys.platform != "win32" or not self._root:
            return
        # The whole tree must be collected before anything is terminated: when
        # an intermediate process dies (possibly taking others with it through
        # its own job), its children can no longer be found from the worker.
        handles = self._open_descendants()
        _kernel32.TerminateProcess(self._root, 1)
        for handle in handles:
            _kernel32.TerminateProcess(handle, 1)
            _kernel32.CloseHandle(handle)
        if self._job:
            _kernel32.TerminateJobObject(self._job, 1)

    def _open_descendants(self):
        """Open a handle on every current descendant of the worker, parents first."""
        children = _children_by_parent()
        # A child is only trusted if it was created after its parent, since the
        # parent PID recorded by Windows may belong to a process that has exited.
        pending = [(self.pid, self._root_created)]
        handles = []
        while pending:
            parent_pid, parent_created = pending.pop()
            for child_pid in children.get(parent_pid, []):
                handle = _kernel32.OpenProcess(
                    _PROCESS_TERMINATE | _PROCESS_QUERY_LIMITED_INFORMATION, False, child_pid)
                if not handle:
                    continue
                created = _creation_time(handle)
                if created is None or parent_created is None or created < parent_created:
                    _kernel32.CloseHandle(handle)
                    continue
                handles.append(handle)
                pending.append((child_pid, created))
        return handles

    def close(self):
        """Release the handles. Any process still in the job is killed."""
        if self._job:
            _kernel32.CloseHandle(self._job)
            self._job = None
        if self._root:
            _kernel32.CloseHandle(self._root)
            self._root = None
        self.pid = None
