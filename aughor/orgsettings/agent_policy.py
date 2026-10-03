"""DE-2b (ROADMAP §3.51; §6 item 37(c)) — one agent policy per organisation.

An outside agent — the MCP client, and whatever drives it — acts under ONE policy its
organisation set, kept with the organisation's other per-org setting (the LLM binding's
SQLite store, `AUGHOR_ORG_LLM_DB`; not a new store):

* ``level`` — ``read`` looks things up; ``run`` also starts explorations and analyses, which
  spend model calls, and cancels nothing; ``act`` also takes the tools that change something
  (an automation run, a job cancel, Spotlight's staged acts).
* ``connections`` — an allowlist of connection ids, or None for every connection;
* ``tools`` — an allowlist of tool names, or None for every tool the level allows.

An install with no saved policy runs at ``run`` — today's exposure, made explicit — and
``act`` is given only by a person (the route refuses an agent setting its own policy). The
ENVIRONMENT can only narrow what is saved (`AUGHOR_AGENT_POLICY_LEVEL`,
`AUGHOR_AGENT_POLICY_CONNECTIONS`, `AUGHOR_AGENT_POLICY_TOOLS`), never widen it: an operator
can pin a deployment below what its organisations allow, not above. The policy is read on
every call, so a change takes effect on the next one.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from aughor.db.backend import connect_store
from aughor.db.sqlite_util import resolve_db_path
from aughor.db.store_pool import ensure_once

LEVELS: tuple[str, ...] = ("read", "run", "act")

# The same store as the organisation's LLM binding — the one per-org setting this install
# already keeps — so the two per-org facts live in one place.
_DB_PATH = resolve_db_path(
    "AUGHOR_ORG_LLM_DB", Path(__file__).parent.parent.parent / "data" / "org_llm.db")


def _conn():
    c = connect_store(_DB_PATH)
    ensure_once(c, _ensure_schema)
    return c


def _ensure_schema(c) -> None:
    c.execute(
        """CREATE TABLE IF NOT EXISTS org_agent_policy (
               org_id      TEXT PRIMARY KEY,
               level       TEXT NOT NULL DEFAULT 'run',
               connections TEXT,
               tools       TEXT,
               set_by      TEXT NOT NULL DEFAULT '',
               updated_at  TEXT NOT NULL DEFAULT ''
           )"""
    )
    c.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def rank(level: str) -> int:
    try:
        return LEVELS.index(level)
    except ValueError:
        raise ValueError(f"unknown agent policy level {level!r} — one of {', '.join(LEVELS)}") from None


@dataclass(frozen=True)
class AgentPolicy:
    level: str = "run"
    connections: Optional[tuple[str, ...]] = None     # None = every connection
    tools: Optional[tuple[str, ...]] = None           # None = every tool the level allows
    set_by: str = ""                                  # "" = nobody: the install's default
    updated_at: str = ""
    #: default — nothing saved; saved — the organisation's; narrowed — the environment cut it.
    source: str = "default"
    narrowed_by: tuple[str, ...] = ()

    def allows_level(self, needed: str) -> bool:
        return rank(self.level) >= rank(needed)

    def allows_tool(self, name: str) -> bool:
        return self.tools is None or name in self.tools

    def allows_connection(self, connection_id: Optional[str]) -> bool:
        return not connection_id or self.connections is None or connection_id in self.connections

    def as_dict(self) -> dict:
        return {"level": self.level,
                "connections": list(self.connections) if self.connections is not None else None,
                "tools": list(self.tools) if self.tools is not None else None,
                "set_by": self.set_by, "updated_at": self.updated_at,
                "source": self.source, "narrowed_by": list(self.narrowed_by)}


DEFAULT_POLICY = AgentPolicy()


def _row(org_id: str) -> Optional[dict]:
    with _conn() as c:
        r = c.execute("SELECT level, connections, tools, set_by, updated_at FROM org_agent_policy WHERE org_id = ?",
                      (org_id,)).fetchone()
    if not r:
        return None
    return {"level": r[0], "connections": r[1], "tools": r[2], "set_by": r[3], "updated_at": r[4]}


def _tuple_or_none(raw: Optional[str]) -> Optional[tuple[str, ...]]:
    if raw is None or raw == "":
        return None
    try:
        vals = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return tuple(str(v) for v in vals) if isinstance(vals, list) else None


def load_agent_policy(org_id: str) -> AgentPolicy:
    """The organisation's SAVED policy, or the default when none is saved."""
    row = _row(org_id)
    if row is None:
        return DEFAULT_POLICY
    return AgentPolicy(level=row["level"] if row["level"] in LEVELS else "run",
                       connections=_tuple_or_none(row["connections"]), tools=_tuple_or_none(row["tools"]),
                       set_by=row["set_by"] or "", updated_at=row["updated_at"] or "", source="saved")


def save_agent_policy(org_id: str, *, level: str, connections: Optional[list[str]] = None,
                      tools: Optional[list[str]] = None, set_by: str) -> AgentPolicy:
    """Save the organisation's policy. ``set_by`` names the person: the route refuses an agent,
    and this refuses an empty name, so `act` is never granted by nobody."""
    rank(level)
    if not (set_by or "").strip():
        raise ValueError("an agent policy is set by a named person")
    conns = sorted({str(c).strip() for c in connections if str(c).strip()}) if connections is not None else None
    tls = sorted({str(t).strip() for t in tools if str(t).strip()}) if tools is not None else None
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO org_agent_policy (org_id, level, connections, tools, set_by, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (org_id, level, json.dumps(conns) if conns is not None else None,
             json.dumps(tls) if tls is not None else None, set_by.strip(), _now()))
        c.commit()
    return load_agent_policy(org_id)


def clear_agent_policy(org_id: str) -> None:
    with _conn() as c:
        c.execute("DELETE FROM org_agent_policy WHERE org_id = ?", (org_id,))
        c.commit()


def _env_list(name: str) -> Optional[tuple[str, ...]]:
    raw = os.environ.get(name, "")
    if not raw.strip():
        return None
    return tuple(sorted({p.strip() for p in raw.split(",") if p.strip()}))


def environment_narrowing() -> dict:
    """What the environment pins, as read right now; the three knobs may each be unset."""
    level = os.environ.get("AUGHOR_AGENT_POLICY_LEVEL", "").strip().lower() or None
    if level is not None and level not in LEVELS:
        level = "read"          # an unreadable cap is the tightest one, not no cap
    return {"level": level,
            "connections": _env_list("AUGHOR_AGENT_POLICY_CONNECTIONS"),
            "tools": _env_list("AUGHOR_AGENT_POLICY_TOOLS")}


def narrow(policy: AgentPolicy, env: Optional[dict] = None) -> AgentPolicy:
    """The policy after the environment's narrowing — never wider than either."""
    env = env if env is not None else environment_narrowing()
    out = policy
    narrowed: list[str] = []
    if env.get("level") is not None and rank(env["level"]) < rank(out.level):
        out = replace(out, level=env["level"])
        narrowed.append("level")
    for key in ("connections", "tools"):
        pinned = env.get(key)
        if pinned is None:
            continue
        have = getattr(out, key)
        merged = tuple(sorted(set(pinned) if have is None else set(pinned) & set(have)))
        if have is None or set(merged) != set(have):
            out = replace(out, **{key: merged})
            narrowed.append(key)
    if narrowed:
        out = replace(out, source="narrowed", narrowed_by=tuple(narrowed))
    return out


def effective_agent_policy(org_id: str) -> AgentPolicy:
    """What applies to an agent's call for this organisation right now: the saved policy (or
    the default), narrowed by the environment. Read every time — nothing is cached, so a
    change takes effect on the next call."""
    return narrow(load_agent_policy(org_id))
