"""JD-4 — the instrument, and it comes first.

Arc JD's battery, adopted from `jevlike/eval.py`: **top-1**, **expected calibration error over
ten bins**, and the **shuffled-context control** — every question paired with the WRONG state, on
the rule that a judgment must beat that control to count.

**The first thing an instrument owes you is an honest "cannot measure".** Run against the live
corpus on 2026-09-20 this battery reports all three as UNAVAILABLE, each with its own reason, and
that is the finding rather than a failure to produce one. A number emitted here would be a number
somebody schedules work against:

* **top-1** needs a reference the choice can be wrong against. `outcome` is the only candidate
  and it is ``ok`` on all 58 rows — the constant A1 was built to break, still constant because
  no decision has been recorded since A1's code reached this machine. Accuracy against a corpus
  with no negatives is 100% by construction.
* **ECE** needs a probability per prediction and there is none: ``confidence`` is 0.0 on all 58,
  which `decisions.py` defines as "the decider offers none". Ten bins over 58 zeros is not a
  calibration number, it is a divide-by-zero wearing one. The reason is per-SITE and the three
  differ — see :data:`ECE_REASONS`.
* **the shuffled-context control** is blocked on FIDELITY, not on cost. One replay is a single
  call at the existing seam (`llm/provider.py: complete_with_tools`), ~2.6-9k prompt tokens, and
  both arms over 58 rows would be ~0.47M — affordable. But the prompt the decider actually saw
  is not recoverable: 44 of 58 rows are mid-loop (``step >= 2``), the tool-result history is
  persisted nowhere, and even the 14 first-turn rows never recorded their system prompt. A
  "replay" would be asking a different question than the one logged, and a control that asks a
  different question measures nothing.

**What IS computable, free, and worth having today** is the floor the control must beat. The
choice distribution is skewed — ``run_sql`` is 44.8% of 58 — so a shuffled arm agreeing with the
real choice at ~45% has demonstrated nothing; it has reproduced the prior. Random over an
11-entry menu would be 9.1%. Reporting that floor now is what stops a future control run from
being read as a pass.

This harness makes NO model call and opens no warehouse, like its two siblings
(`decision_yield_eval.py`, `intake_validity_eval.py`). Every number below is counted from the
store.

Usage:

    uv run python evals/judgment_battery_eval.py \\
        --db data/decisions.db --output evals/judgment_battery_results.json

The falsifier is JD-4's own and is stated in :func:`summarize`: if the real and shuffled arms
score within the noise floor, the judgments are not reading the state and the rest of Arc JD is
pointless. It is **not evaluable** on this corpus, so the run reports ``inconclusive`` rather
than letting an unrunnable control read as a pass.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

#: The three registered decision sites, in the order they run on a deep turn — named so a site
#: that stops recording shows up as a zero row rather than vanishing from the table.
SITES = ("ask.route", "framing.definition", "converse.tool", "analyst.tool")

#: Ten bins, as the battery specifies. Named rather than inlined because a battery whose bin
#: count drifts between runs is not comparable with itself.
ECE_BINS = 10

#: Why a site has no probability to calibrate. THREE sites, THREE causes — a single global
#: string would be wrong for two of them, and "no probability here" reads as the same defect
#: whether the decider cannot produce one or the platform simply has not run that path.
ECE_REASONS = {
    "converse.tool": (
        "no probability is produced at this seam: the tool-calling path returns a function "
        "call, the model is never asked for a number (`agent/tool_loop.py`), and the request "
        "does not ask the wire for one (`llm/provider.py`; `logprobs` appears nowhere in the "
        "tree). This is 'never produced', not 'produced and dropped'."),
    "ask.route": (
        "a probability exists and IS recorded at this site (`agent/nodes.py`); this deployment "
        "has produced no rows here. A traffic gap, not a confidence gap."),
    "analyst.tool": (
        "same seam and same cause as `converse.tool` — a different roster (11 tools, no "
        "`delegate_task`) and a system prompt carrying the resolved spec, but the same "
        "tool-calling path that returns a function call and is never asked for a number."),
    "framing.definition": (
        "a probability exists behind the flag `framing.choice_confidence`, whose ON arm has "
        "never executed here; the population is empty."),
}

#: ⚠️ Rows written before 2026-09-21 carry `converse.tool` for BOTH tool-loop callers, because
#: the site was a hardcoded literal in `agent/tool_loop.py`. On the live corpus that is 46 of 58
#: rows (79%) that are really `analyst.tool`. They are discriminable after the fact only by
#: roster size — the converse menu carries `delegate_task`, the analyst menu does not — and this
#: battery does NOT rewrite them: a corpus that silently relabels its own history cannot be
#: compared with a reading taken before the relabel. Segment by site with that date in mind.
MISLABELLED_BEFORE = "2026-09-21"

_UNKNOWN_SITE_REASON = "no rows, and this site is not one the battery has a recorded cause for"


@dataclass(frozen=True)
class Measure:
    """One battery reading, or the reason there isn't one.

    ``available=False`` with an empty ``reason`` is refused at construction, and so is
    ``available=True`` with no value. The whole point of this class is that "measured, and it
    is 0.0" and "could not measure" must never be the same bytes on the wire — that collapse
    is how a metric nobody could compute ends up scheduling somebody's work.
    """

    name: str
    available: bool
    value: Optional[float] = None
    reason: str = ""
    detail: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.available and not self.reason.strip():
            raise ValueError(f"{self.name}: an unavailable measure must carry its reason")
        if self.available and self.value is None:
            raise ValueError(f"{self.name}: an available measure must carry its value")

    def as_dict(self) -> dict:
        return {"name": self.name, "available": self.available, "value": self.value,
                "reason": self.reason, "detail": dict(self.detail)}


# ── Loading ───────────────────────────────────────────────────────────────────

def load_rows(db_path: Path) -> tuple[list[dict], dict]:
    """Every row, through the store's OWN reader, with truncation reported rather than hidden.

    Pointed at the store by env because `resolve_db_path` is the single seam that decides where
    a store lives; a second path resolution here would be a second definition of "the decisions
    store", and those drift. (The same reasoning as `decision_yield_eval.load_yield`.)

    `list_decisions` caps its limit at 500 internally. At 58 rows that is invisible, which is
    exactly why it is checked: a battery that silently measured 500 of 5,000 rows would report a
    confident number about a sample nobody chose. The totals come from `site_stats`, which
    counts rather than lists.
    """
    os.environ["AUGHOR_DECISIONS_DB"] = str(db_path)
    # 🔴 And redirect every OTHER store too, BEFORE importing anything from `aughor`.
    # Pointing `AUGHOR_DECISIONS_DB` alone is not enough: `resolve_db_path` resolves every other
    # store relative to `AUGHOR_STATE_DIR`, so a harness run from the repo with a server live
    # maps into the same `data/` WAL indexes. The platform's own guard says what that costs —
    # "two processes mapped into one SQLite WAL index is the precondition for the SIGBUS in
    # walFindFrame that has killed this app repeatedly — a read-only connection counts, because
    # it maps the -shm too" — and it fired on the first run of this file, with an API serving.
    # `setdefault`, so an operator who has deliberately pointed the state dir keeps their choice.
    # Same discipline as `scripts/dump_openapi.py`: isolate before the import, not after.
    if not os.environ.get("AUGHOR_STATE_DIR"):
        import tempfile
        os.environ["AUGHOR_STATE_DIR"] = tempfile.mkdtemp(prefix="aughor-jd4-battery-")
    from aughor.learning import decisions

    stats = decisions.site_stats() or {}
    rows: list[dict] = []
    for site in sorted(set(SITES) | set(stats)):
        rows.extend(decisions.list_decisions(site=site, limit=500))

    counted = sum(int((stats.get(s) or {}).get("total", 0)) for s in stats)
    truncation = {
        "rows_listed": len(rows),
        "rows_counted": counted,
        "truncated": counted > len(rows),
        "note": ("`list_decisions` caps at 500 per site; the battery read fewer rows than the "
                 "store counts, so every reading below is over a SAMPLE"
                 if counted > len(rows) else ""),
    }
    return rows, truncation


# ── The three readings ────────────────────────────────────────────────────────

def top1(rows: Sequence[Mapping[str, Any]]) -> Measure:
    """Top-1 accuracy — and why it is usually not available here.

    Accuracy needs a reference the choice can be WRONG against. The only candidate this store
    carries is ``outcome``, and a label that never takes its other value is a constant: scoring
    against it returns 1.0 for any corpus whatsoever, which is the shape A1 exists to break.
    """
    scored = [r for r in rows if str(r.get("outcome") or "")]
    if not scored:
        return Measure("top1", False,
                       reason="no row carries an outcome, so there is nothing to be right or "
                              "wrong against",
                       detail={"scored": 0, "total": len(rows)})
    values = {str(r.get("outcome")) for r in scored}
    if len(values) < 2:
        only = next(iter(values))
        return Measure(
            "top1", False,
            reason=(f"`outcome` is {only!r} on all {len(scored)} scored rows — a label that "
                    "never takes its other value is a constant, and accuracy against a "
                    "constant is 1.0 for any corpus"),
            detail={"scored": len(scored), "distinct_outcomes": sorted(values)})
    good = sum(1 for r in scored if str(r.get("outcome")) in ("ok", "accepted"))
    return Measure("top1", True, value=good / len(scored),
                   detail={"scored": len(scored), "correct": good,
                           "distinct_outcomes": sorted(values)})


def ece(rows: Sequence[Mapping[str, Any]], *, bins: int = ECE_BINS) -> Measure:
    """Expected calibration error over ``bins`` equal-width bins.

    Unavailable when no row carries a probability. ``confidence`` defaults to 0.0 and
    `decisions.py` documents that as "the decider offers none", so a store of zeros is an
    ABSENCE of probabilities and not a store of confidently-wrong ones. Treating those zeros as
    data would produce a large, meaningless ECE and a reader would act on it.
    """
    withprob = [r for r in rows if float(r.get("confidence") or 0.0) > 0.0]
    if not withprob:
        by_site = Counter(str(r.get("site") or "?") for r in rows)
        reasons = {s: ECE_REASONS.get(s, _UNKNOWN_SITE_REASON) for s in sorted(set(by_site) | set(SITES))}
        return Measure(
            "ece", False,
            reason=("no decision carries a probability, so there is nothing to calibrate; the "
                    "cause differs per site — see detail.per_site"),
            detail={"rows": len(rows), "with_probability": 0, "bins": bins,
                    "rows_by_site": dict(by_site), "per_site": reasons})

    scored = [r for r in withprob if str(r.get("outcome") or "")]
    if not scored:
        return Measure("ece", False,
                       reason=(f"{len(withprob)} row(s) carry a probability but none carries an "
                               "outcome, so no probability can be compared to what happened"),
                       detail={"with_probability": len(withprob), "bins": bins})

    # Equal-width bins over [0, 1]; a probability of exactly 1.0 belongs in the last bin.
    buckets: list[list[tuple[float, int]]] = [[] for _ in range(bins)]
    for r in scored:
        p = min(max(float(r.get("confidence") or 0.0), 0.0), 1.0)
        hit = 1 if str(r.get("outcome")) in ("ok", "accepted") else 0
        buckets[min(int(p * bins), bins - 1)].append((p, hit))

    total, err = len(scored), 0.0
    occupied = 0
    for b in buckets:
        if not b:
            continue
        occupied += 1
        conf = sum(p for p, _ in b) / len(b)
        acc = sum(h for _, h in b) / len(b)
        err += (len(b) / total) * abs(acc - conf)
    return Measure("ece", True, value=err,
                   detail={"scored": total, "bins": bins, "occupied_bins": occupied})


def choice_prior(rows: Sequence[Mapping[str, Any]]) -> Measure:
    """The majority-class rate — the floor any shuffled-context control must beat.

    Free, and the one reading that always has signal. If the shuffled arm agrees with the real
    choice at about this rate it has reproduced the prior, not read the state, and JD-4's
    falsifier fires. Reporting it BEFORE any control runs is what stops the control's number
    from being read as a pass.
    """
    chosen = [str(r.get("chosen") or "") for r in rows if str(r.get("chosen") or "")]
    if not chosen:
        return Measure("choice_prior", False,
                       reason="no row records what was chosen",
                       detail={"rows": len(rows)})
    counts = Counter(chosen)
    top, n = counts.most_common(1)[0]
    menus = {len(r.get("options") or []) for r in rows if r.get("options")}
    uniform = (1.0 / max(menus)) if menus else None
    return Measure(
        "choice_prior", True, value=n / len(chosen),
        detail={"majority_choice": top, "majority_n": n, "n": len(chosen),
                "distinct_choices": len(counts),
                "distribution": dict(counts.most_common()),
                "menu_sizes": sorted(menus),
                "uniform_baseline": uniform})


def replayability(rows: Sequence[Mapping[str, Any]]) -> Measure:
    """How many rows a shuffled-context control could be run on FAITHFULLY.

    The control's premise is that the only thing changed between arms is the state. That holds
    only if the rest of the prompt can be reconstructed exactly. It cannot be here: a mid-loop
    decision saw a history of tool results that is persisted nowhere, so re-asking it would
    silently drop the largest part of its input and then attribute the difference to the
    shuffle. Counting the faithful rows is the honest version of "can we run this yet".

    ``step 1`` is read from the context prefix the recorder writes. Matched as a prefix, not a
    substring: ``step 1`` also occurs inside ``step 12``.
    """
    if not rows:
        return Measure("replayable_rows", False, reason="the corpus is empty",
                       detail={"rows": 0})
    first_turn = [r for r in rows if str(r.get("context") or "").startswith("step 1 |")]
    return Measure(
        "replayable_rows", True, value=float(len(first_turn)),
        detail={
            "rows": len(rows),
            "first_turn": len(first_turn),
            "mid_loop": len(rows) - len(first_turn),
            "caveat": ("even first-turn rows never recorded the system prompt the decider saw, "
                       "so none of them is a byte-faithful replay either"),
        })


def shuffled_control(rows: Sequence[Mapping[str, Any]], *, ask=None) -> Measure:
    """JD-4's control arm: each question paired with the WRONG state.

    ``ask`` is the judge — ``ask(context, options) -> chosen``. It is a PARAMETER rather than an
    import so this harness stays free by default and so a test can drive the arm with a stub:
    the scoring must be exercisable without spending a model call, or the only way to find a bug
    in it is to pay for one.

    Refuses rather than approximating when the corpus cannot support a faithful replay. A
    control that asks a different question than the one logged measures nothing, and reporting
    its agreement rate anyway would be the exact "guard that passed for the wrong reason" this
    battery exists to catch.
    """
    rep = replayability(rows)
    faithful = int(rep.detail.get("first_turn", 0)) if rep.available else 0
    if ask is None:
        return Measure(
            "shuffled_control", False,
            reason=("not run: no judge was supplied. Running it costs one model call per row "
                    "per arm, which is the operator's spend, never this harness's default"),
            detail={"would_cost_calls": 2 * len(rows), "faithful_rows": faithful})
    if faithful < 2:
        return Measure(
            "shuffled_control", False,
            reason=(f"only {faithful} row(s) could be replayed faithfully — the rest are "
                    "mid-loop decisions whose tool-result history is persisted nowhere, so a "
                    "replay would change more than the state and attribute it to the shuffle"),
            detail=dict(rep.detail))

    # Pair each row's options with ANOTHER row's context. Rotation by one, not a random
    # shuffle: a run whose control arm changes between invocations cannot be compared with
    # itself, and `Math.random`-style nondeterminism is how a battery stops being a ratchet.
    usable = [r for r in rows if str(r.get("context") or "").startswith("step 1 |")]
    agree = 0
    for i, r in enumerate(usable):
        wrong_state = usable[(i + 1) % len(usable)].get("context")
        picked = ask(wrong_state, list(r.get("options") or []))
        if picked == r.get("chosen"):
            agree += 1
    return Measure("shuffled_control", True, value=agree / len(usable),
                   detail={"n": len(usable), "agreed_with_real_choice": agree,
                           "pairing": "rotate-by-one (deterministic)"})


# ── The report ────────────────────────────────────────────────────────────────

def summarize(rows: Sequence[Mapping[str, Any]], truncation: Mapping[str, Any],
              *, ask=None) -> dict:
    """The battery, and JD-4's falsifier."""
    measures = [top1(rows), ece(rows), choice_prior(rows),
                replayability(rows), shuffled_control(rows, ask=ask)]
    by_name = {m.name: m for m in measures}
    by_site = Counter(str(r.get("site") or "?") for r in rows)

    control, prior = by_name["shuffled_control"], by_name["choice_prior"]
    # JD-4's own falsifier, as the roadmap states it: if the shuffled arm scores within noise of
    # the real one, the judgments are not reading the state and the rest of Arc JD is pointless.
    # The real arm IS the logged choice, so the comparison is the control against the PRIOR:
    # a control at or above the majority-class rate has reproduced the distribution, not read
    # the state. Evaluable only when the control actually ran.
    if control.available and prior.available:
        fires = float(control.value or 0.0) >= float(prior.value or 0.0)
        note = (f"control agreed {control.value:.1%} vs a {prior.value:.1%} majority-class "
                "prior — at or above the prior means the state was not read")
    else:
        fires, note = False, ("not evaluable: " + (control.reason or "the control did not run"))

    out = {
        "n_rows": len(rows),
        "rows_by_site": dict(by_site),
        "sites_silent": [s for s in SITES if not by_site.get(s)],
        "truncation": dict(truncation),
        "measures": {m.name: m.as_dict() for m in measures},
        "falsifier": {"judgments_do_not_read_the_state": fires, "note": note},
    }
    # A battery that could not take a single reading settles nothing, and reporting that as a
    # clean run is how an instrument becomes decoration. `inconclusive` is separate from the
    # falsifier for exactly the reason its siblings keep them apart.
    out["inconclusive"] = (not rows) or (not control.available)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=str(REPO / "data" / "decisions.db"),
                    help="the decisions store to read (default: the repo's own)")
    ap.add_argument("--output", default="", help="write the result JSON here")
    args = ap.parse_args()

    db = Path(args.db)
    if not db.exists():
        raise SystemExit(f"no decisions store at {db}")

    rows, truncation = load_rows(db)
    # No judge is wired here on purpose: this entry point must stay free. The control arm is
    # driven by a caller that has decided to spend.
    summary = summarize(rows, truncation, ask=None)
    result = {"db": str(db), "summary": summary}

    print(f"judgment battery: {summary['n_rows']} rows from {db}")
    if summary["rows_by_site"]:
        print("  rows by site: " + ", ".join(f"{k}={v}" for k, v in
                                             sorted(summary["rows_by_site"].items())))
    if summary["sites_silent"]:
        print(f"  silent sites (no traffic in this store): {', '.join(summary['sites_silent'])}")
    if truncation.get("truncated"):
        print(f"  ⚠️  TRUNCATED: {truncation['note']}")

    print(f"\n  {'measure':<20} {'value':>10}  status")
    for name in ("top1", "ece", "choice_prior", "replayable_rows", "shuffled_control"):
        m = summary["measures"][name]
        shown = "—" if m["value"] is None else (
            f"{m['value']:.4f}" if abs(m["value"]) < 1 else f"{m['value']:.0f}")
        print(f"  {name:<20} {shown:>10}  {'ok' if m['available'] else 'UNAVAILABLE'}")
        if not m["available"]:
            print(f"  {'':<20} {'':>10}  ↳ {m['reason']}")

    prior = summary["measures"]["choice_prior"]
    if prior["available"]:
        d = prior["detail"]
        print(f"\n  the floor a control must beat: {prior['value']:.1%} "
              f"(always guessing {d['majority_choice']!r}); "
              f"uniform over {max(d['menu_sizes'])} options would be "
              f"{(d['uniform_baseline'] or 0):.1%}")

    if summary["inconclusive"]:
        print("\nINCONCLUSIVE: the control arm did not run — this settles nothing in either "
              "direction.")
    print(f"falsifier: "
          f"{'FIRES' if summary['falsifier']['judgments_do_not_read_the_state'] else 'HOLDS'}"
          f" — {summary['falsifier']['note']}")

    if args.output:
        Path(args.output).write_text(json.dumps(result, indent=2, default=str) + "\n")
        print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
