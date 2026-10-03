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

import json
import logging
import math
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
    #: ON-10 — the frame's declared breakdowns ran this turn (the scan tool runs them once). A field
    #: on the turn, not a private state channel: the CA-0 law requires every `state["_…"]` read to
    #: be declared on AgentState, and this flag belongs to the analyst's turn alone.
    frame_breakdowns_ran: bool = False
    #: Tools that produced at least one phase — the "did any evidence land" signal.
    phase_tools_run: list[str] = field(default_factory=list)
    #: Rows returned by tools that do NOT build a phase — `run_sql` above all. The
    #: report's no-data floor counts phase FINDINGS, so an analyst that answered from
    #: an ad-hoc query left it looking at nothing and the run was declared a total
    #: failure over its own correct numbers. This is the evidence it could not see.
    evidence_rows: int = 0
    #: What code measured before the first call (`_measure_declared`): ``(sql, result as the model
    #: reads a tool result)`` — handed to the model as results, never as calls it made.
    measured_by_code: list = field(default_factory=list)

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


#: A date bound in a WHERE clause — its operator, the day, and whatever follows the day inside
#: the quotes (a time, a zone). Bounded and anchored; never a parser.
_ADHOC_BOUND_RE = re.compile(r"""([><]=?)\s*(?:TIMESTAMP\s*)?['"](\d{4}-\d{2}-\d{2})([^'"]{0,40})['"]""", re.I)
#: What may follow the day in a bound that is the START of that day.
_ADHOC_MIDNIGHT_RE = re.compile(r"(?:[ T]00:00(?::00(?:\.0+)?)?)?\s*(?:Z|UTC|[+-]00(?::?00)?)?", re.I)
_ADHOC_DATEY = re.compile(r"(_at|date|day|month|year|period)$", re.I)


def _adhoc_window(text: str) -> str:
    """The dates an ad-hoc query reads, ending on the LAST DAY IT INCLUDES.

    The title below is derived from the RESULT SHAPE, so two queries returning the same columns
    get the same name however differently they were scoped. That is harmless until the loop does
    what a good analyst does and runs one cut over two periods: the report then shows
    "returned_cost by product_brand" twice, with different numbers and nothing saying one is
    February and the other January — an observation/comparison PAIR reads as a repeat.

    A query reads a period half-open — `created_at < '2026-08-01'` is July — and the title printed
    that bound as the end: July was "2026-07-01 → 2026-08-01", and a chart titled "→ 2026-09-04" sat
    under a label that said its period ended on 09-03 (theLook, 2026-10-02). A bound kept with `<`
    at the start of a day ends the day before it. A query with no bound on one side keeps the dates
    it names, first to last."""
    bounds = _ADHOC_BOUND_RE.findall(text)
    if not bounds:
        return ""
    lowers = [day for op, day, _ in bounds if op.startswith(">")]
    uppers = [(date.fromisoformat(day) - timedelta(days=1)).isoformat()
              if op == "<" and _ADHOC_MIDNIGHT_RE.fullmatch(rest) else day
              for op, day, rest in bounds if op.startswith("<")]
    if lowers and uppers:
        start, end = min(lowers), max(uppers)
        return start if end <= start else f"{start} → {end}"
    days = list(dict.fromkeys(day for _, day, _ in bounds))
    return days[0] if len(days) == 1 else f"{days[0]} → {days[-1]}"


_MONTH_ABBR = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
#: Initialisms a column name spells — the set web/lib/format.ts `ABBREVS` upper-cases in a label.
_INITIALISMS = frozenset("usd id uk us eu vat sku url api crm gmv mrr arr ltv cac ctr aov roi pnl gp kpi "
                         "cogs nps arpu cpa cpc cpm sla sql etl csv upc ean gtin ytd mtd qtd yoy".split())


def _words(name: str) -> str:
    """A column's name as words — ``units_sold`` → "units sold", ``aov`` → "AOV". Names are for SQL;
    a title is read (2026-10-02: "units_sold — 2026-07-01 → 2026-07-31" over Q1's figure)."""
    return " ".join(w.upper() if w.lower() in _INITIALISMS else w
                    for w in re.split(r"[_\s]+", str(name or "").strip()) if w)


def _window_words(window: str) -> str:
    """``_adhoc_window``'s days as a reader says them: a whole month "Jul 2026", whole months
    "Aug 2025 – Aug 2026", a whole year "2025", days "4 Mar – 3 Sep 2026" or "1–31 Jul 2026"
    trimmed of what they share. Anything else is left as written."""
    try:
        days = [date.fromisoformat(p.strip()) for p in window.split("→")]
    except ValueError:
        return window
    m = lambda d: _MONTH_ABBR[d.month - 1]                       # noqa: E731
    if len(days) == 1:
        return f"{days[0].day} {m(days[0])} {days[0].year}"
    a, b = days[0], days[-1]
    if a.day == 1 and (b + timedelta(days=1)).day == 1:          # whole months
        if a.year == b.year and a.month == 1 and b.month == 12:
            return str(a.year)
        if (a.year, a.month) == (b.year, b.month):
            return f"{m(a)} {a.year}"
        return f"{m(a)} – {m(b)} {a.year}" if a.year == b.year else f"{m(a)} {a.year} – {m(b)} {b.year}"
    if a.year != b.year:
        return f"{a.day} {m(a)} {a.year} – {b.day} {m(b)} {b.year}"
    return f"{a.day}–{b.day} {m(a)} {a.year}" if a.month == b.month else f"{a.day} {m(a)} – {b.day} {m(b)} {a.year}"


def _and_parts(node: Any) -> list:
    from sqlglot import exp
    while isinstance(node, exp.Paren):
        node = node.this
    return _and_parts(node.this) + _and_parts(node.expression) if isinstance(node, exp.And) else [node]


def _value_filter(cond: Any) -> str:
    """``status = Cancelled`` for a condition that keeps a column to values it names — ``=``,
    ``<>``, ``IN``, each negated or not — or "" for any other condition. A date bound is the
    window's to say."""
    from sqlglot import exp
    negated = isinstance(cond, exp.Not)
    node = cond.this if negated else cond
    while isinstance(node, exp.Paren):
        node = node.this
    if isinstance(node, (exp.EQ, exp.NEQ)):
        col, lit = (node.this, node.expression) if isinstance(node.this, exp.Column) else (node.expression, node.this)
        if not isinstance(col, exp.Column) or not isinstance(lit, exp.Literal) or _ADHOC_DATEY.search(col.name):
            return ""
        return f"{_words(col.name)} {'=' if isinstance(node, exp.EQ) != negated else '≠'} {lit.this}"
    if (isinstance(node, exp.In) and isinstance(node.this, exp.Column) and node.expressions
            and all(isinstance(e, exp.Literal) for e in node.expressions)
            and not _ADHOC_DATEY.search(node.this.name)):
        values = [str(e.this) for e in node.expressions]
        listed = ", ".join(values[:3]) + (f" and {len(values) - 3} more" if len(values) > 3 else "")
        return f"{_words(node.this.name)} {'not in' if negated else 'in'} {listed}"
    return ""


def _adhoc_filters(text: str, declared: Any = (), dialect: str = "") -> list[str]:
    """The conditions of an ad-hoc query's WHERE clauses that keep a column to values it names.

    Read from the WHERE alone: a `CASE WHEN status = 'Returned'` in the projection is the metric's
    own definition, not the rows the query reads, and naming it would title every phase of the run
    with the same words — which is why `status` was once never named at all. That left three of
    July's results under ONE title — the cancelled lines, the rest, and every line — over figures
    of 59,704.10, 359,224.30 and 418,928.40 (theLook, 2026-10-02). A filter a metric of the
    question DECLARES is left out: it is part of that measure, and the receipt says it.

    Best-effort by construction: an unparsed statement names no filter."""
    from sqlglot import exp, parse_one
    from aughor.sql.metric_filter_guard import same_condition
    tree = parse_one(text, read=dialect or None)
    out: list[str] = []
    for where in tree.find_all(exp.Where):
        for cond in _and_parts(where.this):
            piece = _value_filter(cond)
            if piece and not any(same_condition(cond.sql(dialect=dialect or None), str(d), dialect or "duckdb")
                                 for d in declared or ()):
                out.append(piece)
    return list(dict.fromkeys(out))


#: The column roles a result's title reads — the ones `plottedMeasures` in
#: web/components/charts/columnRoles.ts reads, so a title names what its chart plots.
_SHARE_NAME_RE = re.compile(r"(share|pct|percent|rate|ratio|proportion)", re.I)
_AVERAGE_NAME_RE = re.compile(r"(^|_)(avg|average|mean)(_|$)", re.I)
_COUNT_NAME_RE = re.compile(r"(^|_)(count|cnt|num|n)(_|$)", re.I)
_SUPPORT_NAME_RE = re.compile(r"(^|_)(numerator|denominator)(_total)?$|^n$|^event_count$", re.I)
_KEY_NAME_RE = re.compile(r"(_id|_key|_code|_pk|_uuid|_guid|_sk|_hash)$|^id$", re.I)
_GRAIN_NAME_RE = re.compile(r"^(date|month|week|period|quarter|day|year)$"
                            r"|^[a-z]+_(fy|year|quarter|qtr|month|week|half)$", re.I)
_WRITTEN_DECIMALS_RE = re.compile(r"-?\d*\.(\d+)")


def _as_number(value: Any) -> Optional[float]:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _is_ratio_of(rows: list, r: int, a: int, b: int, scale: int) -> bool:
    """Column ``r`` equals ``scale`` × ``a`` ÷ ``b`` on every row holding all three, to the
    precision ``r`` was written at ("6.9" is anything within 0.05) — and on two rows at least."""
    checked = 0
    for row in rows:
        x, av, bv = _as_number(row[r]), _as_number(row[a]), _as_number(row[b])
        if x is None or av is None or bv is None or bv == 0:
            continue
        want = scale * av / bv
        written = _WRITTEN_DECIMALS_RE.fullmatch(str(row[r]).strip())
        if abs(x - want) > max(0.5 * 10 ** -len(written.group(1)) if written else 0.0, abs(want) * 1e-9):
            return False
        checked += 1
    return checked >= 2


def _numeric_columns(cols: list, rows: list) -> list[int]:
    """The columns that hold a measure: a number on every row that has a value, named neither
    as a key nor as a time grain. A cell written "NULL" has no value: Q3's change and prior-month
    columns, "NULL" on their first row, were titled as what the result was cut by (2026-10-03) —
    the chart, which reads "NULL" as empty, plotted them as measures."""
    return [i for i, c in enumerate(cols)
            if not _KEY_NAME_RE.search(c) and not _GRAIN_NAME_RE.search(c)
            and any(_as_number(r[i]) is not None for r in rows)
            and all(_as_number(r[i]) is not None for r in rows
                    if str("" if r[i] is None else r[i]).strip().lower() not in _EMPTY_CELLS)]


def _rate_parts(cols: list, rows: list, numeric: list[int]) -> list[tuple[int, int, int]]:
    """``(rate, numerator, denominator)`` for each rate-named column whose own parts are in the
    result — checked on the values, as `rateParts` in columnRoles.ts checks them."""
    out = []
    for r in (i for i in numeric if _SHARE_NAME_RE.search(cols[i])):
        parts = next(((a, b) for a in numeric for b in numeric if len({r, a, b}) == 3
                      and (_is_ratio_of(rows, r, a, b, 1) or _is_ratio_of(rows, r, a, b, 100))), None)
        if parts:
            out.append((r, *parts))
    return out


#: A rate over fewer records than this is not compared with the others — the chart's rule
#: (`TOO_FEW_TO_COMPARE` in web/components/charts/columnRoles.ts), handed to the analyst too.
_TOO_FEW_TO_COMPARE = 30


def _too_few_to_compare(cols: list, rows: Any) -> dict:
    """``{group: records}`` for each row whose rate rests on fewer than 30 records — its own
    denominator, beside it in the result. Empty when no rate's parts are in the result, when the
    rows carry no label to name a group by, and when every row is that small (there is nothing
    larger to compare them with).

    The repeat-rate answer of 2026-10-01 said "many groups represent small sample sizes" where
    one country of thirteen (Colombia, two first-time buyers) and no traffic source was: the
    model was left to guess what the rows already said."""
    cols = [str(c) for c in (cols or [])]
    rows = [list(r) for r in (rows or []) if isinstance(r, (list, tuple)) and len(r) >= len(cols)]
    numeric = _numeric_columns(cols, rows) if rows else []
    labels = [i for i in range(len(cols)) if i not in numeric]
    out: dict = {}
    if not labels:
        return out
    for _rate, _num, den in _rate_parts(cols, rows, numeric):
        small = {" · ".join(str(row[i]) for i in labels): int(n)
                 for row in rows if (n := _as_number(row[den])) is not None and n < _TOO_FEW_TO_COMPARE}
        if len(small) < len(rows):
            out.update(small)
    return out


_PERIOD_VALUE_RE = re.compile(r"^\d{4}-\d{2}")
_EMPTY_CELLS = frozenset({"", "null", "none", "nan"})


def _first_change_missing(cols: list, rows: Any, observation_start: str) -> dict:
    """``{"period", "columns"}`` when the FIRST period the question asks about has no value in a column every
    later period has one in — a change against the period before, which the statement's own window left out
    (the period before lies outside it). Empty when a period before the window was read too, and when the
    question names no window.

    The monthly-revenue answer of 2026-10-02 took each month's change inside the twelve months asked, so
    September 2025's came back empty — and the answer called December "the only decline" when September
    had fallen 9.7% against August."""
    start = (observation_start or "")[:10]
    cols = [str(c) for c in (cols or [])]
    rows = [list(r) for r in (rows or []) if isinstance(r, (list, tuple)) and len(r) >= len(cols)]
    if not start or len(rows) < 3:
        return {}
    period = next((i for i, c in enumerate(cols)
                   if _GRAIN_NAME_RE.search(c) or all(_PERIOD_VALUE_RE.match(str(r[i])) for r in rows)), None)
    if period is None:
        return {}
    first = min(rows, key=lambda r: str(r[period]))
    p = str(first[period])[:10]
    n = min(len(p), len(start))
    if p[:n] < start[:n]:
        return {}

    def _empty(v: Any) -> bool:
        return v is None or str(v).strip().lower() in _EMPTY_CELLS
    columns = [cols[i] for i in range(len(cols))
               if i != period and _empty(first[i])
               and all(_as_number(r[i]) is not None for r in rows if r is not first)]
    return {"period": p, "columns": columns} if columns else {}


def _measured_cut(cols: list, rows: Any) -> str:
    """'<what it measures> by <what it is cut by>' for a result of three or more columns,
    read from its rows; "" when the rows do not say.

    A rate stands for its own numerator and denominator when they are in the result (checked
    on the values, as the chart checks them), and an average for the row count beside it: the
    title names what the chart plots. The question, cut at 80 characters, titled each of the
    2026-10-01 repeat-rate answer's three results — the same words over three different tables,
    printed three times apiece in its PDF."""
    width = len(cols)
    rows = [list(r) for r in (rows or []) if isinstance(r, (list, tuple)) and len(r) >= width]
    if not rows:
        return ""
    numeric = _numeric_columns(cols, rows)
    support: set[int] = set()
    for _rate, num, den in _rate_parts(cols, rows, numeric):
        support.update((num, den))
    if any(_AVERAGE_NAME_RE.search(cols[i]) for i in numeric):
        support.update(i for i in numeric
                       if _COUNT_NAME_RE.search(cols[i]) and not _AVERAGE_NAME_RE.search(cols[i]))
    support.update(i for i in numeric if _SUPPORT_NAME_RE.search(cols[i]))
    measures = [cols[i] for i in numeric if i not in support] or [cols[i] for i in numeric]
    cuts = [c for i, c in enumerate(cols) if i not in numeric]
    if not measures:
        return ""

    def _listed(names: list) -> str:
        names = [_words(n) for n in names[:3]] + ([f"{len(names) - 3} more"] if len(names) > 3 else [])
        return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"

    return f"{_listed(measures)} by {_listed(cuts)}" if cuts else _listed(measures)


def _adhoc_title(columns: list, question: str, sql: str = "", rows: Any = None, *,
                 declared: Any = (), dialect: str = "") -> str:
    """A name for a query the model framed itself. It supplies no title — the phase
    tools get theirs from a plan — so it comes from the shape of what came back, plus the
    SCOPE that distinguishes it from another cut of the same shape: the values its rows are
    kept to, then its dates. ``declared`` are the filters the question's metrics declare
    (`_adhoc_filters`); ``dialect`` is the engine the statement was written for."""
    cols = [str(c) for c in (columns or []) if str(c).strip()]
    if len(cols) == 2:
        # One row cuts nothing: two measures side by side are "a and b" — Q4's overall row
        # (2026-10-01) was titled "overall_avg_shipped_… by overall_avg_placed_…".
        one_row = isinstance(rows, (list, tuple)) and len(rows) == 1
        base = (_measured_cut(cols, rows) if one_row else "") or f"{_words(cols[1])} by {_words(cols[0])}"
    elif len(cols) == 1:
        base = _words(cols[0])
    else:
        base = _measured_cut(cols, rows)
        if not base:
            return (question or "Query result").strip()[:80]
    text = " ".join((sql or "").split())
    try:
        kept = ", ".join(_adhoc_filters(text, declared, dialect)[:3]) if text else ""
    except Exception:                     # noqa: BLE001 — a statement that does not parse names no filter
        kept = ""
    window = _window_words(_adhoc_window(text))
    title = f"{base} where {kept if len(kept) <= 60 else kept[:59] + '…'}" if kept else base
    title = f"{title} — {window}" if window else title
    return title[:1].upper() + title[1:]


def _declared_filters(turn: "AnalystTurn", dialect: str) -> list[str]:
    """The filters the question's metrics declare — part of those measures, so no result's title
    repeats them (`_adhoc_filters`)."""
    from aughor.semantic.enforcement import rules_for_statement
    rules = rules_for_statement(getattr(turn, "connection_id", ""), turn.state.get("question", ""),
                                dialect=dialect or "duckdb") or []
    return [str(f) for r in rules for f in (r.get("filters") or [])]


def _same_rows(finding: dict, rows: list, row_count: Any) -> bool:
    """Whether a recorded finding holds exactly these rows, in any order — the same result."""
    def _key(rs: Any) -> list:
        return sorted([str(v) for v in r] for r in list(rs or [])[:50])
    return (bool(rows) and int(finding.get("row_count") or 0) == int(row_count or len(rows))
            and _key(finding.get("rows")) == _key(rows))


def _every_result_warned(turn: "AnalystTurn") -> Optional[str]:
    """Why a stop is not an answer yet — every result the turn has shown carries a guard's
    warning — or None. The loop hands it back once (`run_tool_loop`'s ``stop_check``).

    The fulfilment question run of 2026-10-01, 22:37: three queries, each flagged (two on item
    timestamps, one over-counting orders), and the analyst stopped with tool calls to spare and
    answered from one of them — "Chicago and Memphis are the slowest to ship", which per order
    no centre is. The second of six such runs; the rule in its prompt did not hold."""
    findings = [f for p in turn.state.get("investigation_phases") or []
                if p.get("phase_id") != "intake" and not p.get("_hidden")
                for f in (p.get("findings") or []) if f.get("rows")]
    warnings = list(dict.fromkeys((f.get("trust_caveat") or "").strip() for f in findings))
    if not findings or "" in warnings:
        return None
    return ("Every result you have carries a guard's warning, so none of them is an answer yet:\n"
            + "\n".join(f"- {w[:600]}" for w in warnings[:4])
            + "\nRe-measure the way a warning says — the record to measure from, the rows it keeps — "
              "and answer from that result. If the data cannot be measured that way, answer and say so.")


def _not_the_declared(turn: "AnalystTurn", cols: list, sql: str) -> dict:
    """``{column: why}`` for each column of the model's own statement named after a further measure
    that code measured by its declared definition (`_measure_declared`) while the statement does not
    read that definition's table — the analyst's `COUNT(id) AS units_sold` over order lines beside the
    governed units sold, 6,012 against 7,027 (theLook, 2026-10-02). Read by the model with the rows."""
    measured = [d for d in (turn.state.get("_ada_intake") or {}).get("measure_definitions") or []
                if isinstance(d, dict) and d.get("measured") and d.get("table")]
    if not measured or not sql:
        return {}
    read = {str(t).split(".")[-1].lower() for t in _tables_of(sql)}

    def _words(text: Any) -> set:
        return set(re.findall(r"[a-z0-9]+", str(text or "").lower()))
    out: dict = {}
    for d in measured:
        table = str(d["table"]).split(".")[-1].lower()
        if not read or table in read:
            continue
        names = [w for w in (_words(d.get("metric")), _words(d.get("label"))) if w]
        for c in cols:
            if any(n <= _words(c) for n in names):
                out[str(c)] = (f"not the declared {d.get('label')}: code measured that by its definition on "
                               f"{d['table']} as {(d.get('measured') or {}).get('value')} — this column counts rows of "
                               f"{', '.join(sorted(read))}")
    return out


def _rule_misread(turn: "AnalystTurn", sql: str) -> str:
    """Why a statement reads a rule the question's frame declared off another table, or "".

    Q3 (2026-10-03): the frame read "completed orders" as rule completed_orders — orders.status in
    ('Complete') — and the analyst's second query filtered order_items.status = 'Complete', dated by the
    items; its every figure became the answer, beside a first query that had kept to the rule. A statement
    that filters the rule's own table too keeps to it; a column it cannot place is left alone."""
    frame = (turn.state.get("_ada_intake") or {}).get("ontology_frame") or {}
    start = frame.get("start") or {}
    table = str(start.get("table") or "").split(".")[-1].lower()
    rules = [r for r in frame.get("rules") or [] if r.get("usable") and r.get("entity") == start.get("entity")]
    if not sql or not table or not rules:
        return ""
    try:
        import sqlglot
        from sqlglot import exp
        tree = sqlglot.parse_one(sql, read=getattr(getattr(turn, "conn", None), "dialect", "") or None)
    except Exception:                     # noqa: BLE001 — a statement that does not parse is the guards' to refuse
        return ""
    ctes = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}

    def table_of(col) -> str:
        sel = col.find_ancestor(exp.Select)
        tables = [t for t in (sel.find_all(exp.Table) if sel else []) if t.find_ancestor(exp.Select) is sel
                  and t.name.lower() not in ctes]
        if col.table:
            return next((t.name.lower() for t in tables if t.alias_or_name.lower() == col.table.lower()), "")
        return tables[0].name.lower() if len(tables) == 1 else ""

    for r in rules:
        for f in r.get("filters") or []:
            path, values = str(f.get("path") or ""), {str(v).lower() for v in f.get("values") or []}
            if not path or "." in path or not values:
                continue
            on: set = set()
            for node in [*tree.find_all(exp.EQ), *tree.find_all(exp.In)]:
                col = node.this if isinstance(node.this, exp.Column) else None
                lits = list(node.expressions) if isinstance(node, exp.In) else [node.expression]
                if col is not None and col.name.lower() == path.lower() and any(
                        isinstance(v, exp.Literal) and v.is_string and v.this.lower() in values for v in lits):
                    on.add(table_of(col))
            others = sorted(on - {"", table})
            if others and table not in on:
                listed = ", ".join(f"'{v}'" for v in f.get("values") or [])
                return (f'This statement filters {others[0]}.{path}, but the question\'s "{r.get("matched") or r.get("label")}" '
                        f"is the declared rule {r.get('id')}: {table}.{path} in ({listed}) — {r.get('words')}. Filter "
                        f"{table}.{path} (join {table} if the measure lives on another table) and run it again.")
    return ""


def _refused_for_a_rule(turn: "AnalystTurn", args: dict) -> Optional[dict]:
    """A statement that misreads a declared rule does not run: its rows would become the answer."""
    why = _rule_misread(turn, (args or {}).get("sql", ""))
    return {"error": why, "retryable": True, "kind": "declared_rule", "next_tool": "run_sql",
            "instruction": why} if why else None


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
            # Which groups are too small to compare is counted here, from each rate's own
            # denominator, and read by the model with the rows (`_too_few_to_compare`).
            _small = _too_few_to_compare(cols, rows)
            if _small:
                result["too_few"] = _small
            # And when the first period asked has no change against the one before it (`_first_change_missing`).
            _first = _first_change_missing(cols, rows,
                                           (turn.state.get("_ada_intake") or {}).get("observation_start", ""))
            if _first:
                result["first_change_missing"] = _first
            # And a column named after a measure code measured by its definition, counted elsewhere.
            _elsewhere = _not_the_declared(turn, cols, (args or {}).get("sql", ""))
            if _elsewhere:
                result["not_the_declared_measure"] = _elsewhere
            # The statement that RAN, when a guard changed the one the model framed.
            ran = result.get("sql") or (args or {}).get("sql", "")
            # A query re-run to correct one a guard flagged REPLACES it on the page: the same
            # columns, the earlier carried a warning and this one carries none. Kept in the run
            # (hidden, with what replaced it) — the trace still shows the correction; the answer
            # no longer shows the flawed table beside the right one (2026-10-01, fulfilment).
            # A re-run that returns a flagged result's rows UNCHANGED corrected nothing, however it
            # was written: it carries that warning, read by the model on this very result, and
            # replaces only its own copies. The fulfilment answer's last query (2026-10-01, evening)
            # re-wrote a join flagged as an over-count through two CTEs, came back with the flagged
            # rows to the last digit, and replaced four warnings with a table that carried none.
            if not [c for c in (result.get("caveats") or []) if c]:
                def _first(_p: dict) -> dict:
                    return (_p.get("findings") or [{}])[0]
                earlier = [_p for _p in turn.state.get("investigation_phases") or []
                           if str(_p.get("phase_id", "")).startswith("adhoc_") and not _p.get("_hidden")
                           and list(_first(_p).get("columns") or []) == list(cols)]
                same = [_p for _p in earlier if _same_rows(_first(_p), rows, result.get("row_count"))]
                carried = list(dict.fromkeys(c for c in (_first(_p).get("trust_caveat") for _p in same) if c))
                if carried:
                    result["caveats"] = list(result.get("caveats") or []) + carried
                for _p in earlier:
                    if any(_p is _s for _s in same) or (not carried and _first(_p).get("trust_caveat")):
                        _p["_hidden"] = True
                        _p["superseded_by"] = f"adhoc_{n}"
            _dialect = getattr(getattr(turn, "conn", None), "dialect", "") or ""
            title = _adhoc_title(cols, turn.state.get("question", ""), (args or {}).get("sql", ""), rows,
                                 declared=_declared_filters(turn, _dialect), dialect=_dialect)
            turn.merge({"investigation_phases": (turn.state.get("investigation_phases") or []) + [{
                "phase_id": f"adhoc_{n}",
                "phase_name": title,
                "phase_icon": "🔎",
                "status": "complete",
                # Empty: the narrator writes the prose from the evidence log, and a
                # summary invented here would be a second voice on the same rows.
                "summary": "",
                "findings": [{
                    "finding_id": f"adhoc_{n}_1",
                    "title": title,
                    "sql": ran,
                    "columns": cols,
                    "rows": rows[:50],
                    # The RESULT's size, not the preview's: `run_sql` hands the model 20
                    # rows, and recording 20 made a 700-row grid read as complete — and
                    # let a total of the preview pass as the total of every row (item 6).
                    "row_count": int(result.get("row_count") or len(rows)),
                    "error": None,
                    "interpretation": "",
                    "key_numbers": [],
                    "chart_type": "auto",
                    "stat_note": None,
                    "is_significant": False,
                    # What the guards said about these rows reaches the page and the
                    # writer, not only the model that ran the query.
                    "trust_caveat": " ".join(str(c) for c in (result.get("caveats") or []) if c),
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
    from aughor.semantic.enforcement import rules_for_statement
    from aughor.sql.executor import execute_guarded
    return execute_guarded(conn, sql, query_id=query_id,
                           metric_rules=rules_for_statement(
                               getattr(conn, "_connection_id", ""),
                               dialect=getattr(conn, "dialect", "") or "duckdb"))


def _probe(conn, sql: str, query_id: str):
    """A CODE-built probe (quoted identifiers + escaped literal, LIMIT-bounded) runs
    direct, the way the guard battery's own probes do — running a probe through the
    battery would have the guards probing the probes. It is written in DuckDB's spelling
    and declared so; the door renders it for the engine (GM-1)."""
    return conn.execute(query_id, sql, sql_dialect="duckdb", internal=True)


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


def _scan(state: dict, conn, **kwargs) -> dict:
    """The weakness scan itself — one seam, so a test can stand in for it by this name."""
    from aughor.agent.investigate import ada_cross_section
    return ada_cross_section(state, conn, **kwargs)


def cross_section(turn: AnalystTurn, args: dict) -> dict:
    from aughor.agent.investigate import frame_breakdowns

    state = dict(turn.state)
    state["_ada_intake"] = _spec_overrides(turn.intake, args)
    dim = str(args.get("dimension") or "").strip()
    kwargs: dict = {}
    if dim:
        dims = list(turn.intake.get("dimensions") or [])
        matched = [d for d in dims if dim.lower() in d.lower()]
        kwargs["dims_override"] = matched or [dim]
    fresh: list[dict] = []
    if not turn.frame_breakdowns_ran:
        # ON-10 (2026-09-22) — the frame's declared breakdowns run BEFORE the scan here too. The analyst
        # body reaches the scan as a tool, not through the graph's `frame_breakdowns` node (the live
        # receipt on LuxExperience took this body and never met the node), so the node's function runs
        # once per turn, on the first scan — pinned or not: the live model pins the scan to the driver
        # the question named, and the declared breakdown by that driver is the definition's own "by",
        # not the scan's cut. Deterministic, no model call, nothing without a usable frame. The scan
        # itself still owns no breakdown.
        turn.frame_breakdowns_ran = True
        fresh += turn.merge(frame_breakdowns(state, turn.conn), tool="frame_breakdowns")
        state = dict(turn.state)
        state["_ada_intake"] = _spec_overrides(turn.intake, args)
    fresh += turn.merge(_scan(state, turn.conn, **kwargs), tool="cross_section")
    return _phase_payload(fresh)


# ── The roster ────────────────────────────────────────────────────────────────

_WINDOW_PROPS = {
    "observation_start": {"type": "string", "description": "ISO date — override the spec's observation start."},
    "observation_end": {"type": "string", "description": "ISO date — override the spec's observation end."},
    "comparison_start": {"type": "string", "description": "ISO date — override the comparison start."},
    "comparison_end": {"type": "string", "description": "ISO date — override the comparison end."},
    "metric_sql": {"type": "string", "description": "Override the metric aggregation expression (rare — the spec's metric is already resolved)."},
    "metric_label": {"type": "string", "description": "Human label for an overridden metric."},
}


#: Which of `platform_tools`' twelve reads the ANALYST is offered. Just one.
#:
#: `platform_tools` was built for the chat roster, where a question can be about anything
#: the product knows — monitors, packs, the audit log, the briefing, the docs. An analyst
#: is not answering that question. It is answering "why did this metric move", and the
#: measurement says so: across the 14 analyst turns in the live session log the twelve
#: were offered on EVERY turn and exactly one was ever called — `propose_context_note`,
#: once. The other eleven were never chosen, not once.
#:
#: They were not free. The twelve serialise to ~7,500 wire characters, re-sent on every
#: turn of a loop whose median is 3 calls and whose tail reaches 56; dropping eleven of
#: them takes ~5,800 characters (~1,450 tokens) off every analyst tool call. And the cost
#: is not only tokens: `converse_tools` already states the rule this follows — the model
#: picks from what it can see, and a tool it can see is one it will spend a turn trying.
#:
#: `propose_context_note` stays because it is not platform administration. It is the
#: analyst writing back what it just learned about the DATA — a unit, a value meaning, a
#: caveat — which is the analysis path's own business, and it is the one that was used.
#:
#: Membership is by NAME against the live `platform_tools` output rather than a second
#: copy of the declaration, so the tool keeps one definition. That makes a rename able to
#: empty this filter silently, which is why the test asserts the kept tool is PRESENT in
#: the built roster and not merely that the dropped ones are absent.
_ANALYST_PLATFORM_TOOLS = frozenset({"propose_context_note"})

#: The tools that explain a movement or hunt a weakness. A question that asks to SEE the
#: data (`investigate.question_shape` → "describe") is not offered them: each one frames its
#: finding as a change or a shortfall, and a roster the model can see is a roster it spends
#: turns on — Q5 (2026-09-29) was answered with an unasked year-over-year comparison.
_INVESTIGATION_TOOLS = frozenset({"baseline", "decompose", "premise_check", "cross_section"})


def analyst_tools(turn: AnalystTurn, *, emit: Optional[Emit] = None,
                  session_id: str = "", canvas_id: Optional[str] = None,
                  user_question: str = "", shape: str = "diagnose") -> list[ToolSpec]:
    """The analyst's roster: the phase library as tools, the deterministic probes, the
    warehouse primitives, and the ONE platform tool that is analysis business. Bound by
    closure like every converse tool — the model cannot name a connection, session or
    spec it was not given.

    It is deliberately not the chat roster. See :data:`_ANALYST_PLATFORM_TOOLS` for what
    was taken out and why; the short version is that a tool the model can see is a tool
    it will spend a turn trying, and this roster is re-sent on every turn of a loop whose
    tail reaches 56 calls."""
    from aughor.agent.converse_tools import describe_table, list_tables, run_sql
    from aughor.agent.platform_tools import platform_tools

    cid = turn.connection_id
    roster = [
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
            run=lambda a: _refused_for_a_rule(turn, a) or _record_evidence(
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
    ] + [t for t in platform_tools(cid, session_id=session_id)
         if t.name in _ANALYST_PLATFORM_TOOLS]
    if shape == "describe":
        roster = [t for t in roster if t.name not in _INVESTIGATION_TOOLS]
    return roster


# ── The prompt ────────────────────────────────────────────────────────────────


def _spec_section(intake: dict) -> str:
    """The intake's verdicts as STATE the model reasons from — never re-derived per
    tool. This is what makes the spec carry: a follow-up's anchored metric, windows
    and verdicts are simply true at the start of the turn."""
    from aughor.agent.sql_context import window_text
    if not intake:
        return "SPEC: intake produced no spec — inspect the schema before querying."
    lines = ["THE SPEC (resolved by intake; the phase tools default to it):"]
    lines.append(f"  metric: {intake.get('metric_label')} = {intake.get('metric_sql')}")
    from aughor.agent.investigate import measure_definition_text
    for _m in intake.get("other_measures") or []:
        _label = (_m or {}).get("label")
        _defined = measure_definition_text(intake.get("measure_definitions"), _label)
        _measured = next((d.get("measured") for d in intake.get("measure_definitions") or []
                          if isinstance(d, dict) and d.get("label") == _label and d.get("measured")), None)
        lines.append(f"  also asked: {_label} = {(_m or {}).get('sql')}" + _defined + (
            f"; measured that way over the observation by code: {_measured['value']} — state that "
            "figure; do not measure it again" if _measured else
            "; measure it on that table, by that date, in a query of its own" if _defined else ""))
    if intake.get("metric_filters"):
        lines.append("  metric filter (declared, part of the definition): "
                     + "; ".join(str(f) for f in intake["metric_filters"]))
    lines.append(f"  table: {intake.get('metric_table')} · date column: {intake.get('date_column')}")
    # Each window with its filter written out, half-open — the model wrote `<= '2026-07-31'`
    # on a TIMESTAMP column from a bare "→ 2026-07-31" and dropped the day (2026-09-29).
    _col = str(intake.get("date_column") or "")
    if intake.get("observation_start") or intake.get("period_named", True):
        lines.append("  observation: " + window_text(
            str(intake.get("observation_label") or ""), intake.get("observation_start") or "",
            intake.get("observation_end") or "", _col))
    else:
        lines.append("  observation: all the data — the question names no period.")
    if intake.get("comparison_asked") is False:
        lines.append("  comparison: none — the question asks to compare no periods; compare none.")
    elif intake.get("no_prior_period"):
        lines.append("  comparison: NONE — no period before the observation window exists "
                     "in the data. Describe the window; never decompose it against itself.")
    else:
        lines.append("  comparison: " + window_text(
            str(intake.get("comparison_label") or ""), intake.get("comparison_start") or "",
            intake.get("comparison_end") or "", _col))
    dims = intake.get("dimensions") or []
    if dims:
        lines.append("  dimensions: " + ", ".join(str(d) for d in dims[:12]))
    if intake.get("active_filter"):
        lines.append(f"  active filter (ontology): {intake.get('active_filter')}")
    if intake.get("intake_notes"):
        lines.append(f"  intake notes: {str(intake.get('intake_notes'))[:400]}")
    return "\n".join(lines)


#: A question that asks for a figure PER period asks for a series, not one figure.
_PER_PERIOD_RE = re.compile(r"\b(?:each|every|per|by)\s+(?:day|week|month|quarter|year)\b"
                            r"|\b(?:daily|weekly|monthly|quarterly|yearly|annual(?:ly)?)\b", re.I)


def _asks_one_figure(intake: dict, question: str, shape: str) -> bool:
    """Whether the question asks each of its measures as ONE figure over its window: it asks to see
    the data, names no cut, compares no periods and asks for no series."""
    return (shape == "describe" and not intake.get("cross_sectional") and not intake.get("named_dimensions")
            and intake.get("comparison_asked") is False and not _PER_PERIOD_RE.search(question or ""))


def _declared_measure_sql(intake: dict, definition: dict, formula: str) -> str:
    """The statement that measures one further measure by its declared definition: its formula on its
    table, over its filters, with ITS OWN date in the observation (half-open) — or over all its rows
    when the question names no period. "" when the period is asked and the measure has no date."""
    table = str(definition.get("table") or "").strip()
    if not table or not formula:
        return ""
    conds = [str(f).strip() for f in definition.get("filters") or [] if str(f).strip()]
    if intake.get("period_named", True):
        start, end = str(intake.get("observation_start") or "")[:10], str(intake.get("observation_end") or "")[:10]
        day = str(definition.get("date_column") or "").strip()
        if not (start and end and day):
            return ""
        after = (date.fromisoformat(end) + timedelta(days=1)).isoformat()
        conds += [f"{day} >= '{start}'", f"{day} < '{after}'"]
    alias = re.sub(r"[^a-z0-9]+", "_", str(definition.get("metric") or definition.get("label") or "")
                   .lower()).strip("_") or "measure"
    return f"SELECT {formula} AS {alias} FROM {table}" + (f" WHERE {' AND '.join(conds)}" if conds else "")


def _measure_declared(turn: "AnalystTurn", run_sql_tool: Callable[[dict], Any], shape: str) -> None:
    """Measure each further measure tied to a governed metric BY CODE, through the run_sql tool's own
    body (guards, frames, evidence), and record the figure on its definition for the spec.

    "What was total revenue and how many units were sold in July 2026?": the analyst was told units
    sold is the governed units_sold — inventory items by the day they sold — and to measure it in a
    query of its own. It counted order lines in revenue's statement instead, four times, the last
    time with `status IS NOT NULL` so that revenue's declared filter would leave it alone, and
    published revenue with every cancelled line in it (theLook, 2026-10-02). Only the figure over
    the whole window is measured here, so only a question that asks for that figure is."""
    intake = turn.intake
    if not _asks_one_figure(intake, turn.state.get("question", ""), shape):
        return
    formulas = {m.get("label"): m.get("sql") for m in intake.get("other_measures") or [] if isinstance(m, dict)}
    for definition in intake.get("measure_definitions") or []:
        if not isinstance(definition, dict):
            continue
        sql = _declared_measure_sql(intake, definition, str(formulas.get(definition.get("label")) or ""))
        if not sql:
            continue
        before = len(turn.state.get("investigation_phases") or [])
        result = run_sql_tool({"sql": sql})
        phases = turn.state.get("investigation_phases") or []
        rows = result.get("rows") if isinstance(result, dict) else None
        if rows and rows[0] and len(phases) > before:
            definition["measured"] = {"result": phases[-1].get("phase_id"), "value": str(rows[0][0])}
            turn.measured_by_code.append((sql, json.dumps(result, default=str)))


def _measured_preface(turn: "AnalystTurn") -> str:
    """What code measured before the first call, as results the model reads with the question.

    Q1's units sold was measured by its declared definition (7,027) and named in the spec, and the
    analyst counted order lines in revenue's statement and stated its own 6,012 (theLook, 2026-10-02):
    a figure in its instructions was not a figure it had read from a result, and its rule is to state
    only those. Handed over as results — never as a call the model did not make (`tool_loop._exchange`)."""
    if not turn.measured_by_code:
        return ""
    return "\n".join(["Measured for you by code before your first call, through the same run_sql tool and "
                      "guards — tool results, already among this turn's results:",
                      *(f"run_sql: {sql}\n→ {payload}" for sql, payload in turn.measured_by_code)])


def _describe_rules(budget: int) -> list[str]:
    """The stopping rule for a question that asks to SEE the data (item 3). Its conclusion
    is published as the answer (`investigate._conclusion_as_answer`), so it is written for
    the reader, not for a writer to rework."""
    return [
        f"You have at most {budget} tool calls. This question asks to SEE the data, not why "
        "it moved. STOPPING RULE: stop as soon as your results answer every part of it — "
        "each figure it asks for, over the period and across the cuts it names. Do not look "
        "for causes, drivers or anomalies it did not ask about, and compare periods only "
        "where it asks.",
        "",
        "Each cut the question names ('by traffic source and country') is measured on its "
        "own, pooled over everything else — one GROUP BY per cut, with the count behind "
        "each rate. A finer grid (month × source × country) splits the rows into cells too "
        "small to compare and does not answer it. Show every group of a cut, or say how "
        "many you left out. Order a table by the measure, with each group a result lists "
        "under `too_few` after the others and marked with its count — never at the top. "
        "Those are the groups too small to compare: name them, and call no other group small. "
        "A change against the period before is asked of every period the question covers, the "
        "first included: its period before lies outside the window, so read one period earlier "
        "(where the data holds it). A result that lists `first_change_missing` left that change "
        "out — measure it before you answer.",
        "",
        "When you stop, write the answer the reader will read, in plain prose. Open with "
        "the answer itself in one sentence, with its figures — what leads, what trails, by "
        "how much — never a definition or a restatement of the question. That sentence is the "
        "headline the reader sees first: it states a figure read from a row, and one that "
        "announces what follows (\"The following table lists…\") answers nothing. Groups within a "
        "few percent of each other are alike: say so with their range — the lowest and the "
        "highest group's own value, each read from a row — and name no leader or laggard "
        "the data does not separate. Then "
        "the figures asked for, as a table when there are several rows, with the period and "
        "the definition used; then anything the data could not answer. A total or share "
        "across rows is quoted from the result's `totals`, never added up by hand, and a "
        "column under `no_total` is never added up at all; an "
        "overall average comes from a query that computes it without the GROUP BY — never "
        "one group's value, never an average of the groups' averages. No recommendations, "
        "no speculation about causes.",
    ]


def analyst_system_prompt(connection_id: str, intake: dict, budget: int,
                          extra: Optional[str] = None, sql_context: str = "",
                          shape: str = "diagnose") -> str:
    """State, not instructions — the converse rule, extended with the analyst's
    stopping rule. The tools carry the routing; this says what is true.

    ``sql_context`` is the engine and the clock (`agent/sql_context.py`): the intake's
    block when it built one, else the caller's from the connection — so a turn whose
    intake returned nothing still knows the engine and the date. Measured 2026-09-29: the
    analyst was told neither, wrote `DATEADD` and `DATE_TRUNC('month', …)` for BigQuery,
    and with no spec anchored on `CURRENT_DATE` into a month still filling."""
    lines = [
        f"You are Aughor's analyst, investigating one question against the connected "
        f"warehouse '{connection_id}'. You work the way a good analyst works: slice, "
        "LOOK at the result, and choose the next slice because of what you saw — "
        "change the dimension, the grain or the window whenever a result argues for it.",
        "",
        (intake or {}).get("sql_context") or sql_context or "",
        "",
        _spec_section(intake),
        "",
        "Every query — yours and the phase tools' — runs through the guard battery; "
        "receipts and caveats come back with the rows, and what a guard says outranks "
        "what a number implies. A number you did not read from a tool result — yours, or one "
        "measured for you by code before your first call — is a number you do not state. "
        "Significance comes from the z_score tool or a "
        "phase's own stats line, never from your own arithmetic.",
        "",
        "A result shows you at most 20 rows. When it says `truncated`, the rows you see "
        "are not the result: ask for what you need with GROUP BY, or ORDER BY … LIMIT — "
        "never state a range, a spread or a pattern from the rows shown.",
        "",
        "Each measure in THE SPEC is defined on its own table. To cut it by a column that "
        "lives elsewhere, JOIN that table to the measure's — never re-measure it on the "
        "other table's own columns of the same name. A result whose caveat says how to "
        "measure instead (the record to measure from, the rows it left out) is not yet an "
        "answer: re-measure the way it says, then answer from that result. Leaving out the "
        "rows a guard flagged is not a re-measure.",
        "",
        *(_describe_rules(budget) if shape == "describe" else [
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
        ]),
    ]
    if extra:
        lines += ["", extra]
    # AO-1a — the active agent's brief LEADS the analyst's prompt, as it leads the quick
    # body's SQL prompt and (now) the conversation's. Measured 2026-10-03: a custom agent's
    # standing instructions reached neither of the two bodies a user actually talks to.
    # Read from the contextvar: the analyst runs inside the turn that activated the agent
    # (the ask door's outermost wrapper), and the pool propagates contextvars. Empty on the
    # default path, so a run with no agent builds the prompt byte for byte as before.
    try:
        from aughor.custom_agents.context import agent_brief_block
        _brief = agent_brief_block()
    except Exception as brief_exc:
        from aughor.kernel.errors import tolerate
        tolerate(brief_exc, "the agent brief is additive; the analyst stands without it",
                 counter="analyst.agent_brief")
        _brief = ""
    if _brief:
        lines = [_brief.rstrip("\n"), ""] + lines
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
        "investigation_phases": [], "answer_report": None, "_ada_intake": None, "_intake_failed": None,
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

    # Every statement this turn runs is in answer to ONE question, and the declared
    # filters it must carry are that question's (`semantic.enforcement`). Bound for the
    # intake and the loop — the two places a statement executes — and released after.
    from aughor.semantic.enforcement import answering
    with answering(question):
        # Intake — once. The spec anchor: metric resolution, the coverage clamp, the
        # no-prior-period verdict, the origin/follow-up anchoring. Its phase streams
        # like any other so the user sees the spec land.
        turn.merge(ada_intake(state, conn), tool="intake")

        budget = max_steps if max_steps is not None else profile_for("coder").deep_loop_steps
        # Item 3: measure-and-state or investigate, decided by code from the question.
        from aughor.agent.investigate import question_shape
        shape = (turn.intake or {}).get("question_shape") or question_shape(question)
        tools = analyst_tools(turn, emit=emit, session_id=session_id,
                              canvas_id=canvas_id, user_question=question, shape=shape)
        # A further measure tied to a governed metric is measured by code before the analyst's
        # first call, and the spec hands it the figure (`_measure_declared`).
        try:
            _measure_declared(turn, next(t.run for t in tools if t.name == "run_sql"), shape)
        except Exception as exc:                  # noqa: BLE001 — the analyst then measures it itself
            from aughor.kernel.errors import tolerate
            tolerate(exc, "a declared further measure is measured by code best-effort; the analyst "
                          "measures it otherwise", counter="analyst.declared_measure")
        from aughor.agent.sql_context import learned_settle_days, sql_context as _sql_context
        result: LoopResult = run_tool_loop(
            provider or get_provider("coder"),
            analyst_system_prompt(
                eff_conn_id, turn.intake, budget, extra=extra_context,
                sql_context=_sql_context(
                    conn, coverage_end=(turn.intake or {}).get("data_coverage_end") or "",
                    settle_days=learned_settle_days(eff_conn_id)),
                shape=shape),
            question,
            tools,
            max_steps=budget,
            on_step=on_step,
            conn_id=eff_conn_id or "",
            trace_id=state.get("trace_id", "") or "",
            inv_id=state.get("investigation_id", "") or "",
            # The analyst is its OWN decider: a different roster (11 tools vs converse's 38)
            # and a system prompt carrying the resolved spec. Filing its picks under
            # `converse.tool` made 79% of the live corpus unsegmentable by decider.
            site="analyst.tool",
            stop_check=lambda _answer: _every_result_warned(turn),
            preface=_measured_preface(turn),
            # JD-4: the builder's arguments. `intake` is MODEL OUTPUT (the intake step's) and cannot be
            # recomputed, and it is where the analyst's state lives — `_spec_section(intake)` sits
            # mid-prompt — so it is the argument a shuffle actually swaps. Serialised to a string
            # so that a capped copy is MARKED truncated rather than silently clipped: a truncated
            # intake rebuilds a different prompt, and the replay must refuse it.
            replay_args={
                "builder": "analyst_system_prompt",
                "connection_id": eff_conn_id or "",
                "intake": json.dumps(turn.intake or {}, ensure_ascii=False, sort_keys=True,
                                     default=str),
                "budget": int(budget),
                "extra": extra_context or "",
                "shape": shape,
            },
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
        # The question's shape rides the report — a describe answer measured what was asked and
        # tested no hypotheses, and the trace said "Multi-hypothesis analysis" over every one.
        report["question_shape"] = shape
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
