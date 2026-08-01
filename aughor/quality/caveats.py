"""Wave Q2 + Q4 — profiler candidates into the one queue, and caveats onto the answer.

**Q4 is the first-mover feature and it is one function.** Tables in the executed SQL join
against the latest health results at answer time, and failures render inline with
provenance. Nobody ships this; the reason nobody ships it is that it only works once Q1–Q3
exist, which is why it is last.

**One caveat path — the gate this wave added to the program.** Three producers already emit
caveat-shaped strings: O6's violated declarations, `sql/trust_checks`' result critiques,
and now Q3's health results. Rendering them separately would show a reader the same concern
twice in different words, and a caveat somebody has seen twice in different words is a
caveat they stop reading. :func:`assemble` is therefore the single renderer, and it dedups.

**`warn` annotates, `error` can gate.** The severity split is what makes caveats usable: if
every quality signal blocked, teams would turn the plane off; if none did, the plane would
be decoration. :func:`blocking_reasons` is the publish gate's input and is deliberately
separate from the annotation path so a caller cannot accidentally block on a warning.

**Q2 reuses O4's `Candidate`.** Q's proposals are a different *kind*, not a different type.
A second candidate model would be a second queue with extra steps, and J10 says one queue.
"""
from __future__ import annotations

from typing import Iterable, Optional

from aughor.quality.results import Result

#: How stale a verdict may be before it is reported as aged rather than authoritative.
#: A caveat citing a week-old check is worse than none: it teaches the reader the health
#: signal is noise.
MAX_CAVEAT_AGE_HOURS = 72


def _age_note(result: Result) -> str:
    return "" if result.staleness() == "fresh" else " (health check is stale)"


def caveat_for(result: Result) -> str:
    """One reader-facing sentence, with provenance.

    Names the rule and the run: a caveat a reader cannot trace is a caveat they cannot act
    on, and "data quality issue detected" is the phrasing that trains people to ignore the
    banner.
    """
    if result.passed:
        return ""
    what = result.detail or f"failed {result.rule_name or 'a quality check'}"
    run = f" [run {result.run_id}]" if result.run_id else ""
    count = f" ({result.violations} violation(s))" if result.violations else ""
    return f"`{result.table_name}` {what}{count}{run}{_age_note(result)}"


def assemble(
    *,
    health: Iterable[Result] = (),
    declaration_caveats: Iterable[str] = (),
    trust_caveats: Iterable[str] = (),
) -> list[str]:
    """The ONE caveat renderer. Dedups across all three producers.

    Order is deliberate: health results first (a failing table is the most actionable),
    then declaration violations (O6 — the promise the ontology made), then result-semantics
    critiques (`trust_checks`). Within that, the dedup keeps the FIRST rendering of a
    concern, so the most actionable phrasing survives.
    """
    out: list[str] = []
    seen: set[str] = set()

    def _add(text: str) -> None:
        line = " ".join(str(text or "").split())
        if not line:
            return
        key = line.lower()
        if key in seen:
            return
        seen.add(key)
        out.append(line)

    for r in health:
        _add(caveat_for(r))
    for c in declaration_caveats:
        _add(c)
    for c in trust_caveats:
        _add(c)
    return out


def caveats_for_answer(
    connection_id: str,
    tables: Iterable[str],
    *,
    declaration_caveats: Iterable[str] = (),
    trust_caveats: Iterable[str] = (),
    org_id: Optional[str] = None,
) -> list[str]:
    """Q4: the caveats that ride an answer over ``tables``.

    Best-effort by construction — a health store that cannot be read must never fail an
    answer, because a quality plane that can break answers is a quality plane operators
    disable. The other two producers still render.
    """
    health: list[Result] = []
    try:
        from aughor.quality.results import latest_for_tables

        health = [r for r in latest_for_tables(connection_id, list(tables), org_id=org_id)
                  if not r.passed]
    except Exception as exc:
        from aughor.kernel.errors import tolerate

        tolerate(exc, "health caveats are best-effort; the answer proceeds without them",
                 counter="quality.caveats")
    return assemble(health=health, declaration_caveats=declaration_caveats,
                    trust_caveats=trust_caveats)


def blocking_reasons(results: Iterable[Result]) -> list[str]:
    """Why a publish should be refused. `error` failures only.

    Separate from the annotation path on purpose: if a caller could block on the same list
    it annotates with, every warning would eventually become a block by accident, and the
    plane would get switched off.
    """
    return [caveat_for(r) for r in results if r.blocking]


# ── Q2 — profiler thresholds become candidates in the ONE queue ─────────────────────

#: Deterministic thresholds. Conservative on purpose: a candidate queue that proposes
#: something about every column is a queue nobody opens twice.
NULL_RATIO_SUSPECT = 0.5
LOW_CARDINALITY_MAX = 20


def candidates_from_profile(connection_id: str, table: str, columns: Iterable[dict]):
    """Profiler thresholds → typed candidates for the A4 inbox.

    Reuses O4's :class:`~aughor.ontology.candidates.Candidate` rather than declaring a
    second model: Q's proposals are a different KIND, not a different type, and a second
    candidate model is a second queue with extra steps (J10).

    Deterministic only. LLM proposals are allowed to ADD candidates elsewhere, never to
    replace these, and never to become a check — a quality verdict a model authored cannot
    gate a publish.
    """
    from aughor.ontology.candidates import Candidate

    out = []
    for col in columns:
        name = str(col.get("name") or "").strip()
        if not name:
            continue
        null_ratio = col.get("null_ratio")
        distinct = col.get("distinct_count")

        if null_ratio is not None and float(null_ratio) == 0.0:
            out.append(Candidate(
                connection_id=connection_id, kind="filter", subject=f"{table}.{name}",
                proposal=f"not_null check on {table}.{name}", origin="query_log",
                source_rank="mined",
                evidence="profiler observed 0% nulls across the sampled rows"))
        elif null_ratio is not None and float(null_ratio) >= NULL_RATIO_SUSPECT:
            out.append(Candidate(
                connection_id=connection_id, kind="filter", subject=f"{table}.{name}",
                proposal=f"review {table}.{name} — mostly empty", origin="query_log",
                source_rank="mined",
                evidence=f"profiler observed {float(null_ratio):.0%} nulls"))

        if distinct is not None and 0 < int(distinct) <= LOW_CARDINALITY_MAX:
            out.append(Candidate(
                # frozen inbox record value — see candidates.CANDIDATE_KINDS
                connection_id=connection_id, kind="object_set",
                subject=f"{table}.{name}",
                proposal=f"value dictionary for {table}.{name}", origin="query_log",
                source_rank="mined",
                evidence=f"profiler observed {int(distinct)} distinct value(s)"))
    return out
