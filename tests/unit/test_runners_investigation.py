"""Wave H5 — the neutral runner, and the seam it finally lets kinetic close.

Two things are being pinned, and they are different kinds of claim.

**Behavioural**: one runner drives the real ask path, refuses a bad persona binding BEFORE
spending anything, submits without waiting, and never invents an id it could not know. The
inline path — the only one that waits — is now the only one that can report a failure, and it
does: before H5 the drained error was computed and discarded, so an inline run that errored was
filed as ``executed``.

**Structural**: this is the actual point of H5. ``automations`` and ``kinetic`` both start
investigations; A already routes its ``kinetic_action`` effect through K's executor, so pointing
K's ``trigger_investigation`` branch at A's engine would have inverted the dependency. The runner
lives where neither can own it, and the tests below fail if that erodes — in either direction.

Hermetic: ``build_ask_stream`` and the kernel submit seam are both faked, so no investigation, no
LLM and no warehouse are touched.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from aughor.actions.executor import execute_kinetic_action
from aughor.ontology.models import ActionParameter, KineticAction, SideEffect
from aughor.runners import InvestigationRequest, run_investigation
from aughor.runners.investigation import DISPATCH_EVENT
from aughor.custom_agents import create_agent, delete_agent, list_agents

REPO = Path(__file__).resolve().parents[2]
AUGHOR = REPO / "aughor"


@pytest.fixture(autouse=True)
def _clean_agents():
    yield
    for a in list_agents():
        delete_agent(a.id)


@pytest.fixture(autouse=True)
def _agents_flag_on(monkeypatch):
    import aughor.kernel.flags as flags
    monkeypatch.setattr(flags, "flag_enabled",
                        lambda name: name in ("agents.user_defined", "kinetic.actions"))


def _frames(*payloads: dict) -> list[str]:
    return [f"data: {json.dumps(p)}\n\n" for p in payloads]


def _fake_ask(monkeypatch, *payloads: dict):
    """Fake the one ask door; returns the list the drained AskRequest lands in."""
    seen: list = []

    def fake_stream(req, request):
        seen.append(req)

        async def _gen():
            for frame in _frames(*payloads):
                yield frame

        return _gen()

    monkeypatch.setattr("aughor.routers.investigations.build_ask_stream", fake_stream)
    return seen


def _capture_submit(monkeypatch, *, job_id="job-1"):
    """Capture the work instead of running it — the submitted path."""
    captured: list = []

    def fake_submit(kind, work, *, conn_id="", idempotency_key="", **kw):
        captured.append({"kind": kind, "work": work, "conn_id": conn_id,
                         "idem": idempotency_key})
        return job_id

    monkeypatch.setattr("aughor.kernel.jobs.submit_background_tick", fake_submit)
    return captured


def _no_loop(monkeypatch):
    """No live loop — submit declines and the caller runs the work inline."""
    monkeypatch.setattr("aughor.kernel.jobs.submit_background_tick",
                        lambda *a, **kw: None)


def _req(**kw) -> InvestigationRequest:
    base = dict(question="why did refunds spike?", connection_id="conn-h5")
    base.update(kw)
    return InvestigationRequest(**base)


# ── the runner drives the ONE ask path ───────────────────────────────────────────

def test_the_work_drains_the_real_ask_door_at_deep_depth(monkeypatch):
    submitted = _capture_submit(monkeypatch)
    seen = _fake_ask(monkeypatch)

    run = run_investigation(_req(), idempotency_key="k")
    submitted[0]["work"]()

    assert run.status == "executed" and run.job_id == "job-1"
    assert submitted[0]["kind"] == "investigation"      # a supervised, metered kernel job
    assert submitted[0]["conn_id"] == "conn-h5"
    assert seen[0].question == "why did refunds spike?"
    assert seen[0].depth == "deep"


def test_a_submitted_run_reports_the_job_and_invents_no_receipt(monkeypatch):
    """The honest asymmetry: at submit time the investigation does not exist yet, so its id
    and receipt are not knowable. `basis` says so rather than the fields quietly reading as
    'there wasn't one'."""
    _capture_submit(monkeypatch)
    _fake_ask(monkeypatch)

    run = run_investigation(_req(), idempotency_key="k")

    assert run.basis == "submitted" and run.job_id == "job-1"
    assert run.investigation_id == "" and run.receipt_id == ""


def test_the_inline_path_returns_the_real_ids(monkeypatch):
    _no_loop(monkeypatch)
    _fake_ask(monkeypatch,
              {"type": "start", "investigation_id": "inv-77"},
              {"type": "receipt_id", "receipt_id": "rcpt-88"})

    run = run_investigation(_req(), idempotency_key="k")

    assert run.status == "executed" and run.basis == "inline"
    assert (run.investigation_id, run.receipt_id) == ("inv-77", "rcpt-88")


def test_an_inline_run_that_errored_is_a_failure_not_an_executed_tick(monkeypatch):
    """The defect the lift exposed: the drained error used to be computed and thrown away."""
    _no_loop(monkeypatch)
    _fake_ask(monkeypatch,
              {"type": "start", "investigation_id": "inv-77"},
              {"type": "error", "message": "connection 'conn-h5' is unreachable"})

    run = run_investigation(_req(), idempotency_key="k")

    assert run.status == "failed" and not run.ok
    assert "unreachable" in run.message


# ── the join a submitted run cannot return ───────────────────────────────────────

def test_the_dispatch_join_is_recorded_so_a_submitted_run_is_still_traceable(monkeypatch):
    from aughor.kernel.ledger import Ledger
    agent = create_agent(name="Refund Analyst")
    submitted = _capture_submit(monkeypatch)
    _fake_ask(monkeypatch,
              {"type": "start", "investigation_id": "inv-77"},
              {"type": "receipt_id", "receipt_id": "rcpt-88"})

    run_investigation(_req(agent_id=agent.id), idempotency_key="k",
                      caller="automation:auto-1")
    submitted[0]["work"]()

    ev = Ledger.default().events(kind=DISPATCH_EVENT, limit=1)[0]
    p = ev["payload"]
    assert p["caller"] == "automation:auto-1" and p["agent_id"] == agent.id
    assert p["investigation_id"] == "inv-77" and p["receipt_id"] == "rcpt-88"
    assert p["ok"] is True


# ── fail-closed: a refused persona spends nothing ────────────────────────────────

def test_a_conflicting_agent_binding_refuses_before_anything_is_submitted(monkeypatch):
    agent = create_agent(name="Finance Analyst", connection_id="conn-other")
    submitted = _capture_submit(monkeypatch)
    _fake_ask(monkeypatch)

    run = run_investigation(_req(agent_id=agent.id), idempotency_key="k")

    assert run.status == "refused" and not run.ok
    assert "conn-other" in run.message and "conn-h5" in run.message
    assert submitted == [], "a refused binding still submitted the work"


# ── the kinetic seam, closed ─────────────────────────────────────────────────────

def _ki_action(config: dict, **kw) -> KineticAction:
    base = dict(
        id="investigate_refunds", kind="side_effect",
        params=[ActionParameter(name="order_id", data_type="VARCHAR", required=True)],
        submission_criteria=[],
        side_effects=[SideEffect(kind="trigger_investigation", config=config)],
        risk="low",
    )
    base.update(kw)
    return KineticAction(**base)


def test_a_declared_action_starts_an_investigation_through_the_runner(monkeypatch):
    submitted = _capture_submit(monkeypatch, job_id="job-k")
    seen = _fake_ask(monkeypatch)
    action = _ki_action({"question": "why was order {order_id} refunded?"})

    result = execute_kinetic_action(action, {"order_id": "A-9"}, scope="conn-h5")
    submitted[0]["work"]()

    assert result.status == "executed" and result.ok
    out = result.outcome["side_effects"][0]
    assert out["job_id"] == "job-k" and out["basis"] == "submitted"
    # The declared parameter reached the question — one investigation about order A-9.
    assert out["question"] == "why was order A-9 refunded?"
    assert seen[0].question == "why was order A-9 refunded?"
    assert seen[0].connection_id == "conn-h5"


def test_two_orders_are_two_investigations(monkeypatch):
    submitted = _capture_submit(monkeypatch)
    _fake_ask(monkeypatch)
    action = _ki_action({"question": "why was order {order_id} refunded?"})

    execute_kinetic_action(action, {"order_id": "A-9"}, scope="conn-h5")
    execute_kinetic_action(action, {"order_id": "B-2"}, scope="conn-h5")

    assert submitted[0]["idem"] != submitted[1]["idem"], \
        "two orders deduplicated onto one investigation"


def test_a_question_referencing_an_undeclared_parameter_fails_loudly(monkeypatch):
    submitted = _capture_submit(monkeypatch)
    _fake_ask(monkeypatch)
    action = _ki_action({"question": "why was {customer_id} refunded?"})

    result = execute_kinetic_action(action, {"order_id": "A-9"}, scope="conn-h5")

    assert result.status == "dispatch_error"
    assert "customer_id" in result.message
    assert submitted == [], "a question that could not be built still ran"


def test_an_action_with_no_connection_refuses_instead_of_submitting_a_doomed_job(monkeypatch):
    """A job submitted against connection "" would 'succeed' at submit and then quietly never
    answer — the failure lands minutes later, inside a background job, on nobody's screen."""
    submitted = _capture_submit(monkeypatch)
    _fake_ask(monkeypatch)

    result = execute_kinetic_action(_ki_action({"question": "q"}), {"order_id": "A-9"}, scope="")

    assert result.status == "dispatch_error" and "connection" in result.message
    assert submitted == []


def test_a_refused_persona_reaches_the_caller_verbatim(monkeypatch):
    """The K2 property: an action that could not do what it declared says so, in the
    authored words — it does not quietly investigate as nobody."""
    agent = create_agent(name="Finance Analyst", connection_id="conn-other")
    submitted = _capture_submit(monkeypatch)
    _fake_ask(monkeypatch)
    action = _ki_action({"question": "why did refunds spike?", "agent_id": agent.id})

    result = execute_kinetic_action(action, {"order_id": "A-9"}, scope="conn-h5")

    assert result.status == "dispatch_error"
    assert "conn-other" in result.message and "conn-h5" in result.message
    assert submitted == []


def test_an_investigation_cannot_be_declared_read_only(monkeypatch):
    """H5's risk decision: starting a deep run spends the LLM budget, so `read_only` is not a
    truthful tier for it however the overlay declares it. The floor is LOW, and the audit
    ledger — not a comment — is where that is checked."""
    from aughor.govern.actions import recent_audit
    _capture_submit(monkeypatch)
    _fake_ask(monkeypatch)

    execute_kinetic_action(_ki_action({"question": "q"}, risk="read_only"),
                           {"order_id": "A-9"}, scope="conn-h5")
    assert recent_audit(limit=1)[0]["risk"] == "low"

    # A side effect that spends nothing keeps the tier its author declared.
    execute_kinetic_action(
        KineticAction(id="ping", kind="annotate", risk="read_only", side_effects=[]),
        {"table": "t", "body": "b"}, scope="conn-h5")
    assert recent_audit(limit=1)[0]["risk"] == "read_only"


# ── the structural claim: neither package owns the runner ────────────────────────

def _imported_aughor_modules(path: Path) -> set[str]:
    """Every `aughor.*` module this file imports, however the import is spelled."""
    out: set[str] = set()
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("aughor"):
            out.add(node.module)
        elif isinstance(node, ast.Import):
            out.update(a.name for a in node.names if a.name.startswith("aughor"))
    return out


def _py(pkg: str) -> list[Path]:
    return [p for p in (AUGHOR / pkg).rglob("*.py") if "__pycache__" not in p.parts]


def test_the_runner_imports_neither_of_its_callers():
    """If this fails, the runner has grown a caller's concern and stopped being neutral —
    the exact state H5 exists to leave behind."""
    for path in _py("runners"):
        offending = {m for m in _imported_aughor_modules(path)
                     if m.startswith(("aughor.automations", "aughor.actions"))}
        assert not offending, f"{path.name} imports its own caller: {sorted(offending)}"


def test_kinetic_never_imports_automations():
    """The inversion H5 refused to make. A depends on K (its `kinetic_action` effect runs
    through K's executor); K reaching back for A's engine would close the cycle."""
    for path in _py("actions"):
        offending = {m for m in _imported_aughor_modules(path)
                     if m.startswith("aughor.automations")}
        assert not offending, (
            f"aughor/actions/{path.name} imports {sorted(offending)} — A already depends on K, "
            f"so this closes the cycle. Call aughor.runners instead.")


def test_both_callers_go_through_the_runner():
    """The other half: a private copy of the drain reappearing in either package would pass
    the two tests above while defeating the point."""
    for module in (AUGHOR / "automations" / "engine.py", AUGHOR / "actions" / "executor.py"):
        assert any(m.startswith("aughor.runners") for m in _imported_aughor_modules(module)), \
            f"{module.name} no longer runs investigations through the neutral runner"
