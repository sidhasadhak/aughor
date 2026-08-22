"""Migration 10 — `role` and `fallback` as columns, and the tri-state that makes them honest.

Migration 7 promoted the *measures* (provider, model, tokens) out of the JSON payload and stopped.
The two facts it left behind are the two an activity view is actually about:

* **role** — what the call was FOR. Measured 2026-08-14 on the live log: present on 100% of 2,769
  `llm_call` rows, and the spend is wildly uneven (coder 7.48M tokens, narrator 61k, fast 208k).
* **fallback** — whether the primary backend refused and another provider answered. 18% of calls,
  and the chain can reach a PAID backend from a free primary, so it is the most cost-relevant bit
  in the table.

Both were unqueryable: a GROUP BY over them meant parsing every payload.

The tri-state is the subtle half and the reason this file exists. `fallback` must be
True / False / **unknown**, because 3,077 of 5,846 rows are non-`llm_call` kinds that never
carried the fact. Collapsing unknown to False would understate the fallback rate — an error in
precisely the direction that hides a problem — which is the "denominator must contain only things
that could have had the property" rule, applied to a column instead of a ratio.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from aughor.kernel.ledger import Ledger, _as_bool_int


@pytest.fixture
def ledger(tmp_path):
    return Ledger(tmp_path / "led.db")


def _rows(ledger):
    c = sqlite3.connect(ledger.path)
    return list(c.execute("SELECT kind, role, fallback FROM session_events ORDER BY seq"))


# ── the columns exist and are indexed ─────────────────────────────────────────────

def test_migration_adds_the_columns_and_an_index(ledger):
    c = sqlite3.connect(ledger.path)
    cols = {r[1] for r in c.execute("PRAGMA table_info(session_events)")}
    assert {"role", "fallback"} <= cols
    idx = {r[1] for r in c.execute("PRAGMA index_list(session_events)")}
    assert "session_events_role" in idx, "role is a GROUP BY dimension; it needs its index"


# ── the live insert path ──────────────────────────────────────────────────────────

def test_insert_derives_role_and_fallback_from_the_payload(ledger):
    """No emitter had to change: `_record_llm_call` already puts both in the payload."""
    ledger.session_event_insert({"trace_id": "t", "kind": "llm_call",
                                 "payload": {"role": "coder", "fallback": True}})
    assert _rows(ledger) == [("llm_call", "coder", 1)]


def test_explicit_columns_win_over_the_payload(ledger):
    ledger.session_event_insert({"trace_id": "t", "kind": "llm_call",
                                 "role": "narrator", "fallback": False,
                                 "payload": {"role": "IGNORED", "fallback": True}})
    assert _rows(ledger) == [("llm_call", "narrator", 0)]


def test_a_row_that_never_carried_the_fact_stays_unknown(ledger):
    """The tri-state. A tool_call is not a call that "did not fall back"."""
    ledger.session_event_insert({"trace_id": "t", "kind": "tool_call", "name": "run_sql"})
    assert _rows(ledger) == [("tool_call", None, None)]


def test_false_is_recorded_as_false_not_as_unknown(ledger):
    ledger.session_event_insert({"trace_id": "t", "kind": "llm_call",
                                 "payload": {"role": "fast", "fallback": False}})
    assert _rows(ledger) == [("llm_call", "fast", 0)]


def test_as_bool_int_keeps_none_as_none():
    """The whole point: `None` in, `None` out. `0` and `None` must not converge."""
    assert _as_bool_int(None) is None
    assert _as_bool_int(False) == 0 and _as_bool_int(False) is not None


@pytest.mark.parametrize("value,expected", [
    (True, 1), (False, 0), (1, 1), (0, 0),
    ("true", 1), ("True", 1), ("1", 1), ("yes", 1),
    ("false", 0), ("no", 0), ("", 0), ("garbage", 0),
])
def test_as_bool_int_coerces_known_shapes(value, expected):
    got = _as_bool_int(value)
    assert got == expected and isinstance(got, int)


# ── the back-fill ─────────────────────────────────────────────────────────────────

def test_backfill_populates_history_and_leaves_unknowns_alone(tmp_path):
    """A migration that only helps FUTURE rows leaves the operator with an empty view today."""
    path = tmp_path / "hist.db"
    # Write rows with the PRE-migration schema — payload only, no columns.
    led = Ledger(path)
    c = sqlite3.connect(path)
    c.executescript("DROP INDEX IF EXISTS session_events_role;"
                    "UPDATE session_events SET role=NULL, fallback=NULL;")
    c.execute("INSERT INTO session_events (at, trace_id, kind, payload) VALUES (?,?,?,?)",
              ("2026-01-01", "t", "llm_call", json.dumps({"role": "coder", "fallback": True})))
    c.execute("INSERT INTO session_events (at, trace_id, kind, payload) VALUES (?,?,?,?)",
              ("2026-01-01", "t", "llm_call", json.dumps({"role": "fast", "fallback": False})))
    c.execute("INSERT INTO session_events (at, trace_id, kind, payload) VALUES (?,?,?,?)",
              ("2026-01-01", "t", "tool_call", json.dumps({"tables": 3})))
    c.execute("INSERT INTO session_events (at, trace_id, kind, payload) VALUES (?,?,?,?)",
              ("2026-01-01", "t", "tool_call", "not json at all"))
    c.commit()
    c.close()
    del led

    from aughor.kernel.ledger import _add_session_event_attribution
    c = sqlite3.connect(path)
    _add_session_event_attribution(c)
    c.commit()

    got = list(c.execute("SELECT kind, role, fallback FROM session_events ORDER BY seq"))
    assert ("llm_call", "coder", 1) in got
    assert ("llm_call", "fast", 0) in got
    # a payload with no role/fallback keys, and a payload that is not JSON at all
    assert got.count(("tool_call", None, None)) == 2, \
        "a row with no fact, and a malformed payload, must both stay unknown — not crash the run"


# ── the query surface ─────────────────────────────────────────────────────────────

def test_role_filter_and_fallback_only(ledger):
    for role, fb in (("coder", True), ("coder", False), ("fast", False)):
        ledger.session_event_insert({"trace_id": "t", "kind": "llm_call",
                                     "payload": {"role": role, "fallback": fb}})
    ledger.session_event_insert({"trace_id": "t", "kind": "tool_call"})

    assert len(ledger.session_events(role="coder")) == 2
    assert len(ledger.session_events(role="fast")) == 1
    only = ledger.session_events(fallback_only=True)
    assert len(only) == 1, "fallback_only must match =1, never 'IS NOT 0' (which sweeps in NULLs)"
    assert only[0]["role"] == "coder"


def test_fallback_reaches_the_caller_as_a_tri_state(ledger):
    ledger.session_event_insert({"trace_id": "t", "kind": "llm_call",
                                 "payload": {"role": "coder", "fallback": False}})
    ledger.session_event_insert({"trace_id": "t", "kind": "tool_call"})
    by_kind = {e["kind"]: e for e in ledger.session_events()}
    assert by_kind["llm_call"]["fallback"] is False
    assert by_kind["tool_call"]["fallback"] is None, \
        "unknown must survive the trip out, not arrive as a confident False"
