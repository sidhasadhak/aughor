"""One resolved execution scope — the connection + schema + table filter an
investigation/chat/monitor runs against, with the canvas-precedence rules in ONE place.

Before this, four call sites in ``routers/investigations.py`` hand-rolled the same
"resolve the effective schema from a canvas" logic — and two of them (the crash-salvage
and the resume paths) omitted the table-list → owning-schema derivation, so a
table-list-scoped canvas being recovered or resumed pinned nothing and could leak an
unqualified ``FROM orders`` to a sibling schema's same-named table. ``ExecutionScope`` is
the single source of that precedence (NOM-11).

Precedence (canvas wins):
  * a canvas pins its own connection (``primary_connection_id``), its declared schema
    (``scopes[0].schema_name``), and its table filter;
  * ``eff_schema`` — the schema to PIN ``search_path`` to — is the declared schema, else
    the single owning schema of a schema-qualified table list (``missimi.orders`` →
    ``missimi``);
  * for a non-canvas run, an explicit ``schema_scope`` (e.g. a briefing "pull the thread")
    is honoured instead.

Fail-open: a missing / unreadable canvas degrades to the bare connection — ``resolve``
never raises.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Optional

from aughor.kernel.errors import tolerate

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExecutionScope:
    """The resolved connection + schema + table filter for one run.

    Immutable value object: build it once via :func:`resolve_execution_scope`, then read
    its fields. ``eff_schema`` is derived (not stored) so the precedence lives in one place.
    """

    connection_id: str
    canvas_id: Optional[str] = None
    #: The canvas's declared schema (``scopes[0].schema_name``) — drives the explicit
    #: "DEFAULT SCHEMA" prompt note. ``None`` for a full-schema or table-list-only canvas.
    declared_schema: Optional[str] = None
    #: The curated table filter; ``()`` means full schema.
    tables: tuple[str, ...] = ()
    #: ``build_canvas_schema_context(canvas)`` output, when requested at resolve time.
    schema_context: str = ""

    @property
    def is_full_schema(self) -> bool:
        return not self.tables

    @property
    def eff_schema(self) -> Optional[str]:
        """The schema to PIN ``search_path`` to: the declared canvas schema, else the single
        owning schema of a schema-qualified table list (``missimi.orders`` → ``'missimi'``).
        ``None`` when nothing constrains it (full schema with no declared schema, or a
        table list spanning several schemas)."""
        if self.declared_schema:
            return self.declared_schema
        owners = {t.split(".")[0] for t in self.tables if "." in t}
        return next(iter(owners)) if len(owners) == 1 else None

    def open(self):
        """Open a live connection, pinned to ``eff_schema`` when one is resolvable."""
        from aughor.db.connection import open_connection_for, open_connection_for_with_schema

        eff = self.eff_schema
        if eff:
            return open_connection_for_with_schema(self.connection_id, schema_name=eff)
        return open_connection_for(self.connection_id)


def resolve_execution_scope(
    connection_id: str,
    canvas_id: Optional[str] = None,
    *,
    schema_scope: Optional[str] = None,
    schema_context_builder: Optional[Callable[[object], str]] = None,
) -> ExecutionScope:
    """Resolve the scope an investigation/chat/monitor runs against.

    A canvas pins its own connection + schema + table filter (canvas wins over
    ``schema_scope``). For a non-canvas run, ``schema_scope`` is honoured as the schema to
    pin. Pass ``schema_context_builder`` (a ``canvas -> str`` callable) to also populate the
    canvas's schema-context prompt block — injected rather than imported so this platform
    module never reaches into the agent layer (the Platform→Agent boundary; the router that
    owns the prompt builder passes it in).

    Fail-open: a missing or unreadable canvas degrades to the bare ``connection_id``.
    """
    declared_schema: Optional[str] = None
    tables: tuple[str, ...] = ()
    schema_context = ""
    eff_conn = connection_id

    if canvas_id:
        try:
            from aughor.canvas.store import get_canvas

            canvas = get_canvas(canvas_id)
            if canvas and canvas.scopes:
                eff_conn = canvas.primary_connection_id or connection_id
                declared_schema = canvas.scopes[0].schema_name
                tables = tuple(canvas.scopes[0].tables or [])
                if schema_context_builder is not None:
                    schema_context = schema_context_builder(canvas)
        except Exception as e:  # fail-open — a bad canvas must never break a run
            tolerate(e, "canvas scope lookup", counter="canvas_scope", canvas_id=canvas_id)
    elif schema_scope:
        # Non-canvas: an explicit schema scope pins the same way a declared canvas schema does.
        declared_schema = schema_scope

    return ExecutionScope(
        connection_id=eff_conn,
        canvas_id=canvas_id,
        declared_schema=declared_schema,
        tables=tables,
        schema_context=schema_context,
    )
