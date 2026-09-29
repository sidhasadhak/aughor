"""GM-3 (ROADMAP §3.49) — the path is a receipt: the doors a statement passed, recorded as it passes them.

The gate-map study's sixth finding: an answer carried guard receipts — what FIRED — but not which doors its
statement went through. Validated, safety-checked, audited or internal, row-filtered, translated, redacted,
guarded: the confidence the user asked for ("whatever the input, it went through several gates") was true and
unsaid. Each step now says so as it runs, and the statement's result carries the list as ``QueryResult.doors``.

How a step is credited to the right statement. A connection's ``execute`` and ``execute_bounded`` run the statement
through :func:`through_door`, which opens a FRESH trail for that one statement, collects the words the door's steps
say with :func:`passed`, and stamps them on the result it returns. A step outside an open trail records nothing: a
translation made to STORE a statement, or a probe the guard battery runs while judging another statement, opens its
own trail or none, and can never be written onto the wrong result. Layers above the door — the guard battery, the
quick path's inline checks — append their own words to the result they hand back (:func:`add`).

The words are a closed vocabulary, ``name`` or ``name:detail``; :func:`describe` says each in plain words for a
reader, and it is the one place those words live.
"""
from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Callable, Iterable, Optional

_TRAIL: ContextVar[Optional[list[str]]] = ContextVar("aughor_door_trail", default=None)

#: Each door word, in plain words. ``{d}`` is the detail after the colon.
WORDS: dict[str, str] = {
    "translated": "translated from {d}",
    "validated": "parsed as one read-only statement in {d}'s dialect",
    "safety-checked": "safety-checked for writes, injection and exfiltration",
    "flagged": "flagged {d} by the safety check, and run",
    "blocked": "refused by the {d} check",
    "internal": "platform plumbing: not safety-checked, audited or redacted",
    "row-policy": "narrowed by the row-level access policy",
    "pii-checked": "checked for sensitive data (PII)",
    "pii-redacted": "{d} sensitive value(s) redacted",
    "pii-blocked": "withheld: it held sensitive data this agent may not see",
    "row-budget": "cut to the row budget of {d}",
    "audited": "written to the audit log",
    "repaired": "repaired ({d})",
    "guarded": "checked by the {d} guard",
    "unchecked": "NOT checked by the {d} guard: it could not run on this statement",
}

#: The guards a statement can be checked by, as a reader knows them.
GUARDS: dict[str, str] = {
    "preflight": "pre-flight repair",
    "trust-gate": "read-only trust",
    "zero-row": "empty-result",
    "join-domain": "join value-domain",
    "filter-domain": "filter value-domain",
    "id-arithmetic": "id-arithmetic",
    "e1": "function-semantics",
    "entity-columns": "entity-column",
    "fan-out": "fan-out",
    "scope": "schema-scope",
    "breakdown-grain": "breakdown-grain",
    "ratio-of-sums": "ratio-of-sums",
    "chasm": "aggregate-over-chasm",
    "grain": "join-key grain",
}


def passed(word: str) -> None:
    """Record that the statement in flight passed one door. Nothing is open, nothing is recorded."""
    trail = _TRAIL.get()
    if trail is not None:
        trail.append(word)


def add(result: Any, words: Iterable[str], *, first: bool = False) -> Any:
    """``words`` added to ``result.doors`` — after what it already says, or before it — each once."""
    have = list(getattr(result, "doors", None) or [])
    new = [w for w in words if w]
    result.doors = list(dict.fromkeys([*new, *have] if first else [*have, *new]))
    return result


def through_door(conn: Any, sql: str, sql_dialect: Optional[str], run: Callable[[str], Any]) -> Any:
    """One statement through a connection's door, with the path it took stamped on its result.

    The dialect step comes first (`db.dialects.sql_for_engine`, GM-1); ``run`` is the connection's own execution of
    the statement that step returns. The trail is this statement's alone and is closed on the way out, whatever
    happened inside — a refused statement is stamped with the refusal, an exception leaves no half-written trail."""
    from aughor.db.dialects import sql_for_engine

    token = _TRAIL.set([])
    try:
        statement = sql_for_engine(conn, sql, sql_dialect)
        if statement != sql:
            passed(f"translated:duckdb→{getattr(conn, 'dialect', '')}")
        result = run(statement)
        if result is not None and hasattr(result, "doors"):
            add(result, _TRAIL.get() or [], first=True)
        return result
    finally:
        _TRAIL.reset(token)


def describe(doors: Iterable[str]) -> list[str]:
    """Each door word in plain words, in the order the statement passed them. An unknown word is kept as written
    rather than dropped — a receipt that quietly lost a step would say less than happened."""
    out: list[str] = []
    for word in doors or []:
        name, _, detail = str(word).partition(":")
        if name in ("guarded", "unchecked"):
            detail = GUARDS.get(detail, detail)
        text = WORDS.get(name)
        out.append(text.format(d=detail.replace("→", " to ")) if text else str(word))
    return out
