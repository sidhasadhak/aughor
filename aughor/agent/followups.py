"""Follow-up suggestions — what the USER would ask next (Wave 2 / Layer 2.1).

Every path already emits a ``followups`` SSE frame and the UI already renders the
chips, one click sending the question. What was missing is what goes INTO them.

Two changes, both prompt-level:

**The user's voice.** The deep prompts asked for "follow-up investigation questions",
and a model asked that way writes *about* the user ("The user could explore regional
variance"). A chip is typed into the composer verbatim when clicked, so it has to read
like something a person would type: "break this out by region".

**Artifact awareness.** This is the thing a generic chat assistant cannot do and the
deep paths were throwing away: the executed SQL, the columns that came back and the
tables touched are all in hand at the emission site, and the generator was being sent
only the question and a headline. Given the artifact, suggestions become *operations
on this result* — change the grouping, move the window, chase the biggest mover —
using the real column names instead of invented ones.

One builder serves every site so the three near-duplicate one-liners cannot drift
again. It is deliberately NOT a prompt registry: there is no task-model slot or
template store in this codebase to register with (checked 2026-08-08), and inventing
one to hold a single prompt would be the "one store per concept" mistake in reverse.

Deterministic and offline: this module builds strings. The call, its `tolerate`
wrapper and the emission stay at the call sites, where the never-blocking contract
already lives.
"""
from __future__ import annotations

from typing import Any, Optional, Sequence

#: Asked of every path. The voice instruction is first because it is the one the
#: model most often ignores when the rest of the prompt is analytical.
_SYSTEM = (
    "You write the next questions a data analyst would ask, AS THE USER.\n"
    "\n"
    "Write each one in the user's own words — what they would type into the chat box. "
    "Never write about the user ('the user could…', 'consider exploring…'); write what "
    "they would say ('break this out by region').\n"
    "\n"
    "Each suggestion must be a concrete operation on THE RESULT BELOW — change the "
    "grouping, change the time window, filter to one segment, or chase the largest "
    "mover. Use the real table and column names shown; never invent a column.\n"
    "\n"
    "Exactly 3. Max 12 words each. No numbering, no trailing punctuation, no preamble."
)

#: Where a question ended in an honest refusal there is no result to operate on, so
#: the suggestions are about finding solid ground instead.
_SYSTEM_NO_RESULT = (
    "You write the next questions a data analyst would ask, AS THE USER.\n"
    "\n"
    "The question below could NOT be answered from this data. Write what the user "
    "would type next to find solid ground — what IS available, a broader window, a "
    "simpler cut. In their own words, never about them.\n"
    "\n"
    "Exactly 3. Max 12 words each. No numbering, no trailing punctuation, no preamble."
)


def followup_system(*, answered: bool = True) -> str:
    """The system prompt for follow-up generation."""
    return _SYSTEM if answered else _SYSTEM_NO_RESULT


def followup_user(
    question: str,
    *,
    headline: str = "",
    sql: str = "",
    tables: Optional[Sequence[str]] = None,
    columns: Optional[Sequence[str]] = None,
    row_count: Optional[int] = None,
    extra: str = "",
) -> str:
    """The user block: the question plus whatever of the answer artifact is in hand.

    Every field is optional because the sites differ in what they hold — an
    exploration has sub-question findings where a quick answer has one result set —
    and a missing field is simply omitted rather than sent as an empty label. A
    labelled empty is worse than an absence: it tells the model the artifact exists
    and is blank.
    """
    parts = [f"Question: {(question or '').strip()}"]
    if headline:
        parts.append(f"Answer: {str(headline).strip()[:600]}")
    if row_count is not None:
        parts.append(f"Rows returned: {row_count}")
    if tables:
        parts.append(f"Tables used: {', '.join(str(t) for t in list(tables)[:8])}")
    if columns:
        parts.append(f"Columns available: {', '.join(str(c) for c in list(columns)[:12])}")
    if sql:
        parts.append(f"SQL that produced it:\n{str(sql).strip()[:1200]}")
    if extra:
        parts.append(str(extra).strip()[:800])
    return "\n".join(parts)


def artifact_from_history(query_history: Any) -> dict:
    """Pull ``{sql, tables, columns, row_count}`` out of a deep run's query history.

    The deep paths hold a list of executed query records at the moment they emit
    follow-ups and were sending none of it. Takes the LAST query that actually ran
    and returned columns — the one whose result the report's headline is about; the
    earlier ones are the working-out, and a suggestion grounded in an intermediate
    probe reads like a non sequitur.

    Never raises: a shape this does not recognise yields an empty dict, and the
    caller degrades to the question-and-headline prompt it sent before.
    """
    out: dict = {}
    try:
        records = list(query_history or [])
    except TypeError:
        return out

    def _get(rec, name):
        if isinstance(rec, dict):
            return rec.get(name)
        return getattr(rec, name, None)

    chosen = None
    for rec in reversed(records):
        if _get(rec, "error"):
            continue
        if _get(rec, "columns"):
            chosen = rec
            break
    if chosen is None:
        return out

    sql = _get(chosen, "sql") or ""
    cols = _get(chosen, "columns") or []
    rc = _get(chosen, "row_count")
    if sql:
        out["sql"] = str(sql)
        try:
            # The shared AST facade — correct on aliases, subqueries and
            # schema-qualified names, and it excludes CTE names (which are not
            # tables the user can ask about).
            from aughor.sql.analyze import analyze
            facts = analyze(str(sql))
            if facts.ok and facts.tables:
                out["tables"] = sorted(facts.tables)[:8]
        except Exception:
            pass   # tables are a nicety; the SQL itself already carries them
    if cols:
        try:
            out["columns"] = [str(c) for c in cols][:12]
        except TypeError:
            pass
    if isinstance(rc, int):
        out["row_count"] = rc
    return out
