"""Who may read and change a sheet (Arc SH, SH-8; flag ``sheets.sharing``).

A sheet is its workspace's — everyone in it reads and edits it — until its maker shares it with chosen people and
groups, each able to read it (``view``) or to change it (``edit``): the access ladder's own words (``rbac/levels.py``).
The maker holds ``own``: with the flag on, only they change who a sheet is shared with, or remove it. Who it is shared
with is kept in the sheet's definition (``model.Sheet.sharing`` and ``shared_with``), versioned with every other change
to it, as a dashboard keeps who it is published to — so a sharing change has its who and when, and a removed sheet
takes its sharing with it. A group reaches a person as a published dashboard does (``dashboards/sharing.audience_of``):
an organisation's group they are a member of, or a role they hold.

**A sheet not shared with someone is listed and said, never read.** Its name and its maker are told; its rows are
refused at every door that reads them — the sheet's own routes, the chat's tools, and the Sheets connection, which the
SQL Editor, dashboards and every answer read through (`refusal_for_statement`). Its sample values are kept out of the
schema a model is handed, for everyone (`without_samples`), because that schema is cached per connection, not per
person. What is shared is decided whatever the flag says: off, nothing can be shared, and a sheet already shared with
chosen people stays shared only with them — turning a wave off never opens what a person closed.

Who is asking is the person every write is recorded under (``security.authz.acting_person``): the signed-in person,
else this install's own operator.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from aughor.rbac.levels import EDIT, LADDER, OWN, VIEW, level_covers
from aughor.sheets import model
from aughor.sheets.model import Share, Sheet
from aughor.sheets.service import Refused

__all__ = ["EDIT", "OWN", "VIEW", "Access", "NotShared", "acting", "level_of", "require", "readable"]

KINDS = ("person", "group", "role")


@dataclass(frozen=True)
class Access:
    """What a person may do to a sheet — ``own``, ``edit``, ``view``, or ``""`` for nothing — and why."""
    level: str
    why: str


class NotShared(Refused):
    """A sheet, or what was asked of it, not shared with the person asking — in a sentence that names who to ask. A
    refusal like any other, so every door that already says a sheet's refusals says this one."""


def acting() -> str:
    """The person a door that is not a route acts for (the chat's tools, the Sheets connection), as ``user:<id>``."""
    from aughor.security.authz import acting_person
    return acting_person(None)


def person_name(principal: str) -> str:
    """A person as a sentence names them: their id without ``user:``."""
    return (principal or "").removeprefix("user:") or "someone"


def _rank(level: str) -> int:
    return LADDER.index(level) if level in LADDER else -1


def _audience(user_id: str) -> set[tuple[str, str]]:
    """The groups a person is a member of and the roles they hold, as ``(kind, id)`` — what reaches them."""
    from aughor.dashboards.sharing import audience_of
    aud = audience_of(user_id)
    return {(a["kind"], a["id"]) for a in aud.get("groups", []) + aud.get("roles", [])}


def level_of(sheet: Sheet, person: str) -> Access:
    """What ``person`` (``user:<id>``) may do to ``sheet``: its maker owns it; a sheet that is the workspace's is
    everyone's to edit; one shared with chosen people is theirs to read or edit, the most any of their shares gives."""
    if sheet.created_by and person == sheet.created_by:
        return Access(OWN, "made it")
    if sheet.sharing != "chosen":
        return Access(EDIT, "everyone in the workspace can edit it")
    user_id = person.removeprefix("user:")
    best, why = "", ""
    reach: Optional[set[tuple[str, str]]] = None
    for share in sheet.shared_with:
        if share.kind == "person":
            hit = share.id == user_id
        else:
            if reach is None:
                reach = _audience(user_id)
            hit = (share.kind, share.id) in reach
        if hit and _rank(share.level) > _rank(best):
            best = share.level
            why = "shared with you" if share.kind == "person" else f"shared with {share.kind} {share.id}"
    return Access(best, why)


def refusal(sheet: Sheet, got: Access, need: str) -> str:
    """Why ``need`` is not held, naming who decides."""
    maker = person_name(sheet.created_by)
    if not got.level:
        return f'"{sheet.name}" was not shared with you. {maker} made it; ask them to share it with you.'
    if need == OWN:
        return f'Only {maker}, who made "{sheet.name}", can change who it is shared with or remove it.'
    return f'You can read "{sheet.name}" but not change it: {maker} shared it with you to read.'


def require(sheet: Sheet, person: str, need: str = VIEW) -> Access:
    """The person's access, or `NotShared` saying why it is not enough."""
    got = level_of(sheet, person)
    if got.level and level_covers(got.level, need):
        return got
    raise NotShared(refusal(sheet, got, need))


def readable(sheet: Sheet) -> Sheet:
    """The sheet, when the person this door acts for may read it; `NotShared` otherwise."""
    require(sheet, acting(), VIEW)
    return sheet


# ── the Sheets connection ────────────────────────────────────────────────────────────────────────────────────────────

def _chosen(org_id: str = "") -> list[Sheet]:
    return [s for s in model.list_sheets(org_id=org_id) if s.sharing == "chosen"]


def refusal_for_statement(sql: str, person: str = "", org_id: str = "") -> str:
    """Why a statement on the Sheets connection is not run for ``person`` — it reads a sheet not shared with them —
    or ``""``. A statement whose tables cannot be read is held to every word of it that names such a sheet's table,
    so a parse the reader cannot follow never reads past the gate."""
    chosen = _chosen(org_id)
    if not chosen:
        return ""
    who = person or acting()
    withheld = {s.table.lower(): s for s in chosen if not level_of(s, who).level}
    if not withheld:
        return ""
    from aughor.sql.tables import extract_tables
    read = {ref.table.lower() for ref in extract_tables(sql, "duckdb")}
    if not read:
        read = set(re.findall(r"[a-z_][a-z0-9_]*", (sql or "").lower()))
    hit = [withheld[t] for t in sorted(read) if t in withheld]
    if not hit:
        return ""
    sheet = hit[0]
    more = f" (and {len(hit) - 1} more not shared with you)" if len(hit) > 1 else ""
    return (f'The sheet "{sheet.name}"{more} was not shared with you, so this was not run. '
            f"{person_name(sheet.created_by)} made it; ask them to share it with you.")


def without_samples(schema: str, org_id: str = "") -> str:
    """The schema with the sample values of every sheet shared with chosen people taken out of its table's block —
    for everyone, as the schema is cached per connection and never per person. Its columns stay: that the sheet
    exists is told; its values are not."""
    tables = {s.table.lower() for s in _chosen(org_id)}
    if not tables or not schema:
        return schema
    from aughor.db.schema_render import strip_value_samples
    out: list[str] = []
    inside = False
    for line in schema.splitlines(keepends=True):
        m = re.match(r"^TABLE:\s+([\w.]+)", line)
        if m:
            inside = m.group(1).split(".")[-1].lower() in tables
        out.append(strip_value_samples(line) if inside else line)
    return "".join(out)


# ── who a sheet is shared with, said and changed ─────────────────────────────────────────────────────────────────────

def _org() -> str:
    from aughor.org.context import current_org_id
    return current_org_id() or "default"


def _group_names() -> dict[tuple[str, str], str]:
    from aughor.rbac.groups import list_groups
    from aughor.rbac.roles import BUILTIN_ROLES
    names = {("role", r): BUILTIN_ROLES[r].label for r in BUILTIN_ROLES}
    names.update({("group", g.id): g.name for g in list_groups(_org())})
    return names


def _people() -> list[str]:
    """The people this organisation knows by name — those holding a role, and the members of its groups."""
    from aughor.rbac.groups import list_groups, list_members
    from aughor.rbac.store import list_assignments
    org = _org()
    found = {a.user_id for a in list_assignments(org)}
    for g in list_groups(org):
        found |= {m.removeprefix("user:") for m in list_members(org, g.id) if m.startswith("user:")}
    return sorted(p for p in found if p)


def described(sheet: Sheet, person: str) -> dict:
    """Who a sheet is shared with, as the person asking sees it: everyone, or each person and group with what they
    may do; their own access; whether they may change it; and who and what they may choose from."""
    names = _group_names()
    got = level_of(sheet, person)
    maker = sheet.created_by.removeprefix("user:")
    shares = [{"kind": s.kind, "id": s.id, "level": s.level,
               "name": s.id if s.kind == "person" else names.get((s.kind, s.id), s.id)}
              for s in sheet.shared_with]
    groups = [{"kind": k, "id": i, "name": n} for (k, i), n in sorted(names.items(), key=lambda x: (x[0][0], x[1]))]
    return {"sharing": sheet.sharing, "shared_with": shares, "maker": maker, "access": got.level, "why": got.why,
            "may_change": got.level == OWN, "people": [p for p in _people() if p != maker], "groups": groups}


def set_sharing(sheet: Sheet, sharing: str, shared_with: list[dict], *, by: str) -> Sheet:
    """Share a sheet with everyone in the workspace, or with the people and groups chosen — kept as a version of its
    definition, saying who it is shared with now. Only its maker may (`require` ``own``)."""
    require(sheet, by, OWN)
    if sharing not in ("workspace", "chosen"):
        raise Refused(f'a sheet is shared with "workspace" or "chosen" people, not {sharing!r}')
    names = _group_names()
    maker = sheet.created_by.removeprefix("user:")
    kept: dict[tuple[str, str], Share] = {}
    for raw in shared_with if sharing == "chosen" else []:
        try:
            share = Share(**{"kind": raw.get("kind"), "id": str(raw.get("id") or "").strip().removeprefix("user:"),
                             "level": raw.get("level") or VIEW})
        except Exception:  # noqa: BLE001 — a malformed entry is refused by name below
            raise Refused(f"a share is a person, a group or a role, each to view or to edit: {raw!r}") from None
        if not share.id:
            raise Refused(f"a {share.kind} to share with needs its id")
        if share.kind == "person":
            if share.id == maker:
                continue                                   # the maker owns it: a share would only say less
            if any(ch.isspace() for ch in share.id):
                raise Refused(f"{share.id!r} is not a person's id; it is the name they sign in with, with no spaces")
        elif (share.kind, share.id) not in names:
            raise Refused(f"there is no {share.kind} {share.id!r} here")
        kept[(share.kind, share.id)] = share                # the last word on each person or group stands
    if sharing == "chosen" and not kept:
        raise Refused("choose at least one person or group, or share it with everyone in the workspace")
    sheet.sharing = "chosen" if sharing == "chosen" else "workspace"
    sheet.shared_with = list(kept.values())
    return model.save(sheet, what=words(sheet, names), by=by)


def words(sheet: Sheet, names: Optional[dict] = None) -> str:
    """Who a sheet is shared with, in a change's words: "shared with everyone in the workspace", or "shared with ana
    (can edit), Finance (can read)"."""
    if sheet.sharing != "chosen":
        return "shared with everyone in the workspace"
    names = names if names is not None else _group_names()
    said = [f"{s.id if s.kind == 'person' else names.get((s.kind, s.id), s.id)} "
            f"({'can edit' if s.level == EDIT else 'can read'})" for s in sheet.shared_with]
    return "shared with " + ", ".join(said)
