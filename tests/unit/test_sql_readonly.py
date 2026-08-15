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


# ── DuckDB external-reader denylist (file / network / secret exfiltration) ────
# Reads, not writes — the mutation gate passes them by design, so the denylist
# is the only thing between LLM SQL and the local filesystem.

def test_duckdb_file_readers_are_disallowed_in_any_position():
    for sql, expected in [
        ("SELECT * FROM read_csv('/etc/passwd')", "READ_CSV"),          # dedicated sqlglot node
        ("SELECT * FROM read_csv_auto('x.csv')", "READ_CSV_AUTO"),      # exp.Anonymous
        ("SELECT * FROM read_parquet(['a.parquet'])", "READ_PARQUET"),
        ("SELECT * FROM read_text('/etc/passwd')", "READ_TEXT"),
        ("SELECT * FROM glob('/**')", "GLOB"),
        ("SELECT * FROM sniff_csv('/etc/passwd')", "SNIFF_CSV"),
        ("SELECT * FROM postgres_scan('host=h', 'public', 't')", "POSTGRES_SCAN"),
        ("SELECT * FROM duckdb_secrets()", "DUCKDB_SECRETS"),
        ("SELECT getenv('AUGHOR_SECRET_KEY')", "GETENV"),
        # CTE position — the reader must be found anywhere in the tree
        ("WITH t AS (SELECT * FROM read_blob('/etc/shadow')) SELECT * FROM t", "READ_BLOB"),
    ]:
        for dialect in (None, "duckdb"):
            found = disallowed_functions(sql, dialect)
            assert expected in found, f"{sql!r} (dialect={dialect}) → {found}"


def test_file_path_table_sources_are_disallowed():
    # DuckDB's replacement scan: a bare string/identifier table source reads the file.
    for sql in [
        "SELECT * FROM '/data/x.csv'",
        "SELECT * FROM 's3://bucket/x.parquet'",
        'SELECT * FROM "reads.csv"',
    ]:
        found = disallowed_functions(sql, "duckdb")
        assert "FILE_TABLE_SOURCE" in found, f"{sql!r} → {found}"


def test_reader_names_as_columns_or_tables_are_not_flagged():
    # High-precision guarantee: identifiers that merely LOOK like reader names
    # are columns/tables, not calls — they must pass.
    for sql in [
        "SELECT read_csv FROM t",
        "SELECT * FROM orders",
        "SELECT glob, getenv FROM feature_flags",
        "SELECT * FROM s1.t1 JOIN s2.t2 ON t1.id = t2.id",
    ]:
        assert disallowed_functions(sql, "duckdb") == set(), sql


def test_attach_and_install_are_mutating():
    # These parse as dedicated sqlglot nodes (exp.Attach / exp.Install), NOT
    # exp.Command — the command-head list never saw them.
    for sql in [
        "ATTACH '/tmp/evil.db' AS m",
        "INSTALL httpfs",
        "FORCE INSTALL httpfs",
    ]:
        assert is_mutating(sql, dialect="duckdb") is True, sql


def test_safetychecker_blocks_duckdb_reader_surface():
    for sql in [
        "SELECT * FROM read_csv('/etc/passwd')",
        "SELECT * FROM '/data/x.csv'",
        "ATTACH '/tmp/evil.db' AS m",
        # EXPORT/IMPORT DATABASE fail to parse — the first-token belt must hold.
        "EXPORT DATABASE '/tmp/x'",
        "IMPORT DATABASE '/tmp/x'",
        "INSTALL httpfs",
        "LOAD httpfs",
    ]:
        assert SafetyChecker.check(sql).verdict == SafetyVerdict.BLOCKED, sql


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
