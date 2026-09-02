"""DS-14 — an enabled automation, exposed as a tool on our MCP server.

The eighteen tools this server ships are what this VERSION of Aughor can do; an
automation is what THIS deployment's people built. It appears at runtime, it is named by
whoever made it, and no decorator can know about it — so these are registered dynamically
at server start from the one route that says which chains their owners opted in.

The claim being tested is narrow and worth stating exactly: **the caller changes, the
governance does not.** The tool is a wrapper over the same `POST /automations/{id}/run`
the web app's "Run now" presses, so the chain lands in the one engine, writes the run row
Activity reads, and a governed write inside it still parks for the approval gate rather
than firing because the request arrived over MCP.

Four failures a plausible implementation ships, pinned here:

* **Late binding.** Building the closure inline in the loop captures the loop variable, so
  every registered tool runs whichever automation was last — the right NUMBER of tools,
  each doing the wrong thing, and nothing looks wrong until one is called.
* **Shadowing.** An automation someone called "Ask" must not replace `ask`.
* **A dead API taking the server down.** The static tools are the ones you would use to
  find out why the API is down; refusing to start without them helps nobody.
* **Exposing everything.** A deployment's automations are its private machinery.
"""
from __future__ import annotations

import asyncio

import pytest

from aughor.mcp import server as S


def _run(coro):
    return asyncio.run(coro)


class _FakeClient:
    """An AughorClient stand-in: records what was run, answers from a fixed roster."""

    def __init__(self, tools, fail: bool = False):
        self._tools, self._fail = tools, fail
        self.ran: list[str] = []

    async def list_automation_tools(self):
        if self._fail:
            raise RuntimeError("connection refused")
        return self._tools

    async def run_automation(self, automation_id: str):
        self.ran.append(automation_id)
        return {"id": f"run-{automation_id}", "outcome": "fired", "reason": "by hand",
                "effects": [{"kind": "slack_post", "status": "executed", "message": "posted"}]}


@pytest.fixture(autouse=True)
def _clean_automations():
    """The automations store is SESSION-scoped, so a chain saved by one test is still
    there when the next one asks what is exposed. Learned the same way one file over: a
    suite that leaves rows behind fails in the full run and passes on its own."""
    from aughor.automations.store import delete_automation, list_automations
    for a in list_automations(conn_id="ds14"):
        delete_automation(a.id)
    yield
    for a in list_automations(conn_id="ds14"):
        delete_automation(a.id)


@pytest.fixture(autouse=True)
def _clean_registry():
    """Registration mutates the module-level server. Remove only what a test added, so the
    eighteen static tools are still there for the next one."""
    before = set(getattr(S.mcp._tool_manager, "_tools", {}) or {})
    yield
    for name in set(getattr(S.mcp._tool_manager, "_tools", {}) or {}) - before:
        S.mcp._tool_manager.remove_tool(name)


# ── the flag, and the column behind it ────────────────────────────────────────

def _automation(name: str, *, exposed: bool, enabled: bool = True, conn="ds14"):
    from aughor.automations.models import Automation, Condition, Effect
    from aughor.automations.store import upsert_automation
    return upsert_automation(Automation(
        name=name, conn_id=conn, exposed_as_tool=exposed, enabled=enabled,
        conditions=[Condition(kind="schedule", config={"cron": "0 9 * * *"})],
        effects=[Effect(kind="investigate", config={"question": "how are sales?"}),
                 Effect(kind="slack_post", config={"bot_id": "b", "channel": "#ops"})]))


def test_the_flag_survives_a_round_trip_through_the_store():
    """The half-added-field trap this store carries three warnings about: SQLite's named
    binding ignores a key with no column, so a model attribute without a migration reads
    back as its default and NOTHING raises. Here that default would silently un-expose a
    tool an operator had opted in — or, read the other way, is the one assertion that
    proves the column exists."""
    from aughor.automations.store import get_automation
    saved = _automation("Daily sales report", exposed=True)
    assert get_automation(saved.id).exposed_as_tool is True

    flipped = _automation("Daily sales report", exposed=False)
    assert get_automation(flipped.id).exposed_as_tool is False


def test_the_flag_defaults_OFF():
    """A deployment's automations are its private machinery. Exposure is opt-in."""
    from aughor.automations.models import Automation, Condition, Effect
    a = Automation(name="x", conn_id="c",
                   conditions=[Condition(kind="schedule", config={"cron": "0 9 * * *"})],
                   effects=[Effect(kind="investigate", config={"question": "q"})])
    assert a.exposed_as_tool is False


# ── the route the server reads ────────────────────────────────────────────────

def _tools(conn="ds14"):
    from aughor.routers.automations import exposed_tools
    return exposed_tools(conn_id=conn)


def test_only_opted_in_automations_are_offered():
    _automation("Offered chain", exposed=True)
    _automation("Private chain", exposed=False)
    names = [t["name"] for t in _tools()["tools"]]
    assert names == ["Offered chain"]


def test_a_DISABLED_automation_is_not_callable_from_outside():
    """`exposed_as_tool` is the intent and `enabled` is the switch. A chain somebody
    deliberately switched off staying callable over MCP would make the off switch a lie
    for exactly the caller nobody is watching."""
    _automation("Switched off", exposed=True, enabled=False)
    assert _tools()["tools"] == []


def test_the_offered_row_carries_what_a_model_needs_to_choose():
    _automation("Daily sales report", exposed=True)
    row = _tools()["tools"][0]
    assert row["tool_name"] == "daily_sales_report"
    # The steps, so the description can say what the chain DOES.
    assert row["steps"] == ["investigate", "slack_post"]


def test_two_automations_that_would_answer_to_one_name_are_refused_not_silently_dropped():
    """Two tools a client cannot tell apart is worse than one missing tool. The first by
    creation order keeps the name; the other comes back with a reason an operator can act
    on rather than simply being absent."""
    _automation("Daily sales report", exposed=True)
    _automation("daily sales REPORT!", exposed=True)
    out = _tools()
    assert [t["tool_name"] for t in out["tools"]] == ["daily_sales_report"]
    assert len(out["refused"]) == 1
    assert "rename" in out["refused"][0]["reason"]


# ── the name ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("given,expected", [
    ("Daily sales report", "daily_sales_report"),
    ("DS-6 receipt: revenue routing", "ds_6_receipt_revenue_routing"),
    ("   Trim   me   ", "trim_me"),
    ("!!!", "automation"),          # never empty — an unnamed tool cannot be called
    ("", "automation"),
])
def test_the_tool_is_named_in_the_authors_words(given, expected):
    """Their words, not an id: an agent choosing between tools reads the name, and
    `run_a1671c53` tells it nothing."""
    assert S.automation_tool_name(given) == expected


# ── registration ──────────────────────────────────────────────────────────────

def test_each_exposed_automation_becomes_its_own_tool():
    client = _FakeClient([
        {"id": "a1", "name": "Daily sales report", "tool_name": "daily_sales_report",
         "description": "Posts yesterday's numbers", "steps": ["investigate", "slack_post"]},
        {"id": "a2", "name": "Weekly churn sweep", "tool_name": "weekly_churn_sweep"},
    ])
    added = _run(S.register_automation_tools(client))
    assert added == ["daily_sales_report", "weekly_churn_sweep"]
    registered = set(getattr(S.mcp._tool_manager, "_tools", {}) or {})
    assert {"daily_sales_report", "weekly_churn_sweep"} <= registered


def test_each_tool_runs_ITS_OWN_automation():
    """The late-binding bug. A closure built inline in the loop captures the loop
    variable, so every tool would fire the LAST automation — the right number of tools,
    each doing the wrong thing."""
    client = _FakeClient([
        {"id": "a1", "name": "first", "tool_name": "first"},
        {"id": "a2", "name": "second", "tool_name": "second"},
        {"id": "a3", "name": "third", "tool_name": "third"},
    ])
    _run(S.register_automation_tools(client))
    tools = getattr(S.mcp._tool_manager, "_tools", {})
    _run(tools["first"].fn())
    _run(tools["third"].fn())
    assert client.ran == ["a1", "a3"], "a tool fired the wrong automation"


def test_a_name_that_would_shadow_a_static_tool_is_skipped():
    """`ask` is the governed answer path. Replacing it with somebody's chain would be a
    substitution nobody would think to look for."""
    client = _FakeClient([{"id": "a1", "name": "Ask", "tool_name": "ask"},
                          {"id": "a2", "name": "Fine", "tool_name": "fine"}])
    added = _run(S.register_automation_tools(client))
    assert added == ["fine"]
    # `ask` still belongs to the static server, not to the automation.
    assert S.mcp._tool_manager._tools["ask"].fn.__module__ == S.__name__


def test_a_dead_api_leaves_the_static_tools_standing():
    """The static tools are the ones you would use to diagnose the outage."""
    added = _run(S.register_automation_tools(_FakeClient([], fail=True)))
    assert added == []
    assert "ask" in getattr(S.mcp._tool_manager, "_tools", {})


def test_a_row_with_no_id_is_ignored_rather_than_registered_as_a_broken_tool():
    client = _FakeClient([{"name": "nameless", "tool_name": "nameless"}])
    assert _run(S.register_automation_tools(client)) == []


# ── what the tool says and returns ────────────────────────────────────────────

def test_the_description_names_the_steps_and_the_governance():
    """"Runs an automation" is not a description anyone can choose on. A model picking
    between tools needs to know this one posts to Slack — and that a governed write in it
    will stop for a human."""
    text = S._automation_description(
        {"name": "Daily sales report", "description": "Posts yesterday's numbers",
         "steps": ["investigate", "slack_post"]})
    assert "Posts yesterday's numbers" in text
    assert "investigate" in text and "slack_post" in text
    assert "approval" in text.lower()


def test_the_result_is_a_verdict_not_the_whole_run_record():
    """The full row is in Activity, where it belongs. What the caller needs is whether it
    fired and what happened."""
    client = _FakeClient([{"id": "a1", "name": "x", "tool_name": "x"}])
    _run(S.register_automation_tools(client))
    out = _run(getattr(S.mcp._tool_manager, "_tools")["x"].fn())
    assert out["outcome"] == "fired"
    assert out["run_id"] == "run-a1"
    assert out["steps"] == [{"kind": "slack_post", "status": "executed", "message": "posted"}]
