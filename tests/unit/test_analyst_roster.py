"""The analyst's roster is the analysis path's tools, not the chat roster.

`analyst_tools` used to end `+ platform_tools(...)` — all twelve platform reads, offered
on every turn of a loop whose tail reaches 56 calls. The live session log says the model
never wanted them: across 14 analyst turns the twelve were offered every time and exactly
one was ever called (`propose_context_note`, once).

These tests hold that trim in place. The load-bearing one is
`test_the_kept_platform_tool_is_actually_in_the_built_roster`: membership is by NAME
against the live `platform_tools` output, so a rename would empty the filter and silently
drop the kept tool — and a test that only checked the ELEVEN were absent would go green on
exactly that failure. Same for the dropped names themselves: asserting "not in the analyst
roster" passes for free if the name is a typo, so each one is first proven to be a real
platform tool.
"""
from types import SimpleNamespace

from aughor.agent.analyst import _ANALYST_PLATFORM_TOOLS, analyst_tools

#: What the analyst is offered, in full. A pin, not a filter: a tool added to this path
#: has to be added here too, which is the point — the roster is the prompt's largest fixed
#: cost and it should not grow by accident.
EXPECTED = {
    # the phase library
    "baseline", "decompose", "cross_section", "premise_check",
    # deterministic probes
    "z_score", "value_lookup", "profile_column",
    # warehouse primitives
    "run_sql", "list_tables", "describe_table",
    # the one platform tool that is analysis business
    "propose_context_note",
}


def _roster() -> list:
    """The analyst roster for a stub turn.

    `analyst_tools` reads only `turn.connection_id` at BUILD time — every tool body is a
    lambda closing over `turn` and none of them is invoked here — so a stub is enough and
    the test needs no warehouse.
    """
    return analyst_tools(SimpleNamespace(connection_id="test-conn"), session_id="s")


def _platform_names() -> set:
    from aughor.agent.platform_tools import platform_tools
    return {t.name for t in platform_tools("test-conn", session_id="s")}


def test_the_analyst_roster_is_exactly_the_pinned_set():
    assert {t.name for t in _roster()} == EXPECTED


def test_the_kept_platform_tool_is_actually_in_the_built_roster():
    """The filter matched something.

    `_ANALYST_PLATFORM_TOOLS` selects by name out of `platform_tools()`. Rename the tool
    there and the comprehension yields nothing — the analyst quietly loses its write-back
    and every "the eleven are gone" assertion still passes. This is the assertion that
    goes red instead.
    """
    # Without this the loop below is skipped on an empty keep-set and the test passes
    # having asserted nothing — the exact vacuous-pass shape it exists to catch.
    assert _ANALYST_PLATFORM_TOOLS, "the keep-set is empty — nothing is being asserted"
    names = {t.name for t in _roster()}
    for kept in _ANALYST_PLATFORM_TOOLS:
        assert kept in names, (
            f"{kept!r} is in _ANALYST_PLATFORM_TOOLS but not in the built roster — "
            "platform_tools no longer declares that name, so the filter matched nothing")


def test_every_dropped_name_is_a_real_platform_tool():
    """Guards the guard below: a typo'd name is absent from the analyst roster for free."""
    dropped = _platform_names() - _ANALYST_PLATFORM_TOOLS
    assert dropped, "platform_tools declares nothing beyond the kept set — trim is vacuous"
    assert len(dropped) >= 10, f"expected the eleven chat-roster reads, found {sorted(dropped)}"


def test_the_chat_roster_reads_do_not_reach_the_analyst():
    names = {t.name for t in _roster()}
    leaked = (_platform_names() - _ANALYST_PLATFORM_TOOLS) & names
    assert not leaked, f"chat-roster platform tools reached the analyst: {sorted(leaked)}"


def test_converse_still_gets_the_whole_platform_roster():
    """The trim is analyst-only. Chat is where an open question belongs, and the reads
    earn their place there; cutting them here must not cut them there."""
    from aughor.agent.converse_tools import converse_tools
    names = {t.name for t in converse_tools("test-conn")}
    missing = _platform_names() - names
    assert not missing, f"converse lost platform tools: {sorted(missing)}"


def test_the_analyst_prompt_names_no_dropped_tool():
    """A prompt that instructs a tool the roster does not carry is a failure this path has
    had before: a rule naming a shape the model cannot produce. The prompt named none of
    the twelve when they were trimmed — this keeps it that way."""
    import inspect

    from aughor.agent.analyst import analyst_system_prompt
    src = inspect.getsource(analyst_system_prompt)
    for gone in sorted(_platform_names() - _ANALYST_PLATFORM_TOOLS):
        assert gone not in src, (
            f"the analyst prompt names {gone!r}, which is no longer on its roster — "
            "either restore the tool or stop instructing the model to call it")
