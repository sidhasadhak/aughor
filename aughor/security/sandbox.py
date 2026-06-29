"""Query budget — per-connection execution limits.

Enforced inside DatabaseConnection.execute() after the query runs.
Limits are applied in this order:
  1. Row cap   — result truncated to max_rows silently (warning added to result)
  2. Time warn — if elapsed > warn_time_ms a warning is logged (query already ran)

Per-connection budgets override the default. The registry lives in-memory;
restart resets any overrides (they can be re-applied via the API or config).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class QueryBudget:
    """Limits applied to every execute() call for a connection."""

    # Maximum rows returned before the result is hard-truncated.
    max_rows: int = 10_000

    # Execution time in ms above which the query is flagged as slow.
    # NOTE: we cannot *cancel* an already-running query without connection-level
    # support; this is a post-hoc warning rather than a preemptive limit.
    warn_time_ms: float = 15_000

    # Hard wall-clock limit in ms — same caveat as above; used for audit tagging.
    max_time_ms: float = 60_000

    def check_rows(self, row_count: int) -> str | None:
        """Return warning message if row_count exceeds cap, else None."""
        if row_count > self.max_rows:
            return (
                f"Result capped at {self.max_rows:,} rows "
                f"(query returned ≥{row_count:,})"
            )
        return None

    def check_time(self, elapsed_ms: float) -> str | None:
        """Return warning message if elapsed exceeds threshold, else None."""
        if elapsed_ms > self.max_time_ms:
            return f"Query exceeded time limit ({elapsed_ms:.0f}ms > {self.max_time_ms:.0f}ms)"
        if elapsed_ms > self.warn_time_ms:
            return f"Slow query: {elapsed_ms:.0f}ms"
        return None


# Default budget used when no connection-specific override is set
DEFAULT_BUDGET = QueryBudget()

# In-memory registry: connection_id → QueryBudget
_REGISTRY: dict[str, QueryBudget] = {}


def get_budget(connection_id: str) -> QueryBudget:
    """Return the budget for a connection, falling back to the default."""
    return _REGISTRY.get(connection_id, DEFAULT_BUDGET)


def set_budget(connection_id: str, budget: QueryBudget) -> None:
    """Override the budget for a specific connection."""
    _REGISTRY[connection_id] = budget


def list_budgets() -> dict[str, dict]:
    """Return all non-default budgets as plain dicts (for API serialisation)."""
    return {
        conn_id: {
            "max_rows":     b.max_rows,
            "warn_time_ms": b.warn_time_ms,
            "max_time_ms":  b.max_time_ms,
        }
        for conn_id, b in _REGISTRY.items()
    }
