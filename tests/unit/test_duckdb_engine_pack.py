"""The DuckDB pack's claims, executed.

Prose about an engine rots silently: this product's own SQL-repair advice recommended
`epoch_days(date::DATE)` for two years, and DuckDB has never had that function — so the
repair turned one Catalog Error into another. Nobody noticed, because prose has no failing
test.

So the `duckdb-engine` pack's prose (`loader.PROSE_FILE`) was written from measurements
rather than from documentation, and this file re-runs every one of them. If DuckDB changes, or if somebody
edits a claim into something untrue, this fails and the pack gets corrected — which is the
only reason the pack is worth putting in front of a model at all.

Deliberately imports `duckdb` and nothing from `aughor` in the behaviour tests: what is
under test is the ENGINE, and reaching it through a connector would be asserting our
wrapper's behaviour instead.
"""
from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

PACK = Path(__file__).resolve().parents[2] / "packs" / "duckdb-engine"


@pytest.fixture()
def db():
    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE t AS SELECT i AS id, i % 3 AS g, i * 1.5 AS amt "
                "FROM range(10) r(i)")
    yield con
    con.close()


def _one(db, sql):
    return db.execute(sql).fetchone()[0]


# ── the claims, in the order the prose makes them ────────────────────────────────

def test_slash_is_float_division(db):
    """The claim that changes a NUMBER rather than raising: `count(a)/count(b)` means
    something different here than on Postgres, and neither errors."""
    assert _one(db, "SELECT 5/2") == 2.5
    assert _one(db, "SELECT 5//2") == 2


@pytest.mark.parametrize("text,expected", [("4.2", 4), ("4.5", 5), ("4.9", 5), ("-4.9", -5)])
def test_casting_to_an_integer_rounds_rather_than_truncating(db, text, expected):
    """The pack says ROUNDS, and the codebase used to say "truncating to 4" — which is true
    of 4.2 and false of 4.9. A comment that is right about its own example and wrong about
    the general case is how a reader concludes the damage is smaller than it is."""
    assert _one(db, f"SELECT TRY_CAST('{text}' AS BIGINT)") == expected


def test_try_cast_returns_null_for_formatted_numbers(db):
    assert _one(db, "SELECT TRY_CAST('1,234' AS DOUBLE)") is None
    assert _one(db, "SELECT TRY_CAST('$4.20' AS DOUBLE)") is None


def test_the_fractional_probe_the_pack_recommends_actually_works(db):
    """The prose hands the reader a query. An untested snippet in a pack is the same
    liability as an untested claim."""
    db.execute("CREATE TABLE c AS SELECT * FROM (VALUES ('4.9'), ('5'), ('x')) v(c)")
    assert _one(db, "SELECT count(*) FILTER (WHERE try_cast(c AS DOUBLE) IS NOT NULL "
                    "AND try_cast(c AS DOUBLE) <> floor(try_cast(c AS DOUBLE))) FROM c") == 1


def test_date_subtraction_is_a_number_and_timestamp_subtraction_is_an_interval(db):
    assert _one(db, "SELECT typeof(DATE '2024-03-01' - DATE '2024-01-01')") == "BIGINT"
    assert _one(db, "SELECT DATE '2024-03-01' - DATE '2024-01-01'") == 60
    assert _one(db, "SELECT typeof(TIMESTAMP '2024-03-01' - TIMESTAMP '2024-01-01')") \
        == "INTERVAL"


def test_wrapping_a_date_difference_errors_but_a_timestamp_one_does_not(db):
    with pytest.raises(Exception, match="(?i)no function matches"):
        db.execute("SELECT date_part('day', DATE '2024-03-01' - DATE '2024-01-01')")
    assert _one(db, "SELECT EXTRACT(EPOCH FROM "
                    "(TIMESTAMP '2024-03-01' - TIMESTAMP '2024-01-01'))") == 5184000.0


@pytest.mark.parametrize("call", [
    "TIMESTAMPDIFF('day', DATE '2024-01-01', DATE '2024-03-01')",
    "JULIANDAY(DATE '2024-01-01')",
    "to_char(DATE '2024-01-01', 'YYYY-MM')",
    "epoch_days(DATE '2024-01-01')",
])
def test_the_functions_the_pack_says_are_absent_are_absent(db, call):
    with pytest.raises(Exception, match="(?i)does not exist"):
        db.execute(f"SELECT {call}")


@pytest.mark.parametrize("call,expected", [
    ("date_diff('day', DATE '2024-01-01', DATE '2024-03-01')", 60),
    ("datediff('day', DATE '2024-01-01', DATE '2024-03-01')", 60),
    ("strftime(DATE '2024-01-01', '%Y-%m')", "2024-01"),
    ("date_diff('day', DATE '1970-01-01', DATE '2024-01-01')", 19723),
    ("epoch(DATE '2024-01-01')", 1704067200.0),
])
def test_every_replacement_the_pack_recommends_exists(db, call, expected):
    """The half that `epoch_days` failed. Naming the absent function is easy; the value of
    this table is entirely in the right-hand column being real."""
    assert _one(db, f"SELECT {call}") == expected


def test_a_bare_name_does_not_reach_another_schema(db):
    db.execute("CREATE SCHEMA s1; CREATE TABLE s1.orders AS SELECT 1 AS id")
    assert _one(db, "SELECT count(*) FROM s1.orders") == 1
    with pytest.raises(Exception, match="(?i)does not exist"):
        db.execute("SELECT count(*) FROM orders")


@pytest.mark.parametrize("quote", ["'{p}'", '"{p}"'])
def test_an_unmatched_table_source_is_read_as_a_file(db, tmp_path, quote):
    """The one that turns a mistyped table name into somebody's file rather than an error."""
    f = tmp_path / "probe.csv"
    f.write_text("a,b\n1,x\n2,y\n")
    assert _one(db, f"SELECT count(*) FROM {quote.format(p=f)}") == 2


def test_the_unquoted_form_works_for_a_bare_name_and_not_for_a_path(db, tmp_path, monkeypatch):
    """The pack claimed unquoted worked generally. It does not: a source containing `/` is a
    PARSER error, so only a bare relative name reaches the replacement scan unquoted. The
    first draft of the prose over-claimed here and this test is why it no longer does."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "probe.csv").write_text("a,b\n1,x\n2,y\n")

    assert _one(db, "SELECT count(*) FROM probe.csv") == 2
    with pytest.raises(Exception, match="(?i)syntax error"):
        db.execute(f"SELECT count(*) FROM {tmp_path / 'probe.csv'}")


def test_the_placeholder_spelling(db):
    assert db.execute("SELECT $who AS v", {"who": 1}).fetchone()[0] == 1
    assert db.execute("SELECT ? AS v", [1]).fetchone()[0] == 1
    with pytest.raises(Exception, match="(?i)syntax error"):
        db.execute("SELECT :who AS v", {"who": 1})


def test_approx_count_distinct_is_wrong_on_a_small_table(db):
    """The pack's sharpest claim — it says 11 for 10 distinct ids. If a DuckDB release makes
    this exact, the pack is telling readers to distrust a number that is now fine."""
    approx = _one(db, "SELECT approx_count_distinct(id) FROM t")
    exact = _one(db, "SELECT count(DISTINCT id) FROM t")
    assert exact == 10
    assert approx != exact, "approx_count_distinct is now exact here — update the pack"


@pytest.mark.parametrize("sql", [
    "SELECT * EXCLUDE (id) FROM t",
    "SELECT * REPLACE (amt * 2 AS amt) FROM t",
    "SELECT g, count(*) FROM t GROUP BY ALL",
    "SELECT id FROM t QUALIFY row_number() OVER (PARTITION BY g ORDER BY id) = 1",
    "SELECT count(*) FROM t USING SAMPLE 10%",
    "SELECT count(*) FROM t TABLESAMPLE (10 PERCENT)",
])
def test_every_construct_the_pack_recommends_runs(db, sql):
    db.execute(sql).fetchall()


def test_the_type_claims(db):
    assert _one(db, "SELECT typeof(1.5)") == "DECIMAL(2,1)"
    assert _one(db, "SELECT typeof(avg(x)) FROM (SELECT 1.5 AS x)") == "DOUBLE"


# ── the pack itself ──────────────────────────────────────────────────────────────

def test_the_pack_is_loadable_and_scoped_to_duckdb_engines():
    from aughor.packs import load_pack
    from aughor.packs import scope as pack_scope

    pack = load_pack(PACK)
    entries = pack_scope.entries(pack.manifest.scope)

    assert pack.manifest.partial is True, "engine syntax is not a claim about anyone's data"
    assert pack_scope.ANY not in entries, "an engine pack must not be offered to every engine"
    assert not pack_scope.unknown_engines(entries), "scope names an engine no connector has"
    # The DuckDB-backed connectors, by the class the product actually opens.
    for engine in ("duckdb", "local_upload", "motherduck", "s3", "federated", "gsheets"):
        assert pack_scope.matches(entries, connection_id="c1", conn_type=engine), engine
    for other in ("postgres", "bigquery", "snowflake", "mysql"):
        assert not pack_scope.matches(entries, connection_id="c1", conn_type=other), other


def test_the_prose_names_no_function_duckdb_lacks(db):
    """A rot-guard over the pack's own text: every `identifier(` that looks like a call and
    is not on the pack's own absent-list must resolve. `epoch_days` is in this file's
    docstring for a reason — prose is where an unreal function survives longest."""
    import re

    from aughor.packs.loader import PROSE_FILE

    text = (PACK / PROSE_FILE).read_text()
    known_absent = {"timestampdiff", "julianday", "to_char", "epoch_days"}
    catalogued = {r[0] for r in db.execute(
        "SELECT DISTINCT lower(function_name) FROM duckdb_functions()").fetchall()}
    called = {m.lower() for m in re.findall(r"\b([a-z_][a-z0-9_]{2,})\s*\(", text)}

    # SQL keyword-expressions, not catalogued functions — `duckdb_functions()` does not
    # list them, and flagging them would teach the next reader to loosen this guard.
    keywords = {"where", "filter", "over", "partition", "values", "select",
                "cast", "try_cast", "extract"}
    unreal = sorted(called - catalogued - known_absent - keywords)
    assert not unreal, (
        f"the pack names functions DuckDB does not have: {unreal}. Either they are typos or "
        f"they belong on the absent-list with the correct replacement beside them.")
