"""Track C3 — a retried send leaves once (2026-11-06, `notifications/sent_once.py`).

Measured first: the kernel never re-runs a dead job (an orphan is FAILED, "uncertain result"), the
inbox resolves a proposal once before it sends, the automation engine claims a period before it
sends (4.1a), a declared action's outbox leases each call, and the departure gate holds the same
words sent twice to one place within seven days. What was left: senders carried a ``delivery_key``
stable across their retries and only a RECEIVER could honour it — Slack's webhooks, its
chat.postMessage and Jira's create-issue ignore a field in the body — so a retry that reached either
transport with other words, or of a kind the repeat law exempts, sent again; and an unattended Slack
post was missing from the engine's claimed kinds. Now the transport honours the key itself.

The program's exit test is a duplicate-effect test under a killed worker: a real process, killed
while its send is on the wire, and the retry that follows. A model of the kill (an exception) would
run the settle a real kill never runs, so the worker here is a process and the kill is SIGKILL.
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from aughor.notifications import sent_once
from aughor.notifications.models import ActionPayload, ActionTrigger

ROOT = Path(__file__).resolve().parents[2]
TRANSPORTS = {"fire_action", "post_as_bot"}


# ── a receiver that counts what arrives ─────────────────────────────────────────────────────

class _Receiver:
    """A local HTTP endpoint. ``hold`` makes it keep each request open without answering — the
    moment a worker is killed with its message delivered and no reply heard."""

    def __init__(self, status: int = 200, hold: bool = False):
        self.bodies: list[dict] = []
        self.status, self.hold = status, hold
        self.release = threading.Event()
        rx = self

        class _H(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802 — the stdlib's name
                n = int(self.headers.get("Content-Length") or 0)
                rx.bodies.append(json.loads(self.rfile.read(n) or b"{}"))
                if rx.hold:
                    rx.release.wait(30)
                try:
                    payload = json.dumps({"ok": True, "ts": "1730000000.000100", "channel": "C1"}).encode()
                    self.send_response(rx.status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def log_message(self, *a):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/hook"

    def close(self):
        self.release.set()
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def receiver():
    made: list[_Receiver] = []

    def make(**kw) -> _Receiver:
        made.append(_Receiver(**kw))
        return made[-1]
    yield make
    for r in made:
        r.close()


@pytest.fixture(autouse=True)
def _local_targets_allowed(monkeypatch):
    # The SSRF guard refuses 127.0.0.1, which is the only place a test may send to.
    monkeypatch.setattr("aughor.util.url_guard.is_safe_webhook_url", lambda url: True)


def _trigger(url: str) -> ActionTrigger:
    return ActionTrigger(id=f"c3-{uuid.uuid4().hex[:8]}", name="c3 hook", type="webhook", url=url)


def _payload(key: str) -> ActionPayload:
    return ActionPayload(investigation_id="c3", rec_index=0, recommendation="the same message",
                         metric_name="", headline="c3", trigger_id="c3", triggered_at="2026-11-06T00:00:00Z",
                         delivery_key=key)


def _key() -> str:
    return f"c3-test:{uuid.uuid4().hex}"


# ── the transport: four outcomes ────────────────────────────────────────────────────────────

def test_a_delivered_key_is_not_sent_again_and_answers_with_the_first_send(receiver):
    from aughor.notifications.executor import fire_action
    from aughor.notifications.store import list_logs
    rx, key = receiver(), _key()
    trigger = _trigger(rx.url)
    first = fire_action(trigger, _payload(key))
    again = fire_action(trigger, _payload(key))
    assert first.status == "ok" and len(rx.bodies) == 1
    assert again.status == "ok" and again.id == first.id          # the replay: the first send's own record
    rows = list_logs(trigger_id=trigger.id)
    assert [r["status"] for r in rows] == ["ok", "skipped"]        # and the record says nothing left this time
    assert rows[1]["error"].startswith("not sent again — delivered at ")


def test_a_send_that_did_not_arrive_releases_its_key_so_the_retry_sends(receiver):
    """A refusal left nothing behind, so the retry is free to send — the guard must never turn a
    message that did not arrive into one that never will."""
    from aughor.notifications.executor import fire_action
    flaky, key = receiver(status=400), _key()
    trigger = _trigger(flaky.url)
    assert fire_action(trigger, _payload(key)).status == "failed"
    flaky.status = 200
    assert fire_action(trigger, _payload(key)).status == "ok"
    assert fire_action(trigger, _payload(key)).status == "ok"     # and once it has, it is not sent a third time
    assert len(flaky.bodies) == 2


def test_a_send_with_no_key_is_unchanged(receiver):
    from aughor.notifications.executor import fire_action
    rx = receiver()
    trigger = _trigger(rx.url)
    assert [fire_action(trigger, _payload("")).status for _ in range(2)] == ["ok", "ok"]
    assert len(rx.bodies) == 2


def test_two_processes_racing_one_key_get_one_claim(tmp_path):
    from aughor.kernel.ledger import Ledger
    a, b = Ledger(str(tmp_path / "l.db")), Ledger(str(tmp_path / "l.db"))
    assert a.kv_put_if_absent("s", "k", {"by": "a"}) is True
    assert b.kv_put_if_absent("s", "k", {"by": "b"}) is False
    assert b.kv_get("s", "k") == {"by": "a"}


_PG_URL = os.environ.get("AUGHOR_PG_TEST_URL", "postgres://postgres:aughor@localhost:5544/aughor")


def _pg_available() -> bool:
    try:
        import psycopg2
        psycopg2.connect(_PG_URL, connect_timeout=2).close()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _pg_available(), reason="needs a live shared Postgres")
def test_two_instances_on_one_shared_postgres_get_one_claim(tmp_path, monkeypatch):
    """Decision 2's deployment: two API processes on one Postgres. The claim is one statement there
    too, so of two instances racing for one key exactly one sends."""
    from aughor.db import backend as B
    from aughor.kernel.ledger import Ledger
    monkeypatch.setenv(B.DB_URL_ENV, _PG_URL)
    path = tmp_path / "system.db"             # unique per test → its own schema, both share it
    a, b = Ledger(path), Ledger(path)
    wins = [a.kv_put_if_absent(sent_once.STORE, "k", {"by": "a"}),
            b.kv_put_if_absent(sent_once.STORE, "k", {"by": "b"})]
    assert wins == [True, False] and b.kv_get(sent_once.STORE, "k") == {"by": "a"}


def test_the_uncertain_sentence_is_one_sentence():
    from aughor.automations.engine import UNCERTAIN_DELIVERY
    assert UNCERTAIN_DELIVERY == sent_once.MAY_HAVE_ARRIVED


# ── the receipt: a worker killed with its message on the wire ──────────────────────────────

_WORKER = """
import sys
from aughor.util import url_guard
url_guard.is_safe_webhook_url = lambda url: True
transport, url, key, trigger_id = sys.argv[1:5]
print("ready", flush=True)
if transport == "webhook":
    from aughor.notifications.executor import fire_action
    from aughor.notifications.models import ActionPayload, ActionTrigger
    fire_action(ActionTrigger(id=trigger_id, name="c3 hook", type="webhook", url=url),
                ActionPayload(investigation_id="c3", rec_index=0, recommendation="the same message",
                              metric_name="", headline="c3", trigger_id=trigger_id,
                              triggered_at="2026-11-06T00:00:00Z", delivery_key=key))
else:
    from aughor.slackbots import post
    post._POST_URL = url
    post.post_as_bot("test-token", "C1", "the same message", delivery_key=key)
"""


def _kill_mid_send(tmp_path, transport: str, url: str, key: str, trigger_id: str, rx: _Receiver) -> None:
    script = tmp_path / "worker.py"
    script.write_text(_WORKER)
    env = {**os.environ, "PYTHONPATH": str(ROOT)}       # the conftest's store overrides ride along
    proc = subprocess.Popen([sys.executable, str(script), transport, url, key, trigger_id],
                            cwd=str(ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 60
        while not rx.bodies and time.monotonic() < deadline and proc.poll() is None:
            time.sleep(0.05)
        assert rx.bodies, f"the worker never sent: {proc.stderr.read().decode()[-2000:] if proc.poll() is not None else 'still running'}"
    finally:
        proc.kill()                                     # SIGKILL: no handler, no finally, no settle
        proc.wait(10)
    rx.release.set()


@pytest.mark.parametrize("transport", ["webhook", "slack"])
def test_a_worker_killed_mid_send_is_not_sent_again_by_its_retry(tmp_path, receiver, transport):
    """The program's exit test (Track C3). The first worker's message reached the receiver; the
    worker died before it heard back. Its retry does not send — it says the first may have arrived."""
    from aughor.notifications.executor import fire_action
    from aughor.slackbots import post
    rx, key = receiver(hold=True), _key()
    trigger = _trigger(rx.url)
    _kill_mid_send(tmp_path, transport, rx.url, key, trigger.id, rx)
    assert len(rx.bodies) == 1
    rx.hold = False

    if transport == "webhook":
        retry = fire_action(trigger, _payload(key))
        assert retry.status == "timeout"                # what every caller reads as "may have arrived"
        why = retry.error
    else:
        post._POST_URL, before = rx.url, post._POST_URL
        try:
            ok, info = post.post_as_bot("test-token", "C1", "the same message", delivery_key=key)
        finally:
            post._POST_URL = before
        assert ok is False and info.get("uncertain") is True
        why = info["error"]
    assert "has not reported back" in why and sent_once.MAY_HAVE_ARRIVED in why
    assert len(rx.bodies) == 1, "the retry of a send that may have arrived must not send again"


# ── the engine: one key per send, kept across its retries ───────────────────────────────────

def test_each_send_in_a_run_has_its_own_key_and_its_retry_keeps_it():
    from datetime import datetime, timezone

    from aughor.automations.engine import DELIVERY_KEY_KEY, run_automation
    from aughor.automations.models import Automation, Condition, Effect, EffectOutcome
    seen: list[str] = []

    def failing(effect, automation):
        seen.append(effect.config.get(DELIVERY_KEY_KEY, ""))
        return EffectOutcome(kind=effect.kind, target=effect.target(), status="failed")

    auto = Automation(id=f"c3-keys-{uuid.uuid4().hex[:6]}", conn_id="c1", name="two sends", max_retries=1,
                      conditions=[Condition(kind="schedule", config={"cron": "0 8 * * *"})],
                      effects=[Effect(kind="notify", config={"trigger_id": "a"}),
                               Effect(kind="notify", config={"trigger_id": "b"})])
    now = datetime(2026, 11, 6, 9, 0, tzinfo=timezone.utc)
    run_automation(auto, now=now, dispatch=failing, persist=False, sleeper=lambda s: None)
    first_run = list(seen)
    assert len(first_run) == 4 and all(first_run)
    assert first_run[0] == first_run[1] and first_run[2] == first_run[3]   # a retry keeps its send's key
    assert first_run[0] != first_run[2]                                    # two sends are two deliveries
    seen.clear()
    run_automation(auto, now=now, dispatch=failing, persist=False, sleeper=lambda s: None)
    assert not set(seen) & set(first_run)                                  # another run, other deliveries


def test_a_tick_killed_after_an_unattended_slack_post_does_not_post_the_period_again(tmp_path, monkeypatch):
    """`slack_post` was missing from the claimed kinds (the set predates it): a tick killed after
    the post looked, to the next tick, like a period never run."""
    from datetime import datetime, timedelta, timezone

    from aughor.automations.engine import run_automation
    from aughor.automations.models import Automation, Condition, Effect, EffectOutcome
    from aughor.kernel.ledger import Ledger
    led = Ledger(str(tmp_path / "claims.db"))
    monkeypatch.setattr(Ledger, "default", staticmethod(lambda: led))
    posts: list[str] = []

    def post(effect, automation):
        posts.append(effect.kind)
        return EffectOutcome(kind=effect.kind, target=effect.target(), status="executed")

    def post_then_die(effect, automation):
        post(effect, automation)
        raise KeyboardInterrupt("process died after the post")

    auto = Automation(id=f"c3-slack-{uuid.uuid4().hex[:6]}", conn_id="c1", name="morning post",
                      conditions=[Condition(kind="schedule", config={"cron": "0 8 * * *"})],
                      effects=[Effect(kind="slack_post", config={"bot_id": "b1", "channel": "C1",
                                                                 "message": "good morning"})])
    now = datetime(2026, 11, 6, 9, 0, tzinfo=timezone.utc)
    with pytest.raises(KeyboardInterrupt):
        run_automation(auto, now=now, dispatch=post_then_die)
    run_automation(auto, now=now + timedelta(minutes=5), dispatch=post)
    assert posts == ["slack_post"], "the same period must never post twice"
    run_automation(auto, now=now + timedelta(days=1), dispatch=post)
    assert posts == ["slack_post", "slack_post"], "tomorrow's post still goes"


def _engine_sends(monkeypatch):
    """The engine's real notify and Slack dispatchers, with the gate passed and the side work they
    do after a send (filing the link, drawing the chart) counted instead of done."""
    from types import SimpleNamespace

    from aughor.automations import engine
    after: list[str] = []
    monkeypatch.setattr(engine, "_gate_departure", lambda *a, **k: None)
    monkeypatch.setattr(engine, "_file_departure_link", lambda *a, **k: after.append("filed") or "link-1")
    monkeypatch.setattr(engine, "_attach_chart", lambda *a, **k: after.append("chart"))
    monkeypatch.setattr("aughor.slackbots.store.get_bot", lambda bot_id: None)
    monkeypatch.setattr("aughor.slackbots.store.get_bot_decrypted",
                        lambda bot_id: SimpleNamespace(id=bot_id, name="c3 bot", bot_token="test-token", enabled=True))
    return engine, after


def test_a_replayed_notify_is_not_filed_again(monkeypatch, receiver):
    from aughor.automations.models import Automation, Condition, Effect
    from aughor.notifications.store import save_trigger
    engine, after = _engine_sends(monkeypatch)
    rx = receiver()
    trigger = save_trigger(_trigger(rx.url))
    effect = Effect(kind="notify", config={"trigger_id": trigger.id, engine.DELIVERY_KEY_KEY: _key()})
    auto = Automation(id="c3-notify", conn_id="c1", name="n", effects=[effect],
                      conditions=[Condition(kind="schedule", config={"cron": "0 8 * * *"})])
    first, again = engine._dispatch_notify(effect, auto), engine._dispatch_notify(effect, auto)
    assert first.status == again.status == "executed"
    assert len(rx.bodies) == 1 and after == ["filed"]
    assert again.message.startswith("not sent again — delivered at ")


def test_a_replayed_slack_post_draws_and_files_nothing_again(monkeypatch, receiver):
    from aughor.automations.models import Automation, Condition, Effect
    from aughor.slackbots import post
    engine, after = _engine_sends(monkeypatch)
    rx = receiver()
    monkeypatch.setattr(post, "_POST_URL", rx.url)
    effect = Effect(kind="slack_post", config={"bot_id": "b1", "channel": "C1", "message": "good morning",
                                               engine.DELIVERY_KEY_KEY: _key()})
    auto = Automation(id="c3-slack", conn_id="c1", name="n", effects=[effect],
                      conditions=[Condition(kind="schedule", config={"cron": "0 8 * * *"})])
    first, again = engine._dispatch_slack_post(effect, auto), engine._dispatch_slack_post(effect, auto)
    assert first.status == again.status == "executed"
    assert again.data["ts"] == first.data["ts"]                  # the first post's thread, for a later step
    assert len(rx.bodies) == 1 and after == ["chart", "filed"]
    assert again.message.startswith("not sent again — delivered at ")


# ── the ratchet: only a person's send may have no key ──────────────────────────────────────

class _OwnCalls(ast.NodeVisitor):
    """What a function's OWN body calls, and whether any call in it passes a non-empty
    ``delivery_key`` — a nested function is its own site."""

    def __init__(self, root: ast.AST):
        self.root, self.names, self.keyed = root, set(), False

    def visit_FunctionDef(self, node):
        if node is self.root:
            self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Call(self, node: ast.Call):
        f = node.func
        self.names.add(f.id if isinstance(f, ast.Name) else getattr(f, "attr", ""))
        for kw in node.keywords:
            if kw.arg == "delivery_key" and not (isinstance(kw.value, ast.Constant) and not kw.value.value):
                self.keyed = True
        self.generic_visit(node)


def _sites() -> dict[str, bool]:
    """``{"aughor/x.py::function": passes_a_key}`` for every function that calls a transport —
    the population the departure gate's exit ratchet discovers, never a hand-made list."""
    out: dict[str, bool] = {}
    for path in sorted((ROOT / "aughor").rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=rel)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                calls = _OwnCalls(node)
                calls.visit(node)
                if calls.names & TRANSPORTS:
                    out[f"{rel}::{node.name}"] = calls.keyed
    return out


def test_every_send_carries_a_key_or_is_a_persons_by_name():
    sites = _sites()
    assert len(sites) >= 15, sites                       # the walk saw the transports at all
    keyless = sorted(s for s, keyed in sites.items() if not keyed and s not in sent_once.KEYLESS_BY_DESIGN)
    assert not keyless, (
        "these functions send without a delivery key, so a retry of them can send twice: "
        + ", ".join(keyless) + " — pass one stable across the send's retries, or name the site in "
        "sent_once.KEYLESS_BY_DESIGN with the reason a person is the check")


def test_every_keyless_exemption_still_names_a_real_send():
    sites = _sites()
    stale = sorted(s for s in sent_once.KEYLESS_BY_DESIGN if s not in sites)
    assert not stale, f"KEYLESS_BY_DESIGN excuses call sites that no longer send: {stale}"
    keyed = sorted(s for s in sent_once.KEYLESS_BY_DESIGN if sites.get(s))
    assert not keyed, f"KEYLESS_BY_DESIGN excuses call sites that now pass a key: {keyed}"
