"""What a pack proposes the day a connection is made — the 2027 study §P and §W phase 6, "it arrives
ready" (the close-out, C7): its TERMS, for a person to confirm, and its ALERTS, each with a backtest on
this connection, for a person to arm. Confirm, not configure; and nothing here arms itself.

**Terms.** A pack's words — a metric's title and aliases, an object's name and aliases — are written
into the connection's vocabulary (`ontology/vocabulary.py`) at source ``pack``: below a person's word
and this install's own mined evidence, above a model's guess. A pack term widens what a question can
match the day the pack is bound and reaches no prompt until a person confirms it, which promotes it
to ``human`` in place; a decline is a tombstone the next bind cannot resurrect. An object's terms are
proposed on the TABLE the pack's map matched it to (`packs/ontology_map.match_objects`), so they are
proposed on the first ontology build when no graph exists yet at bind time, and said so.

**Alerts.** A pack's watch with a MEASURED prior range (`PackMonitorPrior`, its band and where it was
measured) becomes a `monitor_bundle` proposal in the inbox per bounded side — a threshold monitor on
the metric below its low or above its high, plus the chain its breach fires, the exact shape the
Watcher stages (`monitors/sentinel.stage_alert`) and the inbox already knows how to arm. Each proposal
carries the prior's provenance and a BACKTEST of that band over the metric's own last year on this
connection (`monitors/backtest.py`), so the person reads "would have fired 3 times" before they arm
it — or why it could not be replayed. An unmeasured prior proposes nothing and says why (a band is
learned here or nowhere); so does a metric this connection has not registered (an armed monitor on it
would run nothing). Idempotent by (pack, connection, prior, side): a re-run stages nothing twice and
never resurrects a proposal a person resolved — the inbox's own rule.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import date
from typing import Any, Callable, Optional

from aughor.packs.models import Pack

#: The contract's duty that proposes definitions people confirm (`kernel/contract.py`: "people confirm
#: what a steward proposes") — the proposer of a pack's terms.
TERMS_PROPOSER = "steward"
#: A pack's alerts are the Watcher's kind of proposal, with the pack as their source.
ALERTS_PROPOSER = "watcher"
#: Why an object's terms wait for the build.
OBJECTS_WAIT = "object terms are proposed on the first ontology build, when the pack's map is matched to this connection's tables"


def _norm(term: Any) -> str:
    return " ".join(str(term or "").lower().split())


# ── terms ────────────────────────────────────────────────────────────────────────────────────

def pack_terms(pack: Pack, *, graph=None) -> list[dict[str, Any]]:
    """Every term the pack declares, as rows ``{subject_kind, subject_id, synonym, what}``: a
    metric's title and aliases on the metric; an object's name and aliases on the table the map
    matched it to on ``graph``. With no graph the objects' terms are not proposed (`OBJECTS_WAIT`)."""
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    def add(kind: str, subject: str, term: Any, what: str) -> None:
        t = _norm(term)
        if not t or not subject or t == _norm(subject) or t == _norm(subject.replace("_", " ")):
            return
        key = (kind, subject, t)
        if key in seen:
            return
        seen.add(key)
        rows.append({"subject_kind": kind, "subject_id": subject, "synonym": t, "what": what})

    for m in pack.metrics:
        for t in [m.title, *m.aliases]:
            add("metric", m.name, t, f"metric {m.name}")
    if graph is None:
        return rows
    try:
        from aughor.packs.ontology_map import match_objects, resolve_ontology
        po = resolve_ontology(pack.id) or pack.ontology
        matched = match_objects(po, graph) if po is not None else {}
    except Exception:  # noqa: BLE001 — a map that cannot be read proposes no object terms
        po, matched = pack.ontology, {}
    for obj in (po.objects if po is not None else []):
        eid = matched.get(obj.name)
        entity = graph.entities.get(eid) if eid else None
        tables = list(getattr(entity, "source_tables", None) or []) if entity is not None else []
        if not tables:
            continue
        table = str(tables[0]).split(".")[-1]
        for t in [obj.name, *obj.aliases]:
            add("table", table, t, f"object {obj.name} → {table}")
    return rows


def _term_states(pack: Pack, connection_id: str, *, graph=None) -> tuple[list[dict[str, Any]], set, dict]:
    from aughor.ontology import vocabulary as V
    declined = V.declined_synonyms(connection_id)
    existing = {(s.subject_kind, s.subject_id, s.synonym): s.source for s in V.synonyms_for(connection_id)}
    return pack_terms(pack, graph=graph), declined, existing


def _status_of(key: tuple, declined: set, existing: dict) -> str:
    if key in declined:
        return "declined"
    src = existing.get(key)
    if src == "human":
        return "confirmed"
    if src:
        return "proposed"
    return "not_proposed"


def propose_terms(pack: Pack, connection_id: str, *, schema_name: str = "", graph=None) -> dict[str, Any]:
    """Write the pack's terms into the connection's vocabulary at source ``pack`` — a term a person
    already confirmed, already holds from a stronger source, or declined is left as it is. Returns
    what was proposed, what already stood, what is confirmed and what was declined, each term with
    its status."""
    from aughor.ontology import vocabulary as V
    terms, declined, existing = _term_states(pack, connection_id, graph=graph)
    out: dict[str, Any] = {"pack": pack.id, "connection_id": connection_id, "schema_name": schema_name or "",
                           "declared": len(terms), "proposed": 0, "already": 0, "confirmed": 0, "declined": 0, "terms": []}
    for row in terms:
        key = (row["subject_kind"], row["subject_id"], row["synonym"])
        status = _status_of(key, declined, existing)
        if status == "declined":
            out["declined"] += 1
        elif status == "confirmed":
            out["confirmed"] += 1
        elif status == "proposed" and V._rank_index(existing[key]) <= V._rank_index(V.PACK_SOURCE):
            out["already"] += 1
        else:
            V.add_synonym(connection_id, row["subject_kind"], row["subject_id"], row["synonym"], source=V.PACK_SOURCE,
                          note=f"pack:{pack.id} — {row['what']}; proposed for confirmation")
            out["proposed"] += 1
            status = "proposed"
        out["terms"].append({**row, "status": status, "source": existing.get(key) or (V.PACK_SOURCE if status == "proposed" else "")})
    if graph is None:
        out["note"] = OBJECTS_WAIT
    out["rule"] = "a pack's term widens what a question can match at once and reaches no prompt until a person confirms it"
    return out


def terms_status(pack: Pack, connection_id: str, *, graph=None) -> dict[str, Any]:
    """What the pack proposed on this connection and what became of each — the phase's
    "definitions confirmed against proposed", counted. Read-only."""
    terms, declined, existing = _term_states(pack, connection_id, graph=graph)
    counts = {"declared": len(terms), "confirmed": 0, "pending": 0, "declined": 0, "not_proposed": 0}
    rows = []
    for row in terms:
        key = (row["subject_kind"], row["subject_id"], row["synonym"])
        status = _status_of(key, declined, existing)
        counts["pending" if status == "proposed" else status] += 1
        rows.append({**row, "status": status, "source": existing.get(key, "")})
    return {"pack": pack.id, "connection_id": connection_id, **counts, "terms": rows,
            **({"note": OBJECTS_WAIT} if graph is None else {})}


def confirm_term(connection_id: str, subject_kind: str, subject_id: str, synonym: str, *, by: str) -> dict[str, Any]:
    """A person confirms a proposed term: it becomes theirs (source ``human``) in place and reaches
    the prompt from the next question on."""
    from aughor.ontology import vocabulary as V
    s = V.add_synonym(connection_id, subject_kind, subject_id, synonym, source="human", note=f"confirmed by {by or 'a person'}")
    return {**s.to_dict(), "status": "confirmed"}


def decline_term(connection_id: str, subject_kind: str, subject_id: str, synonym: str, *, by: str, note: str = "") -> dict[str, Any]:
    """A person declines a proposed term: the row goes and a tombstone stays, so no later bind or
    scan brings it back."""
    from aughor.ontology import vocabulary as V
    stone = V.decline_synonym(connection_id, subject_kind, subject_id, synonym, by=by, note=note)
    return {**stone, "status": "declined"}


# ── alerts ───────────────────────────────────────────────────────────────────────────────────

RunSql = Callable[[str], tuple[list, list, Optional[str]]]

#: Why a prior stages nothing.
UNMEASURED = "unmeasured prior: the pack names the watch and no band — nothing to arm; a band is learned here or nowhere"


def alerts_run_id(pack_id: str, connection_id: str) -> str:
    return f"pack:{pack_id}:alerts:{connection_id}"


def _registered_metric(name: str, connection_id: str):
    from aughor.semantic.metrics import get_metric
    try:
        return get_metric(name, connection_id=connection_id) or get_metric(name)
    except Exception:  # noqa: BLE001 — an unreadable registry is "not registered", said below
        return None


def _fmt(value: Optional[float]) -> str:
    return "" if value is None else f"{float(value):g}"


def _backtest_dict(bt) -> dict[str, Any]:
    d = asdict(bt)
    d["count"] = bt.count
    d["firings"] = d.get("firings", [])[:12]
    return d


def _reason(label: str, pack_id: str, m, side: str, bound: float, bt) -> str:
    if m.low is not None and m.high is not None:
        band = f"{_fmt(m.low)}–{_fmt(m.high)}"
    else:
        band = f"at least {_fmt(m.low)}" if m.low is not None else f"at most {_fmt(m.high)}"
    unit = f" ({m.unit})" if m.unit else ""
    verb = "falls below" if side == "below" else "rises above"
    head = (f"{label}: the {pack_id} pack's prior range is {band}{unit}, measured on {', '.join(m.measured_on)}; "
            f"this watch fires when the value {verb} {_fmt(bound)}.")
    tail = f" Backtest on this connection: {bt.sentence}" if bt.ok else f" No backtest on this connection: {bt.reason}."
    return (head + tail + " Checked daily, SQL only — the deep analysis runs only when it fires. Proposed, not armed.")[:600]


def alert_proposals_for(pack: Pack, connection_id: str, *, run_sql: Optional[RunSql] = None,
                        today: Optional[date] = None) -> dict[str, Any]:
    """Stage one `monitor_bundle` proposal per bounded side of every MEASURED prior whose metric this
    connection has registered, each with the prior's provenance and its backtest here; say why every
    other prior stages nothing. Returns ``{staged, already_staged, skipped}``."""
    from aughor.actions.inbox import StagedProposal, stage_proposal
    from aughor.monitors.backtest import Backtest, backtest_monitor
    from aughor.monitors.models import Monitor
    from aughor.monitors.sentinel import CHECK_CRON, watch_chain
    from aughor.org.context import current_org_id

    titles = {pm.name: (pm.title or pm.name) for pm in pack.metrics}
    staged: list[dict[str, Any]] = []
    already: list[dict[str, Any]] = []
    skipped: dict[str, str] = {}
    for m in pack.monitors:
        mid = m.id or m.metric
        if not (m.metric or "").strip():
            skipped[mid] = "names no metric"
            continue
        if m.unmeasured or not m.measured_on or (m.low is None and m.high is None):
            skipped[mid] = UNMEASURED
            continue
        if _registered_metric(m.metric, connection_id) is None:
            skipped[mid] = (f"metric {m.metric!r} is not registered on this connection — an armed watch on it would run "
                            f"nothing; register it (the shopping list says what it needs) and propose again")
            continue
        label = titles.get(m.metric) or m.metric.replace("_", " ")
        for side, bound in (("below", m.low), ("above", m.high)):
            if bound is None:
                continue
            name = f"{label} {side} its prior range"
            monitor = {"conn_id": connection_id, "name": name, "metric_name": m.metric, "alert_on": "threshold_cross",
                       "warning_threshold": float(bound), "threshold_direction": side, "check_cron": CHECK_CRON}
            try:
                bt = backtest_monitor(Monitor(**monitor), run_sql=run_sql, today=today)
            except Exception as exc:  # noqa: BLE001 — a backtest that could not run is said, not invented
                bt = Backtest("", "", False, reason=f"the backtest could not run: {str(exc)[:160]}")
            chain, holes, open_choices = watch_chain(connection_id, name, label)
            prior = {"pack": pack.id, "id": mid, "metric": m.metric, "low": m.low, "high": m.high, "unit": m.unit,
                     "measured_on": list(m.measured_on), "sources": list(m.sources), "note": m.note, "description": m.description}
            proposal = StagedProposal(
                kind="monitor_bundle", org_id=current_org_id() or "", connection_id=connection_id,
                action_id=f"monitor:{name}+automation:{name}",
                params={"monitor": monitor, "automation": chain},
                detail={"to_fill": holes, "open_choices": open_choices, "watches": m.metric, "side": side,
                        "bound": float(bound), "check_cadence": "daily", "source": f"pack:{pack.id}",
                        "prior": prior, "backtest": _backtest_dict(bt)},
                reasoning=_reason(label, pack.id, m, side, float(bound), bt),
                proposer=ALERTS_PROPOSER, source=f"pack:{pack.id}",
                run_id=alerts_run_id(pack.id, connection_id), call_id=f"prior:{mid}:{side}")
            stored = stage_proposal(proposal)
            row = {"proposal_id": stored.id, "metric": m.metric, "side": side, "bound": float(bound),
                   "backtest": bt.sentence if bt.ok else f"no backtest: {bt.reason}", "measured_on": list(m.measured_on)}
            (staged if stored.id == proposal.id else already).append(row)
    return {"pack": pack.id, "connection_id": connection_id, "staged": staged, "already_staged": already, "skipped": skipped,
            "note": "proposed, not armed: accepting a proposal creates the monitor and the chain its breach fires"}


def alerts_status(pack: Pack, connection_id: str) -> dict[str, Any]:
    """Every alert this pack proposed on the connection, with its status in the inbox and its backtest
    sentence — what the day-one screen shows beside the priors."""
    from aughor.actions.inbox import list_proposals
    src = f"pack:{pack.id}"
    rows = [p for p in list_proposals(connection_id=connection_id, limit=500) if p.source == src and p.kind == "monitor_bundle"]
    by_status: dict[str, int] = {}
    out = []
    for p in rows:
        by_status[p.status] = by_status.get(p.status, 0) + 1
        bt = dict(p.detail.get("backtest") or {})
        out.append({"id": p.id, "metric": p.detail.get("watches", ""), "side": p.detail.get("side", ""),
                    "bound": p.detail.get("bound"), "status": p.status,
                    "backtest": bt.get("sentence") or (f"no backtest: {bt.get('reason')}" if bt.get("reason") else ""),
                    "measured_on": list((p.detail.get("prior") or {}).get("measured_on") or [])})
    return {"pack": pack.id, "connection_id": connection_id, "proposals": out, "by_status": by_status}


# ── the day a pack is bound ──────────────────────────────────────────────────────────────────

def _tolerated(fn: Callable[[], dict], what: str, connection_id: str) -> dict[str, Any]:
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 — the binding stands; what could not be proposed is said
        from aughor.kernel.errors import tolerate
        tolerate(exc, f"a bound pack's {what} could not be proposed", counter=f"packs.connect.{what}", conn_id=connection_id)
        return {"note": f"{what} could not be proposed: {str(exc)[:160]}"}


def on_connect(pack_id: str, connection_id: str, *, schema_name: str = "", graph=None,
               run_sql: Optional[RunSql] = None, today: Optional[date] = None) -> dict[str, Any]:
    """Everything a pack proposes when it is bound to a connection: its terms for confirmation and its
    alerts with their backtests. Best-effort in both halves — each says what it could not do."""
    from aughor.packs.ontology_map import load_pack_by_id
    pack = load_pack_by_id(pack_id)
    if pack is None:
        return {"pack": pack_id, "connection_id": connection_id, "note": f"no pack {pack_id!r} could be loaded; nothing proposed"}
    if graph is None:
        try:
            from aughor.ontology.store import load_latest_ontology
            graph = load_latest_ontology(connection_id, schema_name or None)
        except Exception:  # noqa: BLE001 — no graph yet: the objects' terms wait for the build, said
            graph = None
    return {"pack": pack_id, "connection_id": connection_id,
            "terms": _tolerated(lambda: propose_terms(pack, connection_id, schema_name=schema_name, graph=graph), "terms", connection_id),
            "alerts": _tolerated(lambda: alert_proposals_for(pack, connection_id, run_sql=run_sql, today=today), "alerts", connection_id)}
