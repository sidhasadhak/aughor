"""B-6 — time-to-first-insight instrumentation + the Phase-7 built-not-wired fix.

The explorer used to emit a live `exploration.insight` event (and write a K3
Trust-Receipt artifact) ONLY for Phase-8 domain-intel findings. Phase-7
cross-table insights bumped the counters but emitted nothing, so the *earliest*
findings never surfaced live — defeating "first findings surface while later
phases run". Both phases now route through `_emit_insight`, which also stamps the
time-to-first-insight milestone (`exploration.first_insight`).
"""
from datetime import datetime, timedelta, timezone


from aughor.explorer.agent import SchemaExplorer
from aughor.explorer.models import ExplorationPhase, ExplorationStatus, elapsed_seconds


class _StubLedger:
    """Captures artifact_write calls instead of touching data/system.db."""
    def __init__(self):
        self.artifacts = []

    def artifact_write(self, kind, natural_key, payload, **kw):
        self.artifacts.append((kind, natural_key, payload, kw))


def _explorer(monkeypatch, started_at=None):
    """A SchemaExplorer with just the attributes the emit path needs — no DB."""
    import aughor.kernel.ledger as ledger_mod
    stub = _StubLedger()
    monkeypatch.setattr(ledger_mod.Ledger, "default", classmethod(lambda cls: stub))

    ex = object.__new__(SchemaExplorer)
    ex.connection_id = "conn_test"
    ex.canvas_id = None
    ex._status = ExplorationStatus(
        connection_id="conn_test",
        started_at=started_at or datetime.now(timezone.utc).isoformat(),
    )
    ex._status.phase = ExplorationPhase.CROSS_TABLE
    ex._state = {}
    ex._journal_calls = []
    ex._journal = lambda kind, payload=None: ex._journal_calls.append((kind, payload or {}))
    ex._ledger_stub = stub
    return ex


def _insight(i):
    return {"id": f"i{i}", "finding": f"finding number {i}", "sql": "SELECT 1 FROM orders"}


# ── elapsed_seconds (pure) ───────────────────────────────────────────────────

def test_elapsed_seconds_basic():
    a = "2026-06-12T10:00:00+00:00"
    b = "2026-06-12T10:00:47+00:00"
    assert elapsed_seconds(a, b) == 47.0


def test_elapsed_seconds_missing_or_bad():
    assert elapsed_seconds(None, "2026-06-12T10:00:00+00:00") is None
    assert elapsed_seconds("2026-06-12T10:00:00+00:00", None) is None
    assert elapsed_seconds("not-a-date", "2026-06-12T10:00:00+00:00") is None


# ── milestone: stamped once, elapsed measured ─────────────────────────────────

def test_first_insight_stamped_with_elapsed(monkeypatch):
    started = (datetime.now(timezone.utc) - timedelta(seconds=12)).isoformat()
    ex = _explorer(monkeypatch, started_at=started)

    ex._emit_insight(_insight(1), "SELECT 1 FROM orders", journal_extra={"phase": "cross_table"})

    assert ex._status.first_insight_at is not None
    assert ex._state["first_insight_at"] == ex._status.first_insight_at
    milestones = [p for k, p in ex._journal_calls if k == "exploration.first_insight"]
    assert len(milestones) == 1
    assert milestones[0]["elapsed_seconds"] >= 11.0  # ~12s, allow jitter
    assert milestones[0]["phase"] == "cross_table"


def test_first_insight_stamped_only_once(monkeypatch):
    ex = _explorer(monkeypatch)
    ex._emit_insight(_insight(1), "SELECT 1 FROM orders")
    first_stamp = ex._status.first_insight_at
    ex._emit_insight(_insight(2), "SELECT 1 FROM orders")
    ex._emit_insight(_insight(3), "SELECT 1 FROM orders")

    assert ex._status.first_insight_at == first_stamp                      # not re-stamped
    milestones = [k for k, _ in ex._journal_calls if k == "exploration.first_insight"]
    assert len(milestones) == 1                                            # emitted once
    assert ex._status.insights_found == 3                                  # but all counted


def test_resumed_run_does_not_restamp(monkeypatch):
    """A restart restores first_insight_at from state; the next insight must not
    re-stamp or re-emit the milestone."""
    ex = _explorer(monkeypatch)
    prior = "2026-06-12T09:00:00+00:00"
    ex._status.first_insight_at = prior   # simulate constructor restoring from _state

    ex._emit_insight(_insight(9), "SELECT 1 FROM orders")

    assert ex._status.first_insight_at == prior
    assert not [k for k, _ in ex._journal_calls if k == "exploration.first_insight"]


# ── the built-not-wired fix: every insight now fires a live event + artifact ───

def test_emit_insight_fires_live_event_and_artifact(monkeypatch):
    ex = _explorer(monkeypatch)
    ex._emit_insight(_insight(1), "SELECT x FROM orders JOIN customers USING (id)",
                     journal_extra={"phase": "cross_table"})

    live = [p for k, p in ex._journal_calls if k == "exploration.insight"]
    assert len(live) == 1
    assert live[0]["insight_id"] == "i1"
    assert live[0]["phase"] == "cross_table"          # journal_extra merged
    assert "finding number 1" in live[0]["finding"]

    # K3 Trust-Receipt artifact written, with table lineage from the SQL
    assert len(ex._ledger_stub.artifacts) == 1
    kind, key, payload, kw = ex._ledger_stub.artifacts[0]
    assert kind == "finding"
    assert key == "insight:conn_test:i1"
    lineage = kw.get("lineage") or []
    tables = {v.split(":", 1)[1] for (etype, v, _src) in lineage if etype == "input"}
    assert {"orders", "customers"} <= tables


def test_phase8_journal_extra_carries_domain(monkeypatch):
    ex = _explorer(monkeypatch)
    ex._emit_insight(_insight(5), "SELECT 1 FROM orders", journal_extra={"domain": "revenue"})
    live = [p for k, p in ex._journal_calls if k == "exploration.insight"]
    assert live[0]["domain"] == "revenue"


# ── status surfaces the KPI fields ────────────────────────────────────────────

def test_status_to_dict_exposes_ttfi():
    s = ExplorationStatus(
        connection_id="c",
        started_at="2026-06-12T10:00:00+00:00",
        first_insight_at="2026-06-12T10:00:30+00:00",
    )
    d = s.to_dict()
    assert d["first_insight_at"] == "2026-06-12T10:00:30+00:00"
    assert d["first_insight_seconds"] == 30.0


def test_status_to_dict_ttfi_none_before_first_insight():
    s = ExplorationStatus(connection_id="c", started_at="2026-06-12T10:00:00+00:00")
    d = s.to_dict()
    assert d["first_insight_at"] is None
    assert d["first_insight_seconds"] is None


# ── KPI aggregate endpoint ────────────────────────────────────────────────────

def _kpi_with_durations(monkeypatch, durations):
    import aughor.kernel.ledger as ledger_mod
    from aughor.routers.exploration import time_to_first_insight_kpi

    events = [
        {"conn_id": f"c{i}", "at": "2026-06-12T10:00:00", "payload": {"elapsed_seconds": d, "phase": "domain_intel"}}
        for i, d in enumerate(durations)
    ]

    class _L:
        def events(self, **kw):
            assert kw.get("kind") == "exploration.first_insight"
            return events

    monkeypatch.setattr(ledger_mod.Ledger, "default", classmethod(lambda cls: _L()))
    return time_to_first_insight_kpi()


def test_kpi_percentiles(monkeypatch):
    out = _kpi_with_durations(monkeypatch, [10, 20, 30, 40, 100])
    assert out["count"] == 5
    assert out["min_seconds"] == 10
    assert out["max_seconds"] == 100
    assert out["p50_seconds"] == 30   # median of sorted [10,20,30,40,100]
    assert out["p90_seconds"] == 100


def test_kpi_empty(monkeypatch):
    out = _kpi_with_durations(monkeypatch, [])
    assert out["count"] == 0
    assert out["p50_seconds"] is None
    assert out["p90_seconds"] is None


def test_kpi_ignores_null_elapsed(monkeypatch):
    out = _kpi_with_durations(monkeypatch, [15.0, None, 25.0])
    assert out["count"] == 2           # the None sample is excluded from the distribution
    assert out["min_seconds"] == 15.0
    assert len(out["samples"]) == 3    # but still surfaced in the raw sample list
