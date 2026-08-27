"""The analyst — deep analysis as a conversation, not a script (CA-3).

The deep dive that set this arc found the same defect twice: a fixed phase script
narrates a shape code chose. The model had two decision points, both before any row
existed, and no result-reactive step — the answer to "why is Direkteingabe up?" was
three SQL slices away and nobody was allowed to take them. the winning grammar was
slice, *see*, slice again.

This module puts the model where the decisions are. The deterministic phase library —
baseline, decomposition, cross-section, the premise probe, the z-score
gate — is preserved verbatim as TOOL BODIES, with every CA-0/CA-2 guard still inside
(the fan-out re-plan, the partial-period verdicts, the self-comparison refusal, the
minimum-baseline rule, `execute_guarded` under everything). What stops being scripted
is the SEQUENCE: `run_tool_loop` lets the model choose the next slice after seeing the
last one, change grain, dimension or window mid-flight, and stop by the analyst's rule
— *stop when a cause is named with its size, or when you can say what the data cannot
tell and what to check next*.

The intake still runs first, once: it is the spec anchor (metric resolution, the
coverage clamp, the no-prior-period verdict, follow-up anchoring), and its verdicts are
handed to the model as STATE, not re-derived per tool. The evidence log is the loop's
tool results — each phase a tool produced, plus the model's own closing statement —
and the narrator (the synthesis node, unchanged, with all of CA-0's disclosures and
CA-2's confidence ceiling) writes the report from it. Budget lives on `ModelProfile`
(`deep_loop_steps`) — a knob, not a constant, per the roadmap's §5.

Layering: this module sits beside `investigate.py` inside the agent and imports only
its public surface (the phase nodes, the public condensation and baseline-rule
aliases). It knows nothing about HTTP — the router streams it exactly the way it
streams a converse turn.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Callable, Optional

from aughor.agent.tool_loop import LoopResult, LoopStep, ToolSpec, run_tool_loop

logger = logging.getLogger(__name__)

#: What a tool reports while it runs — the same ``(frame_type, payload)`` vocabulary
#: the converse tools use; a no-op default keeps the module usable from sync callers.
Emit = Callable[[str, dict], None]


def _noop_emit(frame_type: str, payload: dict) -> None:
    return None


# ── The turn ──────────────────────────────────────────────────────────────────


@dataclass
class AnalystTurn:
    """One deep turn's mutable context: the graph-shaped state the phase bodies read,
    the connection, and the emit channel the frames stream through.

    The state dict is the SAME shape the phase script seeds (`AgentState`), because the
    tool bodies ARE the phase nodes — a synthetic state is what lets them run outside
    the graph without forking a line of their logic."""

    connection_id: str
    conn: Any
    state: dict
    emit: Emit = _noop_emit
    #: Phases already streamed (so a tool that appends two streams two).
    emitted_phases: int = 0
    #: Tools that produced at least one phase — the "did any evidence land" signal.
    phase_tools_run: list[str] = field(default_factory=list)
    #: Rows returned by tools that do NOT build a phase — `run_sql` above all. The
    #: report's no-data floor counts phase FINDINGS, so an analyst that answered from
    #: an ad-hoc query left it looking at nothing and the run was declared a total
    #: failure over its own correct numbers. This is the evidence it could not see.
    evidence_rows: int = 0

    @property
    def intake(self) -> dict:
        return self.state.get("_ada_intake") or {}

    def merge(self, node_return: dict, *, tool: str) -> list[dict]:
        """Fold a phase node's return into the turn state and stream any NEW phases
        as ``phase_complete`` frames — the same wire shape the graph path emits, so
        CA-1's parts renderer draws the analyst's slices exactly as it draws the
        script's."""
        self.state.update(node_return or {})
        phases = self.state.get("investigation_phases") or []
        fresh = phases[self.emitted_phases:]
        for _ in fresh:
            self.emitted_phases += 1
            self.emit("phase_complete", {"phase": phases[self.emitted_phases - 1],
                                         "all_phases": phases})
        if fresh:
            self.phase_tools_run.append(tool)
        return fresh


#: Date bounds and simple equality filters in a WHERE clause — the two things that make one
#: ad-hoc cut different from another of the same SHAPE. Bounded and anchored; never a parser.
_ADHOC_DATE_RE = re.compile(r"""[><]=?\s*(?:TIMESTAMP\s*)?['"](\d{4}-\d{2}-\d{2})""", re.I)
_ADHOC_EQ_RE = re.compile(r"""(?:\w+\.)?(\w+)\s*=\s*['"]([^'"]{1,40})['"]""")
_ADHOC_DATEY = re.compile(r"(_at|date|day|month|year|period)$", re.I)


def _adhoc_scope(sql: str) -> str:
    """The date window and equality filters of an ad-hoc query, as a short qualifier.

    The title below is derived from the RESULT SHAPE, so two queries returning the same columns
    get the same name however differently they were scoped. That is harmless until the loop does
    what a good analyst does and runs one cut over two periods: the report then shows
    "returned_cost by product_brand" twice, with different numbers and nothing saying one is
    February and the other January — an observation/comparison PAIR reads as a repeat. (It read
    that way to me, and I called it redundant compute before reading the WHERE clauses.)

    Best-effort by construction: an unparsed scope yields "" and the title is exactly what it
    was before.
    """
    try:
        text = " ".join((sql or "").split())
        if not text:
            return ""
        dates = _ADHOC_DATE_RE.findall(text)
        parts: list[str] = []
        if dates:
            uniq = list(dict.fromkeys(dates))
            parts.append(uniq[0] if len(uniq) == 1 else f"{uniq[0]} → {uniq[-1]}")
        for col, val in _ADHOC_EQ_RE.findall(text):
            # A status/date equality is usually the METRIC's own definition (the CASE WHEN), not
            # the cut's scope — naming it would title every phase with the same word.
            if _ADHOC_DATEY.search(col) or col.lower() in ("status", "state"):
                continue
            piece = f"{col} = {val}"
            if piece not in parts:
                parts.append(piece)
            if len(parts) >= 3:
                break
        return ", ".join(parts)[:60]
    except Exception:
        return ""


def _adhoc_title(columns: list, question: str, sql: str = "") -> str:
    """A name for a query the model framed itself. It supplies no title — the phase
    tools get theirs from a plan — so it comes from the shape of what came back, plus the
    SCOPE that distinguishes it from another cut of the same shape."""
    cols = [str(c) for c in (columns or []) if str(c).strip()]
    if len(cols) == 2:
        base = f"{cols[1]} by {cols[0]}"
    elif len(cols) == 1:
        base = str(cols[0])
    else:
        return (question or "Query result").strip()[:80]
    scope = _adhoc_scope(sql)
    return f"{base} — {scope}" if scope else base


def _record_evidence(turn: "AnalystTurn", args: dict, result: Any) -> Any:
    """Pass a tool result through, and make its rows part of the investigation.

    A query the model framed itself is evidence exactly as a phase tool's query is —
    but only phase tools built a phase, so `run_sql` rows reached the narrator's prose
    and nothing else. A deep turn answered that way rendered as three sentences with no
    table and no chart, while the QUICK path, which renders its rows directly, showed
    the whole breakdown. Deep looked thinner than quick for asking the same question.

    So the rows become a finding in a phase of their own, and stream as one: the report
    draws it with the same organs it draws every other finding, and the run's own SQL is
    on the page instead of only in the receipt. One phase per query — the loop's slices
    ARE the story of the turn, and folding them into a single box would hide that it
    took four cuts to get there.
    """
    try:
        if isinstance(result, dict) and result.get("rows"):
            rows = result["rows"]
            turn.evidence_rows += len(rows)
            cols = result.get("columns") or []
            n = len(turn.phase_tools_run) + 1
            turn.merge({"investigation_phases": (turn.state.get("investigation_phases") or []) + [{
                "phase_id": f"adhoc_{n}",
                "phase_name": _adhoc_title(cols, turn.state.get("question", ""),
                                           (args or {}).get("sql", "")),
                "phase_icon": "🔎",
                "status": "complete",
                # Empty: the narrator writes the prose from the evidence log, and a
                # summary invented here would be a second voice on the same rows.
                "summary": "",
                "findings": [{
                    "finding_id": f"adhoc_{n}_1",
                    "title": _adhoc_title(cols, turn.state.get("question", ""),
                                          (args or {}).get("sql", "")),
                    "sql": (args or {}).get("sql", ""),
                    "columns": cols,
                    "rows": rows[:50],
                    "row_count": len(rows),
                    "error": None,
                    "interpretation": "",
                    "key_numbers": [],
                    "chart_type": "auto",
                    "stat_note": None,
                    "is_significant": False,
                }],
                "skipped_reason": None,
                "caveats": [],
            }]}, tool="run_sql")
    except Exception as exc:                      # noqa: BLE001 — never break a tool
        from aughor.kernel.errors import tolerate
        tolerate(exc, "ad-hoc evidence capture is best-effort; the tool result stands",
                 counter="analyst.evidence_capture")
    return result


def _spec_overrides(intake: dict, args: dict) -> dict:
    """A COPY of the intake spec with the model's per-call latitude applied — window,
    metric — never a mutation: the turn's anchor spec survives a tool that explored a
    different window. The guards downstream (temporal, fan-out, partial-period) apply
    to the overridden spec exactly as they would to the anchored one."""
    spec = dict(intake)
    for src, dst in (("observation_start", "observation_start"),
                     ("observation_end", "observation_end"),
                     ("comparison_start", "comparison_start"),
                     ("comparison_end", "comparison_end")):
        v = str(args.get(src) or "").strip()
        if v:
            spec[dst] = v
    if args.get("observation_start") or args.get("observation_end"):
        spec["observation_label"] = (
            f"{spec.get('observation_start', '')} → {spec.get('observation_end', '')}")
    if args.get("comparison_start") or args.get("comparison_end"):
        spec["comparison_label"] = (
            f"{spec.get('comparison_start', '')} → {spec.get('comparison_end', '')}")
        spec["no_prior_period"] = False
    metric_sql = str(args.get("metric_sql") or "").strip()
    if metric_sql:
        spec["metric_sql"] = metric_sql
        spec["metric_label"] = str(args.get("metric_label") or "").strip() or metric_sql
    return spec


def _phase_payload(fresh: list[dict]) -> dict:
    """What a phase tool hands back to the model: the same deterministic,
    number-preserving condensation synthesis will read, plus the carry signal.
    The model reasons over exactly the evidence the narrator later cites."""
    from aughor.agent.investigate import condense_phase_evidence

    if not fresh:
        return {"note": "the phase produced no new evidence"}
    out: list[dict] = []
    for p in fresh:
        out.append({
            "phase_id": p.get("phase_id"),
            "status": p.get("status"),
            "summary": p.get("summary"),
            "evidence": condense_phase_evidence(p),
        })
    return {"phases": out}


# ── Deterministic tool bodies (no LLM inside) ─────────────────────────────────


_IDENT_RE = re.compile(r"^[A-Za-z_][\w$ .-]*$")


def _qident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _qtable(name: str) -> str:
    return ".".join(_qident(p) for p in name.split("."))


def _guarded(conn, sql: str, query_id: str):
    """Model-authored (or model-influenced) SQL goes through the guard battery — the
    Verifier chokepoint every other path uses."""
    from aughor.sql.executor import execute_guarded
    return execute_guarded(conn, sql, query_id=query_id)


def _probe(conn, sql: str, query_id: str):
    """A CODE-built probe (quoted identifiers + escaped literal, LIMIT-bounded) runs
    direct, the way the guard battery's own probes do — running a probe through the
    battery would have the guards probing the probes."""
    return conn.execute(query_id, sql)


def premise_check(turn: AnalystTurn, args: dict) -> dict:
    """The three-way window probe (obs vs comp vs prior), deterministic — one SQL, no
    model. The same pattern the baseline phase runs inline; as a TOOL the analyst can fire
    it the moment a premise smells wrong instead of waiting for the baseline phase.
    On a confirmed mismatch the turn's spec is RE-ANCHORED, exactly as the inline
    check re-anchors downstream phases."""
    from aughor.agent.investigate import detect_question_direction

    intake = turn.intake
    question = str(args.get("question") or turn.state.get("question") or "")
    expected = detect_question_direction(question)
    obs_s, obs_e = intake.get("observation_start"), intake.get("observation_end")
    comp_s, comp_e = intake.get("comparison_start"), intake.get("comparison_end")
    date_col, metric_table = intake.get("date_column"), intake.get("metric_table")
    metric_sql = intake.get("metric_sql")
    if not (obs_s and obs_e and comp_s and comp_e and date_col and metric_table and metric_sql):
        return {"verdict": "not_assessable",
                "reason": "the spec lacks a complete observation/comparison window"}
    if intake.get("no_prior_period"):
        return {"verdict": "no_prior_period",
                "reason": "no period before the observation window exists in the data — "
                          "describe the window; never decompose it against itself"}

    cs, ce = date.fromisoformat(comp_s[:10]), date.fromisoformat(comp_e[:10])
    span = (ce - cs).days
    prior_end = cs - timedelta(days=1)
    prior_start = prior_end - timedelta(days=span)

    # Three scalar subqueries, one per window — NOT the conditional-aggregation form:
    # the intake's metric_sql is itself an aggregate (`SUM(revenue)`), and wrapping an
    # aggregate in `SUM(CASE WHEN … THEN {metric_sql} …)` nests aggregates, which is a
    # SQL error the inline check could only swallow. A scalar subquery per window is
    # correct for ANY aggregate metric — SUM, COUNT(DISTINCT …), AVG, a ratio.
    def _window(start: str, end: str) -> str:
        cond = (f"CAST({date_col} AS DATE) >= DATE '{start}' "
                f"AND CAST({date_col} AS DATE) <= DATE '{end}'")
        if intake.get("active_filter"):
            cond += f" AND ({intake['active_filter']})"
        return f"(SELECT {metric_sql} FROM {metric_table} WHERE {cond})"

    sql = (
        f"SELECT {_window(obs_s, obs_e)} AS obs_value, "
        f"{_window(comp_s, comp_e)} AS comp_value, "
        f"{_window(prior_start.isoformat(), prior_end.isoformat())} AS prior_value"
    )
    res = _guarded(turn.conn, sql, "analyst_premise_check")
    if res.error or not res.rows or len(res.rows[0]) < 3:
        return {"verdict": "not_assessable", "reason": res.error or "the probe returned no row"}
    try:
        obs_v, comp_v, prior_v = (float(res.rows[0][i] or 0) for i in range(3))
    except (TypeError, ValueError):
        return {"verdict": "not_assessable", "reason": "non-numeric probe values"}
    out = {"obs_value": obs_v, "comp_value": comp_v, "prior_value": prior_v,
           "observation": f"{obs_s} → {obs_e}", "comparison": f"{comp_s} → {comp_e}",
           "prior": f"{prior_start.isoformat()} → {prior_end.isoformat()}"}
    if comp_v == 0 or obs_v == comp_v:
        return {**out, "verdict": "not_assessable", "reason": "degenerate values"}
    obs_dir = "up" if obs_v > comp_v else "down"
    if expected is None:
        return {**out, "verdict": "described",
                "direction": obs_dir,
                "change_pct": round((obs_v - comp_v) / abs(comp_v) * 100, 1)}
    if obs_dir == expected:
        return {**out, "verdict": "premise_holds", "direction": obs_dir,
                "change_pct": round((obs_v - comp_v) / abs(comp_v) * 100, 1)}
    # Mismatch — does the comparison window show the asked-about move vs prior?
    if prior_v != 0 and (("down" if comp_v < prior_v else "up") == expected):
        redirect_pct = (comp_v - prior_v) / abs(prior_v) * 100
        spec = dict(intake)
        spec.update({
            "observation_start": comp_s, "observation_end": comp_e,
            "observation_label": intake.get("comparison_label") or f"{comp_s} → {comp_e}",
            "comparison_start": prior_start.isoformat(), "comparison_end": prior_end.isoformat(),
            "comparison_label": f"Prior period ({prior_start.isoformat()} → {prior_end.isoformat()})",
            "_premise_corrected": True,
        })
        turn.state["_ada_intake"] = spec
        return {**out, "verdict": "window_corrected",
                "note": (f"the question's move actually occurred in the comparison window "
                         f"({redirect_pct:+.1f}% vs prior); the spec has been RE-ANCHORED — "
                         "run the phases now and they will use the corrected windows"),
                "redirect_pct": round(redirect_pct, 1)}
    return {**out, "verdict": "premise_contradicted", "direction": obs_dir,
            "note": ("the observation window moved OPPOSITE to the question's premise; "
                     "say so plainly rather than explaining a move that did not happen")}


def z_score(turn: AnalystTurn, args: dict) -> dict:
    """Deterministic significance over a query's series — stats.py, never the model's
    own arithmetic, with CA-2's minimum-baseline rule applied: below
    ``MIN_BASELINE_PERIODS`` periods a z is a description, not a verdict."""
    from aughor.agent.investigate import MIN_BASELINE_PERIODS
    from aughor.tools.stats import analyze_query_result

    sql = str(args.get("sql") or "").strip()
    if not sql:
        return {"error": "no sql supplied — pass the series query to test"}
    res = _guarded(turn.conn, sql, "analyst_z_score")
    if res.error:
        return {"error": res.error}
    rows = list(res.rows or [])
    if len(rows) < MIN_BASELINE_PERIODS:
        return {"verdict": "not_assessable",
                "n_periods": len(rows),
                "reason": (f"the series holds {len(rows)} period(s); at least "
                           f"{MIN_BASELINE_PERIODS} are needed for a z to be a verdict — "
                           "describe the change instead of testing it")}
    sigma = None
    for sr in analyze_query_result(list(res.columns or []), rows, sql):
        if sr.sigma is not None and (sigma is None or float(sr.sigma) > sigma):
            sigma = float(sr.sigma)
    if sigma is None:
        return {"verdict": "not_assessable", "n_periods": len(rows),
                "reason": "no testable numeric series in the result"}
    return {"verdict": "significant" if sigma >= 2.0 else "within_normal_variance",
            "sigma": round(sigma, 2), "n_periods": len(rows)}


_VALUE_PROBE_TABLES = 6
_VALUE_PROBE_COLUMNS = 16


def value_lookup(turn: AnalystTurn, args: dict) -> dict:
    """Where a VALUE lives — which column actually stores this entity. The wrong-column
    conjunction was the specimen's recurring zero-row trap (Direkteingabe lives at
    CHANNEL_LVL_1, the filter said LVL_0); this makes the binding a one-call lookup
    instead of a guessed WHERE clause. Bounded LIMIT-1 probes per text column."""
    value = str(args.get("value") or "").strip()
    if not value:
        return {"error": "no value supplied"}
    safe = value.replace("'", "''")

    from aughor.db.schema_render import parse_schema_tables
    tables = parse_schema_tables(turn.state.get("schema_context") or "")
    wanted = str(args.get("table") or "").strip()
    candidates: list[str] = []
    if wanted:
        bare = wanted.rsplit(".", 1)[-1].lower()
        candidates = [t for t in tables
                      if t.lower() == wanted.lower() or t.rsplit(".", 1)[-1].lower() == bare]
    else:
        # The spec's own tables first — the metric table and each dimension's home.
        intake = turn.intake
        seen: set[str] = set()
        for name in ([intake.get("metric_table") or ""]
                     + [d.rsplit(".", 1)[0] for d in (intake.get("dimensions") or []) if "." in d]):
            bare = name.rsplit(".", 1)[-1].lower()
            for t in tables:
                if bare and t.rsplit(".", 1)[-1].lower() == bare and t not in seen:
                    seen.add(t)
                    candidates.append(t)
        for t in tables:
            if t not in seen:
                candidates.append(t)
    candidates = candidates[:_VALUE_PROBE_TABLES]

    hits: list[dict] = []
    probed = 0
    for t in candidates:
        for col in (tables.get(t) or [])[:_VALUE_PROBE_COLUMNS]:
            probed += 1
            try:
                res = _probe(
                    turn.conn,
                    f"SELECT COUNT(*) FROM {_qtable(t)} "
                    f"WHERE LOWER(CAST({_qident(col)} AS VARCHAR)) = LOWER('{safe}') ",
                    "__analyst_value_lookup__")
            except Exception as exc:
                from aughor.kernel.errors import tolerate
                tolerate(exc, "one value-lookup probe failing must not sink the sweep",
                         counter="analyst.value_lookup_probe")
                continue
            if res.error or not res.rows:
                continue
            n = _as_count(res.rows[0][0])
            if n is None:
                continue
            if n > 0:
                hits.append({"table": t, "column": col, "rows": n})
    if hits:
        return {"value": value, "found_in": hits}
    return {"value": value, "found_in": [],
            "note": (f"'{value}' is stored in NO probed column ({probed} probes over "
                     f"{len(candidates)} table(s)) — the segment is absent, not zero; "
                     "say so rather than filtering on a guessed column")}


def _as_count(v) -> Optional[int]:
    try:
        return int(str(v))
    except (TypeError, ValueError):
        return None


_PROFILE_TOP_VALUES = 8


def profile_column(turn: AnalystTurn, args: dict) -> dict:
    """One column's shape — count, nulls, distincts, range, top values — as three
    guarded queries. What the analyst reads before choosing a dimension or trusting
    a filter, instead of assuming the column is what its name suggests."""
    table = str(args.get("table") or "").strip()
    column = str(args.get("column") or "").strip()
    if not table or not column:
        return {"error": "pass both table and column"}
    if not _IDENT_RE.match(table.replace('"', "")) or not _IDENT_RE.match(column.replace('"', "")):
        return {"error": "table/column must be plain identifiers"}
    qt, qc = _qtable(table), _qident(column)
    base = _probe(
        turn.conn,
        f"SELECT COUNT(*) AS n, COUNT({qc}) AS non_null, COUNT(DISTINCT {qc}) AS distinct_values, "
        f"MIN({qc}) AS min_value, MAX({qc}) AS max_value FROM {qt}",
        "__analyst_profile_column__")
    if base.error or not base.rows:
        return {"error": base.error or "the profile query returned nothing"}
    def _int(v):
        # Connections stringify values on the wire; the model (and the tests) should
        # see counts as numbers.
        try:
            return int(str(v))
        except (TypeError, ValueError):
            return v

    n, non_null, distinct, vmin, vmax = base.rows[0][:5]
    n, non_null, distinct = _int(n), _int(non_null), _int(distinct)
    out = {
        "table": table, "column": column,
        "rows": n, "non_null": non_null,
        "null_count": (n - non_null) if isinstance(n, int) and isinstance(non_null, int) else None,
        "distinct_values": distinct, "min": vmin, "max": vmax,
    }
    top = _probe(
        turn.conn,
        f"SELECT CAST({qc} AS VARCHAR) AS value, COUNT(*) AS n FROM {qt} "
        f"WHERE {qc} IS NOT NULL GROUP BY 1 ORDER BY n DESC LIMIT {_PROFILE_TOP_VALUES}",
        "__analyst_profile_column__")
    if not top.error and top.rows:
        out["top_values"] = [{"value": r[0], "n": r[1]} for r in top.rows]
    return out


# ── Phase tools (the library as bodies, the sequence as the model's) ──────────


def baseline(turn: AnalystTurn, args: dict) -> dict:
    from aughor.agent.investigate import ada_baseline

    state = dict(turn.state)
    state["_ada_intake"] = _spec_overrides(turn.intake, args)
    fresh = turn.merge(ada_baseline(state, turn.conn), tool="baseline")
    out = _phase_payload(fresh)
    if turn.state.get("_baseline_sigma") is not None:
        out["sigma"] = turn.state["_baseline_sigma"]
        out["significant"] = turn.state.get("_baseline_significant")
    return out


def decompose(turn: AnalystTurn, args: dict) -> dict:
    from aughor.agent.investigate import ada_decompose

    state = dict(turn.state)
    spec = _spec_overrides(turn.intake, args)
    dim = str(args.get("dimension") or "").strip()
    if dim:
        dims = list(spec.get("dimensions") or [])
        matched = [d for d in dims if dim.lower() in d.lower()]
        spec["dimensions"] = (matched or [dim]) + [d for d in dims if d not in matched]
    state["_ada_intake"] = spec
    return _phase_payload(turn.merge(ada_decompose(state, turn.conn), tool="decompose"))


def cross_section(turn: AnalystTurn, args: dict) -> dict:
    from aughor.agent.investigate import ada_cross_section

    state = dict(turn.state)
    state["_ada_intake"] = _spec_overrides(turn.intake, args)
    dim = str(args.get("dimension") or "").strip()
    kwargs: dict = {}
    if dim:
        dims = list(turn.intake.get("dimensions") or [])
        matched = [d for d in dims if dim.lower() in d.lower()]
        kwargs["dims_override"] = matched or [dim]
    return _phase_payload(
        turn.merge(ada_cross_section(state, turn.conn, **kwargs), tool="cross_section"))


# ── The roster ────────────────────────────────────────────────────────────────

_WINDOW_PROPS = {
    "observation_start": {"type": "string", "description": "ISO date — override the spec's observation start."},
    "observation_end": {"type": "string", "description": "ISO date — override the spec's observation end."},
    "comparison_start": {"type": "string", "description": "ISO date — override the comparison start."},
    "comparison_end": {"type": "string", "description": "ISO date — override the comparison end."},
    "metric_sql": {"type": "string", "description": "Override the metric aggregation expression (rare — the spec's metric is already resolved)."},
    "metric_label": {"type": "string", "description": "Human label for an overridden metric."},
}


def analyst_tools(turn: AnalystTurn, *, emit: Optional[Emit] = None,
                  session_id: str = "", canvas_id: Optional[str] = None,
                  user_question: str = "") -> list[ToolSpec]:
    """The analyst's roster: the phase library as tools, the deterministic probes, the
    warehouse primitives, and the platform reads. Bound by closure like every converse
    tool — the model cannot name a connection, session or spec it was not given."""
    from aughor.agent.converse_tools import describe_table, list_tables, run_sql
    from aughor.agent.platform_tools import platform_tools

    cid = turn.connection_id
    return [
        ToolSpec(
            name="baseline",
            description=(
                "Establish the metric's baseline: level and trend over the spec's "
                "observation window vs its comparison window, with a code-computed "
                "z-score. The full guard battery applies. Run this FIRST for a "
                "why-did-it-change question unless the premise itself is in doubt. "
                "Optionally override the windows or metric to look at a different slice."
            ),
            parameters={"type": "object", "properties": dict(_WINDOW_PROPS)},
            run=lambda a: baseline(turn, a),
        ),
        ToolSpec(
            name="decompose",
            description=(
                "Split the metric's change across ONE dimension's segments (volume vs "
                "value, channel, device …) to see which segment carries the move. Pass "
                "`dimension` to choose the cut — after seeing a result you may call this "
                "again with a different dimension or window. Guarded like every phase."
            ),
            parameters={"type": "object", "properties": {
                "dimension": {"type": "string",
                              "description": "The dimension (column or table.column) to decompose across."},
                **_WINDOW_PROPS,
            }},
            run=lambda a: decompose(turn, a),
        ),
        ToolSpec(
            name="cross_section",
            description=(
                "Scan ACROSS segments of a dimension for where the metric is weakest / "
                "strongest right now (a where/which question, not a change question). "
                "Pass `dimension` to pin the cut; omit it to scan the spec's dimensions."
            ),
            parameters={"type": "object", "properties": {
                "dimension": {"type": "string", "description": "The dimension to cut across."},
                **_WINDOW_PROPS,
            }},
            run=lambda a: cross_section(turn, a),
        ),
        ToolSpec(
            name="premise_check",
            description=(
                "Verify the question's premise deterministically: one three-way query "
                "(observation vs comparison vs the period before that). If the asked-about "
                "move actually happened in the comparison window, the spec is re-anchored "
                "for every later phase. Cheap — run it early when the premise is load-bearing."
            ),
            parameters={"type": "object", "properties": {}},
            run=lambda a: premise_check(turn, a),
        ),
        ToolSpec(
            name="z_score",
            description=(
                "Test a time series for statistical significance with code, not prose: "
                "pass a query returning period + value rows; you get sigma and a verdict. "
                "Below the minimum baseline length the honest answer is 'not assessable' — "
                "report it as a description, never a significance claim."
            ),
            parameters={"type": "object", "properties": {
                "sql": {"type": "string", "description": "A SELECT returning a period column and a numeric column."},
            }, "required": ["sql"]},
            run=lambda a: z_score(turn, a),
        ),
        ToolSpec(
            name="value_lookup",
            description=(
                "Find which column actually STORES a value ('Direkteingabe', 'iOS', a "
                "campaign name) before filtering on it. A filter on the wrong column of a "
                "hierarchy returns zero rows that read as 'no data' — this lookup is how "
                "you avoid that trap. Returns every (table, column) that holds the value."
            ),
            parameters={"type": "object", "properties": {
                "value": {"type": "string", "description": "The literal value to locate."},
                "table": {"type": "string", "description": "Optional: restrict the search to one table."},
            }, "required": ["value"]},
            run=lambda a: value_lookup(turn, a),
        ),
        ToolSpec(
            name="profile_column",
            description=(
                "One column's shape — row count, nulls, distinct values, min/max, top "
                "values — before you choose it as a dimension or trust a filter on it."
            ),
            parameters={"type": "object", "properties": {
                "table": {"type": "string"}, "column": {"type": "string"},
            }, "required": ["table", "column"]},
            run=lambda a: profile_column(turn, a),
        ),
        ToolSpec(
            name="run_sql",
            description=(
                "Run one SELECT you have framed yourself, through the guard battery, and "
                "get rows plus the guard receipts. For the slice no phase tool expresses — "
                "a finer grain, a conjunction, a custom cut. Read `caveats`: a query can "
                "succeed and still be misleading."
            ),
            parameters={"type": "object", "properties": {
                "sql": {"type": "string", "description": "One SELECT statement."},
            }, "required": ["sql"]},
            run=lambda a: _record_evidence(
                turn, a, run_sql(cid, a, emit=emit, user_question=user_question,
                                 canvas_id=canvas_id)),
        ),
        ToolSpec(
            name="list_tables",
            description="List the tables available, with their columns.",
            parameters={"type": "object", "properties": {}},
            run=lambda a: list_tables(cid, a),
        ),
        ToolSpec(
            name="describe_table",
            description="Inspect ONE table in detail — exact column names and types.",
            parameters={"type": "object", "properties": {
                "table": {"type": "string", "description": "Table name."},
            }, "required": ["table"]},
            run=lambda a: describe_table(cid, a),
        ),
    ] + platform_tools(cid, session_id=session_id)


# ── The prompt ────────────────────────────────────────────────────────────────


def _spec_section(intake: dict) -> str:
    """The intake's verdicts as STATE the model reasons from — never re-derived per
    tool. This is what makes the spec carry: a follow-up's anchored metric, windows
    and verdicts are simply true at the start of the turn."""
    if not intake:
        return "SPEC: intake produced no spec — inspect the schema before querying."
    lines = ["THE SPEC (resolved by intake; the phase tools default to it):"]
    lines.append(f"  metric: {intake.get('metric_label')} = {intake.get('metric_sql')}")
    lines.append(f"  table: {intake.get('metric_table')} · date column: {intake.get('date_column')}")
    lines.append(f"  observation: {intake.get('observation_label')} "
                 f"({intake.get('observation_start')} → {intake.get('observation_end')})")
    if intake.get("no_prior_period"):
        lines.append("  comparison: NONE — no period before the observation window exists "
                     "in the data. Describe the window; never decompose it against itself.")
    else:
        lines.append(f"  comparison: {intake.get('comparison_label')} "
                     f"({intake.get('comparison_start')} → {intake.get('comparison_end')})")
    dims = intake.get("dimensions") or []
    if dims:
        lines.append("  dimensions: " + ", ".join(str(d) for d in dims[:12]))
    if intake.get("active_filter"):
        lines.append(f"  active filter (ontology): {intake.get('active_filter')}")
    if intake.get("intake_notes"):
        lines.append(f"  intake notes: {str(intake.get('intake_notes'))[:400]}")
    return "\n".join(lines)


def analyst_system_prompt(connection_id: str, intake: dict, budget: int,
                          extra: Optional[str] = None) -> str:
    """State, not instructions — the converse rule, extended with the analyst's
    stopping rule. The tools carry the routing; this says what is true."""
    lines = [
        f"You are Aughor's analyst, investigating one question against the connected "
        f"warehouse '{connection_id}'. You work the way a good analyst works: slice, "
        "LOOK at the result, and choose the next slice because of what you saw — "
        "change the dimension, the grain or the window whenever a result argues for it.",
        "",
        _spec_section(intake),
        "",
        "Every query — yours and the phase tools' — runs through the guard battery; "
        "receipts and caveats come back with the rows, and what a guard says outranks "
        "what a number implies. A number you did not read from a tool result is a "
        "number you do not state. Significance comes from the z_score tool or a "
        "phase's own stats line, never from your own arithmetic.",
        "",
        f"You have at most {budget} tool calls for this investigation. STOPPING RULE: "
        "stop the moment a cause is named WITH ITS SIZE (which segment, how much of "
        "the change it carries) — or, if the data cannot answer, stop and say plainly "
        "what it cannot tell and what to check next. Do not spend remaining budget "
        "re-confirming what the evidence already shows.",
        "",
        "When you stop, write your conclusion as plain prose: the cause and its size, "
        "the evidence that carries it, and what you could not test. The report is "
        "assembled from the phases you ran plus this conclusion — a slice you never "
        "ran is a claim you cannot make.",
    ]
    if extra:
        lines += ["", extra]
    return "\n".join(lines)


# ── The runner ────────────────────────────────────────────────────────────────


@dataclass
class AnalystResult:
    answer: str
    report: Optional[dict]
    steps: list[LoopStep]
    stop_reason: str
    investigation_id: str
    injected_chars: int = 0
    reinjection_ratio: float = 0.0


def _base_state(question: str, connection_id: str, investigation_id: str,
                schema_context: str, *, origin_finding: Optional[dict],
                scope_schema: str, canvas_id: Optional[str],
                canvas_schema_context: str, data_catalog: str) -> dict:
    """The synthetic AgentState the phase bodies read — the graph's seed shape, minus
    the graph. `_allow_clarify` is False on purpose: an analyst turn never PAUSES for
    a widget; when the question is ambiguous the model asks in prose."""
    return {
        "question": question, "connection_id": connection_id,
        "investigation_id": investigation_id, "trace_id": "", "agent_id": "",
        "_allow_clarify": False,
        "schema_context": schema_context, "unresolved_tensions": [],
        "scan_context": "", "events_context": "",
        "hypotheses": [], "current_hypothesis_idx": 0, "query_history": [],
        "evidence_scores": [], "pitfalls": [],
        "prior_analyses": [], "origin_finding": origin_finding,
        "iteration": 0, "max_iterations": 6,
        "report": None, "hitl_enabled": False, "human_feedback": None,
        "query_mode": "investigate", "requested_mode": "investigate",
        "route_reasoning": None, "route_confidence": None, "replan_decision": None,
        "sub_questions": [], "current_subq_idx": 0, "subq_answers": [],
        "explore_report": None,
        "investigation_phases": [], "answer_report": None, "_ada_intake": None,
        "canvas_id": canvas_id, "canvas_schema_context": canvas_schema_context,
        "scope_schema": scope_schema,
        "current_plan": None, "data_catalog": data_catalog,
        "subq_data_portrait": {}, "final_text_answer": "",
    }


def build_analyst_context(connection_id: str, question: str, *,
                          canvas_id: Optional[str] = None,
                          schema_scope: Optional[str] = None) -> tuple[Any, dict]:
    """Resolve the scope and build the schema context + catalog the way the phase
    script's seed does — same primitives, so the analyst's coder sees the same
    curated grounding. Returns ``(conn, seed_kwargs)``. Fail-open on the optional
    enrichments; the scope resolution itself may raise (no such connection)."""
    from aughor.canvas.scope import resolve_execution_scope
    from aughor.tools.schema import build_canvas_schema_context

    es = resolve_execution_scope(connection_id, canvas_id, schema_scope=schema_scope,
                                 schema_context_builder=build_canvas_schema_context)
    conn = es.open()
    full_schema = conn.get_schema()
    schema = es.schema_context or full_schema
    if es.eff_schema:
        schema = (
            f"DEFAULT SCHEMA: {es.eff_schema}\n"
            "CRITICAL: Every table reference in SQL MUST include this schema prefix "
            f"(e.g. {es.eff_schema}.table_name). Do NOT use bare table names.\n\n"
            + schema
        )
    try:
        from aughor.tools.schema_linker import link_schema
        schema = link_schema(question, schema, connection_id=es.connection_id)
    except Exception:
        logger.warning("analyst: schema-linking pre-filter failed; using full schema",
                       exc_info=True)
    data_catalog = ""
    try:
        from aughor.db.schema_render import parse_schema_tables
        from aughor.tools.data_catalog import build_data_catalog
        linked = list(parse_schema_tables(schema).keys())
        if linked:
            data_catalog = build_data_catalog(conn, linked, schema=es.eff_schema or None)
    except Exception:
        logger.warning("analyst: data catalog build failed; the linked schema stands",
                       exc_info=True)
    return conn, {
        "connection_id": es.connection_id,
        "schema_context": schema,
        "scope_schema": es.eff_schema or "",
        "canvas_id": canvas_id,
        "canvas_schema_context": es.schema_context or "",
        "data_catalog": data_catalog,
    }


def run_analyst(
    connection_id: str,
    question: str,
    *,
    origin_finding: Optional[dict] = None,
    extra_context: Optional[str] = None,
    session_id: str = "",
    canvas_id: Optional[str] = None,
    schema_scope: Optional[str] = None,
    emit: Optional[Emit] = None,
    on_step: Optional[Callable[[LoopStep], None]] = None,
    provider=None,
    max_steps: Optional[int] = None,
    persist: bool = True,
    purpose: str = "",
) -> AnalystResult:
    """One deep turn as the analyst: intake once, then the loop, then the narrator.

    ``emit`` receives the turn's frames — ``phase_complete`` per phase a tool lands,
    the run_sql receipts, and the terminal ``answer_report`` — in the exact wire
    vocabulary CA-1's parts path renders. ``on_step`` fires per loop step (the
    cancellation checkpoint, like converse). ``persist`` writes the investigation
    row so History, receipts and follow-ups see the run like any other deep run.
    """
    from aughor.agent.investigate import ada_intake, ada_synthesize
    from aughor.llm.profile import profile_for
    from aughor.llm.provider import get_provider

    emit = emit or _noop_emit
    conn, seed = build_analyst_context(connection_id, question,
                                       canvas_id=canvas_id, schema_scope=schema_scope)
    eff_conn_id = seed.pop("connection_id")

    inv_id = ""
    if persist:
        from aughor.db.history import create_investigation
        inv_id = create_investigation(question, eff_conn_id, canvas_id=canvas_id,
                                      purpose=purpose, session_id=session_id or "")
    emit("start", {"question": question, "connection_id": eff_conn_id,
                   "investigation_id": inv_id or None, "body": "analyst"})

    state = _base_state(question, eff_conn_id, inv_id, seed.pop("schema_context"),
                        origin_finding=origin_finding, **seed)
    turn = AnalystTurn(connection_id=eff_conn_id, conn=conn, state=state, emit=emit)

    # Intake — once. The spec anchor: metric resolution, the coverage clamp, the
    # no-prior-period verdict, the origin/follow-up anchoring. Its phase streams
    # like any other so the user sees the spec land.
    turn.merge(ada_intake(state, conn), tool="intake")

    budget = max_steps if max_steps is not None else profile_for("coder").deep_loop_steps
    tools = analyst_tools(turn, emit=emit, session_id=session_id,
                          canvas_id=canvas_id, user_question=question)
    result: LoopResult = run_tool_loop(
        provider or get_provider("coder"),
        analyst_system_prompt(eff_conn_id, turn.intake, budget, extra=extra_context),
        question,
        tools,
        max_steps=budget,
        on_step=on_step,
    )

    answer = (result.answer or "").strip()
    state["_analyst_conclusion"] = answer
    # What the loop gathered outside the phase tools. Absent/zero ⇒ the floor behaves
    # exactly as it did for the phase script, which never had any.
    state["_analyst_evidence_rows"] = turn.evidence_rows

    report: Optional[dict] = None
    if turn.emitted_phases > 0:
        try:
            synth = ada_synthesize(state)
            report = synth.get("answer_report")
            state.update(synth)
        except Exception:
            logger.warning("analyst: synthesis failed; the phases stand without a report",
                           exc_info=True)
    if report is not None:
        emit("tables_used", {"tables": sorted({
            str(t) for p in (state.get("investigation_phases") or [])
            for f in (p.get("findings") or [])
            for t in _tables_of(f.get("sql") or "")})})
        emit("answer_report", {"answer_report": report, "investigation_id": inv_id or None,
                               "query_mode": "investigate", "mode": "investigate"})
    if persist and inv_id:
        try:
            from aughor.db.history import complete_investigation, fail_investigation
            if report is not None:
                save = dict(report)
                save["_report_type"] = "investigate"
                complete_investigation(inv_id, report=save, hypotheses=[],
                                       query_history=[], question=question,
                                       connection_id=eff_conn_id)
            elif answer:
                # The loop concluded in prose without a synthesized report (it may
                # have answered from run_sql evidence alone). The row records what
                # actually happened — a completed turn whose artifact is the prose.
                complete_investigation(inv_id, report={
                    "_report_type": "investigate",
                    "headline": answer[:300],
                    "executive_summary": answer,
                    "phases": state.get("investigation_phases") or [],
                }, hypotheses=[], query_history=[], question=question,
                    connection_id=eff_conn_id, skip_index=True)
            else:
                fail_investigation(inv_id, status="failed")
        except Exception:
            logger.warning("analyst: persisting the run outcome failed; the stream "
                           "already carried it", exc_info=True)

    return AnalystResult(
        answer=answer,
        report=report,
        steps=result.steps,
        stop_reason=result.stop_reason,
        investigation_id=inv_id,
        injected_chars=result.injected_chars,
        reinjection_ratio=result.reinjection_ratio,
    )


def _tables_of(sql: str) -> list[str]:
    try:
        from aughor.explorer.scope import tables_in_sql
        return sorted(tables_in_sql(sql))
    except Exception:
        return []
