"""Result-trust checks — deterministic critiques for the CIDR-2026 E1 "function-semantics" footguns.

CIDR 2026 ("Text-to-SQL Benchmarks are Broken", Jin et al.) found 53–66% of gold SQL is wrong, under a
taxonomy E1–E4. Most patterns Aughor already guards: **E2** (fan-out / missing DISTINCT) = `grain_guard`,
**E3** (suspect join) = `join_guard` value-domain, **E4** (ambiguous column) = `tools.ambiguity`. The
open gap is **E1 — function/operator semantics that silently return the WRONG rows**:

  * a TIMESTAMP column compared to a DATE-only literal (midnight) → `<= 'date'` / `BETWEEN … 'date'`
    drops that day's later rows (CIDR Spider2-Snow TO_TIMESTAMP boundary example);
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


@dataclass
class TrustFinding:
    pattern: str        # "E1-date-boundary" | "E1-lexicographic-order" | "E1-text-numeric-compare"
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


def _numericish_name(name: str) -> bool:
    n = name.lower()
    return any(tok in n for tok in _NUMERICISH)


def _date_only_literal(node) -> Optional[str]:
    if isinstance(node, exp.Literal) and node.is_string and _DATE_ONLY.match(node.this or ""):
        return node.this
    return None


def run_trust_checks(sql: str, *, col_types: Optional[dict] = None,
                     dialect: str = "duckdb") -> list[TrustFinding]:
    """Return E1 function-semantics caveats for `sql`. Pure AST; never raises. `col_types` keys are
    lowercased "table.col" and/or "col" → type string (optional)."""
    try:
        tree = sqlglot.parse_one(sql, read=dialect)
    except Exception:
        return []
    if tree is None:
        return []
    a2t = _alias_to_table(tree)
    all_tables = {t.name for t in tree.find_all(exp.Table)}
    single = next(iter(all_tables)) if len(all_tables) == 1 else None
    out: list[TrustFinding] = []
    seen: set = set()

    def _emit(pattern: str, subject: str, message: str) -> None:
        key = (pattern, subject.lower())
        if key not in seen:
            seen.add(key)
            out.append(TrustFinding(pattern, subject, message))

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
    if out:
        from aughor.stats import bump
        bump("guard.trust_e1.fired", len(out))
    return out


# Per-connection real column types for the E1 checks, cached like `_GRAIN_CACHE` (one
# information_schema scan per connection). Feeding real types is what makes the date-boundary
# check precise: a DATE column named like a timestamp (`acquired_at`, `order_purchase_ts`) is
# then correctly NOT flagged — `_is_timestamp` returns False for DATE — instead of tripping the
# name heuristic. Without this, the live answer paths call run_trust_checks with no types and a
# DATE-named-*_at column produces a false-positive boundary caveat (WP-1f A/B finding).
_COLTYPE_CACHE: dict[str, dict] = {}
_COLTYPES_SQL = "SELECT table_name, column_name, data_type FROM information_schema.columns"


def _coltype_cache_key(conn_id: str, db) -> str:
    """A stable per-connection cache key. Prefer the connection id; fall back to the
    connection's path/dsn so an id-LESS connection (the fixture opens with an empty id,
    yet is the hot demo path) still caches instead of re-scanning every answer — while two
    different id-less connections still get distinct keys (no cross-connection leak)."""
    return str(conn_id or getattr(db, "_path", "") or getattr(db, "_dsn", "") or "")


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
        r = (_bounded("__trust_coltypes__", _COLTYPES_SQL, 50_000) if _bounded
             else db.execute("__trust_coltypes__", _COLTYPES_SQL))
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
