"""The standalone Verifier node — the ADA specialist that owns the deterministic trust
verdict (fan-out / id-arithmetic detection + R3 typed failure classes). Hermetic."""
from __future__ import annotations

from aughor.agent.verifier import FANOUT_CAVEAT, Verifier, VerifierVerdict


class _Q:
    def __init__(self, title, sql): self.title, self.sql = title, sql


class _R:
    def __init__(self, sql, error=None, row_count=0):
        self.sql, self.error, self.row_count = sql, error, row_count


_TCOLS = {
    "orders": ["order_id", "customer_id", "order_value", "order_status"],
    "order_items": ["order_id", "order_item_id", "unit_price", "unit_cost"],
}


def test_scan_detects_id_arithmetic():
    qs = [_Q("x", "SELECT SUM(unit_price * order_item_id) FROM order_items")]
    hits = Verifier.scan(qs, _TCOLS, "duckdb")
    assert hits and "id" in hits[0].lower()


def test_scan_chasm_fanout_is_cardinality_gated():
    # The chasm detectors (sum/avg/count-over-chasm) need a runtime uniqueness oracle to
    # confirm the join multiplies rows; with only static column metadata they conservatively
    # don't fire — the live ADA path supplies the oracle (see the fanout suite). Asserting the
    # static contract here so the Verifier's behavior is explicit, not surprising.
    qs = [_Q("rev", "SELECT SUM(o.order_value) FROM orders o "
                    "JOIN order_items oi ON o.order_id = oi.order_id")]
    assert Verifier.scan(qs, _TCOLS, "duckdb") == []   # cardinality-gated, not a static hit


def test_scan_clean_query_is_empty():
    assert Verifier.scan([_Q("x", "SELECT SUM(unit_price) FROM order_items")], _TCOLS, "duckdb") == []


def test_scan_dedupes_repeated_hits():
    q = _Q("x", "SELECT SUM(unit_price * order_item_id) FROM order_items")
    assert len(Verifier.scan([q, q], _TCOLS, "duckdb")) == 1


def test_classify_failures_gives_typed_classes():
    results = [
        (_Q("missing", "SELECT bad FROM t"),
         _R("SELECT bad FROM t", error='Binder Error: Referenced column "bad" not found')),
        (_Q("ok", "SELECT 1"), _R("SELECT 1", row_count=1)),
        (_Q("syntax", "SELEC 1"), _R("SELEC 1", error='Parser Error: syntax error at or near "SELEC"')),
    ]
    cls = dict(Verifier.classify_failures(results, "duckdb"))
    assert cls["missing"] == "binder"
    assert cls["syntax"] == "parser"
    assert "ok" not in cls            # a successful query has no error class


def test_verdict_combines_hits_caveat_and_pass():
    qs = [_Q("a", "SELECT SUM(unit_price * order_item_id) FROM order_items")]
    results = [(qs[0], _R("...", row_count=3))]
    v: VerifierVerdict = Verifier.verdict(qs, results, table_cols=_TCOLS, dialect="duckdb",
                                          fanout_caveat=FANOUT_CAVEAT)
    assert v.fanout_hits and v.passed and FANOUT_CAVEAT in v.caveats
    # all-failed → not passed
    v2 = Verifier.verdict([], [(_Q("z", "x"), _R("x", error="boom"))], table_cols=_TCOLS, dialect="duckdb")
    assert not v2.passed and v2.error_classes
