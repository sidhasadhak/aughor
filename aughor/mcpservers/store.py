"""VA-9d — the allowlist, and the tool roster discovered against it.

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

from pathlib import Path
from typing import Optional

from aughor.db.sqlite_util import resolve_db_path
from aughor.mcpservers.models import SERVER_SECRET_FIELDS, McpServer, McpTool
from aughor.secretvault import decrypt_secret, encrypt_secret
from aughor.util.json_store import LedgerListStore
from aughor.util.time import now_iso_z

_DIR = resolve_db_path("AUGHOR_MCPSERVERS_DIR", Path("data"))
_SERVERS = LedgerListStore(_DIR / "mcp_servers.json")
#: One row per SERVER holding its whole roster, keyed by server id — not one row per tool.
#: A discovery replaces a server's roster wholesale, and a tool the server stopped offering
#: must disappear rather than linger; per-tool rows would need a reconciliation pass whose
#: only job is to delete, and the bug in that pass is a tool that outlives its server.
_ROSTERS = LedgerListStore(_DIR / "mcp_tool_rosters.json")


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


# ── field-level encryption, the `integrations` shape ─────────────────────────────

def _encrypt(server: McpServer) -> McpServer:
    return server.model_copy(update={
        f: encrypt_secret(getattr(server, f) or "") or "" for f in SERVER_SECRET_FIELDS})


def _decrypt(server: McpServer) -> McpServer:
    return server.model_copy(update={
        f: decrypt_secret(getattr(server, f) or "") or "" for f in SERVER_SECRET_FIELDS})
