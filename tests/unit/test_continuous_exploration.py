"""The continuous loop — the Explorer's three jobs on their own triggers (exploration principles §2, 2026-10-08).

WP-6 re-armed a connection on a schema change or a week's staleness. Measured 2026-10-07 it had
re-armed nothing since 2026-09-26: it read each connection's FIRST dataset only, never retried a
failure, and every run walked every phase and spent the whole curiosity loop. These pin the per-dataset
decision (pure), the planner, the tick's start and receipt, and the governance skip.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import aughor.explorer.continuous as cont
from aughor.explorer.models import ExplorationPhase

_NOW = datetime(2026, 7, 12, tzinfo=timezone.utc)
ASKS = frozenset({"structure", "questions", "time"})
STRUCTURE = frozenset({"structure"})


def _complete(fp="abc", **kw) -> dict:
    return {"phase": ExplorationPhase.COMPLETE.value, "dataset_fingerprint": fp, "tables_total": 3,
            "structure_learned": {"at": "2026-07-01T00:00:00+00:00", "fp": fp}, **kw}


def _prog(*runs, **kw) -> dict:
    return {"runs": list(runs), "reopened": None, "watch": {}, "failures": 0, "next_retry_at": None, **kw}


def _ran(job="questions", new=5, ended=_NOW - timedelta(days=2)) -> dict:
    return {"job": job, "outcome": "complete", "new_findings": new, "ended_at": ended.isoformat()}


def _decide(state, prog=None, *, jobs=ASKS, fp="abc", running=False, interrupted=False, share=0.2):
    return cont.next_job(state, prog or _prog(_ran()), jobs=jobs, current_fp=fp, running=running,
                         interrupted=interrupted, now=_NOW, questions_share=share)


# ── the per-dataset decision ──────────────────────────────────────────────────

def test_a_new_dataset_learns_its_structure_and_asks_only_when_its_layer_does():
    assert _decide({"phase": "pending"}, _prog(), jobs=STRUCTURE) == {
        "job": "structure", "reason": cont.NEW_DATASET, "gaps_only": True, "uses_model": False}
    asked = _decide({"phase": "pending"}, _prog())
    assert asked["job"] == "full" and asked["gaps_only"] is False and asked["uses_model"]


def test_nothing_runs_for_a_running_dataset_or_one_whose_layer_runs_nothing():
    assert _decide(_complete(), running=True) is None
    assert _decide(_complete(), jobs=frozenset()) is None


def test_a_schema_change_learns_the_new_parts_and_fills_only_the_gaps():
    plan = _decide(_complete("old"), fp="new")
    assert plan["job"] == "full" and plan["reason"] == cont.SCHEMA_CHANGED and plan["gaps_only"] is True
    assert _decide(_complete("old"), fp="new", jobs=STRUCTURE)["job"] == "structure"
    # an unknown fingerprint on either side is never read as a change
    assert _decide(_complete(None), fp="new", share=0.9) is None
    assert _decide(_complete("old"), fp=None, share=0.9) is None


def test_a_mature_dataset_is_only_watched_until_a_named_event_reopens_it():
    assert _decide(_complete(), share=0.85) is None
    reopened = _decide(_complete(), _prog(_ran(), reopened={"at": "x", "reason": "AOV was approved"}), share=0.85)
    assert reopened["job"] == "questions" and reopened["gaps_only"] is False and reopened["take_reopen"]
    assert "AOV was approved" in reopened["reason"]


def test_questions_are_asked_at_most_daily_and_only_their_gaps():
    recent = _prog(_ran(ended=_NOW - timedelta(hours=3)))
    assert _decide(_complete(), recent) is None
    plan = _decide(_complete(), _prog(_ran(ended=_NOW - timedelta(days=2))))
    assert plan == {"job": "questions", "reason": cont.GAPS, "gaps_only": True, "uses_model": True}


def test_a_layer_just_set_asks_its_first_questions_with_the_curiosity_loop():
    structure_only = _complete(domain_intel_skipped=True)
    plan = _decide(structure_only, _prog({"job": "structure", "outcome": "complete", "new_findings": 0,
                                          "ended_at": _NOW.isoformat()}))
    assert plan["reason"] == cont.FIRST_QUESTIONS and plan["gaps_only"] is False


_BUDGET_STOP = "cancelled (time budget (600s) exceeded) — progress saved"   # agent.py's sentence


def _stopped(**kw) -> dict:
    return {"phase": ExplorationPhase.FAILED.value, "tables_total": 3, **kw}


def test_a_run_its_budget_stopped_is_continued_a_day_later_and_never_sooner():
    """theLook 2026-09-24: stopped on its 600 s budget and never continued (§6 item 34(f))."""
    legacy = _stopped(error=_BUDGET_STOP, started_at="2026-07-10T18:42:59+00:00")
    assert _decide(legacy)["reason"] == cont.STOPPED_ON_BUDGET
    fresh = _stopped(error=_BUDGET_STOP, stopped_on_budget_at="2026-07-11T12:00:00+00:00")
    assert _decide(fresh) is None
    assert cont.continues_at(fresh) == "2026-07-12T12:00:00+00:00"


def test_a_persons_stop_is_never_continued_and_a_failure_is_retried_with_backoff():
    persons = _stopped(error="cancelled (budget exceeded or stopped) — progress saved",
                       started_at="2026-07-01T00:00:00+00:00")
    assert _decide(persons) is None and cont.continues_at(persons) is None
    failed = _stopped(error="connection refused")
    plan = _decide(failed, _prog(_ran("full")))
    assert plan["reason"] == cont.RETRY and plan["job"] == "full" and plan["retry"]
    later = (_NOW + timedelta(days=1)).isoformat()
    assert _decide(failed, _prog(_ran("full"), failures=1, next_retry_at=later)) is None
    assert _decide(failed, _prog(_ran("full"), failures=cont.MAX_RETRIES)) is None
    # a dataset whose layer does not ask retries its structure only
    assert _decide(failed, _prog(_ran("full")), jobs=STRUCTURE)["job"] == "structure"


def test_an_interrupted_run_resumes_on_its_own_only_where_the_layer_asks():
    mid = {"phase": "synthesis", "tables_total": 3}
    assert _decide(mid, interrupted=True)["reason"] == cont.INTERRUPTED
    assert _decide(mid, interrupted=True, jobs=STRUCTURE) is None, "a person's Continue, not the platform's"


# ── the planner: every dataset, not the first one ─────────────────────────────

def _planner(monkeypatch, states, *, layers, spent_out=False, fps=None):
    from aughor.explorer import budget as B
    from aughor.explorer import program as P
    from aughor.routers import _shared
    monkeypatch.setattr("aughor.db.registry.list_connections", lambda *a, **k: [{"id": "wh"}])
    monkeypatch.setattr(_shared, "explorer_refusal", lambda cid: "")
    monkeypatch.setattr(cont, "_scout_enabled", lambda cid: True)
    monkeypatch.setattr(_shared, "schemas_of_connection", lambda cid: sorted(states))
    monkeypatch.setattr("aughor.routers.exploration.interrupted_runs", lambda cid: [])
    monkeypatch.setattr(_shared, "connection_has_business", lambda cid: "business" in layers.values())
    monkeypatch.setattr(_shared, "layer_scope", lambda cid, sch: sch)
    monkeypatch.setattr("aughor.ontology.dataset_layers.layer_of", lambda cid, sch, table="": layers.get(sch, ""))
    monkeypatch.setattr("aughor.explorer.store.load", lambda key: states[key.split("__", 1)[1]])
    monkeypatch.setattr(P, "load", lambda key: _prog(_ran(ended=_NOW - timedelta(days=2))))
    monkeypatch.setattr(cont, "dataset_fingerprint", lambda cid, sch: (fps or {}).get(sch, "abc"))
    monkeypatch.setattr(cont, "_approved_count", lambda cid, sch: {"marts": 4, "sales": 1}.get(sch, 0))
    monkeypatch.setattr(cont, "_asked_counts", lambda cid, now: {})
    held: list = []
    monkeypatch.setattr(P, "hold", lambda key, why: held.append((key, why)))
    monkeypatch.setattr(B, "standing", lambda cid, now=None: {"spent_out": spent_out, "sentence": "spent", "remaining": None})
    return held


def test_the_planner_judges_every_dataset_and_spends_on_the_most_valuable_first(monkeypatch):
    states = {"marts": _complete(), "sales": _complete(), "stage": _complete("old"), "uploads": _complete()}
    _planner(monkeypatch, states, layers={"marts": "business", "sales": "business", "stage": "raw"},
             fps={"stage": "new"})
    runs, watches = cont.plan_jobs(now=_NOW)
    by = {r["schema"]: r for r in runs}
    assert by["stage"]["job"] == "structure", "a raw dataset learns its changed structure, no model"
    assert by["marts"]["reason"] == cont.GAPS and by["sales"]["reason"] == cont.GAPS
    model = [r["schema"] for r in runs if r["uses_model"]]
    assert model == ["marts", "sales"], "ranked by the approved metrics that read them"
    assert "uploads" not in by, "an unset layer that already learned its structure waits for a person"
    assert {w["schema"]: (w["time"], w["layer"]) for w in watches} == {
        "marts": (True, "business"), "sales": (True, "business"),
        "stage": (False, "raw")}, "a raw dataset is read for its pipeline health, not its periods"


def test_a_spent_budget_holds_the_model_runs_and_says_so(monkeypatch):
    states = {"marts": _complete(), "sales": _complete("old")}
    held = _planner(monkeypatch, states, layers={"marts": "business", "sales": "business"},
                    spent_out=True, fps={"sales": "new"})
    runs, _ = cont.plan_jobs(now=_NOW)
    assert [(r["schema"], r["job"]) for r in runs] == [("sales", "structure")], \
        "a changed structure is still learned — it spends nothing"
    assert ("wh__marts", "spent") in held and ("wh__sales", "spent") in held


def test_a_turned_off_dataset_is_never_planned(monkeypatch):
    states = {"marts": _complete("old"), "stage": _complete("old")}
    _planner(monkeypatch, states, layers={"marts": "business"}, fps={"marts": "new", "stage": "new"})
    monkeypatch.setattr("aughor.ontology.visibility.excluded",
                        lambda cid, sch, table="": object() if sch == "stage" else None)
    runs, _ = cont.plan_jobs(now=_NOW)
    assert [r["schema"] for r in runs] == ["marts"]


# ── the tick: start + receipt ─────────────────────────────────────────────────

def test_the_tick_starts_each_job_as_planned_and_records_it(monkeypatch):
    plan = {"job": "questions", "reason": "reopened — x", "gaps_only": False, "uses_model": True,
            "conn_id": "wh", "schema": "marts", "key": "wh__marts", "take_reopen": True, "value": 1}
    monkeypatch.setattr(cont, "plan_jobs", lambda: ([plan], []))
    calls: list = []

    async def spawn(cid, **kw):
        calls.append((cid, kw))
        return {"ok": True, "job_id": "j1"}

    monkeypatch.setattr("aughor.routers._shared.spawn_explorer", spawn)
    taken: list = []
    monkeypatch.setattr("aughor.explorer.program.take_reopen", lambda key: taken.append(key))
    monkeypatch.setattr("aughor.explorer.program.clear_hold", lambda key: None)
    emits: list = []
    monkeypatch.setattr(cont, "_emit", lambda kind, payload, conn_id: emits.append((kind, payload)))

    assert asyncio.run(cont.run_continuous_tick()) == 1
    cid, kw = calls[0]
    assert cid == "wh" and kw["schema_name"] == "marts" and kw["domain_intel_only"] is True
    assert kw["structure_only"] is False and kw["gaps_only"] is False
    assert taken == ["wh__marts"]
    assert any(k == "exploration.rearmed" and p["job"] == "questions" for k, p in emits)


def test_a_declined_start_records_nothing(monkeypatch):
    plan = {"job": "structure", "reason": cont.NEW_DATASET, "gaps_only": True, "uses_model": False,
            "conn_id": "wh", "schema": None, "key": "wh", "value": 0}
    monkeypatch.setattr(cont, "plan_jobs", lambda: ([plan], []))

    async def spawn(cid, **kw):
        return {"ok": False, "reason": "already running"}

    monkeypatch.setattr("aughor.routers._shared.spawn_explorer", spawn)
    emits: list = []
    monkeypatch.setattr(cont, "_emit", lambda kind, payload, conn_id: emits.append((kind, payload)))
    assert asyncio.run(cont.run_continuous_tick()) == 0
    assert not any(k == "exploration.rearmed" for k, _ in emits)


# ── 6c: the governance skip is surfaced, not silent ───────────────────────────

def test_kickoff_auto_skip_emits_ledger_event(monkeypatch):
    from aughor.routers import _shared

    monkeypatch.setattr("aughor.kernel.agents.is_enabled", lambda agent, ws: False)
    monkeypatch.setattr("aughor.workspace.store.workspace_for_connection", lambda cid: "ws1")
    emits: list = []

    class _L:
        def emit(self, kind, payload, **kw):
            emits.append((kind, payload))

    monkeypatch.setattr("aughor.kernel.ledger.Ledger.default", classmethod(lambda cls: _L()))

    assert _shared.kickoff_exploration("c1", auto=True) is False
    assert any(k == "exploration.skipped" and p.get("reason") == "scout_disabled" for k, p in emits)


def test_continuous_flag_is_gone_for_good():
    """Flag endgame Wave 4 (2026-08-06): the loop is always on for an always-on
    process; the spend controls are the per-dataset gates in this module, not a
    process-wide boolean. A re-registered flag would be the boolean growing back."""
    from aughor.kernel.flags import FLAG_ENV
    assert "explorer.continuous" not in FLAG_ENV
