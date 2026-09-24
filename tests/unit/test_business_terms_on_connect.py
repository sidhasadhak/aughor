"""PENDING.md item 11 — a new connection's business terms proposed when it is added (ROADMAP §3.31).

The declared business terms are what lift answers (§3.15: LuxExperience 5/16 → 16/16), and a new
connection had none until a person pressed Explore. The birth rite now runs the business explorer
once per scope, behind `ontology.explore_on_connect` — on by default since 2026-09-24 (the user's
call), and switched off the rite is exactly what it was.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from aughor.routers import _shared

FLAG_ENV = "AUGHOR_ONTOLOGY_EXPLORE_ON_CONNECT"


@pytest.fixture
def seen():
    return []


def emit_into(seen):
    return lambda step, status, **detail: seen.append((step, status, detail))


@pytest.fixture
def explorer(monkeypatch):
    calls = []
    import aughor.routers.ontology as ontology
    monkeypatch.setattr(ontology, "explore_ontology",
                        lambda connection_id, schema_name=None: calls.append((connection_id, schema_name))
                        or {"run": {"id": "run123"}})
    import aughor.licensing.resolver as resolver
    monkeypatch.setattr(resolver, "has_capability", lambda cap, conn_id=None: True)
    import aughor.ontology.drafts as drafts
    monkeypatch.setattr(drafts, "load_draft", lambda conn, schema: SimpleNamespace(runs=[]))
    import aughor.ontology.store as ontology_store
    monkeypatch.setattr(ontology_store, "load_latest_ontology", lambda conn, schema=None: object())
    return calls


def test_on_by_default(monkeypatch, seen, explorer):
    monkeypatch.delenv(FLAG_ENV, raising=False)
    assert _shared.run_business_terms("c1", "shop", emit_into(seen)) == "done"
    assert explorer == [("c1", "shop")]


def test_switched_off_the_rite_is_unchanged(monkeypatch, seen, explorer):
    monkeypatch.setenv(FLAG_ENV, "0")
    assert _shared.run_business_terms("c1", "shop", emit_into(seen)) == "off"
    assert seen == [] and explorer == []                   # no step emitted, no model call


def test_on_it_explores_a_new_scope_once(monkeypatch, seen, explorer):
    monkeypatch.setenv(FLAG_ENV, "1")
    assert _shared.run_business_terms("c1", "shop", emit_into(seen)) == "done"
    assert explorer == [("c1", "shop")]
    assert [(s, st) for s, st, _ in seen] == [("business_terms", "started"), ("business_terms", "done")]
    assert seen[-1][2] == {"run_id": "run123"}


def test_a_scope_already_explored_is_skipped_so_a_restart_spends_nothing(monkeypatch, seen, explorer):
    monkeypatch.setenv(FLAG_ENV, "1")
    import aughor.ontology.drafts as drafts
    monkeypatch.setattr(drafts, "load_draft", lambda conn, schema: SimpleNamespace(runs=[object()]))
    assert _shared.run_business_terms("c1", "shop", emit_into(seen)) == "skipped"
    assert explorer == [] and seen[0][2]["reason"] == "the business explorer already ran on this scope"


def test_a_plan_without_ontology_edits_is_skipped_and_says_why(monkeypatch, seen, explorer):
    monkeypatch.setenv(FLAG_ENV, "1")
    import aughor.licensing.resolver as resolver
    monkeypatch.setattr(resolver, "has_capability", lambda cap, conn_id=None: False)
    assert _shared.run_business_terms("c1", "shop", emit_into(seen)) == "skipped"
    assert explorer == [] and "does not include ontology edits" in seen[0][2]["reason"]


def test_a_failed_explorer_is_recorded_and_the_rite_stands(monkeypatch, seen, explorer):
    monkeypatch.setenv(FLAG_ENV, "1")
    import aughor.routers.ontology as ontology

    def refuse(connection_id, schema_name=None):
        raise RuntimeError("no model configured")
    monkeypatch.setattr(ontology, "explore_ontology", refuse)
    assert _shared.run_business_terms("c1", "shop", emit_into(seen)) == "failed"
    assert seen[-1][:2] == ("business_terms", "failed") and "no model configured" in seen[-1][2]["error"]


def test_no_ontology_built_yet_is_a_skip_not_a_failure(monkeypatch, seen, explorer):
    """The first real rite (2026-09-23): the intelligence step reported done on a build that was
    a skip, and the explorer refused with a 404 — recorded as a failure it was not."""
    monkeypatch.setenv(FLAG_ENV, "1")
    import aughor.ontology.store as ontology_store
    monkeypatch.setattr(ontology_store, "load_latest_ontology", lambda conn, schema=None: None)
    assert _shared.run_business_terms("c1", "shop", emit_into(seen)) == "skipped"
    assert explorer == [] and seen[0][2]["reason"].startswith("no ontology is built on this scope yet")



def test_the_already_explored_check_reads_the_scope_the_explorer_writes(monkeypatch, seen, explorer):
    """A connection registered with a schema in its meta: the explorer files its run under that
    schema, so the skip must read it there — reading "default" never found the run (branch review)."""
    monkeypatch.setenv(FLAG_ENV, "1")
    import aughor.ontology.drafts as drafts
    import aughor.routers.ontology as ontology
    monkeypatch.setattr(ontology, "resolve_effective_schema", lambda conn, schema=None: schema or "shop")
    monkeypatch.setattr(drafts, "load_draft",
                        lambda conn, schema: SimpleNamespace(runs=[object()] if schema == "shop" else []))
    assert _shared.run_business_terms("c1", None, emit_into(seen)) == "skipped"
    assert explorer == []
