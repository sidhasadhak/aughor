"""DE-5d (ROADMAP §3.51) — what a cut result asks for next: how many rows there are in all, and the next
page of them. Two wrappers over the person's statement, and the one fact paging depends on.

Both wrappers go through the same door the run went through (`routers/query.py`), as a person's statement
under the person's label — so the parse step, the safety check, the row policy, PII redaction, the audit
log and the metering all apply to the count and to every page, exactly as they did to the first rows.
Nothing here runs SQL.

`has_top_level_order` is the fact: a page is a window over the statement's rows, and only an ORDER BY on
the statement's outermost query makes the engine hand those rows back in the same order twice. Without
one, two pages can repeat or skip rows, and the route says so on the page rather than letting the grid
imply a stable sequence.
"""
from __future__ import annotations

from typing import Optional

import sqlglot
from sqlglot import exp


def _bare(sql: str) -> str:
    return sql.strip().rstrip(";").strip()


def count_sql(sql: str) -> str:
    """The statement that counts every row the person's statement returns."""
    return f"SELECT COUNT(*) AS n FROM ({_bare(sql)}) __q"


def page_sql(sql: str, limit: int, offset: int) -> str:
    """The statement that returns rows ``offset`` to ``offset + limit`` of the person's statement. The caller
    asks for one row more than it will show, as the run does: that row arriving is what proves there is more."""
    return f"SELECT * FROM ({_bare(sql)}) __q LIMIT {max(1, int(limit))} OFFSET {max(0, int(offset))}"


def has_top_level_order(sql: str, dialect: Optional[str] = None) -> Optional[bool]:
    """Whether the statement's OUTERMOST query orders its rows. ``None`` when the statement cannot be parsed:
    a page of an unparseable statement is said to be unordered rather than assumed ordered.

    An ORDER BY inside a subquery or a CTE does not order the outer rows and is not counted. A statement
    wrapped in parentheses is unwrapped first; a WITH clause rides on the body, so it is looked through."""
    text = _bare(sql)
    if not text:
        return None
    tree = None
    for read in ((dialect, None) if dialect else (None,)):
        try:
            tree = sqlglot.parse_one(text, read=read)
            break
        except Exception:
            tree = None
    if tree is None:
        return None
    while isinstance(tree, exp.Subquery) and tree.args.get("order") is None and tree.this is not None:
        tree = tree.this
    return tree.args.get("order") is not None
