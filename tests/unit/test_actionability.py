"""Actionability wiring — connection-scoped promote + share-finding-to-trigger.

Covers the backend half of backlog #4 (#20): finding-level Promote-to-Org for
connection-scoped Briefing/Hub findings, and the generic 'Share' path that fires
an arbitrary finding to a configured Action Hub trigger.

See aughor/explorer/store.py::promote_insight_conn and
aughor/routers/{exploration,actions}.py.
"""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import aughor.explorer.store as store
from aughor.routers.exploration import promote_connection_insight
from aughor.routers.actions import send_finding_to_trigger, _SendFindingBody


@pytest.fixture(autouse=True)
def _isolate_store(tmp_path, monkeypatch):
    """Redirect the explorer store per test.

    Was a bare `store._DATA_DIR = tmp_path` inside `_seed_conn` — a module-global assignment
    with NO teardown, so it leaked this file's tmp_path into every later test in the session
    (caught by test_store_hermeticity's sentinel, which sorts after this file). monkeypatch
    restores it; the assignment never did."""
    monkeypatch.setattr(store, "_DATA_DIR", tmp_path)


# ── #20a: connection-scoped promote ──────────────────────────────────────────

def _seed_conn(tmp_path, conn_id, insights):
    state = store._empty()
    state["insights"] = insights
    store.save(conn_id, state)


def test_promote_insight_conn_found(tmp_path):
    _seed_conn(tmp_path, "c1", [
        {"id": "i1", "finding": "Revenue spiked", "domain": "Sales",
         "confidence": 0.8, "novelty": 7},
    ])
    out = store.promote_insight_conn("c1", "i1")
    assert out is not None
    assert out["promoted_to_org"] is True
    assert out["promotion_confidence"] == 0.8
    # persisted
    reloaded = store.load("c1")
    assert reloaded["insights"][0]["promoted_to_org"] is True


def test_promote_insight_conn_not_found(tmp_path):
    _seed_conn(tmp_path, "c1", [{"id": "i1", "finding": "x"}])
    assert store.promote_insight_conn("c1", "nope") is None


def test_promote_insight_conn_missing_confidence_defaults_zero(tmp_path):
    _seed_conn(tmp_path, "c1", [{"id": "i1", "finding": "x"}])
    out = store.promote_insight_conn("c1", "i1")
    assert out["promotion_confidence"] == 0.0


def test_promote_finds_per_schema_insight(tmp_path):
    """Multi-schema connections store insights under {conn}__{schema}; the
    promote endpoint only knows the connection id. Looking in the bare file
    alone made Promote-to-Org a dead button (404) on every per-schema finding."""
    _seed_conn(tmp_path, "c1", [])  # bare state exists but holds nothing
    _seed_conn(tmp_path, "c1__sales", [
        {"id": "s1", "finding": "APAC drop", "domain": "Sales", "confidence": 0.9},
    ])
    out = store.promote_insight_conn("c1", "s1")
    assert out is not None and out["promoted_to_org"] is True
    assert out["source_schema"] == "sales"  # scope recorded for org-intel attribution
    # persisted in the per-schema store, not the bare one
    assert store.load("c1__sales")["insights"][0]["promoted_to_org"] is True
    assert store.load("c1")["insights"] == []


def test_dismiss_finds_per_schema_insight(tmp_path):
    _seed_conn(tmp_path, "c1", [])
    _seed_conn(tmp_path, "c1__ops", [{"id": "o1", "finding": "noise", "domain": "Ops"}])
    out = store.dismiss_insight_conn("c1", "o1", reason="not actionable")
    assert out is not None and out["invalid"] is True
    assert store.load("c1__ops")["insights"][0]["invalid"] is True


def test_promote_endpoint_found(tmp_path, monkeypatch):
    # store layer returns an insight → endpoint reports promoted; Qdrant push is
    # best-effort and must not raise even when unavailable.
    monkeypatch.setattr(store, "promote_insight_conn",
                        lambda c, i: {"finding": "f", "domain": "d", "novelty": 5, "angle": "a"})
    out = promote_connection_insight("conn1", "i1")
    assert out == {"insight_id": "i1", "promoted": True}


def test_promote_endpoint_not_found(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "promote_insight_conn", lambda c, i: None)
    with pytest.raises(HTTPException) as ei:
        promote_connection_insight("conn1", "ghost")
    assert ei.value.status_code == 404


# ── #20b: share finding to a trigger ─────────────────────────────────────────

def _fake_trigger(enabled=True):
    return SimpleNamespace(id="t1", name="slack-ops", type="slack", url="http://x",
                           headers={}, enabled=enabled, channel="#ops",
                           project=None, issue_type=None)


def test_send_finding_empty_text_400():
    with pytest.raises(HTTPException) as ei:
        send_finding_to_trigger("t1", _SendFindingBody(text="   "))
    assert ei.value.status_code == 400


def test_send_finding_unknown_trigger_404(monkeypatch):
    import aughor.actions.store as astore
    monkeypatch.setattr(astore, "get_trigger", lambda tid: None)
    with pytest.raises(HTTPException) as ei:
        send_finding_to_trigger("ghost", _SendFindingBody(text="hello"))
    assert ei.value.status_code == 404


def test_send_finding_maps_payload(monkeypatch):
    import aughor.actions.store as astore
    import aughor.actions.executor as execu
    captured = {}

    def _capture(trigger, payload):
        captured["trigger"] = trigger
        captured["payload"] = payload
        return SimpleNamespace(to_dict=lambda: {"status": "ok"})

    monkeypatch.setattr(astore, "get_trigger", lambda tid: _fake_trigger())
    monkeypatch.setattr(execu, "fire_action", _capture)

    out = send_finding_to_trigger("t1", _SendFindingBody(
        text="Churn is up 12% in EU", metric_name="churn_rate",
        headline="Retention · cohort", source_id="insight_42"))

    assert out == {"status": "ok"}
    p = captured["payload"]
    assert p.recommendation == "Churn is up 12% in EU"
    assert p.metric_name == "churn_rate"
    assert p.headline == "Retention · cohort"
    assert p.investigation_id == "insight_42"  # source_id threads through as provenance


def test_send_finding_disabled_trigger_reports_failed(monkeypatch, tmp_path):
    # End-to-end through the real fire_action with a DISABLED trigger: short-circuits
    # before any network call, so we exercise the wiring without external deps.
    import aughor.actions.store as astore
    monkeypatch.setattr(astore, "get_trigger", lambda tid: _fake_trigger(enabled=False))
    monkeypatch.setattr(astore, "_LOG_PATH", tmp_path / "logs.json", raising=False)
    monkeypatch.setattr(astore, "log_action", lambda log: None)
    out = send_finding_to_trigger("t1", _SendFindingBody(text="hi"))
    assert out["status"] == "failed"
    assert "disabled" in (out["error"] or "").lower()
