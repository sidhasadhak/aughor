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

    # The read path must never open a connection at all — see
    # `test_a_read_never_builds` below.
    def _no_build(*a, **kw):
        raise AssertionError("the ontology READ opened a connection — it must not")

    monkeypatch.setattr(router, "open_connection_for", _no_build)
    monkeypatch.setattr("aughor.ontology.store.list_schemas", lambda cid: sorted(entries))
    return entries


def test_named_schema_never_answers_with_a_neighbour(cache, monkeypatch):
    cache["ecommerce"] = _Graph("ecommerce")
    cache["main"] = _Graph("main")
    monkeypatch.setattr(router, "get_meta", lambda cid: {"schema_name": "main"})

    assert router._get_ontology_graph("c1", "ecommerce").schema_name == "ecommerce"
    assert router._get_ontology_graph("c1", "main").schema_name == "main"


def test_uncached_named_schema_never_answers_with_one_of_several(cache, monkeypatch):
    """The headline defect. `sales` is not built; two others are. Serving one of them
    under the name `sales` is worse than a 404: a wrong answer that looks right."""
    cache["ecommerce"] = _Graph("ecommerce")
    cache["main"] = _Graph("main")
    monkeypatch.setattr(router, "get_meta", lambda cid: {"schema_name": "ecommerce"})

    assert router._get_ontology_graph("c1", "sales") is None


def test_the_only_cached_ontology_answers_whatever_it_is_called(cache, monkeypatch):
    """The vocabulary mismatch that broke the panel outright: the schema NAME the UI
    asks with comes from the catalog tree, the cache key from whoever built it. A
    gsheets connection is browsed as `spotify` and cached as `default`. With exactly
    one cached ontology there is no other schema to confuse it with, so answering is
    not a leak — and the graph reports its own `schema_name`, which is what the panel
    prints."""
    cache["default"] = _Graph("default")
    monkeypatch.setattr(router, "get_meta", lambda cid: {})

    assert router._get_ontology_graph("c1", "spotify").schema_name == "default"


def test_a_read_never_builds(cache, monkeypatch):
    """`GET /ontology?connection_id=workspace&schema_name=main` used to fall through to
    `build_intelligence()` and never return — the panel showed nothing for as long as
    anyone waited. Nothing cached must now mean an immediate None, not a build. The
    fixture's `open_connection_for` asserts if this path opens a connection."""
    monkeypatch.setattr(router, "get_meta", lambda cid: {"schema_name": "main"})

    assert router._get_ontology_graph("c1", "main") is None
    assert router._get_ontology_graph("c1", None) is None


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


# ── The skills key resolver has the same rule ────────────────────────────────

def test_skill_schema_prefers_the_configured_schema(monkeypatch):
    """`/ontology/skills` keys learned skills by schema. It resolved that key through
    `load_latest_ontology(id, None)` — the arbitrary last cache entry — so on the live
    instance it answered `ecommerce` for a connection registered against `main`. A skill
    saved under one schema and read back under another is a skill that disappears."""
    from aughor.memory import skills

    entries = {"main": _Graph("main"), "ecommerce": _Graph("ecommerce")}

    def _load_latest(connection_id, schema_name=None):
        if schema_name:
            return entries.get(schema_name)
        return list(entries.values())[-1]

    monkeypatch.setattr("aughor.ontology.store.load_latest_ontology", _load_latest)
    monkeypatch.setattr("aughor.db.registry.get_meta", lambda cid: {"schema_name": "main"})

    assert skills.resolve_active_schema("c1") == "main"


def test_skill_schema_still_answers_when_the_configured_one_is_unbuilt(monkeypatch):
    from aughor.memory import skills

    entries = {"ecommerce": _Graph("ecommerce")}
    monkeypatch.setattr(
        "aughor.ontology.store.load_latest_ontology",
        lambda cid, schema_name=None: entries.get(schema_name) if schema_name
        else (list(entries.values())[-1] if entries else None))
    monkeypatch.setattr("aughor.db.registry.get_meta", lambda cid: {"schema_name": "main"})

    assert skills.resolve_active_schema("c1") == "ecommerce"
