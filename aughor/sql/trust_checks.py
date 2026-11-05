"""Result-trust checks — deterministic critiques for the CIDR-2026 E1 "function-semantics" footguns.

CIDR 2026 ("Text-to-SQL Benchmarks are Broken", Jin et al.) found 53–66% of gold SQL is wrong, under a
taxonomy E1–E4. Most patterns Aughor already guards: **E2** (fan-out / missing DISTINCT) = `grain_guard`,
**E3** (suspect join) = `join_guard` value-domain, **E4** (ambiguous column) = `tools.ambiguity`. The
open gap is **E1 — function/operator semantics that silently return the WRONG rows**:

  * a TIMESTAMP column compared to a DATE-only literal (midnight) → `<= 'date'` / `BETWEEN … 'date'`
    drops that day's later rows (CIDR Spider2-Snow TO_TIMESTAMP boundary example). Where the schema
    types the column, the guard battery reads that bound whole before the statement runs
    (`sql.day_window`, 2026-10-09: this caveat never reached the reader of a live answer that lost a
    day); this check caveats the shape everywhere else;
  * ORDER BY / MIN / MAX over a numeric-looking TEXT column → lexicographic sort ('10' < '2')
    (CIDR "misranking values lexicographically");
  * a TEXT column compared to a numeric literal → lexicographic / implicit-cast surprise
    (CIDR `CAST(T2.RF AS REAL) < 20` example).

Deterministic and execution-free (pure AST + optional column types) — the safe lever class proven on
strong models (§6 of the Spider2 work): it emits a *labelled caveat*, never overwrites a query, so it
surfaces the issue instead of silently returning a wrong answer — catching the analyst's error, or the
gold's. Column types are optional: the date-boundary check falls back to a conservative name heuristic;
the text/numeric checks require types (skipped, never guessing, when types are absent).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

import sqlglot
from sqlglot import exp

_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TS_TYPE = ("TIMESTAMP", "DATETIME")                       # NOT plain DATE (date vs date is fine)
_TEXT_TYPE = ("VARCHAR", "TEXT", "CHAR", "STRING", "CLOB")
_NUMERICISH = ("num", "amount", "amt", "count", "cnt", "score", "rate", "qty", "price", "rf",
               "value", "val", "rank", "year", "age", "level", "rating", "total", "balance")


#: Arc NV-6 — dialects whose `/` on two integers truncates (7 / 2 = 3). DuckDB, BigQuery, Snowflake, MySQL, ClickHouse and
#: Spark divide to a fraction; these do not, and a ratio written as `a / b` over counts or integer columns silently loses
#: everything after the point.
_TRUNCATING_DIVISION = frozenset({"postgres", "postgresql", "sqlite", "tsql", "mssql", "trino", "presto", "oracle"})
_INT_TYPE = ("INT", "SERIAL", "SMALLINT", "BIGINT", "TINYINT")
#: a literal this many times the column's observed maximum is a different scale, not a large value
_SCALE_FACTOR = 100.0


@dataclass
class TrustIssue:
    pattern: str        # "E1-date-boundary" | "E1-lexicographic-order" | "E1-text-numeric-compare" | "E1-text-date-compare"
                        # | "E1-integer-division" | "E1-scale-mismatch"
    subject: str        # the column / expression involved
    message: str

    def to_dict(self) -> dict:
        return {"pattern": self.pattern, "subject": self.subject, "message": self.message}


def _alias_to_table(tree: exp.Expression) -> dict:
    m: dict = {}
    for t in tree.find_all(exp.Table):
        m[t.name.lower()] = t.name
        if t.alias:
            m[t.alias.lower()] = t.name
    return m


def _coltype(col: exp.Column, a2t: dict, single: Optional[str], col_types: Optional[dict]) -> Optional[str]:
    if not col_types:
        return None
    name = col.name.lower()
    t = a2t.get(col.table.lower()) if col.table else single   # resolve unqualified to the lone table
    if t and f"{t.lower()}.{name}" in col_types:
        return col_types[f"{t.lower()}.{name}"]
    return col_types.get(name)


def _is_timestamp(col: exp.Column, a2t: dict, single: Optional[str], col_types: Optional[dict]) -> bool:
    t = _coltype(col, a2t, single, col_types)
    if t:
        up = t.upper()
        return any(x in up for x in _TS_TYPE)            # DATE alone → False (no intra-day issue)
    name = col.name.lower()                               # heuristic when type unknown
    if name.endswith(("_date",)) or name == "date":
        return False
    return name.endswith(("_at", "_ts", "_time")) or name == "ts" or "timestamp" in name or "datetime" in name


def _is_text(col: exp.Column, a2t: dict, single: Optional[str], col_types: Optional[dict]) -> bool:
    t = _coltype(col, a2t, single, col_types)
    return bool(t) and any(x in t.upper() for x in _TEXT_TYPE)


def _names_a_column(word: str, all_tables: set, col_types: Optional[dict]) -> bool:
    """True when `word` is a column on a table this query reads. Used only to SHARPEN the
    quoted-identifier caveat's suggestion, never to decide whether to emit it — the module's
    rule is that the text/numeric checks skip rather than guess, and this one has nothing to
    guess about: two literals compared is a bug whatever the schema says."""
    if not word or not col_types:
        return False
    w = word.lower()
    if w in col_types:
        return True
    return any(f"{t}.{w}".lower() in col_types for t in (all_tables or ()))


def _facts_of(col: exp.Column, a2t: dict, single: Optional[str], col_facts: Optional[dict]) -> dict:
    """The profiled facts for a column (`connection_column_facts`), resolved like `_coltype`: `table.col` first, the bare
    name as a fallback. {} when nothing is known — every check reading it then says nothing."""
    if not col_facts:
        return {}
    name = col.name.lower()
    t = a2t.get(col.table.lower()) if col.table else single
    if t and f"{t.lower()}.{name}" in col_facts:
        return col_facts[f"{t.lower()}.{name}"]
    if t and f"{t.lower().split('.')[-1]}.{name}" in col_facts:
        return col_facts[f"{t.lower().split('.')[-1]}.{name}"]
    return col_facts.get(name, {})


def _is_integer(col: exp.Column, a2t: dict, single: Optional[str], col_types: Optional[dict]) -> bool:
    t = _coltype(col, a2t, single, col_types)
    return bool(t) and any(x in t.upper() for x in _INT_TYPE) and "POINT" not in t.upper()


def _integer_valued(node: exp.Expression, a2t: dict, single: Optional[str], col_types: Optional[dict]) -> bool:
    """An operand of a division that is a whole number: a COUNT, an integer-typed column, or an integer literal."""
    if isinstance(node, exp.Paren):
        return _integer_valued(node.this, a2t, single, col_types)
    if isinstance(node, exp.Count):
        return True
    if isinstance(node, exp.Column):
        return _is_integer(node, a2t, single, col_types)
    if isinstance(node, exp.Literal) and not node.is_string:
        return "." not in (node.name or "") and "e" not in (node.name or "").lower()
    if isinstance(node, (exp.Sum, exp.Min, exp.Max)) and isinstance(node.this, exp.Column):
        return _is_integer(node.this, a2t, single, col_types)
    return False


def _numeric_literal(node) -> Optional[float]:
    if isinstance(node, exp.Literal) and not node.is_string:
        try:
            return float(node.name)
        except (TypeError, ValueError):
            return None
    if isinstance(node, exp.Neg):
        inner = _numeric_literal(node.this)
        return -inner if inner is not None else None
    return None


def _numericish_name(name: str) -> bool:
    n = name.lower()
    return any(tok in n for tok in _NUMERICISH)


def _date_only_literal(node) -> Optional[str]:
    if isinstance(node, exp.Literal) and node.is_string and _DATE_ONLY.match(node.this or ""):
        return node.this
    return None


def run_trust_checks(sql: str, *, col_types: Optional[dict] = None,
                     dialect: str = "duckdb",
                     phase: str = "trust_check",
                     connection_id: str = "",
                     col_facts: Optional[dict] = None) -> list[TrustIssue]:
    """Return E1 function-semantics caveats for `sql`. Pure AST; never raises. `col_types` keys are
    lowercased "table.col" and/or "col" → type string (optional).

    Arc NV-6 — `col_facts` (same keys → the profiled facts of :func:`connection_column_facts`: a text column's date
    notation, the measured value range, what the values mean) feeds three more checks: a text date compared or
    sorted as text (`E1-text-date-compare`, the notation named so the fix is a cast with it), a division of two
    whole numbers on an engine that truncates (`E1-integer-division`), and a literal a hundred times the column's
    observed maximum, or a percent given for a fraction (`E1-scale-mismatch`). Given a `connection_id` and no
    `col_facts`, the facts are read from the connection's profile cache, cached per process; with neither, those
    three checks say nothing — they never guess.

    PENDING item 27 — given the `connection_id`, also a SUM of a reading at a moment the connection's ontology
    declares (a stock, a balance) that spans more than one of its moments (`semiadditive-sum`,
    `aughor.sql.semiadditive`), the declarations read through the readings registry. Without one, or with nothing
    declared, the check reads nothing.

    MI-1: a fire is also PERSISTED, from here rather than from the callers. Four sites run
    these checks (the quick path, the deep path, the executor and the trust scope) and a
    fifth is the eval plane; recording at each would be five chances to miss one — the same
    shape as the capability that missed a connector three times. `phase` names which caller
    ran it, and carries the weight now that every fire is kept: it is what separates
    production supervision from `eval` and from a speculative `validate`. A site that
    forgets it degrades to the default label, never to silence.

    The write is best-effort and never raises, so the "never raises" half of the contract
    above holds exactly. It is no longer free, though — a FIRE costs a row wherever it
    happens (~1% of statements, measured). That is deliberate: gating on an ambient trace
    discarded ~85% of fires, because only the ask door binds one."""
    try:
        tree = sqlglot.parse_one(sql, read=dialect)
    except Exception:
        return []
    if tree is None:
        return []
    if col_facts is None and connection_id:
        col_facts = connection_column_facts(connection_id)
    a2t = _alias_to_table(tree)
    all_tables = {t.name for t in tree.find_all(exp.Table)}
    single = next(iter(all_tables)) if len(all_tables) == 1 else None
    out: list[TrustIssue] = []
    seen: set = set()

    def _emit(pattern: str, subject: str, message: str) -> None:
        key = (pattern, subject.lower())
        if key not in seen:
            seen.add(key)
            out.append(TrustIssue(pattern, subject, message))

    # E1-date-boundary: a TIMESTAMP column bounded by a DATE-only literal misses that day's later rows.
    for b in tree.find_all(exp.Between):
        col = b.this
        hi = _date_only_literal(b.args.get("high"))
        if isinstance(col, exp.Column) and hi and _is_timestamp(col, a2t, single, col_types):
            _emit("E1-date-boundary", col.name,
                  f"'{col.name}' looks like a timestamp but is bounded by the date-only literal "
                  f"'{hi}' (midnight), so BETWEEN … '{hi}' drops rows later that day. Use "
                  f"`< '{hi}' + 1 day` or cast the column to DATE.")
    for node in tree.find_all(exp.LTE):
        for col, lit in ((node.left, node.right), (node.right, node.left)):
            d = _date_only_literal(lit)
            if isinstance(col, exp.Column) and d and _is_timestamp(col, a2t, single, col_types):
                _emit("E1-date-boundary", col.name,
                      f"'{col.name}' looks like a timestamp but is compared `<= '{d}'` (midnight), so "
                      f"rows later on {d} are dropped. Use `< '{d}' + 1 day` or cast to DATE.")

    # E1-lexicographic-order: ORDER BY / MIN / MAX over a numeric-looking TEXT column sorts as strings.
    for o in tree.find_all(exp.Ordered):
        c = o.this
        if isinstance(c, exp.Column) and _is_text(c, a2t, single, col_types) and _numericish_name(c.name):
            _emit("E1-lexicographic-order", c.name,
                  f"'{c.name}' is a text column; ORDER BY sorts it lexicographically ('10' < '2'). "
                  f"CAST to a numeric type if it stores numbers.")
    for agg in list(tree.find_all(exp.Min)) + list(tree.find_all(exp.Max)):
        c = agg.this
        if isinstance(c, exp.Column) and _is_text(c, a2t, single, col_types) and _numericish_name(c.name):
            _emit("E1-lexicographic-order", c.name,
                  f"MIN/MAX over text column '{c.name}' compares lexicographically ('10' < '2'). "
                  f"CAST to a numeric type if it stores numbers.")

    # E1-text-numeric-compare: a TEXT column compared to a bare numeric literal.
    for cmp_cls in (exp.GT, exp.LT, exp.GTE, exp.LTE, exp.EQ, exp.NEQ):
        for node in tree.find_all(cmp_cls):
            for col, lit in ((node.left, node.right), (node.right, node.left)):
                if (isinstance(col, exp.Column) and isinstance(lit, exp.Literal)
                        and not lit.is_string and _is_text(col, a2t, single, col_types)):
                    _emit("E1-text-numeric-compare", col.name,
                          f"Text column '{col.name}' is compared to the numeric literal {lit.name}; "
                          f"this compares lexicographically / casts unexpectedly. "
                          f"CAST({col.name} AS <numeric>) for a numeric comparison.")
    # Arc NV-6 · E1-text-date-compare: a TEXT column whose dates the profiler read a notation for (or found ambiguous) is
    # compared to, bounded by, or sorted as text. '2/1/2017' < '11/8/2016' character by character; the fix is a cast
    # WITH the notation, which is why the notation is said.
    def _text_date(col) -> Optional[dict]:
        if not isinstance(col, exp.Column):
            return None
        f = _facts_of(col, a2t, single, col_facts)
        return f if (f.get("format") or f.get("format_note", "").startswith("ambiguous")) else None

    def _say_text_date(col, f, how: str) -> None:
        if f.get("format"):
            _emit("E1-text-date-compare", col.name,
                  f"'{col.name}' is a text column whose dates are written {f['format']}; {how} compares it character by "
                  f"character ('2/1/2017' sorts before '11/8/2016'). Parse it with that notation first — on DuckDB "
                  f"STRPTIME({col.name}, <{f['format']} as a format string>), on Postgres TO_DATE, on BigQuery PARSE_DATE — "
                  f"and compare the result as a date.")
        else:
            _emit("E1-text-date-compare", col.name,
                  f"'{col.name}' is a text column of dates whose notation is AMBIGUOUS (every day ≤ 12 reads as both DD/MM "
                  f"and MM/DD); {how} compares it as text, and no cast can be trusted until a person declares the notation "
                  f"on the property.")

    for cmp_cls in (exp.GT, exp.LT, exp.GTE, exp.LTE, exp.EQ, exp.NEQ):
        for node in tree.find_all(cmp_cls):
            for col, lit in ((node.left, node.right), (node.right, node.left)):
                f = _text_date(col)
                if f and isinstance(lit, exp.Literal) and lit.is_string:
                    _say_text_date(col, f, f"`{cmp_cls.__name__.lower()} '{lit.this}'`")
    for b in tree.find_all(exp.Between):
        f = _text_date(b.this)
        if f:
            _say_text_date(b.this, f, "BETWEEN")
    for o in tree.find_all(exp.Ordered):
        f = _text_date(o.this)
        if f:
            _say_text_date(o.this, f, "ORDER BY")
    for agg in list(tree.find_all(exp.Min)) + list(tree.find_all(exp.Max)):
        f = _text_date(agg.this)
        if f:
            _say_text_date(agg.this, f, "MIN/MAX")

    # Arc NV-6 · E1-integer-division: `a / b` over two whole numbers on an engine whose `/` truncates. A ratio of
    # counts — the commonest measure there is — comes back 0 or 1 and nobody is told.
    # sqlglot already carries the engine's semantics on the node: `typed=True` is a `/` that keeps the operands' type
    # (Postgres, SQLite, T-SQL, Trino), `safe=True` one that always divides to a fraction (DuckDB). The dialect list is
    # the fallback for a parser that marks neither.
    for div in tree.find_all(exp.Div):
        if div.args.get("safe"):
            continue
        if div.args.get("typed") or str(dialect or "").lower() in _TRUNCATING_DIVISION:
            if _integer_valued(div.left, a2t, single, col_types) and _integer_valued(div.right, a2t, single, col_types):
                _emit("E1-integer-division", div.sql(),
                      f"`{div.sql()}` divides two whole numbers, and on {dialect} that truncates (7 / 2 = 3): a ratio "
                      f"of counts comes back 0 or 1. Make one side a decimal first — `{div.left.sql()} * 1.0 / "
                      f"{div.right.sql()}` or a CAST to DOUBLE.")

    # Arc NV-6 · E1-scale-mismatch: a literal a hundred times the column's observed maximum, or a percent compared to a
    # fraction of 1. Both read a filter that keeps no row and say nothing.
    for cmp_cls in (exp.GT, exp.LT, exp.GTE, exp.LTE, exp.EQ, exp.NEQ):
        for node in tree.find_all(cmp_cls):
            for col, lit in ((node.left, node.right), (node.right, node.left)):
                if not isinstance(col, exp.Column):
                    continue
                value = _numeric_literal(lit)
                f = _facts_of(col, a2t, single, col_facts)
                rng = f.get("value_range") if f else None
                if value is None or not rng:
                    continue
                lo, hi = rng
                interp = str(f.get("value_interpretation") or "")
                if interp.startswith("fraction") and hi <= 1.0 and 1.0 < abs(value) <= 100.0:
                    _emit("E1-scale-mismatch", col.name,
                          f"'{col.name}' is a fraction of 1 (observed {lo:g}–{hi:g}); the literal {value:g} reads like a "
                          f"percent. Compare to {value / 100:g}, or multiply the column by 100 first.")
                elif hi > 0 and abs(value) >= _SCALE_FACTOR * hi:
                    _emit("E1-scale-mismatch", col.name,
                          f"'{col.name}' was observed between {lo:g} and {hi:g}; the literal {value:g} is at least "
                          f"{_SCALE_FACTOR:g}× its maximum — a different unit or scale, not a large value. The filter "
                          f"keeps no row.")

    # E1-quoted-identifier: a STRING literal compared to a NUMERIC literal — `WHERE 'id' = 165428`.
    #
    # The sibling check above needs a Column on one side, so it is blind to the case where the
    # column reference was never a column: quoting it turned `id` into the three-character string
    # "id", and the predicate now compares two CONSTANTS. Found on a live BigQuery run
    # (2026-09-02) where the editor reported "Guards clean" and the warehouse then refused the
    # job outright — the badge was honest about what it checks and still read as a clean bill of
    # health on a query that could not run.
    #
    # Two outcomes, and the second is why this is worth a caveat rather than just letting the
    # engine complain. STRICT engines (BigQuery) reject it: "No matching signature for operator
    # =" — noisy, but safe, and it costs a round trip. COERCING engines do not: the predicate is
    # a constant that is always FALSE, so the query succeeds and returns ZERO ROWS, and an
    # analyst reads "no data" as a fact about the world. That is the well-formed wrong answer
    # this codebase ranks below an exception.
    #
    # Precision: mismatched literal TYPES only. `WHERE 1 = 1` is the idiomatic generated-SQL
    # placeholder (numeric vs numeric — never flagged), and `WHERE 'a' = 'b'` is string vs string,
    # which is ambiguous enough to leave alone. A quoted word against a number is neither.
    for cmp_cls in (exp.GT, exp.LT, exp.GTE, exp.LTE, exp.EQ, exp.NEQ):
        for node in tree.find_all(cmp_cls):
            for s_lit, n_lit in ((node.left, node.right), (node.right, node.left)):
                if not (isinstance(s_lit, exp.Literal) and s_lit.is_string
                        and isinstance(n_lit, exp.Literal) and not n_lit.is_string):
                    continue
                word = str(s_lit.name)
                # Name the intent when we can PROVE it: the quoted text is a real column on a
                # table this query reads. `col_types` is optional everywhere in this module, so
                # the caveat degrades to the general form rather than disappearing — the
                # comparison is a bug either way, and only the suggestion needs the types.
                looks_like_column = _names_a_column(word, all_tables, col_types)
                fix = (f"Did you mean the column `{word}` (unquoted)?" if looks_like_column
                       else f"If `{word}` is a column, remove the quotes.")
                _emit("E1-quoted-identifier", word,
                      f"'{word}' is quoted, so this compares the STRING \'{word}\' to the number "
                      f"{n_lit.name} — not a column to a value. {fix} A strict engine refuses the "
                      f"query; a coercing one returns zero rows from an always-false predicate.")

    # PENDING item 27 — a SUM of a declared reading at a moment across its moments counts the same quantity once
    # per reading. Declared on the ontology, read here as plain data through the registry the agent fills.
    if connection_id:
        from aughor.kernel.registries.readings import declared_readings_for
        declared = declared_readings_for(connection_id)
        if declared:
            from aughor.sql.semiadditive import semiadditive_misuse
            hit = semiadditive_misuse(sql, declared, dialect=dialect)
            if hit is not None:
                _emit("semiadditive-sum", *hit)

    if out:
        from aughor.stats import bump
        bump("guard.trust_e1.fired", len(out))
        from aughor.security.audit import GuardVerdicts
        for _issue in out:
            GuardVerdicts.record(pattern=_issue.pattern, subject=_issue.subject,
                                 phase=phase, sql=sql, detail=_issue.message)
    return out


# Per-connection real column types for the E1 checks, cached like `_GRAIN_CACHE` (one
# information_schema scan per connection). Feeding real types is what makes the date-boundary
# check precise: a DATE column named like a timestamp (`acquired_at`, `order_purchase_ts`) is
# then correctly NOT flagged — `_is_timestamp` returns False for DATE — instead of tripping the
# name heuristic. Without this, the live answer paths call run_trust_checks with no types and a
# DATE-named-*_at column produces a false-positive boundary caveat (WP-1f A/B finding).
_COLTYPE_CACHE: dict[str, dict] = {}
_COLTYPES_SQL = "SELECT table_name, column_name, data_type FROM INFORMATION_SCHEMA.COLUMNS"


def _coltype_cache_key(conn_id: str, db) -> str:
    """A stable per-connection cache key. Prefer the connection id; fall back to the
    connection's path/dsn so an id-LESS connection (the fixture opens with an empty id,
    yet is the hot demo path) still caches instead of re-scanning every answer — while two
    different id-less connections still get distinct keys (no cross-connection leak)."""
    return str(conn_id or getattr(db, "_path", "") or getattr(db, "_dsn", "") or "")


_COLFACTS_CACHE: dict[str, dict] = {}


def connection_column_facts(conn_id: str) -> dict:
    """Arc NV-6 — the profiled facts the checks read (`profile_cache.load_column_facts`) as the `col_facts` map: keys
    lowercased "table.col" AND bare "col" → {format, format_note, value_range, value_interpretation, dtype}. Cached per
    process and connection; an empty profile caches as empty too, since the cache is the source and a rebuild of it is
    what changes the answer (the ontology rebuild clears this map). Never raises."""
    if conn_id in _COLFACTS_CACHE:
        return _COLFACTS_CACHE[conn_id]
    out: dict = {}
    try:
        from aughor.tools.profile_cache import load_column_facts
        for (tbl, col), facts in load_column_facts(conn_id).items():
            if not (facts.get("format") or facts.get("format_note") or facts.get("value_range")):
                continue
            out[f"{str(tbl).lower()}.{str(col).lower()}"] = facts
            out[f"{str(tbl).lower().split('.')[-1]}.{str(col).lower()}"] = facts
            out.setdefault(str(col).lower(), facts)
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "E1 column-facts read is best-effort; the notation, range and division checks say nothing",
                 counter="trust.e1_colfacts")
        return {}
    _COLFACTS_CACHE[conn_id] = out
    return out


def forget_column_facts(conn_id: str = "") -> None:
    """Drop the cached facts for one connection, or all — a rebuilt profile must be read again."""
    if conn_id:
        _COLFACTS_CACHE.pop(conn_id, None)
    else:
        _COLFACTS_CACHE.clear()


def connection_column_types(conn_id: str, db) -> dict:
    """Real column types for a connection → the `col_types` map run_trust_checks wants (keys
    lowercased "table.col" AND bare "col" → type string), cached per connection. Best-effort:
    on failure returns ``{}`` (the E1 checks fall back to their name heuristic) and does NOT
    cache, so a transient warehouse outage doesn't pin the connection to the heuristic for the
    whole process. Read-only single introspection scan."""
    key = _coltype_cache_key(conn_id, db)
    if key and key in _COLTYPE_CACHE:
        return _COLTYPE_CACHE[key]
    out: dict = {}
    ok = False
    try:
        # execute_bounded (not execute) so a wide-schema warehouse's information_schema is not
        # truncated at the 500-row answer cap — that would drop most columns, revert the E1
        # checks to the name heuristic, and reintroduce the DATE-named-*_at false positive WP-1f
        # closed. 50k column-rows covers any realistic schema; fail-open on a driver without it.
        _bounded = getattr(db, "execute_bounded", None)
        r = (_bounded("__trust_coltypes__", _COLTYPES_SQL, 50_000, sql_dialect="duckdb") if _bounded
             else db.execute("__trust_coltypes__", _COLTYPES_SQL, sql_dialect="duckdb", internal=True))
        if r and not r.error:
            ok = True
            for tbl, col, dt in (r.rows or []):
                if col and dt:
                    out[f"{str(tbl).lower()}.{str(col).lower()}"] = str(dt)
                    out.setdefault(str(col).lower(), str(dt))
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "E1 col-types introspection is best-effort; the name heuristic applies",
                 counter="trust.e1_coltypes")
    if key and ok:                       # cache only a SUCCESSFUL scan (never a transient {})
        _COLTYPE_CACHE[key] = out
    return out
