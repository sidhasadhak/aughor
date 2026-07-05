"""Unit tests for the one execution-scope value object (NOM-11) — `aughor/canvas/scope.py`.

The four hand-rolled canvas-scope blocks in `routers/investigations.py` collapse onto
`resolve_execution_scope` / `ExecutionScope`. These pin the precedence the router code
relied on — and the derivation the salvage + resume paths used to omit (the sibling-schema
leak this consolidation closes).
"""
from __future__ import annotations

from aughor.canvas.models import Canvas, CanvasScope
from aughor.canvas.scope import ExecutionScope, resolve_execution_scope


# ── eff_schema derivation — the precedence in one place ──────────────────────────────────

def test_declared_schema_wins():
    s = ExecutionScope(connection_id="c", canvas_id="cv", declared_schema="sales", tables=("other.orders",))
    assert s.eff_schema == "sales"       # declared beats any table-derived owner


def test_single_owning_schema_derived_from_table_list():
    # A table-list-scoped canvas with schema-qualified names + no declared schema:
    # derive the single owning schema so search_path pins (the leak fix).
    s = ExecutionScope(connection_id="c", canvas_id="cv", tables=("missimi.orders", "missimi.customers"))
    assert s.declared_schema is None
    assert s.eff_schema == "missimi"


def test_multi_schema_table_list_does_not_pin():
    s = ExecutionScope(connection_id="c", tables=("a.orders", "b.orders"))
    assert s.eff_schema is None          # ambiguous → pin nothing


def test_full_schema_with_no_declared_schema_pins_nothing():
    s = ExecutionScope(connection_id="c", canvas_id="cv")
    assert s.is_full_schema is True
    assert s.eff_schema is None


def test_unqualified_table_names_do_not_derive_a_schema():
    s = ExecutionScope(connection_id="c", tables=("orders", "customers"))
    assert s.eff_schema is None


# ── resolve_execution_scope: canvas precedence ───────────────────────────────────────────

def _canvas(monkeypatch, canvas):
    monkeypatch.setattr("aughor.canvas.store.get_canvas", lambda _id: canvas)


def test_resolve_pins_canvas_connection_schema_and_tables(monkeypatch):
    cv = Canvas(id="cv1", name="Missimi",
                scopes=[CanvasScope(connection_id="conn_missimi", schema_name="missimi",
                                    tables=["missimi.orders"])])
    _canvas(monkeypatch, cv)
    s = resolve_execution_scope("conn_passed", "cv1")
    assert s.connection_id == "conn_missimi"   # canvas's primary connection wins
    assert s.declared_schema == "missimi"
    assert s.tables == ("missimi.orders",)
    assert s.eff_schema == "missimi"


def test_resolve_derives_schema_when_canvas_declares_none(monkeypatch):
    # The exact salvage/resume gap: schema_name=None but a schema-qualified table list.
    cv = Canvas(id="cv2", name="Missimi",
                scopes=[CanvasScope(connection_id="conn", schema_name=None,
                                    tables=["missimi.orders", "missimi.line_items"])])
    _canvas(monkeypatch, cv)
    s = resolve_execution_scope("conn", "cv2")
    assert s.declared_schema is None
    assert s.eff_schema == "missimi"           # would have been None before the consolidation


def test_resolve_non_canvas_honours_schema_scope():
    s = resolve_execution_scope("conn", None, schema_scope="analytics")
    assert s.declared_schema == "analytics"
    assert s.eff_schema == "analytics"


def test_resolve_non_canvas_no_scope_is_bare():
    s = resolve_execution_scope("conn", None)
    assert s.canvas_id is None
    assert s.declared_schema is None
    assert s.eff_schema is None
    assert s.is_full_schema is True


def test_canvas_wins_over_schema_scope(monkeypatch):
    cv = Canvas(id="cv3", name="X",
                scopes=[CanvasScope(connection_id="conn", schema_name="sales", tables=[])])
    _canvas(monkeypatch, cv)
    s = resolve_execution_scope("conn", "cv3", schema_scope="ignored")
    assert s.eff_schema == "sales"             # a canvas ignores the non-canvas schema_scope


def test_resolve_fail_open_when_canvas_lookup_raises(monkeypatch):
    def boom(_id):
        raise RuntimeError("store down")
    monkeypatch.setattr("aughor.canvas.store.get_canvas", boom)
    s = resolve_execution_scope("conn", "cv_bad")   # must not raise
    assert s.connection_id == "conn"
    assert s.eff_schema is None


def test_resolve_builds_schema_context_only_when_requested(monkeypatch):
    cv = Canvas(id="cv4", name="X",
                scopes=[CanvasScope(connection_id="conn", schema_name="s", tables=["s.t"])])
    _canvas(monkeypatch, cv)
    monkeypatch.setattr("aughor.tools.schema.build_canvas_schema_context", lambda c: f"CTX:{c.id}")
    assert resolve_execution_scope("conn", "cv4").schema_context == ""             # off by default
    assert resolve_execution_scope("conn", "cv4", with_schema_context=True).schema_context == "CTX:cv4"


# ── .open() branches on eff_schema ───────────────────────────────────────────────────────

def test_open_pins_schema_when_resolvable(monkeypatch):
    calls = {}
    monkeypatch.setattr("aughor.db.connection.open_connection_for_with_schema",
                        lambda cid, schema_name=None: calls.setdefault("pinned", (cid, schema_name)) or "DB")
    monkeypatch.setattr("aughor.db.connection.open_connection_for",
                        lambda cid: calls.setdefault("plain", cid) or "DB")
    ExecutionScope(connection_id="conn", declared_schema="sales").open()
    assert calls == {"pinned": ("conn", "sales")}


def test_open_plain_when_no_eff_schema(monkeypatch):
    calls = {}
    monkeypatch.setattr("aughor.db.connection.open_connection_for_with_schema",
                        lambda cid, schema_name=None: calls.setdefault("pinned", True) or "DB")
    monkeypatch.setattr("aughor.db.connection.open_connection_for",
                        lambda cid: calls.setdefault("plain", cid) or "DB")
    ExecutionScope(connection_id="conn").open()
    assert calls == {"plain": "conn"}
