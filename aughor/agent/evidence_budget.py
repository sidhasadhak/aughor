"""Fresh-full / stale-stub evidence rendering (Wave R3) — pay each blob's context cost once.

Every query result in an investigation is rendered in full **twice**: once for the
``score_evidence`` step that interprets it into a hypothesis verdict, and again in the
synthesis block, which re-renders the entire history. By the second pass the raw table has
already produced its conclusion — the hypothesis carries a scored ``key_finding`` — and the
narrator is reading up to thirty rows of a table whose meaning is stated three lines above
it, for every query the run made.

So a result is rendered **fresh-full for the step that immediately follows it**, and a
**stale stub** thereafter. The stub is not a summary the model has to trust: it keeps the
SQL (provenance), the column names, the true row count, every statistical finding, and a
head of the actual rows. What it drops is the tail of a table that has already been read.

Two policies, deliberately separated because their risk is not the same:

* :func:`collapse_duplicates` is **lossless**. A result whose SQL exactly repeats an
  earlier one in the same block renders as a one-line pointer, because the identical table
  is already present. Nothing the narrator could cite disappears.
* :func:`stub_scored` **does** drop rows, so it is opt-in and its floor is honest: the
  saving is measured below, the effect on answer quality is **not**, and it should not
  graduate until Wave E4 can A/B it. A change that trades tokens against grounding is
  exactly what E4 exists to price, and "it looked fine" is not the standard this repo
  holds ([[verify-features-actually-ran]] — at small n, attribute causally).

Safe direction only, as in :mod:`aughor.agent.schema_focus`: below :data:`MIN_BLOCK_CHARS`
the block is returned untouched.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Iterable, Optional

logger = logging.getLogger(__name__)

#: Rows of the real table kept in a stub. Enough to name a concrete value and see the
#: shape; not enough to be the table again.
STUB_HEAD_ROWS = 4

#: Below this, render everything in full — a block this size is not straining anything,
#: and trimming it could only lose ground.
#:
#: Sized against a real run, not picked as a round number: a 5–7 hypothesis investigation
#: with 2–3 queries each renders roughly 12–20k characters here. A threshold above that
#: band would be a policy that never fires — which reads as "shipped" while doing nothing,
#: the exact failure the flag-graduation audit found 19 of. 12k matches
#: :data:`aughor.agent.schema_focus.FOCUS_MIN_CHARS` so the two Wave-R3 trims engage at
#: the same scale rather than at two unrelated magic numbers.
MIN_BLOCK_CHARS = 12_000


def enabled(flag: str) -> bool:
    """Flag read that fails safe to off — a flag-store hiccup must never silently trim
    evidence out of a synthesis prompt."""
    try:
        from aughor.kernel.flags import flag_enabled
        return flag_enabled(flag)
    except Exception:
        return False


def _fingerprint(result: Any) -> str:
    from aughor.agent.wandering import args_fingerprint

    return args_fingerprint(getattr(result, "sql", "") or "")


def stub(result: Any, *, head_rows: int = STUB_HEAD_ROWS, reason: str = "") -> str:
    """The stale form of one already-interpreted result.

    Keeps everything a narrator may legitimately cite — the SQL it came from, the columns,
    the true row count, every statistical finding, and the first ``head_rows`` real rows.
    Drops the tail. The row count is stated explicitly so the model cannot mistake the head
    for the whole table, which would turn a context saving into a wrong claim about
    coverage.
    """
    from aughor.util.format import round_cell
    from aughor.util.prompt_safety import cap_cell, fence_untrusted

    sql = getattr(result, "sql", "") or ""
    columns = list(getattr(result, "columns", []) or [])
    rows = list(getattr(result, "rows", []) or [])
    n = int(getattr(result, "row_count", len(rows)) or 0)

    lines = [f"SQL: {sql}", f"Rows returned: {n}"]
    if reason:
        lines.append(f"[{reason}]")
    if columns:
        col_str = " | ".join(cap_cell(c) for c in columns)
        table = [col_str, "-" * len(col_str)]
        for row in rows[:max(0, head_rows)]:
            table.append(" | ".join(cap_cell(round_cell(v)) for v in row))
        hidden = n - min(len(rows), max(0, head_rows))
        if hidden > 0:
            table.append(f"... ({hidden} more rows — the full table was read when this "
                         f"result was scored; the finding above is its conclusion)")
        lines.append(fence_untrusted("\n".join(table)))

    stats = list(getattr(result, "stats", []) or [])
    if stats:
        lines.append("")
        lines.append("STATISTICAL ANALYSIS:")
        for s in stats:
            marker = "⚠ SIGNIFICANT" if getattr(s, "is_significant", False) else "—"
            sigma = f" [{s.sigma:.1f}σ]" if getattr(s, "sigma", None) is not None else ""
            lines.append(f"  {marker}{sigma} {getattr(s, 'interpretation', '')}")
    return "\n".join(lines)


def duplicate_pointer(result: Any, prior_step: str) -> str:
    """The one-line form of a result whose identical table is already in this block."""
    return (f"SQL: {getattr(result, 'sql', '')}\n"
            f"[identical to the query already shown for {prior_step} — see that result; "
            f"it is not repeated here]")


def render_history(
    results: Iterable[Any],
    *,
    full_renderer: Callable[[Any], str],
    scored_steps: Optional[set] = None,
    collapse_duplicates: bool = True,
    stub_scored: bool = False,
    head_rows: int = STUB_HEAD_ROWS,
    seen: Optional[dict] = None,
) -> tuple[list[str], dict]:
    """Render each result at the right freshness. Returns ``(parts, info)``.

    ``scored_steps`` is the set of hypothesis ids whose findings were already interpreted —
    only those are eligible to go stale. A result belonging to an unscored (or unknown)
    hypothesis is always rendered full, because nothing else in the prompt carries its
    meaning yet.

    ``seen`` is the caller's fingerprint accumulator, and passing it is what makes
    duplicate-collapse work at all when the block is assembled in pieces: the synthesis
    prompt renders one section per hypothesis, so a purely local ``seen`` resets between
    sections and catches only same-section repeats — the rarest kind. Mutated in place.

    ``info`` reports ``{"full": n, "stubbed": n, "duplicates": n}`` so the effect is a
    number rather than a claim.
    """
    parts: list[str] = []
    info = {"full": 0, "stubbed": 0, "duplicates": 0}
    seen = {} if seen is None else seen
    scored = scored_steps or set()

    for r in results:
        step = getattr(r, "hypothesis_id", "") or ""
        fp = _fingerprint(r) if collapse_duplicates else ""
        if fp and fp in seen and not getattr(r, "error", None):
            parts.append(duplicate_pointer(r, seen[fp]))
            info["duplicates"] += 1
            continue
        if fp:
            seen[fp] = step or "an earlier step"
        if stub_scored and step in scored and not getattr(r, "error", None):
            parts.append(stub(r, head_rows=head_rows,
                              reason=f"already interpreted when {step} was scored"))
            info["stubbed"] += 1
            continue
        parts.append(full_renderer(r))
        info["full"] += 1
    return parts, info
