"""The two-tier schema catalog (Wave R3) — a manifest of everything, DDL for what matters.

The SQL repair prompt sends ``state["schema_context"]`` **whole**, on every failure, on both
the investigate and explore paths. On a wide warehouse that is the largest prompt the app
builds, and almost all of it is irrelevant to the one query that broke: a missing column on
`orders` is not fixed by the DDL of forty other tables. It is also, on a small-context
binding, the block most likely to push the repair over the window — the failure mode
``context_budget`` warns about but cannot prevent.

Two tiers:

* **Tier 1 — the manifest.** One line per table, every table, always. The model needs to
  know what *exists* to decide it must join somewhere new, and a name plus a column count
  is enough for that decision.
* **Tier 2 — full DDL**, for the tables the repair actually touches: those referenced in
  the failing SQL, plus **any table the error message names**. That last set is the
  error-path autoload, and it is the one that changes outcomes rather than just cost —
  a binder error ("no such column: x on table y") is unfixable if `y`'s columns are not
  in front of the model, and schema-linking has no way to know which table an error that
  has not happened yet will name.

**Policy: safe direction only.** Below :data:`FOCUS_MIN_CHARS` the full schema is returned
untouched — byte-identical to today, no grounding or token regression on a small database.
The two-tier form engages only where the full block is large enough that sending it is the
problem. This mirrors :func:`aughor.llm.context_budget.schema_scan_char_limits`, which
already established that policy for the intake caps.
"""
from __future__ import annotations

import logging
import re
from typing import Iterable, Optional

logger = logging.getLogger(__name__)

#: Below this, send the whole schema exactly as before. A schema this small is not what
#: is straining a context window, and narrowing it could only lose ground.
FOCUS_MIN_CHARS = 12_000

_TABLE_HEADER_RE = re.compile(r"^TABLE:\s+(\S+)(.*)$")
# Identifiers a database names in an error. Deliberately generous — this set is only ever
# INTERSECTED with the tables the schema actually declares, so a false hit is dropped.
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")


def _bare(name: str) -> str:
    return (name or "").rsplit(".", 1)[-1].lower()


def table_headers(schema: str) -> list[tuple[str, str]]:
    """``[(table_name, header_line)]`` for every ``TABLE:`` block, in schema order."""
    out: list[tuple[str, str]] = []
    for line in (schema or "").splitlines():
        m = _TABLE_HEADER_RE.match(line)
        if m:
            out.append((m.group(1), line.rstrip()))
    return out


def manifest(schema: str) -> str:
    """Tier 1 — one line per table: its header (name + row count) and its column count.

    Built from the schema text we already have rather than re-queried, so it costs nothing
    and cannot disagree with the DDL it summarises.
    """
    lines = (schema or "").splitlines()
    out: list[str] = []
    current: Optional[str] = None
    n_cols = 0

    def _flush():
        if current is not None:
            out.append(f"{current}  [{n_cols} columns]" if n_cols else current)

    for line in lines:
        m = _TABLE_HEADER_RE.match(line)
        if m:
            _flush()
            current, n_cols = line.rstrip(), 0
        elif current is not None:
            if not line.strip():
                _flush()
                current, n_cols = None, 0
            elif line.startswith((" ", "\t", "-")):
                n_cols += 1
    _flush()
    return "\n".join(out)


def tables_in_sql(sql: str, known: Iterable[str]) -> set[str]:
    """Declared tables the SQL references.

    sqlglot first; on a parse failure (which is common here — this runs on SQL that just
    FAILED) falls back to scanning identifiers. The fallback over-matches by design: the
    result is intersected with the declared tables, so a stray word cannot invent one, and
    including one table too many costs a few hundred characters while missing one costs
    the repair.
    """
    declared = {t: t for t in known}
    bare_map: dict[str, str] = {}
    for t in known:
        bare_map.setdefault(_bare(t), t)

    found: set[str] = set()
    names: set[str] = set()
    try:
        import sqlglot
        from sqlglot import exp

        for node in sqlglot.parse_one(sql or "").find_all(exp.Table):
            names.add(node.name or "")
            if node.db:
                names.add(f"{node.db}.{node.name}")
    except Exception:
        names.update(_IDENT_RE.findall(sql or ""))

    for n in names:
        low = (n or "").lower()
        for cand, real in ((low, declared.get(low)), (_bare(low), bare_map.get(_bare(low)))):
            if real:
                found.add(real)
                break
        else:
            for t in declared:
                if t.lower() == low:
                    found.add(t)
    return found


def tables_named_in_error(error: str, known: Iterable[str]) -> set[str]:
    """The error-path autoload: declared tables whose name appears in the error message.

    This is the set schema-linking structurally cannot produce — it selects tables from the
    *question* before the query runs, so a table named only by a failure that has not
    happened yet is never in it. A binder error is unfixable without the named table's
    columns in front of the model.
    """
    if not error:
        return set()
    text = error.lower()
    idents = {i.lower() for i in _IDENT_RE.findall(text)}
    found = set()
    for t in known:
        if t.lower() in idents or _bare(t) in idents:
            found.add(t)
    return found


def focused_schema(schema: str, *, sql: str = "", error: str = "",
                   extra_tables: Iterable[str] = (),
                   min_chars: int = FOCUS_MIN_CHARS) -> tuple[str, dict]:
    """The two-tier schema block, and a report of what it did.

    Returns ``(text, info)``. ``info`` carries ``{"focused": bool, "tables": [...],
    "before": n, "after": n}`` so the saving is measurable rather than asserted, and so a
    caller can log which tables the error pulled in.

    Falls back to the untouched schema whenever narrowing would be a guess: below the size
    threshold, when no table headers parse (an unrecognised schema format), or when the
    focus set came out empty. "I could not tell what matters" must mean "send everything",
    never "send nothing".
    """
    text = schema or ""
    info = {"focused": False, "tables": [], "before": len(text), "after": len(text)}
    if len(text) < max(0, min_chars):
        return text, info

    known = [name for name, _ in table_headers(text)]
    if not known:
        return text, info

    focus = tables_in_sql(sql, known) | tables_named_in_error(error, known) | {
        t for t in extra_tables if t in known}
    if not focus:
        return text, info

    try:
        from aughor.tools.schema import get_schema_for_tables

        narrowed = get_schema_for_tables(text, sorted(focus))
    except Exception:
        logger.debug("schema_focus: narrowing failed; sending the full schema", exc_info=True)
        return text, info
    if not narrowed.strip():
        return text, info

    out = (
        "ALL TABLES IN THIS DATABASE (name, rows, column count) — use this to decide "
        "whether the fix needs a table not detailed below:\n"
        f"{manifest(text)}\n\n"
        "FULL SCHEMA for the tables this query and its error involve:\n"
        f"{narrowed}"
    )
    # Narrowing that saves nothing is not narrowing — it is a second copy of the manifest
    # bolted onto the same DDL. Keep the original in that case.
    if len(out) >= len(text):
        return text, info

    info.update(focused=True, tables=sorted(focus), after=len(out))
    return out, info


def enabled() -> bool:
    """Flag ``schema.two_tier_catalog``. Fail-safe → off, so a flag-store hiccup can never
    narrow a repair prompt."""
    try:
        from aughor.kernel.flags import flag_enabled
        return flag_enabled("schema.two_tier_catalog")
    except Exception:
        return False


def for_repair_from_state(state, sql: str, error: str) -> str:
    """:func:`for_repair` reading the schema off the graph state — the shape both repair
    call sites use, defined ONCE so the investigate and explore paths cannot drift."""
    try:
        schema = state["schema_context"]
    except Exception:
        schema = (state or {}).get("schema_context", "") if hasattr(state, "get") else ""
    return for_repair(schema, sql, error)


def for_repair(schema: str, sql: str, error: str) -> str:
    """The schema block for a SQL repair prompt — two-tier when the flag is on and the
    schema is large enough, otherwise exactly what was passed in.

    One call site shape for both the investigate and the explore repair paths, so the two
    cannot drift (the guard battery being ~5 re-assembled sites by path is a known
    fragmentation problem in this repo; this does not add a sixth).
    """
    if not enabled():
        return schema
    try:
        out, info = focused_schema(schema, sql=sql, error=error)
        if info["focused"]:
            from aughor.stats import bump

            bump("schema.two_tier.focused")
            bump("schema.two_tier.chars_saved", max(0, info["before"] - info["after"]))
            logger.info("[schema] repair prompt focused to %s — %d → %d chars",
                        ", ".join(info["tables"]) or "(none)", info["before"], info["after"])
        return out
    except Exception:
        logger.debug("schema_focus: falling back to the full schema", exc_info=True)
        return schema
