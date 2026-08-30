"""VA-11 — persistence for provider apps, user grants, and in-flight authorizations.

``LedgerListStore`` on files of their own, the same choice ``slackbots/store.py``
made and for the same two reasons: the records must be visible across serverless
instances (the callback may land on a different instance than the one that began
the flow), and a file store means **no migration** — which keeps this wave clear of
the numbering trap entirely.

⚠️ ``AUGHOR_INTEGRATIONS_DIR`` is a NEW hermeticity boundary and is added to
``tests/conftest.py``'s redirect loop **in the same commit as this file** — the rule
this repo bought with a store that wrote to live ``data/``.

Pending authorizations live in the store rather than in memory for the serverless
reason above, and each is SINGLE-USE: ``take_pending`` pops. A state value that can
complete twice is a token mint.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from aughor.db.sqlite_util import resolve_db_path
from aughor.integrations.models import (
    Connection,
    ProviderApp,
    decrypt_app,
    decrypt_connection,
    encrypt_app,
    encrypt_connection,
)
from aughor.util.json_store import LedgerListStore
from aughor.util.time import now_iso_z

_DIR = resolve_db_path("AUGHOR_INTEGRATIONS_DIR", Path("data"))
_APPS = LedgerListStore(_DIR / "integration_apps.json")
_CONNS = LedgerListStore(_DIR / "integration_connections.json")
_PENDING = LedgerListStore(_DIR / "integration_pending.json")

#: An authorization the user has not completed in this window is abandoned. Ten
#: minutes is generous for a consent screen and short enough that a leaked state
#: value is worthless by the time anyone could replay it.
PENDING_TTL_SECONDS = 600


# ── provider apps ────────────────────────────────────────────────────────────────

def save_app(app: ProviderApp) -> ProviderApp:
    app = app.model_copy(update={"updated_at": now_iso_z()})
    _APPS.upsert(encrypt_app(app).model_dump())
    return app


def get_app(provider_id: str) -> Optional[ProviderApp]:
    d = _APPS.get(provider_id)
    return ProviderApp(**d) if d else None


def get_app_decrypted(provider_id: str) -> Optional[ProviderApp]:
    app = get_app(provider_id)
    return decrypt_app(app) if app else None


# ── user connections ─────────────────────────────────────────────────────────────

def save_connection(conn: Connection) -> Connection:
    conn = conn.model_copy(update={"updated_at": now_iso_z()})
    _CONNS.upsert(encrypt_connection(conn).model_dump())
    return conn


def get_connection(conn_id: str) -> Optional[Connection]:
    d = _CONNS.get(conn_id)
    return Connection(**d) if d else None


def get_connection_decrypted(conn_id: str) -> Optional[Connection]:
    conn = get_connection(conn_id)
    return decrypt_connection(conn) if conn else None


def list_connections(user_id: str = "") -> list[Connection]:
    """The USER's grants, tokens still encrypted. Filtered here rather than by the
    caller, so a route cannot forget and list the whole org's."""
    return [Connection(**d) for d in _CONNS.all() if d.get("user_id", "") == user_id]


# ── pending authorizations (state → flow context) ────────────────────────────────

def put_pending(state: str, *, provider: str, user_id: str, verifier: str,
                redirect_uri: str) -> None:
    # `redirect_uri` rides WITH the flow: the token exchange must present the value
    # byte-identical to the authorize request's, and re-deriving it at callback time
    # from proxy headers is a second derivation that can disagree with the first.
    _PENDING.upsert({"id": state, "provider": provider, "user_id": user_id,
                     "verifier": verifier, "redirect_uri": redirect_uri,
                     "at": time.time()})


def take_pending(state: str) -> Optional[dict]:
    """Pop the pending flow for ``state`` — SINGLE USE, expiry enforced here.

    Expiry is checked inside the take, not by a sweeper: a sweeper that has not run
    yet is an expiry that has not happened, and this is the one place staleness has
    a consequence.
    """
    d = _PENDING.get(state)
    if not d:
        return None
    _PENDING.delete(state)
    if time.time() - float(d.get("at", 0)) > PENDING_TTL_SECONDS:
        return None
    return d
