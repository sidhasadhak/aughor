"""A sheet's definition, kept as versions on the platform's one versioning substrate (``kernel/lifecycle.py``).

The definition is everything about a sheet that is not a value: its name, its columns with their kinds and
descriptions, where its rows came from, the links and totals that read another sheet, and its saved views. Every change
to it is a new version, recorded ``published`` the moment it is made (a sheet has no save≠publish), with the person who
made it and — for the assistant's — the proposal it came from. Removing a sheet is a version too, ``archived``, written
before anything else goes: that version is the tombstone, and a sheet whose newest version says so stays removed
whatever files are left behind.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from aughor.kernel import lifecycle

#: The ledger's artifact kind for a sheet's definition.
KIND = "sheet"

#: The id of the one connection the sheets are, to the rest of Aughor.
SHEETS_CONNECTION = "sheets"

Role = Literal["stored", "computed", "lookup", "total"]
How = Literal["sum", "count", "latest", "earliest", "average", "min", "max"]


def now() -> str:
    """To the microsecond: a sheet's changes are replayed in order to undo them, and two often fall in one second."""
    return datetime.now(timezone.utc).isoformat()


class Link(BaseModel):
    """A stored column whose values are keys into another sheet (SH-7)."""
    sheet: str                    # the other sheet's id
    column: str                   # the other sheet's key column id
    matched: int = 0              # counted when the link was kept
    missed: int = 0


class Column(BaseModel):
    id: str
    name: str
    kind: str = "text"
    #: BIGINT rather than DOUBLE for a Number column whose every value is whole.
    integer: bool = False
    description: str = ""
    #: ``stored`` — imported or typed in; ``computed`` — an expression over this sheet's own columns; ``lookup`` — a
    #: column of another sheet read through a link; ``total`` — the other sheet's rows per key, summed or counted.
    role: Role = "stored"
    #: The column in the source file a stored column was imported from ("" for one added since).
    source: str = ""
    currency: str = ""
    choices: list[str] = Field(default_factory=list)
    hidden: bool = False
    expression: str = ""          # computed: a SQL expression over this sheet's columns, by name
    link: Optional[Link] = None   # stored + kind link
    via: str = ""                 # lookup: this sheet's link column id
    of: str = ""                  # lookup: the other sheet's column id · total: the other sheet's column summed
    sheet: str = ""               # total: the other sheet
    key: str = ""                 # total: the other sheet's key column id
    by: str = ""                  # total: this sheet's column holding the key
    how: str = ""                 # total: sum | count | latest | earliest | average | min | max
    made_by: str = ""             # "the assistant" when a model proposed it (a person applied it)


class Condition(BaseModel):
    """One condition of a view's filter: a column, an operator and a value."""
    column: str                   # column id
    op: str                       # is | is_not | contains | gt | gte | lt | lte | empty | not_empty | before | after | in
    value: Any = None


class View(BaseModel):
    """A saved grid: its filter, sort and hidden columns. Shared — everyone who reads the sheet sees it (SH-3 brings
    views only their maker sees, boards and calendars)."""
    id: str
    name: str
    filter: list[Condition] = Field(default_factory=list)
    sort: list[dict] = Field(default_factory=list)        # [{"column": id, "desc": bool}]
    hidden: list[str] = Field(default_factory=list)
    search: str = ""
    made_by: str = ""


class Source(BaseModel):
    kind: Literal["file", "blank", "rows"] = "blank"
    file: str = ""                # the file's name as brought
    tab: str = ""                 # the workbook tab, for an Excel file
    sha256: str = ""
    rows: int = 0
    imported_at: str = ""
    #: Where a file already uploaded to the Workspace came from, when it did: {"connection", "schema", "file"}.
    upload: dict = Field(default_factory=dict)
    #: A query's rows kept as a sheet: the statement and where it ran, saved beside the rows.
    sql: str = ""
    connection_id: str = ""
    schema_name: str = ""


class Change(BaseModel):
    """The last change made to a definition: what it was, who made it, and what made it."""
    id: str = ""
    what: str = ""
    by: str = ""
    at: str = ""
    #: "" for a person's own; "proposal:<id>" for the assistant's, applied by ``by``; "undo:<id>" / "redo:<id>".
    origin: str = ""


class Sheet(BaseModel):
    id: str
    name: str
    #: The table the Sheets connection names this sheet by.
    table: str
    source: Source = Field(default_factory=Source)
    columns: list[Column] = Field(default_factory=list)
    views: list[View] = Field(default_factory=list)
    #: The column whose values identify a row, for a newer file's keyed merge (SH-7); "" when none is declared.
    key: str = ""
    next_column: int = 1
    created_by: str = ""
    created_at: str = ""
    change: Change = Field(default_factory=Change)
    #: The definition's version on the ledger (filled when read, never written).
    version: int = 0
    state: str = "published"

    def column(self, ref: str) -> Optional[Column]:
        """A column by id, or by name (case-insensitive)."""
        for c in self.columns:
            if c.id == ref:
                return c
        low = (ref or "").strip().lower()
        return next((c for c in self.columns if c.name.lower() == low), None)

    def stored(self) -> list[Column]:
        return [c for c in self.columns if c.role == "stored"]

    def new_column_id(self) -> str:
        cid = f"c{self.next_column}"
        self.next_column += 1
        return cid


def natural_key(sheet_id: str, org_id: str) -> str:
    return f"sheet:{org_id}:{sheet_id}"


def new_id() -> str:
    return uuid.uuid4().hex[:10]


def valid_id(sheet_id: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{10}", sheet_id or ""))


def table_name(name: str, taken: set[str]) -> str:
    """The table a sheet is read by: its name in lower case, words joined by underscores, unique among the sheets."""
    base = re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_") or "sheet"
    if base[0].isdigit():
        base = f"sheet_{base}"
    base = base[:60]
    candidate, n = base, 2
    while candidate in taken:
        candidate, n = f"{base}_{n}", n + 1
    return candidate


def _org() -> str:
    from aughor.org.context import current_org_id
    return current_org_id() or "default"


def _from_revision(rev: lifecycle.Revision) -> Sheet:
    sheet = Sheet(**rev.body)
    sheet.version = rev.version
    sheet.state = rev.state
    return sheet


def get(sheet_id: str, *, org_id: str = "", with_removed: bool = False) -> Optional[Sheet]:
    """The sheet as it stands, or None. A removed sheet reads as None unless asked for."""
    if not valid_id(sheet_id):
        return None
    rev = lifecycle.resolve(KIND, natural_key(sheet_id, org_id or _org()), audience="editor")
    if rev is None or (rev.state == "archived" and not with_removed):
        return None
    return _from_revision(rev)


def history(sheet_id: str, *, org_id: str = "", limit: int = 100) -> list[Sheet]:
    """Every version of a sheet's definition, newest first."""
    return [_from_revision(r) for r in lifecycle.history(KIND, natural_key(sheet_id, org_id or _org()), limit=limit)]


def list_sheets(*, org_id: str = "") -> list[Sheet]:
    """This organisation's sheets, newest change first. A removed sheet is not listed: its tombstone is its newest
    version, and that is the authority."""
    from aughor.kernel.ledger import Ledger
    org = org_id or _org()
    out = []
    for art in Ledger.default().artifacts_of_kind(KIND, conn_id=SHEETS_CONNECTION, org_id=org, limit=1000):
        payload = art.get("payload") or {}
        if lifecycle.state_of(payload) == "archived":
            continue
        body = dict(payload.get("_body") or {}) if isinstance(payload, dict) else {}
        if not body.get("id"):
            continue
        sheet = Sheet(**body)
        sheet.version = int(art.get("version") or 0)
        out.append(sheet)
    return out


def save(sheet: Sheet, *, what: str, by: str, origin: str = "", change_id: str = "",
         state: lifecycle.PublicationState = "published") -> Sheet:
    """Keep the next version of a sheet's definition, recorded with what changed, who changed it and what made it."""
    sheet.change = Change(id=change_id or uuid.uuid4().hex[:12], what=what[:300], by=by, at=now(), origin=origin)
    body = sheet.model_dump(exclude={"version", "state"})
    note = f"proposed by the assistant ({origin.split(':', 1)[1]}), applied by {by}" if origin.startswith("proposal:") else ""
    rev = lifecycle.record(KIND, natural_key(sheet.id, _org()), body, state, by=by, note=note,
                           conn_id=SHEETS_CONNECTION)
    sheet.version = rev.version
    sheet.state = rev.state
    return sheet
