"""Arc ED, ED-2 (ROADMAP §3.58) — a service principal's grant, held at the API's door.

An outside program that presents a service principal is held to the organisation's agent policy (`agent_gate`).
Behind ``security.principal_scopes`` its own grant narrows that further — never widens it — on every request it makes:

* the **areas** it may work in: each route belongs to one (`area_of`); a principal whose grant names areas is refused
  a route in any other, and a route in none, so a door added later is closed to it until it is placed;
* the **connections**, **entities** and **declared actions** it may name, each refused by its own stable code;
* the entities it may **reach**: an entity outside the grant is refused wherever a request reaches it, not only where
  it names it — a link a page follows, a property path through a link in a listing's columns, a query's grouping, its
  measures and its filters (`hold`, read by the object compiler and the linked page through `outside`), with the same
  code and the same words;
* the contract it reads (`/ontology/v1/contract`) is cut to the same grant, and says what it left out.

A grant that names nothing in one of those is not narrowed there. The refusal is the agent gate's, with the code a
client can match (`mcp/policy.py`), and it is audited with the call.
"""
from __future__ import annotations

import contextvars
from dataclasses import dataclass
from typing import Any, Callable, Optional

from fastapi import HTTPException

FLAG = "security.principal_scopes"

#: Routes every principal may reach whatever its grant: what it is, and what the organisation allows it.
OPEN: frozenset = frozenset({("GET", "/ledger/v1/principals/service/me"), ("GET", "/org-settings/agent-policy")})

#: (method or "*", template prefix, area) — the first that matches places a route. Kept beside the level map's
#: spelling of the same routes (`mcp/policy.ROUTE_LEVELS`).
_ROUTES: tuple = (
    ("POST", "/ledger/v1/", "ledger:write"),
    ("GET", "/ledger/v1/", "ledger:read"),
    ("POST", "/objects/v1/actions/", "actions:propose"),
    ("*", "/objects", "objects:read"),
    ("*", "/object-types", "objects:read"),
    ("*", "/object-paths", "objects:read"),
    ("GET", "/ontology/v1/", "objects:read"),
    ("GET", "/automations/tools", "catalog:read"),
    ("POST", "/automations/", "automations:run"),
    ("POST", "/ask", "analysis:run"),
    ("POST", "/chat", "analysis:run"),
    ("POST", "/investigate", "analysis:run"),
    ("POST", "/exploration/", "analysis:run"),
    ("POST", "/jobs/", "analysis:run"),
    ("GET", "/connections", "catalog:read"),
    ("GET", "/metrics", "catalog:read"),
    ("GET", "/exploration/", "catalog:read"),
    ("*", "/knowledge/", "catalog:read"),
    ("GET", "/investigations/", "catalog:read"),
    ("GET", "/jobs", "catalog:read"),
    ("GET", "/traces", "catalog:read"),
    ("GET", "/agents/custom", "catalog:read"),
    ("GET", "/spotlight/tools", "catalog:read"),
    ("GET", "/ada/", "catalog:read"),
    ("GET", "/chat/", "catalog:read"),
)
_ENTITY_KEYS = ("entity", "object_type")


def enabled() -> bool:
    from aughor.kernel.flags import flag_enabled
    return flag_enabled(FLAG)


def area_of(method: str, template: str, tool: Optional[str] = None) -> Optional[str]:
    """The area a route belongs to, or None when it is in none. A Spotlight call is placed by the tool it names: a
    read reads the catalog, an act stages a change for a person."""
    m = (method or "").upper()
    if template.startswith("/spotlight/tools/") and m == "POST":
        from aughor.mcp.policy import spotlight_tool_level
        name = template.rsplit("/", 1)[-1]
        if name.startswith("{") and tool:
            name = tool
        return "actions:propose" if spotlight_tool_level(name) == "act" else "catalog:read"
    for verb, prefix, area in _ROUTES:
        if (verb == "*" or verb == m) and (template == prefix.rstrip("/") or template.startswith(prefix)):
            return area
    return None


def _word(name: str) -> str:
    return "".join(ch for ch in str(name or "").lower() if ch.isalnum())


def principal_of(request: Any):
    """The service principal a request presents, verified, or None — whether or not identity is enforced."""
    from aughor.security import service_principals as SP
    principal = getattr(getattr(request, "state", None), "principal", None)
    if SP.is_service(principal):
        return principal
    return SP.resolve(request) if SP.headers_present(request) else None


def named(request: Any, body: Optional[dict], keys: tuple) -> Optional[str]:
    for source in (getattr(request, "path_params", None) or {}, dict(getattr(request, "query_params", {}) or {}),
                   body or {}):
        for key in keys:
            v = source.get(key)
            if v:
                return str(v)
    return None


def refusal(grant: dict, *, method: str, template: str, tool: Optional[str], connection: Optional[str],
            entity: Optional[str], action: Optional[str]) -> Optional[tuple[str, str]]:
    """``(code, detail)`` when the grant does not admit the request, else None."""
    from aughor.mcp.policy import CODE_ACTION, CODE_AREA, CODE_ENTITY, CODE_GRANT_CONNECTION
    if ((method or "").upper(), template) in OPEN:
        return None
    areas = list(grant.get("areas") or [])
    if areas:
        area = area_of(method, template, tool)
        if area is None or area not in areas:
            where = f"in the area {area}" if area else "in no area a grant can name"
            return CODE_AREA, f"{method.upper()} {template} is {where}; this principal's grant names {', '.join(areas)}"
    connections = list(grant.get("connections") or [])
    if connections and connection and connection not in connections:
        return CODE_GRANT_CONNECTION, f"connection {connection!r} is not on this principal's grant"
    entities = list(grant.get("entities") or [])
    if entities and entity and _word(entity) not in {_word(e) for e in entities}:
        return CODE_ENTITY, entity_refused(entity, entities)
    actions = list(grant.get("actions") or [])
    if actions and action and action not in actions:
        return CODE_ACTION, f"declared action {action!r} is not on this principal's grant ({', '.join(actions)})"
    return None


def entity_refused(entity: str, entities: Any) -> str:
    """The words an entity outside a principal's grant is refused with — named, or reached through a link."""
    return f"entity {entity!r} is not on this principal's grant ({', '.join(entities)})"


class GrantRefused(HTTPException):
    """The agent gate's refusal, raised past the gate by a door that reached an entity outside the grant; the gate
    audits the call with its ``code`` (`agent_gate.enforce_agent_policy`)."""

    def __init__(self, code: str, detail: dict) -> None:
        super().__init__(status_code=403, detail=detail)
        self.code = code


@dataclass(frozen=True)
class _Held:
    entities: tuple[str, ...]
    #: (code, detail sentence) -> the gate's refusal body, as the gate itself would answer it
    refuse: Callable[[str, str], dict]


#: The entities the request in flight may reach, while a service principal's grant names some — set by the agent gate
#: once the request has passed it, never by anything a request carries.
_held: contextvars.ContextVar[Optional[_Held]] = contextvars.ContextVar("aughor_principal_grant_held", default=None)


def hold(entities: Any, refuse: Callable[[str, str], dict]) -> contextvars.Token:
    """Hold the rest of the request to the grant's ``entities`` (`outside`); ``refuse`` builds the gate's body."""
    return _held.set(_Held(entities=tuple(str(e) for e in entities), refuse=refuse))


def release(token: contextvars.Token) -> None:
    try:
        _held.reset(token)
    except ValueError:                        # reset from another context: the request's own ends with it
        _held.set(None)


def outside(entity: Any) -> Optional[str]:
    """Why the request in flight may not reach ``entity`` — the words an entity outside the grant is refused with —
    or None: no grant holds the request, or the grant names it (by id, api name or display name)."""
    held = _held.get()
    if held is None or not held.entities or entity is None:
        return None
    names = {_word(getattr(entity, attr, "") or "") for attr in ("id", "api_name", "display_name")} - {""}
    if names & {_word(e) for e in held.entities}:
        return None
    return entity_refused(str(getattr(entity, "id", "") or entity), held.entities)


def refused_here(detail: str) -> GrantRefused:
    """The gate's refusal of an entity reached outside the grant, for a door to raise: the code and body an entity
    named outside it gets (`refusal`), with ``detail`` saying how it was reached."""
    from aughor.mcp.policy import CODE_ENTITY
    held = _held.get()
    if held is None:
        from aughor.mcp.policy import refusal as body
        return GrantRefused(CODE_ENTITY, body(CODE_ENTITY, tool=None, policy_level="", detail=detail))
    return GrantRefused(CODE_ENTITY, held.refuse(CODE_ENTITY, detail))


def grant_for(request: Any) -> Optional[dict]:
    """The grant the request is held to: the presenting service principal's, while the flag is on; else None."""
    if not enabled():
        return None
    principal = principal_of(request)
    if principal is None:
        return None
    from aughor.security import service_principals as SP
    return SP.grant(SP.name_of(principal))


def narrow_contract(contract: dict, grant: Optional[dict]) -> dict:
    """The contract cut to the grant: entities and declared actions it does not name are left out, and counted."""
    if not grant or not (grant.get("entities") or grant.get("actions")):
        return contract
    keep_entities = {_word(e) for e in grant.get("entities") or []}
    keep_actions = set(grant.get("actions") or [])
    entities = {k: v for k, v in (contract.get("entities") or {}).items()
                if not keep_entities or _word(k) in keep_entities}
    actions = {k: v for k, v in (contract.get("actions") or {}).items() if not keep_actions or k in keep_actions}
    left_out = {"entities": len(contract.get("entities") or {}) - len(entities),
                "actions": len(contract.get("actions") or {}) - len(actions)}
    out = {**contract, "entities": entities, "actions": actions}
    if left_out["entities"] or left_out["actions"]:
        out["withheld"] = {**left_out, "why": "this principal's grant names only the entities and declared actions "
                                              "shown; the rest are left out of its contract"}
    return out
