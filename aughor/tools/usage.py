"""AT-8 — what a column IS, read from what people DO with it.

The last layer, and the only one that costs nothing to maintain: it accretes from real
query history without anybody configuring anything. `GROUP BY customer_state` five hundred
times is a stronger statement that the column is a dimension than any name pattern, and
`SUM(order_total)` is a stronger statement that a column is additive than its DOUBLE type —
plenty of DOUBLEs are ratios nobody may ever sum.

The layer is deliberately weak on its own. Usage is a record of what has been asked so far,
not of what the column is: a column analysts have only ever grouped by may simply never have
been the subject of a question. So every witness here sits below CONFIDENT and needs another
layer to agree, which is the AT-4 rule doing exactly what it was built for.

Two roles are worth more than the others because they are close to contradictions:

* a column that is SUMmed and never grouped is additive — and `rate.per_unit` from the
  pair layer disagreeing with that is a real conflict a human should see;
* a column filtered as `= 0` / `= 1` is being used as an indicator, whatever it is called.

One honesty note this module cannot fix by itself: profiles are cached by schema
fingerprint, and usage moves without the schema moving. A column that becomes popular today
is witnessed at the next profile REBUILD, not the next query. That is a staleness bound, and
it is stated here rather than being discovered later as a bug.
"""
from __future__ import annotations

from typing import Iterable, Mapping

from aughor.sql.query_log_miner import (
    ROLE_AVG,
    ROLE_FILTER_BINARY,
    ROLE_GROUP_BY,
    ROLE_JOIN,
    ROLE_SUM,
)
from aughor.tools.concept import LAYER_USAGE, Witness

#: Below this many observations a role is one analyst's afternoon, not a habit. The
#: threshold is what keeps a single exploratory query from typing a column.
MIN_SUPPORT = 3

#: role → (concept, confidence). Confidences are low by construction: this layer votes,
#: it does not decide.
_ROLE_CONCEPTS: dict[str, tuple[str, float]] = {
    ROLE_GROUP_BY: ("dimension.categorical", 0.4),
    ROLE_SUM: ("measure.additive_total", 0.45),
    ROLE_AVG: ("rate.per_unit", 0.3),
    ROLE_JOIN: ("key.identifier", 0.5),
    ROLE_FILTER_BINARY: ("flag.binary", 0.4),
}


def roles_by_column(column_roles: Mapping) -> dict[str, dict[str, int]]:
    """`{("t.col", role): n}` → `{"t.col": {role: n}}`.

    The miner's counter is keyed by pair because that is what a Counter increments
    cheaply; every consumer wants it the other way round.
    """
    out: dict[str, dict[str, int]] = {}
    for key, count in (column_roles or {}).items():
        # An explicit shape test rather than an unpack in a try: a key that is not a pair
        # is a caller passing the wrong counter, and that should read as a condition here,
        # not as an exception nobody sees.
        if not isinstance(key, tuple) or len(key) != 2:
            continue
        qualified, role = key
        if not qualified or not role:
            continue
        out.setdefault(str(qualified), {})[str(role)] = int(count or 0)
    return out


def usage_witnesses(roles: Mapping[str, int]) -> list[Witness]:
    """One column's roles → the usage layer's witnesses.

    A column can honestly carry two roles — an id is both joined on and grouped by — so
    this returns every role that clears `MIN_SUPPORT` and lets `resolve_concept` weigh
    them against the other layers rather than picking a winner here.
    """
    out: list[Witness] = []
    total = sum(int(n or 0) for n in (roles or {}).values())
    for role, count in sorted((roles or {}).items(), key=lambda kv: -int(kv[1] or 0)):
        n = int(count or 0)
        if n < MIN_SUPPORT:
            continue
        mapped = _ROLE_CONCEPTS.get(str(role))
        if not mapped:
            continue
        concept, confidence = mapped
        share = n / total if total else 0.0
        out.append(Witness(
            layer=LAYER_USAGE,
            concept=concept,
            # A role that is how the column is ALWAYS used says more than one of five
            # habits. The share only ever scales down: no amount of usage makes this
            # layer certain, because usage records the questions asked, not the column.
            confidence=round(confidence * (0.6 + 0.4 * share), 4),
            evidence=f"used as {role} in {n} of {total} logged references",
        ))
    return out


def witnesses_for_table(
    table: str,
    columns: Iterable[str],
    column_roles: Mapping,
) -> dict[str, list[Witness]]:
    """`{column: [Witness]}` for one table, from the miner's counter.

    Matching is case-insensitive on both halves of `table.column`: the log holds whatever
    the analyst typed and the profiler holds whatever the catalog says, and a guard whose
    key stops matching goes silently blind rather than loudly wrong.
    """
    by_col = roles_by_column(column_roles)
    lowered = {k.lower(): v for k, v in by_col.items()}
    out: dict[str, list[Witness]] = {}
    for column in columns or ():
        roles = lowered.get(f"{table}.{column}".lower())
        if not roles:
            continue
        found = usage_witnesses(roles)
        if found:
            out[column] = found
    return out
