"""R8 wiring — making the governed prompt()/embedding() UDFs usable from agent-GENERATED SQL:
the opt-in gate, UDF registration on a real DuckDB connection, the in-SQL round-trip, the
generator hint, and the receipt trigger. Hermetic: the LLM provider / embedder are faked, so
this tests the WIRING + governance, not the model."""
from __future__ import annotations

import re
from types import SimpleNamespace

import duckdb
import pytest

import aughor.semops.ai_sql as ai_sql


def _echo(user: str):
    idxs = [int(m) for m in re.findall(r"\[(\d+)\]", user)]
    return SimpleNamespace(rows=[SimpleNamespace(index=i, value=f"v{i}") for i in idxs])


def _patch_provider(monkeypatch):
    prov = SimpleNamespace(_model="fake-model", complete=lambda **k: _echo(k["user"]))
    monkeypatch.setattr(ai_sql, "get_provider", lambda role: prov)
    return prov


# ── the opt-in gate ──────────────────────────────────────────────────────────
def test_ai_sql_disabled_by_default(monkeypatch):
    monkeypatch.delenv("AUGHOR_AI_SQL", raising=False)
    assert ai_sql.ai_sql_enabled() is False


def test_ai_sql_enabled_by_flag(monkeypatch):
    for v in ("1", "true", "YES", "on"):
        monkeypatch.setenv("AUGHOR_AI_SQL", v)
        assert ai_sql.ai_sql_enabled() is True
    monkeypatch.setenv("AUGHOR_AI_SQL", "0")
    assert ai_sql.ai_sql_enabled() is False


# ── receipt trigger detection ────────────────────────────────────────────────
def test_sql_uses_ai_column_detects_operators():
    assert ai_sql.sql_uses_ai_column("SELECT prompt('x', c) FROM t") == "prompt"
    assert ai_sql.sql_uses_ai_column("SELECT embedding(c) FROM t") == "embedding"
    assert ai_sql.sql_uses_ai_column("SELECT PROMPT('x', c) FROM t") == "prompt"   # case-insensitive
    assert ai_sql.sql_uses_ai_column("SELECT count(*) FROM t") is None
    assert ai_sql.sql_uses_ai_column("SELECT a_prompt_col FROM t") is None         # needs a paren call


# ── the generator hint ───────────────────────────────────────────────────────
def test_operator_hint_is_conservative():
    hint = ai_sql.ai_sql_operator_hint()
    assert "prompt(" in hint and "embedding(" in hint
    assert "LIMIT" in hint                               # always row-bound
    assert "NEVER" in hint                               # discourages overuse vs plain SQL


# ── in-SQL round-trip on a real DuckDB connection ────────────────────────────
def test_register_ai_udfs_prompt_round_trip(monkeypatch):
    """Generated SQL can call the registered prompt() UDF end-to-end on a real DuckDB conn."""
    _patch_provider(monkeypatch)
    con = duckdb.connect(":memory:")
    ai_sql.register_ai_udfs(con, max_calls=50)
    rows = con.execute(
        "SELECT msg, prompt('classify sentiment', msg) AS s "
        "FROM (VALUES ('great'), ('awful')) t(msg) ORDER BY msg"
    ).fetchall()
    assert [r[0] for r in rows] == ["awful", "great"]
    assert all(r[1] == "v0" for r in rows)               # AI column computed per row via the UDF


def test_register_ai_udfs_embedding_round_trip(monkeypatch):
    monkeypatch.setattr("aughor.semantic.embedder.embed", lambda xs: [[0.1, 0.2, 0.3] for _ in xs])
    con = duckdb.connect(":memory:")
    ai_sql.register_ai_udfs(con, max_calls=50)
    assert con.execute("SELECT embedding('hello')").fetchone()[0] == [0.1, 0.2, 0.3]


# ── connection-layer gating (db/connection._maybe_register_ai_udfs) ──────────
def test_connection_helper_noop_when_disabled(monkeypatch):
    from aughor.db import connection as conn_mod
    monkeypatch.delenv("AUGHOR_AI_SQL", raising=False)
    con = duckdb.connect(":memory:")
    conn_mod._maybe_register_ai_udfs(con, None)          # off → not registered
    with pytest.raises(Exception):
        con.execute("SELECT prompt('x', 'y')")


def test_connection_helper_registers_when_enabled(monkeypatch):
    from aughor.db import connection as conn_mod
    _patch_provider(monkeypatch)
    monkeypatch.setenv("AUGHOR_AI_SQL", "1")
    con = duckdb.connect(":memory:")
    conn_mod._maybe_register_ai_udfs(con, None)
    assert con.execute("SELECT prompt('x', 'y')").fetchone()[0] == "v0"


def test_connection_helper_skips_motherduck(monkeypatch):
    # MotherDuck has NATIVE prompt()/embedding() — don't shadow them.
    from aughor.db import connection as conn_mod
    _patch_provider(monkeypatch)
    monkeypatch.setenv("AUGHOR_AI_SQL", "1")
    con = duckdb.connect(":memory:")
    conn_mod._maybe_register_ai_udfs(con, "my_md_db")    # md_db set → skip registration
    with pytest.raises(Exception):
        con.execute("SELECT prompt('x', 'y')")
