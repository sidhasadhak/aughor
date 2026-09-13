"""A rebuild builds, and a rebuild that fails keeps the ontology it meant to replace.

`POST /ontology/rebuild` used to DELETE the cached graph and then read it back through `_get_ontology_graph`, the read
that by design never builds. "Rebuild ontology now" on a working ontology destroyed it and answered 422, or, on a
connection with exactly one OTHER schema cached, answered 200 with that schema's graph under the requested name. The
hourly auto-refresh deleted the same way and then called the fast `get_schema()`, which builds nothing either.

Hermetic: the ontology cache is a temp `KeyedJsonStore` (conftest does not redirect `data/ontology_cache.json`), the
connection is a fake whose `build_intelligence` does to the store what the heavy annotators do, and nothing opens a
warehouse or calls a model.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from aughor.ontology import overrides as OV
from aughor.ontology import store as ST
from aughor.ontology.models import OntologyGraph
from aughor.routers import ontology as router
from aughor.util.json_store import KeyedJsonStore

CONN = "rebuild-t"
OLD = "2020-01-01T00:00:00+00:00"


def _graph(schema: str, *, generated_at: str | None = None, fingerprint: str = "fp",
           connection_id: str = CONN) -> OntologyGraph:
    fields = {"connection_id": connection_id, "schema_name": schema, "schema_fingerprint": fingerprint}
    if generated_at:
        fields["generated_at"] = generated_at
    return OntologyGraph(**fields)


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A temp ontology cache, no overrides or learned actions, no schema-cache side effects, a recorded profile."""
    monkeypatch.setattr(OV, "_ROOT", tmp_path / "ontology_overrides")
    monkeypatch.setattr(ST, "_store", KeyedJsonStore(tmp_path / "onto_cache.json", max_entries=20))
    monkeypatch.setattr("aughor.memory.skills.load_learned_actions", lambda connection_id, schema_name: {})
    monkeypatch.setattr(router, "get_meta", lambda cid: {"schema_name": "main"})
    monkeypatch.setattr(router, "_invalidate_schema_cache", lambda cid: None)
    monkeypatch.setattr("aughor.db.registry.get_dsn", lambda cid: ("duckdb", "/data/warehouse.duckdb"))
    profiles: list[tuple[str, str]] = []

    def _infer(connection_id, schema_name):
        profiles.append((connection_id, schema_name))
        return SimpleNamespace(industry="retail")

    monkeypatch.setattr("aughor.business_profile.infer.infer_business_profile", _infer)
    monkeypatch.setattr("aughor.orgsettings.resolve_industry", lambda industry: industry)
    return SimpleNamespace(profiles=profiles)


class _FakeDB:
    """A pooled connection as the rebuild sees it; records whether the force reached its build."""

    def __init__(self, schema_name, build):
        self._connection_id = CONN
        self._schema_name = schema_name
        self._build = build
        self.last_build = None
        self.forced = None
        self.closed = False

    def build_intelligence(self):
        self.forced = ST.rebuild_forced(CONN)
        return self._build(self)

    def close(self):
        self.closed = True


def _opens(monkeypatch, build) -> list[tuple[str | None, _FakeDB]]:
    """Every open the rebuild makes resolves to a fake; returns (the scope asked for, the connection) per open."""
    opened: list[tuple[str | None, _FakeDB]] = []

    def _open(connection_id, schema_name=None):
        db = _FakeDB(schema_name, build)
        opened.append((schema_name, db))
        return db

    monkeypatch.setattr("aughor.db.connection.open_connection_for_with_schema", _open)
    return opened


def _saves(graph: OntologyGraph, *, error: str | None = None):
    """A build that does what the heavy annotators do on success: save the graph and record an ok build."""
    def build(db):
        ST.save_ontology(CONN, db._schema_name or "default", graph.schema_fingerprint, graph)
        db.last_build = {"ok": True, "stage": "enrichment" if error else None, "error": error}
        return "SCHEMA"
    return build


def _fails(stage: str, error: str):
    def build(db):
        db.last_build = {"ok": False, "stage": stage, "error": error}
        return "SCHEMA"
    return build


def _rebuild(schema_name: str | None = "main"):
    return router.rebuild_ontology(connection_id=CONN, schema_name=schema_name)


# ── The route ──────────────────────────────────────────────────────────────────

def test_a_rebuild_builds_and_answers_with_the_graph_it_built(env, monkeypatch):
    ST.save_ontology(CONN, "main", "fp", _graph("main", generated_at=OLD))
    new = _graph("main")
    opened = _opens(monkeypatch, _saves(new))

    out = _rebuild()

    [(scope, db)] = opened
    assert scope == "main" and db.forced is True and db.closed
    assert out["ok"] is True and out["schema_name"] == "main" and "warning" not in out
    assert out["generated_at"] == new.generated_at != OLD
    assert ST.load_latest_ontology(CONN, "main").generated_at == new.generated_at
    assert env.profiles == [(CONN, "main")]      # the business profile follows a real build, once


def test_a_failed_build_keeps_the_previous_ontology(env, monkeypatch):
    ST.save_ontology(CONN, "main", "fp", _graph("main", generated_at=OLD))
    _opens(monkeypatch, _fails("ontology", "too sparse to model"))

    with pytest.raises(HTTPException) as err:
        _rebuild()

    assert err.value.status_code == 422
    assert "stopped at ontology: too sparse to model" in err.value.detail
    assert err.value.detail.endswith("The previous ontology is unchanged.")
    assert ST.load_latest_ontology(CONN, "main").generated_at == OLD
    assert env.profiles == []                    # no model call after a build that produced nothing


def test_a_build_that_raises_keeps_the_previous_ontology(env, monkeypatch):
    ST.save_ontology(CONN, "main", "fp", _graph("main", generated_at=OLD))

    def build(db):
        raise RuntimeError("the warehouse went away")

    opened = _opens(monkeypatch, build)

    with pytest.raises(HTTPException) as err:
        _rebuild()

    assert err.value.status_code == 422 and "the warehouse went away" in err.value.detail
    assert opened[0][1].closed
    assert ST.load_latest_ontology(CONN, "main").generated_at == OLD


def test_a_rebuild_never_answers_with_another_schemas_graph(env, monkeypatch):
    """The read serves the ONLY cached ontology whatever it is asked for (a gsheets connection is browsed as
    `spotify` and cached as `default`). The old rebuild read back through that substitution, so a build that saved
    nothing for `main` answered 200 with `default`'s graph. A rebuild reads back only the schema it built."""
    ST.save_ontology(CONN, "default", "fp", _graph("default", generated_at=OLD))
    _opens(monkeypatch, lambda db: setattr(db, "last_build", {"ok": True, "stage": None, "error": None}))

    assert router._get_ontology_graph(CONN, "main").schema_name == "default"   # the read's substitution, as designed
    with pytest.raises(HTTPException) as err:
        _rebuild()

    assert err.value.status_code == 422
    assert "without saving a new graph" in err.value.detail
    assert "unchanged" not in err.value.detail   # `main` had nothing to keep
    assert env.profiles == []


def test_a_build_that_saves_nothing_new_is_not_a_rebuild(env, monkeypatch):
    """A build that ran and left the cached graph as it was must not be reported as a rebuild."""
    ST.save_ontology(CONN, "main", "fp", _graph("main", generated_at=OLD))
    _opens(monkeypatch, lambda db: setattr(db, "last_build", {"ok": True, "stage": None, "error": None}))

    with pytest.raises(HTTPException) as err:
        _rebuild()

    assert "without saving a new graph" in err.value.detail
    assert err.value.detail.endswith("The previous ontology is unchanged.")
    assert ST.load_latest_ontology(CONN, "main").generated_at == OLD


def test_a_built_graph_whose_enrichment_failed_says_what_it_lacks(env, monkeypatch):
    new = _graph("main")
    _opens(monkeypatch, _saves(new, error="semantic enrichment failed (ontology still usable): rate limited"))

    out = _rebuild()

    assert out["ok"] is True and out["generated_at"] == new.generated_at
    assert out["warning"].startswith("semantic enrichment failed")


def test_an_in_memory_upload_says_why_and_journals_the_failure(env, monkeypatch):
    ST.save_ontology(CONN, "main", "fp", _graph("main", generated_at=OLD))
    monkeypatch.setattr("aughor.db.registry.get_dsn", lambda cid: ("local_upload", "local://upload-1"))
    # Re-opened empty: `build_intelligence` returns before any annotator runs, so nothing journals the build.
    _opens(monkeypatch, lambda db: "No tables")

    with pytest.raises(HTTPException) as err:
        _rebuild()

    assert "in-memory file upload" in err.value.detail
    assert err.value.detail.endswith("The previous ontology is unchanged.")
    # The build never journaled itself, so the route did. The ledger is conftest's per-session temp system.db.
    from aughor.kernel.ledger import Ledger
    journaled = [e["payload"] for e in Ledger.default().events(kind="ontology.build", conn_id=CONN, limit=50)]
    assert any(p.get("stage") == "rebuild" and p.get("in_memory") is True for p in journaled)
    assert ST.load_latest_ontology(CONN, "main").generated_at == OLD


def test_the_default_placeholder_opens_the_connection_unscoped(env, monkeypatch):
    """`_resolve_schema` answers "default" when the connection has no schema. That is a word for none, not a schema
    to scope the connection to; the birth job opens such a connection unscoped too."""
    monkeypatch.setattr(router, "get_meta", lambda cid: {})
    opened = _opens(monkeypatch, _saves(_graph("default")))

    out = _rebuild(None)

    assert opened[0][0] is None and out["schema_name"] == "default"


# ── The store ──────────────────────────────────────────────────────────────────

def test_a_forced_rebuild_skips_the_fingerprint_cache_for_its_own_connection_only(env, monkeypatch):
    tables = {"orders": SimpleNamespace(row_count=10, grain_column="order_id")}
    fp = ST.compute_ontology_fingerprint(tables)
    ST.save_ontology(CONN, "main", fp, _graph("main", generated_at=OLD, fingerprint=fp))
    extracted: list[str] = []

    def _extract(**kw):
        extracted.append(kw["connection_id"])
        return _graph(kw["schema_name"], fingerprint=kw["schema_fingerprint"])

    monkeypatch.setattr("aughor.ontology.builder.extract_structural_ontology", _extract)

    def build():
        return ST.get_or_build_ontology(CONN, "main", tables, {}, {}, {})

    assert build().generated_at == OLD and extracted == []          # unforced, the cache answers
    with ST.forced_rebuild("another-connection"):
        assert build().generated_at == OLD and extracted == []      # another connection's rebuild is not this one
    with ST.forced_rebuild(CONN):
        fresh = build()
    assert extracted == [CONN] and fresh.generated_at != OLD
    assert ST.load_latest_ontology(CONN, "main").generated_at == fresh.generated_at   # saved over the same key
    assert not ST.rebuild_forced(CONN)                                 # the force ended with its block


# ── The auto-refresh ───────────────────────────────────────────────────────────

def test_the_auto_refresh_picks_only_ontologies_past_their_interval(env, monkeypatch):
    import aughor.api as api
    now = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)
    ST.save_ontology(CONN, "main", "fp", _graph("main", generated_at=(now - timedelta(hours=30)).isoformat()))
    ST.save_ontology(CONN, "sales", "fp", _graph("sales", generated_at=(now - timedelta(hours=2)).isoformat()))
    ST.save_ontology("no-interval", "main", "fp",
                     _graph("main", connection_id="no-interval", generated_at=(now - timedelta(days=9)).isoformat()))
    monkeypatch.setattr(api, "list_connections", lambda: [{"id": CONN}, {"id": "no-interval"}])
    monkeypatch.setattr(api, "get_connection_settings",
                        lambda cid: {"ontology_refresh_hours": 24} if cid == CONN else {})

    assert api._ontology_refreshes_due(now) == [(CONN, "main")]


@pytest.mark.anyio
async def test_the_auto_refresh_rebuilds_instead_of_deleting(env, monkeypatch):
    import aughor.api as api
    ST.save_ontology(CONN, "main", "fp", _graph("main", generated_at=OLD))
    monkeypatch.setattr(api, "list_connections", lambda: [{"id": CONN}])
    monkeypatch.setattr(api, "get_connection_settings", lambda cid: {"ontology_refresh_hours": 1})

    _opens(monkeypatch, _fails("profiling", "statement timeout"))
    await api._refresh_ontologies_once()
    assert ST.load_latest_ontology(CONN, "main").generated_at == OLD   # a failed refresh keeps the ontology

    new = _graph("main")
    _opens(monkeypatch, _saves(new))
    await api._refresh_ontologies_once()
    assert ST.load_latest_ontology(CONN, "main").generated_at == new.generated_at
