"""Plane-conformance tests for the Trust plane (AL-01) — `aughor/trust`.

"Is the Trust plane correct?" as a runnable question, independent of any capability: the façade
must (1) BLOCK mutating / destructive / disallowed-function SQL decisively, (2) surface E1
footguns as advisory WARNs that never flip `ok`, (3) pass clean SELECTs, and (4) faithfully
compose the underlying guards (delegation parity). Plus one integration test proving the first
consumer — `/query/validate` — calls the plane behind the `trust.verify_facade` flag.
"""
from __future__ import annotations

from aughor.trust import verify, Scope, Verdict
from aughor.sql import readonly
from aughor.sql.trust_checks import run_trust_checks


# ── BLOCK: read-only / mutation is the decisive gate (the SEC-02 dimension) ──────────────

def test_delete_is_blocked():
    v = verify("DELETE FROM orders WHERE id = 1")
    assert v.ok is False
    assert [c.name for c in v.blockers] == ["readonly"]
    assert v.reason  # a human reason is present
    assert v.blockers[0].detail["destructive"] is False  # DELETE mutates but isn't DDL-destructive


def test_drop_is_blocked_and_destructive():
    v = verify("DROP TABLE orders")
    assert v.ok is False
    assert v.blockers[0].name == "readonly"
    assert v.blockers[0].detail["destructive"] is True


def test_cte_masked_write_is_blocked():
    # WITH x AS (DELETE ... RETURNING *) SELECT * FROM x — a write hidden in a CTE.
    v = verify("WITH x AS (DELETE FROM orders RETURNING *) SELECT * FROM x")
    assert v.ok is False
    assert any(c.name == "readonly" for c in v.blockers)


def test_disallowed_function_is_blocked():
    v = verify("SELECT pg_read_file('/etc/passwd')", Scope(dialect="postgres"))
    assert v.ok is False
    names = {c.name for c in v.blockers}
    assert "disallowed_functions" in names
    fn_check = next(c for c in v.blockers if c.name == "disallowed_functions")
    assert "PG_READ_FILE" in fn_check.detail["functions"]


# ── PASS: a clean read is ok, with no blockers ───────────────────────────────────────────

def test_clean_select_passes():
    v = verify("SELECT id, total FROM orders WHERE total > 0")
    assert v.ok is True
    assert v.blockers == []
    assert v.artifact == "SELECT id, total FROM orders WHERE total > 0"
    assert v.repaired is False


# ── WARN: E1 footguns are advisory — surfaced, never fatal ───────────────────────────────

def test_e1_date_boundary_is_a_warning_not_a_blocker():
    sql = "SELECT * FROM orders WHERE created_at <= '2024-01-01'"
    v = verify(sql)
    assert v.ok is True                       # a WARN never flips ok
    assert v.blockers == []
    warns = v.warnings
    assert len(warns) == 1
    assert warns[0].name == "trust_checks"
    assert warns[0].detail["pattern"] == "E1-date-boundary"
    assert warns[0].reason  # the caveat message is threaded through


# ── DELEGATION PARITY: the Verdict is exactly the composition of the underlying guards ────

def test_readonly_parity():
    samples = [
        "SELECT 1",
        "SELECT a FROM t",
        "DELETE FROM t",
        "UPDATE t SET a = 1",
        "INSERT INTO t VALUES (1)",
        "DROP TABLE t",
        "TRUNCATE t",
    ]
    for sql in samples:
        expect_blocked = readonly.is_mutating(sql) or bool(readonly.disallowed_functions(sql))
        assert verify(sql).ok is (not expect_blocked), sql


def test_trust_checks_parity_no_conn():
    # With no connection only the pure guards run, so the WARN set == the E1 findings.
    sql = "SELECT * FROM orders WHERE created_at <= '2024-01-01'"
    assert len(verify(sql).warnings) == len(run_trust_checks(sql))


# ── Verdict / Scope shape ────────────────────────────────────────────────────────────────

def test_scopeless_and_conn_free_call_is_safe():
    # A bare Scope() must never crash and never invoke a probe/repair guard.
    v = verify("SELECT 1")
    assert isinstance(v, Verdict)
    assert v.kind == "sql"
    assert v.repaired is False


def test_non_sql_kinds_return_ok_passthrough():
    for kind in ("code", "metadata"):
        v = verify("print('hi')", kind=kind)
        assert v.ok is True
        assert v.kind == kind
        assert v.artifact == "print('hi')"
        assert v.checks == ()


def test_empty_sql_is_ok():
    v = verify("")
    assert v.ok is True
    assert v.checks == ()


# ── Integration: the first consumer (/query/validate) calls the plane behind the flag ────

def test_validate_surfaces_mutation_blockers_when_flag_on(client, builtin_conn_id, monkeypatch):
    monkeypatch.setenv("AUGHOR_TRUST_FACADE", "1")
    r = client.post("/query/validate",
                    json={"conn_id": builtin_conn_id, "sql": "DELETE FROM ecommerce.orders",
                          "dialect": "duckdb"})
    assert r.status_code == 200
    body = r.json()
    assert body["mutation_blockers"], "the AST read-only gate should flag a DELETE"
    assert body["mutation_blockers"][0]["name"] == "readonly"
    assert body["passed"] is False


def test_validate_omits_facade_when_flag_off(client, builtin_conn_id, monkeypatch):
    monkeypatch.delenv("AUGHOR_TRUST_FACADE", raising=False)
    r = client.post("/query/validate",
                    json={"conn_id": builtin_conn_id, "sql": "DELETE FROM ecommerce.orders",
                          "dialect": "duckdb"})
    assert r.status_code == 200
    # Field is always present but empty when the plane is not adopted (default off).
    assert r.json()["mutation_blockers"] == []
