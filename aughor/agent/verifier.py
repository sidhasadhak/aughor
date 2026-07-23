"""The Verifier — the ADA specialist that owns the deterministic trust verdict over a
phase's queries.

Inside every ADA phase the micro-cycle is SQL-Engineer → **Verifier** → Narrator
(see [handoff.py]). The Verifier's job is the deterministic part of trust: detect the
plausible-wrong shapes (fan-out across a chasm, id-arithmetic, ratio-of-sums) the same
``/chat`` path guards, and give each execution failure the R3 typed class
(``parser | binder | semantic | runtime``) that routes repair. Extracted from
``run_analysis_phase`` so verification is a NAMED, owned, testable unit the Fleet view and
the Trust Receipt can speak to — without changing the phase's re-plan/repair control flow
(that stays the SQL-Engineer's job).

Stateless and pure: ``scan`` and ``classify_failures`` are safe to call repeatedly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


# The caveat carried downstream when a fan-out can't be re-planned away — so a magnitude
# the Verifier still distrusts is never presented as trustworthy. Owned here, used by the phase.
FANOUT_CAVEAT = (
    "The metric is aggregated across a fan-out join (a one-to-many join multiplies "
    "the rows being summed), so the magnitudes below are likely inflated and the "
    "ranking may be volume-weighted rather than reflecting the true per-group total — "
    "treat these numbers as directional only."
)


@dataclass
class VerifierVerdict:
    """The Verifier's structured verdict over one phase's queries."""
    fanout_hits: list = field(default_factory=list)        # list[str] prompt-hints (de-duped)
    error_classes: list = field(default_factory=list)      # distinct typed classes of failed queries
    caveats: list = field(default_factory=list)            # list[str]
    passed: bool = True

    def summary(self) -> dict:
        return {"fanout_hits": len(self.fanout_hits), "error_classes": self.error_classes,
                "caveats": self.caveats, "passed": self.passed}


class Verifier:
    """Deterministic trust checks over a phase's engineered queries."""

    @staticmethod
    def scan(queries: Any, table_cols: dict, dialect: str) -> list:
        """Fan-out / id-arithmetic / ratio-of-sums hits across the planned queries — the
        deterministic detection battery (the same five detectors the phase ran inline),
        returning de-duped prompt-hint strings. First hit per query wins (one correction
        per query is enough)."""
        from aughor.sql.fanout import (
            sum_over_chasm_fanout, avg_over_chasm_fanout, count_star_chasm_fanout,
            measure_times_key_arithmetic, avg_of_row_ratios, dimension_ratio_chasm,
            group_by_outer_null_side,
        )

        def _dim_ratio_hint(sql, tc, d):
            # The cross-table dimension-join ratio the FK-root chasm guards miss (#159).
            f = dimension_ratio_chasm(sql, tc, d)
            return f.to_prompt_text() if f else None

        battery = (sum_over_chasm_fanout, avg_over_chasm_fanout, count_star_chasm_fanout,
                   measure_times_key_arithmetic, avg_of_row_ratios, _dim_ratio_hint,
                   group_by_outer_null_side)
        hits: list[str] = []
        for q in (queries or []):
            sql = getattr(q, "sql", "") or (q if isinstance(q, str) else "")
            for det in battery:
                h = det(sql, table_cols, dialect)
                if h:
                    hits.append(h)
                    break
        return list(dict.fromkeys(hits))   # de-dupe, preserve order

    @staticmethod
    def classify_failures(results: Any, dialect: str) -> list:
        """``(title, error_class)`` for each query that errored — the R3 typed signal that
        routes repair. ``results`` is the phase's ``[(plan_query, exec_result), …]``."""
        from aughor.tools.error_classifier import classify_error_type
        out: list[tuple] = []
        for item in (results or []):
            q, r = item if isinstance(item, (tuple, list)) and len(item) == 2 else (None, item)
            err = getattr(r, "error", None)
            if err:
                cls = classify_error_type(err, getattr(r, "sql", "") or "", dialect)
                out.append((getattr(q, "title", "") or "", getattr(cls, "value", str(cls))))
        return out

    @classmethod
    def verdict(cls, queries: Any, results: Any, *, table_cols: dict, dialect: str,
                fanout_caveat: Optional[str] = None) -> VerifierVerdict:
        """The full verdict — fan-out hits + typed failure classes + caveats + a pass flag."""
        hits = cls.scan(queries, table_cols, dialect)
        failures = cls.classify_failures(results, dialect)
        error_classes = list(dict.fromkeys(ec for _, ec in failures))
        caveats = [c for c in [fanout_caveat] if c]
        ok = any(not getattr((r[1] if isinstance(r, (tuple, list)) else r), "error", None)
                 for r in (results or []))
        return VerifierVerdict(fanout_hits=hits, error_classes=error_classes,
                               caveats=caveats, passed=ok)
