"""DS-1 — the palette says what can be placed, and tells the truth about this deployment.

Three properties are worth locking, and one of them is the whole reason the module exists:

1. **Ports come from the tables the save refuses against.** A palette row that advertised a
   port `validate_chain` would reject is a lie drawn in dots.
2. **A measured absence dims a row.** No Slack bot here ⇒ "Post to Slack" reads
   `needs_setup` with a sentence, instead of looking identical to a deployment with three.
3. **A FAILED probe does not.** An unreachable store is our problem; dimming a row that
   would have worked teaches a reader something false that they cannot check. Only a
   successful count of zero dims anything — this is the asymmetry the module is built on,
   and it is the one a refactor is most likely to flatten.
"""
from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from aughor.api import app
from aughor.automations.dataflow import BINDABLE_FIELDS, PUBLISHED_KEYS
from aughor.automations.palette import ENTRIES, NEEDS_SETUP, READY, entries

client = TestClient(app)

WEB = Path(__file__).resolve().parents[2] / "web"


@pytest.fixture
def no_objects(monkeypatch):
    """A deployment where none of the referenced objects exist yet — a fresh clone."""
    monkeypatch.setattr("aughor.slackbots.store.list_bots", lambda **_: [])
    monkeypatch.setattr("aughor.notifications.store.list_triggers", lambda: [])
    monkeypatch.setattr("aughor.briefing.store.list_subscriptions", lambda *_a, **_k: [])
    monkeypatch.setattr("aughor.monitors.store.list_monitors", lambda *_a, **_k: [])
    # DS-11 — and no connected accounts. Patched like every sibling rather than left to
    # the real store: these files share session-scoped stores, so a grant another file
    # created would make "a fresh clone" quietly untrue here.
    monkeypatch.setattr("aughor.integrations.store.list_connections", lambda *_a, **_k: [])


def _by_kind(rows: list[dict]) -> dict[str, dict]:
    return {r["kind"]: r for r in rows}


def test_the_guard_actually_parsed_something():
    """Vacuous-pass guard: an empty roster would let every assertion below iterate nothing."""
    assert len(ENTRIES) >= 9, f"only {len(ENTRIES)} palette entries — the roster is not loaded"


def test_ports_are_the_same_tables_the_save_refuses_against(no_objects):
    for row in entries():
        published = PUBLISHED_KEYS.get(row["kind"], ())
        expected = list(published) if published is not None else None
        assert row["publishes"] == expected, (
            f"{row['kind']} advertises {row['publishes']} but publishes {expected}")
        assert row["bindable"] == list(BINDABLE_FIELDS.get(row["kind"], ()))


#: The declared-action kind, found the way the engine finds it — the one kind whose
#: published keys are OPEN. Derived rather than spelled so this file names the wire
#: literal nowhere: a test that hardcodes it stops testing the property the moment the
#: kind is renamed, and starts testing a string.
OPEN_KIND = next(k for k, v in PUBLISHED_KEYS.items() if v is None)


def test_the_open_set_stays_open(no_objects):
    """The declared-action kind's keys are its action's own outcome shape. Serving `[]`
    instead of `null` would tell the canvas to draw no port at all — not the same claim."""
    assert _by_kind(entries())[OPEN_KIND]["publishes"] is None


def test_adopted_kinds_are_not_offered():
    """`monitor` and `agent_alert` are written by the engine when an existing object
    migrates onto it — the model's docstring says they are not authored by hand. Offering
    them invites a reader to hand-write a duplicate of something they already have."""
    offered = {e.kind for e in ENTRIES}
    assert "monitor" not in offered and "agent_alert" not in offered


def test_a_measured_absence_dims_the_row_and_says_why(no_objects):
    rows = _by_kind(entries())
    for kind in ("slack_post", "notify", "brief", "metric", "integration_call"):
        assert rows[kind]["availability"] == NEEDS_SETUP, f"{kind} should need setup here"
        assert rows[kind]["reason"], f"{kind} dimmed without telling the reader why"


def test_a_kind_whose_required_key_is_a_typed_value_is_always_ready(no_objects):
    """Nothing can be missing for a cron string or a question, so nothing dims them."""
    rows = _by_kind(entries())
    for kind in ("schedule", "source_change", "entity_appears", "investigate"):
        assert rows[kind]["availability"] == READY
        assert rows[kind]["reason"] == ""


def test_the_declared_action_is_ready_without_asking_a_flag(monkeypatch, no_objects):
    """Its objects live in a connection's ontology overrides, and reading them means
    building a graph a palette render must not pay for. The flag route is worse than
    useless — that flag was hardwired and deleted, so `flag_enabled` answers False for an
    unregistered name and every deployment would be told its declared actions are off.
    This test fails the moment someone reaches for it."""
    monkeypatch.setattr("aughor.kernel.flags.flag_enabled",
                        lambda n: (_ for _ in ()).throw(
                            AssertionError(f"the palette asked about the flag {n!r}")))
    assert _by_kind(entries())[OPEN_KIND]["availability"] == READY


def test_a_failed_probe_leaves_the_row_READY(monkeypatch):
    """The asymmetry the module is built on. An unreachable store must not read as an
    absent object: a dimmed row that would have worked is a lie the reader cannot check,
    while a lit one costs at most the save-time error they already get today."""
    def boom(*_a, **_k):
        raise RuntimeError("store unreachable")

    monkeypatch.setattr("aughor.slackbots.store.list_bots", boom)
    monkeypatch.setattr("aughor.notifications.store.list_triggers", boom)
    monkeypatch.setattr("aughor.briefing.store.list_subscriptions", boom)
    monkeypatch.setattr("aughor.monitors.store.list_monitors", boom)

    rows = _by_kind(entries())
    for kind in ("slack_post", "notify", "brief", "metric"):
        assert rows[kind]["availability"] == READY, (
            f"{kind} dimmed because a probe FAILED — that is not a measured absence")


def test_a_disabled_bot_does_not_satisfy_the_prerequisite(monkeypatch, no_objects):
    """A disabled bot cannot post, so it cannot be the reason the row is lit."""
    monkeypatch.setattr("aughor.slackbots.store.list_bots",
                        lambda **_: [SimpleNamespace(id="b1", enabled=False)])
    assert _by_kind(entries())["slack_post"]["availability"] == NEEDS_SETUP

    monkeypatch.setattr("aughor.slackbots.store.list_bots",
                        lambda **_: [SimpleNamespace(id="b1", enabled=True)])
    assert _by_kind(entries())["slack_post"]["availability"] == READY


def test_endpoint_serves_the_roster(no_objects):
    res = client.get("/automations/palette")
    assert res.status_code == 200
    rows = res.json()["entries"]
    assert {r["kind"] for r in rows} == {e.kind for e in ENTRIES}
    assert {r["group"] for r in rows} == {"trigger", "action"}
    for row in rows:
        assert row["label"] and row["description"] and row["icon"]


# ── The client mirror ─────────────────────────────────────────────────────────
#
# The palette panel reads the served table, but the kind `<select>` in `AutomationRows`
# renders synchronously from its own copy. Two spellings of one vocabulary is exactly the
# drift the required-keys guard exists to prevent, so the same treatment applies here.


def _client_kind_tables() -> dict[str, str]:
    """`{kind: label}` parsed out of CONDITION_KINDS / EFFECT_KINDS."""
    src = (WEB / "components" / "automations" / "AutomationRows.tsx").read_text()
    return dict(re.findall(r'\{\s*value:\s*"(\w+)",\s*\n?\s*label:\s*"([^"]+)"', src))


def test_the_label_guard_actually_parsed_something():
    parsed = _client_kind_tables()
    assert len(parsed) >= 9, f"parsed only {len(parsed)} kinds out of AutomationRows.tsx: {parsed}"


def test_every_offered_kind_spells_its_label_the_same_on_both_sides():
    client_labels = _client_kind_tables()
    for entry in ENTRIES:
        assert entry.kind in client_labels, (
            f"the server offers '{entry.kind}' and the client's picker does not")
        assert client_labels[entry.kind] == entry.label, (
            f"'{entry.kind}': the client calls it {client_labels[entry.kind]!r}, "
            f"the palette calls it {entry.label!r}")


def test_every_icon_is_one_the_client_can_actually_draw():
    """An icon name the client's set does not carry renders as nothing, and a palette row
    with no icon reads as a broken row rather than a missing glyph."""
    icons = (WEB / "components" / "ui" / "icon.tsx").read_text()
    known = set(re.findall(r"^  ([a-z][a-zA-Z0-9]*):", icons, re.M))
    assert len(known) > 40, "icon names did not parse out of icon.tsx — the guard reads nothing"
    unknown = sorted({e.icon for e in ENTRIES} - known)
    assert not unknown, f"palette icons the client cannot draw: {unknown}"


# ── DS-11 · the grant prerequisite ────────────────────────────────────────────

def test_only_a_spendable_grant_lights_the_integration_row(monkeypatch, no_objects):
    """A revoked grant is dead and a `needs_reconnect` one is a refusal the provider has
    already made. Neither can be spent, so neither is the prerequisite being met — the
    same rule the Slack probe applies to a disabled bot."""
    from aughor.integrations.models import Connection

    def _grants(*_a, **_k):
        return [Connection(id="a", provider="google", status="revoked"),
                Connection(id="b", provider="slack", status="needs_reconnect")]

    monkeypatch.setattr("aughor.integrations.store.list_connections", _grants)
    row = _by_kind(entries())["integration_call"]
    assert row["availability"] == NEEDS_SETUP
    assert "Integrations" in row["reason"], "the sentence names the door that fixes it"

    monkeypatch.setattr("aughor.integrations.store.list_connections",
                        lambda *_a, **_k: [Connection(id="c", provider="google",
                                                      status="active")])
    assert _by_kind(entries())["integration_call"]["availability"] == READY
