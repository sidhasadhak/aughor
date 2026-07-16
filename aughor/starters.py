"""R13 — named research-starter playbooks + per-space curated questions.

The Databricks ``curated-questions`` / ``research_agent_*`` analog (wire study
#2): a small library of NAMED, deterministic research playbooks — one-click
Deep-Research starters, distinct from free-typed questions — plus per-space
curated questions projected from the R8 doc tree's analyst questions.

Everything here is a template, not a model call:

  • Each named starter declares its route up front (``mode`` — "investigate"
    pins the deep path, "explore" pins the R9 landscape wave via the
    ``AskRequest.mode`` override) and carries a ``purpose`` tag (the R10 seam,
    provenance on the route receipt).
  • The explore-mode starters are PHRASED wide on purpose ("Profile …",
    "Characterize …") so that even a client that drops the ``mode`` field gets
    routed to the explore wave by R9's deterministic ``is_wide_question`` —
    the template and the router agree by construction (locked by a test).
  • Curated questions come from the doc tree (``DocNode.questions``, previously
    CLI-only), ordered by the R14 ``query_popularity`` fact then ``row_count``
    — the tables people actually use ask their questions first.

Surfaced through ``GET /suggestions`` behind the ``starters.library`` flag
(default-off; the response is byte-identical when off).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ResearchStarter:
    """One named, deterministic research playbook."""
    id: str
    title: str
    question: str
    mode: str                 # "investigate" | "explore"
    purpose: str              # the R10 purpose tag (provenance)
    description: str = ""
    source: str = "library"   # "library" | "curated"
    table: str = ""           # curated only: the table that asked it

    def payload(self) -> dict:
        d = asdict(self)
        d["text"] = d.pop("question")   # the chip contract field name
        return d


STARTERS: tuple[ResearchStarter, ...] = (
    ResearchStarter(
        id="outlier_entities",
        title="Interesting outlier entities",
        question=("Profile the most unusual entities in this data — which specific "
                  "records stand out as extreme outliers, and on which measures?"),
        mode="explore",
        purpose="outlier_scan",
        description="A landscape scan that surfaces extreme entities by ID with "
                    "what makes each unusual.",
    ),
    ResearchStarter(
        id="where_are_we_losing_money",
        title="Where are we losing money?",
        question=("Where are we losing money? Find the segments, products or routes "
                  "with negative or below-benchmark contribution and quantify the gap."),
        mode="investigate",
        purpose="profitability",
        description="A deep investigation into underperforming segments and the "
                    "size of the opportunity.",
    ),
    ResearchStarter(
        id="data_quality_scan",
        title="Data quality scan",
        question=("Characterize the data quality across this schema — gaps, "
                  "impossible values, duplicates and inconsistent grains."),
        mode="explore",
        purpose="data_quality",
        description="A landscape scan for quality hazards before you trust the numbers.",
    ),
)


def named_starters() -> list[dict]:
    """The library as chip payloads (id, title, text, mode, purpose, description)."""
    return [s.payload() for s in STARTERS]


def curated_questions(connection_id: str, schema: str = "", *, tree=None,
                      limit: int = 6) -> list[dict]:
    """Per-space curated questions from the R8 doc tree's analyst questions.

    Round-robins across tables (first question of each table before any second)
    so one wide table can't crowd the list; tables order by the R14
    ``query_popularity`` fact, then ``row_count``. Deterministic; [] when no doc
    tree has been built (the R12 birth job / ``ontology.autodoc`` produce one).
    ``tree`` is injectable for tests."""
    try:
        if tree is None:
            from aughor.ontology.doctree import load_doc_tree
            tree = load_doc_tree(connection_id, schema or "default")
        if tree is None:
            return []
        tables = [n for n in tree.nodes.values() if n.kind == "table" and n.questions]
        tables.sort(key=lambda n: (n.facts.get("query_popularity") or 0,
                                   n.facts.get("row_count") or 0), reverse=True)
        out: list[dict] = []
        for rank in range(3):                       # doc tree caps at 3 questions/table
            for t in tables:
                if rank < len(t.questions) and len(out) < limit:
                    out.append(ResearchStarter(
                        id=f"curated:{t.title}:{rank}",
                        title=t.title,
                        question=t.questions[rank],
                        mode="investigate",
                        purpose="curated_question",
                        source="curated",
                        table=t.title,
                    ).payload())
            if len(out) >= limit:
                break
        return out
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "curated starter questions are best-effort",
                 counter="starters.library", conn_id=connection_id or None)
        return []


def starter_payload(connection_id: str, schema: str = "") -> list[dict]:
    """The full starter list for one space: the named library, then curated."""
    return named_starters() + curated_questions(connection_id, schema)
