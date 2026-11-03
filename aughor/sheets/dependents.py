"""What reads a sheet, so removing it says so first, and what read it says why afterwards (Arc SH).

Read from what already names a sheet — nothing new is stored:

* **another sheet** names it by id, in a link, a column looked up through one, or a total (SH-7). Removed, what it kept
  stays and what it read goes empty, never a figure (`projection._derive`); `removed_reads` says so on those columns.
* **a dashboard's card** names its table in its query, on the Sheets connection (SH-6). Removed, the statement has
  nothing to read; the connection's door answers with `removed_words` instead of the engine's "Table with name … does
  not exist! Did you mean "sqlite_master"?". A new sheet that makes that table again is what the card reads.

What the asker is told follows the sharing's rule, that a thing not shared with someone is listed and said, never read: a
sheet not shared with them by its name and maker, a dashboard not reaching them by its owner and how many cards.
"""
from __future__ import annotations

import re
from typing import Optional

from aughor.sheets import model, sharing
from aughor.sheets.model import Sheet

#: A statement that reads a sheet someone removed: its error is `removed_words`' sentence, a person's to read.
REMOVED = "sheet_removed"

_MISSING_TABLE = re.compile(r"Table with name \"?(\w+)\"? does not exist", re.IGNORECASE)


def _reads_table(sql: str, table: str) -> bool:
    """Whether a statement reads the table. One whose tables cannot be read is held to every word of it, as the sharing's
    gate holds it (`sharing.refusal_for_statement`): a card listed too many is told; one left out breaks unsaid."""
    from aughor.dashboards import queries
    read = queries.tables_of(sql or "", "duckdb") or re.findall(r"[a-z_][a-z0-9_]*", (sql or "").lower())
    return table.lower() in read


def _columns_reading(other: Sheet, sheet_id: str) -> tuple[list[str], list[str]]:
    """The columns of ``other`` that read the sheet and go empty — what is looked up through a link to it, its totals of
    it — and its links to it, which keep their own values and link to nothing."""
    links = {c.id: c.name for c in other.columns if c.link and c.link.sheet == sheet_id}
    empties = [c.name for c in other.columns if (c.role == "lookup" and c.via in links)
               or (c.role == "total" and c.sheet == sheet_id)]
    return empties, list(links.values())


def _sheets_reading(sheet: Sheet, reader: str) -> list[dict]:
    out = []
    for other in model.list_sheets():
        if other.id == sheet.id:
            continue
        empties, links = _columns_reading(other, sheet.id)
        if empties or links:
            shown = bool(sharing.level_of(other, reader).level)
            out.append({"id": other.id, "name": other.name, "maker": sharing.person_name(other.created_by),
                        "empties": empties if shown else [], "links": links if shown else [], "withheld": not shown})
    return out


def _cards_and_dashboards(sheet: Sheet, person: str) -> tuple[list[dict], list[dict]]:
    """The dashboards holding a card that reads the sheet's table, and the cards no dashboard holds."""
    from aughor.cards.store import list_cards
    from aughor.dashboards import sharing as dashboard_sharing
    from aughor.dashboards import versions
    from aughor.dashboards.home import NOBODY_IN_PARTICULAR, owner_of
    from aughor.kernel.ledger import Ledger
    reading = {c.id: c for c in list_cards(connection_id=model.SHEETS_CONNECTION)
               if not c.provenance.superseded_by and _reads_table(c.sql, sheet.table)}
    if not reading:
        return [], []
    audience = dashboard_sharing.audience_of(person)
    dashboards, placed = [], set()
    for row in Ledger.default().artifacts_of_kind(versions.KIND, conn_id=model.SHEETS_CONNECTION, limit=1000):
        payload = row.get("payload") if versions.is_mine(row) else None
        if not payload or payload.get("retired"):
            continue
        held = [reading[i] for i in payload.get("cards") or [] if i in reading]
        if not held:
            continue
        placed |= {c.id for c in held}
        owner = owner_of(str(row.get("natural_key") or ""), model.SHEETS_CONNECTION)
        yours = owner == person
        shown = yours or dashboard_sharing.reaches(payload.get("published_to"), audience)
        dashboards.append({"title": versions.title_of(payload.get("spec")) if shown else "", "yours": yours,
                           "owner": "" if owner == NOBODY_IN_PARTICULAR else owner,
                           "cards": [c.title for c in held] if shown else [], "count": len(held), "withheld": not shown})
    loose = [{"title": c.title if c.scope_ref == person else "", "yours": c.scope_ref == person}
             for c in reading.values() if c.id not in placed]
    return dashboards, loose


def dependents_of(sheet: Sheet, reader: str, person: str) -> dict:
    """What reads a sheet, for the person about to remove it: other sheets, the dashboards holding a card over its table,
    and such cards on no dashboard. ``reader`` is who the sheets' sharing knows them as; ``person`` is who the dashboards'
    does — the two differ on an install nobody signs in to."""
    dashboards, cards = _cards_and_dashboards(sheet, person)
    return {"sheets": _sheets_reading(sheet, reader), "dashboards": dashboards, "cards": cards}


def _removal_words(sheet: Sheet) -> str:
    by = sheet.change.by
    who = "you" if by and by == sharing.acting() else sharing.person_name(by)
    return f'The sheet "{sheet.name}" was removed by {who} on {(sheet.change.at or "")[:10]}'


def removed_sentence(sheet_id: str) -> str:
    """A removed sheet asked for by its id, as a person is told; ``""`` when there never was one."""
    gone = model.get(sheet_id, with_removed=True)
    return f"{_removal_words(gone)}." if gone is not None and gone.state == "archived" else ""


def removed_words(error: str) -> str:
    """What to say instead of an engine's error that names the table of a removed sheet, or ``""`` for any other error:
    that sheet's name, who removed it and when, and the one thing that brings the statement back."""
    found = _MISSING_TABLE.search(error or "")
    gone: Optional[Sheet] = model.removed_with_table(found.group(1)) if found else None
    if gone is None:
        return ""
    # a table keeps the name its sheet was made with: the name said is one that makes this table again
    again = gone.name if model.table_name(gone.name, set()) == gone.table else gone.table.replace("_", " ")
    return (f'{_removal_words(gone)}, so this has nothing to read. A new sheet named "{again}" with the same columns '
            "would be read in its place.")


def removed_reads(sheet: Sheet) -> dict[str, str]:
    """For each column of the sheet that reads a removed sheet — a link to it, a column looked up through one, a total
    of it — the removed sheet's name. Read when the sheet is, so a column says why it is empty."""
    names: dict[str, str] = {}

    def gone(sheet_id: str) -> str:
        if sheet_id not in names:
            other = model.get(sheet_id, with_removed=True)
            names[sheet_id] = other.name if other is not None and other.state == "archived" else ""
        return names[sheet_id]

    out: dict[str, str] = {}
    for c in sheet.columns:
        via = sheet.column(c.via) if c.role == "lookup" else None
        read = c.link.sheet if c.link else via.link.sheet if via and via.link else c.sheet if c.role == "total" else ""
        if read and gone(read):
            out[c.id] = gone(read)
    return out
