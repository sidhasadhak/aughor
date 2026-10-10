"""Arc OC-7 — security on the contract: who sees which objects, and which properties, said wherever it bites.

Two declarations on an entity (`OntologyEntity.row_policies`, `.sensitive`), released like any other:

* a **row policy** names a group and the conditions on the entity's own properties its members' objects meet. Once an
  entity declares any, a reader sees only the objects a policy of one of their groups admits; a reader in none of those
  groups sees none, and is told which groups would;
* a **sensitive property** names the groups that read it; for everyone else its value is masked — empty, never
  guessed — and a query that would filter, group or measure by it is refused, because the answer would leak it.

The reader is the person a request acts for (`authz.caller`) and, when an agent acts for them (the
`X-Aughor-Acting-Agent` header, or an actor that is an agent), that agent too: the rows are those BOTH may see and a
property is masked if EITHER may not — an agent never reads beyond the person it acts for, nor beyond its own grants.

Enforced at the three object doors through their one FROM (`object_query.backing_from`), the compiler's one property
resolution (`_Compiler.prop`) and the object page — behind `ontology.security` (off; byte-identical when off). Every
withheld thing is said: the listing's and the page's caveats name the policy, the group and what to ask for.
"""
from __future__ import annotations

import contextlib
import contextvars
import re
from dataclasses import dataclass, field
from typing import Iterator, Optional

from starlette.requests import Request

from aughor.ontology.models import OntologyEntity

FLAG = "ontology.security"
EVERYONE = "*"
#: The header an agent's runtime sends when it acts for the person the request is identified as.
AGENT_HEADER = "X-Aughor-Acting-Agent"

_acting_agent: contextvars.ContextVar[str] = contextvars.ContextVar("aughor_acting_agent", default="")
_unfiltered: contextvars.ContextVar[bool] = contextvars.ContextVar("aughor_security_unfiltered", default=False)
_PRINCIPAL = re.compile(r"^agent:[A-Za-z0-9_.:-]{1,128}$")


def enabled() -> bool:
    from aughor.kernel.flags import flag_enabled
    return flag_enabled(FLAG) and not _unfiltered.get()


@contextlib.contextmanager
def unfiltered() -> Iterator[None]:
    """For the platform's own checks only — whether an object a reader cannot see exists at all, so the page can say
    it is withheld rather than missing. Never around anything a reader receives."""
    token = _unfiltered.set(True)
    try:
        yield
    finally:
        _unfiltered.reset(token)


def set_acting_agent(principal: str) -> "contextvars.Token[str]":
    return _acting_agent.set(principal if _PRINCIPAL.match(principal or "") else "")


def reset_acting_agent(token: "contextvars.Token[str]") -> None:
    _acting_agent.reset(token)


async def acting_agent_from_request(request: Request) -> None:
    """A router dependency: the agent a request says acts for its person. It only ever NARROWS what is read."""
    value = (request.headers.get(AGENT_HEADER) or "").strip()
    if value:
        set_acting_agent(value)


@dataclass
class Reader:
    """Who reads: one principal per party (`user:ana`, and `agent:refunds_bot` when an agent acts for her), each with
    their groups."""
    principals: list[str]
    groups: dict[str, set[str]] = field(default_factory=dict)

    def words(self) -> str:
        return " acting for ".join(reversed(self.principals)) if len(self.principals) > 1 else self.principals[0]


def reader() -> Reader:
    from aughor.org.context import DEFAULT_ORG_ID, current_actor, current_org_id
    from aughor.rbac.groups import groups_of
    from aughor.security.authz import caller
    org = current_org_id() or DEFAULT_ORG_ID
    who = caller() or "anonymous"
    principals = [who if who.startswith(("user:", "agent:")) else f"user:{who}"]
    agent = _acting_agent.get() or (current_actor() if (current_actor() or "").startswith("agent:") else "")
    if agent and agent not in principals:
        principals.append(agent)
    return Reader(principals=principals,
                  groups={p: set(groups_of(org, p)) | {EVERYONE} for p in principals})


# ── rows ─────────────────────────────────────────────────────────────────────────────────────────────────────────────

_OPS = {"=": "=", "!=": "<>", ">": ">", ">=": ">=", "<": "<", "<=": "<="}


def condition_problem(entity: OntologyEntity, condition: dict) -> str:
    """Why a row policy's condition cannot be declared on ``entity``, or "" — own properties, simple operators only."""
    path = str(condition.get("path") or "")
    op = str(condition.get("op") or "=")
    if "." in path or path not in (entity.properties or {}):
        return f"a row policy reads {entity.id}'s own properties — '{path}' is not one of them"
    if op not in (*_OPS, "in", "not_in", "is_null", "not_null"):
        return f"a row policy compares with =, !=, >, >=, <, <=, in, not_in, is_null or not_null — not {op!r}"
    if op in ("in", "not_in") and not list(condition.get("values") or []):
        return f"'{path} {op}' lists the values it admits"
    return ""


def _sql(condition: dict, alias: str) -> str:
    from aughor.ontology.cardinality import quote_ident
    from aughor.semantic.object_query import sql_literal
    col = f"{alias}.{quote_ident(str(condition['path']))}"
    op = str(condition.get("op") or "=")
    if op == "is_null":
        return f"{col} IS NULL"
    if op == "not_null":
        return f"{col} IS NOT NULL"
    if op in ("in", "not_in"):
        values = ", ".join(sql_literal(v, col) for v in condition.get("values") or [])
        return f"{col} {'NOT IN' if op == 'not_in' else 'IN'} ({values})"
    return f"{col} {_OPS[op]} {sql_literal(condition.get('value'), col)}"


def _admitted(entity: OntologyEntity, groups: set[str]) -> list:
    return [p for p in entity.row_policies if p.group in groups]


def row_condition(entity: OntologyEntity, alias: str, who: Optional[Reader] = None) -> Optional[str]:
    """The SQL condition the reader's objects of ``entity`` meet under ``alias``, or None when nothing restricts them
    (the flag off, or no policy declared). "FALSE" when a party is in none of the policies' groups."""
    if not enabled() or not entity.row_policies:
        return None
    who = who or reader()
    parts: list[str] = []
    for principal in who.principals:
        mine = _admitted(entity, who.groups.get(principal, {EVERYONE}))
        if not mine:
            return "FALSE"
        ors = [" AND ".join(f"({_sql(c, alias)})" for c in p.conditions) or "TRUE" for p in mine]
        parts.append("(" + " OR ".join(f"({o})" for o in ors) + ")")
    return " AND ".join(parts)


def rows_said(entity: OntologyEntity, who: Optional[Reader] = None) -> Optional[str]:
    """What a reader is told of the objects of ``entity`` withheld from them, or None."""
    if not enabled() or not entity.row_policies:
        return None
    who = who or reader()
    groups = sorted({p.group for p in entity.row_policies})
    for principal in who.principals:
        mine = _admitted(entity, who.groups.get(principal, {EVERYONE}))
        if not mine:
            return (f"{entity.id} is shown by group, and {principal} is in none of its groups ({', '.join(groups)}) — "
                    f"no {entity.id} object is shown; ask an administrator to add {principal} to one")
    said = "; ".join(f"{p.group}: {_words(p.conditions)}" for p in entity.row_policies
                     if any(p in _admitted(entity, who.groups.get(pr, {EVERYONE})) for pr in who.principals))
    return (f"only the {entity.id} objects {who.words()} may see are shown — {said}"
            + (" (both the person's and the agent's)" if len(who.principals) > 1 else ""))


def counts_said(entity: OntologyEntity, who: Optional[Reader] = None) -> Optional[str]:
    """What a reader is told of a count read over every object of ``entity`` (a process's measurement, kept once for
    every reader) while their own rows are restricted — or None."""
    if not enabled() or not entity.row_policies:
        return None
    return (f"counted over every {entity.id}, not only the ones {(who or reader()).words()} may see — a table of "
            "them lists only those")


def _words(conditions: list[dict]) -> str:
    out = []
    for c in conditions:
        op, path = str(c.get("op") or "="), str(c.get("path"))
        rhs = ", ".join(map(str, c.get("values") or [])) if op in ("in", "not_in") else c.get("value")
        out.append(f"{path} {op}" + ("" if op in ("is_null", "not_null") else f" {rhs}"))
    return " and ".join(out) or "every object"


# ── properties ───────────────────────────────────────────────────────────────────────────────────────────────────────

def masked(entity: OntologyEntity, prop: str, who: Optional[Reader] = None) -> Optional[str]:
    """Why ``entity.prop`` is masked for the reader, or None when they read it."""
    if not enabled():
        return None
    s = (entity.sensitive or {}).get(prop) or next((v for k, v in (entity.sensitive or {}).items()
                                                    if k.lower() == (prop or "").lower()), None)
    if s is None:
        return None
    who = who or reader()
    allowed = set(s.visible_to or [])
    for principal in who.principals:
        if EVERYONE in allowed or allowed & who.groups.get(principal, set()):
            continue
        return (f"{entity.id}.{prop} is {s.level} — masked for {principal}; "
                f"{', '.join(sorted(allowed)) or 'no group'} may read it")
    return None
