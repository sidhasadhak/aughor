"""Arc ED, ED-3 (ROADMAP §3.58) — table health that is measured.

The quality plane was built and never fed. The catalogue compiles each kind to a query that counts what breaks it
(`quality/rules.py`), the one results store keeps every verdict (`quality/results.py`), and three doors read it — an
answer's caveats, the MCP `get_table_health` tool, the Briefing's count of failing tables — but nothing ever ran a
check, so every table's health read "not checked".

An **expectation** (the glossary's word; the code's `Rule`) is one statement a table's data must meet — a column never
empty, a key never repeated, the newest row younger than a day. An automation step now measures a list of them,
read-only, through the connection's own door, and records each verdict in the one store (`dispatch` in the automation
engine). What it records:

* the count of rows that break it, never the rows — the store has no clearance model;
* for the two drift kinds, the reading, judged against the last one (the first is the baseline, and says so);
* nothing for an expectation that could not be measured: an unreadable query is not a table that failed, so it is said
  on the step's outcome instead of counted as unhealthy.

A step carries names and values, never SQL (DS-12's law for this plane): an expectation's table and columns must be
plain identifiers, and its ``filter`` — a SQL fragment — is refused in a step.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

_TABLE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*){0,2}$")
_COLUMN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
#: How far a drift may move before it is not met: row count by percent, distinct values by count of new ones.
DEFAULT_MAX_CHANGE_PCT = 50.0
DEFAULT_MAX_NEW_VALUES = 0


def parse(raw: Any) -> list:
    """The step's expectations as rules, validated — `quality.rules.RuleError` on the first that is malformed or that
    carries anything but names and values."""
    from aughor.quality.rules import RuleError, rule_from_dict
    if not isinstance(raw, list) or not raw:
        raise RuleError("an expectations step lists at least one expectation")
    rules = []
    for item in raw:
        if not isinstance(item, dict):
            raise RuleError("each expectation is an object with a name, a table and a kind")
        rule = rule_from_dict(item)
        if rule.filter.strip():
            raise RuleError(f"expectation {rule.name!r} carries a filter, which is SQL — a step names tables, "
                            f"columns and values only")
        names = [("table", rule.table, _TABLE), ("column", rule.column, _COLUMN),
                 ("references", str(rule.args.get("references") or ""), _TABLE),
                 ("references_column", str(rule.args.get("references_column") or ""), _COLUMN),
                 *(("column", c, _COLUMN) for c in rule.for_each_column),
                 *(("column", str(c), _COLUMN) for c in rule.args.get("columns") or [])]
        for what, value, pattern in names:
            if value and not pattern.match(value):
                raise RuleError(f"expectation {rule.name!r}: {what} {value!r} is not a plain name")
        rules.append(rule)
    seen: set[str] = set()
    for rule in rules:
        if rule.name in seen:
            raise RuleError(f"two expectations are named {rule.name!r}")
        seen.add(rule.name)
    return rules


@dataclass
class Measured:
    """One run of a step: each verdict recorded, and each expectation that could not be measured, with why."""
    run_id: str
    results: list = field(default_factory=list)
    unmeasured: list = field(default_factory=list)          # [(name, why)]

    @property
    def met(self) -> int:
        return sum(1 for r in self.results if r.passed)

    def words(self) -> str:
        tables = sorted({r.table_name for r in self.results})
        said = (f"{', '.join(tables)}: {self.met} of {len(self.results)} expectation"
                f"{'' if len(self.results) == 1 else 's'} met") if self.results else "no expectation was measured"
        broken = [f"{r.rule_name} ({r.detail})" for r in self.results if not r.passed]
        if broken:
            said += " — not met: " + "; ".join(broken)
        if self.unmeasured:
            said += (f"; {len(self.unmeasured)} could not be measured: "
                     + "; ".join(f"{n} ({w})" for n, w in self.unmeasured))
        return said


def _words(rule, violations: int) -> str:
    col, n = rule.column, violations
    rows = f"{n:,} row{'' if n == 1 else 's'}"
    whose = f"{n:,} row's" if n == 1 else f"{n:,} rows'"
    if rule.kind == "not_null":
        return f"{rows} {'has' if n == 1 else 'have'} no {col}" if n else f"every row has a {col}"
    if rule.kind == "unique":
        keys = ", ".join(rule.args.get("columns") or [col])
        return f"{n:,} value{'' if n == 1 else 's'} of {keys} repeat" if n else f"no value of {keys} repeats"
    if rule.kind == "foreign_key":
        ref = f"{rule.args.get('references')}.{rule.args.get('references_column')}"
        return f"{whose} {col} match{'es' if n == 1 else ''} no {ref}" if n else f"every {col} matches a {ref}"
    if rule.kind == "in_list":
        return f"{whose} {col} is outside the expected values" if n else f"every {col} is an expected value"
    if rule.kind == "range":
        return f"{whose} {col} is outside the range" if n else f"every {col} is in range"
    if rule.kind == "freshness":
        hours = rule.args.get("max_age_hours")
        return f"the newest {col} is older than {hours} hours" if n else f"the newest {col} is within {hours} hours"
    return f"{n:,}"


def _drift(rule, observed: float, previous: Optional[float]) -> tuple[bool, str]:
    what = "rows" if rule.kind == "row_count_drift" else f"distinct {rule.column}"
    if previous is None:
        return True, f"{observed:,.0f} {what} — the first reading, kept as the baseline"
    if rule.kind == "row_count_drift":
        limit = float(rule.args.get("max_change_pct", DEFAULT_MAX_CHANGE_PCT))
        change = (abs(observed - previous) / previous * 100.0) if previous else (0.0 if observed == 0 else 100.0)
        return change <= limit, f"{observed:,.0f} {what}, was {previous:,.0f} ({change:.0f}% change; the limit is {limit:g}%)"
    limit = int(rule.args.get("max_new", DEFAULT_MAX_NEW_VALUES))
    new = int(observed - previous)
    return new <= limit, f"{observed:,.0f} {what}, was {previous:,.0f} ({new:+d}; at most {limit} new allowed)"


def measure(db: Any, rules: list, *, connection_id: str) -> Measured:
    """Measure each expectation once, read-only, through the connection's door, and record each verdict."""
    from aughor.quality.results import Result, new_run_id, previous_observation, record
    from aughor.quality.rules import RuleError, compile_rule
    run = Measured(run_id=new_run_id())
    dialect = getattr(db, "dialect", "") or "duckdb"
    for rule in [r for item in rules for r in item.expand()]:
        try:
            sql = compile_rule(rule, dialect)
        except RuleError as exc:
            run.unmeasured.append((rule.name, str(exc)))
            continue
        result = db.execute("expectations", sql)
        if getattr(result, "error", None) or not getattr(result, "rows", None):
            run.unmeasured.append((rule.name, str(getattr(result, "error", "") or "it returned no row")[:200]))
            continue
        cell = result.rows[0][0]
        try:
            value = float(cell)
        except (TypeError, ValueError):
            run.unmeasured.append((rule.name, f"it read {str(cell)[:40]!r}, not a number"))
            continue
        if rule.kind in ("row_count_drift", "accepted_values_drift"):
            passed, detail = _drift(rule, value, previous_observation(connection_id, rule.fingerprint))
            violations = 0 if passed else 1
        else:
            violations = int(value)
            passed, detail = violations == 0, _words(rule, violations)
        run.results.append(record(Result(
            connection_id=connection_id, table_name=rule.table, column_name=rule.column, producer="check",
            rule_name=rule.name, rule_fingerprint=rule.fingerprint, run_id=run.run_id,
            criticality=rule.criticality, passed=passed, violations=violations, observed=value, detail=detail)))
    return run
