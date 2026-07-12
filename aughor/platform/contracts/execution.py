"""The query-execution result contract.

``QueryResult`` is what ``db.execute()`` and every connector return — so it must
live on the **platform** side, not inside the agent. Historically it was defined in
``aughor/agent/state.py``, which forced the data plane (``db`` / ``connectors``) to
``import`` the agent just to name a result — the wrong dependency direction for a
plug-and-play platform.

The type is a **hybrid** and deliberately kept whole (a clean move, zero behaviour
change):

  • **data-plane core** — ``sql``, ``columns``, ``rows``, ``row_count``, ``error`` —
    set by the executor / connectors;
  • **agent overlay** — ``hypothesis_id`` (an opaque audit/investigation label the
    platform already round-trips through the security gate), ``stats``,
    ``expected_if_true`` / ``expected_if_false`` — populated *post-hoc* by the
    investigation pipeline. The platform never reads these; it just carries them.

``aughor/agent/state.py`` re-exports both names, so existing agent imports
(``from aughor.agent.state import QueryResult``) are unchanged.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class StatResult(BaseModel):
    type: str
    interpretation: str
    is_significant: bool
    sigma: Optional[float] = None
    p_value: Optional[float] = None


class QueryResult(BaseModel):
    hypothesis_id: str
    sql: str
    columns: list[str]
    rows: list[list]
    row_count: int
    error: Optional[str] = None
    stats: list[StatResult] = Field(default_factory=list)
    # Predictions set at plan time; carried through for comparison at score time
    expected_if_true: Optional[str] = None
    expected_if_false: Optional[str] = None
    # Guard caveats the executor DETECTED but could not repair (value-disjoint join,
    # unbound filter literal, id-arithmetic, suspicious zero-row, E1 footguns). A
    # result that executed without error can still be silently wrong — this is the
    # channel that carries that knowledge to the caller instead of dropping it
    # (WP-1a: previously `execute_guarded`'s deterministic-only mode swallowed the
    # findings entirely). Additive: default [] keeps every existing consumer intact.
    caveats: list[str] = Field(default_factory=list)
