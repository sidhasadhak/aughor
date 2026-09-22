"""
Outcome Tracking — Sprint 16.

Records the result of each recommendation from an investigation.
Drives historical_success_rate on PlaybookEntry objects.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone  # noqa: F401 — `date` names a type in signatures
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field

_DEFAULT_PATH = Path(__file__).parent.parent.parent / "data" / "recommendation_outcomes.json"

RecStatus = Literal["accepted", "rejected", "implemented", "verified", "dismissed"]


class RecOutcome(BaseModel):
    id: str                              # "{inv_id}_rec_{index}"
    inv_id: str
    rec_index: int                       # position in report.recommended_actions
    rec_text: str
    status: RecStatus = "accepted"
    metric_name: Optional[str] = None
    metric_before: Optional[float] = None
    metric_after: Optional[float] = None
    created_at: str = Field(default_factory=lambda: _now())
    updated_at: str = Field(default_factory=lambda: _now())
    # CB-2 (2026-09-22) — decided when it is accepted: the metric's value NOW, measured with the
    # investigation's own definition (`spec`), and the date the platform measures again and asks
    # whether it worked. The question goes to the metric's owner when one is linked, else to the
    # person who accepted. All additive: a record written before this carries none of it.
    connection_id: str = ""
    accepted_by: str = ""
    spec: Optional[dict] = None
    baseline_value: Optional[float] = None
    baseline_at: str = ""
    baseline_window: str = ""            # "2026-08-23 → 2026-09-21 (30 days)"
    review_days: int = 0
    review_at: str = ""                  # ISO date-time the review is due
    review_value: Optional[float] = None
    reviewed_at: str = ""
    review_window: str = ""
    review_question: str = ""            # the question as asked; "" until the review ran
    review_asked_to: str = ""            # principal the question went to
    review_asked_at: str = ""
    review_note: str = ""                # why a baseline or review could not be measured


from aughor.util.time import now_iso_z as _now


# ── Persistence ───────────────────────────────────────────────────────────────

def _load_raw(path: Path | None = None) -> list[dict]:
    p = path or _DEFAULT_PATH
    if not p.exists():
        return []
    with open(p) as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def _save_raw(outcomes: list[dict], path: Path | None = None) -> None:
    p = path or _DEFAULT_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w") as f:
        json.dump(outcomes, f, indent=2)


# ── Public API ────────────────────────────────────────────────────────────────

def log_outcome(
    inv_id: str,
    rec_index: int,
    rec_text: str,
    status: RecStatus,
    metric_name: Optional[str] = None,
    metric_before: Optional[float] = None,
    metric_after: Optional[float] = None,
    path: Path | None = None,
) -> RecOutcome:
    outcome_id = f"{inv_id}_rec_{rec_index}"
    raw = _load_raw(path)
    outcome = RecOutcome(
        id=outcome_id,
        inv_id=inv_id,
        rec_index=rec_index,
        rec_text=rec_text,
        status=status,
        metric_name=metric_name,
        metric_before=metric_before,
        metric_after=metric_after,
        updated_at=_now(),
    )
    for i, o in enumerate(raw):
        if o.get("id") == outcome_id:
            # Preserve original created_at on update — and (CB-2) everything the acceptance and the
            # review recorded: a status change is an answer to the question, not a new record. The
            # before/after the answer is judged on default to the measured baseline and review.
            kept = {k: o.get(k) for k in _REVIEW_FIELDS if k in o}
            merged = {**outcome.model_dump(), **kept, "created_at": o.get("created_at", _now())}
            if merged.get("metric_before") is None:
                merged["metric_before"] = kept.get("baseline_value")
            if merged.get("metric_after") is None:
                merged["metric_after"] = kept.get("review_value")
            if not merged.get("metric_name"):
                merged["metric_name"] = (kept.get("spec") or {}).get("metric_label") or None
            outcome = RecOutcome(**merged)
            raw[i] = outcome.model_dump()
            _save_raw(raw, path)
            return outcome
    raw.append(outcome.model_dump())
    _save_raw(raw, path)

    # Promote (or weaken) causal proposals for this investigation
    if status in ("verified", "implemented", "rejected"):
        try:
            from aughor.lifecycle.causal import promote_on_outcome
            promote_on_outcome(inv_id, contradicted=(status == "rejected"))
        except Exception:
            pass

    return outcome


_REVIEW_FIELDS = ("connection_id", "accepted_by", "spec", "baseline_value", "baseline_at", "baseline_window",
                  "review_days", "review_at", "review_value", "reviewed_at", "review_window", "review_question",
                  "review_asked_to", "review_asked_at", "review_note")
DEFAULT_REVIEW_DAYS = 30
_QUALIFIED_REF = re.compile(r"\b([A-Za-z_][\w]*)\.([A-Za-z_][\w]*)(?:\.([A-Za-z_][\w]*))?\b")


def _bare(name: str) -> str:
    return (name or "").split(".")[-1].strip().lower()


def measurement_sql(spec: dict, *, end_day: "date") -> tuple[Optional[str], str, str]:
    """The query that measures ``spec`` over a window of its own length ending on ``end_day``
    (the most recent complete day), or ``(None, "", why)`` when the definition cannot be measured
    on its own — a metric whose SQL or date column reaches another table needs a join the intake
    never declared, and a baseline that guessed one would be a number nobody can defend. Written in
    the platform's canonical form; the caller renders it native (`db.dialects.native_sql`)."""
    metric_sql = str(spec.get("metric_sql") or "").strip()
    table = str(spec.get("metric_table") or "").strip()
    date_col = str(spec.get("date_column") or "").strip()
    if not metric_sql or not table:
        return None, "", "the answer carried no measurable definition"
    bare = _bare(table)
    for m in _QUALIFIED_REF.finditer(metric_sql):
        parts = [x for x in m.groups() if x]
        ref_table = parts[-2].lower() if len(parts) >= 2 else ""
        if ref_table and ref_table != bare:
            return None, "", f"the metric spans tables ({m.group(0)} is not on {table}); a baseline needs a one-table definition"
    col = date_col
    if "." in date_col:
        head, _, last = date_col.rpartition(".")
        if _bare(head) != bare:
            return None, "", f"the date column {date_col} is not on {table}"
        col = last
    days = max(1, int(spec.get("window_days") or 1))
    start = end_day - timedelta(days=days - 1)
    stop = end_day + timedelta(days=1)
    where = (f"CAST({col} AS DATE) >= DATE '{start.isoformat()}' AND CAST({col} AS DATE) < DATE '{stop.isoformat()}'"
             if col else "1=1")
    label = f"{start.isoformat()} → {end_day.isoformat()} ({days} day{'s' if days != 1 else ''})"
    return f"SELECT {metric_sql} AS value FROM {table} WHERE {where}", label, ""


def measure_spec(spec: dict, run_sql, *, end_day: Optional["date"] = None) -> tuple[Optional[float], str, str]:
    """``(value, window_label, note)`` — the metric measured now, or ``(None, label, why)``.
    ``run_sql(sql) -> (columns, rows, error)`` is injected (the door builds it on the investigation's
    connection), so this measures without importing the DB layer and a test measures with a fake."""
    end_day = end_day or (datetime.now(timezone.utc).date() - timedelta(days=1))
    sql, label, why = measurement_sql(spec, end_day=end_day)
    if sql is None:
        return None, "", why
    try:
        columns, rows, error = run_sql(sql)
    except Exception as exc:  # noqa: BLE001 — a failed measurement is a note on the record, never a crash
        return None, label, f"measurement failed: {str(exc)[:160]}"
    if error:
        return None, label, f"measurement failed: {str(error)[:160]}"
    if not rows or rows[0] is None or rows[0][0] is None:
        return None, label, "the window holds no rows"
    try:
        return float(rows[0][0]), label, ""
    except (TypeError, ValueError):
        return None, label, f"the metric did not read as a number ({str(rows[0][0])[:40]})"


def record_acceptance(outcome: RecOutcome, *, spec: Optional[dict], connection_id: str, accepted_by: str,
                      run_sql, review_days: Optional[int] = None, now: Optional[datetime] = None,
                      path: Path | None = None) -> RecOutcome:
    """CB-2 — what acceptance decides: the baseline measured NOW with the answer's own definition,
    and the review date. Measured or not, the record says which and why."""
    now = now or datetime.now(timezone.utc)
    days = int(review_days) if review_days and int(review_days) > 0 else DEFAULT_REVIEW_DAYS
    fields: dict = {"connection_id": connection_id or "", "accepted_by": accepted_by or "", "spec": spec,
                    "review_days": days, "review_at": (now + timedelta(days=days)).isoformat(),
                    "baseline_at": now.isoformat(), "baseline_value": None, "baseline_window": "", "review_note": ""}
    if spec:
        value, label, note = measure_spec(spec, run_sql, end_day=now.date() - timedelta(days=1))
        fields.update(baseline_value=value, baseline_window=label, review_note=note)
        if value is not None and outcome.metric_before is None:
            fields["metric_before"] = value
        if not outcome.metric_name and spec.get("metric_label"):
            fields["metric_name"] = spec["metric_label"]
    else:
        fields["review_note"] = "the answer carried no measurable definition; the review will ask without numbers"
    return _update(outcome.id, fields, path)


def due_reviews(now: Optional[datetime] = None, path: Path | None = None) -> list[RecOutcome]:
    """Accepted (or implemented) recommendations whose review date has come and that were not yet
    reviewed. A verified/rejected/dismissed one has its answer and is never asked."""
    now = now or datetime.now(timezone.utc)
    out = []
    for o in load_all_outcomes(path):
        if o.status not in ("accepted", "implemented") or not o.review_at or o.reviewed_at:
            continue
        try:
            due = datetime.fromisoformat(o.review_at)
        except ValueError as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, f"outcome {o.id} carries an unreadable review date; it is never asked",
                     counter="outcomes.review_date")
            continue
        if due.tzinfo is None:
            due = due.replace(tzinfo=timezone.utc)
        if due <= now:
            out.append(o)
    return out


def _fmt(value: float) -> str:
    """A number a person reads: 10,710,477.39 not 1.07105e+07; 0.0425 stays 0.0425."""
    if abs(value) >= 1000:
        return f"{value:,.2f}".rstrip("0").rstrip(".")
    return f"{value:.4g}"


def review_question(o: RecOutcome, review_value: Optional[float], review_window: str) -> str:
    label = (o.spec or {}).get("metric_label") or o.metric_name or "the metric"
    when = (o.baseline_at or o.created_at)[:10]
    if o.baseline_value is not None and review_value is not None:
        return (f"You accepted \"{o.rec_text}\" on {when}. {label} was {_fmt(o.baseline_value)} then "
                f"({o.baseline_window}); it is {_fmt(review_value)} now ({review_window}). Did it work?")
    if o.baseline_value is not None:
        return (f"You accepted \"{o.rec_text}\" on {when}. {label} was {_fmt(o.baseline_value)} then "
                f"({o.baseline_window}); it could not be measured now. Did it work?")
    return f"You accepted \"{o.rec_text}\" on {when}. Did it work?"


def resolve_asked_to(o: RecOutcome) -> tuple[str, str]:
    """``(principal, note)`` — the metric's OWNER when the catalog names one the platform can reach
    (the user's call, 2026-09-22; CB-3 makes a linked display name reach), else the person who
    accepted. The note says when an owner exists but is unresolved, so the record shows why the
    accepter was asked instead of nobody being asked silently."""
    label = (o.spec or {}).get("metric_label") or o.metric_name or ""
    note = ""
    if label:
        try:
            from aughor.rbac.routing import owner_principal
            from aughor.semantic.metrics import get_metric
            m = get_metric(label, connection_id=o.connection_id or None) or get_metric(label)
            owner = getattr(m, "owner", None) if m is not None else None
            principal = owner_principal(owner or "") if owner else None
            if principal:
                return principal, ""
            if owner:
                note = f"owner '{owner}' of {label} is not linked to a person; asked the accepter instead"
        except Exception as exc:  # noqa: BLE001 — an owner lookup that fails falls back to the accepter
            from aughor.kernel.errors import tolerate
            tolerate(exc, "metric owner lookup for a review is best-effort; the accepter is asked",
                     counter="outcomes.review_owner")
    return (o.accepted_by or ""), note


def run_due_reviews(now: Optional[datetime] = None, *, run_sql_for, path: Path | None = None) -> list[RecOutcome]:
    """Measure again and ask, for every due review — each once. ``run_sql_for(connection_id)`` returns
    a ``run_sql`` for that connection (or raises; the review then records the failure and still asks).
    Returns the records reviewed."""
    now = now or datetime.now(timezone.utc)
    reviewed = []
    for o in due_reviews(now, path):
        value, label, note = None, "", ""
        if o.spec:
            try:
                run_sql = run_sql_for(o.connection_id)
                value, label, note = measure_spec(o.spec, run_sql, end_day=now.date() - timedelta(days=1))
            except Exception as exc:  # noqa: BLE001 — recorded on the row
                note = f"review measurement failed: {str(exc)[:160]}"
        else:
            note = o.review_note or "no measurable definition"
        asked_to, owner_note = resolve_asked_to(o)
        notes = "; ".join(x for x in (note or o.review_note, owner_note) if x)
        fields = {"review_value": value, "reviewed_at": now.isoformat(), "review_window": label,
                  "review_question": review_question(o, value, label), "review_asked_to": asked_to,
                  "review_asked_at": now.isoformat(), "review_note": notes}
        if value is not None and o.metric_after is None:
            fields["metric_after"] = value
        reviewed.append(_update(o.id, fields, path))
    return reviewed


def _update(outcome_id: str, fields: dict, path: Path | None = None) -> RecOutcome:
    raw = _load_raw(path)
    for i, o in enumerate(raw):
        if o.get("id") == outcome_id:
            merged = {**o, **fields, "updated_at": _now()}
            out = RecOutcome(**merged)
            raw[i] = out.model_dump()
            _save_raw(raw, path)
            return out
    raise LookupError(f"outcome {outcome_id} not found")


def load_outcomes_for_inv(inv_id: str, path: Path | None = None) -> list[RecOutcome]:
    return [RecOutcome(**o) for o in _load_raw(path) if o.get("inv_id") == inv_id]


def load_all_outcomes(path: Path | None = None) -> list[RecOutcome]:
    return [RecOutcome(**o) for o in _load_raw(path)]


def update_playbook_success_rates(path: Path | None = None) -> int:
    """
    Recompute historical_success_rate for all playbook entries that have outcomes.
    Returns the number of entries updated.
    """
    from aughor.playbook.retriever import retrieve_for_metric_and_phases
    from aughor.playbook.store import get_entry, save_entry

    outcomes = load_all_outcomes(path)
    terminal = [o for o in outcomes if o.status in ("verified", "rejected")]
    if not terminal:
        return 0

    # Group outcomes by matched playbook entry
    entry_stats: dict[str, dict] = {}  # entry_id -> {wins, total}
    for outcome in terminal:
        # Match the recommendation text to playbook entries
        matches = retrieve_for_metric_and_phases([outcome.rec_text], limit=1)
        if not matches:
            continue
        entry = matches[0]
        if entry.id not in entry_stats:
            entry_stats[entry.id] = {"wins": 0, "total": 0, "sources": []}
        entry_stats[entry.id]["total"] += 1
        if outcome.status == "verified":
            entry_stats[entry.id]["wins"] += 1
        if outcome.inv_id not in entry_stats[entry.id]["sources"]:
            entry_stats[entry.id]["sources"].append(outcome.inv_id)

    updated = 0
    for entry_id, stats in entry_stats.items():
        entry = get_entry(entry_id)
        if not entry:
            continue
        entry.historical_success_rate = stats["wins"] / stats["total"] if stats["total"] else 0.0
        entry.evidence_sources = stats["sources"]
        # Auto-promote to active if success rate >= 50% with at least 2 outcomes
        if entry.status == "draft" and stats["total"] >= 2 and entry.historical_success_rate >= 0.5:
            entry.status = "active"
        save_entry(entry)
        updated += 1

    return updated
