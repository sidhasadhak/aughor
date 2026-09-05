"""Turning graded rows into corpora — SFT, DPO and the held-out golden set.

Three properties this file exists to guarantee, each of which has a test:

* **Deterministic.** The same graded rows export to the same content hash, every time.
  Without that an adapter's provenance cites a moving target.
* **Disjoint.** A golden example is never also an SFT example. A corpus that trains on its
  own benchmark cannot be measured by it, and the split is by a STABLE hash of the
  investigation id, not by shuffling — a random split would move every re-export.
* **Scrubbed.** Text goes through the existing `security/pii` seam on the way out, per
  §6.7's annex. Reusing that seam rather than writing a second scrubber is deliberate: two
  redaction implementations means two definitions of what counts as PII.

**Measured before writing (2026-09-03).** The live store holds 5 verdicts: 2 accept, 1
correct, 2 reject, and **none carries `sql_source` or `corrected_sql`** — so these
exporters produce ~0 examples on this deployment today. That is the honest state, and it
is the arc's own prediction (§3.9: *capture is already rich; grading is the gap*), not a
defect here. MI-4's gates — 1,000 SFT / 150 DPO / 150 golden — are measured against these
outputs precisely so the distillation premise stays falsifiable.
"""
from __future__ import annotations

import hashlib
from typing import Optional

from aughor.learning import store

#: Share of accepted findings held out as golden. A tenth is enough to measure and cheap
#: to give up; the split is by stable hash so it does not drift between exports.
_GOLDEN_SHARE = 10


def _scrub(text: str) -> str:
    """One text field through the platform's PII seam.

    The seam is tabular (it was built for query results), so a field is presented as a
    one-cell row. Worth the small awkwardness: a second scrubber would be a second
    definition of PII, and the two would drift."""
    if not text:
        return text
    try:
        from aughor.security.pii import PiiScanner
        res = PiiScanner.scan_and_redact(["text"], [[text]])
        return res.rows[0][0] if res.rows and res.rows[0] else text
    except Exception:
        from aughor.kernel.errors import tolerate
        tolerate(Exception("pii scrub failed"),
                 "an export that cannot be scrubbed must not ship unscrubbed",
                 counter="learning.scrub")
        return ""      # fail CLOSED: drop the text rather than export it unredacted


def _is_golden(verdict_row: dict) -> bool:
    """Stable, content-derived hold-out. Deliberately NOT random: a shuffled split would
    move examples between corpora on every export and break both determinism and the
    promise that a golden example was never trained on."""
    key = str(verdict_row.get("investigation_id") or verdict_row.get("id") or "")
    fingerprint = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return int(fingerprint[:8], 16) % _GOLDEN_SHARE == 0


def _dedupe(examples: list[dict]) -> list[dict]:
    """Aggressive dedupe, first occurrence wins. Duplicated examples do not add signal;
    they add WEIGHT, quietly training the model harder on whatever happens to repeat."""
    seen: set[str] = set()
    out: list[dict] = []
    for ex in examples:
        key = hashlib.sha256(
            (str(ex.get("prompt", "")) + "\x00" + str(ex.get("completion", ""))
             + "\x00" + str(ex.get("rejected", ""))).encode("utf-8")).hexdigest()
        if key not in seen:
            seen.add(key)
            out.append(ex)
    return out


def _trusted_export_rows() -> list:
    """Approved trusted queries whose approval was a HUMAN act — KI-4's addition to
    the corpus. A human-approved (question, SQL) pair is the purest SFT example the
    platform produces: the two-act door (§6 item 9b) means someone verified it ran
    clean AND someone chose to trust it. Excluded deliberately: eval-promoted entries
    (their warrant is consistency — "reproduces a prior answer", not "is true" — and
    §3.9's reward-integrity law keeps the corpus human-graded) and grandfathered
    legacy rows with no verifier of record."""
    from aughor.semantic.trusted_queries import list_trusted

    return [t for t in list_trusted()          # approved-only by default (fail closed)
            if (t.verified_by or "").strip()
            and t.source != "eval_promotion"
            and (t.question or "").strip() and (t.sql or "").strip()]


def export_sft(name: str = "nl2sql-sft", *, task: str = "nl2sql",
               limit: int = 100000) -> dict:
    """Accepted findings + human-approved trusted queries → question → SQL pairs.
    Golden candidates are excluded (same stable-hash predicate for both sources)."""
    from aughor.feedback.verdicts import list_for_export

    rows = list_for_export(("accept",), require_sql=True, limit=limit)
    kept = [r for r in rows if not _is_golden(r)]
    trusted = [t for t in _trusted_export_rows() if not _is_golden({"id": t.id})]
    examples = _dedupe([
        {"prompt": _scrub(r.get("headline") or ""),
         "completion": _scrub(r.get("sql_source") or ""),
         "task": task}
        for r in kept if (r.get("sql_source") or "")
    ] + [
        {"prompt": _scrub(t.question), "completion": _scrub(t.sql), "task": task}
        for t in trusted
    ])
    return store.register(
        name, "sft", examples, task=task,
        lineage=([("finding_verdict", r["id"]) for r in kept]
                 + [("trusted_query", t.id) for t in trusted]))


def export_dpo(name: str = "nl2sql-dpo", *, task: str = "nl2sql",
               limit: int = 100000) -> dict:
    """`correct` verdicts → preference pairs: `sql_source` rejected, `corrected_sql` chosen.

    The platform has been collecting preference data without calling it that — but ONLY
    where a human actually typed a correction. A `correct` verdict with no `corrected_sql`
    is a judgement without a lesson, and including it would fabricate a preference nobody
    expressed."""
    from aughor.feedback.verdicts import list_for_export

    rows = [r for r in list_for_export(("correct",), require_sql=True, limit=limit)
            if (r.get("corrected_sql") or "").strip()]
    examples = _dedupe([
        {"prompt": _scrub(r.get("headline") or ""),
         "completion": _scrub(r.get("corrected_sql") or ""),
         "rejected": _scrub(r.get("sql_source") or ""),
         "task": task}
        for r in rows
    ])
    return store.register(
        name, "dpo", examples, task=task,
        lineage=[("finding_verdict", r["id"]) for r in rows])


def export_golden(name: str = "nl2sql-golden", *, task: str = "nl2sql",
                  limit: int = 100000) -> dict:
    """The held-out tenth of accepted findings — the ratchet's measuring stick.

    Registered as a dataset like any other so it is versioned and provenanced, but it is
    the one kind MI-4 may never train on. Disjointness from SFT is guaranteed by the same
    predicate that excludes these rows there, so the two cannot drift apart."""
    from aughor.feedback.verdicts import list_for_export

    rows = list_for_export(("accept",), require_sql=True, limit=limit)
    held = [r for r in rows if _is_golden(r)]
    trusted = [t for t in _trusted_export_rows() if _is_golden({"id": t.id})]
    examples = _dedupe([
        {"prompt": _scrub(r.get("headline") or ""),
         "completion": _scrub(r.get("sql_source") or ""),
         "task": task}
        for r in held if (r.get("sql_source") or "")
    ] + [
        {"prompt": _scrub(t.question), "completion": _scrub(t.sql), "task": task}
        for t in trusted
    ])
    return store.register(
        name, "golden", examples, task=task,
        lineage=([("finding_verdict", r["id"]) for r in held]
                 + [("trusted_query", t.id) for t in trusted]))


def publish_golden_to_evals(node: dict, *, suite_name: Optional[str] = None) -> Optional[str]:
    """Register a golden dataset as an eval SUITE so the ratchet can actually run it.

    MI-3's receipt is "a golden set shows up in the evals plane", and the word that matters
    is *shows up*: a `golden` row in our own store proves only that we wrote one. The
    evals plane is where promotion gates are enforced, so a held-out set that never lands
    there is a measuring stick nobody measures with — the "tested, not leveraged" shape
    this codebase has paid for four times. Returns the suite id, or None when the set is
    empty (there is nothing to measure, and an empty suite would read as a passing gate).

    The suite name carries the dataset VERSION, so re-publishing a grown golden set makes
    a new suite rather than silently mutating the one a past ratchet result was measured
    against. A baseline whose cases changed underneath it is not a baseline.
    """
    if node.get("kind") != "golden":
        raise ValueError(f"only a golden dataset belongs in the evals plane, got {node.get('kind')!r}")
    rows = store.rows_of(node)
    if not rows:
        return None
    from aughor.evals import store as evals_store

    name = suite_name or f"{node['name']}-v{node['version']}"
    for existing in evals_store.list_suites(limit=500):
        if existing.get("name") == name:
            return existing["id"]          # idempotent: same version, same suite
    suite = evals_store.create_suite(
        name, description=(f"MI-3 golden set — dataset {node['name']} v{node['version']}, "
                           f"{node['row_count']} held-out examples. Never trained on."))
    evals_store.add_cases(suite["id"], [
        {"question": r.get("prompt", ""), "expected": {"sql": r.get("completion", "")},
         "tags": ["golden", "mi-3", node["name"]]}
        for r in rows
    ])
    return suite["id"]


def export_all(*, task: str = "nl2sql") -> dict[str, dict]:
    """Run every exporter. Idempotent: an unchanged corpus re-registers no new version.

    Metered under the kernel's EXISTING budget when called from a job — never a parallel
    one. Two caps for one population is a trap this repo has already paid for: a limit
    nothing enforces and a limit enforced twice are both wrong, in opposite directions."""
    return {"sft": export_sft(task=task),
            "dpo": export_dpo(task=task),
            "golden": export_golden(task=task)}


def gate_status(org_id: Optional[str] = None) -> dict:
    """Where the corpus stands against MI-4's ENTRY GATES — measured, not estimated.

    MI-4 does not start until these pass; publishing the distance is what keeps the arc
    falsifiable rather than aspirational (§3.9's falsifier: if the graded-pair rate cannot
    plausibly reach these in ~90 days, the distillation premise is unproven HERE)."""
    gates = {"sft": 1000, "dpo": 150, "golden": 150}
    s = store.stats(org_id=org_id)
    return {
        kind: {"have": s.get(kind, {}).get("examples", 0), "need": need,
               "passes": s.get(kind, {}).get("examples", 0) >= need}
        for kind, need in gates.items()
    }
