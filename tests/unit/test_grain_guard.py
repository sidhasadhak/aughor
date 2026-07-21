"""Tests for the grain/fan-out guard (aughor/sql/grain_guard.py).

Contract: fire ONLY on a probe-confirmed additive-aggregate-over-fan-out-join (so it can power a
trust caveat / repair signal without ever flagging a correct query). Includes a real in-memory
SQLite integration test so detection is proven against an actual row-multiplying join.
"""
from __future__ import annotations

import sqlite3

from aughor.sql.grain_guard import detect_fanout, fanout_caveat, FanoutFinding


def _mock_probe(fanned_tables: dict):
    """probe_fn that reports (COUNT(*), COUNT(DISTINCT key)) per table from `fanned_tables`."""
    def probe(sql: str):
        for tbl, (total, distinct) in fanned_tables.items():
            if f"FROM {tbl}" in sql:
                return True, [(total, distinct)], ""
        return True, [(1, 1)], ""   # default: unique
    return probe


def test_detects_additive_aggregate_over_fanout_join():
    sql = ("SELECT d.region, SUM(f.amount) AS total FROM fact f "
           "JOIN dim d ON f.region_id = d.region_id "
           "JOIN tags t ON f.id = t.fact_id GROUP BY d.region")
    probe = _mock_probe({"tags": (10, 5), "dim": (5, 5)})   # tags fans out, dim unique
    findings = detect_fanout(sql, probe, dialect="sqlite")
    assert len(findings) == 1
    f = findings[0]
    assert f.fanned_table == "tags" and f.join_key == "fact_id" and f.ratio == 2.0
    assert any("SUM(" in a.upper() for a in f.aggregates)


def test_no_aggregate_no_flag():
    sql = "SELECT f.id, t.label FROM fact f JOIN tags t ON f.id = t.fact_id"
    findings = detect_fanout(sql, _mock_probe({"tags": (10, 5)}), dialect="sqlite")
    assert findings == []   # no additive aggregate ⇒ fan-out cannot inflate a number


def test_count_distinct_is_fanout_safe():
    sql = ("SELECT COUNT(DISTINCT f.id) FROM fact f "
           "JOIN tags t ON f.id = t.fact_id")
    findings = detect_fanout(sql, _mock_probe({"tags": (10, 5)}), dialect="sqlite")
    assert findings == []   # COUNT(DISTINCT …) is not distorted by row duplication


def test_unique_join_not_flagged():
    sql = ("SELECT d.region, SUM(f.amount) FROM fact f "
           "JOIN dim d ON f.region_id = d.region_id GROUP BY d.region")
    findings = detect_fanout(sql, _mock_probe({"dim": (5, 5)}), dialect="sqlite")
    assert findings == []   # one-to-one join ⇒ no fan-out, no false positive


def test_caveat_text():
    f = FanoutFinding(fanned_table="tags", join_key="fact_id", ratio=2.0, aggregates=["SUM(f.amount)"])
    c = fanout_caveat([f])
    assert "over-count" in c.lower() and "tags" in c and "fact_id" in c


def test_real_sqlite_fanout_detected():
    """End-to-end on a real DB: SUM over a 1:many join genuinely over-counts → must be detected."""
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE fact (id INTEGER, amount REAL);
        CREATE TABLE tags (fact_id INTEGER, label TEXT);
        INSERT INTO fact VALUES (1, 100.0), (2, 50.0);
        INSERT INTO tags VALUES (1,'a'),(1,'b'),(2,'c');   -- fact 1 has 2 tags ⇒ fan-out
    """)

    def probe(sql):
        try:
            cur = conn.execute(sql)
            return True, cur.fetchall(), ""
        except Exception as e:
            return False, None, str(e)

    sql = "SELECT SUM(f.amount) FROM fact f JOIN tags t ON f.id = t.fact_id"
    # sanity: the query really does over-count (250 instead of 150)
    assert conn.execute(sql).fetchone()[0] == 250.0
    findings = detect_fanout(sql, probe, dialect="sqlite")
    conn.close()
    assert len(findings) == 1 and findings[0].fanned_table == "tags"


def test_wiring_plumbing_through_product_connector(tmp_path):
    """Proves the /query/validate wiring path: the product SQLiteConnection returns STRINGIFIED
    cells, and detect_fanout must coerce them — using the exact probe wrapper the endpoint uses."""
    from aughor.connectors.file.sqlite import SQLiteConnection

    db_file = tmp_path / "fan.sqlite"
    seed = sqlite3.connect(str(db_file))
    seed.executescript("""
        CREATE TABLE fact (id INTEGER, amount REAL);
        CREATE TABLE tags (fact_id INTEGER, label TEXT);
        INSERT INTO fact VALUES (1,100.0),(2,50.0);
        INSERT INTO tags VALUES (1,'a'),(1,'b'),(2,'c');
    """)
    seed.commit(); seed.close()

    conn = SQLiteConnection(dsn=str(db_file), connection_id="grain_test")

    def _grain_probe(s):                       # identical shape to the endpoint's wrapper
        r = conn.execute("__grain_probe__", s)
        return (not r.error, r.rows, r.error or "")

    findings = detect_fanout(
        "SELECT SUM(f.amount) FROM fact f JOIN tags t ON f.id = t.fact_id",
        _grain_probe, dialect="sqlite")
    conn.close()
    assert len(findings) == 1 and findings[0].fanned_table == "tags"
    assert findings[0].ratio == 1.5 and "over-count" in findings[0].caveat().lower()


def test_probe_keeps_the_schema_qualifier():
    """REGRESSION (luxexperience Briefing, 2026-07-21): the probe was built from `right.name`,
    which sqlglot returns WITHOUT the catalog/schema — so a schema-qualified query (everything
    the explorer writes) probed a table that doesn't exist, errored, and the guard silently
    returned no findings. The guard was structurally disabled on the majority of real SQL.

    Locks the probe text itself, so the qualifier can't be dropped again by a refactor."""
    issued: list[str] = []

    def probe(sql: str):
        issued.append(sql)
        return True, [(6, 2)], ""       # 3 rows per key ⇒ genuine fan-out

    findings = detect_fanout(
        "SELECT f.platform, d.type, SUM(f.gmv) AS m "
        "FROM lux.marketing_campaigns f JOIN lux.brand_collaborations d ON f.platform = d.platform "
        "GROUP BY f.platform, d.type",
        probe, dialect="duckdb")

    assert issued == ["SELECT COUNT(*), COUNT(DISTINCT platform) FROM lux.brand_collaborations"]
    assert len(findings) == 1
    assert findings[0].fanned_table == "lux.brand_collaborations"
    assert findings[0].ratio == 3.0


def test_unqualified_table_probe_stays_unqualified():
    """The qualifier fix must not invent one: a bare table name still probes bare."""
    issued: list[str] = []

    def probe(sql: str):
        issued.append(sql)
        return True, [(4, 2)], ""

    detect_fanout("SELECT SUM(f.amount) FROM fact f JOIN tags t ON f.id = t.fact_id",
                  probe, dialect="duckdb")
    assert issued == ["SELECT COUNT(*), COUNT(DISTINCT fact_id) FROM tags"]
