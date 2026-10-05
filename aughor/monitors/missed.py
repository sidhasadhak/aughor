"""Idea 8 · a review of what was missed (PENDING: "Ideas not taken up").

Someone finds a big move nothing flagged. The platform works out WHY — from what it already
knows, no model — and proposes the fix:

* **was it a move at all?** The metric's daily series (the Watcher's own candidates and
  reader, `monitors/sentinel.py`) is scored on the day under the runner's own rule
  (`rules.anomaly_verdict`, the history before that day): its z, against the mean and spread
  of the days before it. A move inside the normal day-to-day range is said to be one;
* **what was watching it?** Every monitor on the connection that watches this metric (by name,
  or by the very series SQL the Watcher stages), whether it existed on the day, whether it was
  on, what its own rule says about that value, and whether it actually fired;
* **a watch waiting for a person** — the Watcher may already have proposed one, and an
  unaccepted proposal watches nothing;
* **settling** — a day younger than the connection's learned settling lag is not scored yet;
* **a breach that never reached anyone** — the sends the departure gate held, for the chains
  those monitors fire.

The fix, when the answer is "nothing was watching it" and a watch would have caught it: the
Watcher's own `stage_alert` — a `monitor_bundle` proposal in the inbox, armed by nobody but the
person who accepts it. When the only watch that would have caught it would also have fired
every week, that is said instead of proposed.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from statistics import mean, pstdev
from typing import Callable, Optional

RunSql = Callable[[str], tuple]

#: How far back the series is read, so the day has the Watcher's whole replay window behind it.
_LOOKBACK_DAYS = 150


@dataclass
class Watch:
    """One thing that could have flagged the move, and what it would have done."""
    kind: str                     # "monitor"
    id: str
    name: str
    enabled: bool
    existed_on_day: bool
    rule: str                     # "anomaly at 2.5σ" · "below 100 (warning)" · "freshness"
    would_have_fired: Optional[bool]
    fired: list[str] = field(default_factory=list)       # alert timestamps around the day
    held: list[str] = field(default_factory=list)        # departure ids held for its chains
    note: str = ""


@dataclass
class MissReview:
    connection_id: str
    metric: str
    day: str
    value: Optional[float] = None
    baseline_mean: Optional[float] = None
    baseline_std: Optional[float] = None
    z: Optional[float] = None
    settle_days: int = 1
    watches: list[Watch] = field(default_factory=list)
    waiting_proposal: dict = field(default_factory=dict)
    verdict: str = ""
    proposal: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def _day(value) -> Optional[date]:
    """A date from a date, a datetime or an ISO string — None for anything else."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _watching(monitor, metric: str, series_sql: str) -> bool:
    name = (getattr(monitor, "metric_name", "") or "").strip().lower()
    sql = " ".join((getattr(monitor, "custom_sql", "") or "").split())
    return name == metric.strip().lower() or (bool(series_sql) and sql == " ".join(series_sql.split()))


def _monitor_watch(monitor, day: date, value: float, history: list[float]) -> Watch:
    from aughor.monitors.rules import anomaly_verdict, threshold_verdict
    created = _day(getattr(monitor, "created_at", "") or "")
    kind = str(getattr(monitor, "alert_on", "") or "")
    watch = Watch(kind="monitor", id=monitor.id, name=monitor.name,
                  enabled=bool(getattr(monitor, "enabled", True)),
                  existed_on_day=created is None or created <= day, rule=kind, would_have_fired=None)
    if kind == "anomaly":
        sigma = float(getattr(monitor, "sigma_threshold", 2.5) or 2.5)
        watch.rule = f"anomaly at {sigma:g}σ"
        watch.would_have_fired = anomaly_verdict(history, value, sigma).fired
    elif kind == "threshold_cross":
        direction = str(getattr(monitor, "threshold_direction", "below") or "below")
        warn = getattr(monitor, "warning_threshold", None)
        crit = getattr(monitor, "critical_threshold", None)
        watch.rule = (f"{direction} {crit if crit is not None else warn}"
                      f" ({'critical' if crit is not None else 'warning'})")
        watch.would_have_fired = threshold_verdict(value, direction=direction, warning=warn,
                                                   critical=crit).fired
    else:
        watch.note = f"a {kind or 'non-value'} watch — it does not score a day's value"
    return watch


def _fired_around(monitor_id: str, day: date) -> list[str]:
    from aughor.monitors.store import get_alerts
    out = []
    for a in get_alerts(monitor_id=monitor_id, limit=200):
        at = _day(a.triggered_at)
        if at is not None and day <= at <= day + timedelta(days=14):
            out.append(a.triggered_at)
    return out


def _held_for(monitor_id: str, day: date) -> list[str]:
    """Departures the gate HELD for chains this monitor fires, from the day on."""
    from aughor.automations.store import list_automations
    from aughor.govern.departure_store import list_departures
    chains = [a.id for a in list_automations()
              if any(c.kind == "metric" and (c.config or {}).get("monitor_id") == monitor_id
                     for c in a.conditions)]
    held = []
    for chain_id in chains:
        for d in list_departures(automation_id=chain_id, limit=100,
                                 states=["held", "held_probation", "held_owner"]):
            at = _day(d.get("ts") or "")
            if at is None or at >= day:
                held.append(str(d.get("id") or ""))
    return held


def _waiting_proposal(connection_id: str, candidate_name: str) -> dict:
    """The Watcher's own proposal for this metric, if one exists — the inbox key it stages under."""
    from aughor.actions.inbox import list_proposals
    key = f"alert:{candidate_name.strip().lower()}"
    for p in list_proposals(connection_id=connection_id, limit=500):
        if p.proposer == "watcher" and p.call_id == key and p.status in ("pending", "rejected"):
            return {"proposal_id": p.id, "status": p.status, "staged_at": p.created_at}
    return {}


def review_missed(connection_id: str, metric: str, day: str, *, stage: bool = True,
                  run_sql: Optional[RunSql] = None, today: Optional[date] = None) -> MissReview:
    """Why nothing flagged ``metric`` on ``day`` — and, when the answer is "nothing watched
    it" and a quiet watch would have caught it, the watch staged as a proposal (``stage``)."""
    from aughor.monitors import sentinel
    from aughor.monitors.store import list_monitors

    review = MissReview(connection_id=connection_id, metric=metric, day=str(day)[:10])
    when = _day(day)
    if when is None:
        review.verdict = f"'{day}' is not a date — give the day of the move as YYYY-MM-DD."
        return review
    today = today or datetime.now(timezone.utc).date()
    try:
        from aughor.settling import learned_lag_days
        review.settle_days = int(learned_lag_days(connection_id) or 1)
    except Exception as exc:  # noqa: BLE001 — no learned lag is the honest day-one state
        from aughor.kernel.errors import tolerate
        tolerate(exc, "no settling lag learned; a day is scored the next day", counter="missed.settling")
        review.settle_days = 1

    since = when - timedelta(days=_LOOKBACK_DAYS)
    cands = sentinel.candidates(connection_id, since=since)
    cand = next((c for c in cands if c.name.strip().lower() == metric.strip().lower()
                 or c.label.strip().lower() == metric.strip().lower()), None)
    if cand is None:
        names = ", ".join(sorted(c.name for c in cands)) or "none"
        review.verdict = (f"No daily series for '{metric}' on this connection, so nothing could "
                          f"have watched it by day — the metrics that have one: {names}.")
        return review

    if run_sql is None:
        from aughor.db.measure import run_sql_for
        run_sql = run_sql_for(connection_id, internal=True)
    points = sentinel.read_series(run_sql, cand.series_sql)
    on_day = [v for d, v in points if d == when]
    if not on_day:
        review.verdict = f"The series of {cand.label} has no value on {when.isoformat()}."
        return review
    value = on_day[0]
    history = [v for d, v in points if when - timedelta(days=sentinel.HISTORY_DAYS) <= d < when]
    review.value = value
    if len(history) >= 2:
        review.baseline_mean, review.baseline_std = mean(history), pstdev(history)
        if review.baseline_std > 1e-9:
            review.z = (value - review.baseline_mean) / review.baseline_std

    review.watches = []
    for m in list_monitors(connection_id):
        if not _watching(m, cand.name, cand.series_sql):
            continue
        w = _monitor_watch(m, when, value, history)
        w.fired = _fired_around(m.id, when)
        if w.fired:
            w.held = _held_for(m.id, when)
        review.watches.append(w)
    review.waiting_proposal = _waiting_proposal(connection_id, cand.name)
    _decide(review, cand, points, today, stage)
    book_missed_move(review)
    return review


#: The verdict phrases that mean "nothing flagged a move that was one" — a miss, in the study §N's
#: sense (a Correction), as opposed to an ordinary day, a day still settling, or a move that WAS flagged.
_MISS_PHRASES = ("Nothing was watching it", "did not count that as a breach", "it was switched off",
                 "did not exist yet on that day", "no alert is on record")


def is_miss(review: MissReview) -> bool:
    """Whether the review found a miss: the day was a move by the series' own spread and nothing
    that watched it fired — not an ordinary day, not a day still settling, not a move that WAS flagged."""
    v = review.verdict or ""
    if review.value is None or "It WAS flagged" in v or "still settling" in v or "ordinary day" in v:
        return False
    return any(p in v for p in _MISS_PHRASES)


def book_missed_move(review: MissReview) -> str:
    """Phase 5 of the 2027 study — a miss is a Correction: booked as a kernel artifact (kind
    ``missed_move``, one per connection · metric · day, a second review restating the first) so the
    Record's Corrections view lists it. Returns the entry id, or "" when the review found no miss."""
    if not is_miss(review):
        return ""
    try:
        from aughor.kernel.ledger import Ledger
        from aughor.record.corrections import MISSED_MOVE_KIND
        key = f"{MISSED_MOVE_KIND}:{review.connection_id}:{review.metric.strip().lower()}:{review.day}"
        return Ledger.default().artifact_write(MISSED_MOVE_KIND, key, review.to_dict(), conn_id=review.connection_id or None,
                                               lineage=[("missed", f"metric:{review.metric}", review.day)])
    except Exception as exc:  # noqa: BLE001 — the review stands; its Corrections entry is best-effort and said
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the missed move could not be booked as a correction", counter="missed.book",
                 conn_id=review.connection_id or None)
        return ""


def _decide(review: MissReview, cand, points, today: date, stage: bool) -> None:
    from aughor.monitors import sentinel

    when = _day(review.day)
    z = abs(review.z) if review.z is not None else None
    moved = (f"{cand.label} read {review.value:,.4g} on {review.day}, "
             + (f"{z:.1f}σ from the {len([1 for d, _ in points if d < when][-sentinel.HISTORY_DAYS:])} days before it"
                if z is not None else "with too little history before it to score"))
    if when + timedelta(days=review.settle_days) > today:
        review.verdict = (f"{moved}. That day is still settling — this source's days stop changing "
                          f"after {review.settle_days} days, and a watch scores a day only once it "
                          f"has; it will be scored on {(when + timedelta(days=review.settle_days)).isoformat()}.")
        return
    fired = [w for w in review.watches if w.fired]
    if fired:
        w = fired[0]
        review.verdict = (f"{moved}. It WAS flagged: '{w.name}' fired on {w.fired[0][:10]}"
                          + (f", and its message was held at the departure gate ({len(w.held)} held "
                             f"— review them in Agent Ops → Departures)." if w.held
                             else " — look for the alert under Monitors."))
        return
    live = [w for w in review.watches if w.enabled and w.existed_on_day]
    # Not a move at all, by the series' own spread, and no threshold a person set was crossed:
    # say THAT first — "the watch did not exist yet" would read as the reason for a miss there was not.
    by_line = any(w.would_have_fired for w in live if "σ" not in w.rule)
    if z is not None and z < sentinel.SIGMA_LADDER[0] and not by_line:
        names = ", ".join(f"'{w.name}'" for w in review.watches)
        review.verdict = (f"{moved}. That is an ordinary day by this series' own spread — no watch "
                          f"quiet enough to keep (the smallest the Watcher proposes is "
                          f"{sentinel.SIGMA_LADDER[0]:g}σ) would count it"
                          + (f"; the watches on it ({names}) did not either." if names else "."))
        return
    if live:
        quiet = [w for w in live if w.would_have_fired is False]
        if quiet:
            w = quiet[0]
            review.verdict = (f"{moved}. '{w.name}' was watching it ({w.rule}) and its rule did not "
                              f"count that as a breach" + (f" — it needed {w.rule.split()[-1]} and the "
                                                            f"move was {z:.1f}σ." if "σ" in w.rule and z is not None else "."))
        else:
            w = live[0]
            review.verdict = (f"{moved}. '{w.name}' was watching it ({w.rule}); "
                              + (w.note or "its rule would have counted it, yet no alert is on record — "
                                           "check the monitor's run history under Monitors."))
        return
    off = [w for w in review.watches if not w.enabled or not w.existed_on_day]
    if off:
        w = off[0]
        review.verdict = (f"{moved}. '{w.name}' watches it, but "
                          + ("it was switched off." if not w.enabled else
                             "it did not exist yet on that day."))
        return
    if review.waiting_proposal:
        wp = review.waiting_proposal
        review.verdict = (f"{moved}. Nothing was watching it — the Watcher proposed a watch on "
                          f"{str(wp.get('staged_at'))[:10]}, and it is {wp.get('status')} in the inbox "
                          f"(proposal {wp.get('proposal_id')}); accepting it is the fix.")
        return
    dist = sentinel.learn_distribution([(d, v) for d, v in points if d < when + timedelta(days=1)],
                                       today=when + timedelta(days=review.settle_days),
                                       settle_days=review.settle_days)
    if dist is None:
        review.verdict = f"{moved}. Nothing was watching it, and there are too few settled days to tune one."
        return
    if z is None or z < dist.sigma:
        review.verdict = (f"{moved}. Nothing was watching it — and a watch quiet enough to propose "
                          f"({dist.sigma:g}σ, firing at most {sentinel.MAX_FIRINGS} times a quarter) would "
                          f"not have counted it either: by this series' own spread it was an ordinary day.")
        return
    if dist.would_have_fired > sentinel.MAX_FIRINGS:
        review.verdict = (f"{moved}. Nothing was watching it, and the only watch that catches it would "
                          f"have fired {dist.would_have_fired} times in {dist.n} days — too noisy to propose.")
        return
    review.verdict = (f"{moved}. Nothing was watching it. A {dist.sigma:g}σ watch would have caught it, "
                      f"and would have fired {dist.would_have_fired} times in the last {dist.n} days.")
    # The watch runs from NOW, so it is tuned on the series as it stands today; the verdict
    # above was judged on what a watch tuned on that day would have done.
    now = sentinel.learn_distribution(points, today=today, settle_days=review.settle_days) or dist
    if not stage:
        review.proposal = {"would_stage": True, "sigma": now.sigma, "would_have_fired": now.would_have_fired}
        return
    p, created = sentinel.stage_alert(review.connection_id, cand, now, settle_days=review.settle_days)
    review.proposal = {"proposal_id": p.id, "created": created, "sigma": now.sigma}
    review.verdict += (f" It is proposed in the inbox (proposal {p.id}) — a person accepts it and "
                       f"chooses where it posts." if created else
                       f" It was already proposed (proposal {p.id}).")
