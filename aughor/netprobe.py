"""Is something listening on this port, and what is it — shared by `cli` and `doctor`.

Lifted out of `aughor/cli.py` when `doctor` needed the same two answers. A private helper
imported across modules is what `test_kernel_contracts::test_no_new_private_cross_imports`
exists to stop, and it is right: two callers make this shared infrastructure, and shared
infrastructure should say so rather than reach into another module's underscore names.

The implementations are `cli`'s, unchanged in behaviour apart from the wildcard fix recorded
in `port_in_use`.
"""
from __future__ import annotations

import socket
import subprocess


def port_in_use(port: int) -> bool:
    """True when something already LISTENS on the port.

    The bind is attempted the way the SERVER attempts it, with ``SO_REUSEADDR`` (uvicorn sets
    it, as does anything restartable). Without that flag the probe was stricter than the
    process it protects and refused a port in TIME_WAIT, where nothing is listening at all —
    so `./start.sh --stop && ./start.sh` reported "already in use" and quit.

    🔴 The bind alone is NOT enough. The claim that once ended this docstring —
    "``SO_REUSEADDR`` does not let this bind over an active listener on BSD/macOS" — holds
    only for the SAME address. A server on the WILDCARD (``0.0.0.0:8000``, exactly how the
    deployment runbook starts this API) does not stop a bind of the specific
    ``127.0.0.1:8000``. Measured 2026-09-20 on a live machine: `lsof` named listeners on
    ``*:8000`` and ``*:3000`` and this function answered "free" for both, so `aughor up`'s
    guard had never fired there.

    So the bind is joined by a CONNECT. A live listener accepts wherever it is bound; a port
    in TIME_WAIT has no listener and refuses, which is the case ``SO_REUSEADDR`` exists to
    forgive. "Busy" still means a live listener — now including a wildcard one.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return True
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.25)
        try:
            probe.connect(("127.0.0.1", port))
        except OSError:
            return False
        return True


def port_owner(port: int) -> str:
    """Best-effort ``'command (pid N)'`` for the port's listener via lsof.

    Empty when lsof is unavailable or the owner cannot be determined — which is POSIX-only in
    practice, so an empty answer means "not known", never "nobody". A caller that turns it
    into a failure is reporting a missing tool as a broken port.
    """
    try:
        out = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"],
            capture_output=True, text=True, timeout=3,
        ).stdout.splitlines()
    except (OSError, subprocess.SubprocessError):
        return ""
    for line in out[1:]:
        parts = line.split()
        if len(parts) >= 2:
            return f"{parts[0]} (pid {parts[1]})"
    return ""
