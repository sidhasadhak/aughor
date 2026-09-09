"""An explicit `schema_name` is a SCOPE, not a hint.

`/ontology` (and every route that reads through `_get_ontology_graph`) used to fall
back to `load_latest_ontology(connection_id, None)` — "whatever schema was cached
last" — when the requested schema had no cached graph. Measured against the live
instance before the fix:

    GET /ontology?connection_id=baef6c3e&schema_name=no_such_schema_xyz
    → {"schema_name": "ecommerce", entities: Customer, Order, Product, …}

so a panel asking for one schema could be handed a neighbour's entities,
relationships, metrics and actions with nothing on screen saying so. The rule these
tests pin: a request that NAMES a schema either gets that schema or gets nothing.
"""
from __future__ import annotations

import pytest

from aughor.routers import ontology as router


class _Graph:
    """Just enough of an OntologyGraph for the resolution path."""

    def __init__(self, schema_name: str):
        self.schema_name = schema_name


@pytest.fixture
def cache(monkeypatch):
    """A fake ontology cache: {schema_name: graph}, plus the any-schema search."""
    entries: dict[str, _Graph] = {}

    def _load_latest(connection_id: str, schema_name=None):
        if schema_name:
            return entries.get(schema_name)
        # The real store scans by connection prefix and returns the LAST entry —
        # i.e. an arbitrary schema. Model that, because it is what used to leak.
        return list(entries.values())[-1] if entries else None

    monkeypatch.setattr("aughor.ontology.store.load_latest_ontology", _load_latest)

    # No cache hit must ever reach a real database in these tests: the build path is
    # heavy (profiles + enrichment) and is not what is under test here.
    def _no_build(*a, **kw):
        raise RuntimeError("build path — no connection in this test")

    monkeypatch.setattr(router, "open_connection_for", _no_build)
    return entries


def test_named_schema_never_answers_with_a_neighbour(cache, monkeypatch):
    cache["ecommerce"] = _Graph("ecommerce")
    cache["main"] = _Graph("main")
    monkeypatch.setattr(router, "get_meta", lambda cid: {"schema_name": "main"})

    assert router._get_ontology_graph("c1", "ecommerce").schema_name == "ecommerce"
    assert router._get_ontology_graph("c1", "main").schema_name == "main"


def test_uncached_named_schema_returns_nothing_rather_than_another(cache, monkeypatch):
    """The headline defect. `sales` is not built; `ecommerce` is. Serving
    `ecommerce` under the name `sales` is worse than a 404: it is a wrong answer
    that looks like a right one."""
    cache["ecommerce"] = _Graph("ecommerce")
    monkeypatch.setattr(router, "get_meta", lambda cid: {"schema_name": "ecommerce"})

    assert router._get_ontology_graph("c1", "sales") is None


def test_unscoped_read_prefers_the_connections_own_schema(cache, monkeypatch):
    """With no scope asked for, the connection's CONFIGURED schema wins over the
    arbitrary last-written cache entry. Live before the fix: `/ontology/skills` on a
    connection whose registered schema is `main` reported `schema_name: ecommerce`,
    purely because that entry was written last."""
    cache["main"] = _Graph("main")
    cache["ecommerce"] = _Graph("ecommerce")      # written last — the old winner
    monkeypatch.setattr(router, "get_meta", lambda cid: {"schema_name": "main"})

    assert router._get_ontology_graph("c1", None).schema_name == "main"


def test_unscoped_read_still_falls_back_when_nothing_matches(cache, monkeypatch):
    """Legacy callers that genuinely do not know a schema keep working: with no
    entry under the configured name, any cached schema is better than a 404."""
    cache["ecommerce"] = _Graph("ecommerce")
    monkeypatch.setattr(router, "get_meta", lambda cid: {"schema_name": "main"})

    assert router._get_ontology_graph("c1", None).schema_name == "ecommerce"
