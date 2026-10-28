"""Arc FA, FA-7 — what a custom agent would read for a question, read without asking a model.

A program built with any agent SDK reaches an Aughor agent through MCP or the headless doors, and every one of those
ASKS: a model writes SQL, it runs, an answer comes back. A program that wants to ground its own model on what an Aughor
agent knows — or to see what that agent would be handed before it trusts the answer — had no read. This is that read
(``agents.grounding_read`` until it was made unconditional, 2026-10-28), at two doors: the agent's HTTP door with its key
(``POST /doors/agents/{id}/grounding``) and the read-level MCP tool ``ground_agent`` over the session route
``GET /agents/custom/{id}/grounding``, where the agent gate holds and audits it like every other tool call.

What a read returns, and what it never does:

* **The blocks' content** — the grounding receipt's blocks (``agent/grounding.py``), assembled with the agent ACTIVE,
  the contextvar the ask door sets: its brief and lessons, its pack restriction, its own corrections, and only its own
  documents (fail-closed — an agent with none reads none). The connection and schema follow the ask path's rule: an
  explicit value that conflicts with the agent's binding is the ask door's 409, an unset one is the agent's.
* **Trimmed as the ask path trims**, because the producers ARE the ask path's: the clearance trim inside the trusted
  query, glossary and synonym retrievers runs under the caller's clearances, and the agent's document scope holds.
* **Every absent block, with why** — and a producer that failed says so rather than reading as "nothing matched".
* **The embedder, said**: whether this read called it, how often, and which backend — a hosted one may charge.
* **No chat model.** Nothing here asks one; the question frame is read without a model's choice.
* **The agent's grants and guardrails**, in a section the prompt never carries: what it may propose, how a run is capped.
* **How it differs from an answer**, said on every read.

Every read is journaled as ``agent.grounding_read`` — who read, which agent at which revision, the connection, the keys
of the blocks present and whether the embedder was called — never the question and never the content.

The chat-compatible endpoint (``doors.chat_completions``) is written down and not built: it waits until one is asked for.
"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException

#: The MCP tool a client sees.
MCP_TOOL = "ground_agent"
_AUDIT_KIND = "agent.grounding_read"

#: How a read differs from what an answer is given — said on every read, so nobody takes it for the prompt itself.
DIFFERS_FROM_ANSWER = (
    "Read from the producers the quick answer uses, with the agent active — but not the prompt byte for byte: the "
    "quick answer links the schema and binds governed metrics beside its canvas scope, and checks the values its SQL "
    "names after the SQL is written, which this read does not show. A deep analysis plans further reads of its own. "
    "Nothing here was sent to a model.")

#: Why a block is absent when its producer neither failed nor said why — keyed by every block the receipt carries
#: (a test holds this to `build_grounding_context`'s keys, so a new block cannot arrive without its sentence).
ABSENT_WHY: dict[str, str] = {
    "dialect_rules": "no dialect rules are configured for this connection",
    "agent_brief": "the agent has no instructions, and no reviewer has corrected its answers",
    "pack": "no pack steers this question here: it takes an active pack that matches, a person's pinned binding on "
            "this connection, and — when the agent names packs — one of those",
    "instructions": "no custom instructions are kept for this connection",
    "trusted": "no trusted query matched the question",
    "corrections": "no correction on record matched the question",
    "hub_notes": "nothing people noted reached the question; notes reach a prompt only once their source measured lift",
    "question_frame": "the question reached nothing the ontology declares",
    "governed_metrics": "no governed metric binds to the question on this schema",
    "schema_slice": "the schema linker kept nothing for the question",
    "glossary": "no glossary entry matched the question",
    "synonyms": "no person has curated synonyms for this connection",
    "kb_patterns": "no knowledge-base pattern matched the question",
    "sql_examples": "nothing similar was answered here before",
    "exploration": "the explorer has noted nothing about this connection",
    "causal": "no declared cause bears on the question",
    "docs": "",            # said from the agent's own document scope, below
}


def resolve_scope(agent, connection_id: str = "", schema: str = "") -> tuple[str, str]:
    """``(connection, schema)`` this read runs on, by the ask path's own rule and in its own words (``ask_agent_refusal``
    is the public form of the binding check the ask stream makes): a connection or schema that conflicts with the
    agent's binding is a 409; an unset one is the agent's. An unbound agent asked with no connection is refused — a
    read of nothing would look like an agent that knows nothing."""
    from aughor.routers.investigations import AskRequest, ask_agent_refusal
    wanted = (connection_id or "").strip()
    if not wanted and not agent.connection_id:
        raise HTTPException(status_code=422, detail=f"agent '{agent.name}' is bound to no connection; "
                                                    "name one as connection_id")
    req = AskRequest(question="grounding read", connection_id=wanted or agent.connection_id, agent_id=agent.id,
                     schema_name=(schema or "").strip() or None)
    why = ask_agent_refusal(req)
    if why:
        raise HTTPException(status_code=409, detail=why)
    return (agent.connection_id or wanted), (req.schema_name or "")


def check_agent_reader(agent, principal) -> None:
    """With identity on, the reader is of the agent's organisation: another organisation's agent is no agent to it
    (the 404 an unknown id gets, before its binding is said). ``principal`` is the session's caller (the session
    route) or the agent standing in for its key holder (the HTTP door); None — identity off — checks nothing."""
    if principal is not None and agent.owner and principal.org_id and agent.owner != principal.org_id:
        raise HTTPException(status_code=404, detail="No such agent")


def check_connection_reader(connection_id: str, principal) -> None:
    """With identity on, the connection read is the reader's organisation's — the agent's own binding included, which
    no route parameter names and so no router guard sees."""
    if principal is None:
        return
    from aughor.security.authz import check_owner
    check_owner("connection", connection_id, principal)


def agent_as_principal(agent):
    """The agent standing in for whoever holds its key, with identity on — its organisation is the one it may read."""
    from aughor.security.authz import Principal, require_identity_enabled
    if not require_identity_enabled() or not agent.owner:
        return None
    return Principal(user_id=f"agent:{agent.id}", org_id=agent.owner)


def _open(connection_id: str, schema: str):
    """``(db, why)`` — the connection opened at the schema read, or None and why it could not be. An unknown
    connection is the door's 404."""
    from aughor.db.connection import open_connection_for, open_connection_for_with_schema
    try:
        return (open_connection_for_with_schema(connection_id, schema) if schema
                else open_connection_for(connection_id)), ""
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Connection {connection_id!r} not found") from None
    except Exception as exc:                # noqa: BLE001 — said on the read, never a 500
        from aughor.kernel.errors import tolerate
        tolerate(exc, "grounding read: the connection could not be opened; schema blocks are not computed",
                 counter="agents.grounding_read.open")
        return None, f"the connection could not be opened ({type(exc).__name__})"


def _schema_text(connection_id: str, db) -> tuple[str, str]:
    if db is None:
        return "", ""
    from aughor.routers._shared import get_schema_cached
    try:
        return get_schema_cached(connection_id, db) or "", ""
    except Exception as exc:                # noqa: BLE001 — the schema blocks say it
        from aughor.kernel.errors import tolerate
        tolerate(exc, "grounding read: the schema could not be read; schema blocks are not computed",
                 counter="agents.grounding_read.schema")
        return "", f"the schema could not be read ({type(exc).__name__})"


def _why_absent(block, agent, *, schema_text: str, schema_why: str) -> str:
    from aughor.agent.grounding import SCHEMA_BLOCKS
    if block.note:
        return block.note
    if block.key in SCHEMA_BLOCKS and not schema_text:
        return (schema_why or "the connection's schema is empty") + ", so this block was not computed"
    if block.key == "docs":
        n = len(agent.doc_ids)
        return ("the agent has no documents of its own, and it reads only its own" if not n
                else f"none of the agent's {n} document{'s' if n != 1 else ''} matched the question")
    return ABSENT_WHY.get(block.key) or "nothing on record matched the question here"


def _scope_section(agent) -> dict[str, Any]:
    """What the agent may do and how its runs are capped — a section the prompt never carries."""
    from aughor.govern.guardrails import policy_for
    policy = policy_for(agent.id)
    return {
        "in_prompt": False,
        "connection_id": agent.connection_id, "schema_scope": agent.schema_scope,
        "documents": len(agent.doc_ids), "packs": list(agent.pack_ids),
        "tool_grants": list(agent.tool_grants),
        "tool_grants_mean": "the declared actions this agent may propose; a person approves each, and none runs on "
                            "its own",
        "guardrails": policy.to_dict(), "guardrails_are_default": policy.is_default,
    }


def _journal(*, principal: str, door: str, agent, connection_id: str, schema: str, present: list[str],
             absent: int, embedder: dict) -> bool:
    """One `agent.grounding_read` entry — never the question or the content. False when it could not be written."""
    try:
        from aughor.kernel.ledger import Ledger
        Ledger.default().emit(_AUDIT_KIND, {
            "actor": principal, "principal": principal, "door": door, "agent": agent.id, "rev": agent.config_rev,
            "connection_id": connection_id, "schema": schema, "present": present, "absent": absent,
            "embedder_called": embedder.get("called", False), "embedder_backend": embedder.get("backend", ""),
        }, conn_id=connection_id or None)
        return True
    except Exception as exc:                # noqa: BLE001 — the read is answered; the missing entry is said
        from aughor.kernel.errors import tolerate
        tolerate(exc, "grounding read: the journal entry could not be written", counter="agents.grounding_read.audit")
        return False


def read(agent, *, question: str, connection_id: str = "", schema: str = "", principal: str = "",
         door: str = "http", reader=None) -> dict[str, Any]:
    """What ``agent`` would read for ``question``: every block with its content, the absent ones with why, the
    embedder said, the agent's grants and guardrails, and how this differs from an answer. ``reader`` is the identity
    the organisation checks are made for (None with identity off); ``principal`` is who the journal names."""
    from aughor.agent.grounding import build_grounding_context, watch_failures
    from aughor.custom_agents.context import activate_agent, answer_stamp, release_agent
    from aughor.semantic.embedder import describe_backend, tally_calls

    check_agent_reader(agent, reader)
    conn, schema_name = resolve_scope(agent, connection_id, schema)
    check_connection_reader(conn, reader)
    db, open_why = _open(conn, schema_name)
    token = activate_agent(agent)
    try:
        with tally_calls() as tally, watch_failures():
            schema_text, schema_why = _schema_text(conn, db)
            ctx = build_grounding_context(question, conn, db=db, schema=schema_text,
                                          eff_schema=schema_name or getattr(db, "_schema_name", None))
    finally:
        release_agent(token)

    blocks: list[dict[str, Any]] = []
    for b in ctx.blocks:
        row: dict[str, Any] = {"key": b.key, "title": b.title, "present": b.present, "content": b.display}
        if not b.present:
            row["why"] = _why_absent(b, agent, schema_text=schema_text, schema_why=open_why or schema_why)
        elif b.note:
            row["note"] = b.note
        blocks.append(row)
    present = [b["key"] for b in blocks if b["present"]]

    embedder: dict[str, Any] = {"called": tally["requests"] > 0, "requests": tally["requests"],
                                "texts": tally["texts"], "failed": tally["failed"], **describe_backend()}
    if embedder["called"] and embedder.get("hosted"):
        embedder["note"] = "a hosted embedder may charge at its provider for these requests"
    recorded = _journal(principal=principal, door=door, agent=agent, connection_id=conn, schema=schema_name,
                        present=present, absent=len(blocks) - len(present), embedder=embedder)
    return {
        "question": question, "connection_id": conn, "schema": schema_name,
        "answer_stamp": {**(answer_stamp(agent) or {}), "rev": agent.config_rev},
        "receipt": {"blocks": blocks, "present_count": len(present), "absent_count": len(blocks) - len(present)},
        "agent_scope": _scope_section(agent),
        "embedder": embedder,
        "chat_model_called": False,
        "differs_from_answer": DIFFERS_FROM_ANSWER,
        "journal": {"kind": _AUDIT_KIND, "recorded": recorded},
    }


def session_principal(request, asker: str = "") -> tuple[str, str]:
    """``(principal, door)`` for a session-route read: a presented service principal as itself, the MCP client as
    ``api:mcp:<asker>`` (the ask door's spelling for the same caller), else the person signed in."""
    from aughor.rbac import principal_grant
    from aughor.rbac.agent_gate import is_agent_request
    presented = principal_grant.principal_of(request)
    if presented is not None:
        from aughor.security.service_principals import name_of, principal_id
        return principal_id(name_of(presented)), "mcp" if is_agent_request(request) else "session"
    if is_agent_request(request):
        from aughor.custom_agents.reach import principal_for
        return principal_for("mcp", asker), "mcp"
    from aughor.security.authz import acting_person, get_principal
    return acting_person(get_principal(request)), "session"


def door_state(agent, *, issued: bool) -> dict[str, Any]:
    """The grounding door as the Doors tab lists it."""
    return {"state": "open" if issued and agent.enabled else ("needs the HTTP key" if not issued else "paused"),
            "tool": MCP_TOOL,
            "how": "what this agent would read for a question — each block, with why for one that is absent — and "
                   "no model is asked; the MCP tool reads it under the organisation's agent policy"}
