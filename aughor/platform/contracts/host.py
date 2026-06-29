"""The Platform→Agent host contract — what the platform hands the Agent to run within.

The dependency direction is one-way: the Agent imports the Platform (allowed), the
Platform never imports the Agent (enforced by ``test_platform_agent_boundary``). This
module names the *downward* half of that boundary — the capability surface the platform
offers — as a single :class:`HostCapabilities` Protocol with a concrete
:func:`default_host` bound to the live platform.

Today the Aughor Agent reaches these services through their stable module functions
directly (``open_connection_for``, ``vend_llm``, ``kernel().submit``, …) — that is the
allowed direction, so nothing is forced through this object. Its value is to make the
contract **explicit and substitutable**: a *different* agent (the "extensible boundary"
goal) can be handed a ``HostCapabilities`` and discover exactly what the platform
provides, and a test/host can inject a stand-in. The *upward* half of the boundary —
what the agent plugs into the platform — is the registries
(``aughor.kernel.registries`` + ``aughor.agent.bootstrap``).
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Optional, Protocol, runtime_checkable

if TYPE_CHECKING:
    from aughor.db.connection import DatabaseConnection
    from aughor.kernel.ledger import Ledger
    from aughor.platform.contracts.execution import QueryResult


@runtime_checkable
class HostCapabilities(Protocol):
    """The platform services an Agent may use. The data plane, the inference plane, the
    job/ledger substrate, the security gate, and the grant-scoped catalog view."""

    # ── Data plane ────────────────────────────────────────────────────────────
    def open_connection(self, conn_id: str) -> "DatabaseConnection": ...
    def gate_sql(self, conn_id: str, label: str, sql: str) -> "Optional[QueryResult]": ...

    # ── Inference plane (Invariant #7) ────────────────────────────────────────
    def vend_llm(self, role: str, **scope: Any) -> Any: ...

    # ── Job / event substrate ─────────────────────────────────────────────────
    async def submit_job(self, kind: str, fn: Callable, **kw: Any) -> str: ...
    def ledger(self) -> "Ledger": ...

    # ── Governance / grants ───────────────────────────────────────────────────
    def accessible_catalog_ids(self, workspace_id: Optional[str] = None) -> set: ...


class _DefaultHost:
    """The live platform implementation of :class:`HostCapabilities` — thin delegation
    to the existing stable platform functions (no new behaviour)."""

    def open_connection(self, conn_id: str):
        from aughor.db.connection import open_connection_for
        return open_connection_for(conn_id)

    def gate_sql(self, conn_id: str, label: str, sql: str):
        from aughor.db.connection import gate_user_sql
        return gate_user_sql(conn_id, label, sql)

    def vend_llm(self, role: str, **scope):
        from aughor.platform.inference import vend_llm
        return vend_llm(role, **scope)

    async def submit_job(self, kind: str, fn, **kw) -> str:
        from aughor.kernel.jobs import kernel
        return await kernel().submit(kind, fn, **kw)

    def ledger(self):
        from aughor.kernel.ledger import Ledger
        return Ledger.default()

    def accessible_catalog_ids(self, workspace_id: Optional[str] = None) -> set:
        from aughor.metastore import accessible_catalog_ids
        return accessible_catalog_ids(workspace_id)


def default_host() -> HostCapabilities:
    """The platform's live host-capability handle to hand an Agent."""
    return _DefaultHost()
