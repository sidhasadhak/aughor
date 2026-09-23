"""Idea 2 · the Watcher proposes the alerts worth having.

When an exploration finishes — a new connection, or a re-run after the schema moved — the
Watcher reads every metric that has a daily series on this connection, learns how each one
is distributed, and STAGES an anomaly watch for it as a `monitor_bundle` proposal: the
monitor (SQL on a clock, no model) plus the chain its breach fires (deep analysis → a post),
the exact shape Spotlight's `draft_monitor` stages by hand. Nothing arms itself: every
proposal lands in the inbox for a person, and the destination is an open choice the
approver fills (SP-7's law).

Two things make a proposal worth a person's minute rather than noise:

* **the threshold is tuned before it interrupts anyone** — the last 90 settled days are
  replayed under the runner's own rule (`monitors/rules.py`) and the smallest σ on the
  ladder that would have fired at most three times is the one proposed; the count rides the
  reasoning, so the reader sees "would have fired twice" and not a σ they have to trust;
* **still-settling days are not scored** — the connection's learned settling lag
  (`settling.learned_lag_days`) drops the youngest days from the distribution, and the
  monitor the proposal creates drops them at check time the same way.

Deterministic and model-free, so it can run after every exploration. Idempotent by
``(sentinel:<connection>, alert:<metric>)``: a re-run never duplicates a proposal and never
resurrects one a person already resolved — that is the inbox's own rule, reused.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from statistics import mean, median, pstdev
from typing import Callable, Optional

logger = logging.getLogger(__name__)

#: The Watcher's job kind for this work (`kernel/agents.py`).
JOB_KIND = "alert_proposals"
#: The evidence method, in the proposal's run id. Bump it when the way a watch is justified
#: changes: the next run supersedes every pending proposal an older method staged and
#: proposes again on the new evidence — a person is never left deciding on a replay the
#: platform no longer stands behind. (v2: the series is bounded to the recent window in
#: SQL; v1 replayed whatever rows the executor's cap happened to keep. v3: a watch the
#: ladder cannot quieten — more than MAX_FIRINGS even at its top σ — is not proposed.)
EVIDENCE_METHOD = "v3"
#: A series whose newest settled day is older than this is stale or truncated, not a watch.
MAX_SERIES_AGE_DAYS = 365
#: Replay window, and the run-in of history read before it so the first replayed day has a baseline.
HISTORY_DAYS = 90
BASELINE_DAYS = 30
#: Three settled weeks: below that a standard deviation is a guess, and no alert is staged.
MIN_POINTS = 21
#: The thresholds tried, smallest first; the first that fires ≤ MAX_FIRINGS in the replay wins.
SIGMA_LADDER = (2.5, 3.0, 3.5, 4.0)
MAX_FIRINGS = 3
#: A daily series is checked once a day, after the morning's data has landed.
CHECK_CRON = "0 9 * * *"

RunSql = Callable[[str], tuple[list, list, Optional[str]]]


@dataclass
class Candidate:
    name: str
    label: str
    series_sql: str
    source: str            # "explorer" (a north-star metric's trend) | "defined" (an approved metric)
    unit: str = ""


@dataclass
class Distribution:
    n: int
    mean: float
    std: float
    median: float
    first_day: date
    last_day: date
    sigma: float
    would_have_fired: int
    fired_days: list[str] = field(default_factory=list)


# ── series ───────────────────────────────────────────────────────────────────────


def _as_date(value) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def daily_series_sql(expr: str, table: str, ts_col: str, filters: list[str] | None = None,
                     since: Optional[date] = None) -> str:
    """An approved metric's expression, per day — `value_query`'s wrap with the day as the
    grain. Identifiers quoted in DuckDB's dialect (`native_sql` translates for BigQuery).

    ``since`` bounds the series IN SQL. Found on the first live run: theLook's revenue per
    day spans 2019→2026, the executor caps a result at a few thousand rows, and "the last
    90 days" of the capped series ended in August 2024 — a replay of the wrong years,
    staged with confidence. A series must be asked for its recent window, never trimmed
    after the executor already chose which rows to keep."""
    col = '"' + ts_col.replace('"', '""') + '"'
    conds = list(filters or [])
    if since is not None:
        conds.append(f"CAST({col} AS DATE) >= DATE '{since.isoformat()}'")
    where = (" WHERE " + " AND ".join(conds)) if conds else ""
    return (f"SELECT CAST({col} AS DATE) AS day, ({expr}) AS value FROM {table}{where} "
            f"GROUP BY 1 ORDER BY 1")


def read_series(run_sql: RunSql, sql: str) -> list[tuple[date, float]]:
    """(day, value) pairs sorted by day — or [] when the SQL is not a daily series (a
    breakdown's first column is a label, not a date) or fails."""
    try:
        _cols, rows, error = run_sql(sql)
    except Exception as exc:  # noqa: BLE001 — a failed read is "no series", named below
        logger.info("sentinel: series read failed: %s", exc)
        return []
    if error or not rows:
        return []
    out: list[tuple[date, float]] = []
    for r in rows:
        vals = list(r.values()) if isinstance(r, dict) else list(r)
        if len(vals) < 2:
            return []
        day = _as_date(vals[0])
        if day is None:
            return []
        try:
            out.append((day, float(vals[1] if vals[1] is not None else 0.0)))
        except (TypeError, ValueError) as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "a value that is not a number is not a point on the series",
                     counter="sentinel.unreadable_value")
            continue
    out.sort(key=lambda p: p[0])
    return out


# ── the distribution, and the threshold it earns ────────────────────────────────


def _fired(values: list[float], sigma: float) -> list[int]:
    """Indices that would have fired under the runner's OWN rule (`monitors/rules.py`): each
    day against the mean and σ of every day before it. The same function the monitor runs
    with, so the replay that justifies a watch is the rule that will fire it."""
    from aughor.monitors.rules import anomaly_verdict
    return [i for i in range(len(values)) if anomaly_verdict(values[:i], values[i], sigma).fired]


def choose_sigma(values: list[float]) -> tuple[float, list[int]]:
    """The smallest σ on the ladder whose replay fires at most `MAX_FIRINGS` times; the
    ladder's top when none does — and the replay's firings, so the reason can name them."""
    last: tuple[float, list[int]] = (SIGMA_LADDER[-1], _fired(values, SIGMA_LADDER[-1]))
    for sigma in SIGMA_LADDER:
        fired = _fired(values, sigma)
        if len(fired) <= MAX_FIRINGS:
            return sigma, fired
        last = (sigma, fired)
    return last


def learn_distribution(points: list[tuple[date, float]], *, today: Optional[date] = None,
                       settle_days: int = 1) -> Optional[Distribution]:
    """The last `HISTORY_DAYS` SETTLED days of a series, described, with the threshold
    the replay earns. None when there is too little to describe honestly."""
    today = today or datetime.now(timezone.utc).date()
    cutoff = today - timedelta(days=max(1, int(settle_days or 1)))
    settled = [(d, v) for d, v in sorted(points) if d <= cutoff]
    settled = settled[-HISTORY_DAYS:]
    if len(settled) < MIN_POINTS:
        return None
    values = [v for _, v in settled]
    sigma, fired = choose_sigma(values)
    return Distribution(
        n=len(values), mean=mean(values), std=pstdev(values), median=median(values),
        first_day=settled[0][0], last_day=settled[-1][0], sigma=sigma,
        would_have_fired=len(fired), fired_days=[settled[i][0].isoformat() for i in fired])


# ── candidates: every metric with a daily series on this connection ─────────────


def candidates(connection_id: str, schema_name: Optional[str] = None,
               since: Optional[date] = None) -> list[Candidate]:
    out: list[Candidate] = []
    # The explorer's north-star metrics carry a trend query (`chart_sql`, day/week grain).
    try:
        from aughor.business_profile.store import load as load_profile
        profile = load_profile(connection_id, schema_name)
    except Exception as exc:  # noqa: BLE001 — the defined half stands without the profile
        from aughor.kernel.errors import tolerate
        tolerate(exc, "no business profile means no north-star trends to watch",
                 counter="sentinel.profile_unavailable")
        profile = None
    for m in (getattr(profile, "north_star_metrics", None) or []):
        sql = str(getattr(m, "chart_sql", "") or "").strip()
        if sql:
            out.append(Candidate(name=str(m.name), label=str(m.name), series_sql=sql,
                                 source="explorer", unit=str(getattr(m, "unit_or_range", "") or "")))
    # An approved definition on a table with a timestamp: its expression, per day.
    try:
        from aughor.semantic.metrics import list_metrics
        from aughor.settling.sampler import time_tables
        ts_by_table = {t.split(".")[-1]: col for t, col, _ in time_tables(connection_id)}
        for m in list_metrics(connection_id=connection_id):
            if str(getattr(m, "status", "")) != "approved" or not m.tables:
                continue
            if (m.sql or "").strip().lower().startswith("select"):
                continue   # a full SELECT states its own shape; it has no day to add
            col = ts_by_table.get(str(m.tables[0]).split(".")[-1])
            if not col:
                continue
            out.append(Candidate(name=str(m.name), label=str(m.label or m.name),
                                 series_sql=daily_series_sql(m.sql, m.tables[0], col,
                                                             list(m.filters or []), since=since),
                                 source="defined", unit=str(m.unit or "")))
    except Exception as exc:  # noqa: BLE001 — the profile half stands without the registry
        logger.info("sentinel: defined metrics unavailable on %s: %s", connection_id, exc)
    seen: set[str] = set()
    unique: list[Candidate] = []
    for c in out:
        key = c.name.strip().lower()
        if key and key not in seen:
            seen.add(key)
            unique.append(c)
    return unique


# ── staging ──────────────────────────────────────────────────────────────────────


def _reason(cand: Candidate, dist: Distribution, settle_days: int) -> str:
    unit = f" {cand.unit}" if cand.unit else ""
    if dist.would_have_fired == 0:
        fired = "would never have fired"
    else:
        fired = (f"would have fired {dist.would_have_fired} time"
                 f"{'s' if dist.would_have_fired != 1 else ''}"
                 + (f" ({', '.join(dist.fired_days[:3])}{'…' if len(dist.fired_days) > 3 else ''})"
                    if dist.fired_days else ""))
    settle = (f"; the youngest {settle_days} days are still settling on this source and are "
              f"not scored" if settle_days > 1 else "")
    return (f"{cand.label}: over the last {dist.n} settled days ({dist.first_day} to "
            f"{dist.last_day}) it averaged {dist.mean:,.2f}{unit} with σ {dist.std:,.2f}; "
            f"a {dist.sigma}σ watch {fired} in that window{settle}. "
            f"Checked daily, SQL only — the deep analysis runs only when it fires.")[:400]


def run_id_for(connection_id: str) -> str:
    return f"sentinel:{EVIDENCE_METHOD}:{connection_id}"


def supersede_older_methods(connection_id: str) -> list[str]:
    """Resolve every PENDING Watcher proposal on this connection that an older evidence
    method staged. Returns their ids. The inbox's idempotency key is the run id, so the
    new method's proposals are new rows; the old ones must not sit beside them."""
    from aughor.actions.inbox import list_proposals, supersede_proposal
    superseded: list[str] = []
    current = run_id_for(connection_id)
    for p in list_proposals(connection_id=connection_id, status="pending", limit=500):
        run_id = str(getattr(p, "run_id", "") or "")
        if (getattr(p, "proposer", "") == "watcher" and run_id.startswith("sentinel:")
                and run_id != current):
            if supersede_proposal(p.id, actor="watcher:method",
                                  note=f"re-proposed under evidence method {EVIDENCE_METHOD}"):
                superseded.append(p.id)
    return superseded


def stage_alert(connection_id: str, cand: Candidate, dist: Distribution, *,
                settle_days: int = 1):
    """One `monitor_bundle` proposal, the shape Spotlight's `draft_monitor` stages: the
    anomaly monitor on the series plus the chain its breach fires, destination open.
    Returns ``(proposal, created)``; created is False when the inbox already held it."""
    from aughor.actions.inbox import StagedProposal, stage_proposal
    from aughor.agent.spotlight_act import open_choice_fields
    from aughor.automations.models import Automation, fill_required_holes
    from aughor.org.context import current_org_id

    name = f"{cand.label} anomaly watch"
    monitor = {"conn_id": connection_id, "name": name, "custom_sql": cand.series_sql,
               "alert_on": "anomaly", "sigma_threshold": dist.sigma, "check_cron": CHECK_CRON}
    chain = {
        "conn_id": connection_id, "name": name,
        "description": f"Fired by the '{name}' monitor; runs the deep analysis and posts it.",
        "conditions": [{"kind": "metric", "config": {"monitor_id": ""}}],
        "effects": [
            {"kind": "investigate", "config": {"question": f"What moved {cand.label}, and where?"}},
            {"kind": "slack_post", "config": {"channel": "", "bot_id": "",
                                              "message": {"$from": "step1.answer"}}},
        ],
    }
    filled_effects, holes = fill_required_holes(chain["effects"])
    Automation(**{**chain, "effects": filled_effects,
                  "conditions": [{"kind": "metric", "config": {"monitor_id": "…"}}]})
    proposal = StagedProposal(
        kind="monitor_bundle", org_id=current_org_id() or "", connection_id=connection_id,
        action_id=f"monitor:{name}+automation:{name}",
        params={"monitor": monitor, "automation": chain},
        detail={"to_fill": holes, "open_choices": open_choice_fields(chain),
                "watches": cand.name, "sigma": dist.sigma, "check_cadence": "daily",
                "source": cand.source,
                "distribution": {"n": dist.n, "mean": dist.mean, "std": dist.std,
                                 "median": dist.median, "first_day": dist.first_day.isoformat(),
                                 "last_day": dist.last_day.isoformat(),
                                 "would_have_fired": dist.would_have_fired,
                                 "fired_days": dist.fired_days, "settle_days": settle_days}},
        reasoning=_reason(cand, dist, settle_days),
        proposer="watcher", source="agent",
        run_id=run_id_for(connection_id), call_id=f"alert:{cand.name.strip().lower()}")
    stored = stage_proposal(proposal)
    return stored, stored.id == proposal.id


def propose_for_connection(connection_id: str, *, run_sql: Optional[RunSql] = None,
                           today: Optional[date] = None, schema_name: Optional[str] = None) -> dict:
    """The Watcher's work for one connection: read every candidate's series, learn its
    distribution, stage the watch. Returns what happened per metric — staged, already
    staged, or why nothing was."""
    if run_sql is None:
        from aughor.db.measure import run_sql_for
        run_sql = run_sql_for(connection_id)
    try:
        from aughor.settling import learned_lag_days
        settle_days = learned_lag_days(connection_id) or 1
    except Exception:
        settle_days = 1
    today = today or datetime.now(timezone.utc).date()
    since = today - timedelta(days=HISTORY_DAYS + BASELINE_DAYS + settle_days + 7)
    staged: list[dict] = []
    existing: list[str] = []
    skipped: dict[str, str] = {}
    try:
        superseded = supersede_older_methods(connection_id)
    except Exception as exc:  # noqa: BLE001 — an unresolved older proposal is reported, not fatal
        logger.warning("sentinel: could not supersede older proposals on %s: %s", connection_id, exc)
        superseded = []
    cands = candidates(connection_id, schema_name, since=since)
    for cand in cands:
        points = read_series(run_sql, cand.series_sql)
        if not points:
            skipped[cand.name] = "no daily series (the query returned no (day, value) rows)"
            continue
        newest = points[-1][0]
        if newest < today - timedelta(days=MAX_SERIES_AGE_DAYS):
            skipped[cand.name] = (f"the series ends on {newest.isoformat()} — stale, or truncated "
                                  f"by the executor's row cap; not a watch")
            continue
        dist = learn_distribution(points, today=today, settle_days=settle_days)
        if dist is None:
            skipped[cand.name] = (f"too few settled days ({len(points)} points; needs "
                                  f"{MIN_POINTS} settled)")
            continue
        if dist.would_have_fired > MAX_FIRINGS:
            # Measured live on theLook, 2026-09-23: with no settling lag learned yet, the
            # youngest days read ~8× high, σ was 70% of the mean, and even 4σ "would have
            # fired 5 times" — all of them the last five days. A watch that would have
            # interrupted someone five times in a quarter is noise, not a proposal.
            why = (" — the source's settling lag is not learned yet, so its youngest days "
                   "are scored as if final" if settle_days == 1 else "")
            skipped[cand.name] = (f"too noisy to propose: even a {dist.sigma}σ watch would have "
                                  f"fired {dist.would_have_fired} times in the last {dist.n} "
                                  f"days{why}")
            continue
        try:
            p, created = stage_alert(connection_id, cand, dist, settle_days=settle_days)
        except Exception as exc:  # noqa: BLE001 — one metric's failure never stops the rest
            skipped[cand.name] = f"could not stage: {str(exc)[:160]}"
            continue
        if created:
            staged.append({"proposal_id": p.id, "metric": cand.name, "sigma": dist.sigma,
                           "would_have_fired": dist.would_have_fired, "n": dist.n,
                           "reasoning": p.reasoning})
        else:
            existing.append(cand.name)
    return {"connection_id": connection_id, "candidates": len(cands), "staged": staged,
            "already_staged": existing, "skipped": skipped, "settle_days": settle_days,
            "superseded": superseded, "since": since.isoformat()}


async def submit_alert_proposals(connection_id: str, *, fingerprint: str = "") -> Optional[str]:
    """Hand the work to the kernel as the Watcher's job, keyed on the schema fingerprint so
    an unchanged schema re-explored proposes nothing twice. Returns the job id."""
    import asyncio

    from aughor.kernel.jobs import kernel

    async def _work():
        return await asyncio.to_thread(propose_for_connection, connection_id)

    return await kernel().submit(
        JOB_KIND, _work, conn_id=connection_id,
        idempotency_key=f"{JOB_KIND}:{connection_id}:{fingerprint or 'unfingerprinted'}")
