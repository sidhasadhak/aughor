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
    "refunded", "bounced", "blocked",
    # "completed", "done", "delivered", "shipped" removed — these are
    # context-dependent (e.g. "shipped" is mid-flow in fulfillment).
    # Terminal classification is now advisory, not filtering.
})
_ACTIVE = frozenset({
    "active", "live", "running", "processing", "open", "pending", "approved",
    "in_progress", "inprogress", "scheduled", "confirmed", "new", "created",
    "placed", "accepted", "ready", "invoiced",
})

# Substring signals for heuristic state classification when exact match fails
_TERMINAL_SUBS = ("cancel", "fail", "reject", "expir", "close", "archiv", "delet", "return", "void", "refund", "churn")
_ACTIVE_SUBS   = ("pend", "process", "approv", "creat", "open", "activ", "run", "sched", "place", "accept", "new")


# ── Temporal scope — Tier 0: role-aware recency ───────────────────────────────────
# Anchor the analytical window's recency on the CONSENSUS TRAILING EDGE OF ACTIVITY
# among measure-bearing event/fact tables — never MAX(any date column). A calendar /
# date-dimension table holds one row per day far into the future and is uniformly dense
# (so effective_date_range == its full span); anchoring on the global MAX would push the
# window past the last real fact and every fact filter returns zero rows ("no data"
# briefings). See docs/ADAPTIVE_TEMPORAL_SCOPE.md §3.

_SENTINEL_MAX_YEAR = 9999
_SENTINEL_MIN_YEAR = 1900
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")


def _profile_field(prof, name):
    """Read a field from a TableProfile/ColumnProfile that may be a dataclass or a dict."""
    if isinstance(prof, dict):
        return prof.get(name)
    return getattr(prof, name, None)


def _table_recency(prof):
    """Sentinel-filtered recency for a table — (YYYY-MM-DD, is_effective) or (None, False).
    Prefers the dense ``effective_date_range`` over the raw ``date_range``."""
    for key, is_eff in (("effective_date_range", True), ("date_range", False)):
        rng = _profile_field(prof, key)
        if rng and len(rng) >= 2 and _ISO_DATE.match(str(rng[1])):
            head = str(rng[1])[:10]
            try:
                year = int(head[:4])
            except ValueError:
                continue
            if year >= _SENTINEL_MAX_YEAR or year <= _SENTINEL_MIN_YEAR:
                continue  # 9999-12-31 / 1900-01-01 / epoch placeholder — not real activity
            return head, is_eff
    return None, False


def _table_has_measure(cols) -> bool:
    """True when the table has ≥1 additive measure column — what makes it an *activity*
    (fact/event) table rather than a calendar/dimension spine. Tolerates ``cols`` as a
    dict {name: profile} or a list of profiles, each a dataclass or a dict."""
    if not cols:
        return False
    vals = cols.values() if isinstance(cols, dict) else cols
    return any(_profile_field(c, "semantic_type") == "measure" for c in vals)


def _days_between(a: str, b: str) -> int:
    """Absolute day gap between two ISO date strings; 0 on parse error."""
    try:
        return abs((datetime.fromisoformat(b[:10]) - datetime.fromisoformat(a[:10])).days)
    except (ValueError, TypeError):
        return 0


def _anchor_activity(tp, cp=None):
    """Return ``(table, recency, is_effective)`` for the measure-bearing activity table
    with the latest sentinel-filtered recency — the table whose trailing edge defines the
    window. Falls back to all dated tables when no measures are detected. Returns
    ``(None, None, False)`` when nothing is usable."""
    activity, spine = [], []   # each: (recency, is_effective, table)
    for table, prof in (tp or {}).items():
        rec, is_eff = _table_recency(prof)
        if rec is None:
            continue
        (activity if _table_has_measure((cp or {}).get(table)) else spine).append((rec, is_eff, table))
    pool = activity or spine
    if not pool:
        return None, None, False
    rec, is_eff, table = max(pool, key=lambda r: r[0])
    return table, rec, is_eff


def _role_aware_time_window(tp, cp=None, jmap=None, months: int = 12):
    """Choose the analytical window by anchoring recency on *activity* tables.

    Returns ``(start_iso, end_iso, discrepancy)`` where ``discrepancy`` is a list of
    ``(table, recency)`` for non-activity tables (calendar / dimension spines) whose
    dates extend *past* the chosen activity edge — a data-quality signal worth
    surfacing. Returns ``(None, None, [])`` when no usable, non-sentinel date range
    exists. ``jmap`` is accepted for a future join-graph in-degree refinement; the
    measure signal (``cp``) is the primary catch today.
    """
    from datetime import timedelta as _td

    _anchor, best_rec, best_eff = _anchor_activity(tp, cp)
    if best_rec is None:
        return None, None, []

    discrepancy = sorted(
        ((t, _table_recency(p)[0]) for t, p in (tp or {}).items()
         if not _table_has_measure((cp or {}).get(t)) and (_table_recency(p)[0] or "") > best_rec),
        key=lambda x: x[1], reverse=True,
    )

    try:
        max_d = datetime.fromisoformat(best_rec)
        if best_eff:
            # an effective max is month-truncated — nudge forward to cover the final month
            max_d = max_d + _td(days=31)
        start_d = max_d - _td(days=round(months * 30.4375))
        return start_d.strftime("%Y-%m-%d"), max_d.strftime("%Y-%m-%d"), discrepancy
    except (ValueError, TypeError):
        return None, None, []


class SchemaExplorer:
    """
    Background schema exploration agent.

    Create one per connected database and schedule ``explore()`` as an
    asyncio task.  Call ``pause()`` / ``resume()`` to yield to investigations.
    """

    def __init__(
        self,
        connection_id: str,
        conn: "DatabaseConnection",
        canvas_id: Optional[str] = None,
        tables_filter: Optional[list[str]] = None,
    ) -> None:
        self.connection_id = connection_id
        self.canvas_id = canvas_id
        self.tables_filter = tables_filter  # non-empty list = restrict phases 3-7 to these tables
        self._conn = conn
        self._status = ExplorationStatus(
            connection_id=connection_id,
            canvas_id=canvas_id,
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        # Canvas-scoped explorer uses a separate state/episode key
        _store_key = f"canvas_{canvas_id}" if canvas_id else connection_id
        self._store_key = _store_key
        self._episodes = EpisodeCollector(_store_key)
        self._can_run = asyncio.Event()
        self._can_run.set()
        self._stopped = False
        self._state = _store.load_canvas(canvas_id) if canvas_id else _store.load(connection_id)
        self._last_query_at: float = 0.0
        self._rate_seconds: float = _RATE_SECONDS_SCHEMA
        self._time_window: Optional[tuple[str, str]] = None  # (start_iso, end_iso) — 12-month window
        self._macro_context: Optional[dict] = None  # Tier 2 full-span long-arc rollup

    # ── State persistence helpers ─────────────────────────────────────────────

    def _save_state(self) -> None:
        if self.canvas_id:
            _store.save_canvas(self.canvas_id, self._state)
        else:
            _store.save(self.connection_id, self._state)

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

    async def _run(self, sql: str, think: str = "") -> Optional[list]:
        """Execute one read-only SQL query off the event loop and record an episode turn."""
        loop = asyncio.get_running_loop()
        self._last_query_at = time.monotonic()
        self._status.queries_executed += 1
        try:
            result = await loop.run_in_executor(
                None, self._conn.execute, "__explorer__", sql
            )
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

    # ── Time window helpers ───────────────────────────────────────────────────

    def _compute_time_window(
        self, tp: dict, cp: Optional[dict] = None, jmap: Optional[dict] = None,
    ) -> Optional[tuple[str, str]]:
        """Anchor the 12-month window's recency on the consensus trailing edge of
        *activity* (measure-bearing event/fact tables), excluding calendar/dimension
        spines — so a date dimension running into the future can't push the window past
        the last real fact and yield empty ("no data") briefings. Sentinel dates
        (9999/1900/epoch) are filtered, and the dense ``effective_date_range`` is
        preferred over the raw ``date_range``. See docs/ADAPTIVE_TEMPORAL_SCOPE.md §3.
        """
        start, end, discrepancy = _role_aware_time_window(tp, cp, jmap)
        if discrepancy:
            spines = ", ".join(f"{t} (→{r})" for t, r in discrepancy[:3])
            logger.info(
                "[explorer:%s] Date spine(s) extend past the last activity (%s): %s — "
                "anchoring on observed activity, not the calendar.",
                self.connection_id, end, spines,
            )
        if not (start and end):
            return None

        # Tier 1: narrow to the CURRENT regime when one is clearly present. Regime-narrows-
        # only — we move the window start forward to a recent structural break, never widen
        # or weaken the Tier-0 result; any failure falls back to the fixed window.
        try:
            anchor, _rec, _eff = _anchor_activity(tp, cp)
            if anchor:
                regime_start = self._regime_window_start(anchor, tp, start)
                # Floor: never narrow below ~a quarter of data — guards against a recent
                # daily/weekly spike collapsing the window to days.
                if regime_start and regime_start > start and _days_between(regime_start, end) >= 90:
                    logger.info(
                        "[explorer:%s] Tier 1: narrowing window to current regime (start %s → %s)",
                        self.connection_id, start, regime_start,
                    )
                    start = regime_start
        except Exception:
            logger.debug("[explorer:%s] Tier 1 regime refinement skipped", self.connection_id, exc_info=True)

        return start, end

    def _regime_window_start(self, table: str, tp: dict, win_start: str) -> Optional[str]:
        """Query the activity density series (rows per period) for ``table`` and return the
        current-regime start date when a structural break falls *inside* the window
        (``> win_start``), else None. Best-effort; never raises into the pipeline.
        Tier 1 of docs/ADAPTIVE_TEMPORAL_SCOPE.md."""
        prof = tp.get(table)
        ts_col = getattr(prof, "primary_timestamp", None) if prof else None
        if not ts_col:
            return None
        grain = (getattr(prof, "time_grain", None) or "month")
        unit = {"day": "day", "week": "week", "month": "month",
                "quarter": "quarter", "year": "year"}.get(grain, "month")
        sql = (
            f"SELECT date_trunc('{unit}', {ts_col})::VARCHAR AS p, COUNT(*) AS c "
            f"FROM {table} WHERE {ts_col} IS NOT NULL GROUP BY 1 ORDER BY 1"
        )
        try:
            r = self._conn.execute("__explorer__", sql)
        except Exception:
            return None
        rows = (r.rows or []) if not getattr(r, "error", None) else []
        if len(rows) < 12:   # need enough periods for a meaningful regime
            return None
        periods = [str(row[0])[:10] for row in rows]
        counts = [row[1] for row in rows]
        try:
            from aughor.explorer.regime import adaptive_window
            rstart, _rend, _reason = adaptive_window(periods, counts)
        except Exception:
            return None
        return rstart if (rstart and rstart > win_start) else None

    def _compute_macro_context(self, tp: dict, cp: dict) -> Optional[dict]:
        """Tier 2: one coarse full-span rollup over the anchor activity table — the long
        arc (secular trend / growth factor) the briefing juxtaposes against the recent
        regime. Cheap (one GROUP BY year, ~N_years rows). Best-effort; returns None on
        any failure. See aughor/explorer/temporal.py + docs/ADAPTIVE_TEMPORAL_SCOPE.md §5."""
        anchor, _rec, _eff = _anchor_activity(tp, cp)
        if not anchor:
            return None
        prof = tp.get(anchor)
        ts_col = getattr(prof, "primary_timestamp", None) if prof else None
        if not ts_col:
            return None

        # Roll up at year grain unless the full span is short (then quarter).
        grain = "year"
        # Pick one additive measure column on the anchor to roll up alongside row counts.
        # Skip key/id-like columns the profiler mis-tags as measures — SUM(l_orderkey)
        # is a meaningless aggregate of identifiers, not a business quantity.
        def _looks_like_key(name: str) -> bool:
            n = name.lower()
            # _key/_id (snake) and ...key/...id (TPC-style concat: l_orderkey, partkey)
            return (n in ("id", "key") or n.endswith(("_id", "_key", "_no", "_num", "_code", "_sk",
                                                       "key", "id"))
                    or n.startswith(("id_", "key_")))
        measure_col = None
        for col_name, col_p in (cp.get(anchor) or {}).items():
            if _profile_field(col_p, "semantic_type") == "measure" and not _looks_like_key(col_name):
                measure_col = col_name
                break

        measure_expr = f", SUM({measure_col}) AS m" if measure_col else ""
        sql = (
            f"SELECT date_trunc('{grain}', {ts_col})::VARCHAR AS p, COUNT(*) AS c{measure_expr} "
            f"FROM {anchor} WHERE {ts_col} IS NOT NULL GROUP BY 1 ORDER BY 1"
        )
        try:
            r = self._conn.execute("__explorer__", sql)
        except Exception:
            return None
        rows = (r.rows or []) if not getattr(r, "error", None) else []
        if len(rows) < 2:
            return None

        periods = [str(row[0])[:10] for row in rows]
        counts = [row[1] for row in rows]
        measures = [row[2] for row in rows] if measure_col else None

        from aughor.explorer.temporal import build_macro_context
        micro_start = self._time_window[0] if self._time_window else None
        return build_macro_context(
            periods, counts, measures=measures, measure_name=measure_col,
            micro_start=micro_start, grain=grain, anchor=anchor,
        )

    def _time_filter(self, table: str, tp: dict) -> str:
        """
        Return a SQL AND-clause fragment for the 12-month time window, e.g.
          'AND order_purchase_timestamp >= \'2023-09-14\''
        Returns '' if no time window is set or the table has no primary timestamp.
        """
        if not self._time_window:
            return ""
        t_profile = tp.get(table)
        if not t_profile:
            return ""
        ts_col = getattr(t_profile, "primary_timestamp", None)
        if not ts_col:
            return ""
        start_str, _ = self._time_window
        return f"AND {ts_col} >= '{start_str}'"

    # ── Main loop ─────────────────────────────────────────────────────────────

    async def explore(self, domain_intel_only: bool = False) -> None:
        """Full exploration run — schedule this as an asyncio.Task.

        If domain_intel_only=True (triggered by "Explore 5 more") skips phases 3-7
        and runs only Phase 8, consuming the extended budget.
        """
        logger.info(f"[explorer:{self.connection_id}] Starting (domain_intel_only={domain_intel_only})")
        _loop = asyncio.get_running_loop()
        try:
            tp, cp, jmap = await _loop.run_in_executor(None, self._load_profiler_data)
            if not tp:
                logger.info(f"[explorer:{self.connection_id}] No profiler data, aborting")
                return

            self._status.tables_total = len(tp)
            self._status.columns_total = sum(len(v) for v in cp.values())
            self._status.joins_total = len(jmap.get("joins", []))

            # Compute the 12-month window — recency anchored on activity (fact) tables,
            # not the calendar spine (Tier 0; docs/ADAPTIVE_TEMPORAL_SCOPE.md §3).
            self._time_window = self._compute_time_window(tp, cp, jmap)
            if self._time_window:
                logger.info(
                    "[explorer:%s] Time window: %s → %s",
                    self.connection_id, self._time_window[0], self._time_window[1],
                )

            # Tier 2: cheap full-span macro rollup over the anchor — the long arc that
            # briefings juxtapose against the recent-regime micro window. Best-effort.
            try:
                self._macro_context = self._compute_macro_context(tp, cp)
                if self._macro_context:
                    self._state["macro_context"] = self._macro_context
                    self._save_state()
                    logger.info(
                        "[explorer:%s] Macro context: %s %s→%s (%d %ss)",
                        self.connection_id, self._macro_context.get("anchor"),
                        self._macro_context.get("first_period"), self._macro_context.get("last_period"),
                        self._macro_context.get("n_periods"), self._macro_context.get("grain"),
                    )
            except Exception:
                logger.debug("[explorer:%s] Tier 2 macro context skipped", self.connection_id, exc_info=True)

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
                await self._phase6_distributions(cp, tp)

                # Phase 7 — Cross-table pattern discovery
                self._status.phase = ExplorationPhase.CROSS_TABLE
                await self._phase7_patterns(cp, jmap, tp)

            # ── Ontology gate: Phase 8 needs the ontology; build it now if it
            # hasn't been created yet.  On a fresh connection, phases 3-7 can
            # finish in <10 s while the ontology build (triggered by the first
            # /ontology API request) may not have happened yet.  get_schema()
            # is idempotent + cached — instant on the second call.
            from aughor.ontology.store import load_latest_ontology as _load_onto
            if not _load_onto(self.connection_id):
                logger.info(
                    "[explorer:%s] Ontology not found before Phase 8 — building now…",
                    self.connection_id,
                )
                try:
                    await _loop.run_in_executor(None, self._conn.build_intelligence)
                    logger.info(
                        "[explorer:%s] Ontology build complete, proceeding to Phase 8",
                        self.connection_id,
                    )
                except Exception as _onto_exc:
                    logger.warning(
                        "[explorer:%s] Ontology build failed — Phase 8 will be skipped: %s",
                        self.connection_id, _onto_exc,
                    )

            # Phase 8 — Domain intelligence: slow down to avoid overloading the DB
            # and to allow the user to stop between queries if needed
            self._rate_seconds = _RATE_SECONDS_INTEL
            self._status.phase = ExplorationPhase.DOMAIN_INTEL
            self._status.domain_intel_skipped = False   # cleared; set by Phase 8 if it bails
            self._status.domain_intel_note = None
            await self._phase8_domain_intelligence(cp, tp)

            # Done — persist runtime counters so the status fallback can restore them
            self._status.phase = ExplorationPhase.COMPLETE
            self._status.completed_at = datetime.now(timezone.utc).isoformat()
            self._state["phase"] = ExplorationPhase.COMPLETE.value
            self._state["tables_total"] = self._status.tables_total
            self._state["columns_total"] = self._status.columns_total
            self._state["queries_executed"] = self._status.queries_executed
            self._state["started_at"] = self._status.started_at
            self._state["completed_at"] = self._status.completed_at
            self._state["domain_intel_skipped"] = self._status.domain_intel_skipped
            self._state["domain_intel_note"] = self._status.domain_intel_note
            self._save_state()
            logger.info(
                f"[explorer:{self.connection_id}] Complete — "
                f"{self._status.queries_executed}q, "
                f"{self._status.facts_discovered} facts, "
                f"{self._status.insights_found} insights"
            )

        except asyncio.CancelledError:
            self._save_state()
            logger.info(f"[explorer:{self.connection_id}] Cancelled, progress saved")
            raise
        except Exception as e:
            self._status.phase = ExplorationPhase.FAILED
            self._status.error = str(e)
            self._save_state()
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
                if schema:
                    schema_filter = f"= '{schema}'"
                else:
                    # No specific schema configured — scan all user-defined schemas.
                    # DuckDB databases can store tables in non-default schemas
                    # (e.g. samples.duckdb uses 'ecommerce'). Exclude system catalogs.
                    schema_filter = "NOT IN ('information_schema', 'pg_catalog', 'temp')"
            else:
                schema_filter = f"= '{schema or 'public'}'"
            r = self._conn.execute(
                "__explorer__",
                f"SELECT table_schema, table_name FROM information_schema.tables "
                f"WHERE table_schema {schema_filter} "
                f"AND table_type = 'BASE TABLE' ORDER BY table_schema, table_name",
            )
            raw_tables = [(row[0], row[1]) for row in (r.rows or [])] if not r.error else []
            # When multiple schemas exist, fully-qualify table names so generated
            # SQL resolves correctly (e.g. bakehouse.sales_franchises).
            schemas_seen = {s for s, _ in raw_tables}
            if len(schemas_seen) > 1 or (schema and schema not in schemas_seen and len(raw_tables) > 0):
                tables = [f'{s}.{t}' for s, t in raw_tables]
            elif len(schemas_seen) == 1 and not schema:
                # Single schema, no explicit schema configured — still qualify to be safe
                single_schema = next(iter(schemas_seen))
                tables = [f'{single_schema}.{t}' for s, t in raw_tables]
            else:
                tables = [t for _, t in raw_tables]

            if not tables:
                return {}, {}, {}

            # Filter tables to canvas scope when set
            if self.tables_filter:
                filter_set = set(self.tables_filter)
                tables = [t for t in tables if t in filter_set or t.split('.')[-1] in filter_set]
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
                    result = await self._null_cross_ref(table, col_name, status_col, col_p.null_rate, tp=tp)
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
                self._save_state()

    async def _null_cross_ref(
        self, table: str, col: str, status_col: str, null_rate: float,
        tp: Optional[dict] = None,
    ) -> NullMeaningResult:
        tf = self._time_filter(table, tp or {})
        sql = (
            f"SELECT {status_col} AS s, COUNT(*) AS total, "
            f"SUM(CASE WHEN {col} IS NULL THEN 1 ELSE 0 END) AS null_n, "
            f"ROUND(SUM(CASE WHEN {col} IS NULL THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS null_pct "
            f"FROM {table} WHERE 1=1 {tf} "
            f"GROUP BY {status_col} ORDER BY null_pct DESC LIMIT 20"
        )
        think = (
            f"'{table}.{col}' has {null_rate:.0%} nulls. "
            f"Cross-referencing with '{status_col}' to classify: "
            f"pending-event vs terminal-state vs data-quality issue."
        )
        rows = await self._run(sql, think=think)
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
            rows = await self._run(sql, think=think)

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
                self._save_state()

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

            tf = self._time_filter(table, tp)

            # State distribution
            sql = (
                f"SELECT {status_col} AS state, COUNT(*) AS n "
                f"FROM {table} WHERE {status_col} IS NOT NULL {tf} "
                f"GROUP BY {status_col} ORDER BY n DESC LIMIT 30"
            )
            think = (
                f"Extract lifecycle states for {table}.{status_col}. "
                f"Classify terminal vs active states."
            )
            rows = await self._run(sql, think=think)
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
                # Time filter for self-join must be qualified with alias 'a'
                alias_tf = (
                    f"AND a.{ts_col} >= '{self._time_window[0]}'"
                    if self._time_window else ""
                )
                trans_sql = (
                    f"SELECT a.{status_col} AS from_s, b.{status_col} AS to_s, COUNT(*) AS n "
                    f"FROM {table} a "
                    f"JOIN {table} b ON a.{pk_col} = b.{pk_col} AND a.{ts_col} < b.{ts_col} "
                    f"WHERE a.{status_col} != b.{status_col} {alias_tf} "
                    f"GROUP BY a.{status_col}, b.{status_col} "
                    f"ORDER BY n DESC LIMIT 20"
                )
                think2 = (
                    f"Extract state transitions for {table}: "
                    f"self-join on {pk_col} ordered by {ts_col}."
                )
                trans_rows = await self._run(trans_sql, think=think2)
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
            self._save_state()

    # ── Phase 6: Distribution profiling ──────────────────────────────────────

    async def _phase6_distributions(self, cp: dict, tp: dict = None) -> None:
        """
        Characterise the value distribution of every measure column.
        Uses basic stats + percentiles to classify shape.
        """
        tp = tp or {}
        # Phase-completion guard: if a previous full run already finished this
        # phase, skip it entirely rather than re-checking every column.
        if self._state.get("phase6_done"):
            self._status.distributions_profiled = len(self._state.get("distributions", {}))
            return

        for table, col_map in cp.items():
            for col_name, col_p in col_map.items():
                if col_p.semantic_type != "measure":
                    continue

                key = f"{table}:{col_name}"
                existing = self._state.get("distributions", {}).get(key)
                if existing is not None and not existing.get("_partial"):
                    # Fully computed in a previous run — skip
                    self._status.distributions_profiled += 1
                    continue

                await self._gate()

                tf = self._time_filter(table, tp)
                stats_sql = (
                    f"SELECT COUNT(*) AS n, "
                    f"MIN({col_name}) AS mn, MAX({col_name}) AS mx, "
                    f"AVG(CAST({col_name} AS FLOAT)) AS mean_v, "
                    f"AVG(CAST({col_name} AS FLOAT)*CAST({col_name} AS FLOAT)) - AVG(CAST({col_name} AS FLOAT))*AVG(CAST({col_name} AS FLOAT)) AS variance, "
                    f"SUM(CASE WHEN {col_name}=0 THEN 1 ELSE 0 END)*1.0/COUNT(*) AS pct_zero "
                    f"FROM {table} WHERE {col_name} IS NOT NULL {tf}"
                )
                rows = await self._run(stats_sql, think=f"Distribution stats for {table}.{col_name}.")
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

                # Save a partial record immediately after the first query so that a
                # server crash between the two queries doesn't cause the stats query
                # to re-fire on the next run.
                self._state.setdefault("distributions", {})[key] = {
                    "shape": shape.value, "p25": None, "p50": None, "p75": None,
                    "pct_zero": pct_zero, "min": mn, "max": mx, "mean": mean_v,
                    "col_type": col_p.dtype,
                    "_partial": True,
                }
                self._save_state()

                # Refine with percentiles
                await self._gate()
                pct_sql = (
                    f"SELECT "
                    f"percentile_cont(0.25) WITHIN GROUP (ORDER BY {col_name}) AS p25, "
                    f"percentile_cont(0.5)  WITHIN GROUP (ORDER BY {col_name}) AS p50, "
                    f"percentile_cont(0.75) WITHIN GROUP (ORDER BY {col_name}) AS p75 "
                    f"FROM {table} WHERE {col_name} IS NOT NULL {tf}"
                )
                pct_rows = await self._run(pct_sql, think=f"Percentiles for {table}.{col_name}.")
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

                # Write final (non-partial) record
                self._state["distributions"][key] = {
                    "shape": shape.value, "p25": p25, "p50": p50, "p75": p75,
                    "pct_zero": pct_zero, "min": mn, "max": mx, "mean": mean_v,
                    "col_type": col_p.dtype,
                }
                self._status.distributions_profiled += 1
                self._status.facts_discovered += 1
                self._save_state()

        # Mark the entire phase as done so restarts can skip it immediately
        self._state["phase6_done"] = True
        self._save_state()

    # ── Phase 7: Cross-table pattern discovery ────────────────────────────────

    async def _phase7_patterns(self, cp: dict, jmap: dict, tp: dict = None) -> None:
        """
        For each verified join, check if a dimension in the PK table (t2)
        meaningfully explains variation in a measure in the FK table (t1).
        Records findings as OntologyInsights.
        """
        tp = tp or {}
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

                    # Time-scope the fact table to 12-month window
                    fact_tf = ""
                    if self._time_window:
                        t_profile = tp.get(t_fact)
                        ts_col = getattr(t_profile, "primary_timestamp", None) if t_profile else None
                        if ts_col:
                            fact_tf = f"AND f.{ts_col} >= '{self._time_window[0]}'"

                    sql = (
                        f"SELECT d.{dim_col} AS dim_val, "
                        f"ROUND(AVG(f.{mea_col}), 2) AS avg_measure, "
                        f"COUNT(*) AS n "
                        f"FROM {t_fact} f "
                        f"JOIN {t_dim} d ON f.{fk_col} = d.{pk_col} "
                        f"WHERE f.{mea_col} IS NOT NULL AND d.{dim_col} IS NOT NULL {fact_tf} "
                        f"GROUP BY d.{dim_col} "
                        f"HAVING COUNT(*) >= 30 "
                        f"ORDER BY avg_measure DESC LIMIT 20"
                    )
                    think = (
                        f"Does '{dim_col}' ({t_dim}) explain variation "
                        f"in '{mea_col}' ({t_fact})? "
                        f"Checking for >15% variation across segments."
                    )
                    rows = await self._run(sql, think=think)
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
                            "canvas_id": self.canvas_id,
                            "promoted_to_org": False,
                            "promotion_confidence": 0.0,
                        }
                        self._state.setdefault("insights", []).append(insight)
                        done_ids.add(insight_id)
                        self._status.insights_found += 1
                        self._status.facts_discovered += 1
                        self._save_state()
                    except (TypeError, ValueError, ZeroDivisionError):
                        continue


    # ── Phase 8: Domain intelligence curiosity loop ───────────────────────────

    async def _phase8_domain_intelligence(
        self,
        cp: dict | None = None,
        tp: dict | None = None,
    ) -> None:
        """
        For each ontology domain, run an adaptive curiosity loop:
          1. Build domain context from ontology entities + existing findings
          2. Ask LLM: what is the most valuable question to investigate next?
          3. Execute the SQL, interpret the result as a business insight
          4. Store the finding, update knowledge state
          5. Repeat until stopping criteria met
        Stopping: hard budget (15 per domain, extendable by user) OR
                  all coverage angles answered OR novelty decay < 2 avg over last 3

        cp: {table: {col: ColumnProfile}}   (column profiles — cardinality, FK flags)
        tp: {table: TableProfile}           (table profiles — grain, row counts)
        """
        self._episodes.phase = "domain_intel"
        _loop = asyncio.get_running_loop()
        from pydantic import BaseModel as _BM
        from typing import Literal as _Lit
        from aughor.llm.provider import get_provider
        from aughor.ontology.store import load_latest_ontology
        from aughor.sql.writer import SqlWriter

        ontology = load_latest_ontology(self.connection_id)
        if not ontology:
            logger.warning(
                "[explorer:%s] Phase 8: ontology still not available after build attempt — skipping domain intelligence",
                self.connection_id,
            )
            self._status.domain_intel_skipped = True
            self._status.domain_intel_note = (
                "Ontology unavailable — the object model that domain intelligence is "
                "derived from could not be built (the schema may be too sparse to model)."
            )
            return

        # Group entities by domain
        domain_entities: dict[str, list] = {}
        for eid, entity in ontology.entities.items():
            d = entity.domain or "General"
            domain_entities.setdefault(d, []).append(entity)

        if not domain_entities:
            self._status.domain_intel_skipped = True
            self._status.domain_intel_note = (
                "Ontology built, but produced no entities to reason about."
            )
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

                # ── Grain + cardinality context ─────────────────────────────────
                # Inject table grains, row counts, FK columns, and high-cardinality
                # info so the LLM writes JOIN-safe SQL.
                grain_lines: list[str] = []
                fk_pairs: list[tuple[str, str, str]] = []   # (child_tbl, fk_col, parent_tbl hint)

                for tbl in sorted(domain_tables):
                    t_profile = (tp or {}).get(tbl) or (tp or {}).get(tbl.lower())
                    c_profiles = (cp or {}).get(tbl) or (cp or {}).get(tbl.lower()) or {}
                    row_count = getattr(t_profile, "row_count", None) if t_profile else None
                    grain_col = getattr(t_profile, "grain_column", None) if t_profile else None

                    row_str = f"{row_count:,} rows" if row_count else "? rows"
                    grain_str = f"grain={grain_col}" if grain_col else "grain=unknown"
                    grain_lines.append(f"  {tbl} ({row_str}, {grain_str})")

                    # Cardinality notes for columns with known profiles
                    for col_name, col_p in list(c_profiles.items())[:20]:
                        dc = getattr(col_p, "distinct_count", None)
                        is_fk = getattr(col_p, "is_fk", False)
                        sem = getattr(col_p, "semantic_type", "") or ""
                        if is_fk and dc is not None:
                            # FK column — record for join rule generation
                            fk_pairs.append((tbl, col_name, f"{dc:,} distinct"))
                            grain_lines.append(
                                f"    {col_name}: FK ({dc:,} distinct) → references another table's grain"
                            )
                        elif dc is not None and not getattr(col_p, "is_low_cardinality", False) and dc > 100:
                            # High-cardinality measure/ID — note the global distinct count
                            if sem in ("id", "foreign_key", "metric") or col_name.endswith("_id"):
                                grain_lines.append(f"    {col_name}: {dc:,} distinct values (global, not per row)")

                grain_block = ""
                if grain_lines:
                    grain_block = (
                        "TABLE GRAINS AND CARDINALITY — critical for correct SQL:\n"
                        + "\n".join(grain_lines)
                        + "\n"
                    )

                # Build join-safety rules from FK knowledge
                join_rules: list[str] = []
                # Also scan all join verifications for relevant relationships
                jv_all = self._state.get("join_verifications", [])
                for jv_entry in jv_all:
                    ft = jv_entry.get("from_table", "")
                    tt = jv_entry.get("to_table", "")
                    fc = jv_entry.get("from_col", "")
                    card = jv_entry.get("cardinality", "")
                    if ft in domain_tables or tt in domain_tables:
                        if "many" in card.lower() or card in ("N:1", "1:N", "N:M"):
                            join_rules.append(
                                f"  {ft} ↔ {tt} via {fc} ({card}): "
                                f"COUNT(*) after JOIN = rows in {ft}, NOT in {tt}. "
                                f"To count {tt} rows: COUNT(DISTINCT {tt}.grain_col)."
                            )

                # Always add the generic join-safety rule
                join_rules.insert(0, (
                    "  GENERAL: When JOINing a parent table to a child (one-to-many), COUNT(*) counts "
                    "child rows. To count parents use COUNT(DISTINCT parent.grain_column). "
                    "For per-parent averages, aggregate the child in a subquery first:\n"
                    "    SELECT parent_col, AVG(child_cnt) FROM parent\n"
                    "    JOIN (SELECT fk_col, COUNT(*) AS child_cnt FROM child GROUP BY fk_col) s\n"
                    "    ON parent.grain = s.fk_col GROUP BY parent_col\n"
                    "  NEVER do: COUNT(DISTINCT child.col) / COUNT(*) in a join — total-vs-total ratio.\n"
                    "  NEVER do: COUNT(DISTINCT col_a) / COUNT(DISTINCT col_b) — also a total-vs-total ratio.\n"
                    "  ALWAYS use subquery aggregation for per-parent averages:\n"
                    "    AVG(x_cnt) FROM (SELECT parent_id, COUNT(DISTINCT x) AS x_cnt FROM child GROUP BY parent_id) s\n"
                    "    JOIN parent ON parent.grain = s.parent_id"
                ))

                join_safety_block = (
                    "JOIN SAFETY RULES — read before writing any JOIN:\n"
                    + "\n".join(join_rules)
                    + "\n"
                ) if join_rules else ""

                # Build prior-phases context (phases 3-7 findings)
                prior_phases_lines: list[str] = []
                nm = self._state.get("null_meanings", {})
                if nm:
                    meaningful = {k: v for k, v in nm.items() if v.get("meaning") not in ("not_applicable", "unknown")}
                    if meaningful:
                        prior_phases_lines.append("NULL SEMANTICS (from Phase 3):")
                        for k, v in list(meaningful.items())[:8]:
                            prior_phases_lines.append(f"  {k.replace(':', '.')}: NULL = {v.get('meaning', '?')} ({v.get('null_rate', 0):.0%})")
                jv = self._state.get("join_verifications", [])
                if jv:
                    orphans = [j for j in jv if j.get("orphan_count", 0) > 0]
                    if orphans:
                        prior_phases_lines.append("JOIN ISSUES (from Phase 4):")
                        for j in orphans[:5]:
                            prior_phases_lines.append(f"  {j.get('key', '?')}: {j.get('orphan_count', 0)} orphan rows")
                lm = self._state.get("lifecycle_maps", {})
                if lm:
                    prior_phases_lines.append("LIFECYCLES (from Phase 5):")
                    for tbl, m in list(lm.items())[:5]:
                        prior_phases_lines.append(f"  {tbl}.{m.get('status_column', '?')}: {', '.join(m.get('active_states', [])[:4])} → {', '.join(m.get('terminal_states', [])[:3])}")
                prior_phases_block = "\n".join(prior_phases_lines) + "\n\n" if prior_phases_lines else ""

                # Step 1: Ask LLM what to investigate next (grain-aware, schema-grounded)
                # Run synchronous Ollama call in a thread so the event loop stays alive.
                try:
                    _sys1 = (
                        "You are a data analyst autonomously exploring a business database. "
                        "Propose exactly one SQL query that will reveal the most valuable business insight "
                        "for the given domain.\n\n"
                        "CRITICAL RULES:\n"
                        "1. Use ONLY the exact column names listed in EXACT COLUMN NAMES — never guess.\n"
                        "2. Write SELECT-only SQL with real aggregations and comparisons.\n"
                        "3. READ the JOIN SAFETY RULES before writing any JOIN. "
                        "After a one-to-many JOIN, COUNT(*) counts child rows, not parent rows. "
                        "Always use COUNT(DISTINCT parent.grain_col) to count parent entities. "
                        "For per-parent averages, subquery the child first.\n"
                        "4. BANNED PATTERN — never divide two COUNT(DISTINCT) values to express an average: "
                        "COUNT(DISTINCT child.col_a) / COUNT(DISTINCT parent.col_b) is ALWAYS wrong — "
                        "it gives total-A / total-B across the whole group, not the average A per B row. "
                        "The correct pattern for 'average X per parent' is: "
                        "AVG(x_count) FROM (SELECT parent_id, COUNT(DISTINCT x) AS x_count FROM child GROUP BY parent_id) sub. "
                        "This applies equally to COUNT(DISTINCT x) / COUNT(*) — both are banned.\n"
                        "5. RESPECT the TIME WINDOW in the user prompt — scope every query touching a "
                        "timestamped table to the specified date range. Trends, seasonality, and "
                        "growth metrics are only meaningful within a bounded, recent window."
                    )
                    time_window_block = ""
                    if self._time_window:
                        time_window_block = (
                            f"TIME WINDOW: Scope all queries to the last 12 months "
                            f"({self._time_window[0]} to {self._time_window[1]}). "
                            f"Add WHERE <timestamp_col> >= '{self._time_window[0]}' "
                            f"to every query that touches a timestamped table. "
                            f"This ensures trends and aggregations reflect recent data.\n\n"
                        )

                    _usr1 = (
                        f"DOMAIN: {domain}\n\n"
                        f"ENTITIES IN THIS DOMAIN:\n{entity_context}\n\n"
                        f"RELATIONSHIPS:\n{relationship_context}\n\n"
                        f"{domain_schema_block}\n\n"
                        f"{grain_block}\n"
                        f"{join_safety_block}\n"
                        f"{time_window_block}"
                        f"{prior_phases_block}"
                        f"COVERAGE ANGLES TO EXPLORE: {', '.join(uncovered)}\n"
                        f"ANGLES ALREADY COVERED: {', '.join(covered_angles) or 'none'}\n\n"
                        f"EXISTING FINDINGS FOR THIS DOMAIN:\n{existing_findings}\n\n"
                        "Propose the single most valuable next question. "
                        "Choose an uncovered angle. Write grain-correct SQL."
                    )
                    nq: _NextQuestion = await _loop.run_in_executor(
                        None,
                        lambda: llm.complete(system=_sys1, user=_usr1, response_model=_NextQuestion),
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
                    rows = await self._run(sql, think=label)
                    if rows is not None:
                        break
                    if attempt >= MAX_ATTEMPTS - 1:
                        logger.warning(
                            f"[explorer:{self.connection_id}] Phase 8: all {MAX_ATTEMPTS} attempts "
                            f"failed for {domain}/{nq.angle}"
                        )
                        break
                    error_msg = _last_episode_error()
                    fix = await _loop.run_in_executor(
                        None, lambda: sql_writer.fix(sql, error_msg, max_retries=1)
                    )
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

                # ── Sanity-check: detect impossible ratios before interpretation ──
                # If the SQL contains COUNT(DISTINCT ...) / COUNT(*) across a join,
                # the result may look like "2970 distinct sellers per 110k orders" when
                # 2970 is actually the global seller population — catch and skip.
                _skip_result = False
                try:
                    sql_upper = sql.upper()
                    has_join = "JOIN" in sql_upper
                    # Detect either banned ratio pattern:
                    #   COUNT(DISTINCT x) / COUNT(*)           — child vs all rows
                    #   COUNT(DISTINCT x) / COUNT(DISTINCT y)  — total-A / total-B
                    # Detect either banned ratio pattern (must have an actual division):
                    #   COUNT(DISTINCT x) / COUNT(*)           — child vs all rows
                    #   COUNT(DISTINCT x) / COUNT(DISTINCT y)  — total-A / total-B
                    import re as _re
                    _div_ratio_pat = _re.compile(
                        r"COUNT\s*\(\s*DISTINCT[^)]+\)"   # COUNT(DISTINCT x)
                        r"[\s\d.*]*"                       # optional multiplier/cast
                        r"/"                               # division
                        r"\s*COUNT\s*\(",                  # / COUNT(
                        _re.IGNORECASE,
                    )
                    has_distinct_div = bool(_div_ratio_pat.search(sql_upper))
                    if has_join and has_distinct_div:
                        # Check if any result value could be a spurious ratio:
                        # if a "distinct_X_count" cell value equals a known total cardinality
                        # for a global dimension column, the ratio is meaningless.
                        for row in rows[:5]:
                            for cell in row:
                                try:
                                    val = int(cell) if cell is not None else None
                                except (ValueError, TypeError):
                                    val = None
                                if val is None:
                                    continue
                                # Check against known global cardinalities from cp
                                for tbl_p, col_profiles in (cp or {}).items():
                                    for col_n, col_p in col_profiles.items():
                                        dc = getattr(col_p, "distinct_count", None)
                                        if dc and abs(val - dc) <= max(2, dc * 0.01):
                                            # Value equals a known global cardinality
                                            # Only flag if this looks like a "per-X" misread
                                            if col_n.endswith("_id") and not getattr(col_p, "is_low_cardinality", True):
                                                logger.info(
                                                    "[explorer:%s] Phase 8: skipping likely grain-confused result "
                                                    "— result cell %d matches global cardinality of %s.%s (%d). "
                                                    "SQL had JOIN+COUNT(DISTINCT)/COUNT(*).",
                                                    self.connection_id, val, tbl_p, col_n, dc,
                                                )
                                                _skip_result = True
                except Exception:
                    pass

                if _skip_result:
                    logger.info(
                        "[explorer:%s] Phase 8: %s/%s — result skipped (grain-confused ratio detected)",
                        self.connection_id, domain, nq.angle,
                    )
                    continue

                # Step 3: Interpret the result — run in thread to keep event loop live
                try:
                    _sys3 = (
                        "You are interpreting a SQL query result as a concise business insight. "
                        "Write 1-2 sentences maximum. Include specific numbers from the result. "
                        "Focus on what is actionable or surprising.\n\n"
                        "CRITICAL INTERPRETATION RULES:\n"
                        "- If a column is labelled 'distinct_X_count' in a grouped query, it is the "
                        "TOTAL distinct count of X across all rows in that group, NOT a per-row average. "
                        "Do NOT say 'X per Y' unless the SQL explicitly computed an average (AVG or ratio "
                        "from a subquery with per-grain counts).\n"
                        "- Only use ratio language ('per order', 'per customer') when the SQL computed "
                        "a genuine per-grain aggregation.\n"
                        "- Novelty score: 1=already known/trivial, 5=genuinely new and surprising."
                    )
                    _usr3 = (
                        f"DOMAIN: {domain}\n"
                        f"QUESTION: {nq.question}\n"
                        f"SQL:\n{sql}\n\n"
                        f"SQL RESULT (first 20 rows):\n{result_text}\n\n"
                        f"{grain_block}"
                        f"EXISTING FINDINGS FOR CONTEXT:\n{existing_findings}\n\n"
                        "Interpret this result as a business insight. "
                        "Be precise about what the numbers represent — do not invent per-row ratios "
                        "from total-level aggregations."
                    )
                    interp: _Interpretation = await _loop.run_in_executor(
                        None,
                        lambda: llm.complete(system=_sys3, user=_usr3, response_model=_Interpretation),
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
                    "canvas_id": self.canvas_id,
                    "promoted_to_org": False,
                    "promotion_confidence": 0.0,
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

                self._save_state()
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
