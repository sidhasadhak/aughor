"""Wave N3 — consolidate the finding corpus before the cap, and never pick a winner.

**The problem, measured.** The graph's finding projection appends one node per answered
question and bounds itself at :data:`~aughor.ontology.context_graph_build._MAX_RECEIPT_FINDINGS`
= 100, evicting **newest-first**. On the reference connection that window is doing almost all
of the forgetting, and doing it arbitrarily:

===========================================  ==============  ==============
                                             committed (100)  full (794)
===========================================  ==============  ==============
distinct subjects (question + table set)                  77             274
collapsible repeats                                23 (23%)      520 (65%)
===========================================  ==============  ==============

So the artifact spends its whole 100-node budget on 77 distinct subjects when 274 exist. The
cap is not the problem — a committed JSON has to stay diff-readable, and L1 measured what
happens without one (400 findings = a 20k-line file nobody reviews). The problem is *what the
cap keeps*: 100 newest receipts, most of them re-answers of each other, instead of 100
distinct things this connection has learned. Consolidating **before** the cap is the whole
idea; everything else here is the discipline that makes it safe.

**Why this cannot simply "collapse to the newest".** That is what the Neo4j study scoped, and
measuring the corpus refused it. Of the 132 repeated subjects in the full corpus, **25 assert
conflicting numbers** — one run says ``Count: 50,048`` and another says ``Count: 30,949`` to
the same question, or ``Roas: 4.72`` against ``2.87``. Collapsing by recency would have
silently settled all 25, which is precisely the move Wave N1 exists to refuse: whether a
cancelled order counts as revenue is a business fact, not a derivable one, and recency is no
more a warrant than popularity was. The other 107 repeats fold away cleanly, which is the
whole point — the rule has to tell them apart.

So this module splits the two cases by asking *why* the conclusions differ:

- **Same query, different conclusion** ⇒ the data moved. The newest reading is simply the
  current one; the older readings are superseded, and nothing is lost by folding them away.
- **Different query, different conclusion** ⇒ a decision nobody took. The newest survives as
  the node's text, but the node is marked ``contested`` and **carries the alternative
  conclusions inline**, so the disagreement travels with the artifact instead of being
  resolved by timestamp. Settling it is :mod:`aughor.semantic.answer_divergence`'s job, and a
  human's decision.

"Same query" is :func:`~aughor.semantic.answer_divergence.semantic_key` — N1's fingerprint,
imported rather than re-derived, so the two surfaces cannot disagree about what counts as the
same query.

**Nothing is ever deleted.** Every input finding leaves as exactly one of: a survivor, a
superseded id on a survivor, or a contested variant carried on a survivor.
:meth:`ConsolidationReport.balanced` asserts that arithmetic, and a test pins it.

**Staleness is reachability, not a clock.** A finding grounded in a table that is no longer in
the ontology cannot be re-derived or checked; on the reference connection that is 22% of the
committed 100 and 39% of the full 794 — the same vanished-table population N1's impact run hit
independently when 16 of 34 questions came back uncomparable. Stale findings are **kept and
sorted last**, so the cap evicts what can no longer be verified before it evicts live
knowledge. They are never dropped: a stale finding is still evidence of what was once true
(C1's supersede-not-delete rule).

This is deliberately *not* the A3 source-version expiry the study scoped. A3 baselines are
keyed per-automation, not per-table, so there is no per-table version history to compare a
finding's age against — that variant would mark nothing stale today and only begin working
once a new store had accumulated history. Reachability needs no new store and works on the
corpus that exists.

Deterministic, read-only, no LLM.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from aughor.semantic.answer_divergence import question_key, semantic_key


def _bare(table: str) -> str:
    """``luxexperience.orders`` → ``orders`` — the projection compares tables unqualified."""
    return str(table or "").split(".")[-1].strip().lower()


def _tables_of(finding: dict) -> frozenset[str]:
    return frozenset(_bare(t) for t in (finding.get("tables") or []) if _bare(t))


#: Numeric literals in a headline: 1,234.56 · -40.08 · 2.80 · 36.34
_NUMBER_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


def _asserted_numbers(finding: dict) -> frozenset[float]:
    """The numbers a headline asserts — what a conclusion actually *claims*.

    **Why not compare the prose.** The first cut of this module compared normalized headline
    text and reported 45 of 100 survivors as contested. Reading them refuted the number: the
    receipt headline is usually a TITLE, not a conclusion — *"Total sales by product category"*
    versus *"Total sales (EUR) by product category"* versus *"Total sales by product category
    (EUR)"* are one finding written three ways, and *"Monthly order counts by platform"* versus
    *"Monthly order count by platform"* differ by a plural. Flagging those as decisions
    somebody must take is the wolf-crying #226 caught in the divergence detector, one layer up.

    What survives the rephrasings is the arithmetic: *"Gross Margin Pct: -40.08%"* against
    *"Gift_sets has the lowest gross margin at 36.34%"* is a real disagreement, and
    *"Total Attributed Revenue Eur: €2.80B"* against *"Roas: 13.99"* is two different questions
    wearing one label. So conclusions are compared on the numbers they assert — the same move
    ``_result_digest`` makes in :mod:`aughor.semantic.answer_divergence`, which deliberately
    excludes column names for exactly this reason.

    Headlines that assert no number cannot be told apart this way, and the honest answer is
    then "not in conflict": the query-level disagreement is N1's detector to find and a human's
    to settle, and a consolidation step guessing at it from prose would only add noise.
    """
    text = str(finding.get("text") or "")
    out: set[float] = set()
    for tok in _NUMBER_RE.findall(text):
        try:
            out.add(round(float(tok.replace(",", "")), 4))
        except ValueError:
            continue
    return frozenset(out)


def subject_key(finding: dict) -> tuple:
    """What makes two findings the *same subject*: one question, over one set of tables.

    A finding with no question never groups (it keys on its own id). The explorer store's
    findings carry no question text, and guessing that two of them answer the same thing
    because their headlines rhyme is how a consolidation step starts destroying evidence.
    """
    q = question_key(str(finding.get("question") or ""))
    if not q:
        return ("id", str(finding.get("id") or id(finding)))
    return ("q", q, _tables_of(finding))


@dataclass
class ConsolidationReport:
    """What consolidation did, in numbers that have to add up."""

    findings_in: int = 0
    survivors: int = 0
    superseded: int = 0            # identical-conclusion (or same-query) repeats folded away
    contested_subjects: int = 0    # survivors marked contested
    contested_variants: int = 0    # alternative conclusions carried on those survivors
    stale: int = 0                 # survivors whose grounding no longer resolves

    @property
    def balanced(self) -> bool:
        """Count in == count out. Nothing silently lost — the study's gate for N3."""
        return self.findings_in == self.survivors + self.superseded + self.contested_variants

    def to_dict(self) -> dict[str, Any]:
        return {"findings_in": self.findings_in, "survivors": self.survivors,
                "superseded": self.superseded, "contested_subjects": self.contested_subjects,
                "contested_variants": self.contested_variants, "stale": self.stale,
                "balanced": self.balanced}


@dataclass
class _Group:
    """One subject's findings, in input order (newest first)."""

    members: list[dict] = field(default_factory=list)


def _mark_stale(survivor: dict, live_tables: Optional[set[str]]) -> bool:
    """Flag a survivor whose grounding has vanished. Returns whether it is stale.

    ``live_tables=None`` means "the ontology could not be read" — and an unknown ontology
    marks NOTHING stale rather than marking EVERYTHING stale. A failed lookup that expires
    the whole corpus is the silent-catastrophe shape; refusing to answer is correct here.
    """
    if live_tables is None:
        return False
    tables = _tables_of(survivor)
    if not tables:
        return False
    gone = sorted(tables - live_tables)
    if not gone:
        return False
    survivor["stale"] = True
    survivor["stale_reason"] = "grounding vanished: " + ", ".join(gone)
    return True


def consolidate(
    findings: list[dict], *, live_tables: Optional[set[str]] = None,
) -> tuple[list[dict], ConsolidationReport]:
    """Fold repeated subjects together and mark unreachable ones stale.

    ``findings`` arrive newest-first (the loader's order) and that order is preserved among
    survivors, except that **stale survivors sort last** so a downstream cap evicts what can no
    longer be verified before it evicts live knowledge.

    ``live_tables`` is the set of bare table names currently in the ontology; ``None`` disables
    staleness marking entirely (see :func:`_mark_stale`).

    Input findings are not mutated — survivors are shallow copies carrying the extra keys.
    """
    report = ConsolidationReport(findings_in=len(findings))
    if not findings:
        return [], report

    groups: dict[tuple, _Group] = {}
    order: list[tuple] = []
    for f in findings:
        k = subject_key(f)
        if k not in groups:
            groups[k] = _Group()
            order.append(k)
        groups[k].members.append(f)

    live: list[dict] = []
    stale: list[dict] = []
    for k in order:
        members = groups[k].members
        survivor = dict(members[0])          # newest — the loader's order is newest-first
        rest = members[1:]

        # Split the older members: a different QUERY reaching a different CONCLUSION is a
        # decision nobody took; anything else is the same finding again (or the same query
        # over data that moved), and the newest reading supersedes it.
        s_key = semantic_key(str(survivor.get("sql") or ""))
        s_nums = _asserted_numbers(survivor)
        superseded_ids: list[str] = []
        variants: list[dict] = []
        for other in rest:
            o_nums = _asserted_numbers(other)
            # Both must ASSERT numbers for the assertions to be in conflict; a title has no
            # claim to disagree with (see :func:`_asserted_numbers`).
            differs_in_conclusion = bool(s_nums) and bool(o_nums) and o_nums != s_nums
            differs_in_query = semantic_key(str(other.get("sql") or "")) != s_key
            if differs_in_conclusion and differs_in_query:
                variants.append({
                    "id": str(other.get("id") or ""),
                    "text": str(other.get("text") or ""),
                    "sql": str(other.get("sql") or ""),
                    "generated_at": str(other.get("generated_at") or ""),
                })
            else:
                superseded_ids.append(str(other.get("id") or ""))

        if superseded_ids:
            survivor["supersedes"] = len(superseded_ids)
            survivor["superseded_ids"] = superseded_ids
            report.superseded += len(superseded_ids)
        if variants:
            # The node's text is still the newest reading, but the node SAYS it is unsettled
            # and ships the alternatives. Recency is not a warrant (N1); labelling is honest,
            # resolving-by-timestamp is not.
            survivor["contested"] = True
            survivor["contested_variants"] = variants
            report.contested_subjects += 1
            report.contested_variants += len(variants)

        (stale if _mark_stale(survivor, live_tables) else live).append(survivor)

    report.stale = len(stale)
    survivors = live + stale
    report.survivors = len(survivors)
    return survivors, report


def live_tables_for(connection_id: str, schema_name: Optional[str] = None) -> Optional[set[str]]:
    """Bare table names currently in the connection's ontology, or ``None`` if unreadable.

    ``None`` is load-bearing: it means "unknown", and :func:`consolidate` marks nothing stale
    on unknown rather than expiring the corpus because a lookup failed.
    """
    try:
        from aughor.ontology.store import load_latest_ontology

        onto = load_latest_ontology(connection_id, schema_name)
    except Exception as exc:
        from aughor.kernel.errors import tolerate

        tolerate(exc, "staleness marking degrades to 'unknown' when the ontology is unreadable",
                 counter="context_graph.consolidation_ontology")
        return None
    if onto is None:
        return None

    live: set[str] = set()
    mapping = getattr(onto, "entity_to_tables", None)
    if isinstance(mapping, dict):
        for tables in mapping.values():
            for t in tables or []:
                if _bare(t):
                    live.add(_bare(t))
    for ent in (getattr(onto, "entities", {}) or {}).values():
        for attr in ("physical_table", "table", "name"):
            v = getattr(ent, attr, None)
            if isinstance(v, str) and _bare(v):
                live.add(_bare(v))
    return live or None
