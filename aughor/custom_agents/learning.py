"""One closed learning loop per custom agent (Arc AO-7) and its testing centre (AO-6).

No new store. The verdict store is the lesson store (it now carries ``agent_id``), the
goldens table holds the candidates (a ``status``), and the agent row keeps the stamp
before the latest (``prev_eval``). What this module adds is the LOOP between them:

* ``corrected_before_block`` — the agent's own last corrections, bounded, for its brief.
* ``on_verdict`` — an accepted answer becomes an UNCERTIFIED golden candidate on the
  Quality tab; every Nth verdict re-runs the evaluation.
* ``on_configuration_change`` — a configuration change re-runs the evaluation.
* ``draft_synthetic_goldens`` — questions drafted from the catalogue and the purpose
  (one model call per batch), as candidates a person certifies with SQL.
* ``nightly`` — once a UTC day, every agent with certified goldens is re-evaluated and the
  diff against its last stamp is written onto the result.
* ``learning_summary`` — the receipt the page shows: *learned N corrections · M goldens
  certified from use · pass before → after*.

Inside the invariants: nothing here writes a fact a model authored (a drafted question is a
candidate until a person gives it SQL; a judge never certifies), nothing learns online, and
the whole loop is behind flags that are off by default — ``agents.learning_loop`` for the
loop, ``agents.testing_centre`` for the drafter and the nightly run.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

LOOP_FLAG = "agents.learning_loop"
CENTRE_FLAG = "agents.testing_centre"

#: Every Nth verdict on an agent re-runs its evaluation (AO-7d).
REEVAL_EVERY_N_VERDICTS = 5
#: The brief's "corrected before" block: rows and characters per row.
CORRECTED_BEFORE_ROWS = 3
CORRECTED_BEFORE_CHARS = 160
#: Synthetic questions drafted per batch (AO-6).
DRAFT_BATCH = 6


def _flag(name: str) -> bool:
    from aughor.kernel.flags import flag_enabled
    return flag_enabled(name)


# ── AO-7a · the brief's lessons ──────────────────────────────────────────────────

def corrected_before_block(agent_id: str) -> str:
    """The agent's own last rejected/corrected answers, as a bounded block for its brief.
    "" when the loop is off or nothing was ever corrected."""
    if not agent_id or not _flag(LOOP_FLAG):
        return ""
    from aughor.feedback.verdicts import list_corrections
    rows = list_corrections(agent_id=agent_id, limit=CORRECTED_BEFORE_ROWS)
    if not rows:
        return ""
    lines = ["CORRECTED BEFORE — a reviewer judged these earlier answers OF YOURS; do not "
             "repeat the mistake:"]
    for r in rows:
        tag = "rejected" if r.get("verdict") == "reject" else "corrected"
        claim = " ".join(str(r.get("headline") or "").split())[:CORRECTED_BEFORE_CHARS]
        note = " ".join(str(r.get("note") or "").split())[:CORRECTED_BEFORE_CHARS]
        line = f"- [{tag}] {claim or '(no headline recorded)'}"
        if note:
            line += f" — reviewer: {note}"
        lines.append(line)
    return "\n".join(lines) + "\n\n"


# ── AO-7c/7d · what a verdict and a configuration change set in motion ───────────

_RUNNING: set[str] = set()
_RUNNING_LOCK = threading.Lock()


def on_verdict(agent_id: str, *, verdict: str, investigation_id: str, question: str,
               sql: str, headline: str) -> dict[str, Any]:
    """Called after a verdict on one of the agent's answers landed. Returns what it did."""
    did: dict[str, Any] = {"candidate": None, "reevaluated": False}
    if not _flag(LOOP_FLAG):
        return did
    from aughor.custom_agents.store import add_candidate
    if verdict == "accept" and question and sql:
        # AO-7c — accepted in use → a candidate, with the SQL that answered as the
        # STARTING point for the person who certifies it. Not certified: a person's ✅ on
        # an answer is not a person's word that the SQL is the reference.
        did["candidate"] = add_candidate(agent_id, question, source="use", reference_sql=sql,
                                         from_investigation=investigation_id, headline=headline)
    from aughor.feedback.verdicts import count_verdicts_for_agent
    n = count_verdicts_for_agent(agent_id)
    if n and n % REEVAL_EVERY_N_VERDICTS == 0:
        did["reevaluated"] = reevaluate(agent_id, reason=f"{n} verdicts")
    return did


def on_configuration_change(agent_id: str) -> bool:
    """A revision was recorded: re-run the evaluation so the chip measures THIS agent."""
    if not _flag(LOOP_FLAG):
        return False
    return reevaluate(agent_id, reason="configuration changed")


def reevaluate(agent_id: str, *, reason: str, background: bool = True) -> bool:
    """Run the production-path evaluation for one agent. In the background by default — a
    verdict or a save must not wait on N model calls — and never twice at once per agent.
    Returns whether a run was started (or, inline, completed)."""
    from aughor.custom_agents.store import get_agent, list_goldens
    agent = get_agent(agent_id)
    if agent is None or not list_goldens(agent_id, status="certified"):
        return False
    with _RUNNING_LOCK:
        if agent_id in _RUNNING:
            return False
        _RUNNING.add(agent_id)

    def _run() -> None:
        try:
            from aughor.custom_agents.quality import evaluate_agent
            result = evaluate_agent(agent)
            logger.info("agent %s re-evaluated (%s): %s/%s", agent_id, reason,
                        result.get("passed"), result.get("total"))
        except Exception as exc:                        # noqa: BLE001 — logged, never raised
            logger.warning("agent %s re-evaluation (%s) failed: %s", agent_id, reason, exc)
        finally:
            with _RUNNING_LOCK:
                _RUNNING.discard(agent_id)

    if background:
        threading.Thread(target=_run, name=f"agent-reeval-{agent_id}", daemon=True).start()
    else:
        _run()
    return True


# ── AO-6 · the drafter ───────────────────────────────────────────────────────────

def draft_synthetic_goldens(agent, *, n: int = DRAFT_BATCH) -> list[dict]:
    """Draft up to ``n`` golden QUESTIONS for the agent from the connection's metric
    catalogue and the agent's purpose — one model call — and stage them as candidates.
    The model drafts questions; it may not certify answers, so no SQL is written here.
    Raises RuntimeError when the centre's flag is off."""
    if not _flag(CENTRE_FLAG):
        raise RuntimeError("the testing centre is off (flag agents.testing_centre)")
    from pydantic import BaseModel, Field
    from aughor.llm.provider import get_provider
    from aughor.custom_agents.store import add_candidate

    class _Draft(BaseModel):
        question: str
        why: str = ""

    class _Drafts(BaseModel):
        questions: list[_Draft] = Field(default_factory=list)

    metrics = _catalogue_lines(agent.connection_id, agent.schema_scope)
    system = (
        "You draft regression QUESTIONS for a data agent's test suite. Each question must be "
        "answerable with one SQL query over the connection's data, specific enough that two "
        "analysts would write the same query, and worth asking because being wrong would matter. "
        "Draft questions only — never answers, never SQL. Prefer the governed metrics named "
        "below; name the period and the grain. Return at most {n} questions.").format(n=n)
    user = "\n".join([
        f"Agent: {agent.name}",
        f"Purpose: {agent.purpose or '(none given)'}",
        f"Standing instructions: {(agent.instructions or '')[:1200]}",
        "Governed metrics on this connection:" if metrics else "No governed metrics are declared.",
        *metrics,
    ])
    drafts: _Drafts = get_provider("coder").complete(system=system, user=user,
                                                     response_model=_Drafts, temperature=0.2)
    out: list[dict] = []
    for d in drafts.questions[:n]:
        row = add_candidate(agent.id, d.question, source="synthetic", headline=(d.why or "")[:300])
        if row:
            out.append(row)
    return out


def _catalogue_lines(connection_id: str, schema_scope: str = "") -> list[str]:
    """Approved/defined metrics, one line each, capped — the drafter's raw material."""
    try:
        from aughor.semantic.metric_catalogue import catalogue_for
        entries = catalogue_for(connection_id, schema_scope or None) if connection_id else []
    except Exception as exc:                            # noqa: BLE001 — the drafter still runs
        logger.debug("catalogue unavailable for %s: %s", connection_id, exc)
        return []
    lines: list[str] = []
    for e in entries:
        d = e.as_dict() if hasattr(e, "as_dict") else dict(e)
        if d.get("state") not in ("defined", None, ""):
            continue
        if d.get("status") in ("deprecated",):
            continue
        definition = " ".join(str(d.get("definition") or "").split())[:160]
        lines.append(f"- {d.get('label') or d.get('name')}: {definition or '(no definition)'}")
        if len(lines) >= 40:
            break
    return lines


# ── AO-6 · the nightly run ───────────────────────────────────────────────────────

_last_nightly_day: Optional[str] = None


def nightly(*, now: Optional[datetime] = None, force: bool = False) -> dict[str, Any]:
    """Once a UTC day: re-evaluate every enabled agent that has certified goldens, and
    write the diff against its previous stamp onto the result. Behind the centre's flag."""
    global _last_nightly_day
    if not _flag(CENTRE_FLAG):
        return {"skipped": "off"}
    day = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d")
    if _last_nightly_day == day and not force:
        return {"skipped": "already ran today"}
    _last_nightly_day = day
    from aughor.custom_agents.store import list_agents, list_goldens
    from aughor.custom_agents.quality import evaluate_agent
    ran, skipped = [], []
    for agent in list_agents():
        if not agent.enabled or not list_goldens(agent.id, status="certified"):
            skipped.append(agent.id)
            continue
        try:
            result = evaluate_agent(agent)
            ran.append({"agent_id": agent.id, "passed": result.get("passed"),
                        "total": result.get("total"), "diff": result.get("diff")})
        except Exception as exc:                        # noqa: BLE001
            logger.warning("nightly eval of %s failed: %s", agent.id, exc)
            ran.append({"agent_id": agent.id, "error": str(exc)})
    return {"day": day, "ran": ran, "skipped": skipped}


def eval_diff(before: Optional[dict], after: dict) -> dict[str, Any]:
    """What changed between two stamps: the goldens that newly fail or newly pass."""
    def _passes(stamp: Optional[dict]) -> dict[str, bool]:
        return {q.get("golden_id"): bool(q.get("passed"))
                for q in (stamp or {}).get("per_question", []) if q.get("golden_id")}
    b, a = _passes(before), _passes(after)
    return {
        "before": ({"passed": before.get("passed"), "total": before.get("total"),
                    "at": before.get("at")} if before else None),
        "newly_failing": [g for g, ok in a.items() if not ok and b.get(g) is True],
        "newly_passing": [g for g, ok in a.items() if ok and b.get(g) is False],
    }


# ── the receipt ──────────────────────────────────────────────────────────────────

def learning_summary(agent_id: str) -> dict[str, Any]:
    """*learned N corrections · M goldens certified from use · pass before → after* — the
    delta that is the loop's receipt, with the flags' states said."""
    from aughor.custom_agents.store import get_agent, list_goldens, previous_eval
    from aughor.feedback.verdicts import count_verdicts_for_agent, list_corrections
    agent = get_agent(agent_id)
    goldens = list_goldens(agent_id)
    last = (agent.last_eval if agent else None) or None
    prev = previous_eval(agent_id)
    return {
        "agent_id": agent_id,
        "loop_on": _flag(LOOP_FLAG),
        "centre_on": _flag(CENTRE_FLAG),
        "verdicts": count_verdicts_for_agent(agent_id),
        "corrections": len(list_corrections(agent_id=agent_id, limit=200)),
        "candidates_from_use": sum(1 for g in goldens if g.get("status") == "candidate" and g.get("source") == "use"),
        "candidates_synthetic": sum(1 for g in goldens if g.get("status") == "candidate" and g.get("source") == "synthetic"),
        "certified_from_use": sum(1 for g in goldens if g.get("status") == "certified" and g.get("source") == "use"),
        "certified_synthetic": sum(1 for g in goldens if g.get("status") == "certified" and g.get("source") == "synthetic"),
        "certified": sum(1 for g in goldens if g.get("status") == "certified"),
        "before": ({"passed": prev.get("passed"), "total": prev.get("total"), "at": prev.get("at")}
                   if prev else None),
        "after": ({"passed": last.get("passed"), "total": last.get("total"), "at": last.get("at")}
                  if last else None),
    }
