"""
SchemaExplorer — proactive, curiosity-driven background schema cartography.

Aughor connects to a database and immediately begins a background exploration:
one small SQL query at a time, rate-limited to avoid overloading the database,
pausing entirely whenever a user investigation is running.

The 5 exploration phases (building on profiler output for Phases 1 & 2):
  3. Null meaning resolution  — why is a column nullable? (pending vs missing)
  4. Join verification        — orphan checks + cardinality confirmation
  5. Lifecycle mapping        — state machine extraction for entity tables
  6. Distribution profiling   — shape characterisation for measure columns
  7. Cross-table patterns     — pre-computed analytical insights

Each query produces a (think, sql, observation) episode for SkyRL-SQL training.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from aughor.db.connection import DatabaseConnection

from aughor.explorer.models import (
    DistributionProfile,
    DistributionShape,
    ExplorationPhase,
    ExplorationStatus,
    JoinVerificationResult,
    LifecycleMap,
    LifecycleTransition,
    NullMeaning,
    NullMeaningResult,
    OntologyInsight,
)
from aughor.explorer import store as _store
from aughor.explorer.episodes import EpisodeCollector

logger = logging.getLogger(__name__)

_RATE_SECONDS_SCHEMA = 0.0   # schema phases (3-7) run as fast as the DB allows
_RATE_SECONDS_INTEL  = 5.0   # domain intel phase runs at 1 query per 5 seconds

# State-value vocabulary for lifecycle classification
_TERMINAL = frozenset({
    "canceled", "cancelled", "returned", "closed", "archived", "failed",
    "rejected", "expired", "deleted", "churned", "lost", "void", "voided",
    "refunded", "bounced", "blocked", "completed", "done", "delivered",
    "shipped",  # DHL "shipped" = terminal; may be overridden by specific schemas
})
_ACTIVE = frozenset({
    "active", "live", "running", "processing", "open", "pending", "approved",
    "in_progress", "inprogress", "scheduled", "confirmed", "new", "created",
    "placed", "accepted", "ready", "invoiced",
})

# Substring signals for heuristic state classification when exact match fails
_TERMINAL_SUBS = ("cancel", "fail", "reject", "expir", "close", "archiv", "delet", "return", "void", "refund", "churn")
_ACTIVE_SUBS   = ("pend", "process", "approv", "creat", "open", "activ", "run", "sched", "place", "accept", "new")


class SchemaExplorer:
    """
    Background schema exploration agent.

    Create one per connected database and schedule ``explore()`` as an
    asyncio task.  Call ``pause()`` / ``resume()`` to yield to investigations.
    """

    def __init__(self, connection_id: str, conn: "DatabaseConnection") -> None:
        self.connection_id = connection_id
        self._conn = conn
        self._status = ExplorationStatus(
            connection_id=connection_id,
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        self._episodes = EpisodeCollector(connection_id)
        self._can_run = asyncio.Event()
        self._can_run.set()
        self._stopped = False
        self._state = _store.load(connection_id)
        self._last_query_at: float = 0.0
        self._rate_seconds: float = _RATE_SECONDS_SCHEMA

    # ── External control ──────────────────────────────────────────────────────

    def pause(self) -> None:
        """Yield execution — called when a user investigation begins."""
        self._can_run.clear()
        self._status.paused = True

    def resume(self) -> None:
        """Resume exploration — called when a user investigation ends."""
        self._can_run.set()
        self._status.paused = False

    def stop(self) -> None:
        """Permanently stop (e.g. connection deleted)."""
        self._stopped = True
        self._can_run.set()  # unblock if currently paused so the task exits

    @property
    def status(self) -> ExplorationStatus:
        return self._status

    # ── Execution gate ────────────────────────────────────────────────────────

    async def _gate(self) -> None:
        """Block until unpaused, then enforce the per-phase rate limit."""
        await self._can_run.wait()
        if self._stopped:
            raise asyncio.CancelledError()
        if self._rate_seconds > 0:
            elapsed = time.monotonic() - self._last_query_at
            wait = self._rate_seconds - elapsed
            if wait > 0:
                await asyncio.sleep(wait)

    def _run(self, sql: str, think: str = "") -> Optional[list]:
        """Execute one read-only SQL query and record an episode turn."""
        self._last_query_at = time.monotonic()
        self._status.queries_executed += 1
        try:
            result = self._conn.execute("__explorer__", sql)
            if result.error:
                self._episodes.add(think=think, sql=sql, observation=f"ERROR: {result.error}")
                return None
            obs_rows = "\n".join(str(r) for r in (result.rows or [])[:6])
            obs = f"{result.row_count} rows\ncols: {result.columns}\n{obs_rows}"
            self._episodes.add(think=think, sql=sql, observation=obs)
            return result.rows or []
        except Exception as e:
            self._episodes.add(think=think, sql=sql, observation=f"EXCEPTION: {e}")
            return None

    # ── Main loop ─────────────────────────────────────────────────────────────

    async def explore(self, domain_intel_only: bool = False) -> None:
        """Full exploration run — schedule this as an asyncio.Task.

        If domain_intel_only=True (triggered by "Explore 5 more") skips phases 3-7
        and runs only Phase 8, consuming the extended budget.
        """
        logger.info(f"[explorer:{self.connection_id}] Starting (domain_intel_only={domain_intel_only})")
        try:
            tp, cp, jmap = self._load_profiler_data()
            if not tp:
                logger.info(f"[explorer:{self.connection_id}] No profiler data, aborting")
                return

            self._status.tables_total = len(tp)
            self._status.columns_total = sum(len(v) for v in cp.values())
            self._status.joins_total = len(jmap.get("joins", []))

            if not domain_intel_only:
                # Phases 3-7: schema cartography — run as fast as the DB allows
                self._rate_seconds = _RATE_SECONDS_SCHEMA

                # Phase 3 — Null meaning resolution
                self._status.phase = ExplorationPhase.NULL_MEANING
                await self._phase3_null_meaning(tp, cp)

                # Phase 4 — Join verification
                self._status.phase = ExplorationPhase.JOIN_VERIFICATION
                await self._phase4_joins(jmap)

                # Phase 5 — Lifecycle mapping
                self._status.phase = ExplorationPhase.LIFECYCLE_MAPPING
                await self._phase5_lifecycle(tp, cp)

                # Phase 6 — Distribution profiling
                self._status.phase = ExplorationPhase.DISTRIBUTION
                await self._phase6_distributions(cp)

                # Phase 7 — Cross-table pattern discovery
                self._status.phase = ExplorationPhase.CROSS_TABLE
                await self._phase7_patterns(cp, jmap)

            # Phase 8 — Domain intelligence: slow down to avoid overloading the DB
            # and to allow the user to stop between queries if needed
            self._rate_seconds = _RATE_SECONDS_INTEL
            self._status.phase = ExplorationPhase.DOMAIN_INTEL
            await self._phase8_domain_intelligence(cp)

            # Done
            self._status.phase = ExplorationPhase.COMPLETE
            self._status.completed_at = datetime.now(timezone.utc).isoformat()
            self._state["phase"] = ExplorationPhase.COMPLETE.value
            _store.save(self.connection_id, self._state)
            logger.info(
                f"[explorer:{self.connection_id}] Complete — "
                f"{self._status.queries_executed}q, "
                f"{self._status.facts_discovered} facts, "
                f"{self._status.insights_found} insights"
            )

        except asyncio.CancelledError:
            _store.save(self.connection_id, self._state)
            logger.info(f"[explorer:{self.connection_id}] Cancelled, progress saved")
            raise
        except Exception as e:
            self._status.phase = ExplorationPhase.FAILED
            self._status.error = str(e)
            _store.save(self.connection_id, self._state)
            logger.error(f"[explorer:{self.connection_id}] Error: {e}", exc_info=True)

    # ── Profiler data loader ──────────────────────────────────────────────────

    def _load_profiler_data(self):
        """
        Return (table_profiles, col_profiles_by_table, join_map).
        Reads from profile cache when available, builds from DB otherwise.
        col_profiles_by_table: {table: {col_name: ColumnProfile}}
        """
        try:
            # Discover tables (SHOW TABLES is blocked by the SELECT-only validator,
            # so use information_schema for both dialects)
            schema = getattr(self._conn, "_schema_name", None)
            if self._conn.dialect == "duckdb":
                schema_filter = f"= '{schema}'" if schema else "= current_schema()"
            else:
                schema_filter = f"= '{schema or 'public'}'"
            r = self._conn.execute(
                "__explorer__",
                f"SELECT table_name FROM information_schema.tables "
                f"WHERE table_schema {schema_filter} "
                f"AND table_type = 'BASE TABLE' ORDER BY table_name",
            )
            tables = [row[0] for row in (r.rows or [])] if not r.error else []

            if not tables:
                return {}, {}, {}

            # Build / load profiles (idempotent, cached)
            from aughor.tools.profile_cache import get_or_build_profiles
            tp, cp_flat = get_or_build_profiles(
                self._conn, self.connection_id, tables, {}
            )

            # Re-group flat {"table.col": ColumnProfile} → {table: {col: ColumnProfile}}
            cp: dict[str, dict] = {}
            for col_p in cp_flat.values():
                cp.setdefault(col_p.table, {})[col_p.column] = col_p

            # Build a minimal schema string for join inference
            lines = []
            for table in tables:
                lines.append(f"TABLE: {table}")
                for col_p in cp.get(table, {}).values():
                    lines.append(f"  {col_p.column}  {col_p.dtype}")
            schema_str = "\n".join(lines)

            from aughor.tools.schema import _parse_schema_tables, _compute_join_map
            jmap = _compute_join_map(_parse_schema_tables(schema_str))

            return tp, cp, jmap

        except Exception as e:
            logger.warning(f"[explorer:{self.connection_id}] _load_profiler_data failed: {e}")
            return {}, {}, {}

    # ── Phase 3: Null meaning resolution ─────────────────────────────────────

    async def _phase3_null_meaning(self, tp: dict, cp: dict) -> None:
        """
        For each column with a non-trivial null rate (1%–99%), determine whether
        the null is business-meaningful or a data quality problem.
        """
        for table, col_map in cp.items():
            # Find the lifecycle/status column for this table (for cross-reference)
            status_col = _find_status_col(col_map)

            for col_name, col_p in col_map.items():
                if col_p.null_rate is None:
                    continue
                if not (0.01 <= col_p.null_rate <= 0.99):
                    continue
                if col_p.semantic_type in ("key", "timestamp"):
                    continue

                key = f"{table}:{col_name}"
                if key in self._state.get("null_meanings", {}):
                    self._status.null_meanings_resolved += 1
                    continue

                await self._gate()

                if status_col and status_col != col_name:
                    result = await self._null_cross_ref(table, col_name, status_col, col_p.null_rate)
                else:
                    meaning = NullMeaning.MISSING if col_p.null_rate > 0.3 else NullMeaning.UNKNOWN
                    result = NullMeaningResult(
                        table=table, column=col_name,
                        null_rate=col_p.null_rate, meaning=meaning,
                    )

                self._state.setdefault("null_meanings", {})[key] = {
                    "meaning": result.meaning.value,
                    "business_rule": result.business_rule,
                    "evidence_sql": result.evidence_sql,
                }
                self._status.null_meanings_resolved += 1
                self._status.facts_discovered += 1
                _store.save(self.connection_id, self._state)

    async def _null_cross_ref(
        self, table: str, col: str, status_col: str, null_rate: float
    ) -> NullMeaningResult:
        sql = (
            f"SELECT {status_col} AS s, COUNT(*) AS total, "
            f"SUM(CASE WHEN {col} IS NULL THEN 1 ELSE 0 END) AS null_n, "
            f"ROUND(SUM(CASE WHEN {col} IS NULL THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS null_pct "
            f"FROM {table} GROUP BY {status_col} ORDER BY null_pct DESC LIMIT 20"
        )
        think = (
            f"'{table}.{col}' has {null_rate:.0%} nulls. "
            f"Cross-referencing with '{status_col}' to classify: "
            f"pending-event vs terminal-state vs data-quality issue."
        )
        rows = self._run(sql, think=think)
        if not rows:
            return NullMeaningResult(
                table=table, column=col, null_rate=null_rate, meaning=NullMeaning.UNKNOWN
            )

        # rows: [(status_val, total, null_n, null_pct), ...]
        try:
            high = [r for r in rows if r[3] is not None and float(r[3]) > 80]
            low  = [r for r in rows if r[3] is not None and float(r[3]) < 10]
        except (TypeError, ValueError):
            return NullMeaningResult(
                table=table, column=col, null_rate=null_rate, meaning=NullMeaning.UNKNOWN
            )

        if high and low:
            null_states = [str(r[0]) for r in high]
            business_rule = (
                f"NULL when {status_col} IN "
                f"({', '.join(repr(s) for s in null_states)})"
            )
            is_terminal = any(
                s.lower() in _TERMINAL or any(t in s.lower() for t in _TERMINAL_SUBS)
                for s in null_states
            )
            meaning = (
                NullMeaning.NOT_APPLICABLE_TERMINAL if is_terminal else NullMeaning.PENDING
            )
        elif rows and all(r[3] is not None and float(r[3] or 0) > 30 for r in rows):
            meaning, business_rule = NullMeaning.MISSING, None
        else:
            meaning, business_rule = NullMeaning.MIXED, None

        return NullMeaningResult(
            table=table, column=col, null_rate=null_rate,
            meaning=meaning, business_rule=business_rule, evidence_sql=sql,
        )

    # ── Phase 4: Join verification ────────────────────────────────────────────

    async def _phase4_joins(self, jmap: dict) -> None:
        """
        Verify each inferred FK relationship with an orphan check.
        A verified join has orphan_count == 0.
        """
        joins = jmap.get("joins", [])
        done_keys = {v.get("key") for v in self._state.get("join_verifications", [])}

        for j in joins:
            t1, c1, t2, c2 = j["t1"], j["c1"], j["t2"], j["c2"]
            key = f"{t1}.{c1}→{t2}.{c2}"
            if key in done_keys:
                self._status.joins_verified += 1
                continue

            await self._gate()

            sql = (
                f"SELECT "
                f"(SELECT COUNT(DISTINCT {c1}) FROM {t1}) AS fk_distinct, "
                f"(SELECT COUNT(DISTINCT {c2}) FROM {t2}) AS pk_distinct, "
                f"(SELECT COUNT(*) FROM {t1} "
                f" WHERE {c1} IS NOT NULL "
                f" AND {c1} NOT IN (SELECT {c2} FROM {t2} WHERE {c2} IS NOT NULL)"
                f") AS orphan_count"
            )
            think = (
                f"Verify FK {t1}.{c1} → {t2}.{c2}: "
                f"count distinct values and check for orphan rows."
            )
            rows = self._run(sql, think=think)

            if rows and rows[0]:
                try:
                    fk_d = int(rows[0][0] or 0)
                    pk_d = int(rows[0][1] or 0)
                    orphans = int(rows[0][2] or 0)
                except (TypeError, ValueError):
                    continue

                if fk_d == pk_d:
                    card = "1:1"
                elif fk_d > pk_d:
                    card = "N:1"
                else:
                    card = "1:N"

                self._state.setdefault("join_verifications", []).append({
                    "key": key,
                    "from_table": t1, "from_col": c1,
                    "to_table": t2, "to_col": c2,
                    "orphan_count": orphans,
                    "fk_distinct": fk_d, "pk_distinct": pk_d,
                    "verified": orphans == 0,
                    "cardinality": card,
                })
                self._status.joins_verified += 1
                self._status.facts_discovered += 1
                done_keys.add(key)
                _store.save(self.connection_id, self._state)

    # ── Phase 5: Lifecycle mapping ────────────────────────────────────────────

    async def _phase5_lifecycle(self, tp: dict, cp: dict) -> None:
        """
        For each table with a status/lifecycle column, extract the state
        distribution and (when possible) state-transition frequencies.
        """
        for table, col_map in cp.items():
            if table in self._state.get("lifecycle_maps", {}):
                self._status.lifecycles_mapped += 1
                continue

            status_col = _find_status_col(col_map)
            if not status_col:
                continue

            await self._gate()

            # State distribution
            sql = (
                f"SELECT {status_col} AS state, COUNT(*) AS n "
                f"FROM {table} WHERE {status_col} IS NOT NULL "
                f"GROUP BY {status_col} ORDER BY n DESC LIMIT 30"
            )
            think = (
                f"Extract lifecycle states for {table}.{status_col}. "
                f"Classify terminal vs active states."
            )
            rows = self._run(sql, think=think)
            if not rows:
                continue

            states = [str(r[0]) for r in rows]
            terminal, active = _classify_states(states)

            # Try to extract transitions via self-join if PK + timestamp exist
            tp_entry = tp.get(table)
            pk_col = tp_entry.grain_column if tp_entry else None
            ts_col = tp_entry.primary_timestamp if tp_entry else None
            transitions: list[LifecycleTransition] = []

            if pk_col and ts_col:
                await self._gate()
                trans_sql = (
                    f"SELECT a.{status_col} AS from_s, b.{status_col} AS to_s, COUNT(*) AS n "
                    f"FROM {table} a "
                    f"JOIN {table} b ON a.{pk_col} = b.{pk_col} AND a.{ts_col} < b.{ts_col} "
                    f"WHERE a.{status_col} != b.{status_col} "
                    f"GROUP BY a.{status_col}, b.{status_col} "
                    f"ORDER BY n DESC LIMIT 20"
                )
                think2 = (
                    f"Extract state transitions for {table}: "
                    f"self-join on {pk_col} ordered by {ts_col}."
                )
                trans_rows = self._run(trans_sql, think=think2)
                if trans_rows:
                    transitions = [
                        LifecycleTransition(
                            from_state=str(r[0]), to_state=str(r[1]), count=int(r[2])
                        )
                        for r in trans_rows
                    ]

            self._state.setdefault("lifecycle_maps", {})[table] = {
                "status_column": status_col,
                "states": states,
                "terminal_states": terminal,
                "active_states": active,
                "transitions": [
                    {"from": t.from_state, "to": t.to_state, "n": t.count}
                    for t in transitions
                ],
            }
            self._status.lifecycles_mapped += 1
            self._status.facts_discovered += 1
            _store.save(self.connection_id, self._state)

    # ── Phase 6: Distribution profiling ──────────────────────────────────────

    async def _phase6_distributions(self, cp: dict) -> None:
        """
        Characterise the value distribution of every measure column.
        Uses basic stats + percentiles to classify shape.
        """
        for table, col_map in cp.items():
            for col_name, col_p in col_map.items():
                if col_p.semantic_type != "measure":
                    continue

                key = f"{table}:{col_name}"
                if key in self._state.get("distributions", {}):
                    self._status.distributions_profiled += 1
                    continue

                await self._gate()

                stats_sql = (
                    f"SELECT COUNT(*) AS n, "
                    f"MIN({col_name}) AS mn, MAX({col_name}) AS mx, "
                    f"AVG({col_name}) AS mean_v, "
                    f"AVG({col_name}*{col_name}) - AVG({col_name})*AVG({col_name}) AS variance, "
                    f"SUM(CASE WHEN {col_name}=0 THEN 1 ELSE 0 END)*1.0/COUNT(*) AS pct_zero "
                    f"FROM {table} WHERE {col_name} IS NOT NULL"
                )
                rows = self._run(stats_sql, think=f"Distribution stats for {table}.{col_name}.")
                if not rows or not rows[0] or not rows[0][0]:
                    continue

                try:
                    n, mn, mx, mean_v, variance, pct_zero = [
                        float(x) if x is not None else 0.0 for x in rows[0]
                    ]
                    n = int(n)
                    if n == 0:
                        continue
                    std_dev = variance ** 0.5 if variance > 0 else 0.0
                except (TypeError, ValueError):
                    continue

                # Initial shape classification from basic stats
                shape = _classify_shape(mn, mx, mean_v, std_dev, float(pct_zero))

                # Refine with percentiles
                await self._gate()
                pct_sql = (
                    f"SELECT "
                    f"percentile_cont(0.25) WITHIN GROUP (ORDER BY {col_name}) AS p25, "
                    f"percentile_cont(0.5)  WITHIN GROUP (ORDER BY {col_name}) AS p50, "
                    f"percentile_cont(0.75) WITHIN GROUP (ORDER BY {col_name}) AS p75 "
                    f"FROM {table} WHERE {col_name} IS NOT NULL"
                )
                pct_rows = self._run(pct_sql, think=f"Percentiles for {table}.{col_name}.")
                p25 = p50 = p75 = None
                if pct_rows and pct_rows[0]:
                    try:
                        p25 = float(pct_rows[0][0] or 0)
                        p50 = float(pct_rows[0][1] or 0)
                        p75 = float(pct_rows[0][2] or 0)
                        if p50 and p50 > 0 and mean_v / p50 > 1.5:
                            shape = DistributionShape.SKEWED_RIGHT
                    except (TypeError, ValueError):
                        pass

                self._state.setdefault("distributions", {})[key] = {
                    "shape": shape.value, "p25": p25, "p50": p50, "p75": p75,
                    "pct_zero": pct_zero, "min": mn, "max": mx, "mean": mean_v,
                    "col_type": col_p.dtype,
                }
                self._status.distributions_profiled += 1
                self._status.facts_discovered += 1
                _store.save(self.connection_id, self._state)

    # ── Phase 7: Cross-table pattern discovery ────────────────────────────────

    async def _phase7_patterns(self, cp: dict, jmap: dict) -> None:
        """
        For each verified join, check if a dimension in the PK table (t2)
        meaningfully explains variation in a measure in the FK table (t1).
        Records findings as OntologyInsights.
        """
        done_ids = {i.get("id") for i in self._state.get("insights", [])}
        joins = jmap.get("joins", [])[:10]  # bound query count

        for j in joins:
            t_fact = j["t1"]   # fact/event table (orders, order_items)
            t_dim  = j["t2"]   # dimension table (customers, products)
            fk_col = j["c1"]
            pk_col = j["c2"]

            dim_cols = [
                name for name, p in cp.get(t_dim, {}).items()
                if (p.semantic_type == "dimension"
                    and p.is_low_cardinality
                    and p.distinct_count is not None
                    and 2 <= p.distinct_count <= 20)
            ][:2]

            mea_cols = [
                name for name, p in cp.get(t_fact, {}).items()
                if p.semantic_type == "measure"
            ][:2]

            if not dim_cols or not mea_cols:
                continue

            for dim_col in dim_cols:
                for mea_col in mea_cols:
                    insight_id = f"{t_dim}.{dim_col}×{t_fact}.{mea_col}"
                    if insight_id in done_ids:
                        continue

                    await self._gate()

                    sql = (
                        f"SELECT d.{dim_col} AS dim_val, "
                        f"ROUND(AVG(f.{mea_col}), 2) AS avg_measure, "
                        f"COUNT(*) AS n "
                        f"FROM {t_fact} f "
                        f"JOIN {t_dim} d ON f.{fk_col} = d.{pk_col} "
                        f"WHERE f.{mea_col} IS NOT NULL AND d.{dim_col} IS NOT NULL "
                        f"GROUP BY d.{dim_col} "
                        f"HAVING COUNT(*) >= 30 "
                        f"ORDER BY avg_measure DESC LIMIT 20"
                    )
                    think = (
                        f"Does '{dim_col}' ({t_dim}) explain variation "
                        f"in '{mea_col}' ({t_fact})? "
                        f"Checking for >15% variation across segments."
                    )
                    rows = self._run(sql, think=think)
                    if not rows or len(rows) < 2:
                        continue

                    try:
                        vals = [float(r[1]) for r in rows if r[1] is not None]
                        if not vals or min(vals) <= 0:
                            continue
                        ratio = max(vals) / min(vals)
                        if ratio < 1.15:
                            continue  # not interesting enough

                        top, bot = rows[0], rows[-1]
                        total_n = sum(int(r[2] or 0) for r in rows)
                        finding = (
                            f"{t_dim}.{dim_col}='{top[0]}' → "
                            f"avg {mea_col} = {top[1]:.2f} vs "
                            f"{bot[1]:.2f} for '{bot[0]}' "
                            f"({(ratio - 1) * 100:.0f}% variation, n={total_n:,})"
                        )
                        insight = {
                            "id": insight_id,
                            "entities_involved": [t_dim, t_fact],
                            "dimensions": [dim_col],
                            "measures": [mea_col],
                            "finding": finding,
                            "sql": sql,
                            "confidence": min(0.95, 0.5 + (ratio - 1) * 0.5),
                            "generated_at": datetime.now(timezone.utc).isoformat(),
                        }
                        self._state.setdefault("insights", []).append(insight)
                        done_ids.add(insight_id)
                        self._status.insights_found += 1
                        self._status.facts_discovered += 1
                        _store.save(self.connection_id, self._state)
                    except (TypeError, ValueError, ZeroDivisionError):
                        continue


    # ── Phase 8: Domain intelligence curiosity loop ───────────────────────────

    async def _phase8_domain_intelligence(self, cp: dict | None = None) -> None:
        """
        For each ontology domain, run an adaptive curiosity loop:
          1. Build domain context from ontology entities + existing findings
          2. Ask LLM: what is the most valuable question to investigate next?
          3. Execute the SQL, interpret the result as a business insight
          4. Store the finding, update knowledge state
          5. Repeat until stopping criteria met
        Stopping: hard budget (15 per domain, extendable by user) OR
                  all coverage angles answered OR novelty decay < 2 avg over last 3
        """
        self._episodes.phase = "domain_intel"
        from pydantic import BaseModel as _BM
        from typing import Literal as _Lit
        from aughor.llm.provider import get_provider
        from aughor.ontology.store import load_latest_ontology
        from aughor.sql.writer import SqlWriter

        ontology = load_latest_ontology(self.connection_id)
        if not ontology:
            logger.info(f"[explorer:{self.connection_id}] Phase 8: no ontology, skipping")
            return

        # Group entities by domain
        domain_entities: dict[str, list] = {}
        for eid, entity in ontology.entities.items():
            d = entity.domain or "General"
            domain_entities.setdefault(d, []).append(entity)

        if not domain_entities:
            return

        # ── Pydantic models for structured LLM output ──────────────────────────

        class _NextQuestion(_BM):
            question: str      # plain-English business question
            sql: str           # executable SQL using exact table/column names
            angle: str         # which coverage angle this answers (from the checklist)
            why: str           # why this is the most valuable next question

        class _Interpretation(_BM):
            finding: str       # 1-2 sentence business insight, specific with numbers
            novelty: int       # 1-5: how new is this vs existing findings for this domain
            angle_covered: str # which coverage angle this satisfies

        # ── Coverage angles per domain ─────────────────────────────────────────

        DOMAIN_ANGLES: dict[str, list[str]] = {
            "Commerce":   ["volume", "value", "retention", "basket_composition", "seasonality"],
            "Finance":    ["revenue", "margins", "payment_behavior", "refund_rate", "receivables"],
            "Marketing":  ["channel_mix", "conversion", "campaign_roi", "attribution", "experiments"],
            "Operations": ["fulfillment", "inventory_health", "supplier_performance", "lead_times"],
        }
        DEFAULT_ANGLES = ["volume", "value", "patterns", "anomalies", "trends"]

        HARD_BUDGET = 15

        llm = get_provider("coder")
        sql_writer = SqlWriter(self._conn)

        def _last_episode_error() -> str:
            """Read the observation from the most recent episode — used to get SQL errors."""
            try:
                import json as _j
                ep_path = Path("data") / f"episodes_{self.connection_id}.jsonl"
                if ep_path.exists():
                    last = ep_path.read_text().strip().split("\n")[-1]
                    return _j.loads(last).get("observation", "SQL execution failed")
            except Exception:
                pass
            return "SQL execution failed"

        for domain, entities in domain_entities.items():
            await self._gate()
            if self._stopped:
                return

            angles = DOMAIN_ANGLES.get(domain, DEFAULT_ANGLES)
            budgets = self._state.setdefault("domain_budgets", {})
            coverage = self._state.setdefault("domain_coverage", {})
            domain_insights: list[dict] = [
                i for i in self._state.get("insights", []) if i.get("domain") == domain
            ]

            used = budgets.get(domain, 0)

            entity_context = "\n".join(
                f"  - {e.display_name} ({', '.join(e.source_tables)}): {e.description}"
                for e in entities
            )
            relationship_context = "\n".join(
                f"  - {r.from_entity} → {r.to_entity} ({r.verb}, {r.cardinality})"
                for r in ontology.relationships.values()
                if any(e.id == r.from_entity or e.id == r.to_entity for e in entities)
            )[:2000]

            logger.info(f"[explorer:{self.connection_id}] Phase 8: {domain} domain — {len(entities)} entities, used={used}")

            while used < budgets.get(f"{domain}__cap", HARD_BUDGET):
                cap = budgets.get(f"{domain}__cap", HARD_BUDGET)
                await self._gate()
                if self._stopped:
                    return

                covered_angles = coverage.get(domain, [])

                # Stop on novelty decay: avg novelty of last 3 findings < 2
                if len(domain_insights) >= 3:
                    recent_novelty = [i.get("novelty", 3) for i in domain_insights[-3:]]
                    if sum(recent_novelty) / 3 < 2.0:
                        logger.info(f"[explorer:{self.connection_id}] Phase 8: {domain} — novelty decay, stopping")
                        break

                existing_findings = "\n".join(
                    f"  • [{i.get('angle','')}] {i.get('finding','')}"
                    for i in domain_insights
                ) or "  (none yet)"

                uncovered = [a for a in angles if a not in covered_angles]
                if not uncovered:
                    # All named angles covered — let LLM propose deeper / cross-cutting questions
                    uncovered = ["deeper_analysis", "anomalies", "cross_domain_patterns", "trends"]

                # Build compact schema for domain tables — grounding _NextQuestion SQL generation
                domain_tables = {tbl for ent in entities for tbl in ent.source_tables}
                domain_schema_lines: list[str] = []
                for tbl in sorted(domain_tables):
                    cols = (
                        sql_writer.table_cols.get(tbl)
                        or sql_writer.table_cols.get(tbl.lower())
                        or next((v for k, v in sql_writer.table_cols.items() if k.lower() == tbl.lower()), None)
                    )
                    if cols:
                        domain_schema_lines.append(f"  {tbl}: {', '.join(cols)}")
                domain_schema_block = (
                    "EXACT COLUMN NAMES — use ONLY these, never invent:\n"
                    + "\n".join(domain_schema_lines)
                ) if domain_schema_lines else ""

                # Step 1: Ask LLM what to investigate next (schema-grounded)
                try:
                    nq: _NextQuestion = llm.complete(
                        system=(
                            "You are a data analyst autonomously exploring a business database. "
                            "Propose exactly one SQL query that will reveal the most valuable business insight "
                            "for the given domain. CRITICAL: use ONLY the exact column names provided in "
                            "EXACT COLUMN NAMES — never guess or invent column names. "
                            "Write SELECT-only SQL. Be specific — include actual aggregations and comparisons."
                        ),
                        user=(
                            f"DOMAIN: {domain}\n\n"
                            f"ENTITIES IN THIS DOMAIN:\n{entity_context}\n\n"
                            f"RELATIONSHIPS:\n{relationship_context}\n\n"
                            f"{domain_schema_block}\n\n"
                            f"COVERAGE ANGLES TO EXPLORE: {', '.join(uncovered)}\n"
                            f"ANGLES ALREADY COVERED: {', '.join(covered_angles) or 'none'}\n\n"
                            f"EXISTING FINDINGS FOR THIS DOMAIN:\n{existing_findings}\n\n"
                            "Propose the single most valuable next question to investigate. "
                            "Choose an uncovered angle. Write SQL using ONLY the column names above."
                        ),
                        response_model=_NextQuestion,
                    )
                except Exception as e:
                    logger.warning(f"[explorer:{self.connection_id}] Phase 8: LLM question gen failed for {domain}: {e}")
                    break

                # Step 2: Execute SQL — repair loop: run → fail → fix with real error → repeat
                MAX_ATTEMPTS = 3
                think_str = f"Domain {domain} | angle={nq.angle} | {nq.question}"
                sql = nq.sql
                rows = None

                for attempt in range(MAX_ATTEMPTS):
                    label = think_str if attempt == 0 else f"[retry {attempt}] {think_str}"
                    rows = self._run(sql, think=label)
                    if rows is not None:
                        break
                    if attempt >= MAX_ATTEMPTS - 1:
                        logger.warning(
                            f"[explorer:{self.connection_id}] Phase 8: all {MAX_ATTEMPTS} attempts "
                            f"failed for {domain}/{nq.angle}"
                        )
                        break
                    error_msg = _last_episode_error()
                    fix = sql_writer.fix(sql, error_msg, max_retries=1)
                    if not fix.ok:
                        logger.warning(
                            f"[explorer:{self.connection_id}] Phase 8: fix failed at attempt "
                            f"{attempt+1} for {domain}/{nq.angle}: {fix.final_error}"
                        )
                        break
                    logger.info(
                        f"[explorer:{self.connection_id}] Phase 8: fix attempt {attempt+1} "
                        f"for {domain}/{nq.angle} — {fix.explanation}"
                    )
                    sql = fix.sql

                used += 1
                budgets[domain] = used
                self._state["domain_budgets"] = budgets

                if not rows or len(rows) == 0:
                    logger.debug(f"[explorer:{self.connection_id}] Phase 8: empty result for {nq.question}")
                    continue

                # Format result for LLM interpretation (max 20 rows)
                result_text = "\n".join(str(r) for r in rows[:20])

                # Step 3: Interpret the result
                try:
                    interp: _Interpretation = llm.complete(
                        system=(
                            "You are interpreting a SQL query result as a concise business insight. "
                            "Write 1-2 sentences maximum. Include specific numbers. "
                            "Focus on what is actionable or surprising. "
                            "Novelty score: 1=already known/trivial, 5=genuinely new and surprising."
                        ),
                        user=(
                            f"DOMAIN: {domain}\n"
                            f"QUESTION: {nq.question}\n"
                            f"SQL RESULT (first 20 rows):\n{result_text}\n\n"
                            f"EXISTING FINDINGS FOR CONTEXT:\n{existing_findings}\n\n"
                            "Interpret this result as a business insight."
                        ),
                        response_model=_Interpretation,
                    )
                except Exception as e:
                    logger.warning(f"[explorer:{self.connection_id}] Phase 8: LLM interpretation failed for {domain}: {e}")
                    continue

                # Step 4: Store the insight
                insight_id = f"{domain}__{nq.angle}__{used}"
                insight = {
                    "id": insight_id,
                    "domain": domain,
                    "angle": interp.angle_covered or nq.angle,
                    "entities_involved": [e.id for e in entities[:4]],
                    "dimensions": [],
                    "measures": [],
                    "finding": interp.finding,
                    "sql": nq.sql,
                    "confidence": min(0.95, 0.4 + interp.novelty * 0.1),
                    "novelty": interp.novelty,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                }
                self._state.setdefault("insights", []).append(insight)
                domain_insights.append(insight)
                self._status.insights_found += 1
                self._status.facts_discovered += 1

                # Mark angle as covered
                angle_key = interp.angle_covered or nq.angle
                covered = coverage.get(domain, [])
                if angle_key not in covered:
                    covered.append(angle_key)
                    coverage[domain] = covered
                self._state["domain_coverage"] = coverage
                self._status.domain_budgets = dict(budgets)
                self._status.domain_coverage = dict(coverage)

                _store.save(self.connection_id, self._state)
                logger.info(
                    f"[explorer:{self.connection_id}] Phase 8: {domain}/{angle_key} — "
                    f"novelty={interp.novelty} — \"{interp.finding[:80]}…\""
                )


# ── Helpers (module-level) ────────────────────────────────────────────────────

def _find_status_col(col_map: dict) -> Optional[str]:
    """Return the most likely lifecycle/status column in a table's column map."""
    for col_name, col_p in col_map.items():
        if (
            col_p.semantic_type == "dimension"
            and col_p.is_low_cardinality
            and col_p.top_values
            and any(
                v.lower() in _TERMINAL | _ACTIVE
                or any(s in v.lower() for s in _TERMINAL_SUBS + _ACTIVE_SUBS)
                for v in col_p.top_values
            )
        ):
            return col_name
    return None


def _classify_states(states: list[str]) -> tuple[list[str], list[str]]:
    """Split a list of state names into (terminal, active) buckets."""
    terminal: list[str] = []
    active: list[str] = []
    for s in states:
        sl = s.lower()
        if sl in _TERMINAL or any(t in sl for t in _TERMINAL_SUBS):
            terminal.append(s)
        elif sl in _ACTIVE or any(a in sl for a in _ACTIVE_SUBS):
            active.append(s)
    return terminal, active


def _classify_shape(mn: float, mx: float, mean: float, std: float, pct_zero: float) -> DistributionShape:
    """Heuristic distribution shape from basic stats."""
    if mn >= 0 and mx <= 1.01:
        return DistributionShape.FRACTION_0_1
    if std == 0 or mx == mn:
        return DistributionShape.CONCENTRATED
    cv = std / abs(mean) if mean != 0 else float("inf")
    if pct_zero > 0.5 and cv > 1.5:
        return DistributionShape.CONCENTRATED
    if cv > 2.0:
        return DistributionShape.SKEWED_RIGHT
    if cv < 0.15:
        return DistributionShape.CONCENTRATED
    return DistributionShape.NORMAL
