"""Grain / fan-out guard — detect additive aggregates inflated by a one-to-many join.

The single most common "runs but silently wrong" failure on real warehouses: an additive aggregate
(SUM/AVG/non-distinct COUNT) is computed across a join whose other side has multiple rows per join
key, so each fact row is counted several times and the number is inflated. A stronger model does not
fix this — it writes the same plausible join. `composite_key.py` handles one special case (a join
missing part of a shared composite key); this module is the general detector.

It is DETERMINISTIC and execution-grounded: the signal is a uniqueness *count on the real data*
(`COUNT(*)` vs `COUNT(DISTINCT key)` on each joined side), not a model opinion. Because it only fires
on a probe-confirmed structural defect, it can power a trust caveat or a repair signal **without ever
overwriting a correct query** — the failure mode that made LLM-mediated repair loops net-negative on
strong models.

Backend-agnostic: callers inject a read-only `probe_fn(sql) -> (ok, rows, error)` and a `table_cols`
map. Used by the product answer path (attach a fan-out caveat / route a repair) and by the Spider2
harness (measure detection coverage).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

import sqlglot
from sqlglot import exp

ProbeFn = Callable[[str], tuple]  # probe_fn(sql) -> (ok: bool, rows: list, error: str)

_ADDITIVE = (exp.Sum, exp.Avg, exp.Count)  # COUNT handled with a DISTINCT check below


def _to_int(v) -> Optional[int]:
    """Coerce a probe cell to int (connectors may stringify counts as "10"); None if not numeric."""
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


@dataclass
class FanoutFinding:
    fanned_table: str           # the joined table that has many rows per join key (the multiplier)
    join_key: str               # the key column the join used on that table
    ratio: float                # COUNT(*) / COUNT(DISTINCT key) on that table (>1 ⇒ fans out)
    aggregates: list[str] = field(default_factory=list)  # the at-risk additive aggregate expressions

    def caveat(self) -> str:
        aggs = ", ".join(self.aggregates) or "the additive aggregate(s)"
        return (f"Possible over-count: joining '{self.fanned_table}' on '{self.join_key}' fans out "
                f"(~{self.ratio:.1f} rows per key), so {aggs} may be inflated. Aggregate the fact at "
                f"its own grain (pre-aggregate in a CTE) before joining, or use COUNT(DISTINCT …).")


def _alias_to_table(tree: exp.Expression) -> dict[str, str]:
    m: dict[str, str] = {}
    for t in tree.find_all(exp.Table):
        m[t.name.lower()] = t.name
        if t.alias:
            m[t.alias.lower()] = t.name
    return m


def _additive_aggregates(tree: exp.Expression) -> list[str]:
    """Additive aggregates whose value is distorted by row duplication. COUNT(DISTINCT …) and
    plain MIN/MAX are NOT distorted, so they are excluded (no false fan-out flag)."""
    out: list[str] = []
    for agg in tree.find_all(*_ADDITIVE):
        # COUNT(DISTINCT …) / SUM(DISTINCT …) dedup values, so row duplication does not inflate them.
        if agg.find(exp.Distinct) is not None:
            continue
        out.append(agg.sql())
    return out


def detect_fanout(sql: str, probe_fn: ProbeFn, dialect: str = "sqlite") -> list[FanoutFinding]:
    """Return fan-out findings for `sql`: additive aggregates spanning a join whose other side
    probes as non-unique on its join key. Empty when there is no additive aggregate, no join, or
    every joined side is unique on its key (i.e. no real fan-out)."""
    try:
        tree = sqlglot.parse_one(sql, read=dialect)
    except Exception:
        return []
    if tree is None:
        return []

    aggregates = _additive_aggregates(tree)
    if not aggregates:
        return []  # no additive aggregate ⇒ fan-out cannot inflate a number

    _alias_to_table(tree)
    findings: list[FanoutFinding] = []
    seen: set[tuple[str, str]] = set()

    for j in tree.find_all(exp.Join):
        right = j.this
        if not isinstance(right, exp.Table):
            continue
        rt = right.name
        # join key(s) on the right side
        keys: list[str] = []
        using = j.args.get("using")
        on = j.args.get("on")
        if using:
            keys = [u.name for u in using]
        elif on:
            ralias = (right.alias or right.name).lower()
            for col in on.find_all(exp.Column):
                if col.table and col.table.lower() == ralias:
                    keys.append(col.name)
            if not keys:  # unqualified ON — fall back to all referenced columns
                keys = [c.name for c in on.find_all(exp.Column)]
        keys = sorted(set(keys))
        if not keys:
            continue

        if (rt.lower(), keys[0]) in seen:
            continue
        seen.add((rt.lower(), keys[0]))

        # Probe uniqueness of the join key on the right (joined) table, on real data.
        expr = "||'-'||".join(keys) if len(keys) > 1 else keys[0]
        probe = f"SELECT COUNT(*), COUNT(DISTINCT {expr}) FROM {rt}"
        try:
            ok, rows, _ = probe_fn(probe)
        except Exception:
            ok, rows = False, None
        if not ok or not rows or not rows[0] or len(rows[0]) < 2:
            continue
        total, distinct = _to_int(rows[0][0]), _to_int(rows[0][1])
        if total is None or not distinct or total <= distinct:
            continue  # non-numeric or unique on key ⇒ this join does not fan out

        findings.append(FanoutFinding(
            fanned_table=rt, join_key=", ".join(keys),
            ratio=float(total) / float(distinct), aggregates=list(aggregates)))
    return findings


def fanout_caveat(findings: list[FanoutFinding]) -> str:
    """One combined trust caveat for the product to attach to a result (empty when no findings)."""
    return " ".join(f.caveat() for f in findings)
