"""Wave N1 — the same question, answered two different ways.

**The measurement that motivated this.** On a real connection, 793 answer receipts covered
175 distinct questions: **92% of receipts were questions asked two or more times**, and of the
110 questions asked repeatedly, only 9 produced the same SQL every time. Executing the
variants of one ordinary question — *"What is the total gmv_eur by platform?"*, asked 18 times
— returned **€45,437,544** on some days and **€43,595,576** on others. Both queries ran clean.
Neither is a bug. One counted cancelled and test orders as revenue and the other did not, and
nothing remembered which answer the business had already settled on.

That is what this module finds: not errors, but *unremembered decisions*.

**Why detection cannot pin the answer itself.** Whether a cancelled order counts as revenue is
a business fact, not a derivable one. The most common variant is a popularity signal, and
promoting it would launder popularity into correctness — the exact move L5 caught in the
trusted-query prompt header. So this module surfaces divergence and measures its impact; a
**human** picks the survivor, and only then does it become a trusted query, tagged with a
warrant that says a person decided (:data:`HUMAN_TAG`), distinct from the weaker
consistency warrant an eval-promoted entry carries.

**Cosmetic variance is not divergence.** The first cut of this analysis reported 101 of 110
questions as varying — until one was read closely: ``SELECT COUNT(*) FROM luxexperience.returns``
versus ``SELECT COUNT(*) FROM returns`` versus the same with a renamed alias. Three
"different" queries, one meaning. :func:`semantic_key` strips schema qualification, aliases
and whitespace before comparing, which moved the honest count to 99 semantic / 2 cosmetic. A
detector that cries wolf on an alias rename teaches its reader to ignore it.

Nothing here writes to the answer path. Detection is a read over receipts the platform already
stores; the only write is an explicit human pin.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Optional

#: Tag marking a trusted query a HUMAN chose from divergent variants. A stronger warrant
#: than `promote_trusted.SOURCE_TAG` ("passed every eval run" = consistency), and
#: `build_trusted_block` already states the weakest warrant present, so mixing is safe.
HUMAN_TAG = "human_pinned"

#: Questions asked fewer times than this cannot show divergence worth acting on — one run
#: is not a pattern, and the point is decisions taken repeatedly.
MIN_RUNS = 2

#: Rows read per variant when measuring impact. A divergence is visible in the shape and the
#: totals; nobody needs the whole table to see that two answers disagree.
IMPACT_ROW_CAP = 500


def _question_key(question: str) -> str:
    """Questions match on lowercased alphanumerics — punctuation and casing are not intent."""
    return re.sub(r"[^a-z0-9 ]", "", (question or "").lower()).strip()


def semantic_key(sql: str) -> str:
    """A SQL fingerprint that ignores how it was written and keeps what it computes.

    Strips schema qualification (``luxexperience.orders`` → ``orders``), column and table
    aliases, and whitespace. Deliberately NOT a parser: this is a comparison key over queries
    the platform itself generated, and a false "identical" is safer here than a false
    "divergent" — the cost of missing one divergence is a decision left unmade, while the cost
    of crying wolf on an alias rename is a reader who stops reading.
    """
    s = re.sub(r"\s+", " ", (sql or "").strip().lower())
    s = re.sub(r"\b\w+\.(\w+)\b", r"\1", s)      # schema/table qualification
    s = re.sub(r"\s+as\s+\w+", "", s)             # aliases
    return s.strip()


@dataclass
class Variant:
    """One way the question has been answered."""

    sql: str
    key: str
    tables: tuple[str, ...] = ()
    run_count: int = 0
    first_seen: str = ""
    last_seen: str = ""
    receipt_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"sql": self.sql, "key": self.key, "tables": list(self.tables),
                "run_count": self.run_count, "first_seen": self.first_seen,
                "last_seen": self.last_seen, "receipt_ids": list(self.receipt_ids)}


@dataclass
class Divergence:
    """A question the platform has answered more than one way."""

    question: str                       # the most recent phrasing, for display
    question_key: str
    run_count: int
    variants: list[Variant] = field(default_factory=list)   # most-run first
    pinned: bool = False                # already settled by a human?

    @property
    def variant_count(self) -> int:
        return len(self.variants)

    @property
    def top_reuse(self) -> int:
        """How often the most-used variant was reused."""
        return max((v.run_count for v in self.variants), default=0)

    @property
    def contested(self) -> bool:
        """True when at least one variant RECURS — the signal that separates a contested
        decision from open-ended exploration.

        Measured, not assumed. On the reference connection, ranking by variant count put
        *"How do orders and returns relate?"* (15 variants across 15 runs — every single run
        unique) at the top, and *"total attributed_gmv_eur by marketing_channel"* (3 variants
        across 14 runs, the leader used 10 times) far below it. That is backwards: the first
        is an open question being explored from new angles, where variety is the point; the
        second is a routine metric with an established answer and a challenger, which is a
        decision somebody should take. Reuse tells them apart — 34 contested vs 58
        exploratory here — and only the contested ones are worth a human's attention.
        """
        return self.top_reuse >= 2

    @property
    def tables_differ(self) -> bool:
        """Variants reading different tables is the sharper signal — a different filter can
        still be a judgement call, but different sources usually means a different question
        was answered."""
        return len({v.tables for v in self.variants}) > 1

    def to_dict(self) -> dict[str, Any]:
        return {"question": self.question, "question_key": self.question_key,
                "run_count": self.run_count, "variant_count": self.variant_count,
                "top_reuse": self.top_reuse, "contested": self.contested,
                "tables_differ": self.tables_differ, "pinned": self.pinned,
                "variants": [v.to_dict() for v in self.variants]}


def _receipts(connection_id: str, org_id: Optional[str], limit: int) -> list[dict]:
    from aughor.kernel.ledger import Ledger
    from aughor.ontology.context_graph_build import RECEIPT_KINDS

    return Ledger.default().artifacts_of_kind(
        list(RECEIPT_KINDS), conn_id=connection_id, org_id=org_id, limit=limit) or []


def detect(connection_id: str, *, org_id: Optional[str] = None, min_runs: int = MIN_RUNS,
           limit: int = 2000, include_settled: bool = False,
           include_exploratory: bool = False) -> list[Divergence]:
    """Every recurring question this connection has answered more than one way.

    Deterministic and read-only: no LLM, no warehouse access, no writes.

    Ordered **contested first** (see :attr:`Divergence.contested`), then by how established
    the leading answer is, then by how often the question is asked — the order a human should
    spend attention in. Sorting by variant count instead puts open-ended exploration on top,
    where disagreement is the point rather than a defect.

    ``include_exploratory=False`` drops questions where every run produced a unique query:
    those are being explored, not decided, and asking a reviewer to pin one is asking the
    wrong question.

    ``include_settled`` keeps questions that already have a pinned trusted query; by default
    they are dropped, since the decision has been taken and re-surfacing it is noise.
    """
    pinned_keys = _pinned_question_keys(connection_id)
    by_q: dict[str, list[dict]] = {}
    display: dict[str, tuple[str, str]] = {}      # key -> (created_at, question)

    for art in _receipts(connection_id, org_id, limit):
        payload = art.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        question = str(payload.get("question") or "").strip()
        sql = str(payload.get("sql") or "").strip()
        if not question or not sql:
            # A receipt with no SQL concluded nothing this module can compare. Abstentions
            # and text-only answers are legitimate outcomes, not divergences.
            continue
        key = _question_key(question)
        if not key:
            continue
        by_q.setdefault(key, []).append({
            "sql": sql,
            "tables": tuple(sorted(str(t) for t in (payload.get("tables") or []))),
            "id": str(art.get("id") or ""),
            "at": str(art.get("created_at") or ""),
        })
        seen = display.get(key)
        at = str(art.get("created_at") or "")
        if seen is None or at > seen[0]:
            display[key] = (at, question)

    out: list[Divergence] = []
    for key, runs in by_q.items():
        if len(runs) < max(2, int(min_runs)):
            continue
        is_pinned = key in pinned_keys
        if is_pinned and not include_settled:
            continue
        grouped: dict[str, Variant] = {}
        for r in runs:
            sk = semantic_key(r["sql"])
            v = grouped.get(sk)
            if v is None:
                grouped[sk] = Variant(sql=r["sql"], key=sk, tables=r["tables"], run_count=1,
                                      first_seen=r["at"], last_seen=r["at"],
                                      receipt_ids=(r["id"],))
            else:
                grouped[sk] = Variant(
                    sql=v.sql, key=sk, tables=v.tables, run_count=v.run_count + 1,
                    first_seen=min(v.first_seen, r["at"]) if v.first_seen else r["at"],
                    last_seen=max(v.last_seen, r["at"]),
                    receipt_ids=v.receipt_ids + (r["id"],))
        if len(grouped) < 2:
            continue      # answered consistently — nothing to decide
        variants = sorted(grouped.values(), key=lambda v: (-v.run_count, v.first_seen))
        div = Divergence(question=display[key][1], question_key=key,
                         run_count=len(runs), variants=variants, pinned=is_pinned)
        if not div.contested and not include_exploratory:
            continue
        out.append(div)

    out.sort(key=lambda d: (not d.contested, -d.top_reuse, -d.run_count))
    return out


def _pinned_question_keys(connection_id: str) -> set[str]:
    from aughor.kernel.errors import tolerate
    try:
        from aughor.semantic.trusted_queries import list_trusted
        return {_question_key(tq.question) for tq in list_trusted(connection_id)}
    except Exception as exc:
        tolerate(exc, "reading pinned trusted queries is best-effort; divergences are still "
                      "detectable, a settled one is merely re-surfaced",
                 counter="divergence.pinned_read")
        return set()


# ── impact: do the variants actually disagree? ────────────────────────────────────

@dataclass
class VariantResult:
    key: str
    row_count: int = 0
    columns: tuple[str, ...] = ()
    digest: str = ""
    numeric_total: Optional[float] = None
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "row_count": self.row_count, "columns": list(self.columns),
                "digest": self.digest, "numeric_total": self.numeric_total,
                "error": self.error}


@dataclass
class Impact:
    """What the divergence is actually worth, in the data's own numbers."""

    question: str
    results: list[VariantResult] = field(default_factory=list)

    @property
    def results_differ(self) -> bool:
        prints = {r.digest for r in self.results if not r.error}
        return len(prints) > 1

    @property
    def numeric_spread(self) -> Optional[float]:
        """Largest gap between variant totals — the "€1.84M" number, when there is one."""
        vals = [r.numeric_total for r in self.results if r.error == "" and r.numeric_total is not None]
        return (max(vals) - min(vals)) if len(vals) > 1 else None

    def to_dict(self) -> dict[str, Any]:
        return {"question": self.question, "results_differ": self.results_differ,
                "numeric_spread": self.numeric_spread,
                "results": [r.to_dict() for r in self.results]}


def _result_digest(columns: list, rows: list) -> tuple[str, Optional[float]]:
    """A stable digest of a result set's DATA, plus the sum of its numeric cells.

    Column **names are deliberately excluded** — only the column *count* and the values
    matter. An early version hashed the names and duly reported that
    ``SUM(x) AS sum_gmv`` and ``SUM(x) AS total_gmv`` were different answers, when all three
    variants of that question returned byte-identical numbers. Renaming an output label is
    not a disagreement about the data, and a detector that says it is trains its reader to
    stop believing it. Floats are rounded before hashing for the same reason (``ROUND(x,2)``
    vs not is presentation, not fact).
    """
    norm: list[list[str]] = []
    total: Optional[float] = None
    for row in rows:
        cells = []
        for cell in row:
            try:
                f = float(cell)
                total = (total or 0.0) + f
                cells.append(f"{round(f, 4)}")
            except (TypeError, ValueError):
                cells.append(str(cell))
        norm.append(cells)
    payload = f"cols={len(columns)}|" + repr(sorted(norm))
    return hashlib.sha256(payload.encode()).hexdigest()[:16], total


def measure_impact(divergence: Divergence, connection_id: str, *,
                   max_variants: int = 4) -> Impact:
    """Execute each variant read-only and report whether they actually disagree.

    This is the step that turns "the SQL differs" into "these two answers differ by 1.8
    million" — the difference between a code observation and a decision a human can take.
    A variant that errors is reported as errored, never silently dropped: a query that no
    longer runs is itself worth seeing next to one that does.
    """
    from aughor.db.connection import open_connection_for
    from aughor.kernel.errors import tolerate

    impact = Impact(question=divergence.question)
    db = open_connection_for(connection_id)
    try:
        for variant in divergence.variants[:max(1, int(max_variants))]:
            try:
                res = db.execute("divergence-impact", variant.sql)
            except Exception as exc:
                impact.results.append(VariantResult(key=variant.key,
                                                    error=f"{type(exc).__name__}: {exc}"))
                continue
            if res is None or getattr(res, "error", ""):
                impact.results.append(VariantResult(
                    key=variant.key, error=str(getattr(res, "error", "no result"))))
                continue
            rows = list(res.rows or [])[:IMPACT_ROW_CAP]
            cols = [str(c) for c in (res.columns or [])]
            digest, total = _result_digest(cols, rows)
            impact.results.append(VariantResult(
                key=variant.key, row_count=len(res.rows or []), columns=tuple(cols),
                digest=digest, numeric_total=total))
    finally:
        try:
            db.close()
        except Exception as exc:
            tolerate(exc, "closing the impact-measurement handle is best-effort; the "
                          "comparison is already computed", counter="divergence.db_close")
    return impact


# ── the human decision ────────────────────────────────────────────────────────────

def pin(connection_id: str, question: str, sql: str, *, tables: Optional[list[str]] = None,
        note: str = "") -> Any:
    """Record a human's choice of the correct variant as a trusted query.

    The warrant is :data:`HUMAN_TAG` — a person decided — which is stronger than the
    consistency warrant an eval-promoted entry carries, and `build_trusted_block` already
    states the weakest warrant in the set rather than the strongest.

    Content-addressed on the question (the `promote_trusted` id shape), so pinning the same
    question twice REPLACES the decision rather than accumulating two contradictory trusted
    answers — a store that can hold both variants of "does cancelled count as revenue" would
    reintroduce the exact divergence it exists to end.
    """
    from aughor.evals.promote_trusted import trusted_id
    from aughor.semantic.trusted_queries import TrustedQuery, save_trusted

    tq = TrustedQuery(
        id=trusted_id(connection_id, question),
        connection_id=connection_id,
        question=question.strip(),
        sql=sql.strip(),
        tables=[str(t) for t in (tables or [])],
        note=note.strip() or "chosen by a reviewer from divergent past answers",
        tags=[HUMAN_TAG],
    )
    save_trusted(tq)
    return tq


def confirmed(connection_id: str, *, org_id: Optional[str] = None, limit: int = 2000,
              max_questions: int = 25) -> list[tuple[Divergence, Impact]]:
    """Contested divergences whose variants, when EXECUTED, actually disagree.

    Execution is the ground truth and text over-reports it. On the reference connection 34
    questions looked contested; running them left **12 with genuinely different answers**, 6
    identical (the SQL differed, the data did not), and 16 impossible to compare because old
    variants reference tables that no longer exist — schema drift, which is worth seeing
    rather than hiding, since it means a stored answer has quietly stopped working.

    Costs one bounded read per variant, so it is the deliberate second stage: cheap text
    detection narrows the field, execution confirms it. Ordered by the size of the gap
    between the answers, which is as close to "how much is this decision worth" as the
    platform can get without knowing the business.
    """
    out: list[tuple[Divergence, Impact]] = []
    for div in detect(connection_id, org_id=org_id, limit=limit)[:max(1, int(max_questions))]:
        impact = measure_impact(div, connection_id)
        comparable = [r for r in impact.results if not r.error]
        if len(comparable) >= 2 and impact.results_differ:
            out.append((div, impact))
    out.sort(key=lambda pair: -abs(pair[1].numeric_spread or 0))
    return out


def summary(connection_id: str, *, org_id: Optional[str] = None,
            limit: int = 2000) -> dict[str, Any]:
    """Headline counts for a connection — the number that says whether this matters here."""
    divs = detect(connection_id, org_id=org_id, limit=limit, include_settled=True,
                  include_exploratory=True)
    contested = [d for d in divs if d.contested]
    actionable = [d for d in contested if not d.pinned]
    return {
        "connection_id": connection_id,
        "divergent_questions": len(divs),
        "contested": len(contested),
        "exploratory": len(divs) - len(contested),
        "actionable": len(actionable),
        "already_pinned": len(contested) - len(actionable),
        "questions_with_differing_tables": sum(1 for d in contested if d.tables_differ),
        "worst": [d.question for d in actionable[:5]],
    }
