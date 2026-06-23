"""Canonical key normalisation (routers/_shared.canonical_schema).

A single-schema connection has one user schema == the connection, so it must ALWAYS use the
bare key — otherwise an explicit ?schema= splits state between {conn} and {conn}__{schema},
the inconsistency behind the wedge / coverage / stop symptoms. Best-effort on lookup failure.
"""
from __future__ import annotations

import aughor.routers._shared as sh


def test_none_schema_is_bare():
    assert sh.canonical_schema("c", None) is None
    assert sh.canonical_schema("c", "") is None


def test_single_schema_normalises_to_bare(monkeypatch):
    monkeypatch.setattr(sh, "schemas_of_connection", lambda c: ["missimi"])
    assert sh.canonical_schema("workspace", "missimi") is None   # the only schema → bare key


def test_multi_schema_keeps_the_explicit_schema(monkeypatch):
    monkeypatch.setattr(sh, "schemas_of_connection", lambda c: ["missimi", "ecommerce"])
    assert sh.canonical_schema("workspace", "missimi") == "missimi"


def test_lookup_failure_leaves_schema_unchanged(monkeypatch):
    def _boom(c):
        raise RuntimeError("db down")
    monkeypatch.setattr(sh, "schemas_of_connection", _boom)
    assert sh.canonical_schema("workspace", "missimi") == "missimi"   # safe fallback
