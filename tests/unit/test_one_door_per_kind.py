"""Arc NV-7 (ROADMAP §6 item 61) — one door per kind: the platform signs what it sends, the history reader leaves it out,
and a formula other people compute is proposed in the Semantic Layer's catalogue, never as a card in Attention.

Measured first (LuxExperience, 2026-11-05): the warehouse's history was almost entirely the platform's own statements,
and the candidate door proposed sixteen of the platform's own approved metrics back to a person. Three seams pinned here:
the signature at every driver call (and NOT on the statement a result carries); the reader's exclusion, with the count
said; and the coverage run's history proposer — known formulas skipped through one normalisation both sides go through,
the platform's aliases skipped, a proposal carrying the FROM of the statement it was seen in, aliases resolved.
"""
from __future__ import annotations

import ast
import pathlib

from aughor.db.query_history import HistoryRow, QueryHistory, not_platform_statement
from aughor.db.signing import SIGNATURE, is_signed, sign

ROOT = pathlib.Path(__file__).resolve().parents[2]


# ── the signature ─────────────────────────────────────────────────────────────────────────

def test_sign_is_a_leading_comment_applied_once():
    assert sign("SELECT 1") == f"{SIGNATURE} SELECT 1"
    assert sign(sign("SELECT 1")) == f"{SIGNATURE} SELECT 1"
    assert sign("   ") == "   " and sign("") == ""
    assert is_signed(f"{SIGNATURE} SELECT 1") and is_signed("  /* aughor */ select 1") and not is_signed("SELECT 1")
    assert not is_signed("SELECT '/* aughor */' FROM t WHERE x > " + "1" * 300)   # only at the head


def test_every_warehouse_driver_call_is_signed_and_the_result_keeps_the_statement_as_written():
    """A capability added to one connector misses the others (ROADMAP §7): each engine with a history signs at its
    driver call. DuckDB and the file connectors keep no history and are left alone."""
    sites = {
        "aughor/db/connection.py": 2,                        # Postgres: the bound and the plain branch
        "aughor/connectors/warehouse/dbapi.py": 2,           # ClickHouse, Databricks and the DB-API family
        "aughor/connectors/warehouse/snowflake.py": 2,
        "aughor/connectors/warehouse/bigquery.py": 2,        # execute and the typed read
        "aughor/connectors/warehouse/trino.py": 1,
        "aughor/connectors/warehouse/mysql.py": 2,
        "aughor/connectors/warehouse/exasol.py": 1,
    }
    for rel, n in sites.items():
        src = (ROOT / rel).read_text()
        assert src.count("sign(") >= n, (rel, src.count("sign("))
        assert "from aughor.db.signing import sign" in src, rel
        # the signature goes to the driver alone: no QueryResult is built from a signed statement
        assert "sql=sign(" not in src and "QueryResult(hypothesis_id=hypothesis_id, sql=sign" not in src, rel


# ── the reader leaves ours out, and says so ──────────────────────────────────────────────

def test_the_history_reader_leaves_signed_statements_out_and_counts_them():
    h = QueryHistory(engine="postgres", supported=True, source="pg_stat_statements", rows=[
        HistoryRow("t", f"{SIGNATURE} SELECT SUM(gmv_eur) FROM orders", "lux", calls=302),
        HistoryRow("t", "SELECT d.category, SUM(o.duty_eur) FROM orders o JOIN customer_service d ON o.order_id = d.order_id GROUP BY 1", "analyst", calls=7),
        HistoryRow("t", "SELECT count(*) FROM orders", "etl", calls=1),
    ])
    assert h.statements == [h.rows[1].sql, h.rows[2].sql] and h.calls == 8
    assert h.ours == {"statements": 1, "calls": 302} and h.to_dict()["ours"]["calls"] == 302
    assert h.weighted_statements().count(h.rows[1].sql) == 7 and not any(is_signed(s) for s in h.weighted_statements())
    assert not not_platform_statement(f"{SIGNATURE} SELECT 1") and not_platform_statement("SELECT 1 FROM orders")


# ── the coverage run proposes what other people compute, once ────────────────────────────

class _Metric:
    def __init__(self, name, sql, status="approved"):
        self.name, self.label, self.sql, self.status = name, name, sql, status


class _Db:
    dialect = "postgres"
    def __init__(self, rows):
        self._rows = rows
    def query_history(self, *, hours=1, limit=1):
        return QueryHistory(engine="postgres", supported=True, source="public.pg_stat_statements", rows=self._rows)


class _Map:
    readable: list = []


def test_formula_key_folds_literals_parameters_whitespace_and_case():
    from aughor.semantic.coverage_proposals import formula_key
    a = formula_key("SUM(gmv_eur) / NULLIF(COUNT(DISTINCT order_id), 0)", "postgres")
    b = formula_key("sum(gmv_eur)  /  nullif(count(distinct order_id), $1)", "postgres")
    assert a == b
    assert formula_key("SUM(gmv_eur)", "postgres") != formula_key("SUM(refund_eur)", "postgres")


def test_known_formulas_read_through_the_same_miner_as_the_history():
    from aughor.semantic.coverage_proposals import formula_key, known_formula_keys
    keys = known_formula_keys([_Metric("aov", "SELECT SUM(o.gmv_eur) / NULLIF(COUNT(DISTINCT o.order_id), 0) AS aov_eur FROM orders o")],
                              "postgres")
    assert formula_key("SUM(orders.gmv_eur) / NULLIF(COUNT(DISTINCT orders.order_id), $2)", "postgres") in keys


def test_the_from_clause_is_carried_with_aliases_resolved_and_filters_dropped():
    from aughor.semantic.coverage_proposals import from_clause_of
    sql = ("SELECT SUM(oi.quantity * oi.unit_price_eur) AS merch FROM order_items oi JOIN orders o ON o.order_id = oi.order_id "
           "WHERE o.status = 'paid' GROUP BY 1")
    assert from_clause_of(sql, "postgres") == ("FROM order_items JOIN orders ON orders.order_id = order_items.order_id",
                                               ["order_items", "orders"])
    assert from_clause_of("not sql", "postgres") == ("", [])


def test_history_proposals_skip_ours_known_and_platform_aliases_and_propose_the_rest(monkeypatch):
    from aughor.semantic import coverage_proposals as CP
    from aughor.semantic import metric_coverage as MC
    monkeypatch.setattr(MC, "tables_of", lambda cid, s: [])
    rows = [
        HistoryRow("t", f"{SIGNATURE} SELECT SUM(gmv_eur) AS gmv_eur FROM orders", "lux", calls=300),         # ours
        HistoryRow("t", "SELECT SUM(gmv_eur) AS gmv_eur FROM orders", "analyst", calls=5),                     # known metric
        HistoryRow("t", "SELECT MIN(order_date) AS _first FROM orders", "analyst", calls=5),                   # platform alias
        HistoryRow("t", "SELECT SUM(oi.quantity * oi.unit_price_eur) AS merch_value FROM order_items oi "
                        "JOIN orders o ON o.order_id = oi.order_id WHERE o.status = 'paid'", "analyst", calls=3),  # new
        HistoryRow("t", "SELECT AVG(delivery_days) AS once FROM shipments", "analyst", calls=1),               # one run
    ]
    out = CP.history_proposals("c1", "main", _Map(), [_Metric("gmv", "SELECT SUM(gmv_eur) AS gmv_eur FROM orders")], _Db(rows))
    assert [p["name"] for p in out] == ["merch_value"]
    p = out[0]
    assert p["source"] == CP.SOURCE_QUERY_HISTORY and p["runs"] == 3 and p["tables"] == ["order_items", "orders"]
    assert p["sql"] == ("SELECT SUM(order_items.quantity * order_items.unit_price_eur) AS merch_value "
                        "FROM order_items JOIN orders ON orders.order_id = order_items.order_id")
    assert "3 runs of the warehouse's own query history" in p["definition"] and "filters are not carried" in p["definition"]
    assert p["label"] == "Merch value" and p["time_kind"] == "flow"


def test_history_proposals_say_nothing_when_the_engine_keeps_none_or_everything_was_ours(monkeypatch):
    from aughor.semantic import coverage_proposals as CP
    from aughor.semantic import metric_coverage as MC
    monkeypatch.setattr(MC, "tables_of", lambda cid, s: [])
    class Duck:
        dialect = "duckdb"
    assert CP.history_proposals("c1", "main", _Map(), [], Duck()) == []
    ours = _Db([HistoryRow("t", f"{SIGNATURE} SELECT SUM(x) AS total FROM t", "lux", calls=900)])
    assert CP.history_proposals("c1", "main", _Map(), [], ours) == []


def test_the_coverage_run_asks_the_organisation_before_reading_the_history():
    from aughor.semantic import coverage_proposals as CP
    src = pathlib.Path(CP.__file__).read_text()
    run_src = src[src.index("def run("):]
    assert 'allows("read_query_history")' in run_src and "history_proposals(" in run_src
    tree = ast.parse(src)
    assert any(isinstance(n, ast.FunctionDef) and n.name == "history_proposals" for n in ast.walk(tree))


def test_the_catalogue_says_where_a_history_proposal_came_from(monkeypatch):
    from aughor.semantic import coverage_proposals as CP
    from aughor.semantic import metric_catalogue as MCat
    monkeypatch.setattr(CP, "stored", lambda cid, s=None: [{
        "name": "merch_value", "label": "Merch value", "source": CP.SOURCE_QUERY_HISTORY, "runs": 3,
        "sql": "SELECT 1", "tables": ["order_items"], "state": CP.STATE_PROPOSED}])
    [entry] = MCat._coverage_entries("c1", "main")
    assert entry.origin == "query_history" and entry.state == MCat.STATE_PROPOSED
    assert entry.why_it_matters == "the warehouse's own query history — computed in 3 runs by someone other than Aughor (Arc NV-7)"


# ── Attention takes no formula ────────────────────────────────────────────────────────────

def test_a_measure_candidate_is_not_staged_in_attention_and_the_answer_says_where_it_goes():
    from aughor.ontology.candidates import Candidate
    from aughor.ontology.models import OntologyGraph
    from aughor.routers.ontology import stage_candidates
    c = Candidate(connection_id="c1", kind="measure", subject="orders", proposal="SUM(gmv_eur)", origin="query_log",
                  source_rank="mined", evidence="computed as `gmv_eur` over orders in 3 of 9 runs", bound=True)
    g = OntologyGraph(connection_id="c1", schema_name="main", schema_fingerprint="fp", table_to_entity={"orders": "Order"})
    out = stage_candidates([c], g, "c-nv7", "main")
    assert out["proposals"] == [] and out["unstageable"][0]["why"].startswith("a formula is proposed and adopted in the Semantic Layer")
