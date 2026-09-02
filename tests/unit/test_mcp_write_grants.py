"""VA-9d write slice — the grant plane: our ratification, not their label.

The read-only slice deferred two questions on purpose, and §6.6 answered them on
2026-09-02. These tests are those two answers, and almost all of them are about what does
NOT happen.

    **1. Whose declaration of "read-only" is believed? Nobody's but ours.**
    A server's hints are advisory. What authorizes a mutating call is an explicit per-tool
    grant a human wrote down. The allowlist says WHERE we may reach; the grant says WHAT we
    may do there.

    **2. What may a server that CHANGES a declaration after registration do?**
    Nothing it could not do before. A grant pins the declaration it was given for; when the
    roster stops matching it, the grant is refused AND dropped.

The failure mode a plausible implementation reaches for is to fold the grant into
`classify()` — to make a granted tool come back `callable`. That would be wrong in a way no
single test catches, so it is worth naming: `disposition` is what the SERVER said and is
recomputed from hints on every discovery, while a grant is what a PERSON said and must
survive a re-discovery that changed nothing. Collapsing them would make every discovery
silently re-derive human decisions.

Driven against the same real stdio server the read-only suite uses, for the same reason: a
mock of the protocol would be a mock of our own understanding of it.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from aughor.mcpservers import call as door
from aughor.mcpservers import store
from aughor.mcpservers.discover import discover
from aughor.mcpservers.models import (
    CALLABLE, GRANT_ACTIVE, GRANT_NONE, GRANT_STALE, McpServer, McpTool, McpToolGrant,
    grant_key, grant_verdict,
)

_FIXTURE_SERVER = Path(__file__).parent / "fixtures" / "mcp_fixture_server.py"

#: The fixture server's declared-mutating tool. Granting THIS is the whole point of the
#: slice: `readOnlyHint=False, destructiveHint=True` is the most restrictive real shape.
MUTATING = "delete_everything"
#: Declares nothing — the majority case, which the protocol reads as "may modify".
UNDECLARED = "unannotated_thing"
READONLY = "read_the_weather"


@pytest.fixture(autouse=True)
def _clean():
    """Servers, rosters AND grants. A grant left behind is a standing permission to mutate
    somebody else's system that the next test file would inherit."""
    def _wipe():
        for s in store.list_servers():
            store.delete_server(s.id)
        for g in store.list_grants():
            store.delete_grant(g.server_id, g.tool_name)
    _wipe()
    yield
    _wipe()


#: 🔴 FIXED ids, not generated ones, and this is not cosmetic. `service_name()` puts the
#: server id in the outbound span name (`external.mcp:<id>.tools/list`) — deliberately, so a
#: rename cannot detach a cap or an audit line from its counterparty. A test file that mints
#: a fresh id per test therefore mints a fresh TASK NAME per test, and every one of them is
#: slow because a stdio discovery spawns a real subprocess (~370ms measured). Forty-one of
#: those flooded `task_history.slow_tasks(limit=50)` — a leaderboard over task names, shared
#: across the whole session — and pushed a genuine entry out of it, failing
#: `test_task_history` several files later. Two ids for a whole file keeps that noise at two.
_SERVER_ID = "mcps_writegrants01"
_SERVER_ID_B = "mcps_writegrants02"


def _server(server_id: str = _SERVER_ID, **over) -> McpServer:
    fields = {"id": server_id, "name": "Fixture", "transport": "stdio",
              "command": sys.executable, "args": [str(_FIXTURE_SERVER)], **over}
    return store.save_server(McpServer(**fields))


def _discovered(server_id: str = _SERVER_ID) -> McpServer:
    s = _server(server_id)
    discover(s)
    return s


def _grant(server_id: str, tool_name: str, *, by: str = "amit") -> McpToolGrant:
    """Ratify exactly as the route does — pinning from the ROSTER, never from an argument."""
    from aughor.mcpservers.discover import tool_named
    tool = tool_named(server_id, tool_name)
    assert tool is not None, f"{tool_name} is not on the roster; the test is set up wrong"
    return store.save_grant(McpToolGrant(
        server_id=server_id, tool_name=tool_name,
        read_only_hint=tool.read_only_hint, destructive_hint=tool.destructive_hint,
        granted_by=by))


# ── the verdict function, which is the one place staleness is decided ────────────

def _tool(**over) -> McpTool:
    fields = {"server_id": "s", "name": "t", "read_only_hint": False,
              "destructive_hint": True, **over}
    return McpTool(**fields)


def test_no_grant_is_the_off_state():
    assert grant_verdict(_tool(), None) == (GRANT_NONE, "")


def test_a_grant_matching_the_declaration_is_active():
    tool = _tool()
    grant = McpToolGrant(server_id="s", tool_name="t", read_only_hint=False,
                         destructive_hint=True)
    assert grant_verdict(tool, grant)[0] == GRANT_ACTIVE


def test_a_CHANGED_declaration_makes_the_grant_STALE():
    """The heart of the second decision. A human ratified a mutating-but-not-destructive
    tool; the server now calls it destructive. That is not the thing that was ratified."""
    grant = McpToolGrant(server_id="s", tool_name="t", read_only_hint=False,
                         destructive_hint=False)
    state, why = grant_verdict(_tool(destructive_hint=True), grant)
    assert state == GRANT_STALE
    assert "no longer applies" in why
    # The message must say what changed, or the person re-ratifying is being asked to
    # approve a diff they cannot see.
    assert "not destructive" in why and "destructive" in why


def test_a_declaration_going_from_SILENT_to_stated_is_a_change():
    """Silence is an answer here ("may modify, possibly destructively"), so a server that
    starts stating something has changed its declaration, not merely filled one in."""
    grant = McpToolGrant(server_id="s", tool_name="t", read_only_hint=None,
                         destructive_hint=None)
    state, why = grant_verdict(_tool(read_only_hint=False, destructive_hint=True), grant)
    assert state == GRANT_STALE
    assert "may modify, possibly destructively" in why


def test_a_COSMETIC_change_does_NOT_revoke():
    """A control that fires on every legitimate change is one people learn to click through.
    Title and description move for cosmetic reasons; the annotations are the security claim.
    """
    grant = McpToolGrant(server_id="s", tool_name="t", read_only_hint=False,
                         destructive_hint=True)
    renamed = _tool(title="Delete Everything (v2)", description="now with more warnings")
    assert grant_verdict(renamed, grant)[0] == GRANT_ACTIVE


def test_a_grant_never_makes_a_tool_CALLABLE():
    """`disposition` is the server's word, recomputed every discovery; a grant is a person's
    and must survive one. Folding the grant into the disposition would make each discovery
    silently re-derive a human decision."""
    s = _discovered()
    _grant(s.id, MUTATING)
    from aughor.mcpservers.discover import tool_named
    assert tool_named(s.id, MUTATING).disposition != CALLABLE


# ── the door: what the grant actually buys ───────────────────────────────────────

def test_a_mutating_tool_with_NO_grant_is_still_refused():
    """The read-only slice's behaviour, unchanged. The write slice adds a door, it does not
    open one that was shut."""
    s = _discovered()
    result = door.call(s.id, MUTATING, {"target": "x"})
    assert result.status == "refused"
    assert not result.writes


def test_an_UNDECLARED_tool_with_no_grant_is_still_refused():
    """The majority case, and the one a plausible implementation gets backwards."""
    s = _discovered()
    assert door.call(s.id, UNDECLARED, {"x": "1"}).status == "refused"


def test_a_GRANTED_mutating_tool_RUNS():
    """The capability itself. Without this the slice is a permission system for nothing."""
    s = _discovered()
    _grant(s.id, MUTATING)
    result = door.call(s.id, MUTATING, {"target": "the-thing"})
    assert result.ok, f"a granted tool was refused: {result.status} {result.message}"
    assert "deleted the-thing" in result.text
    assert result.writes is True


def test_revoking_a_grant_closes_the_door_again():
    s = _discovered()
    _grant(s.id, MUTATING)
    assert door.call(s.id, MUTATING, {"target": "x"}).ok
    store.delete_grant(s.id, MUTATING)
    assert door.call(s.id, MUTATING, {"target": "x"}).status == "refused"


def test_a_grant_is_scoped_to_ONE_tool_not_the_server():
    """A grant names a tool, never a roster — the blanket-grant failure `_validate_agent_
    grants` refuses one plane over."""
    s = _discovered()
    _grant(s.id, MUTATING)
    assert door.call(s.id, UNDECLARED, {"x": "1"}).status == "refused"


def test_a_grant_is_scoped_to_ONE_SERVER():
    """Two servers, same tool name, one grant. The second must not inherit it."""
    a, b = _discovered(), _server(_SERVER_ID_B, name="Second")
    discover(b)
    _grant(a.id, MUTATING)
    assert door.call(a.id, MUTATING, {"target": "x"}).ok
    assert door.call(b.id, MUTATING, {"target": "x"}).status == "refused"


# ── drift: the second decision, end to end ───────────────────────────────────────

def _drift(server_id: str, tool_name: str, **decl) -> None:
    """Rewrite the STORED roster so the server appears to have changed its declaration.

    The roster is edited rather than the fixture server, because what the door compares
    against is the stored roster (`tool_named`'s own documented property) — so this
    reproduces exactly the state a re-discovery against a changed server would leave, which
    is the state the door has to refuse.
    """
    tools, _ = store.get_roster(server_id)
    store.save_roster(server_id, [
        t.model_copy(update=decl) if t.name == tool_name else t for t in tools])


def test_a_DRIFTED_declaration_is_refused_AT_THE_DOOR():
    """The load-bearing half of decision two. Discovery revokes eagerly, but the door is the
    authority: a grant must never be honoured against a declaration nobody read."""
    s = _discovered()
    _grant(s.id, MUTATING)
    _drift(s.id, MUTATING, destructive_hint=False)

    result = door.call(s.id, MUTATING, {"target": "x"})
    assert result.status == "refused"
    assert "no longer applies" in result.message


def test_the_door_DROPS_a_stale_grant_rather_than_leaving_it_to_read_as_live():
    """A refusal that leaves the row behind would make the roster render 'granted' for a
    tool the door refuses — the catalogue-that-lies failure in miniature."""
    s = _discovered()
    _grant(s.id, MUTATING)
    _drift(s.id, MUTATING, destructive_hint=False)
    door.call(s.id, MUTATING, {"target": "x"})
    assert store.get_grant(s.id, MUTATING) is None


def test_re_ratifying_after_drift_restores_the_call():
    """The grant is not a one-way door: a person who looks at the change and accepts it can
    grant it again, and the new grant pins the NEW declaration."""
    s = _discovered()
    _grant(s.id, MUTATING)
    _drift(s.id, MUTATING, destructive_hint=False)
    assert door.call(s.id, MUTATING, {"target": "x"}).status == "refused"

    _grant(s.id, MUTATING)                       # pins the declaration as it stands now
    assert door.call(s.id, MUTATING, {"target": "x"}).ok


def test_DISCOVERY_revokes_a_grant_whose_declaration_moved():
    """The eager half. Without it a surface renders a permission the door would refuse."""
    s = _discovered()
    _grant(s.id, MUTATING)
    _drift(s.id, MUTATING, read_only_hint=True, destructive_hint=None)

    tools, _ = store.get_roster(s.id)
    dropped = store.revoke_stale_grants(s.id, tools)

    assert [g.tool_name for g in dropped] == [MUTATING]
    assert store.get_grant(s.id, MUTATING) is None


def test_a_REAL_rediscovery_leaves_an_UNCHANGED_grant_alone():
    """The other side of the same coin, and the one that makes the control usable: a
    discovery that changed nothing must not cost a person their ratifications."""
    s = _discovered()
    _grant(s.id, MUTATING)
    discover(s)                                   # a real round trip against the real server
    assert store.get_grant(s.id, MUTATING) is not None
    assert door.call(s.id, MUTATING, {"target": "x"}).ok


def test_a_grant_for_a_tool_the_server_STOPPED_offering_is_dropped():
    """A permission that outlives the thing it permits is how a re-added tool inherits a yes
    nobody gave it."""
    s = _discovered()
    _grant(s.id, MUTATING)
    tools, _ = store.get_roster(s.id)
    remaining = [t for t in tools if t.name != MUTATING]
    store.save_roster(s.id, remaining)

    dropped = store.revoke_stale_grants(s.id, remaining)
    assert [g.tool_name for g in dropped] == [MUTATING]
    assert store.get_grant(s.id, MUTATING) is None


def test_deleting_a_server_forgets_its_GRANTS_too():
    """The roster's rule, applied to the plane that authorizes writes. A grant outliving its
    server is a standing permission against a destination nobody can see."""
    s = _discovered()
    _grant(s.id, MUTATING)
    store.delete_server(s.id)
    assert store.get_grant(s.id, MUTATING) is None
    assert store.list_grants() == []


# ── the audit trail this slice is accountable to ─────────────────────────────────

def test_a_granted_call_is_recorded_AS_A_WRITE_in_the_LEDGER(monkeypatch):
    """🔴 The LEDGER, not the span — the distinction that broke discovery in the read-only
    slice, one field over.

    `external_call` sends `attributes` to the mlflow span and emits
    `payload={"operation", **extra}`: two different destinations. A `writes` flag passed
    only as an attribute rides the span and never reaches the audit trail, and the operation
    string is `tools/call:<name>` for reads and writes alike — so an auditor reading the
    event stream could not tell a granted mutation from a read. Asserting the span would
    prove the flag was passed and not that anything was recorded, which is the same shape as
    the bug this suite already paid for once.
    """
    events: list[dict] = []
    monkeypatch.setattr("aughor.obs.session_log.emit",
                        lambda kind, **kw: events.append({"kind": kind, **kw}))

    s = _discovered()
    _grant(s.id, MUTATING)
    door.call(s.id, READONLY, {"city": "Lisbon"})
    door.call(s.id, MUTATING, {"target": "x"})

    by_name = {e.get("name"): (e.get("payload") or {}) for e in events
               if e["kind"] == "external_call"}
    read = by_name.get(f"mcp:{s.id}.tools/call:{READONLY}")
    write = by_name.get(f"mcp:{s.id}.tools/call:{MUTATING}")

    assert read is not None and write is not None, f"a call left no record: {list(by_name)}"
    assert write.get("writes") is True, (
        "a granted MUTATION was recorded without `writes` — the audit trail cannot "
        "distinguish it from a read")
    assert read.get("writes") is False, "a read was recorded as a write"


def test_granting_and_revoking_are_themselves_audited(monkeypatch):
    """A grant is a governance change, so it goes where governance changes go. A permission
    that appears with no record of who created it is one nobody can be asked about."""
    emitted: list[tuple] = []
    monkeypatch.setattr("aughor.kernel.ledger.Ledger.default",
                        staticmethod(lambda: type("L", (), {
                            "emit": lambda _self, kind, payload=None, **kw:
                                emitted.append((kind, payload or {}))})()))
    s = _discovered()
    _grant(s.id, MUTATING, by="amit")
    store.delete_grant(s.id, MUTATING, reason="withdrawn by a person")

    kinds = [k for k, _ in emitted]
    assert "mcp.tool.granted" in kinds
    assert "mcp.tool.grant_revoked" in kinds
    granted = next(p for k, p in emitted if k == "mcp.tool.granted")
    assert granted["tool"] == MUTATING and granted["granted_by"] == "amit"


# ── `uncertain`: the outcome the read-only slice promised would arrive with writes ──

class _Unreachable:
    def __call__(self, *_a, **_k):
        from aughor.mcpservers.session import McpUnreachable
        raise McpUnreachable("the pipe closed mid-call")


def test_a_transport_failure_on_a_GRANTED_call_is_UNCERTAIN_not_failed(monkeypatch):
    """The read-only slice said the absence of `uncertain` was load-bearing and that the day
    writes landed it would come with them. A write whose answer was lost may have been
    performed, and calling that `failed` invites a retry that mutates twice.
    """
    s = _discovered()
    _grant(s.id, MUTATING)
    monkeypatch.setattr("aughor.mcpservers.call.call_tool", _Unreachable())

    result = door.call(s.id, MUTATING, {"target": "x"})
    assert result.status == "uncertain", (
        f"a lost WRITE was reported as {result.status!r} — a caller will retry it")
    assert result.writes is True
    assert "NOT known whether the call took effect" in result.message


def test_the_same_failure_on_a_READ_is_still_plainly_FAILED(monkeypatch):
    """`uncertain` must not leak onto reads, or it stops meaning anything: a caller that saw
    it everywhere would learn to treat it as `failed` and retry the writes too."""
    s = _discovered()
    monkeypatch.setattr("aughor.mcpservers.call.call_tool", _Unreachable())
    result = door.call(s.id, READONLY, {"city": "Lisbon"})
    assert result.status == "failed"
    assert result.writes is False


# ── the store's own shape ────────────────────────────────────────────────────────

def test_a_grant_is_keyed_by_server_AND_tool():
    assert grant_key("a", "t") != grant_key("b", "t")
    assert grant_key("a", "t") == McpToolGrant(server_id="a", tool_name="t").key


def test_grants_survive_a_roster_replacement_that_changed_nothing():
    """The roster is replaced wholesale on every discovery; the grants are not. A grant
    stored inside the roster row would be destroyed by the next `save_roster`."""
    s = _discovered()
    _grant(s.id, MUTATING)
    tools, _ = store.get_roster(s.id)
    store.save_roster(s.id, tools)
    assert store.get_grant(s.id, MUTATING) is not None


# ── the two surfaces that must learn the same thing (a partial add is the failure) ──

def _step(server_id: str, tool: str):
    from aughor.automations.models import Effect
    return Effect(kind="mcp_call", alias="ask",
                  config={"server_id": server_id, "tool": tool, "arguments": {}})


def test_a_GRANTED_tool_may_be_SAVED_as_a_chain_step():
    """A grant that the door honours but `validate_chain` refuses would be a permission a
    person cannot spend — the step would be unsavable and the capability unreachable."""
    from aughor.automations.dataflow import validate_chain
    s = _discovered()
    assert validate_chain([_step(s.id, MUTATING)]) is not None, (
        "guard: an ungranted mutating step must be refused, or the assertion below passes "
        "vacuously")
    _grant(s.id, MUTATING)
    assert validate_chain([_step(s.id, MUTATING)]) is None


def test_a_step_whose_grant_went_STALE_is_refused_at_SAVE_with_the_drift_sentence():
    """A chain that would refuse at 07:00 against somebody else's machine is one that looks
    schedulable — K1's expensive kind of broken."""
    from aughor.automations.dataflow import validate_chain
    s = _discovered()
    _grant(s.id, MUTATING)
    _drift(s.id, MUTATING, destructive_hint=False)
    problem = validate_chain([_step(s.id, MUTATING)])
    assert problem and "no longer covers" in problem


def _remote_tools():
    from aughor.components.registry import _remote_tool_components
    return {c.id: c for c in _remote_tool_components()}


def test_the_palette_shows_a_granted_tool_as_READY_and_badges_it_as_a_write():
    """LISTED and refused was the read-only slice's law; listed and READY is the write
    slice's, and a write that renders identically to a read hides the one property a reader
    most needs before dropping it on a canvas that runs unattended."""
    s = _discovered()
    before = _remote_tools()[f"remote_tool:{s.id}:{MUTATING}"]
    assert before.availability == "unavailable"

    _grant(s.id, MUTATING)
    after = _remote_tools()[f"remote_tool:{s.id}:{MUTATING}"]
    assert after.availability == "ready"
    assert "writes" in after.badges


def test_the_palette_marks_a_STALE_grant_as_needs_setup_not_unavailable():
    """Somebody DID ratify this. The actionable sentence is 'look again', not 'ask for
    permission' — two different states that a single 'unavailable' would flatten."""
    s = _discovered()
    _grant(s.id, MUTATING)
    _drift(s.id, MUTATING, destructive_hint=False)
    row = _remote_tools()[f"remote_tool:{s.id}:{MUTATING}"]
    assert row.availability == "needs_setup"
    assert "no longer applies" in row.reason


def test_a_switched_off_SERVER_still_dims_a_granted_tool():
    """The server's state dims every one of its rows. A grant is permission to call a tool,
    never permission to wake a destination a person switched off."""
    s = _discovered()
    _grant(s.id, MUTATING)
    store.save_server(s.model_copy(update={"enabled": False}))
    row = _remote_tools()[f"remote_tool:{s.id}:{MUTATING}"]
    assert row.availability == "needs_setup"
    assert "switched off" in row.reason
    assert door.call(s.id, MUTATING, {"target": "x"}).status == "refused"


# ── the whole vertical, through the engine ───────────────────────────────────────

def _chain(server_id: str, tool: str, **cfg):
    from aughor.automations.models import Automation, Condition, Effect
    return Automation(
        name="write slice", conn_id="thelook", max_retries=0,
        conditions=[Condition(kind="schedule", config={"cron": "0 9 * * *"})],
        effects=[Effect(kind="mcp_call", alias="ask",
                        config={"server_id": server_id, "tool": tool, **cfg})])


def test_a_granted_write_RUNS_through_the_engine():
    """The whole vertical: an allowlisted server, a tool its own server refuses, a human's
    grant, a chain step, the one door, and a real subprocess."""
    from aughor.automations.engine import run_automation
    s = _discovered()
    _grant(s.id, MUTATING)
    run = run_automation(_chain(s.id, MUTATING, arguments={"target": "row-9"}),
                         manual=True, persist=False)
    assert run.outcome == "fired", run.reason
    outcome = run.effects[0]
    assert outcome.status == "executed", outcome.message
    assert "deleted row-9" in outcome.data["text"]


def test_a_lost_WRITE_reaches_the_engine_as_uncertain_and_is_NEVER_RETRIED(monkeypatch):
    """🔑 The reason `uncertain` exists at all, asserted where it matters — the engine.

    `EffectOutcome`'s own docstring makes the rule ("Never retried; 'failed' still is"), so
    the load-bearing claim is that a lost write arrives wearing THAT status rather than
    `failed`. A granted MCP call reported as `failed` would be retried by a plane that was
    built to retry it, and the mutation would run twice — which is the single outcome a
    write gate exists to prevent.
    """
    from aughor.automations.engine import run_automation
    s = _discovered()
    _grant(s.id, MUTATING)
    monkeypatch.setattr("aughor.mcpservers.call.call_tool", _Unreachable())

    run = run_automation(_chain(s.id, MUTATING, arguments={"target": "x"}),
                         manual=True, persist=False)
    outcome = run.effects[0]
    assert outcome.status == "uncertain", (
        f"a lost WRITE arrived as {outcome.status!r}; the engine retries 'failed'")
    assert outcome.attempts == 1, "an uncertain write was retried"


# ── the HTTP surface ─────────────────────────────────────────────────────────────

def test_the_route_pins_the_declaration_from_the_ROSTER_not_the_request(client):
    """The load-bearing property of the grant API. `GrantRequest` carries no declaration
    fields at all, so a client cannot state which declaration it is approving — one that
    could would be able to approve a declaration the server never made, which turns the
    pinning that makes drift detectable into a value the caller chooses.
    """
    s = _discovered()
    res = client.put(f"/mcp-servers/{s.id}/grants/{MUTATING}",
                     json={"granted_by": "amit", "note": "cleanup job",
                           # Ignored — and that is the claim.
                           "read_only_hint": True, "destructive_hint": False})
    assert res.status_code == 200, res.text

    stored = store.get_grant(s.id, MUTATING)
    assert stored is not None
    assert stored.read_only_hint is False and stored.destructive_hint is True, (
        "the request's declaration was believed; a caller could grant a tool as read-only "
        "and defeat drift detection")
    assert stored.granted_by == "amit" and stored.note == "cleanup job"


def test_granting_an_UNDISCOVERED_tool_is_404_not_a_grant_for_nothing(client):
    s = _server()
    res = client.put(f"/mcp-servers/{s.id}/grants/whatever", json={})
    assert res.status_code == 404
    assert "discovered roster" in res.json()["detail"]


def test_granting_an_ALREADY_CALLABLE_tool_is_refused(client):
    """A grant that authorizes nothing would then go stale on a declaration change and read
    as a revocation of a permission the tool never needed."""
    s = _discovered()
    res = client.put(f"/mcp-servers/{s.id}/grants/{READONLY}", json={})
    assert res.status_code == 409
    assert "needs no grant" in res.json()["detail"]


def test_the_grant_route_returns_the_server_with_the_new_state(client):
    """The client re-reads rather than guessing — so the route must hand back the truth it
    just created, or the surface paints a state the API did not agree to."""
    s = _discovered()
    body = client.put(f"/mcp-servers/{s.id}/grants/{MUTATING}", json={}).json()
    row = next(t for t in body["server"]["tools"] if t["name"] == MUTATING)
    assert row["grant_state"] == "active"
    assert row["callable_now"] is True
    assert body["server"]["granted_count"] == 1
    # Still the server's own verdict — a grant does not rewrite what the server said.
    assert row["disposition"] == "refused_mutating"


def test_revoking_a_grant_that_is_not_there_is_404(client):
    s = _discovered()
    assert client.delete(f"/mcp-servers/{s.id}/grants/{MUTATING}").status_code == 404


def test_the_list_route_reads_every_grant_ONCE(client, monkeypatch):
    """`all_rosters`'s discipline on the plane beside it: a list route doing one store round
    trip per server is the palette-paying-a-subprocess-for-a-picture shape, one layer in."""
    _discovered()
    _discovered(_SERVER_ID_B)
    calls = []
    real = store.list_grants
    monkeypatch.setattr(store, "list_grants", lambda: (calls.append(1), real())[1])
    assert client.get("/mcp-servers").status_code == 200
    assert len(calls) == 1, f"read the grant store {len(calls)}× for 2 servers"
