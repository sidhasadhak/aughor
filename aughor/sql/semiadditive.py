"""PENDING item 27 — a written SUM of a reading at a moment that spans more than one of its moments.

A stock level or a balance is additive within one moment and not across moments: summing three daily readings of
the same stock counts it three times, and nothing about the number looks wrong. The ontology lets a person declare
such a property (``aughor.ontology.semiadditive``); this is the platform half — the pure reading of a statement the
trust checks (`run_trust_checks`) run on every answer path, given the declarations as plain data through the
readings registry (``aughor.kernel.registries.readings``), never by importing the agent.

Deterministic and high-precision, like `measure_grain_misuse`: flagged only when a SELECT reads the declaring table
itself and a SUM in it names the declared column, and neither its GROUP BY holds the moment column (bare, by
position, by alias or under GROUP BY ALL), nor its WHERE pins the moment to one value (`= '2026-03-01'`,
`= (SELECT MAX(...))`, `IN` one value — a conjunct, never under OR or NOT), nor the sum is divided by
`COUNT(DISTINCT <moment>)` (an average per moment). A window SUM, or a SUM over a derived table, is not read — silent
rather than a guess. Never raises.
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
        return _first_misuse(tree, declared, exp)
    except Exception:  # noqa: BLE001 — never raises: a shape this reader did not foresee is not flagged
        return None


def _first_misuse(tree, declared: dict, exp) -> Optional[tuple[str, str]]:
    for select in tree.find_all(exp.Select):
        mine = {alias: table for alias, table in _tables_of(select, exp).items() if table in declared}
        if not mine:
            continue
        for total in select.find_all(exp.Sum):
            if total.find_ancestor(exp.Select) is not select or total.find_ancestor(exp.Window) is not None:
                continue
            for column in total.find_all(exp.Column):
                table = _table_of(column, mine, declared)
                if table is None:
                    continue
                spec = declared[table][column.name.lower()]
                over = str(spec.get("over") or "").lower()
                if not over or (_grouped_by(select, over, exp) or _pinned(select, over, exp)
                                or per_moment(total, over, exp)):
                    continue
                shown = spec.get("over") or over
                note = f" ({spec['note']})" if spec.get("note") else ""
                return (f"{table}.{column.name}",
                        f"SUM({column.name}) adds {table}.{column.name}, a reading at a moment taken over {shown}"
                        f"{note}, across {shown} — it counts the same quantity once per reading. Group by {shown}, "
                        f"filter to one {shown}, divide by COUNT(DISTINCT {shown}), or use AVG, MIN or MAX.")
    return None


def _tables_of(select, exp) -> dict[str, str]:
    """``{alias or name: table}`` (lower) for the tables this SELECT reads directly — never a derived table's."""
    out: dict[str, str] = {}
    for source in [select.args.get("from_") or select.args.get("from"), *(select.args.get("joins") or [])]:
        node = getattr(source, "this", None)
        if isinstance(node, exp.Table):
            name = node.name.lower()
            out[(node.alias_or_name or name).lower()] = name
    return out


def _table_of(column, mine: dict[str, str], declared: dict) -> Optional[str]:
    """The declaring table a SUM's column is read from — by its qualifier, or, bare, the one table in reach that
    declares that name (a bare name two of them declare is not guessed)."""
    name = column.name.lower()
    if column.table:
        table = mine.get(column.table.lower())
        return table if table is not None and name in declared[table] else None
    aliases = [alias for alias, table in mine.items() if name in declared[table]]
    return mine[aliases[0]] if len(aliases) == 1 else None


def _grouped_by(select, over: str, exp) -> bool:
    """GROUP BY holds the moment column bare — by name, by the position of a column that is it (`GROUP BY 1`), by an
    alias of it, or under DuckDB's `GROUP BY ALL`."""
    group = select.args.get("group")
    if group is None:
        return False
    projections = [p.unalias() for p in select.expressions]
    if group.args.get("all"):
        return any(isinstance(p, exp.Column) and p.name.lower() == over for p in projections)
    aliases = {p.alias.lower(): p.unalias() for p in select.expressions if isinstance(p, exp.Alias)}
    for e in group.expressions:
        if isinstance(e, exp.Literal) and e.is_int:
            i = int(e.this) - 1
            e = projections[i] if 0 <= i < len(projections) else e
        elif isinstance(e, exp.Column) and not e.table and e.name.lower() in aliases:
            e = aliases[e.name.lower()]
        if isinstance(e, exp.Column) and e.name.lower() == over:
            return True
    return False


def _pinned(select, over: str, exp) -> bool:
    """WHERE keeps one moment: the moment column `=` one value, or `IN` a single one — as a conjunct, never under an
    OR or a NOT, which keep more than one."""
    where = select.args.get("where")
    if where is None:
        return False
    for node in where.find_all(exp.EQ, exp.In):
        if node.find_ancestor(exp.Select) is not select or node.find_ancestor(exp.Or, exp.Not) is not None:
            continue
        if isinstance(node, exp.In):
            if (isinstance(node.this, exp.Column) and node.this.name.lower() == over
                    and len(node.expressions) == 1 and not node.args.get("query")):
                return True
            continue
        for side, other in ((node.this, node.expression), (node.expression, node.this)):
            if isinstance(side, exp.Column) and side.name.lower() == over and _one_value(other, select, exp):
                return True
    return False


def _one_value(other, select, exp) -> bool:
    """A side that is one value for the whole statement: a literal, a scalar subquery (`SELECT MAX(d) …`), a
    function of neither (CURRENT_DATE) — never a column of the statement itself, which varies row by row."""
    if isinstance(other, exp.Column):
        return False
    return all(c.find_ancestor(exp.Select) is not select for c in other.find_all(exp.Column))


def per_moment(total, over: str, exp) -> bool:
    """`SUM(x) / COUNT(DISTINCT <moment>)` — the sum as the numerator of a division by the count of distinct moments,
    through parentheses, casts, a scaling product or a ROUND: an average per moment, a total within one on average."""
    node = total
    while node.parent is not None:
        parent = node.parent
        if isinstance(parent, exp.Div):
            return parent.this is node and _counts_moments(parent.expression, over, exp)
        if not isinstance(parent, (exp.Paren, exp.Cast, exp.Mul, exp.Round)):
            return False
        node = parent
    return False


def _counts_moments(node, over: str, exp) -> bool:
    while isinstance(node, (exp.Paren, exp.Cast, exp.Nullif)):
        node = node.this
    if not isinstance(node, exp.Count) or not isinstance(node.this, exp.Distinct):
        return False
    inner = node.this.expressions
    return len(inner) == 1 and isinstance(inner[0], exp.Column) and inner[0].name.lower() == over
