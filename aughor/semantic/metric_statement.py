"""A metric's SQL is a STATEMENT, and its grain is one column of one table (2026-09-26).

The user, on the metric editor's *"Aggregate expression — no SELECT keyword"*: *"not having
SELECT statement is hard because not every metric is SUM or AVG or COUNT of something.. it
can be pre-assessed SELECT statements with multiple CTEs that user may enter. But our job is
to propose those nonetheless (with select statement). Remove this condition and let every
metric have mandatorily a SELECT statement."* And on the date field: *"a combination of a
list and an open input. List should be our proposal of what date/timestamp should the metric
be grained at in a format schema.table.column_name."*

Two words, one concept each:

* A **statement** is a whole ``SELECT`` (CTEs allowed) that returns one row holding the
  metric's value. Every metric a person or the platform writes from now on is one; the doors
  refuse a bare aggregate. A row written before this (an **expression** such as
  ``SUM(sale_price)`` with its ``tables`` and ``filters``) still reads: :func:`as_statement`
  wraps it exactly as `value_query` always has, so nothing already approved changes value.
* The **grain** is the date a row counts on, written ``schema.table.column`` (or
  ``table.column``); a bare column means "on the metric's first table". It names the TABLE
  as well as the column because a statement is cut to a range by substituting that table
  with itself filtered to the window — the one rewrite that works on any statement, CTEs
  included, without the platform having to understand the statement's arithmetic.

Everything here is pure: sqlglot in, sqlglot out, no store, no model.
"""
from __future__ import annotations

import re
from typing import Any, Optional

#: How a statement begins. ``WITH`` is a statement too — the multi-CTE case the user named.
_STATEMENT_STARTS = ("select", "with")


def is_statement(sql: Optional[str]) -> bool:
    """True when ``sql`` is a whole query rather than an aggregate expression."""
    return str(sql or "").strip().lower().startswith(_STATEMENT_STARTS)


def as_statement(sql: Optional[str], tables: Optional[list] = None, filters: Optional[list] = None,
                 name: str = "value") -> str:
    """The runnable statement for a definition: a statement as written, an expression
    wrapped over the metric's first table with its declared filters — the filters ARE the
    definition (revenue that includes cancelled orders is a different metric)."""
    text = str(sql or "").strip()
    if not text:
        return ""
    if is_statement(text):
        return text
    # Leading underscores survive: the value path has always aliased its column `_v`.
    alias = "".join(c if c.isalnum() or c == "_" else "_" for c in (name or "value").lower()) or "value"
    out = f"SELECT ({text}) AS {alias}"
    tables = [t for t in (tables or []) if str(t).strip()]
    if tables:
        out += f" FROM {tables[0]}"
        clauses = [str(f).strip() for f in (filters or []) if str(f).strip()]
        if clauses:
            out += " WHERE " + " AND ".join(clauses)
    return out


def bare(name: str) -> str:
    return str(name or "").split(".")[-1].strip('`"[]').lower()


def split_grain(time_column: Optional[str]) -> tuple[Optional[str], str]:
    """``"schema.table.column"`` → ``("schema.table", "column")``; a bare column → ``(None,
    column)``. Quoting is left as written."""
    text = str(time_column or "").strip()
    if "." not in text:
        return None, text
    table, column = text.rsplit(".", 1)
    return table.strip() or None, column.strip()


def statement_tables(sql: str, dialect: str = "duckdb") -> list[str]:
    """The tables a statement reads, as written (schema kept), CTE names excluded, in order
    of first appearance. Empty when the statement does not parse."""
    try:
        import sqlglot
        from sqlglot import exp
        tree = sqlglot.parse_one(str(sql or ""), read=dialect)
    except Exception:  # noqa: BLE001 — a statement the parser refuses names no table
        return []
    if tree is None:
        return []
    ctes = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    out: list[str] = []
    for t in tree.find_all(exp.Table):
        if not t.name or t.name.lower() in ctes:
            continue
        written = ".".join(p for p in (t.args.get("catalog") and t.catalog, t.db, t.name) if p)
        if written and written.lower() not in {o.lower() for o in out}:
            out.append(written)
    return out


def scoped_statement(sql: str, grain_table: str, predicate, *, dialect: str = "duckdb",
                     rewrite=None) -> tuple[Optional[str], str, int]:
    """``sql`` with every reference to ``grain_table`` replaced by that table filtered to
    ``predicate`` (a sqlglot expression over the table's own columns), so the statement's own
    arithmetic runs unchanged over the rows of one window. ``rewrite``, when given, is applied
    to the whole tree first (a cohort's outcome bound). Returns ``(sql, "", n)`` with ``n`` the
    references substituted, or ``(None, why, 0)``; ``n == 0`` is said, never silently run as the
    whole history."""
    try:
        import sqlglot
        from sqlglot import exp
        tree = sqlglot.parse_one(str(sql or ""), read=dialect)
    except Exception:  # noqa: BLE001
        return None, "its statement does not parse", 0
    if tree is None:
        return None, "its statement is empty", 0
    if rewrite is not None:
        tree, why = rewrite(tree)
        if tree is None:
            return None, why, 0
    ctes = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    want = bare(grain_table)
    n = 0
    for t in list(tree.find_all(exp.Table)):
        if not t.name or t.name.lower() in ctes or bare(t.name) != want:
            continue
        source = t.copy()
        source.set("alias", None)                     # the alias belongs to the subquery
        inner = exp.select(exp.Star()).from_(source).where(predicate.copy())
        alias = t.alias or t.name
        t.replace(exp.Subquery(this=inner, alias=exp.TableAlias(this=exp.to_identifier(alias))))
        n += 1
    if n == 0:
        return None, f"its statement does not read {grain_table}, the table its date is on", 0
    return tree.sql(dialect=dialect), "", n


def date_candidates(sql: str, tables: Optional[list], profile_entry: dict,
                    *, dialect: str = "duckdb") -> list[dict]:
    """The dates a metric could be grained at, as proposals: every date- or time-typed column
    of every table the statement reads (or, for an expression, the definition names), written
    ``schema.table.column`` as the table is written, the profiler's main date of each table
    first. ``[]`` when the statement names no table or the connection was never profiled — the
    caller says which. Only the statement's own tables are read (the user, 2026-09-26: *"only
    when there are multiple date or timestamp columns in the table proposed in the SQL
    statement, only then the user may choose, and only such columns appear in the list"*);
    a date on some other table is not this metric's grain."""
    from aughor.semantic.metric_time import is_time, primary_date, table_columns

    seen: list[str] = []
    for t in statement_tables(sql, dialect) + [str(x).strip() for x in (tables or []) if str(x).strip()]:
        if bare(t) not in {bare(s) for s in seen}:
            seen.append(t)
    # The table another statement table's key NAMES comes first: its date is the business event the rows
    # belong to. Olist's GMV reads order lines JOIN orders, and the first table's date — the shipping
    # deadline — was proposed and saved as GMV's date (the Olist study, Gap 21, 2026-10-22).
    parents = _named_by_keys(seen, profile_entry)
    seen.sort(key=lambda t: bare(t) not in parents)
    out: list[dict] = []
    for table in seen:
        columns = table_columns(profile_entry or {}, bare(table))
        primary = primary_date(profile_entry or {}, bare(table))
        rows = [(c, d) for c, d in columns.items() if is_time(d)]
        if primary and primary not in {c for c, _ in rows}:
            rows.append((primary, columns.get(primary, "timestamp")))
        # Within a table, the date that says the record was MADE (purchased, created, placed) before the
        # profiler's main one: Olist's orders carry order_approved_at as main, and the order is dated by
        # its purchase.
        rows.sort(key=lambda cd: (not CREATION_NAME.search(cd[0]), cd[0] != primary, cd[0]))
        for column, dtype in rows:
            out.append({"grain": f"{table}.{column}", "table": table, "column": column,
                        "type": dtype, "primary": column == primary})
        # Dates kept as TEXT, after the typed ones: the profiler counts only date- and time-typed columns, and
        # LuxExperience keeps its sessions' day as ISO text (`web_sessions.session_start` = '2020-07-01', 2026-10-13).
        # Offered by NAME and said to be text; the period filter casts it, and a text that is not a date fails there,
        # said — never silently.
        for column, dtype in sorted(columns.items()):
            if is_text(dtype) and DATEY_NAME.search(column) and not _NOT_A_DATE.search(column):
                out.append({"grain": f"{table}.{column}", "table": table, "column": column,
                            "type": dtype, "primary": False, "text": True})
    return out


#: A date NAME that says the record was MADE — when an order was placed, a user signed up, a row was created.
CREATION_NAME = re.compile(r"(?:^|_)(?:created|creation|purchase|purchased|placed|ordered|signup|signed_up|"
                           r"registered|booked|opened)(?:_|$)", re.I)


def _core_names(tables: list[str]) -> dict[str, str]:
    """Each table's bare name without the prefix and suffix tokens EVERY table shares — Olist names every table
    `olist_<what>_dataset`, so `olist_orders_dataset` is `orders` and `order_id` can name it. One table, or tables
    that share nothing, keep their names."""
    names = sorted({bare(t) for t in tables if bare(t)})
    if len(names) < 2:
        return {n: n for n in names}
    parts = [n.split("_") for n in names]
    lead = 0
    while all(len(p) > lead + 1 for p in parts) and len({p[lead] for p in parts}) == 1:
        lead += 1
    tail = 0
    while all(len(p) > lead + tail + 1 for p in parts) and len({p[-1 - tail] for p in parts}) == 1:
        tail += 1
    return {n: "_".join(p[lead:len(p) - tail]) for n, p in zip(names, parts)}


def _key_target(column: str, cores: dict[str, str], exclude: set) -> Optional[str]:
    """The table a `<stem>_id` key NAMES among ``cores`` (bare name → core name), or None."""
    if not column.endswith("_id"):
        return None
    stem = column[:-3]
    names = {stem, f"{stem}s", f"{stem}es", f"{stem[:-1]}ies" if stem.endswith("y") else ""} - {""}
    return next((t for t, core in cores.items() if (t in names or core in names) and t not in exclude), None)


def _named_by_keys(tables: list[str], profile_entry: dict) -> set[str]:
    """The statement tables (bare names) another statement table's key names — the parents in the statement."""
    from aughor.semantic.metric_time import table_columns
    cores = _core_names(_profiled_tables(profile_entry) + list(tables))
    own = {bare(t) for t in tables}
    out: set[str] = set()
    for table in tables:
        for column in table_columns(profile_entry or {}, bare(table)):
            target = _key_target(column, {t: c for t, c in cores.items() if t in own}, {bare(table)})
            if target:
                out.add(target)
    return out


#: A column NAME that says it holds a date or a time — `session_start`, `signup_date`, `created_at`, `order_day`.
DATEY_NAME = re.compile(r"(?:^|_)(?:date|day|dt|time|timestamp|ts|at|on|start|started|end|ended|created|updated|"
                        r"opened|closed|period)(?:_|$)", re.I)
#: …and the names that look like one and are not.
_NOT_A_DATE = re.compile(r"zone|type|kind|count|duration|seconds|minutes|hours|days|of_week|status", re.I)


def is_text(dtype: str) -> bool:
    d = str(dtype or "").lower()
    return any(t in d for t in ("char", "text", "string"))


def _profiled_tables(profile_entry: dict) -> list[str]:
    """Every table the profile entry describes, by bare name, once each."""
    names = {bare(str(k)) for k in ((profile_entry or {}).get("tables") or {})}
    for key, prof in ((profile_entry or {}).get("columns") or {}).items():
        owner = (prof or {}).get("table") if isinstance(prof, dict) else None
        names.add(bare(str(owner or str(key).split(".", 1)[0])))
    return sorted(n for n in names if n)


def dates_one_join_away(sql: str, tables: Optional[list], profile_entry: dict,
                        *, dialect: str = "duckdb") -> list[dict]:
    """Dates on the table a statement's key points at — `order_items.order_id` → `orders.order_date` — for a statement
    whose own tables have none. NOT a grain it can take as written: a period filters the date's own table inside the
    statement (`scoped_statement`), so the statement must read that table first. Said so the person knows where the
    date is and what to change (Gross Margin %, LuxExperience, 2026-10-13: `order_items` has no date; `orders` has).
    A key is followed only to the table it names (`order_id` → `orders`), never to another table that merely carries
    it (`returns.order_id`), whose dates belong to something else."""
    from aughor.semantic.metric_time import is_time, primary_date, table_columns

    own = [t for t in statement_tables(sql, dialect) + [str(x).strip() for x in (tables or []) if str(x).strip()]]
    own_bare = {bare(t) for t in own}
    cores = _core_names(_profiled_tables(profile_entry))
    out: list[dict] = []
    for table in dict.fromkeys(own):
        prefix = table.rsplit(".", 1)[0] + "." if "." in table else ""
        for column in table_columns(profile_entry or {}, bare(table)):
            target = _key_target(column, cores, own_bare)
            if not target:
                continue
            cols = table_columns(profile_entry or {}, target)
            primary = primary_date(profile_entry or {}, target)
            dates = sorted((c for c, d in cols.items() if is_time(d)), key=lambda c: (c != primary, c))
            for date_col in dates[:3]:
                grain = f"{prefix}{target}.{date_col}"
                if grain not in {o["grain"] for o in out}:
                    out.append({"grain": grain, "table": f"{prefix}{target}", "column": date_col,
                                "via": column, "from": table, "type": cols.get(date_col, "")})
    return out


def year_only(tables: list[str], profile_entry: dict) -> str:
    """'marketing_campaigns has no date — only fiscal_year, a year number, which cannot be cut to a month', or ""."""
    from aughor.semantic.metric_time import table_columns
    for table in tables:
        cols = table_columns(profile_entry or {}, bare(table))
        years = [c for c, d in cols.items() if re.search(r"(?:^|_)year$", c) and not is_text(d)]
        if years:
            return (f"{table} has no date — only {years[0]}, a year number, which cannot be cut to a month; the "
                    "definition must read a table with a date")
    return ""


def expression_columns(sql: str, dialect: str = "duckdb") -> list[str]:
    """The bare column names an aggregate expression references, lowercase, in order of first
    appearance; ``[]`` when it references none (``COUNT(*)``) or does not parse."""
    try:
        import sqlglot
        from sqlglot import exp
        tree = sqlglot.parse_one(str(sql or ""), read=dialect)
    except Exception:  # noqa: BLE001
        return []
    if tree is None:
        return []
    out: list[str] = []
    for c in tree.find_all(exp.Column):
        name = str(c.name or "").lower()
        if name and name not in out:
            out.append(name)
    return out


def proposed_statements(sql: str, tables: Optional[list], filters: Optional[list], name: str,
                        profile_entry: dict, *, dialect: str = "duckdb") -> tuple[list[dict], str]:
    """The runnable statement(s) the platform proposes for a definition written before the
    rule — *"our job is to propose those nonetheless (with select statement)"* (the user,
    2026-09-26) — as ``[{"table", "statement", "why"}]`` and a note.

    A statement as written proposes nothing (``[]``, no note: it is one). An expression over
    a declared table is wrapped exactly as the value path runs it — ONE proposal. An
    expression naming no table is placed on every profiled table that carries every column
    it references: one carrier is one proposal; several are several, largest table first, and
    the note says so, because a column carried by two tables is two different metrics — the
    first is filled in and the person may switch; none is said."""
    from aughor.semantic.metric_time import table_columns

    text = str(sql or "").strip()
    if not text or is_statement(text):
        return [], ""
    declared = [str(t).strip() for t in (tables or []) if str(t).strip()]
    if declared:
        return [{"table": declared[0], "statement": as_statement(text, declared, filters, name),
                 "why": f"the stored expression over {declared[0]}"
                        + (" with its filters" if any(str(f).strip() for f in (filters or [])) else "")}], ""
    columns = expression_columns(text, dialect)
    if not columns:
        return [], "the expression names no column, so no table can be proposed — write the FROM yourself"
    profiled = list(((profile_entry or {}).get("tables") or {}).keys())
    if not profiled:
        return [], "this connection has no profile yet, so no table can be proposed"
    tables_profiled = (profile_entry or {}).get("tables") or {}

    def rows_of(t: str) -> int:
        raw = str((tables_profiled.get(t) or {}).get("row_count") or "0") if isinstance(tables_profiled.get(t), dict) else "0"
        return int(raw) if raw.lstrip("-").isdigit() else 0
    carriers = [t for t in profiled
                if set(columns) <= {str(c).lower() for c in table_columns(profile_entry, bare(t))}]
    # The largest table first: the finest grain is the likelier reading of an expression
    # that names none (theLook's return rate is "the share of sold LINES sent back" —
    # order_items, not orders). The field is filled with the first; the rest are offered.
    carriers.sort(key=lambda t: (-rows_of(t), t.lower()))
    listed = ", ".join(columns)
    if not carriers:
        return [], f"no profiled table carries {listed}, so no table can be proposed"
    options = [{"table": t, "statement": as_statement(text, [t], filters, name),
                "why": f"{listed} {'is a column' if len(columns) == 1 else 'are columns'} of {t}"}
               for t in carriers]
    if len(carriers) == 1:
        return options, ""
    return options, (f"{listed} {'is' if len(columns) == 1 else 'are'} carried by "
                     f"{' and '.join(carriers)} — each table is a different metric; proposed over "
                     f"{carriers[0]}, the largest — switch if that is the wrong one")


def final_select(tree: Any):
    """The SELECT whose row is the metric's value: the statement itself, or — for a query
    whose outermost node is not a SELECT — None. A ``WITH`` parses as the final SELECT
    carrying its CTEs, so the common multi-CTE case lands here."""
    from sqlglot import exp
    return tree if isinstance(tree, exp.Select) else None
