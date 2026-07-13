"""Ground-first answer resolution — decide, once and deterministically, whether a
question is answerable *as asked* before any SQL is generated.

The quick chat path today answers first (the LLM writes SQL under soft prose
constraints — silently downgrading `monthly`→`fiscal_year`, or running an empty
`franchise='Mytheresa'` filter) and then validates with ~9 deterministic guards
plus two LLM passes that each re-decide entity/grain/measure and contradict each
other. A competent analyst does the opposite: **resolve the entity → locate the
measure at the requested grain → reconcile once → answer.**

This module is that single reconciliation. Given (question, schema[, db]) it emits
one :class:`Resolution` verdict that the generator is *constrained* by and the
answer is a *rendering* of — so the downstream guards/narrator/inspect can read it
instead of re-deriving it. It composes pieces that already exist:

- entity binding from the schema's value annotations (``inject_value_annotations``
  writes ``-- [Mytheresa, …]`` onto low-card categorical columns), matched with
  :class:`aughor.sql.value_index.ValueIndex`; an optional bounded, injection-safe DB
  existence probe confirms *absence* for the honest "not in this data" verdict;
- time-grain resolution (requested grain vs the finest grain the measure's table
  supports);
- metric-class feasibility via
  :func:`aughor.semantic.metric_feasibility.unsupported_metric_gap`.

Deterministic and defensive: any internal failure degrades to an ``answerable``
verdict (never a false abstain, never an exception on the answer path).

**Deletion roadmap** (what this verdict makes redundant once it *constrains*
generation, to be removed in staged follow-ons — see the plan): the semantic
``inspect`` LLM call (its five checks are this verdict), entity-column alignment,
breakdown-grain, id-arithmetic guard+backstop, ratio-of-sums, the measure-grain
caveat, the scope guard, and collapsing the fan-out battery into "emit the
fan-out-safe shape from the resolved join topology."
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

# ── time grain (lifted from the tested grain-feasibility detector) ────────────
# Coarser grain ⇒ larger rank. "requested finer than available" ⟺ rank(req) < rank(avail).
_RANK = {"daily": 0, "weekly": 1, "monthly": 2, "quarterly": 3, "yearly": 4}

_REQ = [
    ("daily",     re.compile(r"\b(daily|day[-\s]?(?:by[-\s]?day|wise)|per[-\s]?day|each day|by day|day[-\s]?level)\b", re.I)),
    ("weekly",    re.compile(r"\b(weekly|week[-\s]?(?:by[-\s]?week|wise)|per[-\s]?week|each week|by week|week[-\s]?level|wow)\b", re.I)),
    ("monthly",   re.compile(r"\b(monthly|month[-\s]?(?:by[-\s]?month|wise)|per[-\s]?month|each month|by month|month[-\s]?level|mom|month[-\s]?over[-\s]?month)\b", re.I)),
    ("quarterly", re.compile(r"\b(quarterly|quarter[-\s]?(?:by[-\s]?quarter|wise)|per[-\s]?quarter|by quarter|quarter[-\s]?level|qoq)\b", re.I)),
    ("yearly",    re.compile(r"\b(yearly|annual\w*|year[-\s]?(?:by[-\s]?year|wise|over[-\s]?year)|per[-\s]?year|by year|year[-\s]?level|yoy)\b", re.I)),
]

_COL = [
    ("daily",     re.compile(r"(^|_)(date|day|datetime|timestamp|ts|dt|created_at|order_date|txn_date|event_date)(_|$)", re.I)),
    ("weekly",    re.compile(r"(^|_)(week|wk|iso_week|week_start|weeknum)(_|$)", re.I)),
    ("monthly",   re.compile(r"(^|_)(month|mon|month_start|year_month|yearmonth|fiscal_month|period_month)(_|$)", re.I)),
    ("quarterly", re.compile(r"(^|_)(quarter|qtr|fiscal_quarter)(_|$)", re.I)),
    ("yearly",    re.compile(r"(^|_)(year|fiscal_year|calendar_year|fy|yr)(_|$)", re.I)),
]

# measure-ish column-name signal (what "sales/revenue" resolve against).
_MEASURE_RX = re.compile(
    r"(sales|revenue|net_sales|gmv|amount|total|price|spend|cost|profit|margin|units?|qty|quantity|"
    r"orders?|count|value|volume|bookings?|gross|turnover)", re.I)

# question tokens that are NEVER an entity filter (time, measure, glue words).
_STOP = {
    "show", "me", "give", "get", "the", "a", "an", "of", "for", "in", "at", "by", "on", "to", "and",
    "with", "per", "each", "wise", "month", "monthly", "year", "yearly", "annual", "week", "weekly",
    "day", "daily", "quarter", "quarterly", "date", "sales", "revenue", "numbers", "number", "data",
    "total", "amount", "trend", "over", "time", "breakdown", "across", "how", "many", "much", "what",
    "is", "are", "all", "top", "list", "count", "value", "gmv", "orders", "order",
}


@dataclass
class EntityBinding:
    noun: str
    table: str
    column: str
    value: str
    confidence: float


@dataclass
class Resolution:
    question: str
    entity_bindings: list[EntityBinding] = field(default_factory=list)
    not_found: list[str] = field(default_factory=list)     # filter nouns confirmed absent
    requested_grain: Optional[str] = None
    available_grain: Optional[str] = None
    grain_feasible_via: Optional[str] = None               # a table serving the finer grain, else None
    measure_gap: Optional[str] = None                      # metric-class feasibility note
    what_is_available: str = ""

    @property
    def feasibility(self) -> str:
        if self.not_found:
            return "not_answerable"
        if (self.requested_grain and self.available_grain
                and _RANK[self.available_grain] > _RANK[self.requested_grain]
                and self.grain_feasible_via is None):
            return "answerable_with_caveat"
        if self.measure_gap:
            return "answerable_with_caveat"
        return "answerable"

    @property
    def caveat(self) -> str:
        """The single honest sentence every answer channel should agree on."""
        if self.not_found:
            avail = f" {self.what_is_available}" if self.what_is_available else ""
            return f"“{self.not_found[0]}” is not present in this data.{avail}"
        if self.feasibility == "answerable_with_caveat" and self.requested_grain and self.available_grain:
            if _RANK[self.available_grain] > _RANK[self.requested_grain]:
                return (f"{self.requested_grain} breakdown was requested, but this measure is only "
                        f"reported at {self.available_grain} grain — there is no finer time column "
                        f"to break it down by")
        if self.measure_gap:
            return self.measure_gap
        return ""

    @property
    def prompt_constraints(self) -> str:
        """Hard constraints for the SQL generator — what the resolution *settled*,
        so the model doesn't silently re-decide it. Empty when nothing was pinned."""
        lines: list[str] = []
        for b in self.entity_bindings:
            lines.append(f"- FILTER: for “{b.noun}”, use {b.table}.{b.column} = '{b.value}' "
                         f"(the resolved value — do not guess a different spelling).")
        if self.requested_grain and self.grain_feasible_via:
            lines.append(f"- GRAIN: for a {self.requested_grain} breakdown, query "
                         f"`{self.grain_feasible_via}` (it has the finer time column).")
        elif (self.requested_grain and self.available_grain
              and _RANK[self.available_grain] > _RANK[self.requested_grain]):
            lines.append(f"- GRAIN: this measure exists only at {self.available_grain} grain; "
                         f"answer at {self.available_grain} and state that a {self.requested_grain} "
                         f"breakdown is unavailable. Do NOT fabricate a finer time column.")
        if not lines:
            return ""
        return "GROUNDED RESOLUTION (already settled from the schema — obey exactly):\n" + "\n".join(lines)


# ── helpers ───────────────────────────────────────────────────────────────────

def requested_time_grain(question: str) -> Optional[str]:
    best = None
    for grain, rx in _REQ:
        if rx.search(question or "") and (best is None or _RANK[grain] < _RANK[best]):
            best = grain
    return best


def _col_grain(col: str) -> Optional[str]:
    for grain, rx in _COL:
        if rx.search(str(col)):
            return grain
    return None


def _columns_grain(cols) -> Optional[str]:
    best = None
    for c in cols or []:
        g = _col_grain(c)
        if g is not None and (best is None or _RANK[g] < _RANK[best]):
            best = g
    return best


# schema line: "  colname  TYPE" optionally "  -- [v1, v2, …]"
_COL_LINE = re.compile(r"^\s{2}(\w+)\s+([A-Za-z][\w()]*)")
_ANNOT = re.compile(r"--\s*\[([^\]]*)\]")
_TABLE_LINE = re.compile(r"^TABLE:\s+([\w.]+)")


def _parse_schema(schema: str):
    """Return ({table: [cols]}, [(table, col, [values])]) from an annotated schema
    string. Value lists come from the ``-- [a, b, …]`` annotations only."""
    tables: dict[str, list[str]] = {}
    domains: list[tuple[str, str, list[str]]] = []
    cur = None
    for line in (schema or "").splitlines():
        tm = _TABLE_LINE.match(line)
        if tm:
            cur = tm.group(1)
            tables[cur] = []
            continue
        if not cur:
            continue
        cm = _COL_LINE.match(line)
        if cm:
            col = cm.group(1)
            tables[cur].append(col)
            am = _ANNOT.search(line)
            if am:
                vals = [v.strip() for v in am.group(1).split(",") if v.strip()]
                if vals:
                    domains.append((cur, col, vals))
    return tables, domains


def _entity_candidates(question: str) -> list[str]:
    """Filter-entity nouns in the question — conservative. Tokens introduced by a
    preposition (for/of/in/at/from) or capitalised proper nouns, minus time/measure/
    glue words. Empty when the question names no obvious entity."""
    q = question or ""
    cands: list[str] = []
    # after a preposition ("… for mytheresa", "of Nike")
    for m in re.finditer(r"\b(?:for|of|in|at|from)\s+([A-Za-z][\w'&.-]*(?:\s+[A-Za-z][\w'&.-]*)?)", q):
        cands.append(m.group(1).strip())
    # standalone capitalised tokens (proper nouns) not at sentence start
    for m in re.finditer(r"(?<!^)(?<![.?!]\s)\b([A-Z][a-zA-Z]{2,})\b", q):
        cands.append(m.group(1))
    out, seen = [], set()
    for c in cands:
        head = c.split()[0].lower().strip(".'&-")
        if head in _STOP or len(head) < 3 or head in seen:
            continue
        seen.add(head)
        out.append(c.strip())
    return out


def _match_annotation(token: str, domains) -> Optional[EntityBinding]:
    """Exact (case-insensitive) then fuzzy match of a token against annotated value
    domains. Returns a binding or None."""
    tl = token.lower()
    for table, col, vals in domains:
        for v in vals:
            if v.lower() == tl:
                return EntityBinding(token, table, col, v, 1.0)
    # fuzzy — only over the columns whose domain looks entity-like
    try:
        from aughor.sql.value_index import ValueIndex
        for table, col, vals in domains:
            idx = ValueIndex(vals)
            hit = idx.best_match(token, cutoff=0.9)
            if hit:
                return EntityBinding(token, table, col, hit, 0.9)
    except Exception:
        pass
    return None


_STR_TYPE = re.compile(r"(VARCHAR|TEXT|CHAR|STRING|NVARCHAR)", re.I)
_DIMISH = re.compile(r"(name|platform|brand|franchise|company|merchant|vendor|segment|category|"
                     r"channel|region|country|city|store|entity|product|customer|owner|type|status|label)", re.I)


def _string_dim_columns(schema: str) -> list[tuple[str, str]]:
    """(table, col) pairs that are string dimensions plausibly holding an entity name."""
    out = []
    cur = None
    for line in (schema or "").splitlines():
        tm = _TABLE_LINE.match(line)
        if tm:
            cur = tm.group(1)
            continue
        if not cur:
            continue
        cm = _COL_LINE.match(line)
        if cm and _STR_TYPE.search(cm.group(2)) and _DIMISH.search(cm.group(1)):
            out.append((cur, cm.group(1)))
    return out


def _db_find_value(db, schema: str, token: str, *, max_cols: int = 8):
    """Bounded, injection-safe existence probe: is ``token`` a value in any string
    dimension column? Returns (table, col, value) on the first hit, "absent" when
    every probed column is confirmed to lack it, or None when we couldn't tell
    (no db / no candidate columns) — in which case the caller must NOT abstain."""
    if db is None:
        return None
    cols = _string_dim_columns(schema)[:max_cols]
    if not cols:
        return None
    lit = token.replace("'", "''")  # SQL-literal escape; the read-only gate blocks non-SELECT
    checked = 0
    for table, col in cols:
        sql = (f"SELECT CAST({col} AS VARCHAR) FROM {table} "
               f"WHERE lower(CAST({col} AS VARCHAR)) = lower('{lit}') LIMIT 1")
        try:
            rows = db.rows(sql, label="__resolve__")
        except Exception:
            continue
        checked += 1
        if rows:
            val = rows[0][0] if not isinstance(rows[0], dict) else list(rows[0].values())[0]
            return (table, col, str(val))
    return "absent" if checked else None


def _available_grain(schema: str, requested: str):
    """(available_grain, feasible_via) for a measure at the requested grain. Scans
    tables that carry a measure-ish column: if any has a time column ≤ requested,
    that's the finer path; otherwise the finest measure-table grain is the ceiling."""
    tables, _ = _parse_schema(schema)
    want = _RANK[requested]
    finest_measure_grain = None
    for tname, cols in tables.items():
        if not any(_MEASURE_RX.search(c) for c in cols):
            continue
        tg = _columns_grain(cols)
        if tg is None:
            continue
        if _RANK[tg] <= want:
            return tg, tname                       # a finer path exists → repair
        if finest_measure_grain is None or _RANK[tg] < _RANK[finest_measure_grain]:
            finest_measure_grain = tg
    return finest_measure_grain, None


def resolve(question: str, *, schema: str = "", db=None, connection_id: str = "",
            eff_schema: Optional[str] = None) -> Resolution:
    """The single ground-first verdict. Never raises; degrades to ``answerable``."""
    r = Resolution(question=question)
    try:
        _tables, domains = _parse_schema(schema)

        # ── entity resolution ──
        for token in _entity_candidates(question):
            bind = _match_annotation(token, domains)
            if bind is not None:
                r.entity_bindings.append(bind)
                continue
            probe = _db_find_value(db, schema, token)
            if isinstance(probe, tuple):
                r.entity_bindings.append(EntityBinding(token, probe[0], probe[1], probe[2], 0.95))
            elif probe == "absent":
                r.not_found.append(token)
        if r.not_found:
            # name a couple of real values from the probed dimension so the answer
            # can say "here's what IS present" instead of a bare "not found".
            sample = next((f"present values include: {', '.join(v[:5])}"
                           for _t, _c, v in domains), "")
            r.what_is_available = sample

        # ── time-grain resolution ──
        req = requested_time_grain(question)
        if req is not None:
            r.requested_grain = req
            avail, via = _available_grain(schema, req)
            r.available_grain = avail
            r.grain_feasible_via = via

        # ── metric-class feasibility ──
        try:
            from aughor.semantic.metric_feasibility import unsupported_metric_gap
            r.measure_gap = unsupported_metric_gap(question, schema) or None
        except Exception:
            r.measure_gap = None
    except Exception:
        return Resolution(question=question)  # answerable, no constraints — never break the answer
    return r
