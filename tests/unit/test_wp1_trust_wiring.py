"""WP-1 (platform review 2026-07-12) — trust-plane wiring.

(1c) Model-generated and stored-SQL labels are AUDITED data activity: the AST
     mutation gate runs for `__agent_eval_ref__` / `__agent_eval_gen__` /
     `__brief_metric_move__` / `__ground__` — previously the "any dunder is
     internal" rule silently exempted them, so model-generated evaluation SQL
     never met the read-only gate.
(1d) The engine read-only posture is a RECORDED fact (`engine_read_only`),
     never silent: local DuckDB = True, base/unknown connector = None.
(1a) Live guard caveats from `execute_guarded` reach the ADA finding's
     `trust_caveat` — which the existing `_cap_confidence_on_trust_advisory`
     turns into a HIGH→MEDIUM confidence cap.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import duckdb

from aughor.db.connection import (
    _AUDITED_AGENT_LABELS,
    DatabaseConnection,
    DuckDBConnection,
    _is_internal_query,
)
from aughor.platform.contracts.execution import QueryResult


def _conn():
    conn = DuckDBConnection.__new__(DuckDBConnection)
    conn._path = Path(":memory:")
    conn._conn = duckdb.connect(":memory:")
    conn._connection_id = "wp1"
    conn._schema_name = None
    conn._conn.execute("CREATE TABLE t (id INT, v INT)")
    conn._conn.execute("INSERT INTO t VALUES (1, 10), (2, 20)")
    return conn


# ── 1c: the four labels are gated ─────────────────────────────────────────────

def test_eval_and_stored_sql_labels_are_audited():
    for label in ("__agent_eval_ref__", "__agent_eval_gen__",
                  "__brief_metric_move__", "__ground__"):
        assert label in _AUDITED_AGENT_LABELS
        assert not _is_internal_query(label), label


def test_generated_eval_sql_ast_only_vector_is_blocked():
    """THE case 1c exists for: `SELECT … INTO` passes the keyword screen (first
    token SELECT, no forbidden keyword), so with the gate skipped it previously
    reached the engine — on this read-write test handle it would have CREATED a
    table. The AST gate (now run for this label) blocks it."""
    conn = _conn()
    r = conn.execute("__agent_eval_gen__", "SELECT * INTO t2 FROM t")
    assert r.error and "BLOCKED" in r.error, r.error
    # And the mutation genuinely did not happen.
    names = [x[0] for x in conn._conn.execute(
        "SELECT table_name FROM information_schema.tables").fetchall()]
    assert "t2" not in names


def test_keyword_mutations_still_blocked_under_audited_labels():
    # The keyword screen remains the first line for classic verbs.
    for label, sql in (("__agent_eval_gen__", "DELETE FROM t"),
                       ("__agent_eval_ref__", "UPDATE t SET v = 0"),
                       ("__ground__", "DROP TABLE t")):
        r = _conn().execute(label, sql)
        assert r.error, (label, sql)


def test_plain_select_still_passes_under_audited_labels():
    r = _conn().execute("__agent_eval_gen__", "SELECT COUNT(*) AS n FROM t")
    assert r.error is None
    # NB: the audited path stringifies row values (PII scan) — compare as str,
    # the same contract the explorer/monitor labels already live with.
    assert str(r.rows[0][0]) == "2"


def test_true_internal_plumbing_labels_remain_exempt():
    # The platform's own plumbing (e.g. `alter_column`, `__catalog__`) must keep
    # its exemption — a blanket "gate every dunder" would block legitimate
    # platform-authored DDL. Only genuine data-activity labels are audited.
    assert _is_internal_query("__catalog__")
    assert _is_internal_query("alter_column")


# ── 1d: engine read-only posture is recorded ──────────────────────────────────

def test_local_duckdb_records_engine_read_only(tmp_path):
    p = tmp_path / "loc.duckdb"
    duckdb.connect(str(p)).close()  # create the file first (read-only open needs it)
    c = DuckDBConnection(p)
    assert c.engine_read_only is True


def test_base_connector_posture_is_unknown_not_assumed():
    assert DatabaseConnection.engine_read_only is None


# ── 1a: live caveats reach the ADA trust_caveat ───────────────────────────────

def test_live_caveats_reach_trust_caveat():
    from aughor.agent.investigate import _assemble_phase_findings

    q = SimpleNamespace(title="metric by region", chart_type="bar",
                        sql="SELECT region, SUM(x) AS x FROM t GROUP BY region")
    r = QueryResult(
        hypothesis_id="ph_0",
        sql="SELECT region, SUM(x) AS x FROM t GROUP BY region",
        columns=["region", "x"], rows=[["EU", 1], ["US", 2]], row_count=2,
        caveats=["join guard: orders.cust ↔ campaigns.id share only 0% of "
                 "sampled values — the join may be unreliable"],
    )
    out = _assemble_phase_findings([(q, r)], [], "ph")
    assert out
    assert "join guard" in (out[0]["trust_caveat"] or ""), out[0]["trust_caveat"]


def test_no_caveats_leaves_trust_caveat_untouched():
    from aughor.agent.investigate import _assemble_phase_findings

    q = SimpleNamespace(title="metric by region", chart_type="bar",
                        sql="SELECT region, SUM(x) AS x FROM t GROUP BY region")
    r = QueryResult(
        hypothesis_id="ph_0",
        sql="SELECT region, SUM(x) AS x FROM t GROUP BY region",
        columns=["region", "x"], rows=[["EU", 1], ["US", 2]], row_count=2,
    )
    out = _assemble_phase_findings([(q, r)], [], "ph")
    assert out
    # verify_insight may or may not flag independently; the merge itself must not
    # invent a caveat when the executor reported none.
    assert "join guard" not in (out[0]["trust_caveat"] or "")
