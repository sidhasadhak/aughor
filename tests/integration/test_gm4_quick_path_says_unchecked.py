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
    # The SQL writer bound `get_provider` by name at import; its repair would reach the real provider.
    monkeypatch.setattr("aughor.sql.writer.get_provider", lambda role="coder", **kw: _Model())


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


# ── a filter finding the quick path acts on is re-checked, and one it cannot clear is said ─────────────────────────

_MISSPELLED = "SELECT COUNT(*) AS n FROM customers WHERE segment = 'Enterprize'"   # stored: 'Enterprise'


def _stub_scripted(monkeypatch, first: str, repair: str) -> dict:
    """The model writes ``first``; asked to repair, it writes ``repair``. Counts its calls."""
    import aughor.llm.provider as prov
    from aughor.routers.investigations import _ChatAnswer, _PostAnswer
    calls = {"answer": 0, "repair": 0}

    class _Model:
        def complete(self, system=None, user=None, response_model=None, temperature=0.1, **kw):
            if response_model is _ChatAnswer:
                calls["answer"] += 1
                return _ChatAnswer(sql=first, headline="There are **N** customers")
            if response_model is _PostAnswer:
                return _PostAnswer(narrative="", anomalies=[], trend="stable", confidence="high", questions=[])
            if response_model is not None and "corrected_sql" in getattr(response_model, "model_fields", {}):
                calls["repair"] += 1
                return response_model(corrected_sql=repair, explanation="rewrote the filter")
            return response_model() if response_model else None

        def complete_streaming(self, *, system, user, response_model, temperature=0.0, text_field, on_text):
            return self.complete(system=system, user=user, response_model=response_model)

    monkeypatch.setattr(prov, "get_provider", lambda role="coder", **kw: _Model())
    monkeypatch.setattr("aughor.sql.writer.get_provider", lambda role="coder", **kw: _Model())
    return calls


def _ask_region(connection_id: str):
    return inv._answer_core("Count the customers.", connection_id, [],
                            emit=lambda t, p: None, skip_clarify=True)


def test_a_literal_the_preflight_bound_is_not_repaired_back_by_the_model(client, builtin_conn_id, monkeypatch):
    """theLook, live, 2026-09-29: the model wrote `country = 'Brazil'` (stored: 'Brasil'). The quick path's filter
    guard read the model's statement BEFORE the pre-flight bound the literal, so its finding outlived the fix and
    asked the model for a repair; the repair wrote 'Brazil' again and was adopted without the filter being asked
    again — 0 shipped where the answer is 4,458, with no caveat."""
    calls = _stub_scripted(monkeypatch, first=_MISSPELLED, repair=_MISSPELLED)
    res = _ask_region(builtin_conn_id)
    assert not res.error, res.error
    assert "'Enterprise'" in res.sql, f"the bound literal did not reach the answer: {res.sql}"
    assert [str(v) for v in res.rows[0]] == ["297"]
    assert calls["repair"] == 0, "a finding the pre-flight had already fixed still asked the model for a repair"


def test_a_repair_that_writes_a_bad_literal_is_not_adopted(client, builtin_conn_id, monkeypatch):
    """A repair asked for by ANOTHER check (here the breakdown grain) is a new statement the model wrote; the
    filter guard is asked of it too, and one that writes a literal the column does not hold is refused."""
    first = "SELECT customer_id, SUM(mrr) AS mrr FROM customers GROUP BY customer_id"
    bad_repair = "SELECT segment, SUM(mrr) AS mrr FROM customers WHERE region = 'Emea' GROUP BY segment"
    calls = _stub_scripted(monkeypatch, first=first, repair=bad_repair)
    res = inv._answer_core("Show total mrr by segment", builtin_conn_id, [], emit=lambda t, p: None,
                           skip_clarify=True)
    assert not res.error, res.error
    assert calls["repair"] >= 1, "the grain check did not ask for a repair — this test proves nothing"
    assert res.sql.strip() == first, f"a repair writing region = 'Emea' (stored: 'EMEA') was adopted: {res.sql}"
    kept = [r for r in res.guard_receipts if r.get("guard") == "repair_recheck"]
    assert kept and "filter" in kept[0]["detail"]


def test_a_value_in_no_column_is_said_and_never_repaired(client, builtin_conn_id, monkeypatch):
    """A literal no column holds is an honest absence: the model is not asked to repair it (a "fix" that drops the
    predicate answers another question), and the zero ships with the reason beside it."""
    calls = _stub_scripted(monkeypatch, first="SELECT COUNT(*) AS n FROM customers WHERE region = 'Atlantis'",
                           repair="SELECT COUNT(*) AS n FROM customers")
    res = _ask_region(builtin_conn_id)
    assert not res.error, res.error
    assert calls["repair"] == 0, "a novel literal asked the model for a repair"
    assert "'Atlantis'" in res.sql
    assert any("'Atlantis' is not a stored value of customers.region" in c and "absent, not zero" in c
               for c in res.caveats), res.caveats


def test_a_repair_that_fixes_the_literal_answers_without_a_stale_caveat(client, builtin_conn_id, monkeypatch):
    """When the pre-flight cannot bind a literal, the model is asked; a repair the filter guard confirms is
    adopted, and the caveats describe the statement that answers, not the one it replaced."""
    monkeypatch.setattr("aughor.sql.join_guard.bind_filter_literals", lambda conn, sql, dialect="duckdb": (sql, []))
    fixed = "SELECT COUNT(*) AS n FROM customers WHERE segment = 'Enterprise'"
    calls = _stub_scripted(monkeypatch, first=_MISSPELLED, repair=fixed)
    res = _ask_region(builtin_conn_id)
    assert not res.error, res.error
    assert calls["repair"] >= 1 and res.sql.strip() == fixed
    assert [str(v) for v in res.rows[0]] == ["297"]
    assert not any("Enterprize" in c for c in res.caveats), f"a caveat about the replaced statement: {res.caveats}"
