"""Agentic schema/data exploration for NL2SQL — probe-and-ground.

The missing capability behind hard text-to-SQL: a model writing SQL from a static
schema string *guesses* the facts it can't see — whether a multi-column join key
fans out, how a column encodes its values (comma-separated? date format?), the
exact spelling of a filter literal, the grain of a table. Those guesses are where
hard queries silently go wrong (and a bigger model guesses the same way).

This module replaces guessing with observation: before writing the final query it
issues small read-only PROBE queries against the live database, reads the results,
and feeds those observations into generation. This is exactly how a competent
analyst (or a SOTA agent like ReFoRCE's column-exploration / Spider-Agent) works.

Backend-agnostic: execution and model calls are injected as callables, so the same
loop drives SQLite (benchmark) or DuckDB/Postgres (production).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class Probe:
    purpose: str
    sql: str
    ok: bool = False
    preview: str = ""


@dataclass
class ExploreResult:
    sql: str
    probes: list[Probe] = field(default_factory=list)
    observations: str = ""
    steps: list[dict] = field(default_factory=list)


_SELECT_ONLY = re.compile(r"^\s*(with|select)\b", re.IGNORECASE)
_FORBIDDEN = re.compile(r"\b(insert|update|delete|drop|alter|create|attach|pragma|replace)\b", re.IGNORECASE)


def _is_safe_select(sql: str) -> bool:
    """A probe must be a single read-only SELECT/CTE — never a mutation."""
    s = sql.strip().rstrip(";")
    if ";" in s:                      # no multi-statement
        return False
    return bool(_SELECT_ONLY.match(s)) and not _FORBIDDEN.search(s)


# Callback contracts:
#   propose_fn()            -> list[Probe]   (purpose + candidate probe SQL)
#   execute_fn(sql)         -> (ok, rows, error)
#   generate_fn(obs: str)   -> final_sql     (obs = formatted probe observations)
ProposeFn = Callable[[], list[Probe]]
ExecuteFn = Callable[[str], tuple]
GenerateFn = Callable[[str], str]


def explore_and_generate(
    *,
    propose_fn: ProposeFn,
    execute_fn: ExecuteFn,
    generate_fn: GenerateFn,
    max_probes: int = 5,
    probe_row_cap: int = 8,
) -> ExploreResult:
    """Run probes, ground the final SQL in their results.

    1. Ask the model what to VERIFY (join-key uniqueness, encodings, filter
       literals, grain) and get candidate probe queries.
    2. Execute each safe probe read-only; capture a compact result preview.
    3. Generate the final SQL with those observations injected.
    """
    probes: list[Probe] = []
    steps: list[dict] = []

    try:
        proposed = propose_fn() or []
    except Exception as e:
        proposed = []
        steps.append({"action": "probe_proposal", "error": str(e)[:120]})

    for p in proposed[:max_probes]:
        if not p.sql or not _is_safe_select(p.sql):
            p.preview = "(skipped — not a read-only SELECT)"
            probes.append(p)
            continue
        try:
            ok, rows, err = execute_fn(p.sql)
        except Exception as e:
            ok, rows, err = False, None, str(e)
        if ok:
            rows = rows or []
            body = "\n".join(" | ".join(str(v)[:40] for v in r) for r in rows[:probe_row_cap]) or "(0 rows)"
            p.ok = True
            p.preview = f"{len(rows)} row(s):\n{body}"
        else:
            p.preview = f"ERROR: {str(err)[:100]}"
        probes.append(p)

    observations = "\n\n".join(
        f"PROBE — {p.purpose}\n  SQL: {p.sql}\n  RESULT: {p.preview}" for p in probes
    )
    steps.append({"action": "exploration", "probes_run": sum(1 for p in probes if p.ok),
                  "probes_total": len(probes)})

    final_sql = (generate_fn(observations) or "").strip()
    return ExploreResult(sql=final_sql, probes=probes, observations=observations, steps=steps)
