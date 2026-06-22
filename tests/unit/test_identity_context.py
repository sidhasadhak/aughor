"""Identity-context breadth (ROADMAP §3) — the declared org identity (company/website/HQ/
industry, via `orgsettings.org_context`) now reaches the BRIEFING NARRATOR and the PROFILE
INFERENCE prompts, not just the explorer steering. Both prepend it unconditionally (it's '' when
unset, so a no-op for unconfigured orgs). These tests capture the LLM `user` prompt at each seam."""
from __future__ import annotations

import pytest

from aughor.knowledge import briefing as B
from aughor.profile import infer as I


class _Boom(Exception):
    """Raised by the fake LLM right after capturing the prompt — avoids constructing a full
    response model or triggering any downstream persistence."""


def _capture_provider(captured: dict):
    class _FakeLLM:
        _model = "test"

        def complete(self, system, user, **kw):
            captured["user"] = user
            raise _Boom()
    return lambda *_a, **_k: _FakeLLM()


# ── briefing narrator ──────────────────────────────────────────────────────────

def test_briefing_narrator_prepends_org_context(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr("aughor.llm.provider.get_provider", _capture_provider(captured))
    monkeypatch.setattr("aughor.orgsettings.org_context",
                        lambda workspace_id=None: "ORGANIZATION: Acme Foods, HQ Berlin — industry: Food Delivery.\n")
    domain_data = {"sales": [{"id": "f1", "domain": "sales", "angle": "trend",
                              "finding": "Revenue grew 10% to 1.2M this quarter.",
                              "confidence": 0.7, "novelty": 3}]}
    with pytest.raises(_Boom):
        B.generate_narrative(domain_data, [], "conn-x", workspace_id="ws-1")
    assert captured["user"].startswith("ORGANIZATION: Acme Foods, HQ Berlin")


def test_briefing_narrator_workspace_id_threads_to_org_context(monkeypatch):
    seen: dict = {}
    monkeypatch.setattr("aughor.llm.provider.get_provider", _capture_provider({}))

    def _org(workspace_id=None):
        seen["ws"] = workspace_id
        raise RuntimeError("stop early")   # the fail-open wrapper swallows this → '' prepended

    monkeypatch.setattr("aughor.orgsettings.org_context", _org)
    domain_data = {"sales": [{"id": "f1", "domain": "sales", "angle": "t",
                              "finding": "Revenue grew 10% to 1.2M.", "confidence": 0.7, "novelty": 3}]}
    with pytest.raises(_Boom):                  # reaches the (capturing) provider — org failure didn't break it
        B.generate_narrative(domain_data, [], "conn-x", workspace_id="ws-42")
    assert seen["ws"] == "ws-42"                # workspace override path reached


def test_briefing_org_context_failure_is_fail_open(monkeypatch):
    # an org_context blow-up must NOT break the brief — it still reaches the narrator.
    captured: dict = {}
    monkeypatch.setattr("aughor.llm.provider.get_provider", _capture_provider(captured))
    monkeypatch.setattr("aughor.orgsettings.org_context",
                        lambda workspace_id=None: (_ for _ in ()).throw(ValueError("boom")))
    domain_data = {"s": [{"id": "f1", "domain": "s", "angle": "t",
                          "finding": "Revenue grew 10% to 1.2M.", "confidence": 0.7, "novelty": 3}]}
    with pytest.raises(_Boom):
        B.generate_narrative(domain_data, [], "conn-x", workspace_id="ws-1")
    assert "user" in captured                   # narrator still called despite org_context error


# ── profile inference ────────────────────────────────────────────────────────────

def test_inference_prepends_org_context(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr("aughor.profile.infer._gather_context",
                        lambda conn, schema=None: ("TABLE orders(order_id INTEGER, total DECIMAL)", []))
    monkeypatch.setattr("aughor.orgsettings.org_context",
                        lambda workspace_id=None: "ORGANIZATION: Acme Foods — industry: Food Delivery.\n")
    monkeypatch.setattr("aughor.llm.provider.get_provider", _capture_provider(captured))
    with pytest.raises(_Boom):
        I.infer_business_profile("test-conn")
    assert captured["user"].startswith("ORGANIZATION: Acme Foods")
    assert "SCHEMA (tables" in captured["user"]   # org block sits ABOVE the schema block


def test_inference_no_org_settings_is_a_noop(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr("aughor.profile.infer._gather_context",
                        lambda conn, schema=None: ("TABLE orders(order_id INTEGER)", []))
    monkeypatch.setattr("aughor.orgsettings.org_context", lambda workspace_id=None: "")
    monkeypatch.setattr("aughor.llm.provider.get_provider", _capture_provider(captured))
    with pytest.raises(_Boom):
        I.infer_business_profile("test-conn")
    assert captured["user"].startswith("SCHEMA (tables")   # nothing prepended when unset
