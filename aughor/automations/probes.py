"""Wave A3 — cheap source version probes (change detection for automations).

A **source version** is a small fingerprint of a table's state — row count plus the max of its best
change-signal column — computed by ONE bounded aggregate (`SELECT COUNT(*), MAX(col)`), never a data
scan. The `source_change` and `entity_appears` conditions fire when the fingerprint differs from the
recorded baseline. This generalizes the *shape* of :mod:`aughor.explorer.watermark` (cheap probe,
fail-open, per-table) into a **trigger input**, without touching that module's scan behaviour.

Two semantics, both deliberate:

* **Fingerprint inequality, not ordering.** A version is compared by ``!=``, so deletes (count
  drops) and out-of-order backfills register as change — a watermark comparison (``>``) would miss
  both. `entity_appears` restricts the fingerprint to insertion-detecting signals (count + max pk),
  so a mere `updated_at` touch does not read as a new entity.
* **Baselines commit only on a FIRED tick** (:func:`commit_fired_baselines`, called by the engine).
  Advancing the baseline at probe time would silently consume a change any time the OTHER condition
  of an ``all``-logic automation was false — the change would be "seen" once, never fired on, and
  lost. Committing on fire makes the semantics *"changed since the last tick that actually
  fired"*, which is the only reading under which no change can be swallowed. The commit re-probes
  (the version at commit time, not evaluation time); rows landing in that seconds-wide window were
  already visible to the effect that just ran, so nothing is lost there either.

**Fail-open, loudly.** A table with no usable version column, an introspection failure, or a probe
error all evaluate as "changed" *with the reason recorded on the run* — the pre-registered A3 gate:
a broken probe must never make an automation silently never-fire. The cost of the failure mode is
noise (diagnosable from run history), never silence.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from aughor.automations.models import Automation, Condition

logger = logging.getLogger(__name__)

#: Strict identifier gate for the authored ``table`` config — up to ``db.schema.table``. The
#: target lands verbatim inside probe SQL, so anything outside this shape is refused (fail-open
#: with the reason), never interpolated.
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*){0,2}$")

# Change-signal column preference. Exact names first (strongest convention), then suffix families.
_TS_EXACT = ("updated_at", "modified_at", "last_modified", "created_at")
_TS_SUFFIXES = ("_at", "_ts", "_time", "_date")
_PK_EXACT = ("id",)
_PK_SUFFIX = "_id"

_PROBE_ID = "__automation_probe__"


def _is_ts_type(dt: str) -> bool:
    d = (dt or "").upper()
    return "TIMESTAMP" in d or "DATE" in d


def _is_int_type(dt: str) -> bool:
    return "INT" in (dt or "").upper()


def _columns_for(conn_id: str, db, table: str) -> dict[str, str]:
    """``{column: data_type}`` for *table*, via the cached introspection the trust checks already
    own. Keys in that map are unqualified ``table.col``, so match on the target's leaf name.
    Best-effort: ``{}`` means "introspection unavailable", not "table absent"."""
    from aughor.sql.trust_checks import connection_column_types
    types = connection_column_types(conn_id, db)
    prefix = table.split(".")[-1].lower() + "."
    return {k[len(prefix):]: v for k, v in types.items() if k.startswith(prefix)}


def _pick_ts_column(cols: dict[str, str]) -> Optional[str]:
    for name in _TS_EXACT:
        if name in cols and _is_ts_type(cols[name]):
            return name
    for name, dt in cols.items():
        if _is_ts_type(dt) and any(name.endswith(s) for s in _TS_SUFFIXES):
            return name
    return None


def _pick_pk_column(cols: dict[str, str]) -> Optional[str]:
    for name in _PK_EXACT:
        if name in cols and _is_int_type(cols[name]):
            return name
    for name, dt in cols.items():
        if _is_int_type(dt) and name.endswith(_PK_SUFFIX):
            return name
    return None


def current_version(conn_id: str, db, table: str, *,
                    insertions_only: bool = False) -> tuple[Optional[str], str]:
    """Compute the table's source-version fingerprint with one bounded aggregate.

    Returns ``(version, how)`` — ``version=None`` means "cannot version this table" and ``how``
    carries the reason (the caller fails open with it). ``insertions_only`` restricts the signal to
    count + max pk (the `entity_appears` semantics: an `updated_at` touch is not a new entity).
    """
    if not _IDENT_RE.match(table or ""):
        return None, f"'{table}' is not a plain table identifier"

    cols = _columns_for(conn_id, db, table)
    ts_col = None if insertions_only else _pick_ts_column(cols)
    pk_col = _pick_pk_column(cols)
    signal = ts_col or pk_col

    parts = ["COUNT(*)"] + ([f"MAX({signal})"] if signal else [])
    sql = f"SELECT {', '.join(parts)} FROM {table}"
    try:
        bounded = getattr(db, "execute_bounded", None)
        r = bounded(_PROBE_ID, sql, 2) if bounded else db.execute(_PROBE_ID, sql)
    except Exception as exc:
        return None, f"probe failed: {type(exc).__name__}: {exc}"
    if r is None or r.error:
        return None, f"probe failed: {getattr(r, 'error', 'no result')}"
    if not r.rows:
        return None, "probe returned no rows"

    row = r.rows[0]
    count = row[0]
    version = f"n={count}"
    how = "row count"
    if signal:
        version += f"|{signal}={row[1]}"
        how = f"row count + MAX({signal})"
    return version, how


def evaluate_source_condition(cond: Condition, automation: Automation) -> tuple[bool, str]:
    """Evaluate one `source_change` / `entity_appears` condition — compare only, NEVER commit.

    The baseline advances in :func:`commit_fired_baselines`, and only after a fired tick (see the
    module docstring for why probe-time advancement loses changes).
    """
    from aughor.db.connection import open_connection_for

    db = open_connection_for(automation.conn_id)
    try:
        current, how = current_version(
            automation.conn_id, db, cond.table,
            insertions_only=(cond.kind == "entity_appears"))
    finally:
        try:
            db.close()
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "closing the probe db handle is best-effort; the version is computed",
                     counter="automations.probes.db_close")

    label = f"{cond.kind}({cond.table})"
    if current is None:
        # The pre-registered gate: never silently never-fire. Noisy beats silent.
        return True, f"{label}: cannot compute a source version ({how}) — failing open to changed"

    from aughor.automations.store import get_probe_baseline
    baseline = get_probe_baseline(automation.id, cond.table)
    if baseline is None:
        return True, f"{label}: first observation ({current}, via {how})"
    if baseline != current:
        return True, f"{label}: {baseline} → {current}"
    return False, f"{label}: unchanged ({current})"


def commit_fired_baselines(automation: Automation) -> None:
    """Record the current version of every source-kind condition's table — called by the engine
    ONLY after a tick whose outcome was ``fired``. Best-effort per condition: a failed commit means
    the next tick may re-fire (at-least-once), which is the safe direction — a change is repeated,
    never lost."""
    source_conds = [c for c in automation.conditions
                    if c.kind in ("source_change", "entity_appears")]
    if not source_conds:
        return
    from aughor.automations.store import set_probe_baseline
    from aughor.db.connection import open_connection_for

    try:
        db = open_connection_for(automation.conn_id)
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "baseline commit is best-effort; an uncommitted baseline re-fires (never loses) the change",
                 counter="automations.probes.commit_open")
        return
    try:
        for cond in source_conds:
            try:
                current, _how = current_version(
                    automation.conn_id, db, cond.table,
                    insertions_only=(cond.kind == "entity_appears"))
                if current is not None:
                    set_probe_baseline(automation.id, cond.table, current)
            except Exception as exc:
                from aughor.kernel.errors import tolerate
                tolerate(exc, "per-condition baseline commit is best-effort (at-least-once semantics)",
                         counter="automations.probes.commit")
    finally:
        try:
            db.close()
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "closing the commit db handle is best-effort; baselines are recorded",
                     counter="automations.probes.commit_db_close")
