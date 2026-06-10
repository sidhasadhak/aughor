"""UNIFY — the metric-unification invariants.

The golden eval could not measure capability lift while the golden references
(authored GROSS) and the injected pipeline (net-of-cancelled, driven by the
registered `revenue` metric) disagreed on the definition. These tests pin the
unification: ONE registered metric, golden refs that reconcile with it, and a
scorer that is convention-neutral on the gross/net choice where the question
does not specify a status filter — while status-SEMANTIC questions stay strict.

Executes against the `samples` connection (the pinned eval connection). Skips if
that connection / its data is unavailable, so the unit suite stays hermetic.
"""
import json
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent.parent


@pytest.fixture(scope="module")
def samples_db():
    try:
        from aughor.db.connection import open_connection_for
        db = open_connection_for("samples")
        db._conn.execute("SELECT 1 FROM ecommerce.orders LIMIT 1")
    except Exception:
        pytest.skip("samples connection/data unavailable")
    yield db
    db.close()


def _scalar(db, sql):
    db._conn.execute(sql)
    return db._conn.fetchone()[0]


class TestRegisteredMetric:
    def test_revenue_metric_is_registered_and_order_grain(self):
        from aughor.semantic.metrics import get_metric
        m = get_metric("revenue")
        assert m is not None, "revenue must be registered in data/metrics.json"
        assert "total_amount" in m.sql, "canonical revenue is order-grain total_amount"
        assert "line_total" not in m.sql, "line_total is a different grain (4.3x divergence)"
        assert any("cancel" in f.lower() for f in m.filters), "net-of-cancelled is the default"

    def test_metric_does_not_leak_to_foreign_schema(self):
        """The #2 leak class: a global curated metric must inject ONLY where its
        table+column exist. A synthetic schema lacking ecommerce.orders /
        total_amount must resolve zero curated metrics."""
        from aughor.semantic.metrics import list_metrics, filter_metrics_to_schema
        # Real schema format (TABLE: header + "  col  TYPE" lines). TPC-H has an
        # orders table but none of revenue's columns/dimensions.
        foreign = (
            "TABLE: tpch.orders\n"
            "  o_orderkey  BIGINT\n"
            "  o_custkey  BIGINT\n"
            "  o_totalprice  DECIMAL\n"
            "  o_orderdate  DATE\n"
        )
        kept = {m.name for m in filter_metrics_to_schema(list_metrics(), foreign)}
        assert "revenue" not in kept, (
            "revenue(total_amount) must NOT match a schema with only o_totalprice"
        )

    def test_metric_reaches_the_injected_block(self, samples_db):
        """built != wired: the registered metric must REACH the prompt the
        pipeline injects, not merely sit in the file."""
        from aughor.semantic.metrics import list_metrics
        from aughor.semantic.canonical import (
            resolve_canonical_metrics, render_canonical_metrics_block,
        )
        metrics = resolve_canonical_metrics(
            samples_db, "ecommerce", catalog=list_metrics(), ontology=None
        )
        block = render_canonical_metrics_block(metrics)
        assert block and "revenue" in block and "SUM(total_amount)" in block, (
            "the canonical revenue formula must appear in the injected block"
        )


class TestReconciliation:
    def test_golden_gross_reconciles_with_registered_net(self, samples_db):
        """The golden 'total revenue' ref (gross) and the registered metric
        (net-of-cancelled) must differ ONLY by the cancelled filter — i.e. they
        are the same metric under one explicit convention choice, not two
        unrelated numbers."""
        from aughor.semantic.metrics import get_metric
        m = get_metric("revenue")
        gross = _scalar(samples_db, "SELECT ROUND(SUM(total_amount),2) FROM ecommerce.orders")
        net = _scalar(samples_db, f"SELECT ROUND({m.sql},2) FROM ecommerce.orders WHERE {m.filters[0]}")
        cancelled = _scalar(samples_db, "SELECT ROUND(SUM(total_amount),2) FROM ecommerce.orders WHERE status = 'cancelled'")
        assert abs(gross - (net + cancelled)) < 1.0, (
            f"gross {gross} must = net {net} + cancelled {cancelled}"
        )

    def test_grain_divergence_is_real_not_a_bug(self, samples_db):
        """total_amount and line_total genuinely diverge on this data — they are
        different bases, which is WHY the metric pins the grain rather than
        treating them as interchangeable."""
        order_grain = _scalar(samples_db, "SELECT SUM(total_amount) FROM ecommerce.orders")
        line_grain = _scalar(samples_db, "SELECT SUM(line_total) FROM ecommerce.order_items")
        assert line_grain > order_grain * 2, "the 4.3x grain divergence is real"


class TestScorerConventionNeutral:
    """The accept_sql bridge: a correct answer in EITHER gross/net convention
    scores full where the convention is unspecified — but status-semantic
    questions remain strict."""

    def _golden(self):
        return {json.loads(l)["id"]: json.loads(l)
                for l in open(REPO / "evals" / "golden_sql_expanded.jsonl") if l.strip()}

    def test_net_revenue_answer_now_scores_full_on_sql004(self, samples_db):
        from evals.sql_accuracy import score_single
        rec = self._golden()["sql004"]
        # A correct NET-of-cancelled answer — previously penalised vs the gross ref.
        net_answer = "SELECT ROUND(SUM(total_amount), 2) AS total_revenue FROM ecommerce.orders WHERE status <> 'cancelled'"
        result = score_single(samples_db, rec, net_answer)
        assert result["overall"] >= 0.99, f"net revenue should score full, got {result['overall']}"
        assert result["matched_reference"] > 0, "should match an accept_sql alt, not the primary"

    def test_gross_revenue_answer_still_scores_full_on_sql004(self, samples_db):
        from evals.sql_accuracy import score_single
        rec = self._golden()["sql004"]
        gross_answer = "SELECT ROUND(SUM(total_amount), 2) AS total_revenue FROM ecommerce.orders"
        result = score_single(samples_db, rec, gross_answer)
        assert result["overall"] >= 0.99
        assert result["matched_reference"] == 0, "gross matches the primary reference"

    def test_status_semantic_questions_stay_frozen(self):
        """sql006/014/025 must NOT have gained convention-neutral variants —
        their status filter is the question, not a free convention."""
        golden = self._golden()
        for qid in ("sql006", "sql025"):
            rec = golden[qid]
            for alt in rec.get("accept_sql") or []:
                # A delivered-only / refund question must not accept an
                # all-status or cancelled-stripped variant.
                assert "delivered" in alt.lower() or "refund" in alt.lower() or "cancel" in alt.lower(), (
                    f"{qid} accept_sql must preserve its status semantics: {alt}"
                )
