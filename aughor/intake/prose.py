"""KI-2's deferred half (§3.10) — the LLM prose mapper, and the falsifier that judges it.

A markdown page or pasted text becomes typed candidates through ONE model call on the
provider chain (`get_provider("coder")` — role from config, no model id here, metered
like every other call). The model's output is a CONTRACT, not a result: it passes
through deterministic validation that drops the nameless, demotes formula-less
metrics to prose definitions, forces every synonym to the `llm_candidate` tier (so
the synonyms prompt block ignores them until a human promotes), and tags everything
`mined:llm` so a reviewer always knows which hand wrote it.

The mapper emits candidates ONLY — the lane is what stands between a hallucinated
formula and the prompt. And the arc's own falsifier is instrumented here: the human
edit-rate on LLM-extracted candidates is measured and PUBLISHED per import and in
aggregate. §3.10: if it stays above ~50% after prompt iteration, the mapper parks and
the deterministic paths remain — a lane full of junk candidates teaches reviewers to
rubber-stamp, which poisons the same verdict stream Arc MI trains on.

Nothing in this module runs at import time; tests patch :func:`extract` and never
spend a token.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

#: Bound on one import's text. One model call per import; a book is not an import.
MAX_TEXT_CHARS = 60_000

#: Per-section cap after validation — a runaway extraction is judgement, not data.
_SECTION_CAP = 50

#: The falsifier threshold §3.10 names. Published with the stats, decided by a human.
EDIT_RATE_THRESHOLD = 0.5

_SYSTEM = """You extract an organisation's data-vocabulary from prose. Return ONLY \
facts the text explicitly states — never infer, never invent, never complete a \
half-stated formula. Empty lists are the correct answer for anything absent.

- metrics: only where the text literally states a formula or SQL expression for a \
named measure. Copy the formula as written. A metric described only in words does \
NOT belong here.
- definitions: named business terms or measures the text defines in words. \
`body` stays close to the text's own wording.
- synonyms: only where the text says one term MEANS another named thing \
("X is also called Y", "the finance team says Y for X").
- rules: standing business rules about how data must be counted, filtered or \
interpreted ("revenue counts only completed orders").
- glossary: only where the text describes a NAMED table or its columns.
"""


class ExtractedMetric(BaseModel):
    name: str
    label: str = ""
    sql: str = ""
    unit: str = ""
    owner: str = ""
    caveats: str = ""


class ExtractedDefinition(BaseModel):
    title: str
    body: str


class ExtractedSynonym(BaseModel):
    term: str                       # the alias the text introduces
    means: str                      # the canonical thing it names
    subject_kind: str = "term"      # table | column | metric | term


class ExtractedRule(BaseModel):
    title: str
    body: str


class ExtractedGlossaryTable(BaseModel):
    table: str
    description: str = ""
    columns: dict[str, str] = Field(default_factory=dict)   # column → description


class ProseExtraction(BaseModel):
    metrics: list[ExtractedMetric] = Field(default_factory=list)
    definitions: list[ExtractedDefinition] = Field(default_factory=list)
    synonyms: list[ExtractedSynonym] = Field(default_factory=list)
    rules: list[ExtractedRule] = Field(default_factory=list)
    glossary: list[ExtractedGlossaryTable] = Field(default_factory=list)


def extract(text: str) -> ProseExtraction:
    """ONE structured model call on the provider chain. Raises what the chain raises
    (`NoModelConfigured` included) — the router turns failures into a plain answer,
    and the deterministic doors keep working without any model at all."""
    from aughor.llm.provider import get_provider

    return get_provider("coder").complete(_SYSTEM, text, ProseExtraction,
                                          temperature=0.0)


def to_sections(extraction: ProseExtraction) -> dict:
    """The deterministic half: model output → lane sections, validated hard.

    Every dropped or demoted entry is a rule, not a judgement call: nameless rows
    drop, a metric without a stated formula is a DEFINITION (the same demotion the
    CSV mapper applies), synonyms are forced to `llm_candidate` (prompt-invisible
    until a person promotes), and everything carries the `mined:llm` tag."""
    from aughor.ontology.vocabulary import SUBJECT_KINDS

    sections: dict[str, list] = {}

    metrics, definitions = [], []
    for m in extraction.metrics[:_SECTION_CAP]:
        name = m.name.strip()
        if not name:
            continue
        if m.sql.strip():
            row = {"name": name.lower().replace(" ", "_"),
                   "label": m.label.strip() or name, "sql": m.sql.strip()}
            for k in ("unit", "owner", "caveats"):
                if getattr(m, k).strip():
                    row[k] = getattr(m, k).strip()
            metrics.append(row)
        elif m.caveats.strip() or m.label.strip():
            definitions.append({"title": name, "body": (m.caveats or m.label).strip(),
                                "tags": ["mined:llm"]})
    for d in extraction.definitions[:_SECTION_CAP]:
        if d.title.strip() and d.body.strip():
            definitions.append({"title": d.title.strip(), "body": d.body.strip(),
                                "tags": ["mined:llm"]})

    synonyms = []
    for s in extraction.synonyms[:_SECTION_CAP]:
        term, means = s.term.strip(), s.means.strip()
        if not term or not means:
            continue
        kind = s.subject_kind.strip().lower()
        synonyms.append({"subject_kind": kind if kind in SUBJECT_KINDS else "term",
                         "subject_id": means, "synonym": term,
                         "source": "llm_candidate",
                         "note": "LLM-extracted from prose; promote to human if right"})

    rules = [{"title": r.title.strip(), "body": r.body.strip(), "tags": ["mined:llm"]}
             for r in extraction.rules[:_SECTION_CAP]
             if r.title.strip() and r.body.strip()]

    glossary = []
    for g in extraction.glossary[:_SECTION_CAP]:
        if not g.table.strip():
            continue
        row: dict = {"table": g.table.strip()}
        if g.description.strip():
            row["description"] = g.description.strip()
        cols = {c.strip(): {"description": v.strip()}
                for c, v in g.columns.items() if c.strip() and v.strip()}
        if cols:
            row["columns"] = cols
        if len(row) > 1:
            glossary.append(row)

    for key, rows in (("metrics", metrics), ("definitions", definitions),
                      ("synonyms", synonyms), ("rules", rules), ("glossary", glossary)):
        if rows:
            sections[key] = rows
    return sections
