"""Promote verified eval cases into trusted queries — Wave L5.

The trusted-query store shipped with **zero entries on every connection**: a mechanism
that was built, wired and never adopted. Meanwhile the eval plane has been accumulating
exactly the thing that store wants — question/SQL pairs whose behaviour is known.

This is the conservative half of the study's capture → verify → generalize loop. It
only *captures*: a case is promotable when it **passed in every run that exercised it**,
across every cell. Passing under one configuration and failing under another means the
answer depends on configuration, and a query whose correctness is conditional is the
last thing that should be presented to the planner as trusted.

What this deliberately does NOT do:

* **Generalize.** No mining of filters or metrics out of the SQL — that is the O4 work,
  and it needs a review queue because a generalization can be wrong in ways a capture
  cannot.
* **Auto-apply without provenance.** Every minted query records the suite and the runs
  that vouched for it, so a reader can audit why it is trusted rather than taking the
  label on faith.
* **Assert correctness.** These cases come from a *consistency* suite: passing means
  "reproduces the answer this connection already gave", not "is true". The note says so
  on every entry, because a store called `trusted` invites exactly that misreading.
"""
from __future__ import annotations

#: Marks entries this module minted, so a later pass can tell them from hand curation.
SOURCE_TAG = "from_eval"


def trusted_id(connection_id: str, question: str) -> str:
    """A deterministic, content-addressed id.

    ``save_trusted`` dedupes on ``id``, so a blank or random one is a trap in opposite
    directions: blank makes every entry overwrite the last (25 promotions leaving 1),
    random makes re-running the promotion duplicate everything it already minted.
    Hashing the question gives idempotence for free — the same question always lands on
    the same row.
    """
    import hashlib

    digest = hashlib.sha256(f"{connection_id}|{question.strip().lower()}".encode())
    return f"tq_{digest.hexdigest()[:12]}"


def promotable(suite_id: str, *, min_runs: int = 2) -> list[dict]:
    """Cases that passed in EVERY run that exercised them.

    ``min_runs`` guards against promoting on a single observation — one pass is an
    anecdote, and the whole point of using the eval plane as the source is that it has
    seen these questions more than once.
    """
    from aughor.evals.store import list_cases, list_runs, run_results

    outcomes: dict[str, list[bool]] = {}
    for run in list_runs(suite_id, limit=50):
        if run.get("status") != "succeeded":
            continue
        for res in run_results(run["id"]):
            outcomes.setdefault(res["case_id"], []).append(bool(res.get("passed")))

    cases = {c["id"]: c for c in list_cases(suite_id)}
    out: list[dict] = []
    for case_id, results in outcomes.items():
        case = cases.get(case_id)
        if case is None or len(results) < min_runs or not all(results):
            continue
        if not (case.get("question") or "").strip() or not (case.get("artifact") or "").strip():
            continue
        out.append({"case": case, "runs": len(results)})
    return out


def promote(suite_id: str, connection_id: str, *, min_runs: int = 2,
            limit: int = 25, dry_run: bool = False) -> dict:
    """Mint trusted queries from a suite's unanimously-passing cases.

    Returns ``{"promoted": n, "skipped_existing": n, "candidates": n}``. Idempotent by
    question text: re-running after another grid adds what is newly verified and leaves
    the rest alone.
    """
    from aughor.semantic.trusted_queries import TrustedQuery, list_trusted, save_trusted

    candidates = promotable(suite_id, min_runs=min_runs)
    # Dedupe against the WHOLE store, drafts included — re-minting over a draft a human
    # is still deciding about would silently overwrite their pending judgement.
    existing = {(tq.question or "").strip().lower()
                for tq in list_trusted(connection_id, include_unapproved=True)}

    promoted = skipped = 0
    for item in candidates:
        if promoted >= limit:
            break
        case = item["case"]
        question = str(case["question"]).strip()
        if question.lower() in existing:
            skipped += 1
            continue
        if dry_run:
            promoted += 1
            existing.add(question.lower())
            continue
        expected = case.get("expected") or {}
        if isinstance(expected, str):
            import json

            from aughor.kernel.errors import tolerate
            try:
                expected = json.loads(expected)
            except Exception as exc:
                tolerate(exc, "eval case `expected` is unreadable JSON; the trusted "
                              "query is still minted, without its table list",
                         counter="evals.promote_trusted.expected_parse")
                expected = {}
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        save_trusted(TrustedQuery(
            id=trusted_id(connection_id, question),
            connection_id=connection_id,
            question=question,
            sql=str(case["artifact"]),
            tables=list((expected or {}).get("tables") or []),
            note=(f"Verified by eval suite {suite_id}: passed in all {item['runs']} runs. "
                  f"Consistency-verified (reproduces this connection's prior answer), "
                  f"NOT independently checked for correctness."),
            tags=[SOURCE_TAG, f"suite:{suite_id}"],
            # KI-0: minted entries were injected before statuses existed and their
            # warrant (unanimous passes, ≥min_runs) is the promotion bar itself —
            # they land approved, with the suite as the verifier of record.
            status="approved", version=1, source="eval_promotion",
            verified_by=f"eval-suite:{suite_id}", verified_at=now,
        ))
        existing.add(question.lower())
        promoted += 1

    return {"promoted": promoted, "skipped_existing": skipped,
            "candidates": len(candidates)}
