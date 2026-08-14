"""SE-4 H — named query parameters, and the two renderings a parameterised query needs.

The editor's syntax is ``:name``. Two things then have to happen to it, and confusing
them is the whole risk of this feature:

**The EXECUTABLE rendering** replaces ``:name`` with the engine's own placeholder and
passes the values as real bind values. A bound value can never change the statement's
structure — verified against DuckDB, where binding ``x'; DROP TABLE t; --`` returns that
text as a STRING. This is the rendering that reaches an engine.

**The GUARD rendering** substitutes the values as SQL literals so the deterministic
guard battery can read them. It exists because the guards parse literals out of the SQL
text: measured on the live warehouse, ``WHERE country = 'Portugalx'`` produces a
value-domain warning naming the typo and suggesting ``'Portugal'``, while
``WHERE country = $country`` produces **zero warnings — the same answer a correct
literal gives.** Without this rendering, parameterising a query silently turns
"checked" into "clean", and the editor's header would report guards clean on a query no
guard could see.

    ⚠️ THE GUARD RENDERING IS NEVER EXECUTED. It is built for analysis functions only
    and there is deliberately no code path from it to `execute()`. If you ever find
    yourself passing `render_for_guards` output to a connector, that is the bug — the
    executable form is `render_for_engine` plus bind values, always.

When a value cannot be rendered as a literal safely (a type this module does not know,
or a parameter the user has not filled in), the answer is ``None`` and the caller
reports "not checked — parameterised" rather than "clean". An unverifiable query saying
so is worth more than one that claims a verification it never ran.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

__all__ = [
    "find_params", "render_for_engine", "render_for_guards", "ParamRenderError",
]


class ParamRenderError(Exception):
    """A parameter could not be rendered as a literal for guard analysis."""


#: A parameter is `:` followed by an identifier. Everything hard about this is deciding
#: WHERE that pattern counts, which `_scan` does — a regex alone would happily rewrite
#: `x::int` and `'hello :world'`.
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _scan(sql: str) -> Iterable[tuple[int, int, str]]:
    """Yield ``(start, end, name)`` for every real parameter position in ``sql``.

    Walks the text once, skipping the four places a ``:name`` is not a parameter:

    * **string literals** — ``'hello :world'`` is data, and `''` escapes a quote;
    * **quoted identifiers** — ``"a:b"`` is a column name;
    * **comments** — ``-- :foo`` and ``/* :foo */`` are prose;
    * **casts** — ``x::int`` is Postgres/DuckDB cast syntax, and a naive rewrite turns
      it into a parameter named ``int``, which is the kind of corruption that produces
      a confusing engine error rather than an obvious one.
    """
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]

        if ch == "'" or ch == '"':
            quote = ch
            i += 1
            while i < n:
                if sql[i] == quote:
                    if i + 1 < n and sql[i + 1] == quote:   # '' / "" escapes itself
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            continue

        if ch == "-" and i + 1 < n and sql[i + 1] == "-":
            j = sql.find("\n", i)
            i = n if j < 0 else j + 1
            continue

        if ch == "/" and i + 1 < n and sql[i + 1] == "*":
            j = sql.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue

        if ch == ":":
            if i + 1 < n and sql[i + 1] == ":":       # a cast, not a parameter
                i += 2
                continue
            m = _IDENT.match(sql, i + 1)
            if m:
                yield i, m.end(), m.group(0)
                i = m.end()
                continue
            i += 1
            continue

        i += 1


def find_params(sql: str) -> list[str]:
    """The parameter names in ``sql``, in first-appearance order, de-duplicated."""
    seen: dict[str, None] = {}
    for _, _, name in _scan(sql or ""):
        seen.setdefault(name, None)
    return list(seen)


#: How each engine spells a named placeholder. DuckDB rejects `:name` outright
#: (`Parser Error: syntax error at or near ":"`), which is why translation is not
#: optional — the editor's syntax is not any engine's syntax.
_PLACEHOLDER = {
    "duckdb": lambda name: f"${name}",
    "postgres": lambda name: f"%({name})s",
}


def render_for_engine(sql: str, dialect: str) -> str:
    """Rewrite ``:name`` into ``dialect``'s placeholder. Values are NOT substituted —
    they travel separately, as bind values, which is the entire security property.

    Raises ``ParamRenderError`` for a dialect with no known placeholder syntax, so an
    unsupported engine refuses the query rather than running an unparameterised one.
    """
    spell = _PLACEHOLDER.get((dialect or "").lower())
    if spell is None:
        raise ParamRenderError(f"parameters are not supported for dialect {dialect!r}")
    out, last = [], 0
    for start, end, name in _scan(sql or ""):
        out.append(sql[last:start])
        out.append(spell(name))
        last = end
    out.append(sql[last:])
    return "".join(out)


def _literal(value: Any) -> str:
    """One value as a SQL literal, for ANALYSIS ONLY (see the module docstring).

    Deliberately narrow: only the types a parameter chip can produce. Anything else
    raises, and the caller degrades to "not checked" — guessing at a rendering for an
    unknown type is how an analysis string becomes wrong in a way nobody notices.
    """
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int) or isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    raise ParamRenderError(f"cannot render {type(value).__name__} as a literal")


def render_for_guards(sql: str, params: dict[str, Any]) -> str:
    """``sql`` with every parameter replaced by its value as a literal — for the guard
    battery, and for nothing else.

    Raises ``ParamRenderError`` when a parameter is missing or unrenderable, so the
    caller reports "not checked — parameterised" instead of a verdict it cannot stand
    behind.
    """
    params = params or {}
    out, last = [], 0
    for start, end, name in _scan(sql or ""):
        if name not in params:
            raise ParamRenderError(f"no value supplied for parameter :{name}")
        out.append(sql[last:start])
        out.append(_literal(params[name]))
        last = end
    out.append(sql[last:])
    return "".join(out)
