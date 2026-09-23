"""ON-10 — the investigation's half of framing (ROADMAP §3.15, the second movement).

`aughor.ontology.framing` resolves a question's words against the declared ontology with no model and no store. This
module does the two things that take more than that. It reads the SERVED graph for the question's scope — the cached
ontology with every declaration overlaid, under the same scope law the ontology doors use — and a person's synonyms.
And, only when the question's words fit several declared definitions equally, it asks a model which of THEM the
question means. The model names one listed definition or none; a name that is not listed chooses nothing
(`frame_question` refuses it and says so). A model never writes a definition here.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from pydantic import BaseModel, Field

from aughor.ontology.framing import DEFAULT_HOPS, Frame, frame_question

logger = logging.getLogger(__name__)


class DefinitionChoice(BaseModel):
    definition: str = Field(default="", description=(
        "The name of the ONE listed definition the question means, copied exactly as listed — or an empty string "
        "when none of them is what the question asks about."))


class DefinitionChoiceWithConfidence(DefinitionChoice):
    """The same choice, asked to say how sure it is (flag ``framing.choice_confidence``).

    A separate model rather than a defaulted field on the one above, because adding a
    field to a response model CHANGES THE PROMPT: the schema the provider ships is part of
    what the model reads. Keeping them apart is what makes the flag's off-arm byte-identical
    to today, which is the only way the A/B measures the field and not the diff around it.
    """

    confidence: float = Field(default=0.0, description=(
        "How sure you are, from 0.0 to 1.0, that this is the definition the question means. Use the "
        "middle of the range when the listed definitions genuinely both fit — a low number here is a "
        "useful answer, not a failure."))


def _choice_confidence(choice: Any) -> float:
    """The model's own number, clamped — 0.0 when it was never asked for one."""
    try:
        return min(1.0, max(0.0, float(getattr(choice, "confidence", 0.0) or 0.0)))
    except (TypeError, ValueError):
        return 0.0


_CHOOSE_SYSTEM = (
    "You read a business question against definitions its business DECLARED. The question's words fit several of the "
    "listed definitions. Name the ONE the question means, exactly as it is listed, or return an empty string when none "
    "of them is what the question asks about. Never name anything that is not listed.")


def served_graph(connection_id: str, schema_name: Optional[str] = None):
    """The ontology an investigation on this scope reads: the cached graph for the schema — or, with no schema named,
    the connection's own configured schema — with every declaration overlaid. None when none is built. A schema that
    names nothing built is NOT answered with another schema's graph, unless the connection has only one."""
    from aughor.ontology.store import list_schemas, load_latest_ontology
    try:
        schema = schema_name
        if not schema:
            from aughor.db.registry import get_meta
            schema = (get_meta(connection_id) or {}).get("schema_name") or ""
        graph = load_latest_ontology(connection_id, schema) if schema else None
        if graph is None:
            built = list_schemas(connection_id)
            if len(built) == 1:
                graph = load_latest_ontology(connection_id, built[0])
        return graph
    except Exception as exc:  # noqa: BLE001 — no ontology is a frame with nothing in it, never a failed run
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the served ontology could not be read; the question is framed against nothing",
                 counter="framing.served_graph", conn_id=connection_id)
        return None


def person_synonyms(connection_id: str) -> list:
    """A person's synonyms on this connection — the human tier only: a mined or model-proposed synonym widens
    retrieval elsewhere, but a frame reads the business's words, and "a model suggested it" is not that."""
    try:
        from aughor.ontology.vocabulary import synonyms_for
        return [s for s in synonyms_for(connection_id) if s.source == "human"]
    except Exception as exc:  # noqa: BLE001
        from aughor.kernel.errors import tolerate
        tolerate(exc, "synonyms are an extra way to name a declaration; the frame reads declared names without them",
                 counter="framing.synonyms", conn_id=connection_id)
        return []


def choose_definition(frame: Frame, graph: Any, *, provider: Any = None, synonyms: Any = (),
                      dialect: str = "duckdb", conn_id: str = "", trace_id: str = "",
                      inv_id: str = "") -> Frame:
    """When the question's words fit several declared definitions equally, a model chooses which of them the question
    means. Unambiguous frames are returned untouched and cost no call."""
    if not frame.ambiguous:
        return frame
    listing = "\n".join(f"- {c.name}: {c.label} — {c.definition}" for c in frame.candidates())
    try:
        if provider is None:
            from aughor.llm.provider import get_provider
            provider = get_provider("fast")
        from aughor.kernel.flags import flag_enabled
        _model = (DefinitionChoiceWithConfidence if flag_enabled("framing.choice_confidence")
                  else DefinitionChoice)
        choice = provider.complete(
            system=_CHOOSE_SYSTEM,
            user=f"QUESTION: {frame.question}\n\nDECLARED DEFINITIONS THE WORDS FIT:\n{listing}\n\n"
                 "Which one does the question mean?",
            response_model=_model, temperature=0.0)
    except Exception as exc:  # noqa: BLE001 — an unchosen frame still lists every candidate
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the model could not choose among the declared definitions; the frame keeps all of them",
                 counter="framing.choose")
        return frame
    name = (getattr(choice, "definition", "") or "").strip()
    # Decision record: the menu is the listing the model was SHOWN (name: label — definition),
    # the label is the candidate's index, and "picked none of them" is a real -1 row. The
    # provider-failed path above records nothing — no decision was made there.
    from aughor.learning.decisions import record_decision
    _names = [c.name for c in frame.candidates()]
    _menu = [" ".join(f"{c.name}: {c.label} — {c.definition}".split()) for c in frame.candidates()]
    record_decision("framing.definition", frame.question, _menu,
                    label=_names.index(name) if name in _names else -1,
                    chosen=name if name in _names else "", source="llm",
                    confidence=_choice_confidence(choice),
                    conn_id=conn_id, trace_id=trace_id, inv_id=inv_id)
    if not name:
        frame.notes.append("a model read none of the declared definitions as what the question means")
        return frame
    return frame_question(frame.question, graph, synonyms=synonyms, hops=frame.hops, dialect=dialect, choice=name,
                          chosen_by="model")


def resolve_frame(question: str, connection_id: str, schema_name: Optional[str] = None, *, dialect: str = "duckdb",
                  provider: Any = None, choose: bool = True, hops: int = DEFAULT_HOPS,
                  trace_id: str = "", inv_id: str = "") -> Optional[Frame]:
    """The frame of ``question`` on its scope, a model's choice included when the words fit several definitions — or
    None when the scope has no ontology."""
    graph = served_graph(connection_id, schema_name)
    if graph is None:
        return None
    synonyms = person_synonyms(connection_id)
    frame = frame_question(question, graph, synonyms=synonyms, hops=hops, dialect=dialect)
    if choose and frame.ambiguous:
        frame = choose_definition(frame, graph, provider=provider, synonyms=synonyms, dialect=dialect,
                                  conn_id=connection_id, trace_id=trace_id, inv_id=inv_id)
    # PENDING item 12 — a question on a scope that declares definitions and reached none of them is
    # counted (the run's trace id, never the question's text), so how often wording misses is known.
    from aughor.ontology.framing_misses import record as _record_miss
    _record_miss(frame, graph, connection_id, schema_name, trace_id=trace_id, inv_id=inv_id)
    return frame


def frame_from_state(state: dict, *, dialect: str = "duckdb", provider: Any = None) -> Optional[Frame]:
    """The frame a run carries (the investigation door frames the question before the graph starts and hands the frame
    in), completed with a model's choice when it is still ambiguous — or framed here, for a caller that did not."""
    carried = state.get("ontology_frame")
    connection_id = state.get("connection_id", "") or ""
    schema = state.get("scope_schema", "") or None
    _trace = state.get("trace_id", "") or ""
    _inv = state.get("investigation_id", "") or ""
    if isinstance(carried, dict) and carried.get("question") == state.get("question"):
        try:
            frame = Frame.model_validate(carried)
        except Exception:  # noqa: BLE001 — a hand-edited checkpoint frames again, never reads as a frame
            frame = None
        if frame is not None:
            if not frame.ambiguous:
                return frame
            graph = served_graph(connection_id, schema)
            return choose_definition(frame, graph, provider=provider, synonyms=person_synonyms(connection_id),
                                     dialect=dialect, conn_id=connection_id,
                                     trace_id=_trace, inv_id=_inv) if graph is not None else frame
    if not connection_id:
        return None
    return resolve_frame(state.get("question", "") or "", connection_id, schema, dialect=dialect, provider=provider,
                         trace_id=_trace, inv_id=_inv)


__all__ = ["DefinitionChoice", "choose_definition", "frame_from_state", "person_synonyms", "resolve_frame",
           "served_graph"]
