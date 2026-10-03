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
#: GM-5 — the statement in flight was declared platform plumbing by its caller (`internal=True`). Read by the safety
#: and audit steps (`db.connection._security_pre/_post`) in place of the label's spelling, which decided it before.
_INTERNAL: ContextVar[bool] = ContextVar("aughor_door_internal", default=False)
#: DE-1 (ROADMAP §3.51) — the dialect of the engine behind the door the statement in flight is passing through, or
#: None outside a door. The parse step (`db.connection._security_pre`) reads it, so a statement is parsed as one
#: read-only statement in the dialect of the engine that will run it, whichever connector's door it came through.
_DIALECT: ContextVar[Optional[str]] = ContextVar("aughor_door_dialect", default=None)

#: Each door word, in plain words. ``{d}`` is the detail after the colon.
WORDS: dict[str, str] = {
    "translated": "translated from {d}",
    "validated": "parsed as one read-only statement in {d}'s dialect",
    "safety-checked": "safety-checked for writes, injection and exfiltration",
    "flagged": "flagged {d} by the safety check, and run",
    "blocked": "refused by the {d} check",
    "internal": "platform plumbing: not safety-checked, audited or redacted",
    "engine-read-write": "run on an engine whose session is not read-only: the door's checks are the read-only boundary",
    "engine-undeclared": "run on an engine whose connector does not say whether its session is read-only: the door's "
                         "checks are the read-only boundary",
    "row-policy": "narrowed by the row-level access policy",
    "pii-checked": "checked for sensitive data (PII)",
    "pii-redacted": "{d} sensitive value(s) redacted",
    "pii-blocked": "withheld: it held sensitive data this agent may not see",
    "row-budget": "cut to the row budget of {d}",
    "audited": "written to the audit log",
    "repaired": "repaired ({d})",
    "failed": "the engine did not answer it: a {d} error",
    "retried": "run once more after a {d} error, being a platform statement (a person's or a model's is never "
               "retried)",
    "guarded": "checked by the {d} guard",
    "unchecked": "NOT checked by the {d} guard: it could not run on this statement",
    # DE-5d — what the engine said the statement cost, where the engine bills by bytes (BigQuery): the
    # measurement the study's paging falsifier asks for, on the trail of every statement that has one.
    "bytes-processed": "read {d} bytes on the engine",
    "bytes-billed": "billed by the engine for {d} bytes",
    "cache-hit": "answered from the engine's result cache: nothing billed",
}

#: The guards a statement can be checked by, as a reader knows them.
GUARDS: dict[str, str] = {
    "preflight": "pre-flight repair",
    "declared-filter": "declared metric filter",
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
    "time-order": "time-order",
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


def statement_is_internal() -> bool:
    """Whether the statement in flight was declared platform plumbing (GM-5). Outside a door, never: a statement the
    safety and audit steps see without a declaration is somebody's activity, and is checked and written down."""
    return _INTERNAL.get()


def door_dialect() -> Optional[str]:
    """The dialect of the engine whose door the statement in flight is passing through (DE-1), or None outside a
    door — where there is no engine yet, and the parse step waits for the door."""
    return _DIALECT.get()


def mark_lost(conn: Any) -> None:
    """Record that ``conn``'s engine connection was lost (DE-3d). The pool closes a marked connection instead of
    returning it to its idle bucket, and never hands one out."""
    try:
        conn._engine_lost = True
    except Exception as exc:  # noqa: BLE001
        from aughor.kernel.errors import tolerate
        tolerate(exc, "a connection object that cannot carry the lost mark is not pooled either",
                 counter="doors.mark_lost_failed")


def connection_lost(conn: Any) -> bool:
    return bool(getattr(conn, "_engine_lost", False))


def engine_posture(conn: Any) -> Optional[str]:
    """The door word for the engine's own read-only posture (DE-1), or None when the engine's session refuses writes
    itself (`engine_read_only` True). An engine with no session-level read-only — BigQuery, Snowflake, an in-memory
    DuckDB a connector fills itself — says so on every result, since there the door's checks are the whole promise;
    a connector that declares nothing says that instead of implying either."""
    read_only = getattr(conn, "engine_read_only", None)
    if read_only is True:
        return None
    return "engine-read-write" if read_only is False else "engine-undeclared"


def through_door(conn: Any, sql: str, sql_dialect: Optional[str], run: Callable[[str], Any], *,
                 internal: bool = False) -> Any:
    """One statement through a connection's door, with the path it took stamped on its result.

    The dialect step comes first (`db.dialects.sql_for_engine`, GM-1); ``run`` is the connection's own execution of
    the statement that step returns. The trail is this statement's alone and is closed on the way out, whatever
    happened inside — a refused statement is stamped with the refusal, an exception leaves no half-written trail.

    ``internal`` is the caller's declaration that the statement is the platform's own (GM-5): a probe, a profile, a
    metadata read, a sample — never SQL a model, a person or a stored definition wrote, nor one answering somebody.
    It holds for this statement alone, as the trail does."""
    from aughor.db.dialects import sql_for_engine

    token = _TRAIL.set([])
    internal_token = _INTERNAL.set(bool(internal))
    dialect_token = _DIALECT.set(str(getattr(conn, "dialect", "") or "duckdb"))
    try:
        statement = sql_for_engine(conn, sql, sql_dialect)
        if statement != sql:
            passed(f"translated:duckdb→{getattr(conn, 'dialect', '')}")
        posture = engine_posture(conn)
        if posture:
            passed(posture)
        result = run(statement)
        kind = getattr(result, "error_kind", None) if getattr(result, "error", None) else None
        if kind:
            passed(f"failed:{kind}")
        if kind == "connection":
            # DE-3d — the connection is lost: the pool must not hand it out again (`db.pool` reads the mark), and
            # only a statement the platform declared its own is run once more, on the connection the connector
            # re-opened for itself. A person's or a model's statement comes back with the typed error: a retry the
            # caller did not ask for is a run they cannot see, and the caller decides.
            mark_lost(conn)
            if internal and "retried:connection" not in (getattr(result, "doors", None) or []):
                # Once: a door nested in another (the base `execute_bounded` runs `execute`) sees the inner retry
                # on the result's path and does not run a third time.
                passed("retried:connection")
                result = run(statement)
        if result is not None and hasattr(result, "doors"):
            add(result, _TRAIL.get() or [], first=True)
        return result
    finally:
        _DIALECT.reset(dialect_token)
        _INTERNAL.reset(internal_token)
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
