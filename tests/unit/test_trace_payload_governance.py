"""VA-5 — what a trace read exposes, and what it records about itself.

Two things ship together here because Arc VA's decision ③ says they must:

    "Full payload access on all traces for admins, with **every access logged as an
    auditable event** (who, whose trace, when). The audit trail is the control, so it
    ships in the same PR as the access — never after."

The access shipped in #372 and the audit did not, so `/traces/{id}` returned every
payload — SQL, tool output, and captured prompt content — while recording nothing about
who had read it. These tests pin the half that was missing, plus the one thing that is
masked for *every* reader: a credential is not the subject's data, it is an access token
that reading would hand over.
"""
from __future__ import annotations

import pytest

from aughor.security import credentials as cred


# ── credential masking ──────────────────────────────────────────────────────────

def test_a_real_key_is_masked():
    text, n = cred.mask_credentials("export OPENAI_API_KEY=sk-abcd1234efgh5678ijkl")
    assert n == 1
    assert "sk-abcd1234efgh5678ijkl" not in text
    assert cred.MASK in text


@pytest.mark.parametrize("secret", [
    "ghp_abcdefghijklmnopqrstuvwxyz012345",
    "AKIAIOSFODNN7EXAMPLE",
    "xoxb-1234567890-abcdefghij",
    "AIzaSyA1234567890abcdefghijklmnopqrstuvw",
])
def test_every_vendor_prefix_shape_is_caught(secret):
    """The prefix IS the tell — no entropy test needed, and none of these should ever
    reach a screen because a run happened to echo its environment."""
    text, n = cred.mask_credentials(f"config: {secret}")
    assert n == 1 and secret not in text


def test_a_documentation_placeholder_is_left_alone():
    """`password=hunter2` in a tutorial is documentation. A masker that cannot tell it
    from a leak trains people to ignore what it hides."""
    for benign in ("password=hunter2", "api_key=YOUR_API_KEY", "token=<your-token>",
                   "secret=changeme", "password=${DB_PASSWORD}"):
        text, n = cred.mask_credentials(benign)
        assert n == 0 and text == benign, f"masked documentation: {benign}"


def test_a_high_entropy_assignment_is_masked_but_the_key_name_survives():
    """A reader still needs to see that a password was set, and where, to go and rotate
    it. Dropping the line says neither."""
    text, n = cred.mask_credentials("password=8Fq2xZ9vLm4TbW7pRk3Ns6Yd")
    assert n == 1
    assert text.startswith("password=") and cred.MASK in text


def test_masking_walks_nested_payloads_and_counts():
    payload = {"sql": "SELECT 1", "env": {"vars": ["TOKEN=sk-abcd1234efgh5678ijkl",
                                                   "SAFE=hello"]}}
    masked, n = cred.mask_payload(payload)
    assert n == 1
    assert masked["sql"] == "SELECT 1"
    assert cred.MASK in masked["env"]["vars"][0]
    assert masked["env"]["vars"][1] == "SAFE=hello"


def test_masking_is_depth_bounded():
    """A trace payload is arbitrary data from the run, not a shape we control. A masker
    the inspected thing can drive into unbounded recursion is a denial of service wearing
    a safety feature."""
    deep: dict = {}
    node = deep
    for _ in range(200):
        node["next"] = {}
        node = node["next"]
    node["leak"] = "sk-abcd1234efgh5678ijkl"
    masked, n = cred.mask_payload(deep)     # must return, not blow the stack
    assert n == 0, "a leak 200 levels deep was reached — the depth bound is not bounding"


def test_the_users_own_data_is_NOT_redacted():
    """Decision ③: admins see everything on a trace, audited. The subject's questions,
    SQL and PII are theirs to read — masking them here would quietly overrule
    a locked decision, and PII redaction belongs to the query-result path
    (`security/pii.py`), not to the trace viewer."""
    prose = "Why did revenue drop for jane.doe@example.com in the 90210 region?"
    text, n = cred.mask_credentials(prose)
    assert n == 0 and text == prose


def test_one_detector_serves_the_skills_linter_too():
    """VA-1's ingestion linter and this masker must agree on what a credential is. Two
    copies of that judgement drift into two answers for the same string."""
    from aughor.skills import lint
    assert lint._KEY_SHAPES is cred.KEY_SHAPES
    assert lint._SECRET_ASSIGN is cred.SECRET_ASSIGN
    assert lint._PLACEHOLDER is cred.PLACEHOLDER


# ── the raw-event seam ──────────────────────────────────────────────────────────

def test_the_event_seam_masks_and_reports_that_it_did():
    """A viewer that quietly alters what it shows is worse than one that shows
    everything, because nobody can tell which it did."""
    from aughor.routers.obs import _mark_content
    ev = {"payload": {"sql": "-- key sk-abcd1234efgh5678ijkl", "user_prompt": "hi"}}
    out = _mark_content(ev)
    assert out["credentials_masked"] == 1
    assert "sk-abcd1234efgh5678ijkl" not in str(out["payload"])
    assert out["content_captured"] is True, "prompt content must still be flagged"


def test_an_event_with_no_credential_is_untouched():
    from aughor.routers.obs import _mark_content
    ev = {"payload": {"sql": "SELECT category, SUM(sales) FROM orders GROUP BY 1"}}
    out = _mark_content(ev)
    assert "credentials_masked" not in out
    assert out["payload"]["sql"].startswith("SELECT category")


# ── the audit record (decision ③'s control) ─────────────────────────────────────

def test_reading_a_trace_journals_who_read_whose_run(monkeypatch):
    """THE seam test for this slice. Before it, `/traces/{id}` returned every payload and
    recorded nothing — an entitlement nobody can review is indistinguishable from no
    policy."""
    from aughor.routers import obs
    from aughor.org import context as octx

    emitted: list[tuple] = []

    class _FakeLedger:
        def emit(self, kind, payload=None, **kw):
            emitted.append((kind, payload, kw))
            return 1

    monkeypatch.setattr("aughor.kernel.ledger.Ledger.default",
                        classmethod(lambda cls: _FakeLedger()))
    tok = octx.set_user_id("admin-7")
    try:
        obs._audit_payload_access(
            "trace-abc",
            [{"user_id": "analyst-3", "agent_id": "agent-1", "content_captured": True},
             {"user_id": "analyst-3", "credentials_masked": 2}],
            "inv-9")
    finally:
        octx._current_user.reset(tok)

    assert emitted, "reading a trace's payloads journalled nothing"
    kind, payload, kw = emitted[0]
    assert kind == "trace.payload_access"
    assert payload["read_by"] == "admin-7"            # who
    assert payload["subject_user_id"] == "analyst-3"  # whose
    assert payload["trace_id"] == "trace-abc"
    assert payload["content_events"] == 1             # was prompt content exposed
    assert payload["credentials_masked"] == 2
    assert kw.get("trace_id") == "trace-abc"


def test_an_unattributed_run_says_so_rather_than_guessing():
    """Local single-user runs carry no identity. Empty is the honest answer; inventing
    one would make the audit trail assert something it does not know."""
    from aughor.routers import obs
    emitted: list[tuple] = []

    class _FakeLedger:
        def emit(self, kind, payload=None, **kw):
            emitted.append((kind, payload, kw))
            return 1

    import aughor.kernel.ledger as _led
    orig = _led.Ledger.default
    _led.Ledger.default = classmethod(lambda cls: _FakeLedger())
    try:
        obs._audit_payload_access("t", [{"kind": "tool_call"}], None)
    finally:
        _led.Ledger.default = orig
    assert emitted[0][1]["subject_user_id"] == ""


def test_a_failing_journal_never_denies_a_legitimate_read():
    """Telemetry must not break the thing it observes — including the audit path. A
    read that a broken journal blocks is an outage dressed as a control."""
    from aughor.routers import obs
    import aughor.kernel.ledger as _led

    class _Broken:
        def emit(self, *a, **k):
            raise RuntimeError("ledger down")

    orig = _led.Ledger.default
    _led.Ledger.default = classmethod(lambda cls: _Broken())
    try:
        obs._audit_payload_access("t", [], None)   # must not raise
    finally:
        _led.Ledger.default = orig


# ── the feed ────────────────────────────────────────────────────────────────────

def test_the_access_kind_is_visible_to_an_auditor():
    """A control that never reaches the audit feed is a row in a table nobody reads."""
    from aughor.govern.audit_categories import (
        CATEGORIES, KIND_CATEGORY, _SINKS, _summarize)
    assert KIND_CATEGORY["trace.payload_access"] == "data_access"
    assert "data_access" in CATEGORIES
    assert any(cat == "data_access" for cat, _ in _SINKS)
    line = _summarize("trace.payload_access",
                      {"read_by": "admin-7", "subject_user_id": "analyst-3",
                       "trace_id": "abcdef123456789", "content_events": 4})
    assert "admin-7" in line and "analyst-3" in line and "prompt content" in line


def test_the_actor_column_is_populated_for_this_kind():
    """`_from_ledger` looks for actor/set_by/cleared_by; this kind names it `read_by`,
    and an audit row whose actor column is blank answers the wrong half of 'who'."""
    from aughor.govern.audit_categories import _from_ledger
    import aughor.govern.audit_categories as ac

    ac_events = [{"created_at": "2026-08-23T10:00:00Z", "org_id": "default",
                  "payload": {"read_by": "admin-7", "trace_id": "t1"}}]
    orig = ac._ledger_events
    ac._ledger_events = lambda kind, limit: ac_events
    try:
        (ev,) = _from_ledger("trace.payload_access", 10)
    finally:
        ac._ledger_events = orig
    assert ev.actor == "admin-7"
    assert ev.category == "data_access"


def test_the_ROUTE_journals_it_not_just_the_helper(monkeypatch):
    """The wiring, not the part. The test above calls `_audit_payload_access` directly,
    so it passes whether or not `get_trace` ever calls it — which is the exact shape of
    a control that exists in the tree and fires nowhere. This one drives the route."""
    from aughor.routers import obs
    from aughor.obs import session_log
    import aughor.kernel.ledger as _led

    events = [
        {"seq": 1, "kind": session_log.USER_REQUEST, "at": "2026-08-23T10:00:00Z",
         "span_id": None, "parent_span_id": None, "name": "", "user_id": "analyst-3",
         "payload": {"question": "top categories?"}},
        {"seq": 2, "kind": session_log.LLM_CALL, "at": "2026-08-23T10:00:01Z",
         "span_id": None, "parent_span_id": None, "name": "m", "user_id": "analyst-3",
         "payload": {"user_prompt": "top categories?", "response": "Furniture"}},
    ]
    monkeypatch.setattr(session_log, "recover_session", lambda *a, **k: events)

    emitted: list[tuple] = []

    class _FakeLedger:
        def emit(self, kind, payload=None, **kw):
            emitted.append((kind, payload))
            return 1

    orig = _led.Ledger.default
    _led.Ledger.default = classmethod(lambda cls: _FakeLedger())
    try:
        result = obs.get_trace("trace-wired")
    finally:
        _led.Ledger.default = orig

    assert result["trace_id"] == "trace-wired"
    kinds = [k for k, _ in emitted]
    assert "trace.payload_access" in kinds, (
        "GET /traces/{id} returned payloads and journalled no access — decision ③'s "
        "control is built but not wired")
    payload = next(p for k, p in emitted if k == "trace.payload_access")
    assert payload["subject_user_id"] == "analyst-3"
    assert payload["content_events"] == 1, \
        "the record must say whether prompt content was actually exposed by this read"
