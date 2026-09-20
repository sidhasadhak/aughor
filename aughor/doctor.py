"""IN-1 — `aughor doctor`: what is wrong with this install, and what to do about it.

Every check answers with a **typed verdict**, never a bare boolean and never `X or {}`: "I
could not tell" and "it is fine" are different answers, and collapsing them is how a check
starts reading as a pass. Each `Check` carries what was WANTED, what was FOUND, a reason when
it is not ok, and the FIX — the shape `cli._print_boot_summary` already uses for the model
verdict, lifted rather than reinvented.

**Two rules this module will not break.**

*No model call, no warehouse query.* "Is a model configured" is answered from
`llm_config.json` and the environment only. The obvious route —
`routers/system.py::_llm_readiness` → `provider.resolve_binding` → `org_config._conn()` —
issues `CREATE TABLE …; commit` against `data/org_llm.db`, so a doctor built that way becomes
a SECOND WRITER on `data/` while the API serves. That is the exact shape behind four
`system.db` corruptions, and a diagnostic that can corrupt the thing it is diagnosing is worse
than no diagnostic.

*It only reads.* Nothing here creates a directory, a file or a table. Writability is tested by
asking the filesystem, not by writing a probe file into a store directory.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

#: A check that cannot answer says so. `unknown` is not `fail` — a missing `lsof` is not a
#: broken port, and reporting it as one sends a person to fix something that is fine.
OK, FAIL, WARN, UNKNOWN = "ok", "fail", "warn", "unknown"


@dataclass
class Check:
    name: str
    status: str
    found: str = ""
    wanted: str = ""
    reason: str = ""
    fix: str = ""

    @property
    def ok(self) -> bool:
        return self.status == OK


def _uv() -> Check:
    from aughor.installer import find_uv
    exe = find_uv()
    if not exe:
        return Check("uv", FAIL, found="not found", wanted="uv on PATH",
                     reason="the launcher, the virtualenv and the Python install all go through uv",
                     fix="curl -LsSf https://astral.sh/uv/install.sh | sh")
    return Check("uv", OK, found=str(exe), wanted="uv on PATH")


def _python() -> Check:
    from aughor.installer import PYTHON_VERSION
    running = ".".join(str(p) for p in sys.version_info[:3])
    wanted = f"{PYTHON_VERSION}.x"
    if sys.version_info[:2] != tuple(int(p) for p in PYTHON_VERSION.split(".")[:2]):
        return Check("python", WARN, found=running, wanted=wanted,
                     reason="this interpreter is not the version the install pins",
                     fix=f"uv python install {PYTHON_VERSION}")
    return Check("python", OK, found=running, wanted=wanted)


def _node(repo: Path) -> Check:
    from aughor.installer import NODE_MIN, find_node
    node, too_old = find_node(repo)
    wanted = ">= " + ".".join(str(p) for p in NODE_MIN)
    if node is None:
        found = ("none new enough (newest " + ".".join(str(p) for p in too_old) + ")"
                 if too_old else "not found")
        return Check("node", FAIL, found=found, wanted=wanted,
                     reason="the web app is built with Node",
                     fix="./install.sh  (it downloads a private Node into .aughor/node/)")
    version = ".".join(str(p) for p in (node.version or ()))
    return Check("node", OK, found=f"{node.exe} ({version})" if version else str(node.exe),
                 wanted=wanted)


def _port(label: str, port: int, flag: str) -> Check:
    from aughor.netprobe import port_in_use, port_owner
    if not port_in_use(port):
        return Check(label, OK, found="free", wanted="free, or held by Aughor")
    owner = port_owner(port)
    if not owner:
        # `port_owner` shells out to `lsof`, which is POSIX-only. No answer is not "nobody".
        return Check(label, UNKNOWN, found="in use, owner unknown", wanted="free, or held by Aughor",
                     reason="something is listening; lsof did not say what",
                     fix=f"find it yourself: lsof -nP -iTCP:{port} -sTCP:LISTEN")
    return Check(label, WARN, found=f"in use by {owner}", wanted="free, or held by Aughor",
                 reason="a restart will refuse rather than take a port from its owner",
                 fix=f"stop it, or run on another port (aughor up {flag} <n>)")


def _state_writable() -> Check:
    from aughor.db import home
    from aughor.db.paths import state_dir
    where = state_dir()
    label = "state dir" + (" (home)" if home.in_use() else "")
    if not where.exists():
        return Check(label, WARN, found=f"{where} does not exist yet", wanted="a writable directory",
                     reason="it is created on first write; nothing is wrong yet",
                     fix="start the app once")
    if not os.access(where, os.W_OK):
        return Check(label, FAIL, found=f"{where} is not writable", wanted="a writable directory",
                     reason="every store writes here",
                     fix="fix its permissions, or set AUGHOR_STATE_DIR to somewhere writable")
    return Check(label, OK, found=str(where), wanted="a writable directory")


def _launcher() -> Check:
    from aughor.installer import LAUNCHER_MARK, find_uv, launcher_dir
    on_path = shutil.which("aughor")
    if on_path:
        return Check("aughor on PATH", OK, found=on_path, wanted="the aughor command on PATH")
    uv = find_uv()
    target = launcher_dir(uv) if uv else None
    return Check("aughor on PATH", WARN, found="not on PATH",
                 wanted="the aughor command on PATH",
                 reason=f"the installer writes it into {target} ({LAUNCHER_MARK})"
                        if target else "uv's command directory could not be located",
                 fix="./install.sh  (it writes the launcher; no shell rc file is edited)")


def _model() -> Check:
    """Answered from the config FILE and the environment. Never through `provider`, which
    would open `org_llm.db` and make this a second writer on a live deployment."""
    from aughor.llm.provider import config_path

    cfg = config_path()
    backend = ""
    source = ""
    try:
        if cfg.is_file():
            raw = json.loads(cfg.read_text(encoding="utf-8") or "{}")
            backend = str(raw.get("backend") or "").strip()
            source = str(cfg)
    except (OSError, ValueError) as exc:
        return Check("model", UNKNOWN, found=f"{cfg} could not be read ({exc})",
                     wanted="a backend chosen in Settings, or AUGHOR_BACKEND",
                     fix="open Settings → Models, or set AUGHOR_BACKEND")
    if not backend:
        backend = os.getenv("AUGHOR_BACKEND", "").strip()
        source = "AUGHOR_BACKEND" if backend else ""
    if not backend:
        return Check("model", FAIL, found="no backend chosen",
                     wanted="a backend chosen in Settings, or AUGHOR_BACKEND",
                     reason="every answer needs one",
                     fix="open Settings → Models, or set AUGHOR_BACKEND")
    return Check("model", OK, found=f"{backend} (from {source})",
                 wanted="a backend chosen in Settings, or AUGHOR_BACKEND")


def run(repo: Path, *, api_port: int, web_port: int) -> list[Check]:
    """Every check, in the order a person reads them. Pure: nothing here writes."""
    return [
        _uv(),
        _python(),
        _node(repo),
        _port(f"port {api_port} (api)", api_port, "--api-port"),
        _port(f"port {web_port} (web)", web_port, "--web-port"),
        _state_writable(),
        _launcher(),
        _model(),
    ]


def worst(checks: list[Check]) -> str:
    """The verdict for the whole run — the exit code comes from this."""
    for status in (FAIL, WARN, UNKNOWN):
        if any(c.status == status for c in checks):
            return status
    return OK
