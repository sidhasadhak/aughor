"""Cross-source connection selection (Rec 2, answer-path): which connections does a question span?

The federated planner (``federated_planner.py``) takes an explicit set of connections. To reach it from a
plain natural-language question — the answer-path integration — something must first decide *which*
connections the question touches. True to the deterministic-first thesis, that decision is made WITHOUT an
LLM: each candidate connection's schema is reduced to a bag of lexical terms, the question's content terms
are matched against each, and a greedy **set-cover** picks the smallest set of connections that together
ground the question's terms. The LLM stays confined to the downstream plan.

`select_connections(question, candidates)` returns the chosen connection ids (empty when NO candidate grounds
any question term; one when the question sits in a single source; several when it spans them), the terms each
contributed, and whether it went multi-source. Empty → the caller reports nothing relevant; single-source →
route to the normal answer path; multi-source → route to the federated planner.

Known limitations of the lexical heuristic (documented, not silent): the crude singularizer only strips one
trailing 's', so irregular/double-letter plurals (``addresses`` vs ``address``) can miss a match and drop a
relevant source; a generic business noun (``name``/``value``/``code``) that is uniquely on an otherwise
irrelevant source can pull it in as an extra source (the set-cover minimality avoids this whenever the term
is already covered elsewhere); and schemas are fetched per candidate without the router layer's TTL cache, so
a large candidate pool of wide warehouse schemas pays N introspections. All are selection-quality/perf, not
correctness — none returns wrong data or crashes.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_MAX_SOURCES = 3

# Content-word tokenizer: letter-initial tokens of length ≥3. Question filler and SQL/schema boilerplate
# are dropped so the overlap reflects real entities (table/column/business names), not glue words.
_WORD = re.compile(r"[a-z][a-z0-9_]{2,}")
# Only unambiguous filler — NOT analytical words like "order"/"count"/"total"/"group" that are also
# real table/column names (dropping "order" would blind the selector to the orders entity).
_STOP = {
    "the", "and", "for", "with", "show", "list", "what", "which", "how", "many", "give", "all", "each",
    "per", "get", "find", "that", "this", "are", "was", "were", "does", "from", "into", "over", "between",
    "across", "their", "its", "you", "our", "have", "has", "had", "who", "when", "where", "why", "then",
    "them", "also", "along", "plus", "but", "not",
}
_SQL_NOISE = {
    "table", "tables", "view", "views", "column", "columns", "rows", "varchar", "integer", "int", "double",
    "boolean", "bool", "timestamp", "datetime", "date", "text", "bigint", "float", "numeric", "decimal",
    "null", "not", "primary", "key", "keys", "foreign", "schema", "source", "select", "distinct", "index",
    "unique", "default", "char", "blob", "uuid", "json", "array", "struct", "map", "hint", "hints", "note",
}


def _terms(text: str) -> set[str]:
    out: set[str] = set()
    for t in _WORD.findall(text.lower()):
        if t in _STOP or t in _SQL_NOISE:
            continue
        out.add(t)
        if len(t) > 4 and t.endswith("s"):     # crude singularization so orders↔order match
            out.add(t[:-1])
    return out


@dataclass
class ConnectionSelection:
    conn_ids: list[str]              # the chosen connections (driver first); empty when nothing is relevant
    matched: dict[str, list[str]]    # per chosen connection, the question terms it grounded
    multi_source: bool               # True when the question spans 2+ connections → route to the federated planner


def _greedy_select(matched: dict[str, set[str]], max_sources: int) -> list[str]:
    """Greedy weighted set-cover: the highest-coverage connection, then add connections that ground the
    most still-uncovered terms, up to ``max_sources``. Deterministic tie-break by (−coverage, conn_id)."""
    if not matched:
        return []
    order = sorted(matched, key=lambda c: (-len(matched[c]), c))
    best = order[0]
    if not matched[best]:
        return []                                # nothing grounds any question term → no relevant connection
    selected = [best]
    covered = set(matched[best])
    while len(selected) < max_sources:
        gains = sorted(
            ((len(matched[c] - covered), c) for c in matched if c not in selected),
            key=lambda g: (-g[0], g[1]),
        )
        if not gains or gains[0][0] == 0:
            break
        selected.append(gains[0][1])
        covered |= matched[gains[0][1]]
    return selected


def select_connections(question: str, candidate_conn_ids: list[str], *, max_sources: int = _MAX_SOURCES) -> ConnectionSelection:
    """Pick the smallest set of candidate connections whose schemas ground the question's terms."""
    from aughor.db.connection import open_connection_for

    qterms = _terms(question)
    matched: dict[str, set[str]] = {}
    for cid in candidate_conn_ids:
        try:
            schema = open_connection_for(cid).get_schema()
        except Exception as exc:  # noqa: BLE001 — a missing/broken candidate just can't be selected
            logger.warning("connection_selector: schema for %s unavailable: %s", cid, exc)
            schema = ""
        matched[cid] = qterms & _terms(schema)

    chosen = _greedy_select(matched, max_sources)
    return ConnectionSelection(
        conn_ids=chosen,
        matched={c: sorted(matched.get(c, set())) for c in chosen},
        multi_source=len(chosen) > 1,
    )
