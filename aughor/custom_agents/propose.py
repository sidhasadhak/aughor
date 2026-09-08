"""Describe an agent in a sentence; get a drafted one back, with its evidence.

The agent analogue of :mod:`aughor.automations.propose`, and it exists for the same
reason: the fields that decide whether an agent can answer anything — which connection,
which schema, which documents — are exactly the fields a person cannot fill in before
they know the catalogue. So the platform reads the catalogue and drafts them, and the
person CERTIFIES rather than composes.

Three rules this module is built around, none of them negotiable:

* **Propose, never execute.** Nothing here saves. The return value is a draft plus the
  reasons for it; creation stays behind the human accept that ``spotlight_act.draft_agent``
  already routes through the approvals inbox. A drafted agent that quietly appeared in the
  chat picker would be a grant nobody made.
* **Only fields that reach the runtime.** The draft fills ``GOVERNING_FIELDS`` and the
  name, and nothing else. A drafted knob that changes no token of the prompt teaches the
  reader the page lies.
* **The model drafts questions; it may not certify answers.** Goldens come back as
  QUESTIONS only. ``reference_sql`` is deliberately absent from the schema — a suite the
  model writes for itself measures nothing, so the SQL is a human's to write. That is a
  design law, not an omission.

Pure by construction: the caller supplies the catalogue, the documents and the packs, and
``provider`` is injectable. The suite exercises every path here without a database and
without spending a token.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

#: Eval is SYNCHRONOUS — up to 20 serial model calls inside one HTTP request
#: (``MAX_GOLDENS_PER_EVAL``). Drafting the cap's worth would make the first Prove click a
#: multi-minute hang, so a proposal drafts a suite a person can actually certify in a
#: sitting and leaves room to add more.
MAX_DRAFTED_GOLDENS = 6

#: Snowflake Cortex recommends staying under ten tables; past roughly this many the scope
#: has stopped being a scope. Advice on the draft, never a refusal — a wide agent is a
#: legitimate thing to want, it just should not be the accident it currently is.
WIDE_SCOPE_TABLES = 30


class ProposedGolden(BaseModel):
    """A question worth being right about. NOTE the absence of ``reference_sql``."""
    question: str = ""
    why: str = ""


class ProposedAgent(BaseModel):
    name: str = ""
    purpose: str = ""
    instructions: str = ""
    schema_scope: str = ""
    doc_ids: list[str] = Field(default_factory=list)
    pack_ids: list[str] = Field(default_factory=list)
    goldens: list[ProposedGolden] = Field(default_factory=list)
    #: Why THIS scope — named tables, in the drafter's own words. Rendered beside the
    #: choice so a person can disagree with the reasoning, not just the result.
    evidence: str = ""
    notes: str = ""


@dataclass
class AgentProposal:
    verdict: str                                    # "proposed" | "refused"
    reason: str = ""
    draft: dict = field(default_factory=dict)
    goldens: list[dict] = field(default_factory=list)
    #: Code-written, never the model's. See `_disclosures`.
    disclosures: list[str] = field(default_factory=list)
    evidence: str = ""
    notes: str = ""

    def as_response(self) -> dict:
        return {"verdict": self.verdict, "reason": self.reason, "draft": self.draft,
                "goldens": self.goldens, "disclosures": self.disclosures,
                "evidence": self.evidence, "notes": self.notes}


_SYS = """\
You configure DATA AGENTS for Aughor. An agent is one record: a SCOPE (where it may look)
and a STANCE (how it should answer). It is not a workflow and has no steps.

You will be given this deployment's real catalogue, documents and packs. Draft using ONLY
those; never invent a schema, a table, a document id or a pack id.

Rules that decide whether the draft is accepted at all:
- `schema_scope` must be one of the schema names listed, or "" for all of them. Prefer the
  narrowest schema that covers the request: an agent pointed at everything is an agent
  nobody can judge.
- `doc_ids` and `pack_ids` must be ids from the lists given. Attach a document when it
  plainly bears on the request; attaching nothing is a real choice with a real cost, so do
  not attach padding to look thorough.
- `instructions` is the STANCE: how to answer, what to prefer, what to refuse, which
  grain and which caveats. Do not restate the schema there — the scope already says where
  it may look, and duplicating it just makes the prompt longer and staler.
- `purpose` is ONE short line: how a supervisor picks this agent from a roster.
- `evidence` names the actual tables that made you choose this scope. A person must be
  able to disagree with your reasoning, not merely with your answer.
- `goldens` are QUESTIONS this agent must get right — the ones where being wrong would
  matter, not the ones that are easy to check. Never write SQL; a human certifies the
  answers. Draft at most %(max_goldens)d.
- If the catalogue cannot support the request, return an empty `name` and say why in
  `notes`. A half-scoped agent that looks finished is worse than a refusal.

Write `instructions` in the user's own vocabulary. Prefer the smallest agent that does
what was asked.
"""


def _catalogue_section(catalogue: Sequence[dict]) -> str:
    """Schemas and their tables, as the deployment actually has them."""
    if not catalogue:
        return ("CATALOGUE: (empty — this connection exposes no readable schemas)\n"
                "You cannot scope an agent here. Refuse and say so.")
    lines = ["CATALOGUE (schema → tables):"]
    for schema in catalogue:
        tables = [str(t.get("name", "")) for t in (schema.get("tables") or [])]
        name = str(schema.get("name") or "") or "(default)"
        shown = ", ".join(tables[:40]) or "(no tables)"
        more = f" … +{len(tables) - 40} more" if len(tables) > 40 else ""
        lines.append(f"- {name} ({len(tables)} tables): {shown}{more}")
    return "\n".join(lines)


def _documents_section(documents: Sequence[dict]) -> str:
    if not documents:
        return ("DOCUMENTS: none indexed on this deployment.\n"
                "Leave `doc_ids` empty — there is nothing to attach.")
    lines = ["DOCUMENTS (id — title):"]
    for d in documents[:60]:
        lines.append(f"- {d.get('id')} — {str(d.get('title') or d.get('name') or '')[:90]}")
    return "\n".join(lines)


def _packs_section(packs: Sequence[dict]) -> str:
    if not packs:
        return "PACKS: none available. Leave `pack_ids` empty."
    lines = ["PACKS (id — what it steers):"]
    for p in packs[:40]:
        lines.append(f"- {p.get('id')} — {str(p.get('description') or p.get('name') or '')[:90]}")
    return "\n".join(lines)


def _tables_in_scope(catalogue: Sequence[dict], schema_scope: str) -> int:
    total = 0
    for schema in catalogue:
        if schema_scope and str(schema.get("name") or "") != schema_scope:
            continue
        total += len(schema.get("tables") or [])
    return total


def _disclosures(draft: dict, catalogue: Sequence[dict], goldens: list) -> list[str]:
    """What the person must be told, written by CODE.

    Every line here is a fact about the draft that the drafter has an incentive to omit and
    no obligation to notice. None of them is left to the model.
    """
    out: list[str] = []

    if not draft.get("doc_ids"):
        # The trap every agent the old form built fell into, undisclosed: the retrieval
        # seam fails CLOSED for an active agent, so no documents is not "no preference".
        out.append(
            "No documents attached — this is RESTRICTIVE, not neutral. An active agent "
            "with no documents retrieves FEWER than asking with no agent at all.")

    n = _tables_in_scope(catalogue, str(draft.get("schema_scope") or ""))
    if not draft.get("schema_scope"):
        out.append(f"Scope is every schema on this connection ({n} tables). An agent that "
                   "has not been told where to look cannot be judged on what it says.")
    elif n > WIDE_SCOPE_TABLES:
        out.append(f"Scope covers {n} tables — wide enough that answers will be hard to "
                   "attribute. Narrowing it is usually the cheapest accuracy win.")

    if goldens:
        out.append(f"{len(goldens)} golden question(s) drafted, none CERTIFIED: a golden "
                   "measures nothing until a human writes its reference SQL. The model is "
                   "not allowed to write it — a suite it writes for itself measures itself.")
    else:
        out.append("No goldens drafted — this agent will ship unmeasured.")

    return out


def propose_agent(description: str, *, conn_id: str,
                  catalogue: Sequence[dict],
                  documents: Sequence[dict] = (),
                  packs: Sequence[dict] = (),
                  provider: Any = None,
                  validator: Optional[Any] = None) -> AgentProposal:
    """Draft an agent for ``description``. Validates. Never saves.

    ``validator`` defaults to the store's ``validate_agent_draft`` — THE rule set the
    create route uses. A draft is refused by the same rules a save would refuse it by, so
    the flow can never render an accept button that 422s.
    """
    if not (description or "").strip():
        return AgentProposal(verdict="refused",
                             reason="describe what the agent should be able to answer")

    system = (_SYS % {"max_goldens": MAX_DRAFTED_GOLDENS} + "\n\n"
              + _catalogue_section(catalogue) + "\n\n"
              + _documents_section(documents) + "\n\n"
              + _packs_section(packs))

    try:
        prov = provider
        if prov is None:
            # The strong reasoner, for the same reason the chain proposer states: this is
            # judgment — pick a scope, write a stance, choose what matters — and the fast
            # tier drafts agents that read plausibly and scope wrongly.
            from aughor.llm.provider import get_provider
            prov = get_provider("coder")
        drafted = prov.complete(system=system, user=description,
                                response_model=ProposedAgent, temperature=0.1)
    except Exception as exc:
        logger.warning("agent proposer failed: %s", exc)
        return AgentProposal(verdict="refused",
                             reason=f"the proposer could not draft an agent: {exc}")

    if not (drafted.name or "").strip():
        # It was asked to refuse in words rather than invent a scope it could not support.
        return AgentProposal(verdict="refused", notes=drafted.notes,
                             reason=drafted.notes or
                             "this catalogue cannot support that agent")

    known_schemas = {str(s.get("name") or "") for s in catalogue}
    schema_scope = str(drafted.schema_scope or "")
    if schema_scope and schema_scope not in known_schemas:
        # A hallucinated schema is the free-text `schema_scope` defect returning by another
        # door: it 409s on every ask, silently, until somebody asks something.
        logger.info("agent proposer named unknown schema %r; widening to all", schema_scope)
        drafted.notes = (drafted.notes + " " if drafted.notes else "") + (
            f"The drafter named a schema this connection does not have ({schema_scope!r}); "
            "scope was widened to all schemas rather than left pointing at nothing.")
        schema_scope = ""

    known_docs = {str(d.get("id")) for d in documents}
    known_packs = {str(p.get("id")) for p in packs}
    draft = {
        "name": drafted.name.strip(),
        "purpose": (drafted.purpose or "").strip(),
        "instructions": (drafted.instructions or "").strip(),
        "connection_id": conn_id,
        "schema_scope": schema_scope,
        "doc_ids": [d for d in drafted.doc_ids if d in known_docs],
        "pack_ids": [p for p in drafted.pack_ids if p in known_packs],
    }

    check = validator
    if check is None:
        from aughor.custom_agents.store import validate_agent_draft
        check = validate_agent_draft
    problems = check(name=draft["name"], instructions=draft["instructions"],
                     connection_id=draft["connection_id"], doc_ids=draft["doc_ids"])
    if problems:
        return AgentProposal(verdict="refused", draft=draft, notes=drafted.notes,
                             reason="the drafted agent is not valid here: "
                                    + "; ".join(problems))

    goldens = [{"question": g.question.strip(), "why": (g.why or "").strip(),
                "reference_sql": "", "certified": False}
               for g in drafted.goldens[:MAX_DRAFTED_GOLDENS] if (g.question or "").strip()]

    return AgentProposal(
        verdict="proposed", draft=draft, goldens=goldens,
        disclosures=_disclosures(draft, catalogue, goldens),
        evidence=(drafted.evidence or "").strip(), notes=(drafted.notes or "").strip())
