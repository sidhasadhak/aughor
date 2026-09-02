"""VA-9d — the allowlist, the roster discovered against it, and the grants over that.

Three kinds of row, and the distinction between them is the security model: a SERVER is
what a human wrote down, a ROSTER is what their machine said last Tuesday, and a GRANT is
what a human said about one line of that roster. Only the middle one is somebody else's
state, which is why only the middle one is replaced wholesale on every discovery.

``LedgerListStore`` on files of their own, the choice `integrations/store.py` and
`slackbots/store.py` both made, for both of their reasons: the rows must be visible across
serverless instances, and a file store means **no migration** — which keeps this wave clear
of the numbering trap (`PRAGMA user_version` has to be read off the LIVE db and no hermetic
test can catch a wrong number).

⚠️ ``AUGHOR_MCPSERVERS_DIR`` is a NEW hermeticity boundary. It is added to
``tests/conftest.py``'s redirect loop AND to ``scripts/dump_openapi.py``'s isolation
**in the same commit as this file** — two lists, not one: the conftest rule was bought by a
store that wrote to live ``data/``, and the dump_openapi half was found in DS-17, where the
directory family had no pin there at all.

**The roster is stored beside the server, not inside it.** A server row is what a human
wrote down; a roster is what their machine said last Tuesday. Keeping them in one record
would make a re-discovery rewrite the human's intent, and would make "when did we last
look?" a property of the allowlist entry rather than of the answer.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from aughor.db.sqlite_util import resolve_db_path
from aughor.mcpservers.models import (
    GRANT_STALE, SERVER_SECRET_FIELDS, McpServer, McpTool, McpToolGrant, grant_key,
    grant_verdict,
)
from aughor.secretvault import decrypt_secret, encrypt_secret
from aughor.util.json_store import LedgerListStore
from aughor.util.time import now_iso_z

logger = logging.getLogger(__name__)

_DIR = resolve_db_path("AUGHOR_MCPSERVERS_DIR", Path("data"))
_SERVERS = LedgerListStore(_DIR / "mcp_servers.json")
#: One row per SERVER holding its whole roster, keyed by server id — not one row per tool.
#: A discovery replaces a server's roster wholesale, and a tool the server stopped offering
#: must disappear rather than linger; per-tool rows would need a reconciliation pass whose
#: only job is to delete, and the bug in that pass is a tool that outlives its server.
_ROSTERS = LedgerListStore(_DIR / "mcp_tool_rosters.json")
#: One row per GRANTED TOOL — the opposite shape to the roster above, and deliberately.
#: A roster is somebody else's state, replaced wholesale every discovery; a grant is OUR
#: record of a human decision and must survive a re-discovery that did not change the
#: declaration it pinned. Rows keyed `<server id>::<tool name>` so a grant is addressable
#: without loading a server's whole set.
_GRANTS = LedgerListStore(_DIR / "mcp_tool_grants.json")


# ── the allowlist ────────────────────────────────────────────────────────────────

def list_servers(*, include_disabled: bool = True) -> list[McpServer]:
    """Every allowlisted server, secrets still encrypted.

    An EMPTY list is the off state and the common one: a fresh clone reaches nothing
    because there is nowhere to go.
    """
    out = [_decrypt(McpServer(**d)) for d in _SERVERS.all()]
    return out if include_disabled else [s for s in out if s.enabled]


def get_server(server_id: str) -> Optional[McpServer]:
    row = _SERVERS.get(str(server_id))
    return _decrypt(McpServer(**row)) if row else None


def save_server(server: McpServer) -> McpServer:
    server.updated_at = now_iso_z()
    _SERVERS.upsert(_encrypt(server).model_dump())
    return server


def delete_server(server_id: str) -> bool:
    """Forget a server AND its roster. The roster is the server's property, so leaving it
    behind would keep a palette row alive for a destination nobody can reach — DS-17 paid
    for the same lesson with a webhook token that outlived its automation."""
    existed = bool(_SERVERS.delete(str(server_id)))
    _ROSTERS.delete(str(server_id))
    for g in grants_for_server(server_id):
        _GRANTS.delete(g.key)
    return existed


# ── the discovered roster ────────────────────────────────────────────────────────

def save_roster(server_id: str, tools: list[McpTool]) -> None:
    """Replace this server's roster wholesale. A tool it no longer offers is GONE."""
    _ROSTERS.upsert({
        "id": str(server_id),
        "discovered_at": now_iso_z(),
        "tools": [t.model_dump() for t in tools],
    })


def get_roster(server_id: str) -> tuple[list[McpTool], str]:
    """This server's tools and when they were read — ``([], "")`` if never discovered.

    The timestamp is returned with the list rather than left for a caller to find, because
    every surface that renders this roster has to say how old it is. A cached remote list
    presented as if it were live is the failure this pair exists to prevent.
    """
    row = _ROSTERS.get(str(server_id))
    if not row:
        return [], ""
    tools = [McpTool(**t) for t in (row.get("tools") or [])]
    return tools, str(row.get("discovered_at", ""))


def all_rosters() -> dict[str, list[McpTool]]:
    """Every server's tools, keyed by server id — one read for the component registry,
    which would otherwise do one store round trip per allowlisted server per render."""
    out: dict[str, list[McpTool]] = {}
    for row in _ROSTERS.all():
        out[str(row.get("id"))] = [McpTool(**t) for t in (row.get("tools") or [])]
    return out


# ── grants: the human's ratification of a mutating tool ──────────────────────────

def get_grant(server_id: str, tool_name: str) -> Optional[McpToolGrant]:
    row = _GRANTS.get(grant_key(server_id, tool_name))
    return McpToolGrant(**{k: v for k, v in row.items() if k != "id"}) if row else None


def list_grants() -> list[McpToolGrant]:
    """Every grant on this deployment. An EMPTY list is the normal state — the same off
    state the allowlist has, one plane in: a deployment that has written servers down still
    calls nothing that mutates until somebody ratifies a specific tool."""
    return [McpToolGrant(**{k: v for k, v in r.items() if k != "id"}) for r in _GRANTS.all()]


def grants_for_server(server_id: str) -> list[McpToolGrant]:
    return [g for g in list_grants() if g.server_id == str(server_id)]


def save_grant(grant: McpToolGrant) -> McpToolGrant:
    """Record a ratification, and say so in the ledger.

    Audited here rather than at the route because the route is not the only caller this
    will ever have, and an audit line that depends on which entry point was used is one
    somebody will lose — `discover()` paid for that lesson with a trace binding.
    """
    _GRANTS.upsert({"id": grant.key, **grant.model_dump()})
    _audit("mcp.tool.granted", grant, {
        "read_only_hint": grant.read_only_hint,
        "destructive_hint": grant.destructive_hint,
        "note": grant.note})
    return grant


def delete_grant(server_id: str, tool_name: str, *, reason: str = "revoked") -> bool:
    """Withdraw a ratification. Returns whether one was there to withdraw."""
    grant = get_grant(server_id, tool_name)
    if grant is None:
        return False
    _GRANTS.delete(grant.key)
    _audit("mcp.tool.grant_revoked", grant, {"reason": reason})
    return True


def revoke_stale_grants(server_id: str, tools: list[McpTool]) -> list[McpToolGrant]:
    """Drop every grant this server's new roster no longer matches. Returns what was dropped.

    Run at DISCOVERY so the surfaces tell the truth the moment a declaration moves, rather
    than at the next call — a roster that still renders "granted" for a tool the door would
    refuse is the catalogue-that-lies failure in miniature. The door checks again anyway
    (`grant_verdict` there, on the same rows): this is the eager half, and the door is the
    load-bearing one, because a grant must never be honoured against a declaration nobody
    read even if this pass did not run.

    A grant for a tool the server STOPPED offering is dropped too. It cannot be evaluated —
    there is no declaration to compare against — and a permission that outlives the thing it
    permits is how a re-added tool inherits a yes nobody gave it.
    """
    by_name = {t.name: t for t in tools}
    dropped: list[McpToolGrant] = []
    for grant in grants_for_server(server_id):
        tool = by_name.get(grant.tool_name)
        if tool is None:
            _GRANTS.delete(grant.key)
            _audit("mcp.tool.grant_revoked", grant, {"reason": "tool no longer offered"})
            dropped.append(grant)
            continue
        state, _ = grant_verdict(tool, grant)
        if state == GRANT_STALE:
            _GRANTS.delete(grant.key)
            _audit("mcp.tool.grant_revoked", grant, {
                "reason": "declaration changed since the grant",
                "was": {"read_only_hint": grant.read_only_hint,
                        "destructive_hint": grant.destructive_hint},
                "now": {"read_only_hint": tool.read_only_hint,
                        "destructive_hint": tool.destructive_hint}})
            dropped.append(grant)
    return dropped


def _audit(kind: str, grant: McpToolGrant, extra: dict) -> None:
    """Grants are governance changes, so they go where governance changes go. Best-effort:
    a ledger that is unavailable must not stop a human withdrawing a permission."""
    try:
        from aughor.kernel.ledger import Ledger
        Ledger.default().emit(kind, {
            "server_id": grant.server_id, "tool": grant.tool_name,
            "granted_by": grant.granted_by, **extra})
    except Exception:                                        # pragma: no cover - best effort
        logger.debug("mcp grant audit emit failed", exc_info=True)


# ── field-level encryption, the `integrations` shape ─────────────────────────────

def _encrypt(server: McpServer) -> McpServer:
    return server.model_copy(update={
        f: encrypt_secret(getattr(server, f) or "") or "" for f in SERVER_SECRET_FIELDS})


def _decrypt(server: McpServer) -> McpServer:
    return server.model_copy(update={
        f: decrypt_secret(getattr(server, f) or "") or "" for f in SERVER_SECRET_FIELDS})
