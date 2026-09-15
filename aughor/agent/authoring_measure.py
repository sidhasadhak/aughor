"""SP-M (§3.11) — measure authoring, with no model anywhere in the measurement.

Two instruments, both pure reads:

* :func:`score_proposal` — the honesty checks SP-7…SP-13 promised, asked of a STAGED
  proposal row (recorded or live): the chain validates, the declared open choices are
  exactly the real ones, runs-as is bound the way the kind promises, the schema is
  real where a catalogue is known, the stated first run sits on its own cron boundary
  in the chain's own clock, and a monitor bundle carries its structural cost facts.
  ``None`` means "not applicable / unknowable offline" — an offline scorer must never
  grade what it cannot see (a failed probe is not an absence, SP-7's own law).

* :func:`authoring_funnel` — staged → accepted → finished in the form → re-drafted →
  rejected → lapsed, counted by ISO week of staging. SP-3's falsifier (a draft
  abandoned for the form) is MEASURED here rather than assumed: it is the
  ``finished_in_form`` column, written by SP-11's editor-resolve door.

The scored ask corpus lives in ``evals/authoring_asks.jsonl`` — thirty real asks,
drafted ONCE against a live model by ``scripts/record_authoring_drafts.py`` (the only
spending step, run on the user's word) and recorded; this module then scores the
recordings forever after, in CI, for free.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

#: The kinds the authoring movement stages — the funnel's population.
DRAFT_KINDS = frozenset({
    "agent_draft", "automation_draft", "agent_bundle",
    "automation_edit", "monitor_bundle", "brief_draft",
})

_CHECKS = ("validates", "open_choices_honest", "runs_as_bound",
           "schema_real", "clock_right", "cost_shown")

#: The sentence SP-11's editor-resolve stamps — the funnel keys on it, and a test
#: holds the two ends together.
FINISHED_IN_FORM_MARK = "finished in the editor"


def _chain_of(kind: str, params: dict) -> Optional[dict]:
    if kind == "automation_draft":
        return dict(params or {})
    if kind in ("agent_bundle", "monitor_bundle"):
        chain = (params or {}).get("automation")
        return dict(chain) if isinstance(chain, dict) else None
    return None


def _validates(kind: str, chain: dict) -> tuple[Optional[bool], str]:
    from aughor.automations.models import Automation, fill_required_holes

    filled, _holes = fill_required_holes(list(chain.get("effects") or []))
    checked = {**chain, "effects": filled}
    if kind == "monitor_bundle":
        # The metric trigger's monitor id is the ACCEPT's to mint — a placeholder for
        # validation, exactly as the drafting tool itself validates.
        checked["conditions"] = [
            {**c, "config": {**dict(c.get("config") or {}),
                             "monitor_id": str((c.get("config") or {}).get("monitor_id") or "…")}}
            if c.get("kind") == "metric" else c
            for c in (chain.get("conditions") or [])
        ]
    try:
        Automation(**checked)
        return True, ""
    except Exception as exc:
        return False, f"chain does not validate: {str(exc)[:200]}"


def _open_choices_honest(chain: dict, detail: dict) -> tuple[Optional[bool], str]:
    """The card's declared fields versus the accept gate's real holes — ONE truth."""
    from aughor.automations.models import fill_required_holes
    from aughor.runners.automation_save import parse_hole

    _f, holes = fill_required_holes(list(chain.get("effects") or []))
    real = {h for h in (parse_hole(x) for x in holes) if h is not None}
    declared = {(int(c.get("action", 0)), str(c.get("key", "")))
                for c in (detail.get("open_choices") or [])
                if isinstance(c, dict)}
    if real == declared:
        return True, ""
    return False, (f"declared open choices {sorted(declared)} != the accept gate's "
                   f"real holes {sorted(real)}")


def _runs_as_bound(kind: str, chain: dict, detail: dict) -> tuple[Optional[bool], str]:
    if kind == "agent_bundle":
        # The id is the accept's to mint — a staged one would be a forgeable claim
        # about a record yet to be born (SP-8's law).
        if "agent_id" in chain:
            return False, "a bundle's chain must not carry agent_id at stage"
        return True, ""
    if kind == "automation_draft" and str(detail.get("runs_as") or ""):
        if str(chain.get("agent_id") or ""):
            return True, ""
        return False, "detail names runs_as but the chain binds no agent_id"
    return None, ""


def _schema_real(kind: str, params: dict,
                 known_schemas: Optional[list] = None) -> tuple[Optional[bool], str]:
    if kind not in ("agent_draft", "agent_bundle"):
        return None, ""
    agent = params if kind == "agent_draft" else dict((params or {}).get("agent") or {})
    scope = str(agent.get("schema_scope") or "")
    if not scope:
        return True, ""             # no claim made — nothing to be wrong about
    if known_schemas is None:
        return None, ""             # unknowable offline; a failed probe is not an absence
    names = {str(s) for s in known_schemas}
    if scope in names:
        return True, ""
    return False, f"schema {scope!r} is not on this connection ({', '.join(sorted(names))})"


def _clock_right(chain: dict, detail: dict) -> tuple[Optional[bool], str]:
    """The stated first run sits ON a cron boundary in the chain's own clock —
    time-independent, so a recording scored months later still grades the same."""
    from aughor.automations.engine import next_fire_utc

    stated = str(detail.get("first_run") or "")
    crons = [str((c.get("config") or {}).get("cron") or "")
             for c in (chain.get("conditions") or []) if c.get("kind") == "schedule"]
    if not crons:
        return None, ""
    if not stated:
        return False, "a scheduled draft states no first run"
    try:
        t = datetime.fromisoformat(stated.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return False, f"first_run {stated!r} is not a readable instant"
    tz = str(chain.get("timezone") or detail.get("timezone") or "")
    for cron in crons:
        if next_fire_utc(cron, t - timedelta(seconds=1), tz) == t:
            return True, ""
    return False, (f"stated first run {stated} sits on no boundary of "
                   f"{crons} in {tz or 'UTC'}")


def _cost_shown(kind: str, detail: dict) -> tuple[Optional[bool], str]:
    if kind != "monitor_bundle":
        return None, ""
    if all(str(detail.get(k) or "") for k in ("watches", "sigma", "check_cadence")):
        return True, ""
    return False, "a monitor bundle must state what it watches, at what σ, how often"


def score_proposal(p, known_schemas: Optional[list] = None) -> dict:
    """Score ONE staged proposal row (a model-free structural read).

    ``p`` is a StagedProposal or any object/dict with kind/params/detail. Returns
    ``{"kind", "checks": {name: True|False|None}, "problems": [...]}``.
    """
    kind = str(getattr(p, "kind", None) or (p.get("kind") if isinstance(p, dict) else ""))
    params = dict(getattr(p, "params", None) or (p.get("params") if isinstance(p, dict) else {}) or {})
    detail = dict(getattr(p, "detail", None) or (p.get("detail") if isinstance(p, dict) else {}) or {})

    checks: dict = {k: None for k in _CHECKS}
    problems: list[str] = []

    def put(name: str, verdict: Optional[bool], why: str) -> None:
        checks[name] = verdict
        if verdict is False and why:
            problems.append(why)

    chain = _chain_of(kind, params)
    if chain is not None:
        put("validates", *_validates(kind, chain))
        put("open_choices_honest", *_open_choices_honest(chain, detail))
        put("runs_as_bound", *_runs_as_bound(kind, chain, detail))
        put("clock_right", *_clock_right(chain, detail))
    put("schema_real", *_schema_real(kind, params, known_schemas))
    put("cost_shown", *_cost_shown(kind, detail))
    return {"kind": kind, "checks": checks, "problems": problems}


def authoring_funnel(rows: Iterable) -> dict:
    """staged → accepted → finished_in_form → redrafted → rejected → lapsed → pending,
    per ISO week of staging, plus totals. A pure fold over proposal rows."""
    weekly: dict[str, dict] = {}
    total = {"staged": 0, "accepted": 0, "finished_in_form": 0, "redrafted": 0,
             "rejected": 0, "lapsed": 0, "pending": 0}

    def bucket_of(p) -> str:
        status = str(getattr(p, "status", ""))
        message = str(getattr(p, "status_message", "") or "")
        if status in ("accepted", "executed", "failed", "uncertain"):
            # a failed accept is still a human saying YES — the funnel measures
            # adoption of the drafts, not the doors behind them
            return "accepted"
        if status == "superseded":
            return "finished_in_form" if FINISHED_IN_FORM_MARK in message else "redrafted"
        if status == "rejected":
            return "rejected"
        if status == "expired":
            return "lapsed"
        return "pending"

    for p in rows:
        if str(getattr(p, "kind", "")) not in DRAFT_KINDS:
            continue
        try:
            created = datetime.fromisoformat(
                str(getattr(p, "created_at", "")).replace("Z", "+00:00"))
            year, week, _ = created.isocalendar()
            wk = f"{year}-W{week:02d}"
        except ValueError:
            wk = "unknown"
        b = weekly.setdefault(wk, {k: 0 for k in total})
        b["staged"] += 1
        total["staged"] += 1
        bucket = bucket_of(p)
        b[bucket] += 1
        total[bucket] += 1
    return {"weekly": dict(sorted(weekly.items())), "total": total}
