"""Wave A3 — source version probes.

Locks the three pre-registered gate properties plus the semantic that makes them safe to compose:

* **Exactly-once**: inserting rows advances the fingerprint and fires the condition once; the next
  tick with no new rows does not re-fire.
* **Fail-open, loudly**: a table with no usable version column (or a broken probe, or a bad
  identifier) evaluates as "changed" WITH the reason recorded — never a silent never-fires.
* **One bounded aggregate**: the probe issues a single `SELECT COUNT(*), MAX(col)` — asserted by
  capturing the SQL, not by trusting the docstring.
* **Baselines commit only on a FIRED tick** — the no-lost-change property: under `all` logic, a
  data change observed while the schedule condition is false must still be there to fire on when
  the schedule comes due.

Probes run against a REAL in-memory DuckDB (the fingerprint math is the thing under test);
baselines land in the hermetic conftest store.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import duckdb
import pytest

from aughor.automations.engine import run_automation
from aughor.automations.models import Automation, Condition, Effect, EffectOutcome
from aughor.automations.probes import (
    commit_fired_baselines,
    current_version,
    evaluate_source_condition,
)
from aughor.automations.store import (
    delete_automation,
    get_probe_baseline,
    get_runs,
    purge_connection,
    set_probe_baseline,
    upsert_automation,
)

NOW = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)


class _DuckLike:
    """The minimal slice of DatabaseConnection the probe needs: execute(label, sql) → rows/error.
    Captures every SQL so tests can assert the probe's query shape."""

    def __init__(self, con):
        self._con = con
        self.sqls: list[str] = []

    def execute(self, label, sql):
        self.sqls.append(sql)
        try:
            return SimpleNamespace(rows=self._con.execute(sql).fetchall(), error=None)
        except Exception as exc:
            return SimpleNamespace(rows=[], error=str(exc))

    def close(self):
        pass


@pytest.fixture
def duck():
    con = duckdb.connect()
    con.execute("""
        CREATE TABLE orders (
            id INTEGER, amount DOUBLE, updated_at TIMESTAMP
        );
        INSERT INTO orders VALUES
            (1, 10.0, TIMESTAMP '2026-07-01 08:00:00'),
            (2, 20.0, TIMESTAMP '2026-07-02 08:00:00');
        CREATE TABLE tags (label VARCHAR);
        INSERT INTO tags VALUES ('a'), ('b');
    """)
    return _DuckLike(con)


def _uid(request) -> str:
    """A per-test connection id, so connection_column_types' success-cache never crosses tests."""
    return f"probe-{request.node.name}"


# ── current_version: signal choice + fingerprint semantics ────────────────────────

def test_version_prefers_the_timestamp_column(duck, request):
    v, how = current_version(_uid(request), duck, "orders")
    assert v == "n=2|updated_at=2026-07-02 08:00:00"
    assert "MAX(updated_at)" in how


def test_probe_is_one_bounded_aggregate_never_a_data_scan(duck, request):
    current_version(_uid(request), duck, "orders")
    probe_sqls = [s for s in duck.sqls if "information_schema" not in s]
    assert probe_sqls == ["SELECT COUNT(*), MAX(updated_at) FROM orders"]


def test_insertions_only_ignores_the_timestamp_and_uses_the_pk(duck, request):
    v, how = current_version(_uid(request), duck, "orders", insertions_only=True)
    assert v == "n=2|id=2"
    assert "MAX(id)" in how


def test_no_signal_column_falls_back_to_row_count(duck, request):
    v, how = current_version(_uid(request), duck, "tags")
    assert v == "n=2"
    assert how == "row count"


def test_insert_changes_the_fingerprint(duck, request):
    uid = _uid(request)
    before, _ = current_version(uid, duck, "orders")
    duck._con.execute("INSERT INTO orders VALUES (3, 30.0, TIMESTAMP '2026-07-03 08:00:00')")
    after, _ = current_version(uid, duck, "orders")
    assert before != after


def test_delete_changes_the_fingerprint_where_a_watermark_would_miss_it(duck, request):
    """Inequality-compare, not ordering: a count drop registers even though MAX() went down."""
    uid = _uid(request)
    before, _ = current_version(uid, duck, "orders")
    duck._con.execute("DELETE FROM orders WHERE id = 2")
    after, _ = current_version(uid, duck, "orders")
    assert before != after


def test_an_update_touch_moves_source_change_but_not_entity_appears(duck, request):
    """The semantic split: updated_at advancing is a source change, not a new entity."""
    uid = _uid(request)
    src_before, _ = current_version(uid, duck, "orders")
    ent_before, _ = current_version(uid, duck, "orders", insertions_only=True)
    duck._con.execute("UPDATE orders SET updated_at = TIMESTAMP '2026-07-10 09:00:00' WHERE id = 1")
    src_after, _ = current_version(uid, duck, "orders")
    ent_after, _ = current_version(uid, duck, "orders", insertions_only=True)
    assert src_before != src_after
    assert ent_before == ent_after


@pytest.mark.parametrize("bad", [
    "orders; DROP TABLE orders", "orders--", "a.b.c.d", "", "or ders", "orders'",
])
def test_a_non_identifier_target_is_refused_never_interpolated(duck, request, bad):
    v, how = current_version(_uid(request), duck, bad)
    assert v is None
    assert "identifier" in how
    assert all(bad not in s for s in duck.sqls), "the bad target reached SQL"


def test_a_missing_table_cannot_be_versioned(duck, request):
    v, how = current_version(_uid(request), duck, "ghost_table")
    assert v is None
    assert "probe failed" in how


# ── evaluate_source_condition: compare only, never commit ─────────────────────────

def _automation(conn_id, conds, **kw):
    base = dict(conn_id=conn_id, name="A", conditions=conds,
                effects=[Effect(kind="notify", config={"trigger_id": "t1"})],
                max_retries=0, retry_backoff_seconds=0.0)
    base.update(kw)
    return Automation(**base)


@pytest.fixture
def wired(duck, monkeypatch, request):
    """Route open_connection_for at the automation's conn to the in-memory DuckDB."""
    monkeypatch.setattr("aughor.db.connection.open_connection_for", lambda cid: duck)
    return duck


def test_first_observation_fires_and_does_not_commit(wired, request):
    a = upsert_automation(_automation(_uid(request),
                                      [Condition(kind="source_change", config={"table": "orders"})]))
    fired, detail = evaluate_source_condition(a.conditions[0], a)
    assert fired is True
    assert "first observation" in detail
    # Evaluation NEVER commits — that is the engine's post-fire job.
    assert get_probe_baseline(a.id, "orders") is None


def test_unchanged_after_commit_does_not_fire(wired, request):
    a = upsert_automation(_automation(_uid(request),
                                      [Condition(kind="source_change", config={"table": "orders"})]))
    commit_fired_baselines(a)
    fired, detail = evaluate_source_condition(a.conditions[0], a)
    assert fired is False
    assert "unchanged" in detail


def test_change_fires_with_old_and_new_in_the_detail(wired, request):
    a = upsert_automation(_automation(_uid(request),
                                      [Condition(kind="source_change", config={"table": "orders"})]))
    commit_fired_baselines(a)
    wired._con.execute("INSERT INTO orders VALUES (9, 90.0, TIMESTAMP '2026-07-20 08:00:00')")
    fired, detail = evaluate_source_condition(a.conditions[0], a)
    assert fired is True
    assert "→" in detail and "n=3" in detail


def test_unversionable_table_fails_open_with_the_reason(wired, request):
    a = upsert_automation(_automation(_uid(request),
                                      [Condition(kind="source_change", config={"table": "ghost"})]))
    fired, detail = evaluate_source_condition(a.conditions[0], a)
    assert fired is True
    assert "failing open to changed" in detail


# ── the engine joint: exactly-once, no lost change, flag gate ─────────────────────

@pytest.fixture
def flag_on(monkeypatch):
    monkeypatch.setattr("aughor.kernel.flags.flag_enabled",
                        lambda n: n == "automations.source_probes")


def _dispatch_ok(effect, automation):
    return EffectOutcome(kind=effect.kind, target=effect.target(), status="executed")


def test_insert_fires_exactly_once(wired, flag_on, request):
    """The A3 decision gate, end to end through run_automation's default probe path."""
    a = upsert_automation(_automation(_uid(request),
                                      [Condition(kind="source_change", config={"table": "orders"})]))

    first = run_automation(a, now=NOW, dispatch=_dispatch_ok)
    assert first.outcome == "fired" and "first observation" in first.reason

    quiet = run_automation(a, now=NOW + timedelta(minutes=1), dispatch=_dispatch_ok)
    assert quiet.outcome == "not_fired"

    wired._con.execute("INSERT INTO orders VALUES (7, 70.0, TIMESTAMP '2026-07-21 08:00:00')")
    changed = run_automation(a, now=NOW + timedelta(minutes=2), dispatch=_dispatch_ok)
    assert changed.outcome == "fired" and "→" in changed.reason

    again = run_automation(a, now=NOW + timedelta(minutes=3), dispatch=_dispatch_ok)
    assert again.outcome == "not_fired", "the same change fired twice"


def test_a_change_seen_while_the_schedule_is_quiet_is_not_lost(wired, flag_on, request):
    """The no-lost-change property that dictates commit-on-fire. `all` logic: data lands while
    the schedule condition is false; when the schedule comes due, the change must still fire."""
    a = upsert_automation(_automation(
        _uid(request),
        [Condition(kind="schedule", config={"cron": "0 8 * * *"}),
         Condition(kind="source_change", config={"table": "orders"})],
        condition_logic="all"))

    t0 = NOW.replace(hour=8, minute=1)
    first = run_automation(a, now=t0, dispatch=_dispatch_ok)
    assert first.outcome == "fired"     # first run: both conditions first-fire

    wired._con.execute("INSERT INTO orders VALUES (8, 80.0, TIMESTAMP '2026-07-24 10:00:00')")

    midday = run_automation(a, now=t0 + timedelta(hours=4), dispatch=_dispatch_ok)
    assert midday.outcome == "not_fired"           # schedule quiet — and the change NOT consumed
    assert "source_change(orders)" not in midday.reason or "→" not in midday.reason

    next_morning = run_automation(a, now=t0 + timedelta(days=1), dispatch=_dispatch_ok)
    assert next_morning.outcome == "fired", "the change observed at midday was silently consumed"
    assert any("→" in d for d in next_morning.conditions_fired)


def test_flag_off_keeps_source_conditions_loudly_unwired(wired, monkeypatch, request):
    monkeypatch.setattr("aughor.kernel.flags.flag_enabled", lambda n: False)
    a = upsert_automation(_automation(_uid(request),
                                      [Condition(kind="source_change", config={"table": "orders"})]))
    run = run_automation(a, now=NOW, dispatch=_dispatch_ok)
    assert run.outcome == "error"
    assert "automations.source_probes" in run.error


def test_entity_appears_end_to_end(wired, flag_on, request):
    a = upsert_automation(_automation(_uid(request),
                                      [Condition(kind="entity_appears", config={"table": "orders"})]))
    run_automation(a, now=NOW, dispatch=_dispatch_ok)                      # baseline
    wired._con.execute("UPDATE orders SET updated_at = TIMESTAMP '2026-07-25 08:00:00'")
    touched = run_automation(a, now=NOW + timedelta(minutes=1), dispatch=_dispatch_ok)
    assert touched.outcome == "not_fired", "an update touch is not a new entity"
    wired._con.execute("INSERT INTO orders VALUES (11, 1.0, TIMESTAMP '2026-07-25 09:00:00')")
    appeared = run_automation(a, now=NOW + timedelta(minutes=2), dispatch=_dispatch_ok)
    assert appeared.outcome == "fired"


# ── store lifecycle ───────────────────────────────────────────────────────────────

def test_baseline_round_trip_and_overwrite():
    set_probe_baseline("auto-x", "orders", "n=1")
    set_probe_baseline("auto-x", "orders", "n=2")
    assert get_probe_baseline("auto-x", "orders") == "n=2"
    assert get_probe_baseline("auto-x", "other") is None


def test_delete_automation_clears_its_probe_state(request):
    a = upsert_automation(_automation(_uid(request),
                                      [Condition(kind="source_change", config={"table": "orders"})]))
    set_probe_baseline(a.id, "orders", "n=5")
    delete_automation(a.id)
    assert get_probe_baseline(a.id, "orders") is None


def test_purge_connection_clears_probe_state_too(request):
    cid = _uid(request)
    a = upsert_automation(_automation(cid,
                                      [Condition(kind="source_change", config={"table": "orders"})]))
    set_probe_baseline(a.id, "orders", "n=5")
    removed = purge_connection(cid)
    assert removed >= 2                       # the automation row + its probe row
    assert get_probe_baseline(a.id, "orders") is None
    assert get_runs(conn_id=cid) == []