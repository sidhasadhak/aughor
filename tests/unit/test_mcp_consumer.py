"""VA-9d — the MCP consumer: the allowlist, the read-only gate, and the one door.

VA-9's own risk note calls a foreign MCP server "the largest new attack surface in the
arc", so these tests are mostly about what does NOT happen.

The load-bearing claim, and the one a plausible implementation gets backwards:

    **A tool that declares nothing is refused.**

It is tempting to read "a tool the server declares as mutating is listed and refused" as
"refuse the ones flagged mutating, allow the rest" — which would allow the overwhelming
majority of real tools, because most servers set no annotations at all. The protocol
settles it rather than leaving it to taste: `readOnlyHint` is documented *"Default: false"*
and `destructiveHint` *"Default: true"*, so silence is not an absence of an answer, it IS
the answer "may modify, possibly destructively". `classify()` is the one place that decides
and every surface quotes it.

The suite drives a REAL MCP server over a real stdio transport (`_FIXTURE_SERVER`), because
the thing most likely to be wrong here is our reading of somebody else's protocol, and a
mock of that protocol would be a mock of our own misunderstanding.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from aughor.mcpservers import call as door
from aughor.mcpservers import store
from aughor.mcpservers.discover import discover, health, tool_named
from aughor.mcpservers.models import (
    CALLABLE, REFUSED_MUTATING, McpServer, McpTool, classify,
)
from aughor.mcpservers.session import McpUnreachable

#: A real MCP server, in-tree, offering one tool of each annotation shape. Written as a
#: file rather than constructed in-process because stdio is the transport being proven —
#: an in-memory session would exercise our classification and none of our plumbing.
_FIXTURE_SERVER = Path(__file__).parent / "fixtures" / "mcp_fixture_server.py"


@pytest.fixture(autouse=True)
def _clean_allowlist():
    """The allowlist is a shared store like every other in this suite. A server left behind
    is an outbound destination the next file inherits."""
    for s in store.list_servers():
        store.delete_server(s.id)
    yield
    for s in store.list_servers():
        store.delete_server(s.id)


def _fixture_server(**over) -> McpServer:
    fields = {"name": "Fixture", "transport": "stdio", "command": sys.executable,
              "args": [str(_FIXTURE_SERVER)], **over}
    return store.save_server(McpServer(**fields))


# ── the classification, which is the whole posture ───────────────────────────────

def test_a_declared_read_only_tool_is_callable():
    assert classify(True, None) == (CALLABLE, "")


def test_a_declared_mutating_tool_is_refused():
    disposition, reason = classify(False, None)
    assert disposition == REFUSED_MUTATING
    assert "declares the tool as modifying" in reason


def test_a_tool_that_declares_NOTHING_is_refused():
    """The majority case, and the one a plausible implementation allows.

    The protocol's own defaults make this the specification's answer rather than our
    preference: an absent `readOnlyHint` means false, and an absent `destructiveHint` under
    a false `readOnlyHint` means true.
    """
    disposition, reason = classify(None, None)
    assert disposition == REFUSED_MUTATING
    assert "does not declare" in reason


def test_a_contradictory_declaration_takes_the_RESTRICTIVE_reading():
    """`destructiveHint` is documented as meaningful only when `readOnlyHint` is false, so a
    server setting both is contradicting itself. Guessing which half was meant is how a
    refusal turns into a write."""
    disposition, reason = classify(True, True)
    assert disposition == REFUSED_MUTATING
    assert "contradiction" in reason


def test_only_an_explicit_true_opens_the_door():
    """The whole table, so a refactor that flattened it has to fail here."""
    assert classify(True, False)[0] == CALLABLE
    for read_only, destructive in [(None, None), (None, True), (None, False),
                                   (False, None), (False, True), (False, False),
                                   (True, True)]:
        assert classify(read_only, destructive)[0] == REFUSED_MUTATING, (read_only, destructive)


# ── the allowlist IS the off state ───────────────────────────────────────────────

def test_a_fresh_deployment_reaches_nothing():
    """Not because a flag says so — `FLAG_DEFAULT` has been empty since the flag endgame,
    and a switch somebody must remember to leave closed is the control this repo already
    replaced once. There is simply nowhere to go."""
    assert store.list_servers() == []
    r = door.call("mcps_anything", "any_tool", {})
    assert r.status == "refused"
    assert "registered" in r.message


def test_a_switched_off_server_refuses_without_being_forgotten():
    s = _fixture_server()
    discover(s)
    s.enabled = False
    store.save_server(s)

    r = door.call(s.id, "read_the_weather", {"city": "Berlin"})
    assert r.status == "refused"
    assert "switched off" in r.message
    # Still on the allowlist, roster intact — "off" and "deleted" are different intents.
    assert store.get_server(s.id) is not None
    assert tool_named(s.id, "read_the_weather") is not None


def test_deleting_a_server_forgets_its_roster_too():
    """A roster outliving its server keeps a palette row alive for a destination nobody can
    reach — DS-17 paid for the same lesson with a webhook token that outlived its chain."""
    s = _fixture_server()
    discover(s)
    assert tool_named(s.id, "read_the_weather") is not None

    assert store.delete_server(s.id) is True
    assert tool_named(s.id, "read_the_weather") is None


# ── discovery against a REAL server over a REAL transport ────────────────────────

def test_discovery_reaches_a_real_server_and_classifies_every_tool():
    s = _fixture_server()
    tools, _ = discover(s)
    by_name = {t.name: t for t in tools}

    assert by_name["read_the_weather"].disposition == CALLABLE
    assert by_name["delete_everything"].disposition == REFUSED_MUTATING
    assert by_name["unannotated_thing"].disposition == REFUSED_MUTATING
    # The server's own words are kept beside our verdict, so a reader can check us.
    assert by_name["read_the_weather"].read_only_hint is True
    assert by_name["unannotated_thing"].read_only_hint is None


def test_the_roster_carries_when_it_was_read():
    """A cached remote list presented as if it were live is the failure the pair exists to
    prevent, so the timestamp comes back WITH the tools rather than being findable."""
    s = _fixture_server()
    discover(s)
    tools, discovered_at = store.get_roster(s.id)
    assert tools and discovered_at


def test_rediscovery_REPLACES_rather_than_merges():
    """A tool the server stopped offering must disappear. Merging would leave a palette row
    for something that no longer exists — and the reader cannot tell which rows are ghosts."""
    s = _fixture_server()
    store.save_roster(s.id, [McpTool(server_id=s.id, name="ghost_from_last_week")])
    discover(s)
    assert tool_named(s.id, "ghost_from_last_week") is None


def test_health_says_how_many_tools_this_deployment_may_actually_call():
    """The number that surprises people: a server can be perfectly healthy and offer this
    deployment nothing it may call."""
    h = health(_fixture_server())
    assert h["ok"] is True
    assert h["tool_count"] == 3
    assert h["callable_count"] == 1


def test_an_unreachable_server_is_a_verdict_not_an_empty_roster():
    """"They are down" and "they offer nothing" are different sentences, and a caller that
    cannot tell them apart shows the reader the wrong one."""
    s = store.save_server(McpServer(name="Ghost", transport="stdio",
                                    command="definitely-not-an-executable-xyz"))
    with pytest.raises(McpUnreachable):
        discover(s)

    h = health(s)
    assert h["ok"] is False and h["reason"]


# ── the door ─────────────────────────────────────────────────────────────────────

def test_a_read_only_tool_runs_and_returns_its_text():
    s = _fixture_server()
    discover(s)
    r = door.call(s.id, "read_the_weather", {"city": "Berlin"})
    assert r.status == "executed", r.message
    assert "Berlin" in r.text
    assert r.truncated is False


def test_a_mutating_tool_is_refused_AT_THE_DOOR_not_only_on_the_roster():
    """The roster is a picture; this is the gate. A surface that dimmed the row but let the
    engine through would be the palette-that-lies failure with the consequences reversed."""
    s = _fixture_server()
    discover(s)
    r = door.call(s.id, "delete_everything", {"target": "prod"})
    assert r.status == "refused"
    assert r.text == ""


def test_the_refusal_is_the_ROSTERS_sentence_verbatim():
    """Three wordings of one refusal is how a reader learns the product has three opinions
    about it."""
    s = _fixture_server()
    discover(s)
    tool = tool_named(s.id, "unannotated_thing")
    assert door.call(s.id, "unannotated_thing", {"x": "1"}).message == tool.reason


def test_an_undiscovered_NAME_is_refused_rather_than_forwarded_hopefully():
    """Forwarding an unknown name would make this an arbitrary-tool-call surface against a
    third party — the URL-field shape §3.4 refuses for `connection_call`."""
    s = _fixture_server()
    discover(s)
    r = door.call(s.id, "tool_the_server_never_mentioned", {})
    assert r.status == "refused"
    assert "no discovered tool" in r.message


def test_a_usage_cap_BLOCKS_rather_than_refuses(monkeypatch):
    """The three outcomes are never flattened into two: `blocked` means nothing was sent and
    the same call is legitimate next window, `refused` means we declined and retrying
    changes nothing. A caller that could not tell them apart would retry a refusal forever."""
    from aughor.govern.outbound import OutboundBlocked

    s = _fixture_server()
    discover(s)

    def _blocked(*_a, **_k):
        raise OutboundBlocked("mcp", "monthly outbound cap reached")

    monkeypatch.setattr("aughor.govern.outbound.external_call", _blocked)
    r = door.call(s.id, "read_the_weather", {"city": "Berlin"})
    assert r.status == "blocked"
    assert "cap" in r.message


def test_every_call_is_RECORDED_not_merely_wrapped(monkeypatch):
    """VA-9a exists BECAUSE of this wave — its own docstring says adding an MCP consumer on
    top of a plane that cannot see or budget what leaves would scale the blindness.

    🔴 This test asserts the LEDGER, and the first version asserted the seam. That version
    passed while discovery recorded NOTHING on the live path, and driving it is what found
    the gap: `session_log.emit` drops any event with no ambient trace, deliberately, and a
    discovery pressed from a route has none. Spying on `external_call` proved the wrapper
    was entered; it could not prove anything was written, and the wrapper being entered was
    never the claim. A proxy is not the measure.
    """
    from aughor.telemetry import current_trace_id

    recorded: list[tuple] = []

    def _emit(kind, **kw):
        # The AMBIENT TRACE at the moment of emission is the thing that was broken, so it
        # is the thing recorded here. Asserting only that `emit` was reached would repeat
        # the first version's mistake one layer down: stubbing `emit` bypasses the very
        # guard that was dropping these events, so a stub that ignored the trace could not
        # fail no matter how badly the trace was missing.
        recorded.append((kind, kw.get("name", ""), kw.get("trace_id") or current_trace_id()))

    monkeypatch.setattr("aughor.obs.session_log.emit", _emit)
    s = _fixture_server()
    discover(s)
    door.call(s.id, "read_the_weather", {"city": "Berlin"})

    by_name = {name: trace for kind, name, trace in recorded if kind == "external_call"}
    for expected in (f"mcp:{s.id}.tools/list", f"mcp:{s.id}.tools/call:read_the_weather"):
        assert expected in by_name, f"{expected} left no record at all"
        assert by_name[expected], (
            f"{expected} was emitted with NO TRACE — the real `emit` drops those, so this "
            f"call would be capped and spanned and never recorded")


def test_the_service_name_is_the_ID_not_the_renameable_display_name():
    """`service` is what a cap is written against and what an audit line is read back by; a
    name a person can rename would silently detach both."""
    from aughor.mcpservers.models import service_name
    s = _fixture_server(name="Finance tools")
    assert service_name(s) == f"mcp:{s.id}"


# ── the record refuses to be half-configured ─────────────────────────────────────

def test_a_stdio_server_without_a_command_is_refused_at_parse():
    """K1: reject at parse, never surface. A row missing the one field its transport needs
    would sit in the table looking reachable and fail on the first call — and a discovery
    failure reads as "their server is down", which sends the reader to somebody else's
    machine."""
    with pytest.raises(ValueError, match="command"):
        McpServer(transport="stdio")
    with pytest.raises(ValueError, match="url"):
        McpServer(transport="http")


def test_the_two_transports_do_not_share_fields():
    with pytest.raises(ValueError, match="no `url`"):
        McpServer(transport="stdio", command="x", url="https://example.com")
    with pytest.raises(ValueError, match="no `command`"):
        McpServer(transport="http", url="https://example.com", command="x")


def test_the_auth_header_never_leaves_in_a_read():
    # The fixture value is deliberately NOT key-shaped. GitHub push protection blocks even
    # FAKE secrets that match a provider's pattern, and the remedy is a history rewrite —
    # this repo has paid for that once.
    """Dropped, not masked — `Connection.to_safe_dict`'s rule: a mask still confirms a
    secret's length-class and invites a client to store the field."""
    s = McpServer(name="A", transport="http", url="https://example.com",
                  auth_header="Bearer not-a-real-credential")
    safe = s.to_safe_dict()
    assert "auth_header" not in safe
    assert safe["has_auth"] is True
    assert "not-a-real-credential" not in repr(safe)


def test_the_auth_header_is_encrypted_at_rest():
    s = store.save_server(McpServer(name="A", transport="http",
                                    url="https://example.com",
                                    auth_header="Bearer not-a-real-credential"))
    raw = repr(store._SERVERS.get(s.id))
    assert "not-a-real-credential" not in raw
    # …and comes back intact for the one caller that must send it.
    assert store.get_server(s.id).auth_header == "Bearer not-a-real-credential"
