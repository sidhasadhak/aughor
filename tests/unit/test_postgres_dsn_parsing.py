"""Every Postgres connection accepts the strings providers actually hand out.

psycopg2 parses a `postgres://` URI itself and rejects a query value containing `=`
plus any parameter it does not recognise. `scripts/load_duckdb_to_postgres.py` hit
this against a real Supabase DSN and fixed it privately (#298); the fix did not reach
the three places the APPLICATION opens Postgres, so a DSN that loaded data fine still
could not be registered as a connection.

The shapes below are the ones that actually break, not invented ones.
"""
from __future__ import annotations

import psycopg2
import pytest

from aughor.db.dsn import LIBPQ_PARAMS, merge_options, split_dsn

# Supabase's copy-paste pooler DSN: a vendor marker libpq has never heard of.
SUPABASE_POOLER = "postgresql://u:p@db.example.supabase.com:6543/postgres?sslmode=require&supa=base-pooler.x"
# A value containing `=` — how `options` arrives, and psycopg2's "extra key/value separator".
EMBEDDED_EQUALS = "postgresql://u:p@host:5432/db?options=-c search_path=public"
PLAIN_SSLMODE = "postgresql://u:p@host:5432/db?sslmode=require"
NO_QUERY = "postgresql://u:p@host:5432/db"


class _FakeCursor:
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def execute(self, *a, **k): return None


class _FakeConn:
    def __init__(self): self.autocommit = False
    def cursor(self): return _FakeCursor()
    def commit(self): return None


# ── the splitter ────────────────────────────────────────────────────────────


def test_vendor_marker_is_dropped_and_named() -> None:
    base, params, dropped = split_dsn(SUPABASE_POOLER)
    # `supa=`, not `supa`: the HOSTNAME is db.example.supabase.com, so a bare substring
    # check passes on a correct result and fails on nothing useful. Matching the
    # parameter is the claim; matching the letters is a different, wrong claim.
    assert "supa=" not in base and "?" not in base
    assert params == {"sslmode": "require"}
    assert dropped == ["supa"], "a dropped parameter must be reported, not swallowed"


def test_value_with_embedded_equals_survives_intact() -> None:
    """parse_qsl splits on the FIRST `=` only — the rest belongs to the value."""
    _base, params, dropped = split_dsn(EMBEDDED_EQUALS)
    assert params == {"options": "-c search_path=public"}
    assert dropped == []


def test_query_free_dsn_is_returned_untouched() -> None:
    assert split_dsn(NO_QUERY) == (NO_QUERY, {}, [])


def test_only_names_are_reported_never_values() -> None:
    """This output reaches operators and chat windows; a value can be a credential."""
    _b, _p, dropped = split_dsn(
        "postgresql://user:hunter2@host/db?token=s3cr3t-value&sslmode=require")
    assert dropped == ["token"]
    assert all("s3cr3t" not in d and "hunter2" not in d for d in dropped)


def test_every_forwarded_param_is_a_real_libpq_keyword() -> None:
    """A typo here would forward a keyword psycopg2 rejects — the bug, inverted."""
    for name in LIBPQ_PARAMS:
        assert name.islower() and name.isidentifier(), name


# ── options merging (the read-only invariant) ───────────────────────────────


def test_merge_puts_required_options_last() -> None:
    """libpq applies `-c` in order, so ours must come last to win."""
    merged = merge_options("-c search_path=public", "-c default_transaction_read_only=on")
    assert merged.index("search_path") < merged.index("default_transaction_read_only")


def test_merge_handles_absent_dsn_options() -> None:
    assert merge_options(None, "-c x=1") == "-c x=1"
    assert merge_options("", "-c x=1") == "-c x=1"


# ── the three application call sites ────────────────────────────────────────


@pytest.mark.parametrize("dsn", [SUPABASE_POOLER, EMBEDDED_EQUALS, PLAIN_SSLMODE, NO_QUERY])
def test_data_connector_never_hands_a_query_string_to_the_uri_parser(monkeypatch, dsn) -> None:
    captured = {}

    def _fake_connect(target, **kwargs):
        captured["target"], captured["kwargs"] = target, kwargs
        return _FakeConn()

    monkeypatch.setattr(psycopg2, "connect", _fake_connect)
    from aughor.db.connection import PostgresConnection
    PostgresConnection(dsn, schema_name="public")

    assert "?" not in captured["target"], (
        f"query string reached psycopg2's URI parser: {captured['target']!r}")
    assert "supa=" not in captured["target"]  # `supa=`, not `supa` — see above


def test_read_only_survives_a_dsn_that_carries_its_own_options(monkeypatch) -> None:
    """The regression this fix could have introduced: passing `options` twice is a
    TypeError, and merging it the wrong way round would let a DSN turn read-only off."""
    captured = {}

    def _fake_connect(target, **kwargs):
        captured.update(kwargs)
        return _FakeConn()

    monkeypatch.setattr(psycopg2, "connect", _fake_connect)
    from aughor.db.connection import PostgresConnection
    PostgresConnection(
        "postgresql://u:p@host/db?options=-c default_transaction_read_only=off",
        schema_name="public")

    opts = captured["options"]
    assert "default_transaction_read_only=on" in opts
    assert opts.rindex("default_transaction_read_only=on") > opts.rindex(
        "default_transaction_read_only=off"), (
        f"a DSN must not be able to turn read-only off: options={opts!r}")


def test_store_backend_lifts_query_params(monkeypatch) -> None:
    captured = {}

    def _fake_connect(target, **kwargs):
        captured["target"], captured["kwargs"] = target, kwargs
        return _FakeConn()

    monkeypatch.setattr(psycopg2, "connect", _fake_connect)
    from aughor.db.backend import PgConnection
    PgConnection(SUPABASE_POOLER, schema="store_test")

    assert "?" not in captured["target"]
    assert captured["kwargs"] == {"sslmode": "require"}


def test_vector_store_lifts_query_params(monkeypatch) -> None:
    captured = {}

    def _fake_connect(target, **kwargs):
        captured["target"], captured["kwargs"] = target, kwargs
        raise RuntimeError("stop after connect — the rest needs a live pgvector")

    monkeypatch.setenv("AUGHOR_DB_URL", SUPABASE_POOLER)
    monkeypatch.setattr(psycopg2, "connect", _fake_connect)
    from aughor.semantic import vector_store

    with pytest.raises(RuntimeError):
        vector_store._pg()
    assert "?" not in captured["target"]
    assert captured["kwargs"] == {"sslmode": "require"}


def test_loader_shares_the_one_implementation() -> None:
    """The bug existed because a fix lived in one caller and not the others."""
    import scripts.load_duckdb_to_postgres as loader

    assert loader._split_dsn is split_dsn
