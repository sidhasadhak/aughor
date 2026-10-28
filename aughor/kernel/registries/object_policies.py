"""Arc ED, ED-1 (ROADMAP §3.58) — the ontology's object policies at a connection's door: the platform's seam.

The row policies and sensitive properties are the ontology's declarations, applied by `ontology/security_sql.py` on the
agent side of the boundary; the connection's door (`db.connection.enforce_row_policy`) is the platform's. The agent
registers its applier here at bootstrap and the door reads through the seam, never importing it.

Unlike the exclusions reader, an applier that is missing is not "nothing to apply". With no applier in the process, a
statement a request runs is refused: a host that forgot to register would otherwise run every statement unfiltered
while the declarations say the policies hold.
"""
from __future__ import annotations

from typing import Callable, Optional

# fn() -> whether the statement in flight is one the policies apply to
Applies = Callable[[], bool]
# fn(connection_id, sql, dialect) -> the statement narrowed to the reader's objects; raises `sql.rls.PolicyRefused`
Apply = Callable[[str, str, str], str]
# fn() -> the reader the result cache must key a narrowed read by, or None
Tenancy = Callable[[], Optional[str]]

_applies: Optional[Applies] = None
_apply: Optional[Apply] = None
_tenancy: Optional[Tenancy] = None


def register_object_policies(*, applies: Applies, apply: Apply, tenancy: Tenancy) -> None:
    """Install (or replace) the applier. The agent registers the real one at bootstrap; tests may register fakes."""
    global _applies, _apply, _tenancy
    _applies, _apply, _tenancy = applies, apply, tenancy


def clear() -> None:
    """Drop the applier (test isolation)."""
    global _applies, _apply, _tenancy
    _applies = _apply = _tenancy = None


def applies() -> bool:
    """Whether the policies apply to the statement in flight. With nothing registered, a request's statement is one
    they apply to, so `apply` refuses it."""
    if _applies is not None:
        return bool(_applies())
    from aughor.db.doors import statement_is_internal
    from aughor.org.context import current_actor
    return bool(current_actor()) and not statement_is_internal()


def apply(connection_id: str, sql: str, dialect: str) -> str:
    if _apply is None:
        from aughor.sql.rls import PolicyRefused
        raise PolicyRefused("the object policies are not loaded in this process, so nothing is run unfiltered")
    return _apply(connection_id, sql, dialect)


def tenancy() -> Optional[str]:
    if _tenancy is None:
        return None
    return _tenancy()
