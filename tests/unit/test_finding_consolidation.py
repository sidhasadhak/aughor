"""Wave N3 — finding consolidation: fold repeats, age the unreachable, never pick a winner.

Hermetic: consolidation is pure over normalized finding dicts — no DB, no Ledger, no LLM.

These encode the N3 decision gate. The load-bearing one is
:func:`test_contested_repeat_is_not_collapsed`: the study scoped "collapse to the newest",
and measuring the real corpus refused it — 111 of 132 repeated subjects DISAGREE with
themselves, so collapsing by recency would silently settle 84% of them. Recency is not a
warrant (Wave N1).
"""
from __future__ import annotations

from aughor.ontology.finding_consolidation import (
    ConsolidationReport,
    consolidate,
    subject_key,
)


def _f(fid: str, *, question="total gmv by platform", text="GMV is 45M",
       sql="SELECT sum(gmv) FROM orders", tables=("orders",), at="2026-07-20") -> dict:
    return {"id": fid, "text": text, "sql": sql, "tables": list(tables),
            "source": "evidence_ledger", "generated_at": at, "question": question}


# ── subject identity ────────────────────────────────────────────────────────────────

def test_same_question_different_phrasing_is_one_subject():
    """Punctuation and casing are not intent — N1's question_key, not a second copy."""
    a = _f("a", question="Total GMV by platform?")
    b = _f("b", question="total gmv by platform")
    assert subject_key(a) == subject_key(b)


def test_same_question_over_different_tables_is_a_different_subject():
    a = _f("a", tables=("orders",))
    b = _f("b", tables=("order_items",))
    assert subject_key(a) != subject_key(b)


def test_finding_without_a_question_never_groups():
    """Explorer-store findings carry no question; guessing two of them answer the same
    thing because their headlines rhyme is how consolidation starts destroying evidence."""
    a = {"id": "a", "text": "same headline", "tables": []}
    b = {"id": "b", "text": "same headline", "tables": []}
    assert subject_key(a) != subject_key(b)
    survivors, report = consolidate([a, b])
    assert report.survivors == 2
    assert report.superseded == 0


# ── the two kinds of repeat ─────────────────────────────────────────────────────────

def test_identical_repeat_collapses_to_the_newest():
    survivors, report = consolidate([_f("new", at="2026-07-25"), _f("old", at="2026-07-01")])
    assert [s["id"] for s in survivors] == ["new"]
    assert survivors[0]["supersedes"] == 1
    assert survivors[0]["superseded_ids"] == ["old"]
    assert report.superseded == 1
    assert report.contested_subjects == 0


def test_same_query_new_number_is_superseded_not_contested():
    """The data moved. One query, two readings — the newest IS the current one, and
    calling that a contested decision would cry wolf on every refreshed metric."""
    survivors, report = consolidate([
        _f("new", text="GMV is 46M", at="2026-07-25"),
        _f("old", text="GMV is 45M", at="2026-07-01"),
    ])
    assert report.contested_subjects == 0
    assert report.superseded == 1
    assert survivors[0]["id"] == "new"
    assert "contested" not in survivors[0]


def test_contested_repeat_is_not_collapsed():
    """A DIFFERENT query reaching a DIFFERENT conclusion is a decision nobody took.

    The survivor keeps the newest text but SAYS it is unsettled and ships the alternative
    — the artifact must not resolve by timestamp what only a human may settle.
    """
    survivors, report = consolidate([
        _f("new", text="GMV is 45.4M", sql="SELECT sum(gmv) FROM orders", at="2026-07-25"),
        _f("old", text="GMV is 43.6M",
           sql="SELECT sum(gmv) FROM orders WHERE status <> 'cancelled'", at="2026-07-01"),
    ])
    assert len(survivors) == 1
    s = survivors[0]
    assert s["contested"] is True
    assert "supersedes" not in s
    assert [v["id"] for v in s["contested_variants"]] == ["old"]
    # The losing conclusion travels WITH the survivor — not discarded, not promoted.
    assert s["contested_variants"][0]["text"] == "GMV is 43.6M"
    assert report.contested_subjects == 1
    assert report.contested_variants == 1


def test_different_query_same_conclusion_still_collapses():
    """Two routes, one answer — that is not a disagreement worth a human's attention."""
    survivors, report = consolidate([
        _f("new", sql="SELECT sum(gmv) FROM orders", at="2026-07-25"),
        _f("old", sql="SELECT SUM(o.gmv) FROM luxexperience.orders o", at="2026-07-01"),
    ])
    assert report.contested_subjects == 0
    assert report.superseded == 1


# ── nothing is lost ─────────────────────────────────────────────────────────────────

def test_count_in_equals_count_out():
    """The study's gate for N3: survivors + superseded + contested variants == input."""
    findings = [
        _f("a1", question="q1", at="2026-07-25"),
        _f("a2", question="q1", at="2026-07-24"),
        _f("a3", question="q1", text="different", sql="SELECT 1 FROM orders", at="2026-07-23"),
        _f("b1", question="q2", at="2026-07-22"),
        _f("c1", question="q3", at="2026-07-21"),
    ]
    survivors, report = consolidate(findings)
    assert report.findings_in == 5
    assert report.balanced
    assert report.survivors + report.superseded + report.contested_variants == 5
    assert len(survivors) == report.survivors


def test_empty_input_is_balanced():
    survivors, report = consolidate([])
    assert survivors == []
    assert report.balanced


def test_unbalanced_report_is_detectable():
    """The guard the build path checks — a lossy report must read as unbalanced."""
    assert not ConsolidationReport(findings_in=5, survivors=2, superseded=1).balanced


def test_input_findings_are_not_mutated():
    original = _f("a")
    snapshot = dict(original)
    consolidate([original, _f("b", at="2026-07-01")])
    assert original == snapshot


# ── staleness is reachability ───────────────────────────────────────────────────────

def test_finding_grounded_in_a_vanished_table_is_stale():
    survivors, report = consolidate([_f("a", tables=("financial_summary",))],
                                    live_tables={"orders", "returns"})
    assert survivors[0]["stale"] is True
    assert "financial_summary" in survivors[0]["stale_reason"]
    assert report.stale == 1


def test_stale_findings_sort_last_so_the_cap_evicts_them_first():
    """The whole point of consolidating before the cap: a bounded slice keeps what can
    still be verified."""
    survivors, _ = consolidate(
        [_f("dead", question="q1", tables=("gone_table",)),
         _f("live", question="q2", tables=("orders",))],
        live_tables={"orders"})
    assert [s["id"] for s in survivors] == ["live", "dead"]


def test_stale_findings_are_kept_never_deleted():
    """C1's supersede-not-delete rule — a stale finding is still evidence of what was
    once true."""
    survivors, report = consolidate([_f("a", tables=("gone",))], live_tables={"orders"})
    assert len(survivors) == 1
    assert report.balanced


def test_unknown_ontology_marks_nothing_stale():
    """A failed lookup that expires the whole corpus is the silent-catastrophe shape."""
    survivors, report = consolidate([_f("a", tables=("anything",))], live_tables=None)
    assert report.stale == 0
    assert "stale" not in survivors[0]


def test_finding_without_tables_is_never_stale():
    survivors, report = consolidate([_f("a", tables=())], live_tables={"orders"})
    assert report.stale == 0
    assert "stale" not in survivors[0]


# ── the build wiring: off is byte-identical, on consolidates before the cap ─────────

def _wire(monkeypatch, *, on: bool, calls: list):
    """Point the build path's loader at a spy and set the N3 flag."""
    from aughor.ontology import context_graph_build as build_mod

    def _loader(conn, org=None, *, limit=None):
        calls.append(limit)
        return [_f(f"r{i}", question=f"q{i % 3}", at=f"2026-07-{20 - i % 3:02d}")
                for i in range(20)]

    monkeypatch.setattr(build_mod, "load_investigation_findings", _loader)
    monkeypatch.setattr(build_mod, "flag_enabled",
                        lambda name: on if name == "graph.consolidate" else False)
    return build_mod


def test_flag_off_reads_exactly_as_before(monkeypatch):
    """Byte-identical: the previous call, cap and all — no over-fetch, no consolidation."""
    calls: list = []
    build_mod = _wire(monkeypatch, on=False, calls=calls)
    out = build_mod._consolidated_investigation_findings("c1", "org1", None)
    assert calls == [None]                       # the loader's own default cap
    assert len(out) == 20                        # untouched
    assert all("supersedes" not in f and "stale" not in f for f in out)


def test_flag_on_overfetches_and_consolidates(monkeypatch):
    """Consolidation only pays off if it can see the repeats, and they live behind the cap."""
    calls: list = []
    build_mod = _wire(monkeypatch, on=True, calls=calls)
    out = build_mod._consolidated_investigation_findings("c1", "org1", None)
    assert calls == [build_mod.MAX_RECEIPT_FINDINGS * build_mod.CONSOLIDATION_OVERFETCH]
    assert len(out) == 3                         # 20 receipts over 3 distinct questions
    assert sum(f.get("supersedes", 0) for f in out) == 17


def test_flag_on_still_honours_the_cap(monkeypatch):
    """The artifact's size budget is not negotiable — consolidation changes WHAT it keeps."""
    from aughor.ontology import context_graph_build as build_mod

    monkeypatch.setattr(build_mod, "load_investigation_findings",
                        lambda c, o=None, *, limit=None: [
                            _f(f"r{i}", question=f"q{i}") for i in range(500)])
    monkeypatch.setattr(build_mod, "flag_enabled",
                        lambda name: name == "graph.consolidate")
    out = build_mod._consolidated_investigation_findings("c1", "org1", None)
    assert len(out) == build_mod.MAX_RECEIPT_FINDINGS


def test_projection_omits_consolidation_keys_when_absent():
    """A graph built with the flag off serializes exactly as it did before N3."""
    from aughor.ontology.context_graph import finding_node_data

    assert set(finding_node_data(_f("a"))) == {"sql", "tables", "generated_at"}


def test_projection_carries_contested_variants_into_the_node():
    """A node that survived a disagreement has to say so in the committed artifact."""
    from aughor.ontology.context_graph import finding_node_data

    survivors, _ = consolidate([
        _f("new", text="45.4M", sql="SELECT sum(gmv) FROM orders"),
        _f("old", text="43.6M", sql="SELECT sum(gmv) FROM orders WHERE ok", at="2026-07-01"),
    ])
    data = finding_node_data(survivors[0])
    assert data["contested"] is True
    assert data["contested_variants"][0]["text"] == "43.6M"


# ── conclusions are compared on what they ASSERT, not how they are worded ───────────

def test_rephrased_title_is_not_a_disagreement():
    """The wolf-crying case: the first cut flagged 45 of 100 survivors as contested, and
    reading them showed the receipt headline is usually a TITLE, not a conclusion."""
    survivors, report = consolidate([
        _f("new", text="Total sales by product category",
           sql="SELECT cat, sum(x) FROM orders", at="2026-07-25"),
        _f("old", text="Total sales (EUR) by product category",
           sql="SELECT cat, SUM(y) FROM orders GROUP BY 1", at="2026-07-01"),
    ])
    assert report.contested_subjects == 0
    assert report.superseded == 1
    assert survivors[0]["id"] == "new"


def test_conflicting_numbers_are_a_disagreement():
    """What survives rephrasing is the arithmetic."""
    _, report = consolidate([
        _f("new", text="Count: 50,048", sql="SELECT count(*) FROM orders", at="2026-07-25"),
        _f("old", text="Count: 30,949",
           sql="SELECT count(*) FROM orders WHERE ok", at="2026-07-01"),
    ])
    assert report.contested_subjects == 1


def test_thousands_separators_do_not_fake_a_disagreement():
    _, report = consolidate([
        _f("new", text="Count: 50,048", sql="SELECT count(*) FROM orders", at="2026-07-25"),
        _f("old", text="Count: 50048",
           sql="SELECT count(*) FROM orders GROUP BY 1", at="2026-07-01"),
    ])
    assert report.contested_subjects == 0
