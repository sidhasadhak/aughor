# Arc SH — Sheets: tables people make, edit, combine and chat with (drafted and adopted 2026-10-27)

**The ask.** The user, 2026-10-27, after Teable was dropped (`docs/TEABLE_STUDY_2026-10-26.md`):

> *"my point is that within our platform users should be able to work with spreadsheets the way screenshots suggest..
> Is it really so hard to incorporate it in our platform?"*

The screenshots show a table a person made from an Excel file:
- a typed grid of 110 records, with status chips, check boxes, dates and amounts;
- views as tabs: grouped, a board, filtered, a calendar;
- a toolbar: add, hidden fields, filter, sort, group, search, undo, redo, share;
- a chat panel beside it that turned the Excel file into the table, made the views, flagged 37 rows and filled a
  summary column.

The user's earlier message named three things as Teable's strengths: custom apps, combining Excel, CSV and connectors,
and the chat. Then: *"write the spreadsheet arc (steps, sizes, the calls) and mock up the Spreadsheets page on real data
before anything is built"*.

Asked *"Is something missing?"*, ten gaps were named. The user asked for them all to be folded in: backups first,
combining, the Spreadsheets home, a sheet made by the chat, the AI column, totals, a record view and sharing.

**Status.** ✅ **Adopted 2026-10-27** — ROADMAP §3.64 and §6 item 56, all ten calls as recommended (§5), with Arc
SV's SV-1 and SV-2 first (§3.63). The user: *"The ten-screen Spreadsheets mockup looks right — take the ten calls as
recommended and adopt Arc SH (with SV-1/SV-2 first) into the roadmap."* Nothing built. PENDING 66.

**The mockup.** `design-mockups/spreadsheets.html`, ten screens. Every row is the uploaded Olist files in the Workspace
connection: orders, customers, payments and reviews. They were read with the reader the upload door uses
(`read_csv_auto`), read-only. Olist's money is in reais (R$), the currency the Olist workspace already carries.

---

## 1. The premise, measured

**What Aughor already has:**
- **A file becomes a table.** The upload door reads CSV, TSV, Parquet, XLSX, XLS and JSON
  (`connectors/file/local_upload.py:84-96`). The Olist orders file reads as 99,441 rows in 8 typed columns, and every
  value in its five date columns reads back exactly as written.
- **A grid.** The SQL editor's `ResultsGrid` is TanStack Table v9 with virtual scrolling, sort, column sizing, typed
  nulls and copy. It is read-only. The component-library study chose it as the house's one grid.
- **Edits with history.** The edit layer (`actions/overlay.py`) keeps a person's change to a cell, with who, when, a
  version (a stale write is refused), a history row per save and withdrawal, and the run that made it. It cannot add a
  row or a column.
- **A rule that names rows.** Business rules and segments are declared and counted by code.
- **A chat beside a screen.** *Ask this briefing* is a 420 px side panel grounded server-side in the screen. The side
  assistant for every screen is parked (ROADMAP §3.61).
- **A model over rows, capped.** The semantic operators (`semops/operators.py:31-32`) refuse above 200 rows unless
  overridden, and fill 25 rows per model call.
- **Dashboards, with an App builder (Arc AP).** This is the Aughor answer to Teable's "custom apps", which run generated
  code on hosted servers and were refused here (§6 item 50(d)).

**What it does not have:**
- **A table Aughor owns and people change.** An upload is rebuilt in memory from its files whenever they change
  (`_materialize`), so an edit written into it would vanish.
- **A backup of anything.** 46 SQLite stores and no scheduled copy (the Grist study §3). Today every store holds
  something Aughor could re-derive or re-read. A sheet changes that: what people type exists nowhere else.
- **Adding rows and columns, typed editing in a grid, column totals.**
- **Saved views:** grouped, board or calendar.
- **Opening a row as a record.**
- **Combining:** linking two tables a person brought, rolling one up into the other, adding next month's file.
- **A chat that makes or changes the table on screen.**

**A measurement that changed a figure.** "Arrived late" first compared a delivery's *time* with an estimated *date*
held at midnight. That counted 1,292 orders delivered on their estimated day as late.

By calendar day, 6,535 orders arrived late (not 7,827), with a median delay of 7 days, not 5. A sheet's rules compare
like with like; SH-1's kinds keep a Date apart from a Date & time for exactly this reason.

**Where it goes.** One row in the rail's Data group, under Catalog, SQL Editor and Semantic Layer
(`web/app/page.tsx:328-335`). ROADMAP §4.10 adds a row only where the rail fits at 1440×900:
- **The measurement then.** It found room for two more on 2026-10-05, when the rail had 18 rows (`33d414f6`).
- **Since then.** Ontology took one on 2026-10-09.
- **So Spreadsheets would take the last.** It is measured again on the live app before it is built, because the look
  change of 2026-10-25 (#627) altered row spacing.

---

## 2. The model — no new store of record

- **A sheet is its source plus the changes people made to it.**
  - *The source* is the file a person brought (kept as the upload door keeps files), a query's or an answer's rows
    frozen when kept, or nothing for a blank sheet. An imported value names its source: the file and its row.
  - *The changes* are edits in the edit layer, gaining row grain (a row added, a row removed, superseded never
    deleted). Each carries who, when, a version, and, for the assistant's, the proposal and the person who applied it.
  - *The definition* is the sheet's name, columns, kinds, descriptions, links, views and rules. It is versioned on the
    platform's one versioning substrate (`kernel/lifecycle.py`), as a dashboard is.
- **The table people read is a projection.** It is the source with accepted changes applied, materialized in a DuckDB
  file per workspace. Only the API process writes it, and it is rebuilt from source plus changes whenever it is missing
  or in doubt. The Grist study's oracle tests it: the materialized table must equal a fresh rebuild.
- **A link is a declaration, not a copy.** A column that reads another sheet by a key, or a total of the other sheet's
  rows for each key, is computed in the projection. Change the other sheet and the linked column follows.
- **To the rest of Aughor, the sheets are one connection,** *Sheets*. The Catalog, the chat, the ontology explorer,
  dashboards and the Briefing read them as they read any table.

---

## 3. The waves

**SH-0 is a precondition, not a wave of this arc: Arc SV-1 and SV-2 come first** (the Grist study §3):
- a labelled backup before every migration;
- verified backups kept on a schedule.

People's typing will live in the edit layer and the definitions on the lifecycle; both must be backed up before the
first sheet holds a value nobody can re-import. *The falsifier:* a sheet's change written with no backup taken within
the hour stops SH-1's release.

| # | Builds | Flag (off) · size | Falsifier |
|---|---|---|---|
| **SH-1** | **Sheets Aughor keeps, and their home.** <br>• *Spreadsheets* lists the workspace's sheets: rows, columns, where each came from, who changed it last. <br>• *New sheet* takes a file (CSV, TSV, Parquet, JSON; an Excel workbook becomes one sheet per tab, each named), starts blank, or keeps a query's or a chat answer's rows. <br>• The files already uploaded are offered as the place to start. <br>• Kinds are set at import (the list below), each checked. <br>• Removing a sheet writes its tombstone first. <br>• A glossary row: *Sheet* (Google's stay *Google Sheet*). | `sheets.core` · M–L | The materialized table differs from a fresh rebuild → stop |
| **SH-2** | **The grid.** <br>• Edit a typed cell in place; add a row or a column; hide, sort, filter, group and search. <br>• Each cell has its history: imported from file row *N*, or set by whom and when. <br>• Undo and redo are the changes' own history; a stale edit is refused. <br>• **Totals at the foot**: count, sum, average, earliest and latest, per column, over the rows the view shows. <br>• **A description on each column**, shown on its header. <br>• **Open a row as a record**: a drawer with every field and its source, its linked rows, its history, and comments. <br>• Rows are 30 px; Copy and CSV. | `sheets.grid` · L | An edit made in the grid is not what the chat's next read of the same cell returns → stop |
| **SH-4** | **The chat beside the sheet.** <br>• It is grounded server-side in the sheet and view on screen, and answers through a query on the Sheets connection, with its receipt. <br>• **It makes a sheet from a file dropped into it**: it proposes the name, the kinds, a few views and a rule for rows that need attention, as one card. <br>• It **proposes** changes to a sheet: a view, a computed column, a yes/no column, a rule, a link. <br>• A person applies all or part; each change is recorded as proposed by the assistant and applied by the person. | `sheets.chat` · M | A chat answer about a sheet differs from the grid's own count of the same rows → stop |
| **SH-7** | **Combining.** <br>• *Link* a column to another sheet by a key: every match and every miss counted before it is kept. <br>• *Total* the other sheet's rows per key (sum, count, latest), e.g. an order's payments. <br>• *Add a newer file* to a sheet: a keyed merge, shown first as every row added and every cell changed, then applied as one change that can be undone (the Grist study §6). <br>• *Keep a query's rows as a sheet*, from the SQL editor or a chat answer. | `sheets.combine` · M–L | A linked total differs from the same total computed by SQL over the two sheets → stop |
| **SH-3** | **Views.** A saved grid (filter, sort, group with group totals, hidden fields); a board by a choice column, where moving a card is an edit; a calendar by a date column. Rows can be marked by a declared rule. A view is *shared* (everyone who reads the sheet sees it) or *personal* (only its maker). | `sheets.views` · M | — |
| **SH-8** | **Sharing.** <br>• *First version:* a sheet belongs to its workspace, and everyone in the workspace reads and edits it. The Share button says exactly that. <br>• *Then:* chosen people or groups (the RBAC groups) as readers or editors. A reader who may not see a sheet is told it exists and that it was not shared with them. <br>• *Two people editing at once:* the version check refuses a stale write and says who changed the cell. Showing who else is on the sheet comes later. | `sheets.sharing` · M | — |
| **SH-5** | **Columns a model writes** (only if call 5 says yes). <br>• A model fills a column per row, the semantic operators' way: 25 rows a call, at most 200 rows a fill. <br>• It fills the rows of a view a person picks, never the whole sheet at once. The calls are counted, and their cost is said before it runs. <br>• The column is marked *written by a model* everywhere, and is never a source for a number or a claim. <br>• New rows are filled only with a person's standing yes. | `sheets.model_columns` · M | — |
| **SH-6** | **Sheets everywhere else.** <br>• A sheet is live: it never "settles", and caches read it fresh. <br>• *Make a dashboard from this sheet* starts the Dashboards builder on it. <br>• The breakdown piece and the Briefing work over sheets; a sheet can back an ontology entity a person declares. | `sheets.everywhere` · S | — |

**Column kinds (SH-1).** A kind is set at import and taken only when every value reads back as it was written (the
Grist study's lossless rule); a value that does not fit stays text and is counted, never dropped.
- **Text, Number.**
- **Money,** in the workspace's currency.
- **Date and Date & time,** kept apart: comparing a time with a date at midnight is the bug measured in §1.
- **Choice,** few values, each a coloured chip.
- **Yes/No, Email, Link** (to another sheet).

**Order.** SV-1 → SV-2 → SH-1 → SH-2 → SH-4 → SH-7 → SH-3 → SH-8 → SH-6, and SH-5 only on its call. The chat comes
early because it is what the user asked for. Combining comes next because the user named it as what makes Teable
useful.

**Later, not waves yet:** a form that adds rows; showing who else is on a sheet; attachments in cells; a person as a
column's kind.

---

## 4. The laws it keeps

- **A model proposes; a person applies.** Teable's agent made its changes on its own over fifteen minutes. Here the chat
  drafts a card, the person applies it, and every change can be undone.
- **No model authors a fact.** A column a model writes is marked so wherever it is shown, and nothing computes from it.
- **Withheld is said:**
  - a value that did not fit its kind;
  - a link's misses;
  - a sheet not shared with you;
  - a model column's rows not yet filled.
- **Backups before people's typing.** SV-1 and SV-2 ship first.
- **The rail stays.** One row in the Data group, shown before it is built (§4.10).
- **One skin, CLARITY's layout:** figures first, read first, edit behind a click.

---

## 5. Decisions for you

1. **Aughor writes its own sheets.** A sheet is the workspace's data, never a customer's warehouse. *Recommended:* yes.
2. **Where a sheet's table lives.** *Recommended:* a DuckDB projection per workspace, rebuilt from source plus changes.
3. **Where changes live.** *Recommended:* the edit layer, gaining row grain: one store for "a person's change to a
   value". The alternative is a sheet change log of its own.
4. **The grid.** *Recommended:* the house's TanStack grid, extended for editing. The alternative is Teable's MIT
   canvas grid, faster past 100,000 rows.
5. **Columns a model writes.** *Recommended:* allowed, marked, filling a view a person picks (at most 200 rows a fill),
   with the calls and cost said first. The alternative is not at all.
6. **The chat proposes, a person applies.** *Recommended:* yes, every time.
7. **The rail row.** *Recommended:* "Spreadsheets" in the Data group, if the rail fits it at 1440×900; otherwise a tab
   of the Catalog.
8. **Sharing in the first version.** *Recommended:* the workspace, said on the Share button. Chosen people come in
   SH-8.
9. **Backups first.** *Recommended:* SH-1 waits for Arc SV-1 and SV-2.
10. **Comments on a record.** *Recommended:* said claims in the Record (as Google comments on a decision already are),
    anchored to the sheet and row, readable by whoever can read the row.
