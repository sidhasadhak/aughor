"""AST read-only / mutation gate — the cases the regex first-token check misses.

Locks the contract for aughor/sql/readonly.py (is_mutating / is_destructive /
disallowed_functions) and aughor/sql/tables.py (CTE-safe extraction), plus the
SafetyChecker integration that now blocks AST-detected mutations.

High-precision: a real SELECT must NEVER be flagged mutating.
"""
from aughor.db.connection import _validate
from aughor.sql.readonly import disallowed_functions, is_destructive, is_mutating
from aughor.sql.tables import extract_tables
from aughor.security.safety import SafetyChecker, SafetyVerdict


# ── connection-level _validate: keyword-in-string is data, not a statement ────

def test_validate_allows_dml_keyword_inside_a_string_literal():
    # The natural aughor_ops self-investigation query — task names literally
    # contain 'execute'/'delete'-ish words; these must not be mistaken for DML.
    for sql in [
        "SELECT input FROM aughor_ops.task_history WHERE task = 'sql.execute'",
        "SELECT * FROM orders WHERE note = 'please DELETE this later'",
        "SELECT 'DROP TABLE x' AS s",
        "SELECT task FROM t WHERE task IN ('sql.execute', 'briefing.run')",
    ]:
        ok, reason = _validate(sql)
        assert ok, f"{sql!r} wrongly blocked: {reason}"


def test_validate_still_blocks_real_mutations_even_with_strings():
    # A real DML keyword in statement position is outside any balanced string and
    # must still be rejected (the fix only blanks string DATA, not the statement).
    for sql in [
        "DELETE FROM t WHERE note = 'keep this'",
        "DROP TABLE aughor_ops.task_history",
        "UPDATE t SET x = 1 WHERE label = 'select me'",
        "INSERT INTO t (a) VALUES ('sql.execute')",
    ]:
        ok, _ = _validate(sql)
        assert not ok, f"{sql!r} must be blocked"


# ── reads must stay reads (no false positives) ────────────────────────────────

def test_plain_selects_are_not_mutating():
    for sql in [
        "SELECT * FROM orders",
        "SELECT customer_id, SUM(total) FROM orders GROUP BY customer_id",
        "SELECT * FROM a JOIN b ON a.id = b.id WHERE a.x > 1",
        "WITH x AS (SELECT 1 AS n) SELECT * FROM x",
        "SELECT upper('lo_export') AS s",         # string arg, NOT a function call
        "SELECT count(*) FROM t HAVING count(*) > 5",
        "EXPLAIN SELECT * FROM t",                # plain EXPLAIN is a read
    ]:
        assert is_mutating(sql) is False, sql


def test_cte_masking_a_write_does_not_hide_it():
    # The CTE body is a DELETE — must be caught even though the outer is SELECT.
    sql = "WITH x AS (DELETE FROM t RETURNING *) SELECT * FROM x"
    assert is_mutating(sql, dialect="postgres") is True


# ── DML / DDL the first-token list covers (regression) ────────────────────────

def test_classic_dml_ddl_is_mutating():
    for sql in [
        "INSERT INTO t VALUES (1)",
        "UPDATE t SET x = 1",
        "DELETE FROM t WHERE id = 1",
        "DROP TABLE t",
        "TRUNCATE TABLE t",
        "CREATE TABLE t AS SELECT 1 AS n",
        "ALTER TABLE t ADD COLUMN c INT",
        "MERGE INTO t USING s ON t.id = s.id WHEN MATCHED THEN UPDATE SET t.x = s.x",
    ]:
        assert is_mutating(sql) is True, sql


# ── the AST-only catches (regex passed these) ─────────────────────────────────

def test_mutating_functions_in_a_select_are_caught():
    assert is_mutating("SELECT lo_export('/tmp/x', loid) FROM big_objects") is True
    assert is_mutating("SELECT setval('my_seq', 1)") is True
    assert is_mutating("SELECT nextval('my_seq')") is True


def test_explain_analyze_dml_is_mutating():
    assert is_mutating("EXPLAIN ANALYZE DELETE FROM t", dialect="postgres") is True


def test_select_into_ctas_is_mutating():
    assert is_mutating("SELECT * INTO new_table FROM orders", dialect="postgres") is True


# ── destructive subset ────────────────────────────────────────────────────────

def test_is_destructive():
    assert is_destructive("DROP TABLE t") is True
    assert is_destructive("TRUNCATE TABLE t") is True
    assert is_destructive("ALTER TABLE t ADD COLUMN c INT") is True
    # DML mutates but is not "destructive DDL"
    assert is_destructive("INSERT INTO t VALUES (1)") is False
    assert is_destructive("SELECT * FROM t") is False


# ── disallowed (info-disclosure / file / network) functions ───────────────────

def test_disallowed_functions():
    assert "PG_READ_FILE" in disallowed_functions("SELECT pg_read_file('/etc/passwd')")
    assert "VERSION" in disallowed_functions("SELECT version()")
    assert disallowed_functions("SELECT * FROM orders") == set()


# ── CTE-safe table extraction ─────────────────────────────────────────────────

def test_extract_tables_excludes_cte_names():
    refs = extract_tables("WITH foo AS (SELECT * FROM secret) SELECT * FROM foo")
    names = {r.table for r in refs}
    assert "secret" in names
    assert "foo" not in names  # the CTE alias is not a real table


def test_extract_tables_schema_qualified_and_joins():
    refs = extract_tables("SELECT * FROM s1.t1 JOIN s2.t2 ON t1.id = t2.id")
    pairs = {(r.schema, r.table) for r in refs}
    assert ("s1", "t1") in pairs
    assert ("s2", "t2") in pairs


# ── SafetyChecker integration: AST verdict now blocks ─────────────────────────

def test_safetychecker_blocks_ast_only_writes():
    # These were SAFE under the pure-regex gate.
    for sql in [
        "SELECT lo_export('/tmp/x', 1)",
        "SELECT setval('s', 1)",
        "SELECT pg_read_file('/etc/passwd')",
    ]:
        assert SafetyChecker.check(sql).verdict == SafetyVerdict.BLOCKED, sql


def test_safetychecker_still_allows_reads():
    assert SafetyChecker.check("SELECT * FROM orders WHERE total > 100").verdict == SafetyVerdict.SAFE
    assert SafetyChecker.check("WITH x AS (SELECT 1 AS n) SELECT * FROM x").verdict == SafetyVerdict.SAFE
