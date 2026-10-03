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
from typing import Optional

from aughor.answer import exhibit
from aughor.answer.envelope import AnswerEnvelope, ChartDecision, Grid

#: Slack's ENCODINGS — the only part of a table this door owns (CP-5). The TypeScript mention
#: bot sends the same three numbers to `POST /exhibits/table`, so both Slack doors draw one table.
#: Past this many columns a Slack table wraps into an unreadable block.
MAX_INLINE_COLS = 6
#: Past this many rows a thread turns into a spreadsheet nobody scrolls.
MAX_INLINE_ROWS = 10
#: How much of an oversized grid to preview.
PREVIEW_ROWS = 5
#: A thread reads two caveats; the rest are in the report.
MAX_CAVEATS = 2


def worth_showing(grid: Optional[Grid]) -> bool:
    """A one-number result is already in the sentence above it (`exhibit.worth_showing`)."""
    return grid is not None and exhibit.worth_showing(grid.columns, grid.rows)


def render_grid_markdown(grid: Grid, *, money_symbol: str = "") -> str:
    """The grid for a thread, by the one table builder — whole when narrow and short, a
    captioned preview when long, a caption alone when wide."""
    if grid.empty:
        return ""
    return exhibit.reader_table(grid.columns, grid.rows, max_cols=MAX_INLINE_COLS,
                                max_rows=MAX_INLINE_ROWS, preview_rows=PREVIEW_ROWS,
                                rest="the full result is in the report",
                                money_symbol=money_symbol).markdown


@dataclass
class SlackSelection:
    text: str
    table: str = ""
    caveats: list[str] = field(default_factory=list)
    grid: Optional[Grid] = None
    chart: Optional[ChartDecision] = None


def select_for_slack(env: AnswerEnvelope, *, money_symbol: str = "") -> SlackSelection:
    """Headline + body + the grid once + the top caveats. Nothing else."""
    text = "\n\n".join(p for p in (env.headline.strip(), env.body.strip()) if p)
    if env.error and not text:
        text = f"⚠️ {env.error}"
    grid = env.grid if worth_showing(env.grid) else None
    return SlackSelection(
        text=text,
        table=render_grid_markdown(grid, money_symbol=money_symbol) if grid is not None else "",
        caveats=list(env.caveats[:MAX_CAVEATS]),
        grid=grid,
        chart=env.chart if grid is not None else None,
    )


def slack_message(env: AnswerEnvelope, *, money_symbol: str = "") -> str:
    """One string for a door that posts raw text (`post_as_bot`). Slack renders no
    markdown table, so the grid rides in a fenced block — an encoding, local to this door."""
    sel = select_for_slack(env, money_symbol=money_symbol)
    parts = [sel.text]
    if sel.table:
        parts.append(f"```\n{sel.table}\n```")
    parts.extend(f"⚠️ {c}" for c in sel.caveats)
    return "\n\n".join(p for p in parts if p).strip()
