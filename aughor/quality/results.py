"""Wave Q3 — the ONE quality-results store, and the decision about where it lives.

**J12, and the reasoning rather than the ruling.** The scoping survey found quality-shaped
results in five mutually-unaware places, and a check result looks exactly like a monitor
alert: a table, a rule, a severity, a value, a time. So a `check_results` table would have
been correct-looking, easy, and the sixth surface — the shape Wave E found five times for
evals, Wave V thirteen times for staleness, and G3b five times for audit sinks.

**Where it lives, and why not `monitor_alerts`.** The incumbent was the obvious home and it
does not fit: `monitor_alerts` is keyed by `monitor_id` and carries `metric_name`,
`threshold`, `previous_value`, `acknowledged` — a monitor's *firing*, with a monitor's
lifecycle. A check result is keyed by `(connection, table, rule fingerprint, run)` and has
no monitor. Bending one into the other would mean a nullable `monitor_id` on half the rows
and an `acknowledged` column that means nothing for checks, which is how a shared table
becomes two tables wearing one name.

So the scoping doc's own escape clause applies: *"if it cannot carry a check result
without contortion, the migration is part of Q3."* This IS that migration — one
`quality_results` table that both producers write, with monitors adapted in via
:func:`record_monitor_alert` rather than keeping their own parallel history. The rule was
never "use the incumbent table"; it was "do not end up with two".

**Results are V-freshness citizens.** A verdict computed against yesterday's data is not
authoritative today, and :meth:`Result.staleness` says so in V's vocabulary rather than
letting age pass silently — the mistake N3 found when a `fresh` badge sat over an empty
graph.

**Counts, never rows.** A check records how many violations, never which. Offending rows
are warehouse data, and a result store has no clearance model — Wave G spent a whole wave
on why that matters.
"""
from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from aughor.db.sqlite_util import resolve_db_path
from aughor.db.backend import connect_store
from aughor.db.store_pool import ensure_once
from aughor.org.context import current_org_id
from aughor.util.time import now_iso as _now

_DB_PATH = resolve_db_path(
    "AUGHOR_QUALITY_DB", Path(__file__).parent.parent.parent / "data" / "quality.db")

#: Who produced a result. The point of the shared table is that this column exists rather
#: than the producers existing in different tables.
PRODUCERS: tuple[str, ...] = ("check", "monitor", "profiler")

#: How old a verdict may be before it stops being authoritative, in hours.
STALE_AFTER_HOURS = 24


def _conn() -> sqlite3.Connection:
    c = connect_store(_DB_PATH)
    c.row_factory = sqlite3.Row
    ensure_once(c, _ensure_schema)
    return c


def _ensure_schema(c: sqlite3.Connection) -> None:
    c.execute("""
        CREATE TABLE IF NOT EXISTS quality_results (
            id             TEXT PRIMARY KEY,
            org_id         TEXT NOT NULL DEFAULT 'default',
            connection_id  TEXT NOT NULL,
            table_name     TEXT NOT NULL,
            producer       TEXT NOT NULL DEFAULT 'check',
            rule_name      TEXT NOT NULL DEFAULT '',
            rule_fingerprint TEXT NOT NULL DEFAULT '',
            ruleset_fingerprint TEXT NOT NULL DEFAULT '',
            run_id         TEXT NOT NULL DEFAULT '',
            criticality    TEXT NOT NULL DEFAULT 'warn',
            passed         INTEGER NOT NULL DEFAULT 1,
            violations     INTEGER NOT NULL DEFAULT 0,
            observed       REAL,
            detail         TEXT NOT NULL DEFAULT '',
            checked_at     TEXT NOT NULL
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS ix_quality_latest "
              "ON quality_results (org_id, connection_id, table_name, checked_at)")
    c.execute("CREATE INDEX IF NOT EXISTS ix_quality_run "
              "ON quality_results (org_id, run_id)")
    c.commit()


@dataclass
class Result:
    """One verdict about one table."""

    connection_id: str
    table_name: str
    producer: str = "check"
    rule_name: str = ""
    rule_fingerprint: str = ""
    ruleset_fingerprint: str = ""
    run_id: str = ""
    criticality: str = "warn"
    passed: bool = True
    violations: int = 0
    observed: Optional[float] = None
    detail: str = ""
    checked_at: str = ""
    id: str = ""

    def staleness(self, *, now: Optional[str] = None) -> str:
        """V's vocabulary, applied to the verdict itself.

        A verdict computed against yesterday's data is not authoritative today. Saying so
        is the difference between a health board and a health board people trust — the
        mistake N3 found when a `fresh` badge sat over an empty graph.
        """
        from datetime import datetime, timedelta, timezone

        if not self.checked_at:
            return "unknown"
        try:
            when = datetime.fromisoformat(self.checked_at.replace("Z", "+00:00"))
        except Exception:
            return "unknown"
        reference = (datetime.fromisoformat(now.replace("Z", "+00:00")) if now
                     else datetime.now(timezone.utc))
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return "stale" if reference - when > timedelta(hours=STALE_AFTER_HOURS) else "fresh"

    @property
    def blocking(self) -> bool:
        """Whether this failure should gate a publish. `warn` annotates; `error` blocks."""
        return (not self.passed) and self.criticality == "error"

    def to_dict(self) -> dict:
        return {"id": self.id, "connection_id": self.connection_id,
                "table": self.table_name, "producer": self.producer,
                "rule_name": self.rule_name, "rule_fingerprint": self.rule_fingerprint,
                "ruleset_fingerprint": self.ruleset_fingerprint, "run_id": self.run_id,
                "criticality": self.criticality, "passed": self.passed,
                "violations": self.violations, "observed": self.observed,
                "detail": self.detail, "checked_at": self.checked_at,
                "staleness": self.staleness(), "blocking": self.blocking}


def _row_to_result(row: sqlite3.Row) -> Result:
    return Result(id=row["id"], connection_id=row["connection_id"],
                  table_name=row["table_name"], producer=row["producer"],
                  rule_name=row["rule_name"], rule_fingerprint=row["rule_fingerprint"],
                  ruleset_fingerprint=row["ruleset_fingerprint"], run_id=row["run_id"],
                  criticality=row["criticality"], passed=bool(row["passed"]),
                  violations=int(row["violations"] or 0), observed=row["observed"],
                  detail=row["detail"], checked_at=row["checked_at"])


def record(result: Result, *, org_id: Optional[str] = None) -> Result:
    """Persist one result. The single write path — every producer comes through here."""
    if result.producer not in PRODUCERS:
        raise ValueError(f"unknown producer {result.producer!r} — known: {list(PRODUCERS)}")
    org = org_id or current_org_id()
    result.id = result.id or uuid.uuid4().hex[:16]
    result.checked_at = result.checked_at or _now()
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO quality_results (id, org_id, connection_id, "
            "table_name, producer, rule_name, rule_fingerprint, ruleset_fingerprint, "
            "run_id, criticality, passed, violations, observed, detail, checked_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (result.id, org, result.connection_id, result.table_name.split(".")[-1].lower(),
             result.producer, result.rule_name, result.rule_fingerprint,
             result.ruleset_fingerprint, result.run_id, result.criticality,
             1 if result.passed else 0, int(result.violations), result.observed,
             result.detail, result.checked_at))
        c.commit()
    return result


def record_monitor_alert(connection_id: str, table: str, *, monitor_name: str,
                         severity: str, message: str, value: Optional[float] = None,
                         run_id: str = "", org_id: Optional[str] = None) -> Result:
    """A monitor firing, written to the SAME store as a check result.

    This adapter is what makes J12 true rather than aspirational: without it, monitors
    keep their own history and "one results store" is a sentence in a doc. Severity maps
    onto the shared criticality vocabulary so a consumer never has to know which producer
    a row came from to read it.
    """
    return record(Result(
        connection_id=connection_id, table_name=table, producer="monitor",
        rule_name=monitor_name, run_id=run_id,
        criticality="error" if str(severity).lower() in ("critical", "error") else "warn",
        passed=False, violations=1, observed=value, detail=message), org_id=org_id)


def latest_for_tables(connection_id: str, tables: list[str], *,
                      org_id: Optional[str] = None) -> list[Result]:
    """The most recent result per (table, rule) for the given tables.

    Latest-per-rule rather than latest-overall: a table with a passing freshness check and
    a failing not-null check has both facts, and collapsing to one row would hide whichever
    ran second.
    """
    if not tables:
        return []
    org = org_id or current_org_id()
    bare = [str(t).split(".")[-1].lower() for t in tables]
    placeholders = ",".join("?" * len(bare))
    with _conn() as c:
        rows = c.execute(
            f"SELECT * FROM quality_results WHERE org_id=? AND connection_id=? "
            f"AND table_name IN ({placeholders}) ORDER BY checked_at DESC",
            (org, connection_id, *bare)).fetchall()
    seen: set[tuple] = set()
    out: list[Result] = []
    for row in rows:
        key = (row["table_name"], row["rule_name"] or row["rule_fingerprint"])
        if key in seen:
            continue
        seen.add(key)
        out.append(_row_to_result(row))
    return out


def results_for_run(run_id: str, *, org_id: Optional[str] = None) -> list[Result]:
    """Everything one run produced — the run_id spine tying artifact ↔ metrics ↔ ruleset."""
    org = org_id or current_org_id()
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM quality_results WHERE org_id=? AND run_id=? "
            "ORDER BY table_name, rule_name", (org, run_id)).fetchall()
    return [_row_to_result(r) for r in rows]


def count_failing(connection_id: str, *, org_id: Optional[str] = None) -> int:
    """How many recorded checks are currently failing on a connection.

    A counting reader rather than the digest reaching into this module's connection: a
    caller that wants a number should get a number, and the private-import ratchet is
    right that a cross-module `_conn` is a coupling nobody meant to sign up for.
    """
    org = org_id or current_org_id()
    with _conn() as c:
        row = c.execute(
            "SELECT COUNT(*) AS n FROM quality_results "
            "WHERE org_id=? AND connection_id=? AND passed=0",
            (org, connection_id)).fetchone()
    return int(row["n"] if row else 0)


def new_run_id() -> str:
    return uuid.uuid4().hex[:12]
