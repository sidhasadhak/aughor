"""R6 — per-workspace compute isolation: a DuckDB "lane" per workspace.

A noisy workspace can tax its neighbours two ways:
  * RESOURCE — one heavy DuckDB query can grab all of the host's RAM / CPU threads.
  * CONCURRENCY — a workspace firing many runs at once can monopolise the shared
    executor and starve other workspaces' cheap requests.

A *lane* bounds both, per workspace:
  * a DuckDB **resource envelope** — ``PRAGMA memory_limit`` + ``threads`` applied when
    the workspace's connections open, so its queries run inside a fixed compute budget; and
  * a bounded **concurrency gate** — a semaphore so a workspace runs at most N heavy
    phases at once; excess work queues instead of piling onto the event loop.

Resolved per workspace via ``workspace_for_connection``, from app-level env defaults plus
an optional per-workspace ``settings_override["compute"]``. Everything here is fail-open:
if the workspace can't be resolved, the global default lane applies — a lane never blocks
or breaks a run. **No-op at defaults** — the resource PRAGMAs are only emitted when an
operator configures a limit, so an unconfigured deployment behaves exactly as before.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

_GLOBAL = "__global__"


@dataclass(frozen=True)
class LaneConfig:
    """One workspace's compute envelope. Defaults are permissive — ``memory_limit``/``threads``
    empty means *leave DuckDB's own default*, so nothing is emitted unless configured."""
    max_concurrency: int = 2
    memory_limit: str = ""      # e.g. "2GB"; "" → don't set (DuckDB default)
    threads: int = 0            # 0 → don't set (DuckDB default)

    @classmethod
    def default(cls) -> "LaneConfig":
        # Concurrency default tracks the historical explorer cap so a single-workspace
        # deployment is unchanged; resource limits are opt-in (empty/0 = unset).
        return cls(
            max_concurrency=max(1, _int_env("AUGHOR_LANE_MAX_CONCURRENCY",
                                            _int_env("AUGHOR_MAX_CONCURRENT_EXPLORERS", 2))),
            memory_limit=os.getenv("AUGHOR_LANE_MEMORY_LIMIT", "").strip(),
            threads=max(0, _int_env("AUGHOR_LANE_THREADS", 0)),
        )

    def merged_with(self, override: Optional[dict]) -> "LaneConfig":
        """Apply a per-workspace ``settings_override['compute']`` dict over these defaults."""
        if not override or not isinstance(override, dict):
            return self
        return LaneConfig(
            max_concurrency=max(1, int(override.get("max_concurrency", self.max_concurrency) or self.max_concurrency)),
            memory_limit=str(override.get("memory_limit", self.memory_limit) or self.memory_limit).strip(),
            threads=max(0, int(override.get("threads", self.threads) or self.threads)),
        )

    def pragmas(self) -> list:
        """The SET statements that apply this envelope to a fresh DuckDB connection."""
        out: list = []
        if self.memory_limit:
            out.append(f"SET memory_limit='{self.memory_limit}'")
        if self.threads > 0:
            out.append(f"SET threads={self.threads}")
        return out


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)) or default)
    except (TypeError, ValueError):
        return default


class WorkspaceLane:
    """The live lane for one workspace — its config + a lazily-created concurrency semaphore.

    The semaphore is created on first use inside the running event loop (asyncio.Semaphore
    must bind to a loop), mirroring the explorer's existing lazy pattern."""

    def __init__(self, workspace_id: str, config: LaneConfig):
        self.workspace_id = workspace_id
        self.config = config
        self._sem: "asyncio.Semaphore | None" = None

    def semaphore(self) -> "asyncio.Semaphore":
        if self._sem is None:
            self._sem = asyncio.Semaphore(self.config.max_concurrency)
        return self._sem

    @asynccontextmanager
    async def gate(self):
        """``async with lane.gate():`` — hold one of the workspace's concurrency slots for
        the duration of a heavy phase. Excess callers queue here rather than on the loop."""
        sem = self.semaphore()
        await sem.acquire()
        try:
            yield self
        finally:
            sem.release()

    def apply_envelope(self, duck_conn) -> None:
        """Emit this lane's resource PRAGMAs onto a fresh DuckDB connection. No-op when the
        envelope is unset (the default). Fail-open — never breaks the connection open."""
        for stmt in self.config.pragmas():
            try:
                duck_conn.execute(stmt)
            except Exception as exc:  # noqa: BLE001
                logger.debug("lane %s: could not apply '%s': %s", self.workspace_id, stmt, exc)


# ── Registry — one lane per workspace, memoized ──────────────────────────────────

_lanes: dict = {}
_lanes_lock = threading.Lock()


def _config_for_workspace(workspace_id: str) -> LaneConfig:
    base = LaneConfig.default()
    if not workspace_id or workspace_id == _GLOBAL:
        return base
    try:
        from aughor.workspace.store import get_workspace
        ws = get_workspace(workspace_id)
        override = getattr(ws, "settings_override", None) if ws else None
        compute = (override or {}).get("compute") if isinstance(override, dict) else None
        return base.merged_with(compute)
    except Exception as exc:  # noqa: BLE001 — fail-open to the default envelope
        logger.debug("lane config for workspace %s fell back to default: %s", workspace_id, exc)
        return base


def lane_for_workspace(workspace_id: Optional[str]) -> WorkspaceLane:
    key = workspace_id or _GLOBAL
    with _lanes_lock:
        lane = _lanes.get(key)
        if lane is None:
            lane = WorkspaceLane(key, _config_for_workspace(key))
            _lanes[key] = lane
        return lane


def lane_for_connection(conn_id: str) -> WorkspaceLane:
    """Resolve the lane that owns ``conn_id`` (its workspace), falling back to the global
    default lane when the connection isn't pinned to a specific workspace."""
    ws_id = ""
    try:
        from aughor.workspace.store import workspace_for_connection
        ws = workspace_for_connection(conn_id)
        ws_id = getattr(ws, "id", "") if ws else ""
    except Exception as exc:  # noqa: BLE001 — fail-open to the global lane
        logger.debug("lane_for_connection(%s) fell back to global: %s", conn_id, exc)
    return lane_for_workspace(ws_id)


def reset_lanes() -> None:
    """Drop the memoized lanes (tests / config reload)."""
    with _lanes_lock:
        _lanes.clear()
