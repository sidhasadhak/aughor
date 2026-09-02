"""VA-9d — the consumer as a CHAIN STEP, which is the half that makes it leveraged.

A plane that is built and tested but that nothing can reach is this repo's recurring
failure — §7 names it, VA-11 paid for it once (a vault that minted tokens no capability
could spend), and the roadmap's own note on the declared-action plane says features stall
at TESTED, not at leveraged. So the allowlist is not finished when `call()` works; it is
finished when a chain can name a tool and the engine runs it.

What these lock, in order of how badly a plausible implementation gets them wrong:

* **The save refuses what the engine would refuse.** A step naming an unknown server, an
  undiscovered tool, or a tool this deployment declines is refused at SAVE — K1's rule —
  rather than surfacing at 07:00 as somebody else's 404.
* **Neither `server_id` nor `tool` may be bound.** The DS-11 trap, and worse here:
  `BINDABLE_FIELDS` declares `arguments` as the only port but `resolve()` walks the whole
  config, so a `{"$from": …}` on `server_id` would let an upstream value choose which third
  party gets called. That is an arbitrary-destination call wearing a named one's clothes.
* **A refusal is terminal, a cap is not.** `refused` → `dispatch_error` (retrying never
  changes it); `blocked` → `failed` (a cap window rolls over).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from aughor.automations.dataflow import validate_chain
from aughor.automations.models import Automation, Condition, Effect
from aughor.mcpservers import store
from aughor.mcpservers.discover import discover
from aughor.mcpservers.models import McpServer

_FIXTURE_SERVER = Path(__file__).parent / "fixtures" / "mcp_fixture_server.py"
CONN = "va9d"


@pytest.fixture(autouse=True)
def _clean():
    for s in store.list_servers():
        store.delete_server(s.id)
    yield
    for s in store.list_servers():
        store.delete_server(s.id)


@pytest.fixture
def server() -> McpServer:
    s = store.save_server(McpServer(
        name="Fixture", transport="stdio", command=sys.executable,
        args=[str(_FIXTURE_SERVER)]))
    discover(s)
    return s


def _chain(**cfg) -> Automation:
    # `max_retries=0` because `blocked` maps to the RETRIABLE `failed`, and the default one
    # retry costs a real 30s jittered backoff — 44 seconds in one test, measured. The retry
    # semantics are asserted by the status these tests read, not by waiting for one.
    return Automation(
        name="VA-9d step", conn_id=CONN, max_retries=0,
        conditions=[Condition(kind="schedule", config={"cron": "0 9 * * *"})],
        effects=[Effect(kind="mcp_call", alias="ask", config=cfg)])


# ── the save refuses what the engine would ───────────────────────────────────────

def test_a_callable_tool_SAVES(server):
    """The guard that keeps every refusal below from passing vacuously: if `_mcp_problem`
    refused everything, each `assert problem` would still hold and the kind would be
    unusable."""
    assert validate_chain([Effect(kind="mcp_call", alias="ask", config={
        "server_id": server.id, "tool": "read_the_weather"})]) is None


def test_a_step_naming_an_unregistered_server_is_refused_at_save():
    problem = validate_chain([Effect(kind="mcp_call", alias="ask", config={
        "server_id": "mcps_nobody", "tool": "read_the_weather"})])
    assert problem and "allowlist" in problem


def test_a_step_naming_an_undiscovered_tool_is_refused_at_save(server):
    problem = validate_chain([Effect(kind="mcp_call", alias="ask", config={
        "server_id": server.id, "tool": "tool_that_was_never_discovered"})])
    assert problem and "discovered roster" in problem


def test_a_step_calling_a_MUTATING_tool_is_refused_at_save(server):
    """A chain that would always refuse at 07:00 is one that "looks schedulable", which is
    K1's expensive kind of broken. The roster's own sentence comes along."""
    problem = validate_chain([Effect(kind="mcp_call", alias="ask", config={
        "server_id": server.id, "tool": "delete_everything"})])
    assert problem and "declares the tool as modifying" in problem


def test_a_step_calling_an_UNANNOTATED_tool_is_refused_at_save(server):
    """The majority case reaching the save path, not just the classifier."""
    problem = validate_chain([Effect(kind="mcp_call", alias="ask", config={
        "server_id": server.id, "tool": "unannotated_thing"})])
    assert problem and "does not declare" in problem


@pytest.mark.parametrize("field", ["server_id", "tool"])
def test_neither_the_server_nor_the_tool_may_be_BOUND(server, field):
    """`BINDABLE_FIELDS` declares `arguments` as the only port, but `resolve()` walks the
    WHOLE config — so this has to be refused where a save actually fails."""
    cfg = {"server_id": server.id, "tool": "read_the_weather"}
    cfg[field] = {"$from": "step1.answer"}
    problem = validate_chain([Effect(kind="mcp_call", alias="ask", config=cfg)])
    assert problem and f"binds '{field}'" in problem


def test_the_two_config_keys_are_required_at_construction():
    """Every sibling kind's rule: reject at parse, never surface."""
    with pytest.raises(ValueError, match="server_id"):
        Effect(kind="mcp_call", config={"tool": "x"})
    with pytest.raises(ValueError, match="tool"):
        Effect(kind="mcp_call", config={"server_id": "s"})


# ── the engine actually runs it ──────────────────────────────────────────────────

def test_the_step_runs_and_publishes_its_text(server):
    """The whole vertical: an allowlisted server, a discovered read-only tool, a chain step,
    the one door, a real subprocess, and a value a later step could bind to."""
    from aughor.automations.engine import run_automation

    chain = _chain(server_id=server.id, tool="read_the_weather",
                   arguments={"city": "Lisbon"})
    run = run_automation(chain, manual=True, persist=False)

    assert run.outcome == "fired", run.reason
    outcome = run.effects[0]
    assert outcome.status == "executed", outcome.message
    assert "Lisbon" in outcome.data["text"]
    assert outcome.data["truncated"] is False
    # Both halves: the tool alone would make two steps calling two different third parties
    # look identical in a run history.
    assert outcome.target == f"{server.id}:read_the_weather"


def test_the_published_keys_are_what_a_later_step_may_bind(server):
    """A step advertising a key the engine does not publish is a drawn edge that resolves
    to nothing at 07:00 — B1's whole argument."""
    from aughor.automations.dataflow import PUBLISHED_KEYS
    assert set(PUBLISHED_KEYS["mcp_call"]) == {"text", "truncated"}


def test_a_refused_call_is_TERMINAL_not_retried(server, monkeypatch):
    """`dispatch_error`, not `failed`. Retrying a refusal is a request against something
    that has already said no, forever."""
    from aughor.automations.engine import run_automation

    chain = _chain(server_id=server.id, tool="read_the_weather", arguments={"city": "X"})
    # The roster is what the save checked; make the door refuse at run time the way a
    # re-discovery between save and run would.
    monkeypatch.setattr("aughor.mcpservers.call.tool_named", lambda *a, **k: None)
    run = run_automation(chain, manual=True, persist=False)
    assert run.effects[0].status == "dispatch_error"


def test_a_capped_call_is_FAILED_because_the_window_rolls_over(server, monkeypatch):
    from aughor.automations.engine import run_automation
    from aughor.govern.outbound import OutboundBlocked

    def _blocked(*_a, **_k):
        raise OutboundBlocked("mcp", "outbound cap reached")

    monkeypatch.setattr("aughor.govern.outbound.external_call", _blocked)
    chain = _chain(server_id=server.id, tool="read_the_weather", arguments={"city": "X"})
    run = run_automation(chain, manual=True, persist=False)
    assert run.effects[0].status == "failed"


def test_a_failed_call_publishes_NOTHING(server, monkeypatch):
    """A failed call's message is the server's error, not this tool's output. Publishing it
    would let a later step bind to a value that means something else entirely."""
    from aughor.automations.engine import run_automation

    monkeypatch.setattr("aughor.mcpservers.call.tool_named", lambda *a, **k: None)
    chain = _chain(server_id=server.id, tool="read_the_weather", arguments={"city": "X"})
    run = run_automation(chain, manual=True, persist=False)
    assert run.effects[0].data == {}


# ── the palette tells the truth about this deployment ────────────────────────────

def test_the_palette_dims_the_step_when_no_server_is_allowlisted():
    from aughor.automations.palette import NEEDS_SETUP, entries
    row = next(e for e in entries() if e["kind"] == "mcp_call")
    assert row["availability"] == NEEDS_SETUP
    assert "MCP servers" in row["reason"]


def test_the_palette_lights_it_once_a_server_exists(server):
    from aughor.automations.palette import READY, entries
    row = next(e for e in entries() if e["kind"] == "mcp_call")
    assert row["availability"] == READY


def test_a_DISABLED_server_does_not_light_the_row(server):
    """Counting rows would have said otherwise — the distinction this module already draws
    for a revoked grant and a disabled Slack bot."""
    from aughor.automations.palette import NEEDS_SETUP, entries
    server.enabled = False
    store.save_server(server)
    row = next(e for e in entries() if e["kind"] == "mcp_call")
    assert row["availability"] == NEEDS_SETUP


# ── the registry family ──────────────────────────────────────────────────────────

def test_discovered_tools_appear_as_their_OWN_family(server):
    """Not as `mcp_tool`, which is what we SERVE. The two point in opposite directions and
    a flat family holding both would answer confidently and wrongly."""
    from aughor.components import components

    rows = {c.id: c for c in components() if c.family == "remote_tool"}
    assert f"remote_tool:{server.id}:read_the_weather" in rows
    assert rows[f"remote_tool:{server.id}:read_the_weather"].availability == "ready"
    # Listed, not hidden — the catalogue-that-lies failure DS-10 exists to end.
    refused = rows[f"remote_tool:{server.id}:delete_everything"]
    assert refused.availability == "unavailable"
    assert "declares the tool as modifying" in refused.reason


def test_a_remote_tool_names_the_ONE_DOOR_as_its_governor(server):
    from aughor.components import components
    rows = [c for c in components() if c.family == "remote_tool"]
    assert rows and all(c.governed_by == "aughor.mcpservers.call" for c in rows)
