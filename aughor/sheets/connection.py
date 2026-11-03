"""The sheets, as one connection — *Sheets* — that the rest of Aughor reads as it reads any table (Arc SH).

A DuckDB connection over the organisation's projection: a cursor of the one database the API process writes
(``projection.py``), so a chat answer, a Catalog browse or a dashboard reads exactly what the grid shows. The engine is
writable by construction — the API process writes the projection — so, as for the Workspace, the door's checks are the
read-only boundary for a person's or a model's statement, and every result's doors say so.

Never pooled: it is a cursor, cheap to take, and the projection it reads is the request's organisation's — a pooled one
would be handed to the next request whatever its organisation.

A sheet shared with chosen people (SH-8) is read here only by them: a statement reading one not shared with the person
it runs for is refused, saying so and who to ask, before the engine runs it; and the schema a model is handed carries no
sample values of such a sheet, for anyone (``sharing.py``). No profile or ontology is built over it at all
(`build_intelligence`). A statement reading a removed sheet's table is told who removed it and when (``dependents.py``).
"""
from __future__ import annotations

import re

from aughor.db.connection import DuckDBConnection, QueryResult


def _says_each_renamed_sheet(schema: str) -> str:
    """A renamed sheet's table keeps the name it was made with, so its TABLE line says what the sheet is called now, inline
    as any table's description is (`db.annotations`): a model asked for the sheet by that name has to find it."""
    from aughor.sheets import model
    renamed = {s.table.lower(): s.name for s in model.list_sheets() if not model.named_for(s)}
    if not renamed:
        return schema
    out = []
    for line in schema.splitlines(keepends=True):
        found = re.match(r"^TABLE:\s+([\w.]+)", line)
        name = renamed.get(found.group(1).split(".")[-1].lower()) if found else None
        if name:
            body = line.rstrip("\n")
            line = f'{body}  ⬝ the sheet "{name}"{line[len(body):]}'
        out.append(line)
    return "".join(out)


class SheetsConnection(DuckDBConnection):
    dialect = "duckdb"
    engine_read_only = False
    poolable = False

    def __init__(self, dsn: str = "sheets://", schema_name: str | None = None, connection_id: str = "sheets",
                 meta: dict | None = None):
        from aughor.sheets import files, projection
        self._path = files.projection_path()
        self._conn = projection.cursor()
        self._connection_id = connection_id or "sheets"
        self._schema_name = None
        self._ontology = None
        self.engine_read_only = False

    def make_reader(self) -> "SheetsConnection":
        return SheetsConnection(connection_id=self._connection_id)

    def _run(self, hypothesis_id: str, sql: str, max_rows: int, params: dict | None = None) -> QueryResult:
        from aughor.sheets.sharing import refusal_for_statement
        refused = refusal_for_statement(sql)
        if refused:
            return QueryResult(hypothesis_id=hypothesis_id, sql=sql, columns=[], rows=[], row_count=0, error=refused)
        result = super()._run(hypothesis_id, sql, max_rows, params)
        if result.error:
            # a table that is not there because its sheet was removed: said, never the engine's "did you mean"
            from aughor.sheets.dependents import REMOVED, removed_words
            said = removed_words(result.error)
            if said:
                result.error, result.error_kind = said, REMOVED
        return result

    def get_schema(self) -> str:
        from aughor.sheets.sharing import without_samples
        return _says_each_renamed_sheet(without_samples(super().get_schema()))

    def build_intelligence(self) -> str:
        """The fast schema, and nothing heavier. A sheet is live and each person's to read or not: value profiles and an
        ontology built over its rows would be stale after the next edit, and would carry a sheet shared with chosen
        people to everyone who reads them (SH-8). Nothing had been built over this connection on the live install
        (2026-10-28); this keeps it so."""
        self.last_build = {"ok": True, "stage": "skipped",
                           "why": "a sheet's rows are read at its door; no profile or ontology is built over them"}
        return self.get_schema()

    def ibis_connection(self):
        """None: the projection is open read-write in this process, and a second, read-only open of the file is
        refused by DuckDB."""
        return None

    def test(self) -> tuple[bool, str]:
        try:
            self._conn.execute("SELECT 1")
            return True, "Connected"
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)
