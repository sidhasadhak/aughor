"""Arc CP · CP-4 — what each door SELECTS from the envelope.

Selection is policy and belongs beside the envelope so every Python door reads the same
rule; encodings (a fenced block for a raw `chat.postMessage`, a CSV attachment where the
transport can carry one) stay with the door that has the transport.

Slack takes the headline, the body, the grid once, and the top caveats. It takes NO
provenance — the user's 2026-09-22 rule that Slack messages carry no receipts is a rule
about which FIELD a door shows, and this is where it is applied on the Python side (the
TypeScript mention bot applies the same selection in `bots/slack/src/bot.ts`).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from aughor.answer.envelope import AnswerEnvelope, ChartDecision, Grid

#: Past this many columns a Slack table wraps into an unreadable block (`artifacts.ts`).
MAX_INLINE_COLS = 6
#: Past this many rows a thread turns into a spreadsheet nobody scrolls.
MAX_INLINE_ROWS = 10
#: How much of an oversized grid to preview.
PREVIEW_ROWS = 5
#: A thread reads two caveats; the rest are in the report.
MAX_CAVEATS = 2


def _cell(v: Any) -> str:
    if v is None:
        return ""
    return str(v).replace("|", "\\|").replace("\n", " ")


def gfm_table(grid: Grid) -> str:
    if not grid.columns:
        return ""
    head = "| " + " | ".join(_cell(c) for c in grid.columns) + " |"
    rule = "| " + " | ".join("---" for _ in grid.columns) + " |"
    body = ["| " + " | ".join(_cell(r[i] if i < len(r) else "") for i in range(len(grid.columns))) + " |"
            for r in grid.rows]
    return "\n".join([head, rule, *body])


def worth_showing(grid: Optional[Grid]) -> bool:
    """A one-number result is already in the sentence above it; a grid earns its place by
    having a shape — more than one row, or enough columns to be a breakdown."""
    if grid is None or grid.empty:
        return False
    return len(grid.rows) > 1 or len(grid.columns) > 2


def fits_inline(grid: Grid) -> bool:
    return 0 < len(grid.columns) <= MAX_INLINE_COLS and len(grid.rows) <= MAX_INLINE_ROWS


def render_grid_markdown(grid: Grid) -> str:
    """The grid for a thread: whole when narrow and short, a captioned preview when long,
    a caption alone when wide — and the caption always says which one happened."""
    if grid.empty:
        return ""
    if fits_inline(grid):
        return gfm_table(grid)
    n, m = len(grid.rows), len(grid.columns)
    if m > MAX_INLINE_COLS:
        return f"_{n} row{'' if n == 1 else 's'} × {m} columns — the full result is in the report._"
    shown = min(PREVIEW_ROWS, n)
    preview = Grid(columns=grid.columns, rows=grid.rows[:shown])
    return f"{gfm_table(preview)}\n\n_Showing {shown} of {n} rows — the full result is in the report._"


@dataclass
class SlackSelection:
    text: str
    table: str = ""
    caveats: list[str] = field(default_factory=list)
    grid: Optional[Grid] = None
    chart: Optional[ChartDecision] = None


def select_for_slack(env: AnswerEnvelope) -> SlackSelection:
    """Headline + body + the grid once + the top caveats. Nothing else."""
    text = "\n\n".join(p for p in (env.headline.strip(), env.body.strip()) if p)
    if env.error and not text:
        text = f"⚠️ {env.error}"
    grid = env.grid if worth_showing(env.grid) else None
    return SlackSelection(
        text=text,
        table=render_grid_markdown(grid) if grid is not None else "",
        caveats=list(env.caveats[:MAX_CAVEATS]),
        grid=grid,
        chart=env.chart if grid is not None else None,
    )


def slack_message(env: AnswerEnvelope) -> str:
    """One string for a door that posts raw text (`post_as_bot`). Slack renders no
    markdown table, so the grid rides in a fenced block — an encoding, local to this door."""
    sel = select_for_slack(env)
    parts = [sel.text]
    if sel.table:
        parts.append(f"```\n{sel.table}\n```")
    parts.extend(f"⚠️ {c}" for c in sel.caveats)
    return "\n\n".join(p for p in parts if p).strip()
