"""Briefing on a serverless deployment — the three faults that kept it from running.

1. Brief subscriptions (and delivery triggers) lived in a JSON file under ``data/``,
   which a serverless bundle ships EMPTY and read-only: every instance read zero
   subscriptions (so each cron tick evaluated zero briefs, forever) and creating one
   failed on the write. The stores now ride the Ledger (`LedgerListStore`), which is
   Postgres behind ``AUGHOR_DB_URL`` on serverless — the file stays as legacy import
   and fallback.
2. The cron tick only ENQUEUED the delivery (kernel submit → asyncio task) and the
   instance froze at the response, so the work never ran — and its PENDING row then
   blocked the automation forever under the idempotency key. Under ``VERCEL`` the
   tick now runs the work inline, before responding.
3. ``sweep_stale`` only swept RUNNING, so a PENDING row from a frozen instance
   outlived every warm tick between cold boots. It now sweeps stale PENDING too.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from aughor.kernel.jobs import JobKernel, JobState
from aughor.kernel.ledger import Ledger
from aughor.util.json_store import LedgerListStore


def _iso(dt: datetime) -> str:
    return dt.isoformat()


# ── LedgerListStore — the list-shaped Ledger facade ───────────────────────────

def _led(tmp_path, monkeypatch) -> Ledger:
    led = Ledger(tmp_path / "system.db")
    monkeypatch.setattr("aughor.kernel.ledger.Ledger.default", staticmethod(lambda: led))
    return led


def test_rows_live_in_the_ledger_not_the_file(tmp_path, monkeypatch):
    """The write must not depend on the file being writable — on serverless it isn't."""
    _led(tmp_path, monkeypatch)
    path = tmp_path / "bundle" / "list.json"    # parent never created — like a RO bundle
    store = LedgerListStore(path)
    store.upsert({"id": "a", "v": 1})
    store.upsert({"id": "b", "v": 2})

    assert [r["id"] for r in store.all()] == ["a", "b"]
    assert store.get("a") == {"id": "a", "v": 1}
    assert not path.exists()                    # the file was never needed


def test_a_second_instance_sees_the_row(tmp_path, monkeypatch):
    """The serverless failure was per-instance state: a subscription created on one
    instance was invisible to the one running the cron. Two store objects over the
    same Ledger stand in for two instances."""
    _led(tmp_path, monkeypatch)
    LedgerListStore(tmp_path / "list.json").upsert({"id": "s1", "cadence": "daily"})
    other = LedgerListStore(tmp_path / "list.json")
    assert other.get("s1") == {"id": "s1", "cadence": "daily"}


def test_upsert_keeps_list_semantics(tmp_path, monkeypatch):
    """The file version removed-then-appended on upsert; the kv seq reproduces that."""
    _led(tmp_path, monkeypatch)
    store = LedgerListStore(tmp_path / "list.json")
    store.save_all([{"id": "a", "v": 1}, {"id": "b", "v": 1}])
    store.upsert({"id": "a", "v": 2})
    assert [r["id"] for r in store.all()] == ["b", "a"]
    assert store.delete("b") is True
    assert store.delete("b") is False
    assert [r["id"] for r in store.all()] == [{"id": "a", "v": 2}["id"]]


def test_legacy_file_imports_once(tmp_path, monkeypatch):
    """A deployment that had file rows keeps them: imported on first touch, and the
    file is not re-read after (deleting it changes nothing)."""
    _led(tmp_path, monkeypatch)
    path = tmp_path / "list.json"
    path.write_text('[{"id": "old", "v": 1}]')
    store = LedgerListStore(path)
    assert [r["id"] for r in store.all()] == ["old"]
    path.unlink()
    assert [r["id"] for r in store.all()] == ["old"]


def test_falls_back_to_the_file_when_the_ledger_is_down(tmp_path, monkeypatch):
    def _boom():
        raise RuntimeError("ledger unavailable")
    monkeypatch.setattr("aughor.kernel.ledger.Ledger.default", staticmethod(_boom))
    store = LedgerListStore(tmp_path / "list.json")
    store.upsert({"id": "a", "v": 1})
    assert [r["id"] for r in store.all()] == ["a"]
    assert (tmp_path / "list.json").exists()    # the original file behaviour


# ── The brief-subscription store rides it ─────────────────────────────────────

def test_brief_subscriptions_survive_without_their_file(tmp_path, monkeypatch):
    _led(tmp_path, monkeypatch)
    from aughor.briefing import store as briefs
    from aughor.briefing.models import BriefSubscription

    fresh = LedgerListStore(tmp_path / "subs.json")
    monkeypatch.setattr(briefs, "_store", fresh)

    sub = briefs.save_subscription(
        BriefSubscription(name="Daily brief", conn_id="c1", trigger_id="t1"))
    assert sub.id
    assert not (tmp_path / "subs.json").exists()
    assert [s.id for s in briefs.list_subscriptions()] == [sub.id]
    assert briefs.get_subscription(sub.id) is not None
    assert briefs.delete_subscription(sub.id) is True
    assert briefs.list_subscriptions() == []


# ── The cron tick delivers before it responds ─────────────────────────────────

def test_run_one_is_inline_under_vercel(monkeypatch):
    """On serverless the tick must FINISH the work, not enqueue it: the instance
    freezes at the response, and an enqueued PENDING job both never runs and wedges
    the idempotency key. The kernel offer is skipped entirely."""
    from aughor.automations import scheduler as auto_sched
    from aughor.kernel import jobs as jobs_mod

    class _A:
        id, name, conn_id, enabled = "brief:s1", "B", "c1", True

    calls = {"submit": 0, "run": 0}
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setattr("aughor.db.registry.get_connection_org",
                        lambda cid: "default", raising=False)
    monkeypatch.setattr("aughor.automations.engine.run_automation",
                        lambda a, **k: calls.__setitem__("run", calls["run"] + 1),
                        raising=False)
    monkeypatch.setattr(jobs_mod, "submit_background_tick",
                        lambda *a, **k: (calls.__setitem__("submit", calls["submit"] + 1),
                                         "job1")[1])

    auto_sched._run_one(_A())
    assert calls["run"] == 1        # the delivery ran, inside the tick
    assert calls["submit"] == 0     # the kernel was never offered the work


def test_run_one_still_offers_the_kernel_off_vercel(monkeypatch):
    from aughor.automations import scheduler as auto_sched
    from aughor.kernel import jobs as jobs_mod

    class _A:
        id, name, conn_id, enabled = "brief:s1", "B", "c1", True

    calls = {"submit": 0, "run": 0}
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.setattr("aughor.db.registry.get_connection_org",
                        lambda cid: "default", raising=False)
    monkeypatch.setattr("aughor.automations.engine.run_automation",
                        lambda a, **k: calls.__setitem__("run", calls["run"] + 1),
                        raising=False)
    monkeypatch.setattr(jobs_mod, "submit_background_tick",
                        lambda *a, **k: (calls.__setitem__("submit", calls["submit"] + 1),
                                         "job1")[1])

    auto_sched._run_one(_A())
    assert calls["submit"] == 1 and calls["run"] == 0


# ── The sweep un-wedges a frozen PENDING row ──────────────────────────────────

def test_sweep_stale_fails_an_orphaned_pending_job(tmp_path, monkeypatch):
    led = _led(tmp_path, monkeypatch)
    kernel = JobKernel(led)
    old = _iso(datetime.now(timezone.utc) - timedelta(hours=2))
    led.job_insert({"id": "wedged", "kind": "automation", "state": JobState.PENDING,
                    "attempt": 1, "created_at": old,
                    "idempotency_key": "automation:brief:s1"})

    assert kernel.sweep_stale() == 1
    row = led.jobs_where(limit=10)[0]
    assert row["id"] == "wedged" and row["state"] == JobState.INTERRUPTED
    # The key is free again — the next tick can submit this automation.
    assert not led.jobs_where(states=list(JobState.ACTIVE),
                              idempotency_key="automation:brief:s1", limit=1)


def test_sweep_stale_leaves_a_fresh_pending_job_alone(tmp_path, monkeypatch):
    led = _led(tmp_path, monkeypatch)
    kernel = JobKernel(led)
    led.job_insert({"id": "queued", "kind": "automation", "state": JobState.PENDING,
                    "attempt": 1, "created_at": _iso(datetime.now(timezone.utc))})
    assert kernel.sweep_stale() == 0
    assert led.jobs_where(limit=10)[0]["state"] == JobState.PENDING
