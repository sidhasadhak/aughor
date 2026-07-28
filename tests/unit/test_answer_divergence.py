"""Wave N1 — detecting the same question answered two different ways.

The three things these tests hold, all of which the live data taught rather than the design:

* **cosmetic variance must not report as divergence.** Schema qualification and alias renames
  produced 3 "different" queries for one COUNT(*) question; a detector that fires on those
  teaches its reader to ignore it.
* **reuse separates a contested decision from open exploration.** Ranking by variant count put
  a 15-variants-over-15-runs exploratory question above a routine metric with an established
  answer and a challenger — exactly backwards.
* **the system must never pick the winner.** Whether cancelled orders count as revenue is a
  business fact; promoting the most common variant would launder popularity into correctness.
"""
from __future__ import annotations

from aughor.semantic import answer_divergence as AD


def _receipt(rid, question, sql, tables=(), at="2026-07-01T00:00:00Z"):
    return {"id": rid, "created_at": at, "kind": "chat_answer",
            "payload": {"question": question, "sql": sql, "tables": list(tables)}}


def _patch_receipts(monkeypatch, rows):
    monkeypatch.setattr(AD, "_receipts", lambda conn, org, limit: list(rows))
    monkeypatch.setattr(AD, "_pinned_question_keys", lambda conn: set())


# ── semantic key: what counts as "the same query" ─────────────────────────────

def test_schema_qualification_and_aliases_are_not_divergence():
    a = "SELECT COUNT(*) AS count FROM luxexperience.returns"
    b = "SELECT COUNT(*) AS row_count FROM returns"
    assert AD.semantic_key(a) == AD.semantic_key(b)


def test_a_real_filter_difference_is_divergence():
    a = "SELECT platform, SUM(gmv_eur) FROM orders GROUP BY platform"
    b = "SELECT platform, SUM(gmv_eur) FROM orders WHERE status <> 'cancelled' GROUP BY platform"
    assert AD.semantic_key(a) != AD.semantic_key(b), \
        "including or excluding cancelled orders is the decision this module exists to surface"


# ── detection ─────────────────────────────────────────────────────────────────

def test_consistent_question_is_not_reported(monkeypatch):
    _patch_receipts(monkeypatch, [
        _receipt("r1", "total gmv", "SELECT SUM(gmv) FROM orders"),
        _receipt("r2", "total gmv", "SELECT SUM(gmv) AS t FROM luxexperience.orders"),
    ])
    assert AD.detect("c1") == []


def test_contested_question_is_reported_with_variants_ranked_by_use(monkeypatch):
    _patch_receipts(monkeypatch, [
        _receipt("r1", "total gmv", "SELECT SUM(gmv) FROM orders"),
        _receipt("r2", "total gmv", "SELECT SUM(gmv) FROM orders"),
        _receipt("r3", "total gmv", "SELECT SUM(gmv) FROM orders WHERE status <> 'cancelled'"),
    ])
    divs = AD.detect("c1")
    assert len(divs) == 1
    d = divs[0]
    assert d.variant_count == 2 and d.run_count == 3
    assert d.top_reuse == 2 and d.contested
    assert d.variants[0].run_count == 2, "the established answer leads"


def test_exploratory_questions_are_excluded_by_default(monkeypatch):
    """Every run unique => being explored, not decided. Asking a reviewer to pin one of
    fifteen one-off queries is asking the wrong question."""
    _patch_receipts(monkeypatch, [
        _receipt(f"r{i}", "why are returns high", f"SELECT {i} FROM returns")
        for i in range(5)
    ])
    assert AD.detect("c1") == []
    loose = AD.detect("c1", include_exploratory=True)
    assert len(loose) == 1 and not loose[0].contested


def test_contested_outranks_exploratory(monkeypatch):
    rows = [_receipt(f"e{i}", "explore me", f"SELECT {i} FROM t") for i in range(9)]
    rows += [_receipt("c1", "decide me", "SELECT SUM(a) FROM t"),
             _receipt("c2", "decide me", "SELECT SUM(a) FROM t"),
             _receipt("c3", "decide me", "SELECT SUM(b) FROM t")]
    _patch_receipts(monkeypatch, rows)
    divs = AD.detect("c1", include_exploratory=True)
    assert divs[0].question == "decide me", \
        "a 3-run contested decision must outrank a 9-variant exploration"


def test_receipts_without_sql_are_ignored(monkeypatch):
    """An abstention concluded nothing to compare — it is a legitimate outcome, not a variant."""
    _patch_receipts(monkeypatch, [
        _receipt("r1", "q", ""), _receipt("r2", "q", ""),
    ])
    assert AD.detect("c1") == []


def test_pinned_questions_drop_out(monkeypatch):
    rows = [_receipt("r1", "total gmv", "SELECT SUM(gmv) FROM orders"),
            _receipt("r2", "total gmv", "SELECT SUM(gmv) FROM orders"),
            _receipt("r3", "total gmv", "SELECT SUM(gmv) FROM orders WHERE ok")]
    monkeypatch.setattr(AD, "_receipts", lambda c, o, l: rows)
    monkeypatch.setattr(AD, "_pinned_question_keys", lambda c: {"total gmv"})
    assert AD.detect("c1") == [], "a settled decision is not re-surfaced"
    assert len(AD.detect("c1", include_settled=True)) == 1


# ── impact: only executed disagreement is real ────────────────────────────────

def test_fingerprint_ignores_column_names_but_not_values():
    """Renaming an output label is not a disagreement about the data. An early version
    hashed column names and reported three identical-number variants as differing."""
    a, _ = AD._result_digest(["sum_gmv"], [[1.0], [2.0]])
    b, _ = AD._result_digest(["total_gmv"], [[1.0], [2.0]])
    c, _ = AD._result_digest(["total_gmv"], [[1.0], [3.0]])
    assert a == b
    assert a != c


def test_fingerprint_is_row_order_insensitive_and_totals_numerics():
    a, ta = AD._result_digest(["x"], [[1.0], [2.0]])
    b, tb = AD._result_digest(["x"], [[2.0], [1.0]])
    assert a == b
    assert ta == tb == 3.0


def test_impact_reports_the_spread_between_answers():
    imp = AD.Impact(question="q", results=[
        AD.VariantResult(key="a", digest="f1", numeric_total=45_437_544.0),
        AD.VariantResult(key="b", digest="f2", numeric_total=43_595_576.0),
    ])
    assert imp.results_differ
    assert round(imp.numeric_spread) == 1_841_968


def test_an_errored_variant_never_silently_counts_as_agreement():
    imp = AD.Impact(question="q", results=[
        AD.VariantResult(key="a", digest="f1", numeric_total=1.0),
        AD.VariantResult(key="b", error="Catalog Error: table gone"),
    ])
    assert not imp.results_differ, "one comparable result is not a disagreement"
    assert imp.numeric_spread is None


# ── pinning: the human decides, and the warrant says so ───────────────────────

def test_pin_records_a_human_warrant_and_is_idempotent(monkeypatch, tmp_path):
    saved: list = []
    monkeypatch.setattr("aughor.semantic.trusted_queries.save_trusted", lambda tq: saved.append(tq))

    tq1 = AD.pin("c1", "total gmv", "SELECT SUM(gmv) FROM orders WHERE status <> 'cancelled'",
                 tables=["orders"], note="cancelled orders are not revenue")
    tq2 = AD.pin("c1", "total gmv", "SELECT SUM(gmv) FROM orders")

    assert AD.HUMAN_TAG in tq1.tags
    assert tq1.id == tq2.id, (
        "content-addressed on the question so a re-pin REPLACES the decision — a store "
        "holding both variants would reintroduce the divergence it exists to end")


def test_the_module_never_picks_a_winner():
    """The public surface offers detection, measurement and an explicit human pin — and
    deliberately no auto-promote. Whether cancelled orders count as revenue is a business
    fact; promoting the most-used variant would launder popularity into correctness."""
    exported = {n for n in dir(AD) if not n.startswith("_")}
    for forbidden in ("auto_pin", "promote", "resolve", "pick_winner", "auto_resolve"):
        assert forbidden not in exported
