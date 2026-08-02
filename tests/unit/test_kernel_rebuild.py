"""Wave V2 — staleness-resolved rebuild: inputs AND logic, not a timer.

The pre-registered decision gate is two-sided and BOTH halves are asserted here:

* ``test_gate_cost_half``       — inputs unchanged + TTL lapsed ⇒ NO rebuild (cost saved).
* ``test_gate_correctness_half`` — inputs moved + TTL still valid ⇒ rebuild (wrong number
  avoided).

A PR that showed only the cost half would not have met the gate: making a cache lazier is
easy, and doing it without also making it *more* correct is how a resolved rebuild quietly
becomes a worse timer.
"""
from __future__ import annotations

import pytest

from aughor.kernel import rebuild as rb


@pytest.fixture(autouse=True)
def _isolated_store(monkeypatch, tmp_path):
    """The rebuild state store must never touch data/ (two real data-loss incidents)."""
    from aughor.util.json_store import KeyedJsonStore

    monkeypatch.setattr(rb, "_store", KeyedJsonStore(tmp_path / "rebuild_state.json",
                                                     max_entries=50))


def _probe(monkeypatch, version, how="1 table(s) probed"):
    """Stand in for the live source probe (hermetic: no DB, no connection)."""
    monkeypatch.setattr(rb, "inputs_version", lambda conn, tables=None: (version, how))


# ── The flag contract ─────────────────────────────────────────────────────────

def test_force_short_circuits_before_any_probe(monkeypatch):
    monkeypatch.setattr(rb, "inputs_version",
                        lambda *a, **k: pytest.fail("force must not probe"))
    d = rb.resolve("art", connection_id="c", force=True)
    assert (d.should_rebuild, d.reason) == (True, "forced")


# ── THE GATE ──────────────────────────────────────────────────────────────────

def test_gate_cost_half_ttl_lapsed_but_nothing_moved(monkeypatch):
    """The briefing's 2h TTL would rebuild here — an LLM call for an identical answer."""
    _probe(monkeypatch, "v1")
    first = rb.resolve("brief:c", connection_id="c", ttl_expired=False)
    assert first.should_rebuild is True and "first resolution" in first.reason
    rb.record("brief:c", first)

    later = rb.resolve("brief:c", connection_id="c", ttl_expired=True)   # timer says GO
    assert later.should_rebuild is False                                  # evidence says no
    assert later.staleness == "fresh"
    assert later.resolved is True
    assert later.saved_a_rebuild is True
    assert "TTL had lapsed but nothing moved" in later.reason


def test_gate_correctness_half_source_moved_inside_the_ttl(monkeypatch):
    """The TTL would serve this brief for up to two hours after the data changed."""
    _probe(monkeypatch, "v1")
    rb.record("brief:c", rb.resolve("brief:c", connection_id="c", ttl_expired=False))

    _probe(monkeypatch, "v2")                                            # source moved
    d = rb.resolve("brief:c", connection_id="c", ttl_expired=False)      # timer says SERVE
    assert d.should_rebuild is True                                      # evidence says go
    assert d.staleness == "stale"
    assert d.caught_a_stale_read is True
    assert "source data moved" in d.reason


def test_logic_change_rebuilds_even_when_the_source_is_identical(monkeypatch):
    """The other input: the producer's own version. Same data, new narrative shape."""
    _probe(monkeypatch, "v1")
    rb.record("brief:c", rb.resolve("brief:c", connection_id="c", logic="1"))

    d = rb.resolve("brief:c", connection_id="c", logic="2")
    assert d.should_rebuild is True
    assert "producer logic changed (1 → 2)" in d.reason


# ── Failing open, loudly ──────────────────────────────────────────────────────

@pytest.mark.parametrize("ttl_expired", [True, False])
def test_unversionable_inputs_fail_open_to_the_ttl(monkeypatch, ttl_expired):
    """A table with no change signal must not read as 'unchanged' — that would serve a
    stale artifact forever. Fall back to the timer and SAY so."""
    _probe(monkeypatch, None, how="no table could be versioned: t (no signal column)")

    d = rb.resolve("art", connection_id="c", ttl_expired=ttl_expired)
    assert d.should_rebuild is ttl_expired
    assert d.resolved is False
    assert d.staleness == "unknown"
    assert "failing open to the TTL decision" in d.reason
    assert d.saved_a_rebuild is False, "an unresolved decision must never claim a saving"


def test_probe_exception_fails_open_and_is_counted(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("warehouse down")

    monkeypatch.setattr(rb, "inputs_version", boom)
    d = rb.resolve("art", connection_id="c", ttl_expired=True)
    assert d.should_rebuild is True and d.resolved is False
    assert "probe raised RuntimeError" in d.reason


# ── record / forget semantics ─────────────────────────────────────────────────

def test_record_is_a_noop_without_a_resolved_version(monkeypatch):
    """Recording an unresolved decision would consume a change: the next check would
    compare against inputs whose output was never produced."""
    _probe(monkeypatch, None, how="unversionable")
    rb.record("art", rb.resolve("art", connection_id="c", ttl_expired=True))
    assert rb.last_built_as_of("art") == ""


def test_record_stamps_the_as_of_source_view(monkeypatch):
    _probe(monkeypatch, "v1")
    rb.record("art", rb.resolve("art", connection_id="c"), as_of="2026-07-26T00:00:00+00:00")
    assert rb.last_built_as_of("art") == "2026-07-26T00:00:00+00:00"


def test_forget_makes_the_next_check_rebuild(monkeypatch):
    _probe(monkeypatch, "v1")
    rb.record("art", rb.resolve("art", connection_id="c"))
    assert rb.resolve("art", connection_id="c").should_rebuild is False

    rb.forget("art")
    assert rb.resolve("art", connection_id="c").should_rebuild is True


# ── No silent caps ────────────────────────────────────────────────────────────

def test_probe_cap_is_reported_not_hidden(monkeypatch):
    """A bitten cap must name what it skipped — silent truncation reads as full coverage."""
    tables = [f"t{i}" for i in range(rb.MAX_PROBE_TABLES + 7)]
    monkeypatch.setattr(rb, "source_tables_for", lambda conn, db: tables)
    monkeypatch.setattr("aughor.automations.probes.current_version",
                        lambda conn, db, t, **k: (f"n=1|id={t}", "row count"))

    class _DB:
        def close(self):
            pass

    monkeypatch.setattr("aughor.db.connection.open_connection_for", lambda c: _DB())

    version, how = rb.inputs_version("c")
    assert version and f"7 skipped (cap {rb.MAX_PROBE_TABLES})" in how


def test_partial_coverage_is_reported(monkeypatch):
    """Some tables versionable, some not: usable signal, but say what you cannot see."""
    monkeypatch.setattr(rb, "source_tables_for", lambda conn, db: ["a", "b"])
    monkeypatch.setattr(
        "aughor.automations.probes.current_version",
        lambda conn, db, t, **k: (("n=1", "row count") if t == "a" else (None, "no signal")),
    )

    class _DB:
        def close(self):
            pass

    monkeypatch.setattr("aughor.db.connection.open_connection_for", lambda c: _DB())

    version, how = rb.inputs_version("c")
    assert version and "1 unversionable" in how


def test_no_versionable_table_yields_none_not_a_hash_of_nothing(monkeypatch):
    monkeypatch.setattr(rb, "source_tables_for", lambda conn, db: ["a"])
    monkeypatch.setattr("aughor.automations.probes.current_version",
                        lambda conn, db, t, **k: (None, "no signal column"))

    class _DB:
        def close(self):
            pass

    monkeypatch.setattr("aughor.db.connection.open_connection_for", lambda c: _DB())

    version, how = rb.inputs_version("c")
    assert version is None and "no table could be versioned" in how


def test_no_tables_known_is_unresolvable(monkeypatch):
    monkeypatch.setattr(rb, "source_tables_for", lambda conn, db: [])

    class _DB:
        def close(self):
            pass

    monkeypatch.setattr("aughor.db.connection.open_connection_for", lambda c: _DB())
    assert rb.inputs_version("c")[0] is None


# ── The briefing integration ──────────────────────────────────────────────────

def test_briefing_serves_a_ttl_expired_brief_when_nothing_moved(monkeypatch):
    """The cost half, through the real briefing entry point."""
    from aughor.knowledge import briefing

    _probe(monkeypatch, "v1")
    stale = {"generated_at": "2020-01-01T00:00:00+00:00"}

    needs, decision = briefing._brief_rebuild_decision("k", "c", stale)
    assert needs is True and decision.reason.startswith("first resolution")
    rb.record("brief:k", decision)

    needs, decision = briefing._brief_rebuild_decision("k", "c", stale)
    assert needs is False and decision.saved_a_rebuild is True


def test_briefing_logic_version_is_registered_in_the_v1_inventory():
    """V1's ratchet enforces this; asserting it here documents the coupling."""
    from aughor.kernel.freshness import logic_versions

    assert "briefing" in logic_versions()
