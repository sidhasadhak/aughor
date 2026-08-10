"""Postgres connection strings as providers actually hand them out.

psycopg2 parses a ``postgres://`` URI itself, and its parser is stricter than the
strings real providers give you. It rejects a query value containing ``=``
("extra key/value separator") and any parameter it does not recognise
("invalid URI query parameter") — and a Supabase copy-paste DSN can carry both:

    postgresql://…/postgres?sslmode=require&supa=base-pooler.x
    postgresql://…/postgres?options=-c%20search_path%3Dpublic

Either becomes a traceback before a single packet is sent.

`scripts/load_duckdb_to_postgres.py` hit this against a real Supabase DSN and fixed
it privately (#298). That fix did not reach the three places the APPLICATION opens
Postgres — the data connector, the store backend, and the vector store — all of which
were still handing the raw string to the URI parser. This module is that fix made
common, so the next caller inherits it instead of rediscovering it.
"""
from __future__ import annotations

from urllib.parse import parse_qsl, urlparse, urlunparse

#: Query parameters libpq understands, and which psycopg2 therefore accepts as keyword
#: arguments. Anything outside this set is a vendor marker (Supabase's `supa=`, a
#: connection-pooler hint) that libpq would reject.
LIBPQ_PARAMS = frozenset({
    "sslmode", "sslcert", "sslkey", "sslrootcert", "sslcrl", "sslpassword",
    "application_name", "fallback_application_name", "connect_timeout",
    "keepalives", "keepalives_idle", "keepalives_interval", "keepalives_count",
    "target_session_attrs", "options", "client_encoding", "gssencmode",
    "channel_binding", "passfile", "service", "replication",
})


def split_dsn(dsn: str) -> tuple[str, dict[str, str], list[str]]:
    """A URI plus its query parameters lifted into keyword arguments.

    `parse_qsl` splits on the FIRST ``=`` only, so ``options=-c search_path=public``
    survives intact as a value; handing it to psycopg2 as a keyword argument puts it
    past the URI parser entirely. Vendor markers are dropped and RETURNED, never
    silently discarded — a caller that swallows part of what someone pasted is its own
    kind of confusing.

    Returns ``(base_uri, libpq_kwargs, dropped_param_names)``. Only NAMES are returned
    for the dropped ones: these end up in operator-facing messages, and a value can be
    a credential.
    """
    parsed = urlparse(dsn)
    if not parsed.query:
        return dsn, {}, []
    params: dict[str, str] = {}
    dropped: list[str] = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        if key in LIBPQ_PARAMS:
            params[key] = value
        else:
            dropped.append(key)
    return urlunparse(parsed._replace(query="")), params, dropped


def merge_options(from_dsn: str | None, *required: str) -> str:
    """Combine libpq ``options`` from a DSN with options the caller must have.

    Both the DSN and the caller can carry ``-c`` settings, and passing ``options``
    twice to psycopg2 is a TypeError rather than a merge. The caller's come LAST
    because libpq applies ``-c`` in order and the last occurrence wins — which is what
    makes this safe for `default_transaction_read_only=on`: a DSN that tries to set it
    off cannot override the connector's own guarantee (SEC-02 / INV-2).
    """
    parts = [p for p in ([from_dsn] if from_dsn else []) + list(required) if p]
    return " ".join(parts)
