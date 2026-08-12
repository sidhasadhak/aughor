"""PE-1 — prompt-token spend per call site.

Three claims:
  1. Every provider call is attributed to the SITE that spent the tokens
     (stack-derived — no opt-in kwarg to forget), and the attribution survives
     the round trip through ``session_log.emit`` (the route-mix ``_clip`` lesson:
     a write-path defect once survived full coverage of the reader because no
     test ever put a payload THROUGH emit and read it back).
  2. The fold's denominators are honest: calls without reported usage are
     counted, never folded into zero; pre-attribution events appear as a
     visible ``(unattributed)`` row.
  3. The numbers are reachable over HTTP (a fold with no route is not a
     measurement — the model_usage gap this wave also closes).
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from aughor.api import app
from aughor.obs import session_log

client = TestClient(app)


def _emit_call(caller=None, prompt_tokens=100, completion_tokens=10, model="m-test"):
    # trace_id passed explicitly: emit DROPS trace-less events by design (an
    # uncorrelated row cannot be reconstructed into anything).
    payload = {"role": "coder"}
    if caller:
        payload["caller"] = caller
    session_log.emit(session_log.LLM_CALL, name=model, trace_id="t-pe1-test",
                     ok=True, duration_ms=5.0, provider="faux", model=model,
                     prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                     payload=payload)


def test_prompt_weight_round_trips_through_emit():
    _emit_call(caller="aughor.agent.prompts_investigate:report_user_prompt",
               prompt_tokens=3833, completion_tokens=900)
    _emit_call(caller="aughor.agent.prompts_investigate:report_user_prompt",
               prompt_tokens=3000, completion_tokens=800)
    out = session_log.prompt_weight()
    site = next(s for s in out["sites"]
                if s["caller"] == "aughor.agent.prompts_investigate:report_user_prompt")
    assert site["calls"] >= 2
    assert site["prompt_tokens"] >= 6833
    assert site["roles"].get("coder", 0) >= 2
    assert out["reported_prompt_tokens"] >= site["prompt_tokens"]


def test_unreported_usage_is_counted_not_zeroed():
    _emit_call(caller="aughor.test:usage_free_site",
               prompt_tokens=None, completion_tokens=None)
    out = session_log.prompt_weight()
    site = next(s for s in out["sites"] if s["caller"] == "aughor.test:usage_free_site")
    assert site["calls_without_usage"] >= 1
    assert site["prompt_tokens"] == 0
    assert site["mean_prompt_tokens"] is None or site["calls"] > site["calls_without_usage"], \
        "a site with no reported usage must not fabricate a mean"


def test_pre_attribution_events_fold_into_a_visible_bucket():
    _emit_call(caller=None, prompt_tokens=42)
    out = session_log.prompt_weight()
    assert any(s["caller"] == "(unattributed)" for s in out["sites"]), \
        "old events without attribution must be visible, never silently dropped"


def test_caller_attribution_walks_past_llm_plumbing():
    from aughor.llm.provider import _caller_attribution

    def _my_prompt_site():
        return _caller_attribution()

    got = _my_prompt_site()
    assert got and got.endswith(":_my_prompt_site"), got


def test_live_provider_call_is_attributed(monkeypatch):
    """A real complete() through the faux backend lands in the session log with a
    caller — the attribution is stamped by the provider, not by cooperating call
    sites."""
    from pydantic import BaseModel

    from aughor import telemetry
    from aughor.llm.faux import set_responses
    from aughor.llm.provider import LLMProvider

    class _Out(BaseModel):
        ok: bool

    provider = LLMProvider(backend="faux", role="coder")
    set_responses(['{"ok": true}'])

    def _briefing_shaped_site():
        return provider.complete("sys", "user", _Out)

    with telemetry.bind_trace("t-pe1-live"):
        _briefing_shaped_site()
    out = session_log.prompt_weight()
    mine = [s for s in out["sites"] if s["caller"].endswith(":_briefing_shaped_site")]
    assert mine, f"provider call not attributed; sites={[s['caller'] for s in out['sites'][:6]]}"


def test_prompt_weight_endpoint_serves_the_fold():
    _emit_call(caller="aughor.test:endpoint_site", prompt_tokens=7)
    r = client.get("/obs/prompt-weight")
    assert r.status_code == 200
    body = r.json()
    assert body["measured"] is True and "sites" in body
    assert any(s["caller"] == "aughor.test:endpoint_site" for s in body["sites"])


def test_model_usage_endpoint_exists():
    r = client.get("/obs/model-usage")
    assert r.status_code == 200
    assert "models" in r.json()
