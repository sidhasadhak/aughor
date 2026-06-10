"""Dismiss-with-reason (#3) — a user can hide a wrong/stale finding from the card.

Reuses the quarantine flag: sets invalid=True + reason (hidden from intel via the
store read filter, KEPT in the store, reversible) and logs the reason for the guard
backlog. No hand-edited JSON required.
"""
import aughor.explorer.store as store


def test_dismiss_flags_invalid_with_reason(monkeypatch):
    monkeypatch.setattr(store, "_log_dismissal", lambda *a, **k: None)
    state = {"insights": [{"id": "X", "finding": "f", "sql": "s"}]}
    ins = store._dismiss(state, "X", "wrong channel", "conn:t")
    assert ins is not None
    assert ins["invalid"] is True
    assert "wrong channel" in ins["invalid_reason"]


def test_dismiss_missing_id_returns_none(monkeypatch):
    monkeypatch.setattr(store, "_log_dismissal", lambda *a, **k: None)
    assert store._dismiss({"insights": []}, "nope", "r", "conn:t") is None


def test_dismiss_logs_the_reason(monkeypatch):
    logged = {}
    monkeypatch.setattr(store, "_log_dismissal", lambda scope, ins, reason: logged.update(scope=scope, reason=reason))
    store._dismiss({"insights": [{"id": "X"}]}, "X", "stale window", "conn:abc")
    assert logged == {"scope": "conn:abc", "reason": "stale window"}


def test_read_path_filters_dismissed(monkeypatch):
    monkeypatch.setattr(store, "load", lambda cid: {"insights": [
        {"id": "A"},
        {"id": "B", "invalid": True, "invalid_reason": "dismissed by user: x"},
    ]})
    assert [i["id"] for i in store.get_insights("any")] == ["A"]
    # the escape hatch still exposes quarantined findings for a review view
    assert [i["id"] for i in store.get_insights("any", include_invalid=True)] == ["A", "B"]
