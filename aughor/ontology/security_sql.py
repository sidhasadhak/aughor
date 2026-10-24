"""Arc ED, ED-1 (ROADMAP §3.58) — one row policy at every door: OC-7's declarations applied where SQL is run.

OC-7 (`ontology.security`) declares on an entity which objects each group may see and which properties only some may
read, and enforces both at the object doors (`object_query.backing_from`, the compiler's property resolution and the
object page). A quick answer, a deep analysis and the SQL editor reach the same rows another way: through a
connection's own door, where only the RBAC row policy (`rbac/row_policy.py`, which ships empty) applied. So a reader
denied an order on its page could count it in an answer.

Behind ``ontology.security_sql`` (off; it needs ``ontology.security``) the connection's door applies the same
declarations to every statement a request runs (`db.connection.enforce_row_policy`), on the tables that back the
entities of the connection's released ontology:

* a table that backs an entity with row policies is read through the reader's objects, the condition the object door
  applies (`security.row_condition`), and the answer says so (`db.doors.say`);
* a statement that reads a property masked for the reader — named anywhere, or under a ``SELECT *`` — is refused with
  the object door's words, where the object door would show it empty;
* a table read through a query-backed entity the reader is restricted on is refused: raw SQL over its base tables
  cannot be narrowed to the reader's objects, and the objects can be read at the object door.

What it never narrows: the platform's own statements (`internal=True`), a schedule or an automation run (no request
acts for anyone there — the counts the Briefing keeps for every reader say so, `security.counts_said`), and the object
doors' own statements, which apply the declarations themselves and mask what they read (`object_door`).
"""
from __future__ import annotations

import contextlib
import contextvars
from typing import Iterator, Optional

FLAG = "ontology.security_sql"

#: Set around the object doors' own statements: they read the reader's rows through `backing_from` and mask what they
#: show, so the connection's door leaves them to it. Set by code only — never by anything a statement carries.
_door: contextvars.ContextVar[bool] = contextvars.ContextVar("aughor_object_door", default=False)


def enabled() -> bool:
    from aughor.kernel.flags import flag_enabled
    from aughor.ontology import security
    return flag_enabled(FLAG) and security.enabled()


@contextlib.contextmanager
def object_door() -> Iterator[None]:
    """The statements run inside were compiled by an object door, which applies the reader's declarations itself."""
    token = _door.set(True)
    try:
        yield
    finally:
        _door.reset(token)


async def object_door_from_request() -> None:
    """A router dependency for the object doors' routers: every statement they run is an object door's."""
    _door.set(True)


def applies() -> bool:
    """Whether the connection's door applies the declarations to the statement in flight: the flags on, a request
    acting for someone, and neither an object door's statement nor the platform's own."""
    if not enabled() or _door.get():
        return False
    from aughor.db.doors import statement_is_internal
    from aughor.org.context import current_actor
    return bool(current_actor()) and not statement_is_internal()


def _graphs(connection_id: str) -> list:
    """The released ontology of every schema built on the connection — a read, never a build."""
    from aughor.ontology.store import built_schemas, load_latest_ontology
    schemas = built_schemas(connection_id)
    graphs = [load_latest_ontology(connection_id, s) for s in schemas] if schemas else [
        load_latest_ontology(connection_id, None)]
    return [g for g in graphs if g is not None]


def _table_of(entity) -> str:
    b = entity.backing
    return str((b.table if b is not None else None) or (entity.source_tables[0] if entity.source_tables else "") or "")


def _base_tables(sql: str) -> list[tuple[str, str]]:
    import sqlglot
    from sqlglot import exp
    from aughor.sql.rls import bare_name
    tree = sqlglot.parse_one(sql, read="duckdb", error_level=sqlglot.ErrorLevel.RAISE)
    ctes = {(c.alias_or_name or "").lower() for c in tree.find_all(exp.CTE)}
    return sorted({(bare_name(t.db), bare_name(t.name)) for t in tree.find_all(exp.Table) if bare_name(t.name) not in ctes})


def rules_for(connection_id: str, who=None, graphs: Optional[list] = None) -> list:
    """The SQL door's rules for the reader on this connection: one per table that backs an entity declaring row
    policies or sensitive properties."""
    from aughor.ontology import security
    from aughor.sql.rls import EntityRule, bare_name
    who = who or security.reader()
    rules: list = []
    for graph in (graphs if graphs is not None else _graphs(connection_id)):
        for entity in (graph.entities or {}).values():
            if not entity.row_policies and not entity.sensitive:
                continue
            b = entity.backing
            if b is not None and b.kind == "platform":
                continue                      # Arc OC-6 — its objects live in the edit layer; no SQL reads them
            predicate = security.row_condition(entity, "__rp", who)
            masked = tuple((prop, why) for prop in sorted(entity.sensitive or {})
                           if (why := security.masked(entity, prop, who)))
            if b is not None and b.kind == "query" and b.sql:
                if (predicate is None or security.sees_every(entity, who)) and not masked:
                    continue
                held = "; ".join([*([security.rows_said(entity, who)] if predicate is not None else []),
                                  *(w for _, w in masked)])
                rules += [EntityRule(table=t, schema=s, entity=entity.id, refused=(
                    f"{t} is read by {entity.id}'s query, so a statement over it cannot be narrowed to what "
                    f"{who.words()} may see ({held}); read {entity.id} through its objects instead"))
                    for s, t in _base_tables(b.sql)]
                continue
            table = _table_of(entity)
            if not table:
                continue
            parts = [p for p in table.split(".") if p]
            rules.append(EntityRule(table=bare_name(parts[-1]), schema=bare_name(parts[-2]) if len(parts) > 1 else "",
                                    entity=entity.id, predicate=predicate,
                                    masked=tuple((bare_name(c), w) for c, w in masked)))
    return rules


def apply(connection_id: str, sql: str, dialect: str = "duckdb") -> str:
    """``sql`` narrowed to the reader's objects, with what was narrowed said on the result (`db.doors.say`). Raises
    `sql.rls.PolicyRefused` for a statement that reads what the reader may not. Unchanged, as written, when no table
    of a policied entity is read."""
    from aughor.db.doors import passed, say
    from aughor.ontology import security
    from aughor.sql.rls import apply_entity_rules
    who = security.reader()
    graphs = _graphs(connection_id)
    out, applied = apply_entity_rules(sql, rules_for(connection_id, who, graphs), dialect)
    if applied:
        passed("object-policy:" + ",".join(sorted({r.entity for r in applied})))
        entities = {e.id: e for g in graphs for e in (g.entities or {}).values()}
        for r in applied:
            entity = entities.get(r.entity)
            said = security.rows_said(entity, who) if entity is not None else None
            if said:
                say(f"{said} — this answer read {r.table} through {r.entity}'s row policy")
    return out


def tenancy_words() -> Optional[str]:
    """What the result cache must key a statement by while the declarations apply to it: the reader and their groups.
    None when they do not apply, so the cache key is the one it was."""
    if not applies():
        return None
    from aughor.ontology import security
    who = security.reader()
    return "|".join(f"{p}:{','.join(sorted(who.groups.get(p, set())))}" for p in who.principals)


# ── edit history ────────────────────────────────────────────────────────────────────────────────────────────────────

def _word(name: str) -> str:
    return "".join(ch for ch in (name or "").lower() if ch.isalnum())


def _admitted_keys(connection_id: str, entity, keys: set) -> Optional[set]:
    """Which of ``keys`` are objects of ``entity`` the reader may see — read through the object door's FROM, which
    applies their row policy. None when it could not be read (the caller withholds, never shows)."""
    try:
        from aughor.db.connection import open_connection_for
        from aughor.ontology.cardinality import quote_ident
        from aughor.semantic.object_instances import key_of
        from aughor.semantic.object_query import backing_from, sql_literal
        key = key_of(entity)
        col = f"o.{quote_ident(key)}"
        listed = ", ".join(sql_literal(k, col) for k in sorted(keys))
        db = open_connection_for(connection_id)
        try:
            with object_door():
                result = db.execute("edit_history_rows",
                                    f"SELECT {col} FROM {backing_from(entity, 'o')} WHERE {col} IN ({listed})",
                                    sql_dialect="duckdb")
        finally:
            db.close()
        if getattr(result, "error", None):
            return None
        return {str(r[0]) for r in (result.rows or [])}
    except Exception as exc:  # noqa: BLE001 — unread is withheld, and said
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the edit history's objects could not be checked against the reader's rows; withheld",
                 counter="ontology.security_sql.history_unread")
        return None


def history_as_read(connection_id: str, rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """``(shown, withheld)``: the edit history as the reader may read it (`ontology.security_sql`). A masked property's
    values are emptied and say why; an edit to an object outside the reader's rows is withheld, and each entity's
    withheld edits are counted and said. An edit to no object (a table's or a column's) is kept."""
    from aughor.ontology import security
    from aughor.sql.rls import bare_name
    who = security.reader()
    by_name: dict = {}
    by_table: dict = {}
    for graph in _graphs(connection_id):
        for e in (graph.entities or {}).values():
            by_name.setdefault(_word(e.id), e)
            by_name.setdefault(_word(getattr(e, "api_name", "") or ""), e)
            table = _table_of(e)
            if table:
                by_table.setdefault(bare_name(table.split(".")[-1]), e)

    def entity_of(row: dict):
        return by_name.get(_word(row.get("object_type") or "")) or by_table.get(bare_name(str(row.get("table") or "")
                                                                                       .split(".")[-1]))

    asked: dict = {}
    for row in rows:
        e = entity_of(row)
        if e is not None and row.get("row_key") and not security.sees_every(e, who):
            asked.setdefault(e.id, (e, set()))[1].add(str(row["row_key"]))
    admitted = {eid: _admitted_keys(connection_id, e, keys) for eid, (e, keys) in asked.items()}
    shown: list[dict] = []
    held: dict = {}
    for row in rows:
        e = entity_of(row)
        if e is None:
            shown.append(row)
            continue
        if e.id in admitted and row.get("row_key"):
            ok = admitted[e.id]
            if ok is None or str(row["row_key"]) not in ok:
                held[e.id] = held.get(e.id, 0) + 1
                continue
        why = security.masked(e, str(row.get("column") or ""), who) if row.get("column") else None
        shown.append({**row, "body": "", "previous": "", "masked": why} if why else row)
    withheld = []
    for eid, n in sorted(held.items()):
        e = asked[eid][0]
        unread = admitted.get(eid) is None
        withheld.append({"object_type": eid, "count": n,
                         "why": (f"the {eid} objects these edits are on could not be checked against what "
                                 f"{who.words()} may see, so they are withheld") if unread
                         else (security.rows_said(e, who) or f"{eid} objects {who.words()} may not see")})
    return shown, withheld
