"""The continuous loop — the Explorer's three jobs on their own triggers (exploration principles §2, 2026-10-08).

WP-6 made exploration re-arm when the schema changed or a run went a week stale. Measured 2026-10-07, it
had re-armed nothing since 2026-09-26: it read only each connection's FIRST dataset, never retried a
failure, could not tell a budget stop from a person's, and every run it did start walked every phase
again and spent the model's whole curiosity loop. The principles replace the fixed clock with events:

  • **Learn the structure** when the dataset's fingerprint changes — no model.
  • **Map the questions** while the dataset is not mature, at most daily, within the month's budget —
    the uncovered cells of its question list only, unless a named event reopened it (a metric approved,
    a figure that moved) or it has never been asked: then the model's curiosity loop runs too.
  • **Watch over time** on each settled period at its metrics' date grains — SQL only (`explorer/watch.py`).

Every dataset of every connection is judged on its own (`next_job`, pure). What the platform may do on
its own is the dataset's LAYER, set by a person (`ontology/dataset_layers.py`): an unset layer learns the
structure only. A dataset turned off is never touched. Scout governance still decides whether a
connection explores on its own at all. The hourly heartbeat is the check; spend happens on events.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

_TICK_SECONDS = 3600.0            # how often the loop wakes; the work is gated below

#: A run stopped by its own time or token budget is continued this long after it stopped —
#: the user's call, 2026-09-26 (ROADMAP §6 item 34(f)): theLook's run stopped on its 600 s
#: budget and nothing ever continued it. It resumes from its saved progress, under the same
#: per-connection gates as any automatic run. A person's stop is never continued.
STOPPED_RERUN_SECONDS = 86_400.0
#: The one sentence the budget path writes (``explorer/agent.py``); a run recorded before the
#: ``stopped_on_budget_at`` stamp existed is recognised by it. A user's stop or a kernel
#: cancel ends "… or stopped) — progress saved" and never matches.
_BUDGET_STOP_TAIL = "exceeded) — progress saved"
#: A dataset's questions are asked at most this often on the platform's own initiative.
QUESTIONS_EVERY_SECONDS = 86_400.0
#: A failed run is retried after 1, 2, 4 … days, at most this many times; then a person's Start.
MAX_RETRIES = 4
#: The most model-spending runs one check starts, the most valuable first; and the most readings.
MODEL_RUNS_PER_TICK = 2
WATCHES_PER_TICK = 6

#: Why a run was started (the ledger's `exploration.rearmed` reasons, and the run's own note).
NEW_DATASET = "a new dataset"
SCHEMA_CHANGED = "its tables or columns changed"
INTERRUPTED = "it was interrupted"
STOPPED_ON_BUDGET = "it stopped on its run budget a day ago"
RETRY = "a retry after a failure"
FIRST_QUESTIONS = "its layer is set — its first questions"
REOPENED = "reopened"
GAPS = "its question list has uncovered cells"
#: The order the model-spending runs are started in when the check may start only some.
_PRIORITY = {REOPENED: 0, FIRST_QUESTIONS: 1, NEW_DATASET: 2, SCHEMA_CHANGED: 3, INTERRUPTED: 4,
             STOPPED_ON_BUDGET: 4, RETRY: 5, GAPS: 6}


def stopped_on_budget_at(state: dict) -> Optional[datetime]:
    """When a run that its own budget stopped came to a halt, or None — a complete or running
    run, a failure with an error, and a person's stop are not budget stops."""
    from aughor.explorer.models import ExplorationPhase
    if state.get("phase") != ExplorationPhase.FAILED.value:
        return None
    stamp = state.get("stopped_on_budget_at")
    if not stamp:
        error = str(state.get("error") or "")
        if not (error.startswith("cancelled (") and error.endswith(_BUDGET_STOP_TAIL)):
            return None
        # recorded before the stamp: the run stopped within its budget of starting
        stamp = state.get("started_at")
    try:
        at = datetime.fromisoformat(str(stamp))
    except (TypeError, ValueError):
        return None   # an unreadable stamp is not a reason to spend
    return at if at.tzinfo else at.replace(tzinfo=timezone.utc)


def continues_at(state: dict) -> Optional[str]:
    """When the continuous loop will continue a budget-stopped run, for the Briefing to say."""
    at = stopped_on_budget_at(state)
    return (at + timedelta(seconds=STOPPED_RERUN_SECONDS)).isoformat() if at else None


def fingerprint_of(schema_text: str) -> Optional[str]:
    """A dataset's fingerprint from its schema text: each table's column count, by bare name — so a run
    that qualifies its names and a check that does not read the same fingerprint. None for no tables."""
    from aughor.db.schema_render import parse_schema_tables
    from aughor.tools.profile_cache import compute_schema_fingerprint
    tables = parse_schema_tables(schema_text or "")
    if not tables:
        return None
    return compute_schema_fingerprint({str(t).split(".")[-1].lower(): len(c) for t, c in tables.items()})


def dataset_fingerprint(conn_id: str, schema: Optional[str]) -> Optional[str]:
    """The dataset's current fingerprint, computed as a run stamps it (`fingerprint_of` over the schema
    text of the same scope, the tables a person turned off included — turning one off is not a change
    to learn). Best-effort: None on any failure — the check then waits."""
    try:
        from aughor.db.connection import open_connection_for, open_connection_for_with_schema
        db = open_connection_for_with_schema(conn_id, schema) if schema else open_connection_for(conn_id)
        try:
            from aughor.db.connection import unfiltered_schema
            return fingerprint_of(unfiltered_schema(db))
        finally:
            db.close()
    except Exception as exc:  # noqa: BLE001
        logger.debug("continuous: dataset fingerprint failed for %s/%s: %s", conn_id, schema, exc)
        return None


def connection_schema_fingerprint(connection_id: str) -> Optional[str]:
    """The connection's current schema fingerprint (all schemas), computed the SAME way the
    profile cache does — so it is directly comparable to the value a run stamps at completion.
    Best-effort: None on any failure (the tick then falls back to the staleness path only)."""
    try:
        from aughor.db.connection import open_connection_for
        from aughor.tools.schema import parse_schema_tables
        from aughor.tools.profile_cache import compute_schema_fingerprint
        db = open_connection_for(connection_id)
        try:
            schema_str = db.get_schema()
        finally:
            db.close()
        table_cols = parse_schema_tables(schema_str)
        return compute_schema_fingerprint({t: len(cols) for t, cols in table_cols.items()})
    except Exception as exc:
        logger.debug("continuous: fingerprint failed for %s: %s", connection_id, exc)
        return None


def _emit(kind: str, payload: dict, conn_id: str) -> None:
    try:
        from aughor.kernel.ledger import Ledger
        Ledger.default().emit(kind, payload, conn_id=conn_id)
    except Exception:
        logger.debug("continuous: ledger emit %s failed", kind, exc_info=True)


def _ago(stamp, now: datetime) -> Optional[float]:
    try:
        at = datetime.fromisoformat(str(stamp))
    except (TypeError, ValueError):
        return None
    at = at if at.tzinfo else at.replace(tzinfo=timezone.utc)
    return (now - at).total_seconds()


def _plan(job: str, reason: str, *, gaps_only: bool = True, **extra) -> dict:
    return {"job": job, "reason": reason, "gaps_only": gaps_only,
            "uses_model": job in ("questions", "full"), **extra}


def next_job(state: dict, prog: dict, *, jobs: frozenset, current_fp: Optional[str], running: bool,
             interrupted: bool, now: datetime, questions_share: Optional[float]) -> Optional[dict]:
    """Pure: the job one dataset needs next, or None. ``jobs`` are what its layer lets the platform
    run on its own; ``questions_share`` is its Questions maturity (`explorer.maturity`)."""
    from aughor.explorer import maturity as M
    from aughor.explorer import program as P
    if running or not jobs:
        return None
    asks = "questions" in jobs
    phase = str(state.get("phase") or "pending")
    learned = bool(state.get("structure_learned")) or phase in ("domain_intel", "synthesis", "complete")
    if phase == "pending" and not state.get("tables_total") and not learned:
        return _plan("full", NEW_DATASET, gaps_only=False) if asks else _plan("structure", NEW_DATASET)
    if interrupted:
        if asks:
            return _plan("full", INTERRUPTED)
        return None if learned else _plan("structure", INTERRUPTED)
    stopped = stopped_on_budget_at(state)
    if stopped is not None:
        if (now - stopped).total_seconds() < STOPPED_RERUN_SECONDS:
            return None
        last = P.last_run(prog)
        job = (last or {}).get("job") or "full"
        if job != "structure" and not asks:
            return None if learned else _plan("structure", STOPPED_ON_BUDGET)
        return _plan(job, STOPPED_ON_BUDGET)
    if phase == "failed":
        error = str(state.get("error") or "")
        if error.startswith("cancelled (") or "turned off for analysis" in error:
            return None                      # a person's stop, or a person's off switch, belongs to the person
        if prog.get("failures", 0) >= MAX_RETRIES:
            return None
        wait = _ago(prog.get("next_retry_at"), now) if prog.get("next_retry_at") else 0.0
        if wait is not None and wait < 0:
            return None
        job = (P.last_run(prog) or {}).get("job") or ("full" if asks else "structure")
        if job != "structure" and not asks:
            job = "structure"
        return _plan(job, RETRY, retry=True)
    if phase != "complete":
        return None
    stored = state.get("dataset_fingerprint") or (state.get("structure_learned") or {}).get("fp")
    if current_fp and stored and current_fp != stored:
        return _plan("full", SCHEMA_CHANGED) if asks else _plan("structure", SCHEMA_CHANGED)
    if not asks:
        return None
    reopened = prog.get("reopened")
    if reopened:
        return _plan("questions", f"{REOPENED} — {reopened.get('reason') or 'a named event'}",
                     gaps_only=False, take_reopen=True, priority_reason=REOPENED)
    asked = P.last_run(prog, "questions", "full") is not None or (
        not state.get("domain_intel_skipped") and bool(state.get("domain_coverage")))
    if not asked:
        return _plan("questions", FIRST_QUESTIONS, gaps_only=False)
    if questions_share is not None and questions_share >= M.MATURE:
        return None                          # mature: watched, until a named event reopens it
    last_q = P.last_run(prog, "questions", "full")
    since = _ago((last_q or {}).get("ended_at"), now) if last_q else None
    if since is not None and since < QUESTIONS_EVERY_SECONDS:
        return None
    return _plan("questions", GAPS)


def _scout_enabled(conn_id: str) -> bool:
    from aughor.kernel.agents import is_enabled
    from aughor.workspace.store import workspace_for_connection
    return is_enabled("scout", workspace_for_connection(conn_id))


def plan_jobs(*, now: Optional[datetime] = None) -> tuple[list[dict], list[dict]]:
    """Sync, executor-safe: every dataset of every connection, judged on its own. Returns
    ``(runs, watches)`` — the runs to start, the most valuable model-spending ones first and at most
    ``MODEL_RUNS_PER_TICK`` of them, and the datasets whose settled periods are due a reading. Reads
    stores and each dataset's live fingerprint; starts nothing. Never raises."""
    from aughor.db.registry import list_connections
    from aughor.explorer import budget as B
    from aughor.explorer import maturity as M
    from aughor.explorer import program as P
    from aughor.explorer import store as expl_store
    from aughor.explorer.models import ExplorationPhase
    from aughor.ontology.dataset_layers import LAYERS, auto_jobs
    from aughor.ontology.visibility import excluded
    from aughor.routers._shared import (automatic_jobs, connection_has_business, explorer_refusal, explorers,
                                        layer_scope, schemas_of_connection)

    now = now or datetime.now(timezone.utc)
    runs: list[dict] = []
    watches: list[dict] = []
    for conn in list_connections():
        conn_id = conn.get("id")
        if not conn_id:
            continue
        try:
            if explorer_refusal(conn_id):
                continue
            if not _scout_enabled(conn_id):
                _emit("exploration.skipped", {"reason": "scout_disabled", "connection_id": conn_id}, conn_id)
                continue
            from aughor.routers.exploration import interrupted_runs
            schemas = schemas_of_connection(conn_id)
            datasets: list[Optional[str]] = list(schemas) if len(schemas) >= 2 else [None]
            stuck = set(interrupted_runs(conn_id))
            has_business = connection_has_business(conn_id)
            explored = frozenset(l for l in LAYERS if "questions" in auto_jobs(l, connection_has_business=has_business))
            standing = None
            popularity = None
            for sch in datasets:
                if sch and excluded(conn_id, sch) is not None:
                    continue
                key = P.key_for(conn_id, sch)
                jobs = automatic_jobs(conn_id, sch)
                if not jobs:
                    continue
                state = expl_store.load(key)
                prog = P.load(key)
                live = explorers.get(key)
                live_phase = getattr(getattr(live, "status", None), "phase", None) if live is not None else None
                running = (live_phase not in (ExplorationPhase.COMPLETE, ExplorationPhase.FAILED, None)
                           or (expl_store.is_unfinished(state) and key not in stuck))
                fp = dataset_fingerprint(conn_id, sch) if str(state.get("phase") or "") == "complete" else None
                from aughor.ontology.dataset_layers import layer_of
                layer = layer_of(conn_id, layer_scope(conn_id, sch))
                share = M.questions_bar(state, prog, layer=layer, explored_layers=explored)["share"]
                plan = next_job(state, prog, jobs=jobs, current_fp=fp, running=running,
                                interrupted=key in stuck, now=now, questions_share=share)
                if plan is not None and plan["uses_model"]:
                    standing = standing or B.standing(conn_id, now=now)
                    if standing["spent_out"]:
                        P.hold(key, standing["sentence"])
                        plan = (_plan("structure", plan["reason"]) if plan["reason"] in (SCHEMA_CHANGED, NEW_DATASET)
                                else None)
                    elif plan is not None:
                        plan["budget_left"] = standing.get("remaining")
                if plan is not None:
                    if popularity is None:
                        popularity = _asked_counts(conn_id, now)
                    runs.append({**plan, "conn_id": conn_id, "schema": sch, "key": key,
                                 "value": _approved_count(conn_id, sch),
                                 "asked": sum(popularity.get(t, 0) for t in _tables_of(state)),
                                 "failures": prog.get("failures", 0)})
                if str(state.get("phase") or "") == "complete" and ("time" in jobs or layer == "raw"):
                    # business: its settled periods and its dimensions' new values; raw: its pipeline health
                    watches.append({"conn_id": conn_id, "schema": sch, "key": key, "layer": layer,
                                    "time": "time" in jobs, "reopen": "questions" in jobs})
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "continuous-exploration planning is best-effort per connection",
                     counter="explorer.continuous_plan", conn_id=conn_id)
    # Spend goes to the most valuable first (§7): the reason, then the approved metrics that read the dataset,
    # then how often people query its tables.
    model = sorted((r for r in runs if r["uses_model"]),
                   key=lambda r: (_PRIORITY.get(r.get("priority_reason") or r["reason"], 9), -r["value"],
                                  -r.get("asked", 0)))[:MODEL_RUNS_PER_TICK]
    # Each run is capped at its share of what is left of the month, so the runs one check starts cannot
    # together overshoot the budget (the kernel enforces the cap like any run budget).
    per_conn: dict[str, int] = {}
    for r in model:
        per_conn[r["conn_id"]] = per_conn.get(r["conn_id"], 0) + 1
    for r in model:
        left = r.get("budget_left")
        if left is not None:
            r["token_cap"] = max(1, int(left) // per_conn[r["conn_id"]])
    rest = [r for r in runs if not r["uses_model"]]
    return rest + model, watches[:WATCHES_PER_TICK]


#: When each connection's query popularity was last mined by this process — refreshed at most daily.
_ASKED_MINED: dict[str, float] = {}
ASKED_REFRESH_SECONDS = 86_400.0


def _asked_counts(conn_id: str, now: datetime) -> dict[str, int]:
    """How often people have queried each table of the connection (`sql/popularity.py`, by bare name),
    mined from the query history at most once a day. {} when nothing was mined."""
    from aughor.sql.popularity import load_popularity, refresh_popularity
    stamp = now.timestamp()
    if stamp - _ASKED_MINED.get(conn_id, 0.0) >= ASKED_REFRESH_SECONDS:
        _ASKED_MINED[conn_id] = stamp
        try:
            from aughor.db.connection import connection_traits
            from aughor.db.registry import get_conn_type
            refresh_popularity(conn_id, dialect=connection_traits(get_conn_type(conn_id)).get("dialect") or "duckdb")
        except Exception as exc:  # noqa: BLE001 — the ranking falls back to approved metrics
            from aughor.kernel.errors import tolerate
            tolerate(exc, "query popularity could not be mined for the ranking", counter="explorer.asked",
                     conn_id=conn_id)
    return {str(t).lower(): int(n) for t, n in (load_popularity(conn_id).get("table") or {}).items()}


def _tables_of(state: dict) -> set[str]:
    """The tables a dataset's runs have read, by bare name — from what its structure job recorded."""
    out: set[str] = set()
    for k in list((state.get("distributions") or {})) + list((state.get("null_meanings") or {})):
        out.add(str(k).split(":")[0].split(".")[-1].lower())
    out.update(str(t).split(".")[-1].lower() for t in (state.get("lifecycle_maps") or {}))
    return out


def _approved_count(conn_id: str, schema: Optional[str]) -> int:
    try:
        from aughor.briefing.ranges import governed_metrics
        return len(governed_metrics(conn_id, schema))
    except Exception:  # noqa: BLE001 — ranking only
        return 0


async def run_continuous_tick() -> int:
    """One pass of the loop: plan off the event loop, start the runs on it, then read what is due.
    Returns the number of runs started. Never raises."""
    import asyncio
    from aughor.explorer import program as P
    from aughor.explorer import watch as W
    from aughor.routers._shared import spawn_explorer

    loop = asyncio.get_running_loop()
    runs, watches = await loop.run_in_executor(None, plan_jobs)
    started = 0
    now = datetime.now(timezone.utc)
    for r in runs:
        try:
            res = await spawn_explorer(
                r["conn_id"], schema_name=r["schema"], structure_only=r["job"] == "structure",
                domain_intel_only=r["job"] == "questions", gaps_only=bool(r.get("gaps_only")),
                reason=f"started on its own: {r['reason']}", token_cap=r.get("token_cap"))
            if not res.get("ok"):
                logger.info("continuous: %s not started (%s): %s", r["key"], r["reason"], res.get("reason"))
                continue
            started += 1
            if r.get("take_reopen"):
                P.take_reopen(r["key"])
            if r.get("retry"):
                days = 2 ** int(r.get("failures") or 0)
                P.record_failure(r["key"], (now + timedelta(days=days)).isoformat())
            P.clear_hold(r["key"])
            _emit("exploration.rearmed", {"reason": r["reason"], "job": r["job"], "connection_id": r["conn_id"],
                                          "schema": r["schema"]}, r["conn_id"])
            logger.info("continuous: %s job for %s (%s)", r["job"], r["key"], r["reason"])
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "continuous-exploration start is best-effort per dataset",
                     counter="explorer.continuous_rearm", conn_id=r.get("conn_id"))
    from aughor.explorer import health as H
    for w in watches:
        try:
            got = (await loop.run_in_executor(None, lambda w=w: W.read_due(
                w["conn_id"], w["schema"], reopen_questions=w["reopen"]))) if w.get("time", True) else []
            daily = await loop.run_in_executor(None, lambda w=w: H.read_dataset(
                w["conn_id"], w["schema"], layer="raw" if w.get("layer") == "raw" else "business",
                reopen_questions=w["reopen"]))
            for g in got:
                if g.get("moved") and w["reopen"]:
                    await explain_move(w["conn_id"], w["schema"], g["grain"], through=str(g.get("through") or ""))
            if got or daily:
                _emit("exploration.watched", {"connection_id": w["conn_id"], "schema": w["schema"],
                                              "grains": [g["grain"] for g in got],
                                              "daily": (daily or {}).get("kind", "")}, w["conn_id"])
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "the watch job is best-effort per dataset", counter="explorer.watch",
                     conn_id=w.get("conn_id"))
    return started


async def explain_move(conn_id: str, schema: Optional[str], grain: str, *, through: str = "") -> Optional[str]:
    """Have the model write the explanation of a reading's move (`explorer/move_story.py`) as a supervised job
    under the Explorer's charter — its tokens count against the month's budget, capped at what is left. A
    spent budget withholds the explanation and says why. Returns the job id, or None."""
    import asyncio
    from aughor.explorer import budget as B
    from aughor.explorer import move_story as S
    from aughor.explorer import program as P
    key = P.key_for(conn_id, schema)
    standing = B.standing(conn_id)
    if standing["spent_out"]:
        P.record_story(key, grain, {"text": "", "withheld": f"not written — {standing['sentence']}"})
        return None
    from aughor.kernel.jobs import kernel

    async def _run():
        # to_thread copies the job's context into the thread, so the model call is metered on this job
        return await asyncio.to_thread(S.explain_reading, conn_id, schema, grain)

    return await kernel().submit(
        S.JOB_KIND, _run, conn_id=conn_id, idempotency_key=f"{S.JOB_KIND}:{key}:{grain}:{through}",
        payload={"schema_name": schema, "grain": grain,
                 **({"token_cap": max(1, int(standing["remaining"]))} if standing.get("remaining") else {})})
