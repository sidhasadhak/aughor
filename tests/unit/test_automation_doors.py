"""DS-17 — Deploy is a menu of doors, and the menu tells the truth about THIS deployment.

Four properties are worth locking, and the last two are the ones a refactor flattens:

1. **A door has a POSITION, not just an availability.** `open` and `closed` are both
   "everything is fine"; only one of them means traffic is coming through. The palette's
   three states cannot say that, which is why this module has four.
2. **Both halves are needed.** Every sentence here is a property of the CHAIN (does it
   have a schedule trigger, is it exposed) crossed with a property of the DEPLOYMENT (is a
   clock running, is there a bot). A door that read only one half would be confidently
   wrong on every deployment but the author's.
3. **The alt-door rule is content, not structure.** A Slack door that says "connect via
   OAuth" is *shaped* correctly and points a self-hosted install at a door it cannot open
   — Slack rejects `http://localhost` callbacks. So the assertion is on the WORDS.
4. **A failed probe leaves a door where it was.** The palette's asymmetry: an unreachable
   store is our problem, and dimming a door because we could not look teaches a reader
   something false that they cannot check. Only a measured absence closes anything.
"""
from __future__ import annotations

import pytest

from aughor.automations.doors import CLOSED, NEEDS_SETUP, OPEN, UNAVAILABLE, doors, summary
from aughor.automations.models import Automation, Condition, Effect

CONN = "ds17"


@pytest.fixture(autouse=True)
def _clean_automations():
    """The automations store is SESSION-scoped — a chain saved here is still there when
    the next file asks what is exposed. (Third time this trap has been paid for.)"""
    from aughor.automations.store import delete_automation, list_automations
    for a in list_automations(conn_id=CONN):
        delete_automation(a.id)
    yield
    for a in list_automations(conn_id=CONN):
        delete_automation(a.id)


@pytest.fixture(autouse=True)
def _a_running_clock(monkeypatch):
    """Most tests are about the CHAIN half, so pin the deployment half to a live heartbeat.
    The tests that are about the clock override this explicitly."""
    monkeypatch.setattr("aughor.automations.scheduler.clock",
                        lambda: ("heartbeat", "in-process heartbeat, every 60s"))


@pytest.fixture(autouse=True)
def _one_slack_bot(monkeypatch):
    """Likewise for Slack: a deployment with exactly one usable bot, unless a test says
    otherwise. Patched rather than left to the real store because these files share
    session-scoped stores, and a bot another file created would make "no bots" untrue."""
    monkeypatch.setattr("aughor.slackbots.store.list_bots",
                        lambda **_: [object()])


def _chain(*, triggers=("schedule",), steps=("investigate",), enabled=True,
           exposed=False, name="DS-17 receipt", channel="#ops") -> Automation:
    cfg = {"schedule": {"cron": "0 9 * * *"}, "webhook": {},
           "metric": {"monitor_id": "m1"}}
    step_cfg = {"investigate": {"question": "how are sales?"},
                "slack_post": {"bot_id": "b1", "channel": channel}}
    return Automation(
        name=name, conn_id=CONN, enabled=enabled, exposed_as_tool=exposed,
        conditions=[Condition(kind=k, config=dict(cfg[k])) for k in triggers],
        effects=[Effect(kind=k, config=dict(step_cfg[k])) for k in steps])


def _by_kind(a: Automation) -> dict[str, dict]:
    return {d["kind"]: d for d in doors(a)}


# ── the guard that keeps every assertion below from passing vacuously ────────────

def test_the_menu_actually_has_doors():
    """A `doors()` that returned [] would let every `_by_kind(...)["x"]` KeyError — but a
    filter bug that returned three of four would let the *others* pass silently."""
    rows = doors(_chain())
    assert [d["kind"] for d in rows] == ["schedule", "webhook", "slack", "mcp_tool"]
    assert all(d["reason"] for d in rows), "a door with no sentence explains nothing"


def test_every_door_reports_one_of_the_four_states():
    for d in doors(_chain()):
        assert d["state"] in (OPEN, CLOSED, NEEDS_SETUP, UNAVAILABLE)


# ── 1 · open and closed are different answers ────────────────────────────────────

def test_a_scheduled_enabled_chain_is_OPEN_and_names_its_cron():
    d = _by_kind(_chain())["schedule"]
    assert d["state"] == OPEN
    assert "0 9 * * *" in d["detail"]


def test_switching_the_chain_off_CLOSES_the_schedule_door_rather_than_breaking_it():
    """The distinction the palette cannot draw: nothing is missing, nothing needs setting
    up, and one gesture opens it. `needs_setup` here would send a reader to look for a
    prerequisite that is already there."""
    d = _by_kind(_chain(enabled=False))["schedule"]
    assert d["state"] == CLOSED
    assert "switched off" in d["reason"].lower()


def test_a_chain_with_no_schedule_trigger_needs_setup_and_names_the_canvas():
    d = _by_kind(_chain(triggers=("metric",)))["schedule"]
    assert d["state"] == NEEDS_SETUP
    assert "canvas" in d["reason"].lower()


# ── 2 · the deployment half — the clock, measured rather than assumed ─────────────

def test_a_deployment_with_no_clock_reports_the_schedule_door_UNAVAILABLE(monkeypatch):
    """`start()` swallows its own failure as non-fatal, so this is a state a deployment can
    genuinely be in — and nothing else in the product reports it. A door that read `open`
    here is the palette's original sin: offering something that quietly does nothing."""
    monkeypatch.setattr("aughor.automations.scheduler.clock",
                        lambda: ("stopped", "no clock is running in this process"))
    d = _by_kind(_chain())["schedule"]
    assert d["state"] == UNAVAILABLE
    assert "/cron/tick" in d["reason"], "the reason must name the door that still works"


def test_serverless_keeps_the_schedule_door_OPEN(monkeypatch):
    """The alt-door rule applied to the clock. On Vercel the in-process heartbeat is OFF by
    design and an external cron drives the tick; a door that looked for a THREAD would tell
    that deployment its schedules are dead while they fire every minute."""
    monkeypatch.setattr("aughor.automations.scheduler.clock",
                        lambda: ("external", "serverless — an external cron calls GET /cron/tick"))
    d = _by_kind(_chain())["schedule"]
    assert d["state"] == OPEN
    assert "cron" in d["reason"].lower()


# ── 3 · the alt-door rule is about the WORDS ─────────────────────────────────────

def test_a_deployment_with_no_slack_bot_is_pointed_at_the_manifest_never_at_OAuth(monkeypatch):
    """RC-5, bought live with the user: Slack REJECTS `http://localhost` callbacks (Google
    and Microsoft both accept them — Slack is the one that does not), so a fresh clone sent
    to the OAuth door is sent to a door it cannot open. Socket Mode needs no public URL,
    and it is what `slack_post` actually uses."""
    monkeypatch.setattr("aughor.slackbots.store.list_bots", lambda **_: [])
    d = _by_kind(_chain(steps=("investigate", "slack_post")))["slack"]
    assert d["state"] == NEEDS_SETUP
    assert "oauth" not in d["reason"].lower()
    assert "socket mode" in d["reason"].lower()


def test_a_disabled_bot_is_not_a_door(monkeypatch):
    """Counting ROWS would have said otherwise — the distinction the palette draws for a
    revoked grant. The door asks for bots that could actually post."""
    seen: dict = {}

    def _bots(**kw):
        seen.update(kw)
        return []                       # i.e. none once the disabled ones are excluded

    monkeypatch.setattr("aughor.slackbots.store.list_bots", _bots)
    _by_kind(_chain(steps=("slack_post",)))["slack"]
    assert seen.get("include_disabled") is False


def test_a_bot_exists_but_the_chain_posts_nowhere():
    d = _by_kind(_chain(steps=("investigate",)))["slack"]
    assert d["state"] == NEEDS_SETUP
    assert "post to slack" in d["reason"].lower()


def test_a_chain_that_posts_is_OPEN_on_its_channel():
    d = _by_kind(_chain(steps=("slack_post",), channel="#revenue"))["slack"]
    assert d["state"] == OPEN
    assert "#revenue" in d["detail"]


# ── 4 · a failed probe leaves a door where it was ────────────────────────────────

def test_an_unreachable_bot_store_does_not_close_the_slack_door(monkeypatch):
    """The asymmetry this module is built on, and the one a refactor is most likely to
    flatten into `except: return 0`. A measured zero closes the door; a failure to look
    must not, because the reader cannot check our outage."""
    def _boom(**_):
        raise RuntimeError("bot store unreachable")

    monkeypatch.setattr("aughor.slackbots.store.list_bots", _boom)
    d = _by_kind(_chain(steps=("slack_post",)))["slack"]
    assert d["state"] == OPEN
    assert "socket mode" not in d["reason"].lower(), "a failed probe must not claim an absence"


def test_an_unreadable_clock_does_not_declare_the_schedule_door_dead(monkeypatch):
    def _boom():
        raise RuntimeError("scheduler module unreachable")

    monkeypatch.setattr("aughor.automations.scheduler.clock", _boom)
    assert _by_kind(_chain())["schedule"]["state"] == OPEN


# ── the MCP door · DS-14's law, stated where it bites ────────────────────────────

def test_exposed_and_enabled_is_OPEN_and_names_the_tool():
    d = _by_kind(_chain(name="Daily sales report", exposed=True))["mcp_tool"]
    assert d["state"] == OPEN
    assert d["detail"] == "daily_sales_report"
    assert "reconnect" in d["reason"].lower(), (
        "the tool list is read once at MCP server start — a door that omitted this would "
        "have an operator debugging a client that is working exactly as designed")


def test_exposed_but_switched_off_is_CLOSED_because_both_flags_must_hold():
    """A chain someone deliberately switched off must not stay callable from outside —
    that would make the off switch a lie for exactly the caller nobody is watching."""
    d = _by_kind(_chain(exposed=True, enabled=False))["mcp_tool"]
    assert d["state"] == CLOSED
    assert "switched off" in d["reason"].lower()


def test_a_name_that_would_shadow_a_static_tool_is_refused_BEFORE_the_door_opens():
    """DS-14 SKIPS a colliding name at registration. A door that read `open` and then
    registered nothing is the difference between a menu and a report."""
    d = _by_kind(_chain(name="Ask", exposed=False))["mcp_tool"]
    assert d["state"] == NEEDS_SETUP
    assert "rename" in d["reason"].lower()


def test_two_chains_answering_to_one_name_is_refused_with_the_rival_named():
    from aughor.automations.store import upsert_automation
    upsert_automation(_chain(name="Revenue check", exposed=True))
    rival = _chain(name="revenue  check", exposed=False)
    d = _by_kind(rival)["mcp_tool"]
    assert d["state"] == NEEDS_SETUP
    assert "Revenue check" in d["reason"]


# ── the webhook door · the one plane this wave built ─────────────────────────────

def test_a_chain_with_no_webhook_trigger_needs_one_first():
    d = _by_kind(_chain(triggers=("schedule",)))["webhook"]
    assert d["state"] == NEEDS_SETUP
    assert "canvas" in d["reason"].lower()


def test_a_webhook_trigger_with_no_url_issued_is_CLOSED():
    d = _by_kind(_chain(triggers=("webhook",)))["webhook"]
    assert d["state"] == CLOSED
    assert "once" in d["reason"].lower(), "the reader must learn the token is shown once"


def test_an_issued_url_OPENS_the_door_and_the_menu_never_carries_the_token():
    from aughor.automations.store import upsert_automation
    from aughor.automations.webhooks import issue_webhook_token

    a = upsert_automation(_chain(triggers=("webhook",)))
    token = issue_webhook_token(a.id)

    d = _by_kind(a)["webhook"]
    assert d["state"] == OPEN
    assert token not in repr(doors(a)), (
        "the whole menu is rendered in a browser — a token in it is a credential in a "
        "response whose job is to be read")


def test_a_switched_off_chain_says_the_url_is_accepted_and_does_nothing():
    """Both facts, in order. `open` would promise a caller something the engine declines;
    saying nothing about the URL would suggest revoking it is unnecessary."""
    from aughor.automations.store import upsert_automation
    from aughor.automations.webhooks import issue_webhook_token

    a = upsert_automation(_chain(triggers=("webhook",), enabled=False))
    issue_webhook_token(a.id)
    d = _by_kind(a)["webhook"]
    assert d["state"] == CLOSED
    assert "does nothing" in d["reason"].lower()


# ── the one-line summary ─────────────────────────────────────────────────────────

def test_the_summary_counts_only_what_is_OPEN():
    """`needs_setup` and `closed` are both "not live"; a header that totalled them would
    tell a reader their chain was half-deployed when nothing was reachable at all."""
    assert summary([{"state": NEEDS_SETUP}, {"state": CLOSED}]) == "Not live"
    assert summary([{"state": OPEN}, {"state": CLOSED}]) == "Live on 1 door"
    assert summary([{"state": OPEN}, {"state": OPEN}]) == "Live on 2 doors"
