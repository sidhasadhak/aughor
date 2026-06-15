"""Composite join-key completeness guard.

A normalized schema often joins two tables on a COMPOSITE key (match_id, over_id,
ball_id, innings_no). When the generated SQL joins on only a SUBSET of that key,
the join FANS OUT — rows multiply and aggregates (SUM/COUNT) silently inflate.
This is the single most common "runs but wrong" failure on enterprise schemas,
and a stronger model does not fix it (it guesses the same partial key); existing
fan-out detection targets the chasm/multi-fact pattern, not this one.

This guard is DETERMINISTIC: it parses the joins, finds the key-like columns the
two tables SHARE, and — when the join uses only a strict subset AND a uniqueness
probe confirms the subset is not unique (i.e. it really fans out) — adds the
missing key column(s). Observation becomes action without relying on the model.

Backend-agnostic: table columns and a uniqueness probe are injected.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

import sqlglot
from sqlglot import exp


@dataclass
class KeyFinding:
    left_table: str
    right_table: str
    used: set[str]
    missing: set[str]


def _keyish(col: str) -> bool:
    c = col.lower()
    return c.endswith("_id") or c.endswith("_no") or c.endswith("_key") or c in ("id", "key")


def _alias_to_table(tree: exp.Expression) -> dict[str, str]:
    """Map every table alias (and bare name) to its real table name."""
    m: dict[str, str] = {}
    for t in tree.find_all(exp.Table):
        real = t.name
        m[real.lower()] = real
        if t.alias:
            m[t.alias.lower()] = real
    return m


def detect_partial_keys(sql: str, table_cols: dict[str, set], dialect: str = "sqlite") -> list[KeyFinding]:
    """Find joins that use only a subset of the key-like columns the two tables share."""
    try:
        tree = sqlglot.parse_one(sql, read=dialect)
    except Exception:
        return []
    if tree is None:
        return []

    cols_lc = {t.lower(): {c.lower() for c in cs} for t, cs in table_cols.items()}
    real_name = {t.lower(): t for t in table_cols}
    a2t = _alias_to_table(tree)
    findings: list[KeyFinding] = []

    for j in tree.find_all(exp.Join):
        right = j.this
        if not isinstance(right, exp.Table):
            continue
        rt = right.name.lower()
        # columns used in the join condition + the aliases they reference
        used_cols: set[str] = set()
        ref_aliases: set[str] = set()
        using = j.args.get("using")
        on = j.args.get("on")
        if using:
            used_cols = {u.name.lower() for u in using}
        elif on:
            for col in on.find_all(exp.Column):
                used_cols.add(col.name.lower())
                if col.table:
                    ref_aliases.add(col.table.lower())
        if not used_cols:
            continue

        # The "left" table = the other alias referenced in ON (or any prior table
        # that shares these columns). Try ON-referenced aliases first.
        candidates = {a2t.get(a, "").lower() for a in ref_aliases} - {rt, ""}
        if not candidates:
            candidates = {t for t in cols_lc if t != rt}

        for lt in candidates:
            if lt not in cols_lc or rt not in cols_lc:
                continue
            shared_keyish = {c for c in (cols_lc[lt] & cols_lc[rt]) if _keyish(c)}
            if not shared_keyish:
                continue
            missing = shared_keyish - used_cols
            # only flag when the join actually uses a subset of the shared key
            if missing and used_cols & shared_keyish:
                findings.append(KeyFinding(
                    left_table=real_name.get(lt, lt), right_table=real_name.get(rt, rt),
                    used=used_cols & shared_keyish, missing=missing))
                break
    return findings


def confirm_fanout(finding: KeyFinding, probe_fn: Callable[[str], tuple]) -> bool:
    """Probe: is the used subset NON-unique on the right table? (i.e. real fan-out)
    probe_fn(sql) -> (ok, rows, error). Returns True if it fans out (or unknown)."""
    keys = sorted(finding.used)
    if not keys:
        return True
    expr = "||'-'||".join(keys)
    sql = f"SELECT COUNT(*), COUNT(DISTINCT {expr}) FROM {finding.right_table}"
    try:
        ok, rows, _ = probe_fn(sql)
        if ok and rows:
            total, distinct = rows[0][0], rows[0][1]
            return total != distinct        # fans out iff subset not unique
    except Exception:
        pass
    return True   # can't tell → assume risk, let the fix apply


def repair_partial_key(sql: str, finding: KeyFinding, dialect: str = "sqlite") -> Optional[str]:
    """Add the missing key column(s) to the offending join. Handles USING(...) and
    qualified ON a.x=b.x ... by appending equalities. Returns new SQL or None."""
    try:
        tree = sqlglot.parse_one(sql, read=dialect)
    except Exception:
        return None
    a2t = _alias_to_table(tree)

    for j in tree.find_all(exp.Join):
        right = j.this
        if not isinstance(right, exp.Table) or right.name.lower() != finding.right_table.lower():
            continue
        using = j.args.get("using")
        on = j.args.get("on")
        if using:
            have = {u.name.lower() for u in using}
            for mc in sorted(finding.missing):
                if mc.lower() not in have:
                    using.append(exp.column(mc))
            return tree.sql(dialect=dialect)
        if on:
            # find the two aliases used in the ON to qualify the new equality
            aliases = sorted({c.table for c in on.find_all(exp.Column) if c.table})
            la = next((a for a in aliases if a2t.get(a.lower(), "").lower() == finding.left_table.lower()), None)
            ra = next((a for a in aliases if a2t.get(a.lower(), "").lower() == finding.right_table.lower()), None)
            if la and ra:
                cond = on
                for mc in sorted(finding.missing):
                    eq = exp.EQ(this=exp.column(mc, table=la), expression=exp.column(mc, table=ra))
                    cond = exp.And(this=cond, expression=eq)
                j.set("on", cond)
                return tree.sql(dialect=dialect)
    return None
