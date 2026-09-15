"""SP-7 (§3.11, the second movement) — the guide names what is on screen.

The census found the guide sending a person to an "Agents page → New agent" where the rail
says “Agent Ops” and the button “+ Create agent”, and to a "Connections page (the plug icon
in the sidebar)" the rail does not have. Walkthrough text is curated, so it rots silently
when the interface moves. The convention that makes it checkable: a UI label is written in
curly quotes, and this test finds every quoted label in every RENDERED walkthrough and
requires it to exist in the web app's own source. The population comes from the guide's
text, not from a list kept beside the expectation — a list like that cannot fail.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

import aughor.agent.spotlight_guide as guide

WEB = Path(__file__).resolve().parents[2] / "web"
TOPICS = ["create_agent", "create_automation", "connect_data", "appearance"]
_QUOTED = re.compile(r"“([^”]+)”")


def _rendered(topic: str) -> str:
    out = guide.platform_guide({"topic": topic})
    return "\n".join([*out["steps"], out["summary"], out["offer"]["sentence"]])


@pytest.fixture(scope="module")
def ui_source() -> str:
    parts = [path.read_text(encoding="utf-8", errors="replace")
             for root in ("app", "components")
             for path in (WEB / root).rglob("*.tsx") if ".test." not in path.name]
    source = "\n".join(parts)
    assert len(source) > 100_000, "the web source was not found — every label would 'pass'"
    return source


@pytest.mark.parametrize("topic", TOPICS)
def test_every_quoted_label_exists_in_the_web_app(topic, ui_source):
    labels = _QUOTED.findall(_rendered(topic))
    assert labels, f"{topic}: a walkthrough that quotes no label cannot be checked"
    missing = sorted({label for label in labels if label not in ui_source})
    assert not missing, f"{topic} names labels the web app does not have: {missing}"


@pytest.mark.parametrize("stale", ["Agents page", "New agent", "plug icon", "Connections page"])
def test_the_names_the_census_found_wrong_are_gone(stale):
    assert stale not in "\n".join(_rendered(topic) for topic in TOPICS)


def test_the_agent_walkthrough_starts_where_the_create_flow_starts():
    """The flow opens on “Describe” — the draft-from-words door the old walkthrough skipped."""
    first = guide.platform_guide({"topic": "create_agent"})["steps"][0]
    assert "“+ Create agent”" in first and "“Describe”" in first
