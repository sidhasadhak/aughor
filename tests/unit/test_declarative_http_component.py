"""DS-13 — the declarative custom component: extension without ``exec``.

Langflow's answer to "I need a component you did not ship" is a Python editor. Ours is a
described call: method, url, headers, an encrypted auth header and a body TEMPLATE, filled
and never evaluated. There is no code in the record, so there is none to run.

It deliberately rides the plane that already exists. A declared action already carries
typed params, submission criteria, a risk tier and the graduated approval gate, so a
fourth side-effect kind inherits all four the day it is authored — where a parallel
"custom component" object with its own store and its own gate would have been the second
policy authority ROADMAP §3.4 refuses in one line.

What is pinned here is the part a plausible implementation gets wrong:

* **The SSRF guard runs on the FILLED url.** Guarding the template approves
  ``https://api.vendor.com/{path}`` and then sends the request wherever ``path`` says.
* **URL parameters are percent-encoded**, so a value carrying ``/`` cannot reshape the
  path it lands in.
* **The credential never comes back.** It is decrypted at dispatch, set on one header, and
  absent from everything this returns.
* **An unchanged secret survives an edit.** A form that shows a mask sends the mask back;
  storing it would replace the key with bullets and break the component at 03:00.
* **The call goes through ``govern.outbound``** — and so does the older ``webhook`` kind,
  which was the one outbound sender in the tree that never joined that seam.
"""
from __future__ import annotations

import pytest

from aughor.actions import executor as ex
from aughor.ontology.models import (
    ActionParameter,
    KineticAction,
    SideEffect,
    encrypt_action_secrets,
    mask_action_secrets,
)
from aughor.secretvault import decrypt_secret, encrypt_secret, is_encrypted


@pytest.fixture(autouse=True)
def _no_dns(monkeypatch):
    """The guard's on-prem escape hatch, so these tests never touch DNS.

    Without it `is_safe_webhook_url` resolves the host — a suite that needs the network to
    decide whether a guard fired is a suite that fails on a train. The one test that
    exercises the guard for real turns this OFF and uses a name that resolves locally.
    """
    monkeypatch.setenv("AUGHOR_ALLOW_PRIVATE_WEBHOOKS", "1")


@pytest.fixture
def sent(monkeypatch):
    """Capture the request instead of making it."""
    calls: list[dict] = []

    class _Resp:
        status_code = 202
        is_success = True
        text = '{"dedup_key": "abc123"}'

        def json(self):
            import json
            return json.loads(self.text)

    def _request(method, url, headers=None, json=None, timeout=None):
        calls.append({"method": method, "url": url, "headers": dict(headers or {}),
                      "json": json})
        return _Resp()

    import httpx
    monkeypatch.setattr(httpx, "request", _request)
    return calls


def _pagerduty(secret="pd-routing-key-xyz", **cfg) -> KineticAction:
    config = {
        "url": "https://events.pagerduty.com/v2/enqueue",
        "method": "POST",
        "headers": {"Content-Type": "application/json"},
        "auth_header": "Authorization",
        "auth_secret": encrypt_secret(secret),
        "body": {"routing_key": "svc", "event_action": "trigger",
                 "payload": {"summary": "{summary}", "severity": "{severity}"}},
        **cfg,
    }
    return KineticAction(
        id="page_oncall", display_name="Page on-call", kind="side_effect", risk="high",
        params=[ActionParameter(name="summary"), ActionParameter(name="severity")],
        side_effects=[SideEffect(kind="http", config=config)])


# ── the described call ────────────────────────────────────────────────────────

def test_a_declared_component_calls_the_vendors_own_api(sent):
    """The whole point. `webhook` posts AUGHOR's envelope; PagerDuty wants PagerDuty's."""
    out = ex.default_dispatch(_pagerduty(), {"summary": "disk full", "severity": "critical"})
    call = sent[0]
    assert call["method"] == "POST"
    assert call["url"] == "https://events.pagerduty.com/v2/enqueue"
    # The body is the VENDOR's shape, with declared params filled in place — nested, and
    # with the non-templated literals left exactly as authored.
    assert call["json"] == {"routing_key": "svc", "event_action": "trigger",
                            "payload": {"summary": "disk full", "severity": "critical"}}
    assert out["side_effects"][0]["ok"] is True
    assert out["side_effects"][0]["response"] == {"dedup_key": "abc123"}


def test_the_credential_is_sent_as_a_header_and_never_returned(sent):
    out = ex.default_dispatch(_pagerduty(), {"summary": "s", "severity": "info"})
    assert sent[0]["headers"]["Authorization"] == "pd-routing-key-xyz"
    assert sent[0]["headers"]["Content-Type"] == "application/json"
    assert "pd-routing-key-xyz" not in str(out), "the credential rode back out in the result"


def test_a_declared_auth_header_with_no_secret_is_refused(sent):
    """Rather than sending an unauthenticated request that the vendor rejects with a 401
    three layers away from the thing that is actually wrong."""
    action = _pagerduty()
    action.side_effects[0].config["auth_secret"] = ""
    with pytest.raises(ex.KineticDispatchError, match="re-enter the credential"):
        ex.default_dispatch(action, {"summary": "s", "severity": "info"})
    assert sent == []


def test_an_undeclared_placeholder_is_an_authoring_error(sent):
    """Total substitution, the rule `_fill_question` already states: only DECLARED params
    can appear, and an unknown one fails loudly rather than shipping a literal brace."""
    action = _pagerduty()
    action.side_effects[0].config["body"] = {"summary": "{nope}"}
    with pytest.raises(ex.KineticDispatchError, match="does not declare"):
        ex.default_dispatch(action, {"summary": "s", "severity": "info"})
    assert sent == []


def test_a_url_parameter_cannot_reshape_the_path(sent):
    """Percent-encoded, so a value carrying a slash lands as a value and not as a path."""
    action = _pagerduty()
    action.side_effects[0].config["url"] = "https://api.vendor.com/incidents/{summary}"
    ex.default_dispatch(action, {"summary": "a/../../admin", "severity": "x"})
    assert sent[0]["url"] == "https://api.vendor.com/incidents/a%2F..%2F..%2Fadmin"


def test_the_ssrf_guard_is_handed_the_FILLED_url_not_the_template(monkeypatch, sent):
    """The subtle one, and the first version of this test could not see it.

    Asserting only that a localhost parameter is REFUSED proves nothing: an unfilled
    `http://{summary}/x` has `{summary}` as its hostname, which fails to resolve, so the
    guard blocks it either way — a guard checking the template and a guard checking the
    filled url are indistinguishable from the outcome. The discriminating question is what
    the guard was actually HANDED, so that is what this asserts.
    """
    seen: list[str] = []
    import aughor.util.url_guard as guard
    monkeypatch.setattr(guard, "is_safe_webhook_url",
                        lambda u: (seen.append(u), True)[1])
    action = _pagerduty()
    action.side_effects[0].config["url"] = "https://{severity}.example.com/x"
    ex.default_dispatch(action, {"summary": "s", "severity": "evil-host"})
    assert seen == ["https://evil-host.example.com/x"], seen


def test_a_parameter_that_moves_the_request_to_a_private_host_is_blocked(monkeypatch, sent):
    """And the outcome half, with the guard doing its real work: `localhost` resolves
    without a network, so this stays hermetic."""
    monkeypatch.delenv("AUGHOR_ALLOW_PRIVATE_WEBHOOKS", raising=False)
    action = _pagerduty()
    action.side_effects[0].config["url"] = "http://{summary}/x"
    with pytest.raises(ex.KineticDispatchError, match="SSRF guard"):
        ex.default_dispatch(action, {"summary": "localhost", "severity": "x"})
    assert sent == [], "a blocked call must not be made"


def test_an_unknown_method_is_refused_rather_than_passed_through(sent):
    action = _pagerduty(method="TRACE")
    with pytest.raises(ex.KineticDispatchError, match="TRACE"):
        ex.default_dispatch(action, {"summary": "s", "severity": "x"})
    assert sent == []


def test_a_huge_response_is_capped_before_it_reaches_a_run_record(sent, monkeypatch):
    """A vendor answering with a megabyte must not put a megabyte into a record a canvas
    will render."""
    big = "x" * (ex.MAX_RESPONSE_CHARS + 100)

    class _Big:
        status_code = 200
        is_success = True
        text = big

        def json(self):
            raise ValueError("not json")

    import httpx
    monkeypatch.setattr(httpx, "request", lambda *a, **k: _Big())
    out = ex.default_dispatch(_pagerduty(), {"summary": "s", "severity": "x"})
    se = out["side_effects"][0]
    assert se["truncated"] is True
    assert len(se["response_text"]) == ex.MAX_RESPONSE_CHARS


# ── the outbound seam ─────────────────────────────────────────────────────────

def _external_events(monkeypatch) -> list:
    events: list = []
    from aughor.obs import session_log as slog
    monkeypatch.setattr(slog, "emit",
                        lambda kind, **kw: events.append({"kind": kind, **kw}))
    return events


def test_the_component_call_is_capped_spanned_and_counted(sent, monkeypatch):
    events = _external_events(monkeypatch)
    ex.default_dispatch(_pagerduty(), {"summary": "s", "severity": "x"})
    from aughor.obs import session_log as slog
    external = [e for e in events if e["kind"] == slog.EXTERNAL_CALL]
    assert external and external[0]["ok"] is True
    assert external[0]["name"] == "http_component.page_oncall"


def test_the_OLDER_webhook_kind_now_joins_that_seam_too(monkeypatch):
    """VA-9a named three senders that emitted no span and consulted no cap and fixed them.
    This was the fourth and was missed: a declared webhook fired unbudgeted and invisible
    to `observed_usage`, which reads session events rather than spans."""
    events = _external_events(monkeypatch)

    class _R:
        status_code = 200
        is_success = True

    import httpx
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _R())
    action = KineticAction(id="ping", kind="side_effect", side_effects=[
        SideEffect(kind="webhook", config={"url": "https://hooks.example.com/x"})])
    ex.default_dispatch(action, {})
    from aughor.obs import session_log as slog
    assert [e for e in events if e["kind"] == slog.EXTERNAL_CALL], \
        "the declared webhook still bypasses govern.outbound"


# ── the credential at rest ────────────────────────────────────────────────────

def test_a_new_secret_is_encrypted_before_it_reaches_the_override_file():
    """An ontology override is a FILE, and files here are tracked. Plaintext would be a
    key in the repo."""
    fields = {"kind": "side_effect", "side_effects": [
        {"kind": "http", "config": {"url": "https://x.example.com", "auth_secret": "raw-key"}}]}
    out = encrypt_action_secrets(fields)
    stored = out["side_effects"][0]["config"]["auth_secret"]
    assert is_encrypted(stored) and stored != "raw-key"
    assert decrypt_secret(stored) == "raw-key"


def test_an_unchanged_masked_secret_keeps_what_is_already_stored():
    """The edit-form trap. Someone fixes a typo in the description; the form sends back the
    mask it was showing; storing it would replace the credential with bullets."""
    previous = {"side_effects": [
        {"kind": "http", "config": {"auth_secret": encrypt_secret("original-key")}}]}
    incoming = {"kind": "side_effect", "side_effects": [
        {"kind": "http", "config": {"url": "https://x.example.com",
                                    "auth_secret": "••••key"}}]}
    out = encrypt_action_secrets(incoming, previous)
    assert decrypt_secret(out["side_effects"][0]["config"]["auth_secret"]) == "original-key"


def test_the_api_form_shows_that_a_key_is_set_without_showing_the_key():
    """Masked rather than dropped, unlike a Connection's tokens: this feeds an EDIT form,
    and a dropped field makes "no key" and "a key you may not see" look identical."""
    dumped = {"side_effects": [
        {"kind": "http", "config": {"auth_secret": encrypt_secret("super-secret-value")}}]}
    safe = mask_action_secrets(dumped)
    shown = safe["side_effects"][0]["config"]["auth_secret"]
    assert "super-secret-value" not in shown
    assert not is_encrypted(shown), "the ciphertext itself must not be handed out either"
    assert shown, "an empty value would read as 'no credential set'"


# ── the law ───────────────────────────────────────────────────────────────────

def test_the_executor_contains_no_code_evaluation():
    """DS-13's defining claim, checked rather than asserted in prose. `ast` is imported
    here for the SAFE predicate evaluator, which walks a parsed tree and never runs it."""
    import inspect
    src = inspect.getsource(ex)
    assert "exec(" not in src
    # `eval(` must not appear as a call — `_eval` (the guarded walker) is a different name.
    assert " eval(" not in src and "=eval(" not in src and "(eval(" not in src
