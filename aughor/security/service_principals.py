"""Service principals — an outside vendor's agent as a named author (the 2027 study §H "Identity",
§Q; phase 7, P7-1).

A person mints one: a name, a key returned exactly once and stored as a hash, the organisation it
belongs to, a note, and the connections it may name (empty = the organisation's agent policy decides).
The agent presents the name and the key on every request (:data:`NAME_HEADER`, :data:`KEY_HEADER`);
the API resolves a :class:`~aughor.security.authz.Principal` whose id is ``service:<name>`` — so every
entry it books carries its author — and holds the request to the organisation's agent policy exactly
as it holds the MCP client's (`rbac/agent_gate.py`). A presented key that does not match resolves to
NOTHING and never falls through to the header seam: a bad credential is refused, not downgraded.

The shape is the custom agent's key (`custom_agents/keys.py`): random bytes, a constant-time compare,
revocation as a state the row carries (supersede, never delete — the record of who was let in stays).
Rows live in the kernel ledger's kv store; no new store.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from typing import Any, Optional

NAME_HEADER = "X-Aughor-Service"
KEY_HEADER = "X-Aughor-Service-Key"
KV_STORE = "service_principals"
_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{1,62}$")
_TOKEN_BYTES = 32
PREFIX = "service:"


class ServicePrincipalRefused(ValueError):
    """The door said no, and why."""


def _ledger():
    from aughor.kernel.ledger import Ledger
    return Ledger.default()


def _now() -> str:
    from aughor.util.time import now_iso_z
    return now_iso_z()


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _row(name: str) -> Optional[dict]:
    raw = _ledger().kv_get(KV_STORE, name, None)
    return dict(raw) if isinstance(raw, dict) else None


def _put(row: dict) -> None:
    _ledger().kv_put(KV_STORE, row["name"], row, max_entries=10000)


def principal_id(name: str) -> str:
    return f"{PREFIX}{name}"


def is_service(principal) -> bool:
    return bool(principal is not None and str(getattr(principal, "user_id", "") or "").startswith(PREFIX))


def mint(name: str, *, org_id: str, by: str, note: str = "", connections: Optional[list[str]] = None) -> tuple[dict, str]:
    """A person mints a service principal: returns ``(record, key)`` — the key once, never again.
    Minting an existing name ROTATES its key (the same gesture, so rotation is something a person
    will do). Refuses a malformed name, no organisation or no minter."""
    if not _NAME.match(name or ""):
        raise ServicePrincipalRefused("a service principal's name is 2 to 63 characters of lowercase letters, digits, '-' or '_'")
    if not (org_id or "").strip():
        raise ServicePrincipalRefused("a service principal belongs to an organisation")
    if not (by or "").strip() or str(by).startswith(PREFIX) or str(by).startswith("agent:"):
        raise ServicePrincipalRefused("a person mints a service principal; an agent or a service cannot mint one")
    key = secrets.token_urlsafe(_TOKEN_BYTES)
    prior = _row(name) or {}
    row = {"name": name, "org_id": org_id, "key_hash": _hash(key), "created_at": prior.get("created_at") or _now(),
           "rotated_at": _now() if prior else "", "created_by": prior.get("created_by") or by, "rotated_by": by if prior else "",
           "note": (note or prior.get("note") or "")[:400], "connections": sorted({str(c) for c in (connections if connections is not None else prior.get("connections") or []) if str(c).strip()}),
           "active": True, "revoked_at": "", "revoked_by": ""}
    _put(row)
    try:
        _ledger().emit("service_principal.minted", {"name": name, "by": by, "active": True, "rotated": bool(prior)})
    except Exception as exc:  # noqa: BLE001 — the row is the authority; the event is the trail
        from aughor.kernel.errors import tolerate
        tolerate(exc, "a service principal's minting could not be journaled; its row is written",
                 counter="service_principal.minted_event")
    return public(row), key


def revoke(name: str, *, by: str, why: str = "") -> dict:
    row = _row(name)
    if row is None:
        raise ServicePrincipalRefused(f"no service principal named {name!r}")
    row.update({"active": False, "revoked_at": _now(), "revoked_by": by or "unidentified", "revoked_why": (why or "")[:400]})
    _put(row)
    try:
        _ledger().emit("service_principal.minted", {"name": name, "by": by, "active": False})
    except Exception as exc:  # noqa: BLE001 — the row is the authority; the event is the trail
        from aughor.kernel.errors import tolerate
        tolerate(exc, "a service principal's revocation could not be journaled; its row is written",
                 counter="service_principal.minted_event")
    return public(row)


def public(row: dict) -> dict:
    """The record without the hash — what a door returns."""
    return {k: v for k, v in row.items() if k != "key_hash"} | {"principal": principal_id(row["name"])}


def get(name: str) -> Optional[dict]:
    row = _row(name)
    return public(row) if row else None


def list_principals(org_id: Optional[str] = None) -> list[dict]:
    """Every service principal (of an organisation), active and revoked alike."""
    out = []
    for row in (_ledger().kv_load_all(KV_STORE) or {}).values():
        if not isinstance(row, dict) or not row.get("name"):
            continue
        if org_id and row.get("org_id") != org_id:
            continue
        out.append(public(row))
    return sorted(out, key=lambda r: r["name"])


def matches(name: str, candidate: str) -> bool:
    """Constant-time comparison against the stored hash; False on every failure path."""
    row = _row(name)
    if not row or not candidate or not row.get("active", False):
        return False
    return hmac.compare_digest(str(row.get("key_hash") or ""), _hash(candidate))


def headers_present(request: Any) -> bool:
    headers = getattr(request, "headers", {}) or {}
    return bool((headers.get(NAME_HEADER) or "").strip() or (headers.get(KEY_HEADER) or "").strip())


def resolve(request: Any):
    """The service principal a request presents, or None. A presented name or key that does not
    match an active row is None too — the caller must not fall through to a weaker seam."""
    headers = getattr(request, "headers", {}) or {}
    name = (headers.get(NAME_HEADER) or "").strip()
    key = (headers.get(KEY_HEADER) or "").strip()
    if not (name and key) or not matches(name, key):
        return None
    row = _row(name) or {}
    from aughor.security.authz import Principal
    return Principal(user_id=principal_id(name), org_id=str(row.get("org_id") or ""))


def allowed_connection(name: str, connection_id: str) -> bool:
    """A service principal minted with a connection list may name only those; an empty list leaves
    it to the organisation's agent policy."""
    row = _row(name) or {}
    allowed = row.get("connections") or []
    return not allowed or connection_id in allowed
