"""Execution-grounded probe-and-repair (B6) — interrogate the real data, then repair only a
*named, concrete* defect.

The dominant "runs but wrong" failure (wrong_values: formula/grain/value errors) needs facts the
schema can't give — the actual value domain, the real grain, whether a join fans out, whether a time
series has gaps. This module fires cheap read-only PROBES derived deterministically from the query's
own structure, hands the observed evidence to a repair callable, and adopts a fix ONLY when the
repairer names a concrete defect (grain / filter / value / frame / join) — otherwise it keeps the
original verbatim.

That FP-gate is the whole point: it is what an unconstrained repair loop (faithful-EK, net -2)
lacked. Probing is grounded in real data; the repair is conservative. Whether this *net* helps a
strong model on the dominant bucket is an open question — it must be judged with the reliability
protocol (evals/reliability.py), not a single run.

Pure + backend-agnostic (callables injected): the orchestrator and probe-proposal are unit-testable
offline; the LLM repair is exercised by the harness / product at run time.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

import sqlglot
from sqlglot import exp

ExecuteFn = Callable[[str], tuple]                  # (sql) -> (ok, rows, error)
RepairFn = Callable[[str, str], tuple]             # (baseline_sql, evidence) -> (corrected_sql|None, defect_type)

_CONCRETE_DEFECTS = {"grain", "filter", "value", "frame", "join"}


@dataclass
class Probe:
    purpose: str
    sql: str


@dataclass
class ProbeRepairResult:
    sql: str
    repaired: bool
    evidence: str
    defect_type: str
    receipt: dict = field(default_factory=dict)


def _alias_to_table(tree: exp.Expression) -> dict:
    m: dict = {}
    for t in tree.find_all(exp.Table):
        m[t.name.lower()] = t.name
        if t.alias:
            m[t.alias.lower()] = t.name
    return m


def propose_probes(sql: str, dialect: str = "sqlite", max_probes: int = 5) -> list[Probe]:
    """Derive cheap read-only diagnostic probes from the query's own structure:
      * value-domain of each string equality/IN filter  (catches wrong/enum literals),
      * join-key grain (COUNT(*) vs COUNT(DISTINCT key)) (catches fan-out / wrong grain).
    Deterministic; returns at most ``max_probes`` (highest-signal first), de-duplicated."""
    try:
        tree = sqlglot.parse_one(sql, read=dialect)
    except Exception:
        return []
    if tree is None:
        return []
    a2t = _alias_to_table(tree)
    all_tables = {t.name for t in tree.find_all(exp.Table)}

    def _table_of(col: exp.Column) -> Optional[str]:
        if col.table:
            return a2t.get(col.table.lower())
        return next(iter(all_tables)) if len(all_tables) == 1 else None

    probes: list[Probe] = []
    seen: set = set()

    # value-domain of filtered columns
    for node in list(tree.find_all(exp.EQ)) + list(tree.find_all(exp.In)):
        col = None
        if isinstance(node, exp.EQ):
            for side in (node.left, node.right):
                if isinstance(side, exp.Column):
                    col = side
            has_str = any(isinstance(s, exp.Literal) and s.is_string for s in (node.left, node.right))
            if not has_str:
                continue
        elif isinstance(node, exp.In) and isinstance(node.this, exp.Column):
            col = node.this
            if not any(isinstance(e, exp.Literal) and e.is_string for e in node.expressions):
                continue
        if col is None or not col.name:
            continue
        t = _table_of(col)
        if not t or ("val", t.lower(), col.name.lower()) in seen:
            continue
        seen.add(("val", t.lower(), col.name.lower()))
        probes.append(Probe(
            purpose=f"actual values of {t}.{col.name}",
            sql=f"SELECT DISTINCT {col.name} FROM {t} WHERE {col.name} IS NOT NULL LIMIT 8"))

    # join-key grain (fan-out)
    for j in tree.find_all(exp.Join):
        right = j.this
        if not isinstance(right, exp.Table):
            continue
        rt = right.name
        on = j.args.get("on")
        using = j.args.get("using")
        keys: list[str] = []
        if using:
            keys = [u.name for u in using]
        elif on:
            ral = (right.alias or right.name).lower()
            keys = [c.name for c in on.find_all(exp.Column) if c.table and c.table.lower() == ral]
        keys = sorted(set(keys))
        if not keys or ("grain", rt.lower(), keys[0]) in seen:
            continue
        seen.add(("grain", rt.lower(), keys[0]))
        expr = "||'-'||".join(keys) if len(keys) > 1 else keys[0]
        probes.append(Probe(
            purpose=f"grain of {rt} on join key ({', '.join(keys)}): rows vs distinct keys",
            sql=f"SELECT COUNT(*), COUNT(DISTINCT {expr}) FROM {rt}"))

    return probes[:max_probes]


def gather_evidence(probes: list[Probe], execute_fn: ExecuteFn) -> str:
    """Run probes read-only and format the observations (skips any probe that errors)."""
    lines: list[str] = []
    for p in probes:
        try:
            ok, rows, _ = execute_fn(p.sql)
        except Exception as e:
            from aughor.kernel.errors import tolerate
            tolerate(e, "probe_repair: probe failed — skipped", counter="probe_repair.probe_error")
            continue
        if ok and rows:
            preview = "; ".join(str(tuple(r) if not isinstance(r, (str, int, float)) else r)
                                for r in rows[:6])
            lines.append(f"- {p.purpose}: {preview}")
    return "\n".join(lines)


def probe_and_repair(sql: str, execute_fn: ExecuteFn, repair_fn: RepairFn, *,
                     dialect: str = "sqlite", max_probes: int = 5) -> ProbeRepairResult:
    """Probe the live data, then adopt a repair ONLY when the repairer names a concrete defect AND
    the corrected SQL executes. Never raises; keeps the original on anything uncertain."""
    receipt = {"probed": 0, "repaired": False, "defect_type": "none"}
    probes = propose_probes(sql, dialect, max_probes)
    receipt["probed"] = len(probes)
    if not probes:
        return ProbeRepairResult(sql, False, "", "none", receipt)

    evidence = gather_evidence(probes, execute_fn)
    if not evidence.strip():
        return ProbeRepairResult(sql, False, "", "none", receipt)

    try:
        corrected, defect = repair_fn(sql, evidence)
    except Exception:
        corrected, defect = None, "none"
    defect = (defect or "none").strip().lower()
    receipt["defect_type"] = defect

    if defect in _CONCRETE_DEFECTS and corrected and corrected.strip() != sql.strip():
        try:
            ok, rows, _ = execute_fn(corrected.strip())
        except Exception:
            ok, rows = False, None
        if ok and rows:                       # adopt only a fix that executes and returns rows
            receipt["repaired"] = True
            return ProbeRepairResult(corrected.strip(), True, evidence, defect, receipt)
    return ProbeRepairResult(sql, False, evidence, defect, receipt)
