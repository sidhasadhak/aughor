"""
In-process stats registry for developer visibility.

Tracks counters and timings across key code paths — materializer cache,
ibis vs raw SQL, ACTION token expansions, tier gate firings, SQL correction
retries, prior-analysis RAG hits, and ontology enrichment.

Usage:
    from aughor.stats import stats
    stats.inc("materializer_hits")
    stats.timing("materializer_time_saved_ms", elapsed_ms)

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
        mat_hits = counters.get("materializer_hits", 0)
        mat_misses = counters.get("materializer_misses", 0)
        mat_total = mat_hits + mat_misses
        ibis_execs = counters.get("ibis_executions", 0)
        raw_execs = counters.get("raw_sql_executions", 0)
        rag_hits = counters.get("rag_hits", 0)
        rag_misses = counters.get("rag_misses", 0)
        corrections = counters.get("sql_correction_retries", 0)
        correction_ok = counters.get("sql_correction_successes", 0)

        return {
            "uptime_seconds": uptime_s,
            "counters": counters,
            "timings": timings,
            "derived": {
                "materializer_hit_rate": round(mat_hits / mat_total, 3) if mat_total else None,
                "ibis_usage_rate": round(ibis_execs / (ibis_execs + raw_execs), 3) if (ibis_execs + raw_execs) else None,
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
