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

# The measure NOUNS a question can name, and the column-name substrings each maps
# to. This is what ties the answer to the RIGHT table: "sales" resolves against a
# net_sales/revenue column, NOT a collaboration's est_gmv — so the entity binds to
# and the grain is read from the table that actually holds the asked-for measure.
_MEASURE_NOUNS = re.compile(
    r"\b(sales|revenue|turnover|gmv|orders?|customers?|aov|margin|profit|ebitda|units?|"
    r"quantity|spend|cost|bookings?|volume)\b", re.I)
_MEASURE_SYNONYMS = {
    "sales": ("net_sales", "sales", "revenue", "turnover"),
    "revenue": ("revenue", "net_sales", "sales", "turnover"),
    "turnover": ("turnover", "revenue", "sales"),
    "gmv": ("gmv",),
    "order": ("orders", "order_count", "num_orders"),
    "orders": ("orders", "order_count", "num_orders"),
    "customer": ("customers", "active_customers", "buyers"),
    "customers": ("customers", "active_customers", "buyers"),
    "aov": ("aov", "average_order"),
    "margin": ("margin",),
    "profit": ("profit", "ebitda"),
    "ebitda": ("ebitda",),
    "unit": ("units", "quantity", "qty"),
    "units": ("units", "quantity", "qty"),
    "quantity": ("quantity", "qty", "units"),
    "spend": ("spend", "cost", "budget"),
    "cost": ("cost", "spend"),
    "booking": ("bookings",),
    "bookings": ("bookings",),
    "volume": ("volume", "units", "quantity"),
}
# fallback measure-ish signal when the question names no explicit measure.
_MEASURE_RX = re.compile(
    r"(sales|revenue|net_sales|gmv|amount|total|spend|cost|profit|margin|units?|qty|quantity|"
    r"orders?|count|volume|bookings?|turnover|ebitda|aov)", re.I)

# ── grain-fallback vocabulary (the transactional finer-grain path) ────────────
# A revenue-type question ("monthly sales") whose governed measure table is coarse
# (financial_summary is yearly) can still be answered at the finer grain FROM the
# transactional fact table — IF the schema has one carrying an ACTUAL revenue-family
# measure + a fine time column + the same entity dimension. These regexes make that
# substitution safe: exclude estimates/projections (est_gmv is not a sale), prefer a
# canonical fact table, and demote indirect proxies (influenced/attributed/uplift).
_REVENUE_FAMILY = re.compile(r"(revenue|sales|net_sales|gmv|turnover|amount|bookings|proceeds)", re.I)
_EST_PREFIX = re.compile(r"^(est|estimated|projected|forecast|budget|target|planned|expected)_", re.I)
_FACT_TABLE = re.compile(r"(^|_)(orders?|order_items?|line_items?|transactions?|txns?|sales|invoices?|payments?|bookings?|ledger|fact)(_|s?$)", re.I)
_INDIRECT_MEASURE = re.compile(r"(influenced|attributed|uplift|potential|indirect|est_|projected)", re.I)

# question tokens that are NEVER an entity filter (time, measure, glue words).
_STOP = {
    "show", "me", "give", "get", "the", "a", "an", "of", "for", "in", "at", "by", "on", "to", "and",
    "with", "per", "each", "wise", "month", "monthly", "year", "yearly", "annual", "week", "weekly",
    "day", "daily", "quarter", "quarterly", "date", "sales", "revenue", "numbers", "number", "data",
    "total", "amount", "trend", "over", "time", "breakdown", "across", "how", "many", "much", "what",
    "is", "are", "all", "top", "list", "count", "value", "gmv", "orders", "order",
}

# A deictic reference back to the PRIOR result — the signal that a follow-up continues the
# previous turn ("break THAT down", "filter THOSE", "the SAME for Q3") rather than starting a
# new filter. Gates conversation carry-forward in resolve() so "what about menswear?" (a new
# noun, no deictic) never inherits the old entity.
_DEICTIC = re.compile(r"\b(that|those|these|this|it|them|they|the same|same|again|previous|above|prior)\b", re.I)


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
    grain_note: str = ""                                   # honest note when the finer grain uses a different (transactional) measure
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
        if self.grain_note:                          # answerable via a finer transactional path — say which measure
            return self.grain_note
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
            via = (f"- GRAIN: for a {self.requested_grain} breakdown, query "
                   f"`{self.grain_feasible_via}` (it has the finer time column).")
            if self.grain_note:
                via += f" NOTE: {self.grain_note}"
            lines.append(via)
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


def question_measures(question: str) -> list:
    """Public: the measure nouns a question names (``[]`` if none) — the metric-presence
    signal reused by the overview router to detect a metric-free, widest-scope ask."""
    return _question_measures(question)


def entity_candidates(question: str) -> list:
    """Public: the filter-entity nouns a question names (``[]`` if none) — the
    entity-presence signal reused by the overview router."""
    return _entity_candidates(question)


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


def _question_measures(question: str) -> list[str]:
    """The measure nouns the question names (e.g. ['sales']) — what the answer is
    ABOUT. Empty when the question names no explicit measure."""
    return list(dict.fromkeys(m.lower() for m in _MEASURE_NOUNS.findall(question or "")))


def _col_matches_measure(col: str, measures: list[str]) -> bool:
    c = col.lower()
    if _EST_PREFIX.search(c):
        return False            # an estimate/projection (est_gmv) is never the measure —
        #                         this is what stops brand_collaborations' est_gmv_eur from
        #                         re-latching the entity onto the decoy for a "gmv" question.
    for m in measures:
        if any(syn in c for syn in _MEASURE_SYNONYMS.get(m, (m,))):
            return True
    return False


def _measure_tables(tables: dict, measures: list[str]) -> set:
    """Tables that carry a column for the asked-for measure — the tables an answer
    about that measure must come from. Falls back to any measure-ish column when the
    question names no explicit measure. This is what stops the entity binding and
    the grain from latching onto an unrelated table (e.g. brand_collaborations'
    launch_date) that merely happens to share the entity value."""
    out = set()
    for t, cols in tables.items():
        if measures:
            if any(_col_matches_measure(c, measures) for c in cols):
                out.add(t)
        elif any(_MEASURE_RX.search(c) for c in cols):
            out.add(t)
    return out


def _annotation_matches(token: str, domains) -> list:
    """All (table, col, value, conf) where an annotated value domain contains the
    token — exact (case-insensitive) first, else fuzzy. Never raises."""
    tl = token.lower()
    out = []
    for table, col, vals in domains:
        for v in vals:
            if v.lower() == tl:
                out.append((table, col, v, 1.0))
                break
    if out:
        return out
    try:
        from aughor.sql.value_index import ValueIndex
        for table, col, vals in domains:
            hit = ValueIndex(vals).best_match(token, cutoff=0.9)
            if hit:
                out.append((table, col, hit, 0.9))
    except Exception:
        return out
    return out


def _pick(matches: list, prefer_tables: set):
    """Choose the match whose table carries the asked-for measure; else the first."""
    for m in matches:
        if m[0] in prefer_tables:
            return m
    return matches[0] if matches else None


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


def _stem(w: str) -> str:
    """Crudest singular stem, so a plural question word matches a singular column name
    ('categories' → 'category', 'brands' → 'brand'). Good enough for column-name matching."""
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    if w.endswith("es") and len(w) > 4:
        return w[:-2]
    if w.endswith("s") and len(w) > 3:
        return w[:-1]
    return w


def _rank_dim_columns(cols: list[tuple[str, str]], prefer_tables: Optional[set],
                      question: str) -> list[tuple[str, str]]:
    """Order candidate dimension columns so the ones the QUESTION points at are probed first:
    (1) a column whose name (stem-matched) appears in the question — a 'categories' question
    floats the ``category`` columns — then (2) measure-bearing tables, then the rest. So a
    filter-by-<dimension> value binds in the first few probes, not buried past a cap. Ranking
    is an optimisation for the common case; correctness comes from probing EVERY column before
    abstaining (see :func:`_db_find_value`)."""
    qstems = {_stem(w) for w in re.findall(r"[a-z]{3,}", (question or "").lower())}
    prefer = prefer_tables or set()

    def named(col: str) -> bool:
        cl = col.lower()
        return any(s in cl or _stem(cl) == s for s in qstems)

    return sorted(cols, key=lambda tc: (0 if named(tc[1]) else 1,
                                        0 if tc[0] in prefer else 1))


def _db_find_value(db, schema: str, token: str, *, prefer_tables: Optional[set] = None,
                   value_samples: Optional[dict] = None, question: str = ""):
    """Injection-safe existence probe: is ``token`` a value in any string dimension column?
    Returns (table, col, value) on the first hit, "absent" when EVERY candidate column is
    confirmed to lack it, or None when we couldn't tell (no db / no candidate columns) — in
    which case the caller must NOT abstain.

    Columns are probed in RELEVANCE order (a column the ``question`` names → measure-bearing
    tables → the rest) so the answer binds fast in the common case. Crucially for the
    ground-first contract ("never a false abstain"), "absent" is returned only after ALL
    candidate columns have been checked — never after a fixed cap. (A prior 8-of-N cap declared
    present values absent when the value lived in a lower-ranked column: e.g. a ``category``
    value like 'womenswear' while the measure bound to a summary table that has no category.)

    ``value_samples`` (R5) is the warmed {(table, col): distinct-values} map: a token already
    present there binds OFFLINE, skipping the live probe. A MISS still falls through to the live
    probe — the persisted set can lag the data, and the contract forbids a sample-only absent."""
    cols = _rank_dim_columns(_string_dim_columns(schema), prefer_tables, question)
    if not cols:
        return None

    low = token.lower()
    # Offline first, over ALL ranked columns (in-memory; no DB) — cheapest and complete.
    if value_samples:
        from aughor.sql.value_index import ValueIndex
        for table, col in cols:
            sample = value_samples.get((table, col))
            if not sample:
                continue
            for v in sample:
                if str(v).lower() == low:
                    return (table, col, str(v))
            m = ValueIndex(sample).best_match(token, cutoff=0.9)
            if m is not None:
                return (table, col, m)

    if db is None:
        return None
    lit = token.replace("'", "''")  # SQL-literal escape; the read-only gate blocks non-SELECT
    checked = 0
    # Live sweep over EVERY candidate column (relevance-ordered; early-return on the first hit).
    # A genuine "absent" therefore costs a full sweep — acceptable on the rare not-found path,
    # where a correct "here's what IS present" beats a fast but wrong "not present".
    for table, col in cols:
        sql = (f"SELECT CAST({col} AS VARCHAR) FROM {table} "
               f"WHERE lower(CAST({col} AS VARCHAR)) = lower('{lit}') LIMIT 1")
        try:
            rows = db.rows(sql, label="__resolve__")
        except Exception:
            rows = None          # couldn't probe this column — skip, don't count as "absent"
        if rows is None:
            continue
        checked += 1
        if rows:
            val = rows[0][0] if not isinstance(rows[0], dict) else list(rows[0].values())[0]
            return (table, col, str(val))
    return "absent" if checked else None


def _available_grain(tables: dict, measure_tables: set, requested: str):
    """(available_grain, feasible_via) for the asked-for measure at the requested
    grain. Scans ONLY the tables that carry that measure. Among those that can serve
    the requested grain it picks DETERMINISTICALLY — a canonical fact table over a
    niche/indirect one (orders' order_date beats clienteling's interaction_date), not
    whichever the set happened to yield first; otherwise the finest measure-table grain
    is the ceiling (→ answer-at-coarser caveat)."""
    want = _RANK[requested]
    finest = None
    servers = []  # (is_fact, -rank, table)
    for tname in measure_tables:
        cols = tables.get(tname, [])
        tg = _columns_grain(cols)
        if tg is None:
            continue
        if _RANK[tg] <= want:
            servers.append((bool(_FACT_TABLE.search(tname)), -_RANK[tg], tname))
        if finest is None or _RANK[tg] < _RANK[finest]:
            finest = tg
    if servers:
        servers.sort(reverse=True)                 # fact table first, then finest grain
        best = servers[0][2]
        return _columns_grain(tables.get(best, [])), best
    return finest, None


def _finer_grain_fallback(tables: dict, requested: str, measures: list[str],
                          entity_dim_col: Optional[str]):
    """When the governed measure's own table is too coarse for the requested grain,
    find the TRANSACTIONAL fact table that can serve it: an ACTUAL (non-estimated)
    revenue-family measure column + a time column at least as fine as requested +
    (the entity's filter dimension, when one was bound, so the filter transfers).
    Prefers a canonical fact table over a niche/indirect proxy. Returns
    ``(table, measure_col, grain)`` or ``None``.

    This is the antidote to the FALSE 'monthly is impossible' the strict measure-table
    scan produces when — e.g. — net_sales is a yearly summary but order_date exists on
    the orders fact. Gated to revenue-type questions (or no named measure); the
    est_-prefix + indirect-proxy exclusions keep an estimate table (est_gmv by
    launch_date) from hijacking the answer the way the measure-first design already
    guards entity binding."""
    if measures and not any(_REVENUE_FAMILY.search(m) for m in measures):
        return None                                 # only revenue asks have this proxy
    want = _RANK[requested]
    best = None  # (is_fact, -rank_penalty, table, measure_col, grain) — higher is better
    for t, cols in tables.items():
        tg = _columns_grain(cols)
        if tg is None or _RANK[tg] > want:
            continue                                # can't serve the requested grain
        if entity_dim_col and entity_dim_col not in cols:
            continue                                # the entity filter can't transfer
        actual = [c for c in cols if _REVENUE_FAMILY.search(c) and not _EST_PREFIX.search(c)]
        if not actual:
            continue                                # no real revenue measure here
        direct = [c for c in actual if not _INDIRECT_MEASURE.search(c)]
        measure_col = (direct or actual)[0]
        is_fact = bool(_FACT_TABLE.search(t))
        is_direct = bool(direct)
        # rank: canonical fact table first, then a direct (non-proxy) measure, then finer grain
        key = (is_fact, is_direct, -_RANK[tg])
        if best is None or key > best[0]:
            best = (key, t, measure_col, tg)
    if best is None:
        return None
    return best[1], best[2], best[3]


def resolve(question: str, *, schema: str = "", db=None, connection_id: str = "",
            eff_schema: Optional[str] = None, prior_context: str = "") -> Resolution:
    """The single ground-first verdict. Never raises; degrades to ``answerable``.

    Measure-first: resolve WHAT the question is about (the measure), then bind the
    entity and read the grain from the table(s) that actually carry that measure —
    so an unrelated table sharing the entity value (or a stray date column) can't
    hijack the answer.

    ``prior_context`` (the previous turn's question) makes a FOLLOW-UP conversation-aware:
    when the current question names no entity of its own, it inherits the prior turn's
    entities — so "break that down by platform" keeps the earlier filter instead of
    resolving against nothing. Empty (the default) → single-turn behaviour, unchanged."""
    r = Resolution(question=question)
    try:
        tables, domains = _parse_schema(schema)
        measures = _question_measures(question)
        mtables = _measure_tables(tables, measures)

        # ── entity resolution — bind to a MEASURE-bearing table when possible ──
        candidates = _entity_candidates(question)
        # Conversation carry-forward: a follow-up that REFERS BACK to the prior result ("break
        # THAT down by platform", "filter THOSE to Q3") and names no entity of its own inherits
        # the prior turn's entities (from `prior_context`) — keeping the earlier 'womenswear'
        # filter. Gated on an explicit DEICTIC reference, never on a bare empty extraction: a
        # follow-up that introduces a new noun ("what about menswear?") must NOT inherit the old
        # entity even though the extractor misses the lowercase noun. An inherited entity absent
        # in this scope is not a dead-end (the prior turn grounded it) so it never abstains.
        inherited = bool(prior_context) and not candidates and bool(_DEICTIC.search(question))
        if inherited:
            candidates = _entity_candidates(prior_context)
        # Warmed high-card value samples (R5) — loaded once, read-only. Lets an
        # entity that exists in the data bind offline instead of live-probing the
        # warehouse per token; empty when nothing is cached → live probe as before.
        value_samples: dict = {}
        if candidates and connection_id:
            try:
                from aughor.tools.profile_cache import load_value_samples
                value_samples = load_value_samples(connection_id)
            except Exception:
                value_samples = {}
        # R11 — a per-column-config `index: false` retires a column's persisted
        # sample immediately (the capture gate honours the config only on the
        # next profile rebuild, and old-fingerprint entries linger). Flag-gated;
        # any hiccup keeps the unfiltered map.
        if value_samples:
            try:
                from aughor.kernel.flags import flag_enabled
                if flag_enabled("ontology.column_config"):
                    from aughor.ontology.column_config import load_index_disabled
                    _idx_off = load_index_disabled(connection_id)
                    if _idx_off:
                        value_samples = {
                            k: v for k, v in value_samples.items() if k not in _idx_off
                        }
            except Exception as _idx_exc:
                from aughor.kernel.errors import tolerate
                tolerate(_idx_exc, "column-config sample retire-filter is best-effort",
                         counter="ontology.column_config", conn_id=connection_id or None)
        for token in candidates:
            matches = _annotation_matches(token, domains)
            if matches:
                t, c, v, conf = _pick(matches, mtables)
                r.entity_bindings.append(EntityBinding(token, t, c, v, conf))
                continue
            probe = _db_find_value(db, schema, token, prefer_tables=mtables,
                                   value_samples=value_samples, question=question)
            if isinstance(probe, tuple):
                r.entity_bindings.append(EntityBinding(token, probe[0], probe[1], probe[2], 0.95))
            elif probe == "absent" and not inherited:
                r.not_found.append(token)
        if r.not_found:
            # name a couple of real values from the probed dimension so the answer
            # can say "here's what IS present" instead of a bare "not found".
            sample = next((f"present values include: {', '.join(v[:5])}"
                           for _t, _c, v in domains), "")
            r.what_is_available = sample

        # ── time-grain resolution — over the measure's table(s) only ──
        # (skip entirely on an abstain — a not-found entity needs no grain verdict.)
        req = requested_time_grain(question)
        if req is not None and not r.not_found:
            r.requested_grain = req
            avail, via = _available_grain(tables, mtables, req)
            r.available_grain = avail
            r.grain_feasible_via = via
            # The governed measure's own table can't serve the finer grain (via is None
            # and the finest available is coarser). Before declaring the grain
            # impossible, look for the transactional fact path (order_date exists!) and
            # answer FROM it — noting the measure may be transactional.
            coarse = (avail is not None and _RANK[avail] > _RANK[req])
            if via is None and (coarse or avail is None):
                entity_dim = r.entity_bindings[0].column if r.entity_bindings else None
                fb = _finer_grain_fallback(tables, req, measures, entity_dim)
                if fb is not None:
                    fb_table, fb_measure, fb_grain = fb
                    r.grain_feasible_via = fb_table
                    r.available_grain = fb_grain
                    # If the fallback measure differs from the governed one, say so.
                    gov = next((c for t in mtables for c in tables.get(t, [])
                                if _col_matches_measure(c, measures or [])), None)
                    if gov and gov.lower() != fb_measure.lower():
                        r.grain_note = (f"{req} figures use `{fb_table}.{fb_measure}` (transaction-level); "
                                        f"the governed `{gov}` is only summarized at {avail or 'a coarser'} grain")
            # Unify: whenever a finer table serves the grain, the entity FILTER and the
            # GRAIN must name ONE table — rebind the filter onto the grain table (same
            # dimension column, verified present) so the generator can't split them.
            if r.grain_feasible_via:
                for b in r.entity_bindings:
                    if b.table != r.grain_feasible_via and b.column in tables.get(r.grain_feasible_via, []):
                        b.table = r.grain_feasible_via

        # ── metric-class feasibility ──
        try:
            from aughor.semantic.metric_feasibility import unsupported_metric_gap
            r.measure_gap = unsupported_metric_gap(question, schema) or None
        except Exception:
            r.measure_gap = None
    except Exception:
        return Resolution(question=question)  # answerable, no constraints — never break the answer
    return r
