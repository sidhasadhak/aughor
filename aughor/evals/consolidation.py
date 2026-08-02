"""Wave N3 — deterministic evidence for `graph.consolidate`.

**Why this flag needs its own kind of receipt.** Most flags are graduated by sampling: run a
suite twice and refuse the delta if it does not clear a noise floor. L4 added a second kind for
flags whose claim is *exactness* (:mod:`aughor.evals.equivalence`). ``graph.consolidate`` is a
third: its claim is not "answers get better" and not "the output is unchanged" — it is that the
committed artifact **carries more distinct, still-verifiable knowledge in the same node
budget, losslessly**. That is a property of the artifact, decidable without a warehouse, an
LLM, or a single sampled run.

So the evidence splits in two, and both halves are needed:

- **The invariants are proven here, hermetically.** Losslessness, never-picks-a-winner,
  budget, eviction order, and flag-off identity are asserted over synthetic corpora, so the
  receipt does not depend on whatever happens to be in ``data/`` on the day it was run.
- **The magnitude is measured on the real connection** and recorded as the decision's
  before/after (:func:`measured_effect`), because an invariant that holds over a fixture
  proves correctness, not usefulness.

The evaluator, the ``Comparison`` shape and the suite plumbing are L4's, imported rather than
re-derived — a second copy of "expected == observed" is a second place for the two suites to
disagree about what a pass means.

No LLM, no warehouse, no network. The whole suite is arithmetic over finding dicts.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from aughor.evals.equivalence import Comparison, DeterministicEquivalenceEvaluator
from aughor.evals.evaluator import EvalCase, EvalObservation
from aughor.ontology.context_graph_build import MAX_RECEIPT_FINDINGS as CAP
from aughor.ontology.finding_consolidation import consolidate

#: Suite name — looked up by name so creating the suite is idempotent across runs.
SUITE_NAME = "context graph — finding consolidation (N3)"

#: The flag this suite is evidence for.
#: The flag this suite once gated on. HARDWIRED 2026-08-02 — kept as the name the
#: tombstone test asserts is gone, so the deletion cannot be quietly undone.
FLAG = "graph.consolidate"

Scenario = Callable[[], Comparison]
SCENARIOS: dict[str, Scenario] = {}


def scenario(name: str) -> Callable[[Scenario], Scenario]:
    def _register(fn: Scenario) -> Scenario:
        SCENARIOS[name] = fn
        return fn
    return _register


# ── synthetic corpora ────────────────────────────────────────────────────────────

def _finding(fid: str, *, question: str, text: str, sql: str,
             tables: tuple[str, ...] = ("orders",), at: str = "2026-07-20") -> dict:
    return {"id": fid, "text": text, "sql": sql, "tables": list(tables),
            "source": "evidence_ledger", "generated_at": at, "question": question}


def _mixed_corpus() -> list[dict]:
    """One of each shape the real corpus contains, newest first.

    Deliberately includes the two repeat kinds that must NOT be treated alike: a re-run of the
    same query (the data moved) and a different query reaching a different number (a decision
    nobody took).
    """
    return [
        # a plain repeat — same query, same conclusion
        _finding("r1", question="total gmv", text="GMV: 45.4M",
                 sql="SELECT sum(gmv) FROM orders", at="2026-07-25"),
        _finding("r2", question="total gmv", text="GMV: 45.4M",
                 sql="SELECT SUM(o.gmv) FROM shop.orders o", at="2026-07-24"),
        # a re-run over moved data — same query, new number
        _finding("r3", question="total gmv", text="GMV: 44.9M",
                 sql="SELECT sum(gmv) FROM orders", at="2026-07-23"),
        # a genuine disagreement — different query, different number
        _finding("c1", question="order count", text="Count: 50,048",
                 sql="SELECT count(*) FROM orders", at="2026-07-22"),
        _finding("c2", question="order count", text="Count: 30,949",
                 sql="SELECT count(*) FROM orders WHERE status <> 'cancelled'",
                 at="2026-07-21"),
        # grounded in a table that no longer exists
        _finding("s1", question="legacy revenue", text="Revenue: 12.0M",
                 sql="SELECT sum(x) FROM financial_summary", tables=("financial_summary",),
                 at="2026-07-20"),
        # a distinct, live subject
        _finding("d1", question="returns rate", text="Rate: 4.1%",
                 sql="SELECT avg(r) FROM returns", tables=("returns",), at="2026-07-19"),
    ]


_LIVE = {"orders", "returns"}


# ── the invariants ───────────────────────────────────────────────────────────────

@scenario("lossless")
def _lossless() -> Comparison:
    """Every input finding leaves as a survivor, a superseded id, or a contested variant."""
    corpus = _mixed_corpus()
    _, report = consolidate(corpus, live_tables=_LIVE)
    accounted = report.survivors + report.superseded + report.contested_variants
    return Comparison(
        scenario="lossless",
        expected={"accounted_for": len(corpus), "balanced": True},
        observed={"accounted_for": accounted, "balanced": report.balanced},
        oracle="declared (N3: count in == count out)",
        note="nothing may be silently dropped by consolidation",
        detail=report.to_dict(),
    )


@scenario("never_picks_a_winner")
def _never_picks_a_winner() -> Comparison:
    """A genuine disagreement is LABELLED, never resolved by recency.

    The one invariant that stops this module from becoming the thing N1 refuses to be. The
    survivor may carry the newest text, but the losing conclusion must still be readable on
    the node — otherwise the artifact has settled a business question by timestamp.
    """
    survivors, _ = consolidate(_mixed_corpus(), live_tables=_LIVE)
    contested = [s for s in survivors if s.get("contested")]
    alternatives = sorted(v["text"] for s in contested for v in s["contested_variants"])
    return Comparison(
        scenario="never_picks_a_winner",
        expected={"contested_subjects": 1, "alternatives_retained": ["Count: 30,949"]},
        observed={"contested_subjects": len(contested), "alternatives_retained": alternatives},
        oracle="declared (N1: the platform never picks the winner)",
        note="the losing conclusion travels with the survivor",
    )


@scenario("repeat_is_superseded_not_contested")
def _repeat_is_superseded() -> Comparison:
    """A re-run of the SAME query is the data moving, not a decision to take.

    Pinned because the first cut of the detector called 45 of 100 survivors contested by
    comparing headline prose; a suite that let that regress would restore the wolf-crying.
    """
    survivors, report = consolidate(_mixed_corpus(), live_tables=_LIVE)
    gmv = next(s for s in survivors if s["question"] == "total gmv")
    return Comparison(
        scenario="repeat_is_superseded_not_contested",
        expected={"supersedes": 2, "contested": False},
        observed={"supersedes": gmv.get("supersedes"), "contested": bool(gmv.get("contested"))},
        oracle="declared (N3: same query, new number = the data moved)",
        note="a refreshed metric is not a contested decision",
        detail={"contested_subjects": report.contested_subjects},
    )


@scenario("budget_respected")
def _budget_respected() -> Comparison:
    """Consolidation changes WHAT the artifact keeps, never how much."""
    corpus = [_finding(f"f{i}", question=f"q{i}", text=f"N: {i}",
                       sql=f"SELECT {i} FROM orders") for i in range(CAP * 3)]
    survivors, _ = consolidate(corpus, live_tables=_LIVE)
    return Comparison(
        scenario="budget_respected",
        expected={"within_cap": True},
        observed={"within_cap": len(survivors[:CAP]) <= CAP},
        oracle=f"declared (the projection's {CAP}-node budget)",
        note="the diff-readability constraint L1 measured is not negotiable",
    )


@scenario("unverifiable_evicted_first")
def _unverifiable_evicted_first() -> Comparison:
    """When the corpus overflows the budget, what survives is what can still be checked.

    This is the whole point of consolidating BEFORE the cap: a newest-first window evicts by
    accident of timestamp, and the accident was costing the artifact a fifth of its nodes.
    """
    corpus = ([_finding(f"dead{i}", question=f"dq{i}", text=f"N: {i}",
                        sql=f"SELECT {i} FROM gone", tables=("gone",), at="2026-07-25")
               for i in range(CAP)]
              + [_finding(f"live{i}", question=f"lq{i}", text=f"N: {i}",
                          sql=f"SELECT {i} FROM orders", at="2026-07-01")
                 for i in range(CAP)])
    survivors, _ = consolidate(corpus, live_tables=_LIVE)
    kept = survivors[:CAP]
    return Comparison(
        scenario="unverifiable_evicted_first",
        expected={"stale_in_budget": 0, "live_in_budget": CAP},
        observed={"stale_in_budget": sum(1 for s in kept if s.get("stale")),
                  "live_in_budget": sum(1 for s in kept if not s.get("stale"))},
        oracle="declared (N3: stale sorts last so the cap evicts it first)",
        note="the stale findings are older here, so a newest-first window would have kept "
             "them and dropped every live one",
    )


@scenario("stale_is_kept_not_deleted")
def _stale_is_kept() -> Comparison:
    """C1's supersede-not-delete rule: a stale finding is still evidence of what was true."""
    survivors, report = consolidate(
        [_finding("s1", question="legacy", text="R: 12.0M", sql="SELECT 1 FROM gone",
                  tables=("gone",))], live_tables=_LIVE)
    return Comparison(
        scenario="stale_is_kept_not_deleted",
        expected={"survivors": 1, "stale": 1, "balanced": True},
        observed={"survivors": len(survivors), "stale": report.stale,
                  "balanced": report.balanced},
        oracle="declared (C1: supersede, never delete)",
        note="ageing a finding must not remove it",
    )


@scenario("unknown_ontology_expires_nothing")
def _unknown_ontology_expires_nothing() -> Comparison:
    """A failed lookup that expired the whole corpus would be the silent catastrophe."""
    survivors, report = consolidate(_mixed_corpus(), live_tables=None)
    return Comparison(
        scenario="unknown_ontology_expires_nothing",
        expected={"stale": 0, "any_marked": 0},
        observed={"stale": report.stale,
                  "any_marked": sum(1 for s in survivors if s.get("stale"))},
        oracle="declared (N3: unknown marks nothing)",
        note="an unreadable ontology must not age the corpus",
    )


@scenario("flag_off_projection_identical")
def _flag_off_projection_identical() -> Comparison:
    """With the flag off, a finding node's payload is exactly what it was before N3.

    Checked against the projection itself rather than a remembered list, so the claim
    "byte-identical off" is re-derived on every run instead of trusted.
    """
    from aughor.ontology.context_graph import finding_node_data

    plain = _finding("f1", question="q", text="N: 1", sql="SELECT 1 FROM orders")
    consolidated, _ = consolidate(_mixed_corpus(), live_tables=_LIVE)
    contested = next(s for s in consolidated if s.get("contested"))
    return Comparison(
        scenario="flag_off_projection_identical",
        expected={"unconsolidated_keys": ["generated_at", "sql", "tables"],
                  "consolidated_adds_keys": True},
        observed={"unconsolidated_keys": sorted(finding_node_data(plain)),
                  "consolidated_adds_keys": set(finding_node_data(contested)) > {
                      "generated_at", "sql", "tables"}},
        oracle="declared (the pre-N3 finding payload)",
        note="off adds nothing to the artifact; on adds only where consolidation happened",
    )


# ── the measured magnitude (the other half of the receipt) ───────────────────────

def measured_effect(connection_id: str, schema_name: Optional[str] = None) -> dict[str, Any]:
    """Consolidation's before/after on a REAL connection — the decision's evidence payload.

    Read-only and ``persist=False``: measuring whether a rebuild is worth committing must
    never itself commit one. Returns ``{"available": False, ...}`` rather than raising when
    the connection has no ontology or no receipts, so a graduation run on a bare clone
    reports "no evidence" instead of a flattering zero.
    """
    from aughor.ontology.context_graph_build import load_investigation_findings
    from aughor.ontology.finding_consolidation import bare_table, live_tables_for

    try:
        live = live_tables_for(connection_id, schema_name)
        raw = load_investigation_findings(connection_id, limit=CAP)
    except Exception as exc:
        return {"available": False, "reason": f"{type(exc).__name__}: {exc}"}
    if not raw:
        return {"available": False, "reason": "no answer receipts on this connection"}
    if not live:
        return {"available": False, "reason": "no readable ontology — staleness is unknown"}

    def _unverifiable(items: list[dict]) -> int:
        return sum(1 for f in items
                   if (t := {bare_table(x) for x in (f.get("tables") or [])}) and (t - live))

    from aughor.ontology.context_graph_build import CONSOLIDATION_OVERFETCH
    wide = load_investigation_findings(connection_id, limit=CAP * CONSOLIDATION_OVERFETCH)
    survivors, report = consolidate(wide, live_tables=live)
    after = survivors[:CAP]
    return {
        "available": True,
        "connection_id": connection_id,
        "before": {"findings": len(raw),
                   "distinct_conclusions": len({f.get("text") for f in raw}),
                   "unverifiable": _unverifiable(raw)},
        "after": {"findings": len(after),
                  "distinct_conclusions": len({f.get("text") for f in after}),
                  "unverifiable": _unverifiable(after),
                  "contested_labelled": sum(1 for f in after if f.get("contested")),
                  "readings_folded_in": sum(int(f.get("supersedes") or 0) for f in after)},
        "corpus": {"receipts_read": len(wide), "distinct_subjects": report.survivors,
                   "lossless": report.balanced},
    }


# ── the target, suite and graduation ─────────────────────────────────────────────

def consolidation_target() -> Callable[[EvalCase], EvalObservation]:
    """Run the scenario named in ``case.expected["scenario"]``; unknown is an ERROR."""
    def target(case: EvalCase) -> EvalObservation:
        name = str((case.expected or {}).get("scenario") or case.id)
        fn = SCENARIOS.get(name)
        if fn is None:
            return EvalObservation(error=f"unknown consolidation scenario: {name!r}")
        comparison = fn()
        return EvalObservation(narrative=comparison.note, meta=comparison.to_meta())

    return target


def ensure_suite() -> str:
    """Create the suite (idempotent by name) with one case per scenario; return its id."""
    from aughor.evals import store

    existing = next((s for s in store.list_suites(200) if s["name"] == SUITE_NAME), None)
    if existing is None:
        existing = store.create_suite(
            SUITE_NAME,
            description=("Wave N3 — `graph.consolidate` claims the artifact carries more "
                         "distinct, still-verifiable knowledge in the same node budget, "
                         "losslessly. Each case asserts one invariant of that claim over a "
                         "synthetic corpus: no warehouse, no LLM, no dependence on data/."),
            target="consolidation")
    suite_id = existing["id"]

    have = {(c.get("expected") or {}).get("scenario") for c in store.list_cases(suite_id)}
    missing = [n for n in SCENARIOS if n not in have]
    if missing:
        store.add_cases(suite_id, [
            {"question": f"Does {n} hold?", "expected": {"scenario": n},
             "tags": ["n3", "consolidation"]}
            for n in missing
        ])
    return suite_id


def run_suite(*, iterations: int = 1, persist: bool = True):
    """Run every scenario and return the :class:`~aughor.evals.runner.RunSummary`."""
    from aughor.evals import runner
    from aughor.evals.registry import get_evaluator, register_evaluator

    if get_evaluator(DeterministicEquivalenceEvaluator.name) is None:
        register_evaluator(DeterministicEquivalenceEvaluator())

    suite_id = ensure_suite()
    return runner.run_suite(
        suite_id, consolidation_target(), iterations=iterations, persist=persist,
        evaluators=[DeterministicEquivalenceEvaluator.name])
