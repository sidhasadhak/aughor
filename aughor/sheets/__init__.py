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

The waves are part of the platform (ROADMAP §3.65): SH-1 (the sheets and their home), SH-2 (editing), SH-3 (groups
with their totals, boards, calendars, rules, views kept to oneself), SH-4 (the chat beside a sheet), SH-5 (a column a
model writes for the rows of a view, ``model_columns.py``), SH-6 (its first piece: a dashboard made from a sheet),
SH-7 (links, totals, a newer file, a query's rows kept) and SH-8 (a sheet shared with chosen people and groups,
``sharing.py``).
"""
from __future__ import annotations
