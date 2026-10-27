"""Sheets — tables people make, edit, combine and chat with (Arc SH, ROADMAP §3.64; docs/SPREADSHEETS_ARC_2026-10-27.md).

**No new store of record.** A sheet is three things the platform already keeps:

- *its source* — the file a person brought, kept beside its typed rows (``files.py``), a query's or an answer's rows
  frozen when kept, or nothing for a blank sheet;
- *the changes people made to it* — edits in the edit layer (``aughor/actions/overlay.py``), which gained row grain for
  it: a cell set, a row added, a row removed, each with who, when, a version and the change it belongs to;
- *its definition* — name, columns, kinds, descriptions, links, totals and views, versioned on the platform's one
  versioning substrate (``kernel/lifecycle.py``), as a dashboard is.

**The table people read is a projection** (``projection.py``): the source with the changes applied, in a DuckDB file
per organisation, written only by the API process and rebuilt from source plus changes whenever it is missing or in
doubt. Its oracle — the table as changed equals a fresh rebuild — is the falsifier of SH-1.

To the rest of Aughor the sheets are one connection, *Sheets* (``connection.py``): the Catalog, the chat, dashboards
and the Briefing read them as they read any table.

Each wave is behind its own flag, off by default: ``sheets.core`` (SH-1: the sheets and their home), ``sheets.grid``
(SH-2: editing), ``sheets.chat`` (SH-4: the chat beside a sheet), ``sheets.combine`` (SH-7: links, totals, a newer
file, a query's rows kept) and ``sheets.views`` (SH-3: groups with their totals, boards, calendars, rules, views
kept to oneself). Off, no route answers, the Sheets connection is not listed and nothing is written.
"""
from __future__ import annotations

CORE = "sheets.core"
GRID = "sheets.grid"
CHAT = "sheets.chat"
COMBINE = "sheets.combine"
VIEWS = "sheets.views"


def on(flag: str = CORE) -> bool:
    """Whether a wave is on. Every wave stands on ``sheets.core``: with it off, none is."""
    from aughor.kernel.flags import flag_enabled
    if not flag_enabled(CORE):
        return False
    return flag == CORE or flag_enabled(flag)
