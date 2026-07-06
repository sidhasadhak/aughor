"""
In-process stats registry for developer visibility.

Tracks counters and timings across key code paths — ACTION token expansions,
tier gate firings, SQL correction retries, prior-analysis RAG hits, and
ontology enrichment.

Exposed via GET /dev/stats.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict
from typing import Any


class _Stats:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, int] = defaultdict(int)
        self._timings_sum: dict[str, float] = defaultdict(float)
        self._timings_count: dict[str, int] = defaultdict(int)
        self._started_at = time.time()

    def inc(self, key: str, n: int = 1) -> None:
        with self._lock:
            self._counters[key] += n

    def timing(self, key: str, ms: float) -> None:
        with self._lock:
            self._timings_sum[key] += ms
            self._timings_count[key] += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            counters = dict(self._counters)
            timings = {
                k: {
                    "total_ms": round(self._timings_sum[k], 1),
                    "count": self._timings_count[k],
                    "avg_ms": round(self._timings_sum[k] / self._timings_count[k], 1)
                    if self._timings_count[k] > 0 else 0,
                }
                for k in self._timings_sum
            }
        uptime_s = int(time.time() - self._started_at)

        # Derived convenience metrics
        rag_hits = counters.get("rag_hits", 0)
        rag_misses = counters.get("rag_misses", 0)
        corrections = counters.get("sql_correction_retries", 0)
        correction_ok = counters.get("sql_correction_successes", 0)

        return {
            "uptime_seconds": uptime_s,
            "counters": counters,
            "timings": timings,
            "derived": {
                "rag_hit_rate": round(rag_hits / (rag_hits + rag_misses), 3) if (rag_hits + rag_misses) else None,
                "sql_correction_success_rate": round(correction_ok / corrections, 3) if corrections else None,
            },
        }

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._timings_sum.clear()
            self._timings_count.clear()
            self._started_at = time.time()


# Module-level singleton — import this everywhere
stats = _Stats()


def bump(counter: str, n: int = 1) -> None:
    """Fail-safe counter increment for guard/safety code paths.

    The deterministic guards run inside fail-open pipelines where an
    observability call must never be able to break the query path — this is the
    shared version of the `_bump` pattern (sql/safety.py) for all guard modules,
    so guard fire/repair rates are measurable at GET /dev/stats instead of
    invisible."""
    try:
        stats.inc(counter, n)
    except Exception:
        # No trail by design: this IS the trail mechanism — a failing counter
        # increment has nowhere sane to report (tolerate() itself increments a
        # counter) and must never break a guard path.
        return
