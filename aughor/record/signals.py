"""Signals the loop looks for before a KPI moves — the settling lag itself changing, and the early
stages of a declared process slowing (the 2027 study §K; phase 2's capability "new signals"; the
arc's close-out, C4).

§K's table named both as "not signals yet": a broken promise and a new finding already open
inquiries, a fired alert too (`monitors/notify._open_inquiry_for_alert`), but nothing watched the
weak signals that come BEFORE the number moves — dispatch lag before late delivery, a source whose
numbers stop settling when they used to. This module is those two, as code over readings the
platform already takes:

- **the settling lag** (`settling/sampler.run_settling_samples_daily`): the connection's learned lag
  is read before and after the day's reading; a lag that moved by :data:`SETTLING_MIN_DAYS_MOVED`
  days and :data:`SETTLING_MIN_REL` of itself, or that stopped being learnable (a table still moving
  at the horizon), opens an inquiry on the connection;
- **a process's early stages** (`ontology/processes.measure_override_processes`): each measurement
  is compared with the one it overwrites; a stage before the last whose p90 transition lag rose by
  :data:`STAGE_MIN_REL` and :data:`STAGE_MIN_DAYS`, or a promise whose breach rate rose by
  :data:`BREACH_MIN_POINTS`, opens an inquiry on the process.

An inquiry opened here spends no run: it is a run proposed with its cost (`inquiry.propose_run`),
listed for a person. `open_inquiry` folds a second signal on the same subject within a fortnight
into the one inquiry, so a slow drift is one question, not one a day. Every signal is journaled as
`inquiry.signal`. Nothing here is a model.
"""
from __future__ import annotations

from typing import Any, Optional

SETTLING_MIN_DAYS_MOVED = 2
SETTLING_MIN_REL = 0.5
STAGE_MIN_REL = 0.25
STAGE_MIN_DAYS = 0.5
BREACH_MIN_POINTS = 0.05


def _emit(connection_id: str, signal: dict, inquiry_id: str) -> None:
    try:
        from aughor.kernel.ledger import Ledger
        Ledger.default().emit("inquiry.signal", {**signal, "connection_id": connection_id, "inquiry": inquiry_id},
                              conn_id=connection_id or None)
    except Exception as exc:  # noqa: BLE001 — the spine is observability
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the signal opened its inquiry; only its spine event was lost", counter="signals.emit")


# ── the settling lag ───────────────────────────────────────────────────────────────────────

def settling_signal(before: dict, after: dict) -> Optional[dict]:
    """A signal when the connection's lag moved enough to matter, else None. ``before``/``after``
    are `settling/store.connection_lag` readings: ``{days, source, still_moving, horizon}``."""
    b_days, a_days = before.get("days"), after.get("days")
    b_src, a_src = before.get("source"), after.get("source")
    if a_days is None:
        return None                                   # nothing learned yet: nothing to compare
    if b_days is None:
        return None                                   # the first verdict is a baseline, not a move
    moved = abs(float(a_days) - float(b_days))
    if moved >= SETTLING_MIN_DAYS_MOVED and moved >= SETTLING_MIN_REL * max(float(b_days), 1.0):
        return {"signal": "settling_lag", "before": b_days, "after": a_days, "source": a_src,
                "text": f"the settling lag moved from {b_days} to {a_days} days"
                        + (f" (still moving: {', '.join(after.get('still_moving') or [])})" if after.get("still_moving") else "")}
    if b_src == "learned" and a_src == "beyond_horizon":
        return {"signal": "settling_lag", "before": b_days, "after": a_days, "source": a_src,
                "text": f"a table stopped settling inside the horizon: {', '.join(after.get('still_moving') or []) or 'unnamed'}"
                        f" — the lag is at least {a_days} days where {b_days} was learned"}
    return None


def on_settling_sampled(connection_id: str, before: dict, after: dict):
    """The sampler's hook: open (or wake) the connection's settling inquiry when the day's reading
    moved the lag. Returns the inquiry, or None. Never raises into the sampler."""
    signal = settling_signal(before or {}, after or {})
    if signal is None:
        return None
    try:
        from aughor.record.inquiry import open_inquiry
        q = open_inquiry(question=f"Why did the data's settling lag change on this connection — {signal['text']}?"[:500],
                         connection_id=connection_id, opened_by="settling", subject="settling-lag")
        _emit(connection_id, signal, q.id)
        return q
    except Exception as exc:  # noqa: BLE001 — a signal that cannot open an inquiry leaves the reading standing
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the settling signal fired; its inquiry could not be opened", counter="signals.settling",
                 conn_id=connection_id or None)
        return None


# ── a process's early stages ───────────────────────────────────────────────────────────────

def _stages(measured: Any) -> list[dict]:
    if not isinstance(measured, dict):
        return []
    return [s for s in (measured.get("stages") or []) if isinstance(s, dict)]


def process_signals(process_id: str, prior: Any, now: Any) -> list[dict]:
    """The signals between two measurements of one process (`Process.model_dump()` dicts): an early
    stage slowed, a promise is breaking more. The first measurement is a baseline and yields none."""
    before, after = _stages(prior), _stages(now)
    if not before or not after:
        return []
    by_name = {s.get("name"): s for s in before}
    out: list[dict] = []
    last = after[-1].get("name") if after else None
    for s in after:
        name = s.get("name")
        p = by_name.get(name)
        if not p:
            continue
        if name != last:
            a90, b90 = s.get("p90_days"), p.get("p90_days")
            if isinstance(a90, (int, float)) and isinstance(b90, (int, float)) and b90 > 0:
                rose = float(a90) - float(b90)
                if rose >= STAGE_MIN_DAYS and rose >= STAGE_MIN_REL * float(b90):
                    out.append({"signal": "stage_slowed", "process": process_id, "stage": name,
                                "before": b90, "after": a90,
                                "text": f"the {name} stage of {process_id} slowed: p90 {b90} → {a90} days"})
        pa, pb = s.get("promise") or {}, p.get("promise") or {}
        ra, rb = pa.get("breach_rate") if isinstance(pa, dict) else None, pb.get("breach_rate") if isinstance(pb, dict) else None
        if isinstance(ra, (int, float)) and isinstance(rb, (int, float)) and float(ra) - float(rb) >= BREACH_MIN_POINTS:
            out.append({"signal": "promise_breaking", "process": process_id, "stage": name, "before": rb, "after": ra,
                        "text": f"the {pa.get('name') or name} promise of {process_id} is breaking more: {rb:.1%} → {ra:.1%}"})
    return out


def on_process_measured(connection_id: str, process_id: str, prior_entry: Any, new_entry: Any) -> list:
    """The measure pass's hook: compare the measurement being written with the one it overwrites and
    open an inquiry per signal. Returns the inquiries opened. Never raises into the pass."""
    prior = (prior_entry or {}).get("measured") if isinstance(prior_entry, dict) else None
    now = (new_entry or {}).get("measured") if isinstance(new_entry, dict) else None
    opened = []
    for signal in process_signals(process_id, prior, now):
        try:
            from aughor.record.inquiry import mission_for, open_inquiry
            metric = f"{signal.get('stage')}_lag_days" if signal["signal"] == "stage_slowed" else f"{signal.get('stage')}_breach_rate"
            q = open_inquiry(question=f"Why did {signal['text']}?"[:500], connection_id=connection_id,
                             opened_by=f"process:{process_id}", subject=f"process-{process_id}-{signal.get('stage')}",
                             mission=mission_for(connection_id, metric))
            _emit(connection_id, signal, q.id)
            opened.append(q)
        except Exception as exc:  # noqa: BLE001
            from aughor.kernel.errors import tolerate
            tolerate(exc, "a process signal fired; its inquiry could not be opened", counter="signals.process",
                     conn_id=connection_id or None)
    return opened
