"""Journal retention — the `events` table's age window, row cap and batch bound.

The journal shipped with no retention at all. Measured on the live install 2026-09-19:
430,768 rows back to 2026-06-16, growing 23,287/day, in a `system.db` of 247 MB whose
freelist was zero. The cost was not disk. `AughorOpsConnection` snapshots the NEWEST
100,000 rows per curated table, so anything that will not fit under that cap is not
merely old — it cannot be queried by the platform's own self-investigation surface at
all. On that date the oldest visible event was five days back: 76.8% of the history was
invisible, and 99.1% of a week's writes were `job.state` and `automation.run` chatter
from automations that ticked 30,470 times and fired 198.

So the sweep is SCOPED, and these tests are mostly about what it must NOT delete. A
retention bug that removes evidence looks exactly like a retention feature working.
"""
from datetime import datetime, timedelta, timezone

import pytest

from aughor.kernel import ledger as ledger_mod
from aughor.kernel.ledger import Ledger


@pytest.fixture()
def led(tmp_path):
    return Ledger(tmp_path / "system.db")


def _at(days_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def _insert(led: Ledger, kind: str, days_ago: float, n: int = 1) -> None:
    """Backdated rows. `emit` stamps `at` itself, so a retention test that needs an age
    has to write the column directly — the same thing a back-fill or an import does."""
    with led._lock, led._conn:
        for _ in range(n):
            led._conn.execute(
                "INSERT INTO events (at, kind, conn_id, canvas_id, job_id, payload, "
                "trace_id, org_id) VALUES (?,?,?,?,?,?,?,?)",
                (_at(days_ago), kind, None, None, None, None, "", "default"))


def _kinds(led: Ledger) -> dict:
    rows = led._conn.execute("SELECT kind, count(*) FROM events GROUP BY kind").fetchall()
    return {r[0]: r[1] for r in rows}


# ── what the sweep must not touch ────────────────────────────────────────────

class TestScope:
    def test_a_semantic_kind_survives_however_old(self, led):
        """The whole design: `events` has no pin, so the exemption is the default. A
        90-day-old investigation record is history, not chatter."""
        _insert(led, "investigation.created", days_ago=90)
        _insert(led, "investigation.completed", days_ago=365)
        _insert(led, "job.state", days_ago=90)

        led.events_prune(keep_days=2, max_rows=0)

        surviving = _kinds(led)
        assert surviving.get("investigation.created") == 1
        assert surviving.get("investigation.completed") == 1
        assert "job.state" not in surviving

    def test_only_the_named_kinds_are_swept(self, led):
        """Mutation guard: widening the sweep to every kind, or defaulting the kind list
        to empty-means-all, both pass a test that only counts total rows. Name the
        survivor."""
        for kind in ("agent.handoff", "ontology.build", "error.tolerated",
                     "playbook.use", "node.span"):
            _insert(led, kind, days_ago=60)
        _insert(led, "automation.run", days_ago=60)

        deleted = led.events_prune(keep_days=1, max_rows=0, kinds=("automation.run",))

        assert deleted == 1
        surviving = _kinds(led)
        assert "automation.run" not in surviving
        for kind in ("agent.handoff", "ontology.build", "error.tolerated",
                     "playbook.use", "node.span"):
            assert surviving.get(kind) == 1, f"{kind} was swept and must not be"

    def test_an_empty_kind_list_disables_the_sweep_entirely(self, led):
        _insert(led, "job.state", days_ago=90, n=5)
        assert led.events_prune(keep_days=1, max_rows=1, kinds=()) == 0
        assert _kinds(led).get("job.state") == 5

    def test_env_can_disable_the_sweep(self, led, monkeypatch):
        monkeypatch.setenv("AUGHOR_EVENTS_PRUNE_KINDS", "")
        _insert(led, "job.state", days_ago=90, n=5)
        assert led.events_prune() == 0
        assert _kinds(led).get("job.state") == 5

    def test_env_names_the_kinds(self, led, monkeypatch):
        monkeypatch.setenv("AUGHOR_EVENTS_PRUNE_KINDS", "node.span")
        monkeypatch.setenv("AUGHOR_EVENTS_OPS_KEEP_DAYS", "1")
        monkeypatch.setenv("AUGHOR_EVENTS_OPS_MAX_ROWS", "0")
        _insert(led, "node.span", days_ago=90)
        _insert(led, "job.state", days_ago=90)

        led.events_prune()

        surviving = _kinds(led)
        assert "node.span" not in surviving
        # job.state is the DEFAULT sweep kind — naming node.span must replace the
        # default list, not extend it.
        assert surviving.get("job.state") == 1


# ── the age window ───────────────────────────────────────────────────────────

class TestAgeWindow:
    def test_deletes_past_the_cutoff_and_keeps_inside_it(self, led):
        _insert(led, "job.state", days_ago=5, n=3)
        _insert(led, "job.state", days_ago=0.5, n=4)

        deleted = led.events_prune(keep_days=2, max_rows=0)

        assert deleted == 3
        assert _kinds(led).get("job.state") == 4

    def test_zero_disables_the_age_half(self, led):
        _insert(led, "job.state", days_ago=90, n=3)
        assert led.events_prune(keep_days=0, max_rows=0) == 0
        assert _kinds(led).get("job.state") == 3


# ── the row cap ──────────────────────────────────────────────────────────────

class TestRowCap:
    def test_keeps_the_newest_n_of_the_swept_kinds(self, led):
        _insert(led, "job.state", days_ago=0.1, n=10)

        deleted = led.events_prune(keep_days=0, max_rows=4)

        assert deleted == 6
        assert _kinds(led).get("job.state") == 4

    def test_the_cap_counts_only_swept_kinds(self, led):
        """A cap that counted every row would let evidence consume the chatter's budget:
        the threshold probe would land among the semantic rows and carry every swept row
        below it away, cap or no cap.

        ORDER MATTERS, and getting it wrong is how this test first passed for the wrong
        reason. The chatter is written FIRST so the semantic rows are the newest — with
        the chatter newest, an unscoped probe lands on a chatter row and deletes exactly
        what the scoped one does, and the mutation survives."""
        _insert(led, "job.state", days_ago=0.1, n=10)
        _insert(led, "investigation.created", days_ago=0.1, n=50)

        led.events_prune(keep_days=0, max_rows=4)

        surviving = _kinds(led)
        assert surviving.get("investigation.created") == 50
        assert surviving.get("job.state") == 4

    def test_cap_is_a_no_op_below_the_threshold(self, led):
        _insert(led, "job.state", days_ago=0.1, n=3)
        assert led.events_prune(keep_days=0, max_rows=100) == 0
        assert _kinds(led).get("job.state") == 3


# ── the batch bound, and the stamp that depends on it ────────────────────────

class TestBatchBound:
    def test_a_sweep_never_exceeds_its_batch(self, led):
        """The sweep runs inside `Ledger.__init__`. An unbounded first DELETE against a
        backlog is a boot-time stall, and work that raised in `__init__` has already
        cost this store a no-boot once (Migration 10)."""
        _insert(led, "job.state", days_ago=90, n=25)

        deleted = led.events_prune(keep_days=1, max_rows=0, batch=10)

        assert deleted == 10
        assert _kinds(led).get("job.state") == 15

    def test_successive_sweeps_drain_the_backlog(self, led):
        _insert(led, "job.state", days_ago=90, n=25)
        for _ in range(3):
            led.events_prune(keep_days=1, max_rows=0, batch=10)
        assert "job.state" not in _kinds(led)

    def test_a_full_batch_is_not_stamped_so_it_retries(self, led, monkeypatch):
        """If a bounded sweep stamped its clock, the backlog would drain at one batch per
        six hours. A full batch means "come back immediately".

        The stamp is cleared first and deliberately: opening the Ledger already runs one
        sweep against an empty table, which stamps. Without the clear, this asserts the
        constructor's stamp rather than this sweep's — and its sibling below would pass
        no matter what the production code did."""
        monkeypatch.setattr(ledger_mod, "_EVENT_PRUNE_BATCH", 5)
        led.kv_delete(ledger_mod._PRUNE_KV_STORE, ledger_mod._EVENT_PRUNE_KV_KEY)
        _insert(led, "job.state", days_ago=90, n=20)

        led._prune_events_and_stamp()

        assert led.kv_get(ledger_mod._PRUNE_KV_STORE,
                          ledger_mod._EVENT_PRUNE_KV_KEY) is None

    def test_a_short_sweep_is_stamped(self, led, monkeypatch):
        monkeypatch.setattr(ledger_mod, "_EVENT_PRUNE_BATCH", 100)
        led.kv_delete(ledger_mod._PRUNE_KV_STORE, ledger_mod._EVENT_PRUNE_KV_KEY)
        _insert(led, "job.state", days_ago=90, n=3)

        led._prune_events_and_stamp()

        assert led.kv_get(ledger_mod._PRUNE_KV_STORE,
                          ledger_mod._EVENT_PRUNE_KV_KEY) is not None

    def test_opening_the_ledger_sweeps_the_journal(self, led, tmp_path):
        """The restart insurance, which is the half the session log had to learn twice:
        a counter that starts at zero every boot is retention only on a long-lived
        process."""
        _insert(led, "job.state", days_ago=90, n=4)
        led.kv_delete(ledger_mod._PRUNE_KV_STORE, ledger_mod._EVENT_PRUNE_KV_KEY)
        led._conn.commit()

        reopened = Ledger(tmp_path / "system.db")

        assert "job.state" not in _kinds(reopened)

    def test_the_two_stamps_are_distinct_keys(self):
        """One clock for both sweeps would let a recent session-log prune suppress the
        journal's, which is the bug `_prune_if_overdue_at_open` is guarded against."""
        assert ledger_mod._EVENT_PRUNE_KV_KEY != ledger_mod._PRUNE_KV_KEY


# ── the amortised path ───────────────────────────────────────────────────────

class TestAmortisedSweep:
    def test_emit_drives_the_counter_and_fires_on_the_boundary(self, led, monkeypatch):
        """Hung off `emit`, not off the session-log counter: the journal takes ~50× the
        writes, and a sweep driven by session writes would fire about once a day."""
        monkeypatch.setattr(ledger_mod, "_EVENT_PRUNE_EVERY", 5)
        fired = []
        monkeypatch.setattr(Ledger, "_prune_events_and_stamp",
                            lambda self: fired.append(1))

        for _ in range(4):
            led.emit("node.span")
        assert fired == []

        led.emit("node.span")
        assert len(fired) == 1

    def test_a_failing_sweep_never_breaks_the_write(self, led, monkeypatch):
        def boom(self, **kw):
            raise RuntimeError("disk on fire")
        monkeypatch.setattr(Ledger, "events_prune", boom)
        monkeypatch.setattr(ledger_mod, "_EVENT_PRUNE_EVERY", 1)

        seq = led.emit("node.span", {"x": 1})

        assert seq > 0
        assert _kinds(led).get("node.span") == 1


# ── Migration 12 ─────────────────────────────────────────────────────────────

class TestIndexes:
    def test_the_journal_carries_its_correlation_and_retention_indexes(self, led):
        """`trace_id` was added by Migration 6 with a DEFAULT '' and no index, so the
        question it was added to answer has been a full scan for its whole life."""
        names = {r[0] for r in led._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='events'"
        ).fetchall()}
        assert {"events_trace", "events_kind_at", "events_at"} <= names

    def test_the_sweep_predicate_uses_an_index(self, led):
        _insert(led, "job.state", days_ago=5, n=3)
        plan = " ".join(str(r) for r in led._conn.execute(
            "EXPLAIN QUERY PLAN SELECT seq FROM events WHERE kind IN ('job.state') "
            "AND at < ? ORDER BY seq ASC LIMIT 10", (_at(2),)).fetchall())
        assert "SCAN" not in plan.upper() or "INDEX" in plan.upper(), plan
