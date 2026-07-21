"""A QUICK answer must be pinned to the selected schema, exactly as a deep one is.

`AskRequest.schema_name` was forwarded only on the deep branch. The quick branch called
`_stream_chat(...)` — which had no schema parameter at all — and its `resolve_execution_scope`
call omitted `schema_scope`, so nothing constrained the run. On a multi-schema connection an
unqualified `FROM orders` could then resolve against a sibling schema's same-named table
(the "missimi silently answering from netflix" failure the scope resolver exists to prevent).

Side effect of the same gap: a user-defined agent's `schema_scope` binding did not constrain
a quick answer either.
"""
from __future__ import annotations

import inspect

from aughor.canvas.scope import resolve_execution_scope
from aughor.routers.investigations import _stream_chat


def test_stream_chat_accepts_a_schema_scope():
    assert "schema_scope" in inspect.signature(_stream_chat).parameters


def test_quick_branch_forwards_the_requested_schema():
    """Guards the wiring itself — the gap was a dropped argument, not broken logic."""
    src = inspect.getsource(inspect.getmodule(_stream_chat))
    assert "schema_scope=req.schema_name" in src


def test_stream_chat_hands_the_scope_to_the_resolver():
    assert "schema_scope=schema_scope" in inspect.getsource(_stream_chat)


# ── The platform behaviour the wiring now reaches ─────────────────────────────


def test_explicit_schema_pins_a_non_canvas_run():
    scope = resolve_execution_scope("workspace", None, schema_scope="netflix")
    assert scope.declared_schema == "netflix"
    assert scope.connection_id == "workspace"


def test_no_schema_leaves_the_run_unpinned():
    assert resolve_execution_scope("workspace", None).declared_schema is None


def test_two_schemas_resolve_to_two_distinct_scopes():
    a = resolve_execution_scope("workspace", None, schema_scope="netflix")
    b = resolve_execution_scope("workspace", None, schema_scope="luxexperience")
    assert a.declared_schema != b.declared_schema
