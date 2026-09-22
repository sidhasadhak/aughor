"""R13 — named research-starter playbooks + per-space curated questions.

A small library of NAMED, deterministic research playbooks (wire study #2,
docs/DATABRICKS_HAR_CANVAS_BIRTH_STUDY_2026-07-16.md) — one-click
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
from typing import Optional


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
        # A revenue ranking can never find losses (segment revenue is never negative) —
        # the question must NAME the loss lenses so the intake can't reduce it to one.
        question=("Where are we losing money? Quantify money that walks back out — "
                  "refunds, cancellations, chargebacks, discounts — as a share of gross "
                  "and find the segments where that leakage rate concentrates; if the "
                  "data carries capacity (seats, slots, inventory), compute utilization "
                  "against the best-performing segment and the value of closing the gap. "
                  "Rank below-benchmark revenue contribution only as context, and do not "
                  "declare anything profitable if cost data is absent."),
        mode="investigate",
        purpose="profitability",
        description="A deep investigation into leakage, utilization gaps and "
                    "underperforming segments — and the size of the opportunity.",
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


PACKAGE_SUGGESTIONS_CAP = 4


def connection_industry(connection_id: str, schema: str = "") -> str:
    """The industry a connection resolves to, the way the explorer resolves it: the workspace's
    declared industry wins, else the stored business profile's inferred one. "" when neither."""
    profile_industry = ""
    try:
        from aughor.business_profile import store as _pstore
        bp = _pstore.load(connection_id, schema or None)
        profile_industry = (getattr(bp, "industry", "") or "").strip() if bp is not None else ""
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the stored business profile is best-effort for the industry",
                 counter="starters.package", conn_id=connection_id or None)
    try:
        from aughor.orgsettings import resolve_industry
        from aughor.workspace.store import workspace_for_connection
        return resolve_industry(profile_industry, workspace_for_connection(connection_id))
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "workspace industry resolution is best-effort; the profile's industry stands",
                 counter="starters.package", conn_id=connection_id or None)
        return profile_industry


def package_suggestions(connection_id: str, schema: str = "", *, industry: Optional[str] = None,
                        cap: int = PACKAGE_SUGGESTIONS_CAP) -> list[dict]:
    """IP (2026-09-22) — the questions the connection's ACTIVE industry package declares, as
    suggestion chips: canonical questions route as ``ask``, diagnostic ones as ``investigate``,
    canonical first, ``cap`` in all. Each carries ``source: "package"``, the pack ids and the
    purpose tag, so a route receipt can say where the question came from. Deterministic, no model.
    ``[]`` — the common case — when the connection resolves to no industry with an active package,
    so a deployment without one gets a byte-identical payload. ``industry`` is injectable for tests."""
    try:
        eff = industry if industry is not None else connection_industry(connection_id, schema)
        if not eff:
            return []
        from aughor.business_profile.metric_kb import package_questions
        pq = package_questions(eff)
        if not pq["packs"]:
            return []
        packs = ",".join(pq["packs"])
        out: list[dict] = []
        for mode, questions in (("ask", pq["canonical"]), ("investigate", pq["diagnostic"])):
            for q in questions:
                if len(out) >= cap:
                    break
                if any(o["text"] == q for o in out):
                    continue
                out.append({"text": q, "mode": mode, "source": "package", "pack": packs,
                            "purpose": "package_question"})
        return out
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "package question suggestions are best-effort",
                 counter="starters.package", conn_id=connection_id or None)
        return []


def starter_payload(connection_id: str, schema: str = "") -> list[dict]:
    """The full starter list for one space: the named library, then curated."""
    return named_starters() + curated_questions(connection_id, schema)
