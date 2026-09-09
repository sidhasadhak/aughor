"""The restart sequence must be mutually exclusive, not lucky.

Several sessions restart this API, and a hand-rolled kill-then-launch has no
serialisation. Observed 2026-09-08: one session's launch took the port a second
after another's kill freed it. The two properties worth pinning are the ones that
race — the lock, and the fact that a freed PORT is not a dead PROCESS.
"""

import fcntl
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "restart_api.py"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import restart_api  # noqa: E402


class TestProcessLiveness:
    def test_alive_is_true_for_this_process(self):
        assert restart_api.alive(os.getpid()) is True

    def test_alive_is_false_once_a_child_has_exited(self):
        p = subprocess.Popen([sys.executable, "-c", "pass"])
        p.wait()
        # The child is a zombie until reaped; Popen.wait reaped it, so it is gone.
        assert restart_api.alive(p.pid) is False

    def test_wait_gone_returns_false_while_a_process_persists(self):
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            started = time.monotonic()
            assert restart_api.wait_gone(p.pid, 0.6) is False
            assert time.monotonic() - started >= 0.5, "returned early — it did not wait"
        finally:
            p.kill()
            p.wait()

    def test_wait_gone_returns_true_when_the_process_exits(self):
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.3)"])
        assert restart_api.wait_gone(p.pid, 10) is True
        p.wait()

    def test_stop_kills_a_process_that_ignores_sigterm(self):
        # The escalation exists because a graceful uvicorn shutdown has been seen
        # to outlive its own timeout.
        code = "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)"
        p = subprocess.Popen([sys.executable, "-c", code])
        try:
            assert restart_api.stop(p.pid, grace=1.0, say=lambda _m: None) is True
            assert restart_api.alive(p.pid) is False
        finally:
            if p.poll() is None:
                p.kill()
            p.wait()


class TestPortIsNotAProcess:
    def test_port_busy_is_false_on_a_closed_port(self, unused_tcp_port=54329):
        assert restart_api.port_busy(unused_tcp_port) is False

    def test_port_busy_sees_a_listener(self):
        import socket
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        try:
            assert restart_api.port_busy(srv.getsockname()[1]) is True
        finally:
            srv.close()


class TestMutualExclusion:
    def test_a_second_restarter_refuses_rather_than_interleaving(self, tmp_path):
        # Hold the lock the way a mid-flight restart would, then run the script and
        # require it to decline. Anything other than a refusal here is the race.
        state = tmp_path / "data"
        state.mkdir()
        lock_path = state / restart_api.LOCK_NAME
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
        fcntl.flock(fd, fcntl.LOCK_EX)
        os.write(fd, b"424242")
        try:
            proc = subprocess.run(
                [sys.executable, str(SCRIPT), "--port", "54330"],
                env={**os.environ, "AUGHOR_STATE_DIR": str(state),
                     "PYTHONPATH": str(REPO_ROOT)},
                capture_output=True, text=True, timeout=90,
            )
            assert proc.returncode == 2, f"expected refusal, got {proc.returncode}: {proc.stdout}{proc.stderr}"
            assert "REFUSED" in proc.stdout
            assert "424242" in proc.stdout, "the refusal should name the holder"
            assert "Nothing was stopped or started" in proc.stdout
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def test_the_lock_is_released_when_the_holder_goes_away(self, tmp_path):
        # A crashed restarter must not leave a lock nobody can explain or clear.
        state = tmp_path / "data"
        state.mkdir()
        lock_path = state / restart_api.LOCK_NAME
        holder = subprocess.Popen(
            [sys.executable, "-c",
             f"import fcntl,os,time; fd=os.open({str(lock_path)!r}, os.O_RDWR|os.O_CREAT); "
             "fcntl.flock(fd, fcntl.LOCK_EX); time.sleep(30)"],
        )
        try:
            time.sleep(1.0)
            fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
            with pytest.raises(OSError):
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            holder.kill()
            holder.wait()
            time.sleep(0.3)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)   # must not raise
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
        finally:
            if holder.poll() is None:
                holder.kill()
                holder.wait()


class TestRefusalsBeforeStarting:
    def test_it_will_not_start_beside_an_unclaimed_listener(self, tmp_path):
        # No .serving.pid, but something IS on the port: that is precisely the
        # two-writers-on-one-directory case, so refuse rather than add a second.
        import socket
        state = tmp_path / "data"
        state.mkdir()
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        try:
            proc = subprocess.run(
                [sys.executable, str(SCRIPT), "--port", str(port)],
                env={**os.environ, "AUGHOR_STATE_DIR": str(state),
                     "PYTHONPATH": str(REPO_ROOT)},
                capture_output=True, text=True, timeout=90,
            )
            assert proc.returncode == 3, f"{proc.stdout}{proc.stderr}"
            assert "REFUSED" in proc.stdout
            assert "second server beside a live one" in proc.stdout
        finally:
            srv.close()
