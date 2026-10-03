"""The API owns the Slack supervisor process (Arc AO-2b, flag ``slack.managed_supervisor``).

Measured 2026-10-03: nothing started the supervisor (``start.sh`` does not), nothing
watched it, and the bot card read "enabled" on a machine where it was not running. Behind
the flag the API spawns it, watches it, and restarts it with a backoff; the status route
and the bot card say which of those is true right now.

**The spike (§6 item 38(d)) — spawn-and-watch, not in-process Socket Mode.** Decided by
reading, not by a day: the bot's whole answer path is TypeScript — the Chat SDK's
streaming, the chart PNG via resvg, the thread grammar (``bots/slack/src``). An
in-process Python Socket Mode client would be a second implementation of all of it,
drifting from the first. Spawning the one implementation keeps one bot; watching it is
what the flag adds.

Off by default and byte-identical when off: ``start()`` returns ``"off"`` and spawns
nothing. The child gets its own key (a second row in the key store, never the operator's)
so a managed supervisor cannot be darkened by a person's "Regenerate".
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

FLAG = "slack.managed_supervisor"

#: Restart backoff, seconds, by consecutive failure; the last value repeats.
BACKOFF_S = (5, 15, 60, 180)
#: After this many exits inside an hour the host stops restarting and says so — a child
#: that dies every minute is a configuration fault, not a transient.
MAX_RESTARTS_PER_HOUR = 10
_WATCH_S = 5


def supervisor_dir(root: Optional[Path] = None) -> Path:
    base = root or Path(__file__).resolve().parents[2]
    return base / "bots" / "slack"


@dataclass
class Status:
    flag: bool = False
    managed: bool = False
    state: str = "off"          # off · starting · running · restarting · stopped · failed
    pid: Optional[int] = None
    started_at: str = ""
    restarts: int = 0
    last_exit_code: Optional[int] = None
    last_error: str = ""
    command: list[str] = field(default_factory=list)
    cwd: str = ""
    #: What would stop a start before it is tried — said, so the fix is named.
    preconditions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class ManagedSupervisor:
    """One child process, one watcher thread. ``spawn`` is injectable for tests."""

    def __init__(self, *, api_url: str, runtime_key: str, cwd: Optional[Path] = None,
                 spawn=None, flag_enabled=None):
        self._api_url = api_url
        self._runtime_key = runtime_key
        self._cwd = cwd or supervisor_dir()
        self._spawn = spawn or self._real_spawn
        self._flag_enabled = flag_enabled or _flag_on
        self._proc: Any = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._exits: list[float] = []
        self._status = Status()

    # ── preconditions ────────────────────────────────────────────────────────────
    def preconditions(self) -> list[str]:
        problems: list[str] = []
        if not (self._cwd / "package.json").is_file():
            problems.append(f"no supervisor at {self._cwd} — the repo's bots/slack is missing")
        if not (self._cwd / "node_modules").is_dir():
            problems.append("bots/slack/node_modules is missing — run `npm install` in "
                            "bots/slack (the installer does this when the flag is on)")
        if not self._npx():
            problems.append("no `npx` on PATH — install Node.js 20+")
        if not self._runtime_key:
            problems.append("no managed runtime key could be issued")
        return problems

    @staticmethod
    def _npx() -> str:
        return shutil.which("npx") or ""

    def command(self) -> list[str]:
        return [self._npx() or "npx", "tsx", "src/index.ts"]

    def env(self) -> dict[str, str]:
        env = dict(os.environ)
        env.update({
            "AUGHOR_API_URL": self._api_url,
            "AUGHOR_RUNTIME_KEY": self._runtime_key,
            "AUGHOR_MANAGED_BY_API": "1",
        })
        # The managed child reads the registry, never a .env.local bot.
        for k in ("SLACK_BOT_TOKEN", "SLACK_APP_TOKEN", "SLACK_SIGNING_SECRET"):
            env.pop(k, None)
        return env

    def _real_spawn(self, cmd: list[str], cwd: Path, env: dict[str, str]):
        return subprocess.Popen(cmd, cwd=str(cwd), env=env,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # ── lifecycle ────────────────────────────────────────────────────────────────
    def start(self) -> str:
        """Start the child and the watcher. Returns the resulting state."""
        with self._lock:
            self._status.flag = bool(self._flag_enabled(FLAG))
            if not self._status.flag:
                self._status.state = "off"
                return "off"
            self._status.managed = True
            self._status.preconditions = self.preconditions()
            self._status.command = self.command()
            self._status.cwd = str(self._cwd)
            if self._status.preconditions:
                self._status.state = "failed"
                self._status.last_error = "; ".join(self._status.preconditions)
                return "failed"
            self._launch()
            if self._thread is None:
                self._stop.clear()
                self._thread = threading.Thread(target=self._watch, name="slack-supervisor-host",
                                                daemon=True)
                self._thread.start()
            return self._status.state

    def _launch(self) -> None:
        try:
            self._proc = self._spawn(self.command(), self._cwd, self.env())
        except Exception as exc:                        # noqa: BLE001 — said on the status
            self._status.state = "failed"
            self._status.last_error = f"could not start: {exc}"
            self._proc = None
            return
        self._status.state = "running"
        self._status.pid = getattr(self._proc, "pid", None)
        self._status.started_at = _now_iso()
        self._status.last_error = ""

    def _watch(self) -> None:
        failures = 0
        while not self._stop.is_set():
            time.sleep(_WATCH_S)
            with self._lock:
                proc = self._proc
                if proc is None:
                    continue
                code = proc.poll()
                if code is None:
                    continue
                now = time.time()
                self._exits = [t for t in self._exits if now - t < 3600] + [now]
                self._status.last_exit_code = code
                self._status.pid = None
                if len(self._exits) > MAX_RESTARTS_PER_HOUR:
                    self._status.state = "stopped"
                    self._status.last_error = (
                        f"exited {len(self._exits)} times in an hour (last code {code}); "
                        "not restarting — check the supervisor's own log and the bot card")
                    self._proc = None
                    continue
                failures += 1
                wait = BACKOFF_S[min(failures, len(BACKOFF_S)) - 1]
                self._status.state = "restarting"
                self._status.last_error = f"exited with code {code}; restarting in {wait}s"
                self._status.restarts += 1
            if self._stop.wait(wait):
                return
            with self._lock:
                self._launch()
                if self._status.state == "running":
                    failures = 0

    def restart(self) -> Status:
        """A person asked: stop the child (if any) and start it again now."""
        with self._lock:
            self._terminate()
            self._exits = []
            self._status.restarts += 1
            if self._status.flag:
                self._status.preconditions = self.preconditions()
                if self._status.preconditions:
                    self._status.state = "failed"
                    self._status.last_error = "; ".join(self._status.preconditions)
                else:
                    self._launch()
            return self.status()

    def _terminate(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None or proc.poll() is not None:
            return
        try:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:                            # noqa: BLE001
                proc.kill()
        except Exception as exc:                         # noqa: BLE001
            logger.warning("managed supervisor: terminate failed: %s", exc)

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            self._terminate()
            if self._status.managed:
                self._status.state = "stopped"
                self._status.pid = None

    def status(self) -> Status:
        s = Status(**self._status.to_dict())
        if self._proc is not None and self._proc.poll() is None:
            s.state = "running"
            s.pid = getattr(self._proc, "pid", None)
        return s


def _flag_on(name: str) -> bool:
    from aughor.kernel.flags import flag_enabled
    return flag_enabled(name)


_HOST: Optional[ManagedSupervisor] = None


def host() -> Optional[ManagedSupervisor]:
    return _HOST


def start_managed_supervisor(*, api_url: str) -> Status:
    """Called by the API's lifespan. With the flag off this issues nothing, spawns nothing
    and returns ``state="off"`` — the byte-identical path."""
    global _HOST
    from aughor.kernel.flags import flag_enabled
    if not flag_enabled(FLAG):
        return Status()
    from aughor.slackbots import store
    key = store.issue_managed_key()
    _HOST = ManagedSupervisor(api_url=api_url, runtime_key=key)
    _HOST.start()
    return _HOST.status()


def stop_managed_supervisor() -> None:
    global _HOST
    if _HOST is not None:
        _HOST.stop()
        _HOST = None


def managed_status() -> dict[str, Any]:
    if _HOST is None:
        s = Status(flag=_flag_on(FLAG))
        if s.flag:
            s.state = "stopped"
            s.last_error = "the flag is on but the host was not started — restart the API"
        return s.to_dict()
    return _HOST.status().to_dict()
