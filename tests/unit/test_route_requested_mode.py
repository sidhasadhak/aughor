"""Explicit Deep Analysis selection must bypass the route classifier."""
from aughor.agent.nodes import route_question


def test_requested_mode_binds_no_classifier(monkeypatch):
    import aughor.agent.nodes as n
    def _boom(q):
        raise AssertionError("classifier must not run for an explicit mode")
    monkeypatch.setattr(n, "classify_question", _boom)
    out = route_question({"question": "Where are we losing money?",
                          "requested_mode": "investigate"})
    assert out.get("query_mode") != "direct"
    assert "explicit user selection" in (out.get("route_reasoning") or "")
