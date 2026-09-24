"""PENDING item 27 — a written SUM of a reading at a moment that spans more than one of its moments.

A stock level or a balance is additive within one moment and not across moments: summing three daily readings of
the same stock counts it three times, and nothing about the number looks wrong. The ontology lets a person declare
such a property (``aughor.ontology.semiadditive``); this is the platform half — the pure reading of a statement the
trust checks (`run_trust_checks`) run on every answer path, given the declarations as plain data through the
readings registry (``aughor.kernel.registries.readings``), never by importing the agent.

A declared column is followed through the statement's own intermediate queries — each CTE and derived table, read
before the query that reads it (`traverse_scope`): an intermediate query that keeps the reading per moment (daily
totals grouped by the date, or its rows as they are) passes the reading on, under the name it gives it, with its
moment under the name it gives that — so `SUM(total)` over a CTE of daily totals is the same sum across moments
`SUM(on_hand)` is. One that keeps a single moment (pinned to one date, or the latest reading per partition by
`ROW_NUMBER() … = 1` or QUALIFY) passes on a quantity at one moment, which sums like any other.

A SUM is flagged when it reads a reading and its SELECT keeps no single moment: neither its GROUP BY holds the moment
column (bare, by position, by alias or under GROUP BY ALL), nor its WHERE pins the moment to one value (`=` a
literal, a scalar subquery or a function of neither; `IN` one value; `IN (SELECT MAX(<moment>) … GROUP BY <a
grouping this SELECT groups by too>)` — a month-end), nor a rank ordered by the moment is kept at 1, nor the sum is
divided by `COUNT(DISTINCT <moment>)` (an average per moment; `COUNT(*)` over rows that are one per moment). A window
SUM is not read. Deterministic and high-precision, like `measure_grain_misuse`: what it cannot follow it does not
flag. Never raises.
"""
from __future__ import annotations

from typing import Optional


def semiadditive_misuse(sql: str, declared: dict, *, dialect: str = "duckdb") -> Optional[tuple[str, str]]:
    """``(subject, sentence)`` for the first SUM of a declared reading that spans more than one moment, or None.
    ``declared`` is ``{table: {column: {"over": str, "note": str}}}``, every name lower-cased."""
    if not declared or not sql:
        return None
    try:
        import sqlglot
        from sqlglot import exp
        tree = sqlglot.parse_one(sql, read=dialect)
    except Exception:  # noqa: BLE001 — a statement that cannot be read is not flagged
        return None
    if tree is None:
        return None
    try:
        return _scoped_misuse(tree, declared, exp)
    except Exception:  # noqa: BLE001 — scopes that cannot be built: the statement read flat, its own tables only
        try:
            return _flat_misuse(tree, declared, exp)
        except Exception:  # noqa: BLE001 — never raises: a shape this reader did not foresee is not flagged
            return None


# ── following the reading through the statement ─────────────────────────────────────────────

def _scoped_misuse(tree, declared: dict, exp) -> Optional[tuple[str, str]]:
    from sqlglot.optimizer.scope import traverse_scope
    passed: dict[int, tuple[dict, dict]] = {}          # id(an intermediate SELECT) -> (readings, ranks) it passes on
    for scope in traverse_scope(tree):
        select = scope.expression
        if not isinstance(select, exp.Select):
            continue
        known, ranks = _sources(scope, declared, passed, exp)
        if not known:
            continue
        hit = _misuse_in(select, known, ranks, exp)
        if hit is not None:
            return hit
        passed[id(select)] = _passed_on(select, known, ranks, exp)
    return None


def _sources(scope, declared: dict, passed: dict, exp) -> tuple[dict, dict]:
    """``({alias: {column: reading}}, {alias: {rank column: moment}})`` for what this SELECT reads: a declaring table,
    or an intermediate query that passed readings or moment ranks on."""
    known: dict[str, dict] = {}
    ranks: dict[str, dict] = {}
    for name, (_, source) in scope.selected_sources.items():
        alias = name.lower()
        if isinstance(source, exp.Table):
            table = source.name.lower()
            columns = declared.get(table) or {}
            if columns:
                known[alias] = {c: {"over": str(s.get("over") or ""), "note": str(s.get("note") or ""),
                                    "visible": True, "table": True, "origin": f"{table}.{c}",
                                    "moment": str(s.get("over") or "")} for c, s in columns.items()}
        else:
            readings, rk = passed.get(id(source.expression), ({}, {}))
            if readings:
                known[alias] = readings
            if rk:
                ranks[alias] = rk
    return known, ranks


def _resolve(column, known: dict) -> Optional[tuple[str, dict]]:
    """The source and the reading a column names — by its qualifier, or, bare, the one source in reach that has it
    (a bare name two of them have is not guessed)."""
    name = column.name.lower()
    if column.table:
        alias = column.table.lower()
        reading = (known.get(alias) or {}).get(name)
        return (alias, reading) if reading is not None else None
    hits = [(alias, cols[name]) for alias, cols in known.items() if name in cols]
    return hits[0] if len(hits) == 1 else None


def _misuse_in(select, known: dict, ranks: dict, exp) -> Optional[tuple[str, str]]:
    for total in select.find_all(exp.Sum):
        if total.find_ancestor(exp.Select) is not select or total.find_ancestor(exp.Window) is not None:
            continue
        for column in total.find_all(exp.Column):
            hit = _resolve(column, known)
            if hit is None:
                continue
            alias, reading = hit
            over = reading["over"].lower()
            if (_one_moment(select, alias, reading, ranks, exp)
                    or per_moment(total, over, exp, rows=bool(reading.get("rows_per_moment")))):
                continue
            return _said(column, alias, reading)
    return None


def _said(column, alias: str, reading: dict) -> tuple[str, str]:
    over = reading["over"]
    note = f" ({reading['note']})" if reading.get("note") else ""
    moment = reading.get("moment") or over
    taken = over if moment.lower() == over.lower() else f"{over} (its {moment})"
    origin = reading.get("origin") or ""
    carried = not reading.get("table")
    subject = f"{alias}.{column.name.lower()}" if carried else origin
    via = f" ({origin}, carried through {alias})" if carried else ""
    if not reading.get("visible"):
        return (subject, f"SUM({column.name}) adds {subject}{via}, a reading at a moment taken over {taken}{note}, "
                         f"across {over} — and {alias} does not carry {over}, so nothing keeps one moment: it counts "
                         f"the same quantity once per reading. Keep {over} in {alias} and group by it, or use AVG, "
                         f"MIN or MAX.")
    return (subject, f"SUM({column.name}) adds {subject}{via}, a reading at a moment taken over {taken}{note}, across "
                     f"{over} — it counts the same quantity once per reading. Group by {over}, filter to one {over}, "
                     f"divide by COUNT(DISTINCT {over}), or use AVG, MIN or MAX.")


def _one_moment(select, alias: str, reading: dict, ranks: dict, exp) -> bool:
    over = reading["over"].lower()
    if reading.get("visible") and (_grouped_by(select, over, exp) or _pinned(select, over, exp)):
        return True
    return _ranked_one(select, over, ranks, exp) or _qualified_one(select, over, exp)


def _passed_on(select, known: dict, ranks: dict, exp) -> tuple[dict, dict]:
    """What an intermediate query passes on to the query reading it: each output that is still a reading ACROSS
    moments — the reading itself, an expression of it, or its SUM grouped by the moment — under its output name, with
    the moment under the name this query gives it; and each rank it computes ordered by a moment. An output at one
    moment (pinned, or the latest per partition) is a quantity like any other, and is not passed on."""
    aggregated = select.args.get("group") is not None or any(
        a.find_ancestor(exp.Window) is None for p in select.expressions for a in p.find_all(exp.AggFunc))
    readings: dict[str, dict] = {}
    out_ranks: dict[str, str] = {}
    for p in select.expressions:
        star_of = _star_of(p, exp)
        if star_of is not None:
            if aggregated:
                continue
            for alias, cols in known.items():
                if star_of and alias != star_of:
                    continue
                for c, reading in cols.items():
                    if not _one_moment_rows(select, alias, reading, ranks, exp):
                        readings[c] = reading
            for alias, rk in ranks.items():
                if not star_of or alias == star_of:
                    out_ranks.update(rk)
            continue
        name, expr = p.alias_or_name.lower(), p.unalias()
        rank = _rank_moment(expr, exp)
        if rank:
            out_ranks[name] = _moment_out(select, rank, exp) or rank
            continue
        if any(_resolve(c, known) for w in expr.find_all(exp.Window) for c in w.find_all(exp.Column)):
            continue            # computed across readings (a change since the last one, a running total): not followed
        for column in expr.find_all(exp.Column):
            hit = _resolve(column, known)
            if hit is None:
                continue
            alias, reading = hit
            over = reading["over"].lower()
            total = column.find_ancestor(exp.AggFunc)
            if total is not None and (not isinstance(total, exp.Sum) or per_moment(total, over, exp)):
                continue                        # an average, a min, a count — or a sum per moment — is not a reading
            if _one_moment_rows(select, alias, reading, ranks, exp):
                continue                        # one moment: a quantity like any other
            if aggregated and not (reading.get("visible") and _grouped_by(select, over, exp)):
                continue                        # summed across moments here, and flagged here
            moment = _moment_out(select, over, exp) if reading.get("visible") else None
            readings[name] = {"over": moment or reading["over"], "note": reading.get("note", ""),
                              "visible": moment is not None, "origin": reading.get("origin", ""),
                              "moment": reading.get("moment") or reading["over"],
                              "rows_per_moment": aggregated and _group_keys(select, exp) == {over}}
            break
    return readings, out_ranks


def _one_moment_rows(select, alias: str, reading: dict, ranks: dict, exp) -> bool:
    """This query's rows hold one moment of the reading (per partition): pinned, or ranked to the first."""
    over = reading["over"].lower()
    return ((reading.get("visible") and _pinned(select, over, exp)) or _ranked_one(select, over, ranks, exp)
            or _qualified_one(select, over, exp))


def _star_of(p, exp) -> Optional[str]:
    """"" for `*`, the qualifier for `t.*`, None for anything else."""
    if isinstance(p, exp.Star):
        return ""
    if isinstance(p, exp.Column) and isinstance(p.this, exp.Star):
        return (p.table or "").lower()
    return None


def _rank_moment(expr, exp) -> str:
    """The moment a ROW_NUMBER / RANK / DENSE_RANK window is ordered by first, or ""."""
    if not isinstance(expr, exp.Window) or not isinstance(expr.this, (exp.RowNumber, exp.Rank, exp.DenseRank)):
        return ""
    order = expr.args.get("order")
    first = order.expressions[0].this if order is not None and order.expressions else None
    return first.name.lower() if isinstance(first, exp.Column) else ""


def _moment_out(select, over: str, exp) -> Optional[str]:
    """The name this query gives the moment column — as it is, under an alias, or through `*` — or None."""
    for p in select.expressions:
        star_of = _star_of(p, exp)
        if star_of is not None:
            return over
        inner = p.unalias()
        if isinstance(inner, exp.Column) and inner.name.lower() == over:
            return p.alias_or_name.lower()
    return None


def _ranked_one(select, over: str, ranks: dict, exp) -> bool:
    """WHERE keeps a rank ordered by the moment at 1 (`rn = 1`, `rn <= 1`): one reading per partition."""
    where = select.args.get("where")
    if where is None or not ranks:
        return False
    for node in where.find_all(exp.EQ, exp.LTE):
        if node.find_ancestor(exp.Select) is not select or node.find_ancestor(exp.Or, exp.Not) is not None:
            continue
        column, one = node.this, node.expression
        if isinstance(one, exp.Column):
            column, one = one, column
        if not (isinstance(column, exp.Column) and isinstance(one, exp.Literal) and one.name == "1"):
            continue
        name = column.name.lower()
        pools = [ranks.get(column.table.lower(), {})] if column.table else list(ranks.values())
        if any(pool.get(name) == over for pool in pools):
            return True
    return False


def _qualified_one(select, over: str, exp) -> bool:
    """QUALIFY keeps a rank ordered by the moment at 1: one reading per partition."""
    qualify = select.args.get("qualify")
    if qualify is None:
        return False
    for node in qualify.find_all(exp.EQ, exp.LTE):
        if node.find_ancestor(exp.Or, exp.Not) is not None:
            continue
        for window, one in ((node.this, node.expression), (node.expression, node.this)):
            if isinstance(one, exp.Literal) and one.name == "1" and _rank_moment(window, exp) == over:
                return True
    return False


# ── one SELECT ──────────────────────────────────────────────────────────────────────────────

def _group_keys(select, exp) -> set[str]:
    """The GROUP BY, each key as unqualified SQL — positions and aliases resolved to what they name."""
    group = select.args.get("group")
    if group is None:
        return set()
    projections = [p.unalias() for p in select.expressions]
    if group.args.get("all"):
        keys = [p for p in projections if p.find(exp.AggFunc) is None]
    else:
        aliases = {p.alias.lower(): p.unalias() for p in select.expressions if isinstance(p, exp.Alias)}
        keys = []
        for e in group.expressions:
            if isinstance(e, exp.Literal) and e.is_int:
                i = int(e.this) - 1
                e = projections[i] if 0 <= i < len(projections) else e
            elif isinstance(e, exp.Column) and not e.table and e.name.lower() in aliases:
                e = aliases[e.name.lower()]
            keys.append(e)
    return {_bare(k, exp) for k in keys}


def _bare(node, exp) -> str:
    """SQL with every column unqualified, lower-cased — so `DATE_TRUNC('month', s.d)` and `DATE_TRUNC('month', d)`
    are one grouping."""
    return node.transform(lambda n: exp.column(n.name) if isinstance(n, exp.Column) else n).sql().lower()


def _grouped_by(select, over: str, exp) -> bool:
    """GROUP BY holds the moment column bare — by name, by the position of a column that is it (`GROUP BY 1`), by an
    alias of it, or under DuckDB's `GROUP BY ALL`."""
    return over in _group_keys(select, exp)


def _pinned(select, over: str, exp) -> bool:
    """WHERE keeps one moment: the moment column `=` one value, `IN` a single one, or `IN` the last (or first) moment
    of each group this SELECT groups by — as a conjunct, never under an OR or a NOT, which keep more than one."""
    where = select.args.get("where")
    if where is None:
        return False
    for node in where.find_all(exp.EQ, exp.In):
        if node.find_ancestor(exp.Select) is not select or node.find_ancestor(exp.Or, exp.Not) is not None:
            continue
        if isinstance(node, exp.In):
            if not (isinstance(node.this, exp.Column) and node.this.name.lower() == over):
                continue
            query = node.args.get("query")
            if query is None:
                if len(node.expressions) == 1:
                    return True
                continue
            if _ends_of_groups(query, over, select, exp):
                return True
            continue
        for side, other in ((node.this, node.expression), (node.expression, node.this)):
            if isinstance(side, exp.Column) and side.name.lower() == over and _one_value(other, select, exp):
                return True
    return False


def _ends_of_groups(query, over: str, outer, exp) -> bool:
    """`IN (SELECT MAX(<moment>) FROM … GROUP BY g)` keeps ONE moment per group of the outer SELECT when the outer
    groups by every g too (a month-end per month); with no GROUP BY, one moment in all."""
    inner = query.this if isinstance(query, exp.Subquery) else query
    if not isinstance(inner, exp.Select) or len(inner.expressions) != 1:
        return False
    edge = inner.expressions[0].unalias()
    if not (isinstance(edge, (exp.Max, exp.Min)) and isinstance(edge.this, exp.Column)
            and edge.this.name.lower() == over):
        return False
    keys = _group_keys(inner, exp)
    return not keys or keys <= _group_keys(outer, exp)


def _one_value(other, select, exp) -> bool:
    """A side that is one value for the whole statement: a literal, a scalar subquery (`SELECT MAX(d) …`), a
    function of neither (CURRENT_DATE) — never a column of the statement itself, which varies row by row."""
    if isinstance(other, exp.Column):
        return False
    return all(c.find_ancestor(exp.Select) is not select for c in other.find_all(exp.Column))


def per_moment(total, over: str, exp, *, rows: bool = False) -> bool:
    """`SUM(x) / COUNT(DISTINCT <moment>)` — the sum as the numerator of a division by the count of distinct moments,
    through parentheses, casts, a scaling product or a ROUND: an average per moment, a total within one on average.
    With ``rows`` (each row read is one moment), `COUNT(*)` counts the moments too."""
    node = total
    while node.parent is not None:
        parent = node.parent
        if isinstance(parent, exp.Div):
            return parent.this is node and _counts_moments(parent.expression, over, exp, rows)
        if not isinstance(parent, (exp.Paren, exp.Cast, exp.Mul, exp.Round)):
            return False
        node = parent
    return False


def _counts_moments(node, over: str, exp, rows: bool = False) -> bool:
    while isinstance(node, (exp.Paren, exp.Cast, exp.Nullif)):
        node = node.this
    if not isinstance(node, exp.Count):
        return False
    if rows and (isinstance(node.this, exp.Star) or (isinstance(node.this, exp.Literal) and not node.this.is_string)):
        return True
    if not isinstance(node.this, exp.Distinct):
        return False
    inner = node.this.expressions
    return len(inner) == 1 and isinstance(inner[0], exp.Column) and inner[0].name.lower() == over


# ── the flat reading, for a statement whose scopes cannot be built ──────────────────────────

def _flat_misuse(tree, declared: dict, exp) -> Optional[tuple[str, str]]:
    for select in tree.find_all(exp.Select):
        known: dict[str, dict] = {}
        for source in [select.args.get("from_") or select.args.get("from"), *(select.args.get("joins") or [])]:
            node = getattr(source, "this", None)
            if isinstance(node, exp.Table) and node.name.lower() in declared:
                table = node.name.lower()
                known[(node.alias_or_name or table).lower()] = {
                    c: {"over": str(s.get("over") or ""), "note": str(s.get("note") or ""), "visible": True,
                        "table": True, "origin": f"{table}.{c}"} for c, s in declared[table].items()}
        if known:
            hit = _misuse_in(select, known, {}, exp)
            if hit is not None:
                return hit
    return None
