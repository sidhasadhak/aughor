"""GM-4 — the quick path's filter guard, through the real answer core; only the model is stubbed.

The quick path runs its own filter value-domain guard before it executes, and GM-3 credits the answer's
statement with `guarded:filter-domain` once the guard has run. GM-4 made the guard say what it could not check;
these pin that the quick path carries it: `unchecked:filter-domain` on the answer's doors, never `guarded:`, and
the reason among the answer's caveats.
"""
from __future__ import annotations

from aughor.routers import investigations as inv
from aughor.sql.guard_run import GuardRun

_SQL = "SELECT COUNT(*) AS n FROM customers WHERE region = 'EMEA'"


def _stub_model(monkeypatch) -> None:
    import aughor.llm.provider as prov
    from aughor.routers.investigations import _ChatAnswer, _PostAnswer

    class _Model:
        def complete(self, system=None, user=None, response_model=None, temperature=0.1, **kw):
            if response_model is _ChatAnswer:
                return _ChatAnswer(sql=_SQL, headline="There are **250** customers in EMEA")
            if response_model is _PostAnswer:
                return _PostAnswer(narrative="", anomalies=[], trend="stable", confidence="high", questions=[])
            return response_model()

        def complete_streaming(self, *, system, user, response_model, temperature=0.0, text_field, on_text):
            return self.complete(system=system, user=user, response_model=response_model)

    monkeypatch.setattr(prov, "get_provider", lambda role="coder", **kw: _Model())


def _ask(connection_id: str):
    return inv._answer_core("How many customers are in EMEA?", connection_id, [], emit=lambda t, p: None,
                            skip_clarify=True)


def test_the_quick_path_credits_a_filter_guard_that_ran(client, builtin_conn_id, monkeypatch):
    _stub_model(monkeypatch)
    res = _ask(builtin_conn_id)
    assert not res.error, res.error
    assert res.sql.strip() == _SQL
    assert "guarded:filter-domain" in res.doors


def test_the_quick_path_says_what_its_filter_guard_could_not_check(client, builtin_conn_id, monkeypatch):
    _stub_model(monkeypatch)
    reason = "the values of customers.region could not be read: 400 refused"
    monkeypatch.setattr("aughor.sql.join_guard.filter_domain_check",
                        lambda db, sql: GuardRun("filter-domain", unchecked=[reason]))
    res = _ask(builtin_conn_id)
    assert not res.error, res.error
    assert "unchecked:filter-domain" in res.doors and "guarded:filter-domain" not in res.doors
    assert f"filter value-domain guard: not checked — {reason}" in res.caveats
