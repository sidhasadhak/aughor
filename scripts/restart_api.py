#!/usr/bin/env python3
"""Restart the API so two of them are never briefly alive on one ``data/``.

Several Claude sessions work this repo at once, and the standing arrangement has
each of them merge-and-restart the operator's API itself. The restart they run is
hand-rolled: kill whatever holds the port, then launch a detached uvicorn. Nothing
serialises those, so two sessions restarting within the same second is a race that
has already been observed — on 2026-09-08 one session's launch took the port a
second after another session's kill freed it, and on 2026-09-06 the serving guard
caught a transient two-process WAL overlap. Every SQLite crash this repo has taken
shares that shape (see ``aughor/db/serving.py``).

This makes the sequence mutually exclusive instead of lucky:

  * an exclusive ``flock`` on the state directory, so a second restarter REFUSES
    rather than interleaving — it does not queue, because a caller blocked behind
    an unknown holder is worse than one that says so and stops;
  * the incumbent is found from ``.serving.pid`` — the process's own claim —
    rather than inferred from the port;
  * shutdown waits for the PROCESS to be gone, never for the port to be free. The
    port is released first, and starting on that signal is exactly how two live
    processes end up sharing a directory;
  * the log is opened for APPEND. ``>`` truncates the previous run's exit
    evidence, which is what made the original race hard to diagnose.

``serving.py`` stays advisory — it warns and never refuses, deliberately. The
refusal lives here, in the one place whose whole job is starting a second server.
"""
from __future__ import annotations

import argparse
import errno
import fcntl
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
LOCK_NAME = ".restart.lock"
DEFAULT_LOG = "/tmp/aughor-api.log"


def _state_dir() -> Path:
    """The directory whose stores we are protecting, by the app's own rule."""
    from aughor.db.paths import state_dir
    return state_dir()


def _is_zombie(pid: int) -> bool:
    """True for an exited-but-unreaped process.

    ``kill(pid, 0)`` succeeds for a zombie — the entry is still in the process
    table — so liveness alone would wait forever on one. A zombie holds no file
    handles and no database, so for our purposes it is gone. macOS has no
    ``/proc``, hence ``ps``.
    """
    try:
        out = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)],
                             capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return False
    return out.stdout.strip().startswith("Z")


def alive(pid: int) -> bool:
    """True while the process is running — signal 0, minus zombies."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True          # someone else's process, but it IS there
    return not _is_zombie(pid)


def port_busy(port: int, host: str = "127.0.0.1") -> bool:
    """True when something accepts connections on the port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.4)
        return s.connect_ex((host, port)) == 0


def wait_gone(pid: int, timeout: float) -> bool:
    """Wait for a process to actually exit. Returns False if it outlives the wait."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not alive(pid):
            return True
        time.sleep(0.2)
    return not alive(pid)


def stop(pid: int, *, grace: float, say) -> bool:
    """SIGTERM, wait for the process to be GONE, escalate to SIGKILL if it is not."""
    say(f"  stopping pid {pid} (SIGTERM)")
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        say("  already gone")
        return True
    if wait_gone(pid, grace):
        say("  exited cleanly")
        return True
    say(f"  still alive after {grace:g}s — SIGKILL")
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return True
    return wait_gone(pid, 10)


def health(port: int, timeout: float, say) -> bool:
    deadline = time.monotonic() + timeout
    url = f"http://127.0.0.1:{port}/health"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as r:
                if r.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(0.5)
    say(f"  no 200 from {url} within {timeout:g}s")
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", type=Path, default=REPO_ROOT,
                    help="checkout whose API to restart; its data/ is the directory "
                         "protected. Defaults to the checkout this script lives in — "
                         "running a worktree's copy targets the WORKTREE's data/, not "
                         "the operator's.")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--log", default=DEFAULT_LOG)
    ap.add_argument("--grace", type=float, default=25.0,
                    help="seconds to wait for a clean exit before SIGKILL")
    ap.add_argument("--health-timeout", type=float, default=60.0)
    ap.add_argument("--stop-only", action="store_true", help="stop the incumbent, start nothing")
    args = ap.parse_args()

    def say(msg: str) -> None:
        print(msg, flush=True)

    repo = args.repo.resolve()
    os.chdir(repo)                   # data/ is cwd-relative; resolve it the way the app does
    sys.path.insert(0, str(repo))
    from aughor.db import serving

    state = _state_dir().resolve()   # absolute, so a mismatch is visible in the output
    state.mkdir(parents=True, exist_ok=True)
    lock_path = state / LOCK_NAME

    lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno not in (errno.EAGAIN, errno.EACCES):
                raise
            os.lseek(lock_fd, 0, os.SEEK_SET)
            holder = os.read(lock_fd, 32).decode(errors="replace").strip()
            say(f"REFUSED — another restart holds {lock_path}"
                + (f" (pid {holder})" if holder else ""))
            say("Nothing was stopped or started. Wait for it to finish, then run again.")
            return 2

        os.ftruncate(lock_fd, 0)
        os.write(lock_fd, str(os.getpid()).encode())
        os.fsync(lock_fd)

        say(f"restart_api — repo {repo}")
        say(f"             state dir {state}")

        incumbent: Optional[int] = serving.serving_pid()
        if incumbent:
            say(f"  incumbent from .serving.pid: {incumbent}")
        elif port_busy(args.port):
            say(f"  nothing claimed {state}, but port {args.port} is busy.")
            say("  REFUSED — starting now would put a second server beside a live one.")
            say("  Either another checkout's API owns that port (check --repo), or a")
            say("  process is serving without claiming its state dir. Stop it yourself.")
            return 3
        else:
            say("  nothing serving")

        if incumbent and not stop(incumbent, grace=args.grace, say=say):
            say(f"  REFUSED — pid {incumbent} would not die; not starting a second server.")
            return 4

        if port_busy(args.port):
            say(f"  REFUSED — port {args.port} still has a listener after the stop.")
            return 5

        if args.stop_only:
            say("  stopped. --stop-only, so nothing was started.")
            return 0

        log = Path(args.log)
        log.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            str(repo / ".venv/bin/uvicorn"), "aughor.api:app",
            "--host", "0.0.0.0", "--port", str(args.port),
            "--timeout-graceful-shutdown", "3",
        ]
        say(f"  starting: {' '.join(cmd)}")
        # APPEND, never truncate — the previous run's exit is the only evidence of
        # why it stopped, and several sessions restart this same API.
        with open(log, "ab") as fh:
            fh.write(f"\n=== restart by pid {os.getpid()} at "
                     f"{time.strftime('%Y-%m-%d %H:%M:%S')} ===\n".encode())
            fh.flush()
            proc = subprocess.Popen(
                cmd, cwd=str(repo), stdout=fh, stderr=subprocess.STDOUT,
                start_new_session=True,     # survives this script exiting
            )

        if not health(args.port, args.health_timeout, say):
            say(f"  started pid {proc.pid} but it never answered; see {log}")
            return 6

        say(f"  up — pid {proc.pid}, logging to {log}")
        return 0
    finally:
        # Releasing on close is what makes a crashed restarter recoverable rather
        # than a permanent lock nobody can explain.
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        finally:
            os.close(lock_fd)


if __name__ == "__main__":
    sys.exit(main())
