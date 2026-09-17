"""Which process is SERVING out of this state directory, so the others can say so.

Every SQLite crash this repo has taken shares one shape: two processes with the same
store file open, one of them long-lived. Measured 2026-08-24 across 21 `SIGBUS ·
FS pagein error: 22` reports, the crashing process was frequently NOT the API —
`parent=zsh`, `parent=uv`, `parent=Exited process` — i.e. bare scripts, CLI commands and
test runs opening `data/` while the API served out of it. The operating rule ("one writer
per `data/`", later tightened to "do not open it at all, `mode=ro` included") has been
written down four times and violated anyway, because nothing in the code ever said so at
the moment it happened.

This is that seam. The API claims the directory on startup; anyone else opening a store
under it learns, once, from the process doing it.

It does NOT refuse. `aughor` CLI subcommands are legitimately run against a live install,
and a hard failure would turn a latent risk into a certain outage. What it removes is the
silence.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

_LOG = logging.getLogger(__name__)

#: Lives beside the stores it describes, so a redirected state dir (the test conftest,
#: an on-prem install) gets its own and never sees the developer's.
PIDFILE_NAME = ".serving.pid"

_checked = False
_foreign = False

#: Read by `_alive`, and set by the tests that hold its Windows branch.
_WINDOWS = os.name == "nt"

# kernel32 values for the Windows liveness probe.
_SYNCHRONIZE = 0x00100000
_WAIT_TIMEOUT = 0x00000102
_ERROR_ACCESS_DENIED = 5


def _pidfile() -> Path:
    from aughor.db.paths import state_dir
    return state_dir() / PIDFILE_NAME


def claim(pid: Optional[int] = None) -> None:
    """Record that this process serves out of the state directory. Never raises."""
    try:
        path = _pidfile()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(pid if pid is not None else os.getpid()))
    except Exception as exc:                    # noqa: BLE001 — a marker is not worth a boot failure
        _LOG.debug("could not claim the state directory: %s", exc)


def release() -> None:
    """Drop the claim on a clean shutdown. Never raises."""
    try:
        _pidfile().unlink(missing_ok=True)
    except Exception as exc:                    # noqa: BLE001
        _LOG.debug("could not release the state directory: %s", exc)


def serving_pid() -> Optional[int]:
    """The live pid serving this state directory, or None.

    A pidfile left behind by a crash names a dead pid — and this whole module exists
    because of a crash, so a stale file is the EXPECTED case, not the exotic one. The
    liveness probe is what keeps it from crying wolf forever after the first SIGBUS.
    """
    try:
        pid = int(_pidfile().read_text().strip())
    except (OSError, ValueError):
        return None
    return pid if _alive(pid) else None


def _alive(pid: int) -> bool:
    """Whether a process with this pid is running.

    Never `os.kill(pid, 0)` on Windows. There signal 0 is CTRL_C_EVENT, so CPython calls
    GenerateConsoleCtrlEvent(CTRL_C_EVENT, pid): a Ctrl+C for process group `pid`. A server's
    pid is no process group, so the console host finds nobody to deliver it to, resets its
    target to every process and keeps the Ctrl+C pending (conhost's ProcessCtrlEvents); the
    next process to touch that console delivers it to all of them. `/health` asks this, so
    on Windows `aughor up` stopped itself seconds after both servers answered.
    """
    if _WINDOWS:
        return _alive_on_windows(pid)
    try:
        os.kill(pid, 0)                         # POSIX signal 0: liveness only, delivers nothing
    except ProcessLookupError:
        return False
    except PermissionError:
        return True                             # alive, owned by somebody else
    return True


def _alive_on_windows(pid: int) -> bool:
    """Open the process and ask whether it has exited, which sends it nothing."""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel32.OpenProcess(_SYNCHRONIZE, False, pid)
    if not handle:
        return ctypes.get_last_error() == _ERROR_ACCESS_DENIED   # alive, owned by somebody else
    try:
        # An exited process can still be opened while anything holds a handle to it.
        return kernel32.WaitForSingleObject(handle, 0) == _WAIT_TIMEOUT
    finally:
        kernel32.CloseHandle(handle)


def warn_if_foreign(path: Path) -> bool:
    """Say once, loudly, that this process is opening a store another one is serving.

    Returns whether it fired, so the diagnostics surface can report it.

    Resolved ONCE per process, on the first store open, and then answered from memory —
    `connect_store` runs per operation, thousands of times, and a diagnostic that reads a
    file on each of them would cost more than the thing it warns about. The case this
    forgoes is a process that opens a store BEFORE the server claims the directory, which
    is not the dangerous ordering: the hazard is arriving at a directory already served.
    """
    global _checked, _foreign
    if _checked:
        return _foreign
    try:
        _checked = True
        other = serving_pid()
        if other is None or other == os.getpid():
            return False
        _foreign = True
        _LOG.error(
            "This process (pid %d) is opening %s while pid %d is SERVING out of the same "
            "state directory. Two processes mapped into one SQLite WAL index is the "
            "precondition for the SIGBUS in walFindFrame that has killed this app "
            "repeatedly — a read-only connection counts, because it maps the -shm too. "
            "Redirect the store (AUGHOR_SYSTEM_DB=/tmp/scratch.db, AUGHOR_STATE_DIR=...) "
            "or stop the server first.",
            os.getpid(), path, other)
        return True
    except Exception:                           # noqa: BLE001 — a warning must never break a store open
        return False
