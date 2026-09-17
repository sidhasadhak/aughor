"""HB-2 — what a departure's numbers were measured from.

The departure gate judges text; these builders hand it the measurement the text departs
on, read from the stores that already hold it — an analysis's result rows, a promise's
stamp, a finding's query, an alert's reading — and, where the measurement can run again,
the call that re-executes it (law 1). Plus the two facts laws 5 and 6 need from those same
stores: the claim licence an analysis recorded, and who owns a metric whose readings
disagree.

Nothing here calls a model. Re-execution is bounded (``REMEASURE_MAX_QUERIES``) and runs
only when the gate decides a measurement is too old to count as taken at departure; every
reader is best-effort — a store it cannot read yields no measurement, and the gate records
what that means instead of guessing.
"""
from __future__ import annotations

import json
import re
from typing import Iterator, Optional

from aughor.govern.departure import Measurement
from aughor.kernel.errors import tolerate

#: At most this many stored queries are re-executed for one departure — the gate runs live
#: SQL, and one message must not fan out into a scan.
REMEASURE_MAX_QUERIES = 5

#: Cells read per result, for grounding and for re-execution alike.
MAX_ROWS_PER_RESULT = 500

#: The internal query label re-execution runs under (dunder: platform verification, the
#: convention the Briefing's receipt re-run already uses).
RERUN_LABEL = "__departure__"

_LICENCE_RE = re.compile(r"CLAIM LICENCE:\s*(descriptive|associational|predictive|causal)")
_ISO_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")


# ── an analysis ────────────────────────────────────────────────────────────────────

def measurement_for_analysis(investigation_id: str, conn_id: str = "") -> Optional[Measurement]:
    """The result rows a deep analysis or answer kept — every cell its prose may cite.
    Re-execution re-runs the stored queries whose cells grounded a claim."""
    inv = _analysis_record(investigation_id)
    if not inv:
        return None
    results: list[dict] = []
    _collect_results(inv.get("report"), results)
    _collect_results(inv.get("query_history"), results)
    connection = conn_id or str(inv.get("connection_id") or "")
    report = inv.get("report") if isinstance(inv.get("report"), dict) else {}

    def _again(claims: list) -> Optional[tuple]:
        from aughor.explorer.grounding import numeral_matches_measure
        chosen = [r for r in results if r["sql"]
                  and any(numeral_matches_measure(n, c) for n in claims for c in r["cells"])]
        if not chosen:
            return None
        cells = rerun_queries(connection, [r["sql"] for r in chosen[:REMEASURE_MAX_QUERIES]])
        return None if cells is None else (cells, [])

    return Measurement(
        source=f"analysis {investigation_id[:8]}",
        values=[c for r in results for c in r["cells"]],
        measured_at=str(inv.get("completed_at") or ""),
        as_of=_as_of_in(str(report.get("observation_period") or "")),
        remeasure=_again if connection and results else None,
        stale_note="" if results else "the analysis kept no query to re-execute")


def analysis_claim_facts(investigation_id: str) -> tuple[str, bool]:
    """(licence, refuted) — the claim licence the analysis recorded at intake
    ("CLAIM LICENCE: <type>", `agent/claim_type.py`'s decision), and whether an adversarial
    verification challenged its conclusion. ("", False) when nothing is recorded."""
    inv = _analysis_record(investigation_id)
    report = inv.get("report") if inv and isinstance(inv.get("report"), dict) else {}
    if not report:
        return "", False
    m = _LICENCE_RE.search(json.dumps(report, default=str))
    refuted = any("adversarial verification challenged" in str(g).lower()
                  for g in (report.get("data_gaps") or []))
    return (m.group(1) if m else ""), refuted


def _analysis_record(investigation_id: str) -> dict:
    if not investigation_id:
        return {}
    try:
        from aughor.db.history import get_investigation
        return get_investigation(investigation_id) or {}
    except Exception as exc:
        tolerate(exc, "departure basis: the analysis record is unreadable",
                 counter="departures.basis_analysis_unreadable")
        return {}


def _collect_results(obj, out: list, depth: int = 0) -> None:
    """Every stored ``{sql, rows}`` result inside a report or a query history."""
    if depth > 10:
        return
    if isinstance(obj, dict):
        rows = obj.get("rows")
        if isinstance(rows, list) and rows:
            from aughor.explorer.grounding import cell_values
            out.append({"sql": str(obj.get("sql") or ""),
                        "cells": cell_values(rows[:MAX_ROWS_PER_RESULT])})
        for value in obj.values():
            _collect_results(value, out, depth + 1)
    elif isinstance(obj, list):
        for value in obj:
            _collect_results(value, out, depth + 1)


def _as_of_in(period: str) -> str:
    """The first ISO date an observation period names ("2026-09-08 (most recent complete
    day…)"), or ""."""
    m = _ISO_DATE_RE.search(period or "")
    return m.group(1) if m else ""


# ── a finding ──────────────────────────────────────────────────────────────────────

def measurement_for_finding(finding_id: str, conn_id: str) -> Optional[Measurement]:
    """A stored explorer finding and the query that produced it. Findings keep their SQL,
    not their cells, so the measurement is always re-executed before its numbers leave."""
    finding = find_finding(finding_id, conn_id)
    if finding is None:
        return None
    sql = str(finding.get("sql") or "")
    return Measurement(
        source=f"finding {finding_id}",
        values=[],
        measured_at=str(finding.get("generated_at") or ""),
        remeasure=((lambda _claims: _cells_or_none(rerun_queries(conn_id, [sql])))
                   if sql and conn_id else None),
        stale_note="" if sql else "the finding kept no query to re-execute")


def find_finding(finding_id: str, conn_id: str) -> Optional[dict]:
    """A finding by id across the connection's own state and every per-schema run."""
    if not (finding_id and conn_id):
        return None
    try:
        from aughor.explorer.store import get_findings, schema_run_keys
        for key in [conn_id, *schema_run_keys(conn_id)]:
            for row in get_findings(key):
                if str(row.get("id", "")) == str(finding_id):
                    return row
    except Exception as exc:
        tolerate(exc, "departure basis: the finding store is unreadable",
                 counter="departures.basis_finding_unreadable")
    return None


def _cells_or_none(cells: Optional[list]) -> Optional[tuple]:
    return None if cells is None else (cells, [])


# ── a promise, a process, a rule ────────────────────────────────────────────────────

def measurement_for_promise(securable: str, conn_id: str) -> Optional[Measurement]:
    """A promise's stamp — objects, reached, breached, kept, open, overdue, its breach rate
    and the data's own as-of. Scoped to exactly that promise: a sibling promise's count is
    not a measurement of this one (the 2026-09-16 anchor stated the delivery promise's
    99,441 ORDERS as dispatch-promise order lines)."""
    kind, _, ident = str(securable or "").partition(":")
    if kind != "promise":
        return None
    found = _find_promise(ident, conn_id)
    if found is None:
        stamp = _hub_stamp(securable)
        if not stamp:
            return None
        rate = stamp.get("breach_rate")
        return Measurement(
            source=f"promise {ident}",
            values=[float(stamp[k]) for k in ("reached", "breached")
                    if isinstance(stamp.get(k), (int, float))],
            rates=[float(rate)] if isinstance(rate, (int, float)) else [],
            as_of=str(stamp.get("as_of") or ""),
            definition=f"promise {ident} (declared)",
            stale_note="a promise is re-measured by the ontology's measure pass, not at a send")
    process, promise = found
    values = [float(promise[k]) for k in ("objects", "reached", "breached", "kept", "open",
                                           "open_overdue")
              if isinstance(promise.get(k), (int, float))]
    rate = promise.get("breach_rate")
    return Measurement(
        source=f"promise {promise.get('name', '')} of {process.get('display_name') or process.get('id', '')}",
        values=values,
        rates=[float(rate)] if isinstance(rate, (int, float)) else [],
        measured_at=str(process.get("measured_at") or ""),
        as_of=str(promise.get("as_of") or ""),
        definition=f"promise {promise.get('name', '')} (declared)",
        stale_note="a promise is re-measured by the ontology's measure pass, not at a send")


def declared_thing(securable: str, conn_id: str) -> Optional[dict]:
    """``{kind, label, measured}`` for a declared promise, process or rule on the
    connection's cached ontology, or None when it is not declared there. A read of the
    cache — a departure never builds an ontology."""
    kind, _, ident = str(securable or "").partition(":")
    if kind == "promise":
        found = _find_promise(ident, conn_id)
        if found is None:
            # HB-3's reader of the same stamps — a promise it can read is declared and
            # measured wherever it lives.
            return ({"kind": "promise", "measured": True, "label": f"promise {ident}"}
                    if _hub_stamp(securable) else None)
        process, promise = found
        return {"kind": "promise", "measured": bool(promise.get("verified")),
                "label": f"promise {promise.get('name', '')} of "
                         f"{process.get('display_name') or process.get('id', '')}"}
    for _cid, graph in _graphs(conn_id):
        if kind == "process":
            thing = (getattr(graph, "processes", None) or {}).get(ident)
        elif kind == "rule":
            thing = (getattr(graph, "rules", None) or {}).get(ident)
        else:
            return None
        if thing is not None:
            return {"kind": kind, "measured": bool(getattr(thing, "verified", False)),
                    "label": f"{kind} {getattr(thing, 'display_name', '') or ident}"}
    return None


def _hub_stamp(securable: str) -> dict:
    """The promise's stamp through HB-3's reader (`hub.links.stamped_measures`, the one the
    links store files snapshots with) — the fallback when this connection's cached graphs
    do not hold the promise directly."""
    try:
        from aughor.hub.links import stamped_measures
        return stamped_measures(securable) or {}
    except Exception as exc:
        tolerate(exc, "departure basis: the hub's promise stamp is unreadable",
                 counter="departures.basis_stamp_unreadable")
        return {}


def _find_promise(ident: str, conn_id: str) -> Optional[tuple[dict, dict]]:
    process_id, _, name = ident.partition(".")
    if not (process_id and name):
        return None
    for _cid, graph in _graphs(conn_id):
        process = (getattr(graph, "processes", None) or {}).get(process_id)
        if process is None:
            continue
        try:
            from aughor.ontology.processes import describe_process
            described = describe_process(graph, process)
        except Exception as exc:
            tolerate(exc, "departure basis: a declared process could not be described",
                     counter="departures.basis_process_undescribed")
            continue
        for stage in described.get("stages", []) or []:
            promise = stage.get("promise")
            if isinstance(promise, dict) and promise.get("name") == name:
                return described, promise
    return None


def _graphs(conn_id: str) -> Iterator[tuple[str, object]]:
    """Every cached graph of the connection, across its schemas — a promise declared on one
    schema is invisible to a newest-graph read that lands on another."""
    try:
        from aughor.ontology.store import cached_ontology_scopes, load_latest_ontology
        scopes = cached_ontology_scopes()
    except Exception as exc:
        tolerate(exc, "departure basis: the ontology cache is unreadable",
                 counter="departures.basis_ontology_unreadable")
        return
    for cid, schema in scopes:
        if conn_id and cid != conn_id:
            continue
        try:
            graph = load_latest_ontology(cid, schema)
        except Exception as exc:
            tolerate(exc, "departure basis: a cached graph is unreadable",
                     counter="departures.basis_ontology_unreadable")
            continue
        if graph is not None:
            yield cid, graph


# ── alerts ──────────────────────────────────────────────────────────────────────────

def measurement_for_monitor_alert(alert, monitor=None) -> Measurement:
    """The reading a monitor alert fired on — its value, the previous one and the
    threshold, measured in the tick that dispatches it."""
    values = [float(v) for v in (getattr(alert, "current_value", None),
                                 getattr(alert, "previous_value", None),
                                 getattr(alert, "threshold", None))
              if isinstance(v, (int, float))]
    name = getattr(alert, "monitor_name", "") or getattr(monitor, "name", "") or "monitor"
    return Measurement(
        source=f"monitor '{name}'",
        values=values,
        measured_at=str(getattr(alert, "triggered_at", "") or ""),
        definition=f"monitor '{name}' (declared)",
        rendered=True,
        stale_note="a monitor alert is sent in the tick that measured it; a late send is not "
                   "re-executed")


def measurement_for_agent_alert(event, rule) -> Measurement:
    """The window an agent alert rule measured — its value, threshold and population."""
    values = [float(v) for v in (getattr(event, "value", None),
                                 getattr(event, "threshold", None),
                                 getattr(event, "population", None))
              if isinstance(v, (int, float))]
    name = getattr(rule, "name", "") or "alert rule"
    return Measurement(
        source=f"alert rule '{name}'",
        values=values,
        measured_at=str(getattr(event, "fired_at", "") or ""),
        definition=f"alert rule '{name}' (declared)",
        rendered=True,
        stale_note="an alert is sent in the tick that measured it")


# ── law 6 — who is asked ────────────────────────────────────────────────────────────

def owner_for_disagreement(disagreement: dict, conn_id: str) -> str:
    """The routable owner of the governed metric whose readings disagree — a principal
    string (``group:finance``, ``user:ana``) — or "" when the owner is display text or
    unset. Display text is never guessed into a person."""
    name = str((disagreement or {}).get("metric_name") or "")
    if not name:
        return ""
    try:
        from aughor.rbac.routing import owner_principal
        from aughor.semantic.metrics import get_metric
        metric = get_metric(name, connection_id=conn_id or None)
        return owner_principal(getattr(metric, "owner", "") or "") or ""
    except Exception as exc:
        tolerate(exc, "departure basis: the metric owner is unreadable",
                 counter="departures.basis_owner_unreadable")
        return ""


# ── re-execution ────────────────────────────────────────────────────────────────────

def rerun_queries(conn_id: str, queries: list[str]) -> Optional[list]:
    """Run stored queries again and return every numeric cell, or None when any of them
    cannot run (a partial re-measure would ground half a message in today's data and half
    in yesterday's)."""
    if not (conn_id and queries):
        return None
    from aughor.db.connection import open_connection_for
    from aughor.explorer.grounding import cell_values
    db = open_connection_for(conn_id)
    try:
        cells: list = []
        for sql in queries[:REMEASURE_MAX_QUERIES]:
            result = db.execute(RERUN_LABEL, sql)
            if getattr(result, "error", None):
                return None
            cells.extend(cell_values((getattr(result, "rows", None) or [])[:MAX_ROWS_PER_RESULT]))
        return cells
    finally:
        try:
            db.close()
        except Exception as exc:
            tolerate(exc, "departure basis: closing the re-execution connection failed",
                     counter="departures.basis_close_failed")
