"""Move files to the Windows Recycle Bin, so that the user can restore them."""

import sys


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _FO_DELETE = 3
    _FOF_SILENT = 0x0004
    _FOF_NOCONFIRMATION = 0x0010
    _FOF_ALLOWUNDO = 0x0040
    _FOF_NOERRORUI = 0x0400

    class _SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("wFunc", wintypes.UINT),
            ("pFrom", wintypes.LPCWSTR),
            ("pTo", wintypes.LPCWSTR),
            ("fFlags", ctypes.c_ushort),
            ("fAnyOperationsAborted", wintypes.BOOL),
            ("hNameMappings", wintypes.LPVOID),
            ("lpszProgressTitle", wintypes.LPCWSTR),
        ]

    _shell32 = ctypes.WinDLL("shell32")
    _shell32.SHFileOperationW.restype = ctypes.c_int
    _shell32.SHFileOperationW.argtypes = [ctypes.POINTER(_SHFILEOPSTRUCTW)]


def move_to_recycle_bin(paths):
    """Move the given files to the Recycle Bin. Returns the ones that could
    not be moved (all of them on other platforms)."""
    paths = [str(path) for path in paths]
    if sys.platform != "win32" or not paths:
        return paths
    remaining = []
    # One call per file, so that one failure does not hide the others.
    for path in paths:
        operation = _SHFILEOPSTRUCTW(
            wFunc=_FO_DELETE,
            pFrom=path + "\0",  # the list must end with two null characters
            fFlags=_FOF_ALLOWUNDO | _FOF_NOCONFIRMATION | _FOF_SILENT | _FOF_NOERRORUI,
        )
        if _shell32.SHFileOperationW(ctypes.byref(operation)) != 0 or operation.fAnyOperationsAborted:
            remaining.append(path)
    return remaining
