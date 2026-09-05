"""The grounding context the SQL writer is given — assembled once, shown on demand.

Rec 5 of the 2026-07-11 platform study (flag ``ask.context_receipt``): the
*input-side* twin of the Trust Receipt. The Trust Receipt says what the answer
did; the grounding receipt says what the model was *grounded on* — the schema
slice chosen, glossary/business definitions, governed-metric bindings,
ambiguity-ledger priors (closed-loop corrections), dialect rules, trusted-query
templates, and which agent brief and pack are active.

Design (single source of truth, no drift): each grounding block has ONE producer
function here, wrapping the same underlying retriever the answer path already
calls (``retrieve_for_planning``, ``unified_metric_grounding``,
``build_corrections_section``, …). :func:`build_grounding_context` composes them
into a :class:`GroundingContext`; the quick ``/ask`` path and the ``GET
/ask/context`` endpoint both build blocks from these same producers, so the
receipt reflects the real grounding rather than a re-derivation that can diverge.

Staging note: the quick-``/ask`` assembly (``routers/investigations.py::
_stream_chat``) currently shares the pure *prepend* producers here (dialect
rules, agent brief, pack, trusted, corrections); its schema-linking + governed-metric
blocks are computed inline (entangled with canvas-scope resolution) and are a
deliberate follow-up to fold in. The value-index literal-binding block is
post-generation on the answer path (a guard, not a prompt block) and is not yet
surfaced here.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Optional

logger = logging.getLogger(__name__)


def _safe(fn: Callable[[], str], reason: str) -> str:
    """Run a block producer, degrading to '' on failure (a missing grounding block
    must never break the answer or the receipt) while still journaling the reason.

    Returns the producer's output VERBATIM (no stripping) so a producer shared with
    the answer path (dialect rules, agent brief, corrections) yields the byte-identical
    string the prompt used; presentation-time trimming happens in :class:`GroundingBlock`."""
    try:
        return fn() or ""
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, reason, counter="grounding.block")
        return ""


# ── Per-block producers — one wrapper per grounding source (the answer path's) ──

def dialect_rules_block() -> str:
    from aughor.rules import get_chat_rules_block
    return _safe(get_chat_rules_block, "grounding: dialect rules block")


def agent_brief(question: str = "", connection_id: str = "") -> str:
    from aughor.custom_agents.context import agent_brief_block
    return _safe(agent_brief_block, "grounding: active agent brief")


def pack_steering(question: str, connection_id: str = "",
                  schema_name: str = "") -> tuple[str, str]:
    """``(block, pack_id)`` for the deployed pack — ``("", "")`` if none steers.

    The pair exists because the explore path labels its run with the pack id, while the
    other two consumers want only the text. Both halves come from one resolve, so a
    caller can never report a pack that did not actually steer, or steer without being
    able to name the pack.
    """
    from aughor.packs.intake import injection_for_question, render_injection

    resolved: dict[str, str] = {}

    def _render() -> str:
        inj = injection_for_question(question, connection_id, schema_name)
        if inj is None:
            return ""
        resolved["pack_id"] = inj.pack_id
        return render_injection(inj)

    block = _safe(_render, "grounding: pack steering")
    return (block, resolved.get("pack_id", "")) if block else ("", "")


def pack_brief(question: str, connection_id: str = "", schema_name: str = "") -> str:
    """The deployed pack's steering block, or '' when nothing steers.

    The single producer for pack steering. Before this existed the payload had exactly
    one engine caller (``agent/explore.py``), so a pack bound to a custom agent sharpened
    exploration runs and nothing else — and this module's own receipt titled a block
    "Active agent / pack brief" while :func:`agent_brief` only ever rendered the *agent's*
    instructions. The receipt claimed pack coverage it did not have.

    ``schema_name`` is a schema NAME, not rendered DDL: it keys ``load_binding``, so
    handing it the schema TEXT that the neighbouring producers take would look up a
    binding under a multi-kilobyte key, find none, and return '' forever — a block that
    silently never fires. The registration below passes ``eff_schema`` for that reason.

    Inert by construction: '' unless the packs flag is on AND an active pack matches
    AND a human pinned a deploy binding on this connection.
    """
    return pack_steering(question, connection_id, schema_name)[0]


def custom_instructions(connection_id: str, canvas_id: str = "") -> str:
    """User-authored custom instructions — connection-level, plus the Canvas's own
    when the ask is canvas-scoped. The Sprint 53 surfaces (``PUT /connections/{id}/
    instructions``, the Canvas Configure panel's Instructions tab) stored this text
    from day one; this producer is what finally injects it. '' when nothing is
    stored, so a scope with no instructions keeps a byte-identical prompt."""
    from aughor.semantic.instructions import build_instructions_block
    return _safe(lambda: build_instructions_block(connection_id, canvas_id),
                 "grounding: custom instructions")


def vocabulary_synonyms(connection_id: str) -> str:
    """Human-curated business synonyms, rendered verbatim (not question-matched —
    an alias matters both for reading the question and for labelling the answer).
    Only the human tier renders; mined and model-proposed entries keep widening
    schema-linker retrieval and stay out of the prompt until a person promotes
    them. '' when the connection has none."""
    from aughor.ontology.vocabulary import build_synonyms_block
    return _safe(lambda: build_synonyms_block(connection_id),
                 "grounding: vocabulary synonyms")


def trusted_templates(question: str, connection_id: str) -> str:
    from aughor.semantic.trusted_queries import retrieve_trusted, build_trusted_block
    return _safe(lambda: build_trusted_block(retrieve_trusted(question, connection_id)),
                 "grounding: trusted query templates")


def correction_priors(question: str, connection_id: str) -> str:
    from aughor.feedback.priors import build_corrections_section
    return _safe(lambda: build_corrections_section(question, connection_id),
                 "grounding: ambiguity-ledger corrections")


def connection_glossary(question: str, connection_id: str) -> str:
    from aughor.semantic.connection_kb import retrieve_for_question
    return _safe(lambda: retrieve_for_question(question, connection_id),
                 "grounding: connection KB / glossary")


def kb_patterns(question: str, connection_id: str = "") -> str:
    from aughor.semantic.kb_retriever import retrieve_for_planning
    return _safe(lambda: retrieve_for_planning(question, top_k=2), "grounding: KB planning patterns")


def sql_examples(question: str, connection_id: str) -> str:
    from aughor.tools.prior_analyses import search_sql_examples
    return _safe(lambda: search_sql_examples(question, connection_id), "grounding: prior-analysis SQL examples")


def exploration_annotations(question: str, connection_id: str) -> str:
    from aughor.explorer.store import render_exploration_annotations
    return _safe(lambda: render_exploration_annotations(connection_id), "grounding: exploration annotations")


def causal_context(question: str, connection_id: str) -> str:
    from aughor.lifecycle.causal import build_causal_context_section
    return _safe(lambda: build_causal_context_section(question, conn_id=connection_id),
                 "grounding: causal context")


def external_docs(question: str, connection_id: str = "") -> str:
    from aughor.knowledge.indexer import build_external_context_section
    return _safe(lambda: build_external_context_section(question, top_k=2), "grounding: connection documents")


def governed_metrics(question: str, connection_id: str, *, db: Optional[object] = None,
                     schema: str = "", eff_schema: Optional[str] = None) -> str:
    """Governed-metric grounding — byte-identical to the quick ``/ask`` path's
    ``metrics_section``: the unified metric bindings (``unified_metric_grounding``,
    the SAME resolver Deep uses), plus — when a live ``db`` is given — the measure
    grain block and the metric-feasibility gap. Empty without a schema."""
    if not schema:
        return ""
    try:
        from aughor.semantic.canonical import unified_metric_grounding
        _mb = unified_metric_grounding(connection_id, eff_schema, schema_text=schema, question=question)
        out = (_mb + "\n\n") if _mb else ""
    except Exception:
        out = ""  # matches the answer path: a metric-grounding failure drops the block
    if db is not None:
        from aughor.semantic.data_understanding import build_data_understanding
        _gb = build_data_understanding(db, connection_id=connection_id, schema=schema).grain_block
        if _gb:
            out += _gb + "\n\n"
        from aughor.semantic.metric_feasibility import unsupported_metric_gap
        _fg = unsupported_metric_gap(question, schema)
        if _fg:
            out += "DATA AVAILABILITY — " + _fg + ".\n\n"
    return out


def schema_slice(question: str, connection_id: str, *, schema: str = "") -> str:
    """The schema-linked slice (relevant tables/columns) — the same pre-filter the
    answer path applies, with the SAME profile-derived budgets (A3 reconciled the
    old 4-vs-8 disagreement: a receipt must describe the prompt that actually ran),
    falling back to the full schema on failure (byte-identical to the answer
    path's fallback)."""
    if not schema:
        return ""
    try:
        from aughor.tools.schema_linker import link_schema_for_prompt
        return link_schema_for_prompt(question, schema, connection_id=connection_id)
    except Exception:
        logger.warning("schema-linking pre-filter failed; using full schema", exc_info=True)
        return schema


# The receipt's block order (prepends first, then the template body) with titles.
# ``needs_schema`` blocks are computed only when the caller resolved a schema.
_BLOCKS: list[tuple[str, str, Callable[..., str], bool]] = [
    ("dialect_rules", "Dialect rules", lambda q, c, **k: dialect_rules_block(), False),
    ("agent_brief", "Active agent brief", lambda q, c, **k: agent_brief(q, c), False),
    # eff_schema (the schema NAME), never k["schema"] (rendered DDL) — see pack_brief.
    ("pack", "Pack steering",
     lambda q, c, **k: pack_brief(q, c, k.get("eff_schema") or ""), False),
    ("instructions", "Custom instructions",
     lambda q, c, **k: custom_instructions(c, k.get("canvas_id") or ""), False),
    ("trusted", "Trusted query templates", lambda q, c, **k: trusted_templates(q, c), False),
    ("corrections", "Ambiguity-ledger priors (corrections)", lambda q, c, **k: correction_priors(q, c), False),
    ("governed_metrics", "Governed-metric bindings",
     lambda q, c, **k: governed_metrics(q, c, db=k.get("db"), schema=k.get("schema", ""),
                                        eff_schema=k.get("eff_schema")), True),
    ("schema_slice", "Schema slice (linked)",
     lambda q, c, **k: schema_slice(q, c, schema=k.get("schema", "")), True),
    ("glossary", "Connection glossary / business definitions", lambda q, c, **k: connection_glossary(q, c), False),
    ("synonyms", "Business synonyms (human-curated)",
     lambda q, c, **k: vocabulary_synonyms(c), False),
    ("kb_patterns", "Knowledge-base planning patterns", lambda q, c, **k: kb_patterns(q, c), False),
    ("sql_examples", "Prior-analysis SQL examples", lambda q, c, **k: sql_examples(q, c), False),
    ("exploration", "Exploration annotations", lambda q, c, **k: exploration_annotations(q, c), False),
    ("causal", "Causal context", lambda q, c, **k: causal_context(q, c), False),
    ("docs", "Connection documents", lambda q, c, **k: external_docs(q, c), False),
]


@dataclass
class GroundingBlock:
    key: str
    title: str
    content: str

    @property
    def present(self) -> bool:
        return bool((self.content or "").strip())

    @property
    def display(self) -> str:
        return (self.content or "").strip()


@dataclass
class GroundingContext:
    """The assembled grounding for one (question, connection) — every block the
    SQL writer would be given, whether or not it fired."""

    question: str
    connection_id: str
    blocks: list[GroundingBlock] = field(default_factory=list)

    @property
    def present(self) -> list[GroundingBlock]:
        return [b for b in self.blocks if b.present]

    def to_dict(self) -> dict:
        return {
            "question": self.question,
            "connection_id": self.connection_id,
            "blocks": [{"key": b.key, "title": b.title, "present": b.present, "content": b.display}
                       for b in self.blocks],
            "present_count": len(self.present),
        }

    def to_markdown(self) -> str:
        lines = [f"# Grounding for “{self.question}”", ""]
        present = self.present
        if not present:
            lines.append("_No grounding blocks fired for this question on this connection._")
            return "\n".join(lines)
        lines.append(f"_{len(present)} of {len(self.blocks)} grounding blocks active._")
        lines.append("")
        for b in present:
            lines.append(f"## {b.title}")
            lines.append("")
            lines.append("```")
            lines.append(b.display)
            lines.append("```")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"


def build_grounding_context(
    question: str,
    connection_id: str,
    *,
    db: Optional[object] = None,
    schema: str = "",
    eff_schema: Optional[str] = None,
    canvas_id: str = "",
) -> GroundingContext:
    """Assemble the grounding blocks for a (question, connection).

    ``schema`` (a rendered schema string) enables the schema-dependent blocks
    (governed metrics, schema slice); a live ``db`` additionally fills the grain +
    feasibility parts of the metrics block; ``canvas_id`` scopes the
    custom-instructions block to a Canvas. Every block is best-effort — a failing
    producer degrades to an empty block, never an error.
    """
    blocks: list[GroundingBlock] = []
    for key, title, producer, _needs in _BLOCKS:
        content = producer(question, connection_id, db=db, schema=schema, eff_schema=eff_schema,
                           canvas_id=canvas_id)
        blocks.append(GroundingBlock(key=key, title=title, content=content))
    return GroundingContext(question=question, connection_id=connection_id, blocks=blocks)
