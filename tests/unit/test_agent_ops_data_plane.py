"""W0 of the Agent Ops control room — the data plane the Overview cannot be honest without.

Three defects this wave exists to close, each measured on the live store 2026-08-17:

1. **`session_events.agent_id` was populated on 0 of 7,365 rows**, so no panel could say
   which agent spent what. It is not a bug — `agent_id` means "which CUSTOM agent asked"
   and platform work never activates one — but it left charter identity and model spend in
   two stores with no join. `charter_id`/`job_id` are that join.
2. **Every fold was row-windowed** (`scan=5000` = "the last N rows"), so a quiet week and a
   busy hour drew the same width, and the Overview showed two different time bases in one
   table. One resolved window now feeds everything.
3. **The automation engine's tick was counted as an agent** — 1,291 of 1,316 jobs in
   twenty-four hours — which made runs/min a heartbeat reading. Runners come back
   separately and are never summed into the agent totals.

Hermetic: every test builds its own Ledger under tmp_path. Nothing here may touch
`data/system.db`, which a live API holds open.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from aughor.kernel.ledger import Ledger
from aughor.obs.timeseries import (
    RUNNER_CHARTER_ID, bucket_edges, fold, is_runner, resolve_window,
)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


@pytest.fixture
def ledger(tmp_path):
    return Ledger(tmp_path / "system.db")


# ── the version-numbering trap ────────────────────────────────────────────────────

def test_attribution_migration_applies_to_a_store_already_at_version_9(tmp_path):
    """The defect a hermetic test cannot see, caught only by opening the real database.

    A version-9 migration adding `role`/`fallback` was applied to the live store by a
    parallel session whose code was later lost to a tree-wide revert. The store therefore
    sits at `user_version=9` while this file's history contains no migration 9 at all.

    `run_migrations` applies only versions ABOVE the current one. Numbering this wave's
    migration 9 would make it skip forever on every database that already holds data —
    `job_id`/`charter_id` would never be added, and because `_SESSION_EVENT_COLS` selects
    them, every read and write of the session log would fail on exactly the machines with
    something to lose. A fresh test database gets all the columns and reports nothing
    wrong, which is what makes this class of defect ship.
    """

    path = tmp_path / "already-at-9.db"
    led = Ledger(path)                                   # build the current schema
    del led
    c = sqlite3.connect(path)
    # Simulate the live store: the two v9 columns present, the version stamped, and this
    # wave's columns absent. Indexes go first — SQLite refuses to drop a column an index
    # still references, which is itself the live store's shape (it has session_events_role
    # from v9 and none of this wave's).
    for idx in ("session_events_job", "session_events_charter", "session_events_at"):
        c.execute(f"DROP INDEX IF EXISTS {idx}")
    for col in ("job_id", "charter_id"):
        c.execute(f"ALTER TABLE session_events DROP COLUMN {col}")
    c.execute("PRAGMA user_version = 9")
    c.commit()
    c.close()

    Ledger._instances.pop(str(path), None)               # force a real re-open
    led = Ledger(path)
    c = sqlite3.connect(path)
    cols = {r[1] for r in c.execute("PRAGMA table_info(session_events)")}
    assert {"job_id", "charter_id"} <= cols, (
        "the attribution migration was skipped on a store already at v9 — number it ABOVE "
        "the highest version any deployed database has reached")
    assert c.execute("PRAGMA user_version").fetchone()[0] >= 10
    # and the round trip still works on that store
    led.session_event_insert({"trace_id": "t", "kind": "llm_call", "charter_id": "curator"})
    assert led.session_events(charter_id="curator")


def test_migration_versions_are_unique_and_ordered():
    """Two migrations sharing a version means one of them silently never runs."""
    from aughor.kernel.ledger import _MIGRATIONS

    versions = [m.version for m in _MIGRATIONS]
    assert versions == sorted(versions), "migrations must be in ascending order"
    assert len(versions) == len(set(versions)), f"duplicate migration version in {versions}"


# ── run attribution: which agent spent this ───────────────────────────────────────

def test_migration_adds_run_attribution_columns_and_indexes(ledger):
    c = sqlite3.connect(ledger.path)
    cols = {r[1] for r in c.execute("PRAGMA table_info(session_events)")}
    assert {"job_id", "charter_id"} <= cols
    idx = {r[1] for r in c.execute("PRAGMA index_list(session_events)")}
    assert "session_events_charter" in idx
    assert "session_events_job" in idx
    assert "session_events_at" in idx, (
        "every panel is about to ask for a time window; `seq` is a cursor, not a clock")


def test_charter_and_job_survive_the_round_trip(ledger):
    ledger.session_event_insert({"trace_id": "t", "kind": "llm_call",
                                 "job_id": "job-1", "charter_id": "curator"})
    got = ledger.session_events()[0]
    assert got["job_id"] == "job-1" and got["charter_id"] == "curator"


def test_charter_filter_selects_only_that_agents_calls(ledger):
    for charter in ("curator", "curator", "scout"):
        ledger.session_event_insert({"trace_id": "t", "kind": "llm_call",
                                     "charter_id": charter})
    assert len(ledger.session_events(charter_id="curator")) == 2
    assert len(ledger.session_events(charter_id="scout")) == 1


def test_a_call_outside_any_run_is_unattributed_not_mislabelled(ledger):
    """An /ask turn answered inline belongs to a request, not to a background run."""
    ledger.session_event_insert({"trace_id": "t", "kind": "llm_call"})
    got = ledger.session_events()[0]
    assert got["job_id"] is None and got["charter_id"] is None


def test_a_real_job_run_stamps_its_charter_onto_emitted_events(tmp_path, monkeypatch):
    """The whole seam, through the real runner — not the contextvar in isolation.

    Verified against the live store after this shipped: `role` and `fallback` populated on
    735 of 735 new llm_calls, and `charter_id` on none of them — because every one came
    from an interactive /ask turn, and the only jobs that ran were automation ticks and
    profiles, neither of which calls a model. That is the designed answer, but "correct by
    explanation" is not proof, so this drives an actual job through `JobRunner._run` and
    reads what the sink received.
    """
    import asyncio

    from aughor.kernel.jobs import JobKernel, JobState
    from aughor.obs import session_log

    led = Ledger(tmp_path / "system.db")
    monkeypatch.setattr("aughor.kernel.ledger.Ledger.default", staticmethod(lambda: led))
    monkeypatch.setattr(session_log, "enabled", lambda: True)

    kernel = JobKernel(led)
    job_id = "job-under-test"
    led.job_insert({"id": job_id, "kind": "profile",       # profile → the Curator charter
                    "state": JobState.PENDING, "attempt": 1,
                    "created_at": _iso(datetime.now(timezone.utc))})

    async def _work():
        # Whatever an agent does inside a run — here, the one thing this test is about.
        session_log.emit("llm_call", name="probe", trace_id="t-probe", model="m",
                         provider="p", payload={"role": "coder", "fallback": False})

    asyncio.run(kernel._run(job_id, _work, None))

    rows = led.session_events(kind="llm_call")
    assert rows, "the run emitted nothing"
    got = rows[0]
    assert got["charter_id"] == "curator", (
        f"a profile run must stamp the Curator charter, got {got['charter_id']!r}")
    assert got["job_id"] == job_id
    assert got["role"] == "coder" and got["fallback"] is False


def test_run_attribution_reads_the_job_contextvar():
    """The write half: `run_attribution()` is what `emit` stamps from."""
    from aughor.kernel import jobs as jobs_mod

    assert jobs_mod.run_attribution() == ("", "")      # outside a run
    t1 = jobs_mod._current_job.set("job-9")
    t2 = jobs_mod._current_charter.set("analyst")
    try:
        assert jobs_mod.run_attribution() == ("job-9", "analyst")
    finally:
        jobs_mod._current_job.reset(t1)
        jobs_mod._current_charter.reset(t2)


# ── the drill filters: every ranked list is a door ────────────────────────────────

@pytest.mark.parametrize("field,value,other", [
    ("model", "gpt-5.4-nano", "gemini-3.1-flash-lite"),
    ("provider", "openrouter", "gemini"),
])
def test_drill_filters_select_exactly_their_rows(ledger, field, value, other):
    for v in (value, value, other):
        ledger.session_event_insert({"trace_id": "t", "kind": "llm_call", field: v})
    assert len(ledger.session_events(**{field: value})) == 2
    assert len(ledger.session_events(**{field: other})) == 1


def test_job_id_filter_reconstructs_one_run(ledger):
    ledger.session_event_insert({"trace_id": "t", "kind": "llm_call", "job_id": "a"})
    ledger.session_event_insert({"trace_id": "t", "kind": "llm_call", "job_id": "b"})
    assert [e["job_id"] for e in ledger.session_events(job_id="a")] == ["a"]


# ── the shared time axis ──────────────────────────────────────────────────────────

def test_named_ranges_pick_a_legible_number_of_buckets():
    """A 30-day window at minute resolution is 43,200 bars nobody can read or click."""
    for key in ("1h", "6h", "24h", "7d", "30d"):
        win = resolve_window(key)
        assert 10 <= win.bucket_count <= 32, f"{key} drew {win.bucket_count} buckets"
        assert len(bucket_edges(win)) == win.bucket_count


def test_an_unknown_range_falls_back_rather_than_raising():
    """A stale bookmark carrying ?range=90d should show a day, not an error page."""
    assert resolve_window("90d").range_key == "24h"


def test_explicit_bounds_choose_their_own_bucket_size():
    now = datetime.now(timezone.utc)
    win = resolve_window(since=_iso(now - timedelta(days=365)), until=_iso(now))
    assert win.bucket_count <= 200, "the bucket ladder must bound any span"


def test_index_of_places_a_row_and_rejects_one_outside():
    now = datetime.now(timezone.utc)
    win = resolve_window("24h", until=_iso(now))
    assert win.index_of(_iso(now - timedelta(minutes=30))) == win.bucket_count - 1
    assert win.index_of(_iso(now - timedelta(days=2))) is None, "before the window"
    assert win.index_of(_iso(now + timedelta(days=2))) is None, "after the window"
    assert win.index_of("not a timestamp") is None


def test_a_space_separated_timestamp_still_parses():
    """SQLite's datetime('now') renders a SPACE where ISO has a T, and because these
    comparisons are lexical a mixed one silently widens the window instead of erroring.
    That trap cost this program a measurement; the parser absorbs it."""
    now = datetime.now(timezone.utc)
    win = resolve_window("24h", until=_iso(now))
    spaced = _iso(now - timedelta(minutes=30)).replace("T", " ")
    assert win.index_of(spaced) == win.bucket_count - 1


def test_fold_drops_rows_outside_the_window_rather_than_clamping():
    """A clamped row makes the first bar of every chart a spike that is not real."""
    now = datetime.now(timezone.utc)
    win = resolve_window("1h", until=_iso(now))
    rows = [{"k": "a", "at": _iso(now - timedelta(minutes=5))},
            {"k": "a", "at": _iso(now - timedelta(days=3))}]
    series = fold(rows, win, key_of=lambda r: r["k"], at_of=lambda r: r["at"])
    assert len(series) == 1 and series[0].total == 1


def test_fold_sums_a_measure_not_only_rows():
    now = datetime.now(timezone.utc)
    win = resolve_window("1h", until=_iso(now))
    rows = [{"k": "m", "at": _iso(now - timedelta(minutes=5)), "t": 100},
            {"k": "m", "at": _iso(now - timedelta(minutes=6)), "t": 50}]
    series = fold(rows, win, key_of=lambda r: r["k"], at_of=lambda r: r["at"],
                  value_of=lambda r: r["t"])
    assert series[0].total == 150


# ── the window reaches the store ──────────────────────────────────────────────────

def test_session_events_window_is_half_open(ledger):
    base = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)
    for offset in (0, 30, 90):
        ledger.session_event_insert({"trace_id": "t", "kind": "llm_call",
                                     "at": _iso(base + timedelta(minutes=offset))})
    got = ledger.session_events(since=_iso(base), until=_iso(base + timedelta(minutes=90)))
    assert len(got) == 2, "since is inclusive, until is exclusive"


def test_jobs_window_and_kind_filters(ledger):
    base = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)
    c = sqlite3.connect(ledger.path)
    for i, kind in enumerate(("profile", "automation", "profile")):
        c.execute("INSERT INTO jobs (id, kind, state, created_at) VALUES (?,?,?,?)",
                  (f"j{i}", kind, "SUCCEEDED", _iso(base + timedelta(minutes=i * 30))))
    c.commit()
    c.close()
    led = Ledger(ledger.path)
    assert len(led.jobs_where(kinds=["profile"])) == 2
    assert len(led.jobs_where(since=_iso(base + timedelta(minutes=15)))) == 2
    assert len(led.jobs_where(since=_iso(base), until=_iso(base + timedelta(minutes=30)))) == 1


# ── runners are not agents ────────────────────────────────────────────────────────

def test_the_unclaimed_kind_is_a_runner():
    """`charter_for_kind` returns the _UNKNOWN charter for a kind nothing claims — the
    automation tick. That id is the whole basis of the agents/runners split."""
    from aughor.kernel.agents import charter_for_kind

    assert charter_for_kind("automation").id == RUNNER_CHARTER_ID
    assert is_runner(charter_for_kind("automation").id)
    assert not is_runner(charter_for_kind("profile").id), "profile belongs to Curator"


def test_runner_role_says_the_ticks_are_not_work():
    from aughor.routers.control_room import _runner_role

    text = _runner_role(["automation"], {"runs": 1291})
    assert "1,291" in text and "tick" in text.lower(), (
        "a row showing 1,291 runs must say they are ticks, or it reads as the busiest "
        "agent on the fleet")


def test_runner_gets_its_own_name_not_the_lookup_that_produced_it():
    from aughor.routers.control_room import _RUNNER_NAMES

    assert _RUNNER_NAMES["automation"] == "Automations"
    assert "Unassigned" not in "".join(_RUNNER_NAMES.values())


# ── prices come from the provider, never a hardcoded rate ─────────────────────────

def test_catalogue_prices_fill_in_where_nothing_is_declared(monkeypatch):
    from aughor.obs import usage

    monkeypatch.setattr(usage, "_CATALOGUE_PRICES", {}, raising=False)
    usage.price_for.cache_clear()
    assert usage.price_for("openrouter", "vendor/some-paid-model") is None

    monkeypatch.setattr("aughor.llm.models.list_models", lambda backend, refresh=False: {
        "models": [{"id": "vendor/some-paid-model", "price_in": 0.5, "price_out": 1.5}]})
    assert usage.refresh_catalogue_prices(backends=("openrouter",)) == 1
    price = usage.price_for("openrouter", "vendor/some-paid-model")
    assert price is not None and price.input_per_1m == 0.5 and price.output_per_1m == 1.5


def test_a_declared_price_outranks_the_catalogue(monkeypatch):
    """A rate somebody wrote down on a date is a deliberate claim; a fetched one is not."""
    from aughor.obs import usage

    monkeypatch.setattr("aughor.llm.models.list_models", lambda backend, refresh=False: {
        "models": [{"id": "vendor/thing:free", "price_in": 99.0, "price_out": 99.0}]})
    usage.refresh_catalogue_prices(backends=("openrouter",))
    assert usage.price_for("openrouter", "vendor/thing:free").input_per_1m == 0.0


def test_an_unreachable_catalogue_leaves_models_unpriced_rather_than_free(monkeypatch):
    from aughor.obs import usage

    def _boom(backend, refresh=False):
        raise RuntimeError("network down")

    monkeypatch.setattr("aughor.llm.models.list_models", _boom)
    assert usage.refresh_catalogue_prices(backends=("openrouter",)) == 0
    assert usage.price_for("openrouter", "vendor/never-seen") is None, (
        "unpriced, never a confident zero — a missing rate that rounds to free makes "
        "every aggregate above it quietly wrong")


def test_the_catalogue_converts_per_token_rates_to_per_million():
    """OpenRouter quotes USD per TOKEN as a string; every cost surface here is per 1M."""
    from aughor.llm.models import _openai_style_models


    class _Resp:
        @staticmethod
        def raise_for_status():
            return None

        @staticmethod
        def json():
            return {"data": [{"id": "m", "pricing": {"prompt": "0.0000005",
                                                     "completion": "0.0000015"}}]}

    import httpx

    original = httpx.get
    httpx.get = lambda *a, **k: _Resp()
    try:
        entry = _openai_style_models("http://x", "", timeout=1)[0]
    finally:
        httpx.get = original
    assert entry["price_in"] == pytest.approx(0.5)
    assert entry["price_out"] == pytest.approx(1.5)
