"""A departure learns whether its send arrived (2026-11-06, the follow-on to Track C3).

Found by running it: an automation's notify, refused by its receiver (a 500), was retried by the
engine — and the retry was held at the gate as *"the same message already departed … never the
same finding twice"*. The receiver had one request, the refused one; the person never got the
message; the record said it departed. The gate writes `departed` BEFORE the send, and three of its
counts read that word as "a person heard it": law 7 (the repeat), the attention budget and a
mission's charge. So a refused send held its own retry, and the same words to that place for seven
days after. Now the send writes what became of it onto the departure, and those counts skip the
sends that did not arrive (`departure_store.HEARD`).
"""
from __future__ import annotations

import ast
import json
import threading
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from aughor.govern import departure_store as store

ROOT = Path(__file__).resolve().parents[2]


class _Receiver:
    """Answers each POST with the next code in ``codes`` (the last one repeats)."""

    def __init__(self, *codes: int, body: dict | None = None):
        self.codes, self.hits = list(codes), 0
        payload = json.dumps(body or {}).encode()
        rx = self

        class _H(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802 — the stdlib's name
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                code = rx.codes[min(rx.hits, len(rx.codes) - 1)]
                rx.hits += 1
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *a):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/hook"


@pytest.fixture
def receiver():
    made: list[_Receiver] = []

    def make(*codes, **kw):
        made.append(_Receiver(*codes, **kw))
        return made[-1]
    yield make
    for r in made:
        r.server.shutdown()
        r.server.server_close()


@pytest.fixture(autouse=True)
def _local(monkeypatch):
    monkeypatch.setattr("aughor.util.url_guard.is_safe_webhook_url", lambda url: True)
    # One HTTP attempt per send, so a refusal is the send's answer rather than the transport's
    # inner retry's — the engine's retry is the one under test.
    monkeypatch.setattr("aughor.notifications.executor._MAX_ATTEMPTS", 1)


def test_a_refused_notify_is_retried_and_arrives(receiver):
    """The probe, kept: the receiver refuses the first send and takes the second."""
    from aughor.automations.engine import run_automation
    from aughor.automations.models import Automation, Condition, Effect
    from aughor.notifications.models import ActionTrigger
    from aughor.notifications.store import save_trigger
    rx = receiver(500, 200)
    trigger = save_trigger(ActionTrigger(id=f"dd-{uuid.uuid4().hex[:6]}", name="dd", type="webhook", url=rx.url))
    auto = Automation(id=f"dd-auto-{uuid.uuid4().hex[:6]}", conn_id="c1", name="weekly signups", max_retries=1,
                      conditions=[Condition(kind="schedule", config={"cron": "0 8 * * *"})],
                      effects=[Effect(kind="notify", config={"trigger_id": trigger.id,
                                                             "message": "weekly signups report is ready"})])
    run = run_automation(auto, now=datetime(2026, 11, 6, 9, 0, tzinfo=timezone.utc), sleeper=lambda s: None)
    assert rx.hits == 2, "the retry of a refused send must reach the receiver"
    assert [o.status for o in run.effects] == ["executed"], [o.message for o in run.effects]
    rows = store.list_departures(automation_id=auto.id)
    assert sorted((r["state"], r["delivery"]) for r in rows) == [("departed", "delivered"),
                                                                ("departed", "not_delivered")]


def _departed(**over) -> str:
    fields = dict(id=uuid.uuid4().hex[:12], kind="notify", org_id="default", conn_id="c1", state="departed",
                  automation_id=f"dd-src-{uuid.uuid4().hex[:6]}", target="hook-1", origin="unattended",
                  fingerprint="weekly signups report is ready", numerals="[]")
    fields.update(over)
    return store.record_departure(**fields)


def test_a_send_that_did_not_arrive_is_not_heard_by_any_count():
    since = "2000-01-01T00:00:00Z"
    refused = _departed(target=f"t-{uuid.uuid4().hex[:6]}", checks=json.dumps({"mission": "m-dd"}))
    row = store.get_departure(refused)
    store.record_delivery(refused, "not_delivered")
    assert store.last_departed(source=row["automation_id"], target=row["target"],
                               fingerprint=row["fingerprint"], since=since) is None
    assert store.count_departed_to(row["target"], since=since) == 0
    assert store.count_departed_bearing("m-dd", since=since) == 0
    # and one that may have arrived still counts — never sent again blind
    store.record_delivery(refused, "uncertain")
    assert store.last_departed(source=row["automation_id"], target=row["target"],
                               fingerprint=row["fingerprint"], since=since) is not None
    assert store.count_departed_to(row["target"], since=since) == 1
    assert store.count_departed_bearing("m-dd", since=since) == 1


def test_a_held_row_takes_no_delivery():
    held = _departed(state="held")
    store.record_delivery(held, "delivered")
    assert store.get_departure(held)["delivery"] == ""


@pytest.mark.parametrize("answer, ok_expected, outcome", [
    ({"ok": True, "ts": "1.2", "channel": "C1"}, True, "delivered"),
    ({"ok": False, "error": "channel_not_found"}, False, "not_delivered"),
])
def test_a_slack_post_writes_its_outcome_onto_its_departure(receiver, monkeypatch, answer, ok_expected, outcome):
    from aughor.slackbots import post
    rx = receiver(200, body=answer)
    monkeypatch.setattr(post, "_POST_URL", rx.url)
    dep = _departed(kind="slack_post")
    ok, _ = post.post_as_bot("test-token", "C1", "hello", departure_id=dep)
    assert ok is ok_expected and store.get_departure(dep)["delivery"] == outcome


def test_an_unreachable_slack_post_is_uncertain_on_its_departure(monkeypatch):
    from aughor.slackbots import post
    monkeypatch.setattr(post, "_POST_URL", "http://127.0.0.1:9/never")      # discard port: refused
    dep = _departed(kind="slack_post")
    ok, info = post.post_as_bot("test-token", "C1", "hello", departure_id=dep)
    assert ok is False and info.get("uncertain") and store.get_departure(dep)["delivery"] == "uncertain"


# ── every gated send tells its transport which departure it is ─────────────────────────────

def _own_nodes(fn: ast.AST):
    """The nodes of a function's OWN body — a nested function is its own site."""
    stack = list(ast.iter_child_nodes(fn))
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        yield node
        stack.extend(ast.iter_child_nodes(node))


def _gated_sends() -> dict[str, bool]:
    """``{"aughor/x.py::function": names_its_departure}`` for every function that asks the gate and
    calls a transport — `post_as_bot(..., departure_id=…)`, or a payload whose context carries the
    gate's receipt (where `fire_action` reads the departure from)."""
    out: dict[str, bool] = {}
    for path in sorted((ROOT / "aughor").rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        for fn in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=rel)):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            own = list(_own_nodes(fn))
            calls = [n for n in own if isinstance(n, ast.Call)]
            names = {getattr(c.func, "id", "") or getattr(c.func, "attr", "") for c in calls}
            if not names & {"gate_departure", "_gate_departure"} or not names & {"fire_action", "post_as_bot"}:
                continue
            posts = [c for c in calls if (getattr(c.func, "id", "") or getattr(c.func, "attr", "")) == "post_as_bot"]
            posts_named = all(any(k.arg == "departure_id" for k in c.keywords) for c in posts)
            fires = "fire_action" in names
            receipt = "_receipt_context" in names or any(
                isinstance(n, ast.Dict) and any(isinstance(k, ast.Constant) and k.value == "receipt" for k in n.keys)
                for n in own)
            out[f"{rel}::{fn.name}"] = posts_named and (receipt or not fires)
    return out


def test_every_gated_send_names_its_departure_to_its_transport():
    sites = _gated_sends()
    assert len(sites) >= 12, sites
    unnamed = sorted(s for s, ok in sites.items() if not ok)
    assert not unnamed, ("these sends ask the gate but do not tell the transport which departure they "
                         "are, so a send that does not arrive is still counted as heard: " + ", ".join(unnamed))
