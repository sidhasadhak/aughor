"""Removing a connection — or one dataset of it — takes its ontology, its metrics and its documentation.

The user, 2026-10-11: "Removing a connection means also removing its ontology, its metrics and related documents..
make that default". Measured that day: five removed connections' accepted ontology overrides were still in the
checkout (where no sweep of the state directory reaches), and a removed dataset kept every ontology tree, ~250
documentation files, its indexed "Schema documentation" and four metrics.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def trees(tmp_path, monkeypatch):
    """Every ontology tree under tmp, each at the root its own module resolves — and a shipped seed beside them."""
    from aughor.knowledge import indexer
    from aughor.ontology import context_graph_store, drafts, overrides, recommendations

    roots = {name: tmp_path / name for name in ("overrides", "overrides_draft", "drafts", "recommendations",
                                                "docs", "column_config", "context_graph", "seed")}
    monkeypatch.setattr(overrides, "_ROOT", roots["overrides"])
    monkeypatch.setattr(overrides, "_DRAFT_ROOT", roots["overrides_draft"])
    monkeypatch.setattr(overrides, "_SEED_ROOT", roots["seed"])
    monkeypatch.setattr(drafts, "_ROOT", roots["drafts"])
    monkeypatch.setattr(recommendations, "_ROOT", roots["recommendations"])
    monkeypatch.setenv("AUGHOR_ONTOLOGY_DOCS_DIR", str(roots["docs"]))
    monkeypatch.setenv("AUGHOR_COLUMN_CONFIG_ROOT", str(roots["column_config"]))
    monkeypatch.setattr(context_graph_store, "_ROOT", roots["context_graph"])
    unregistered: list[str] = []
    monkeypatch.setattr(indexer, "delete_document", lambda doc_id: unregistered.append(doc_id) or True)
    monkeypatch.setattr(indexer, "purge_connection_doctrees", lambda conn: unregistered.append(f"all:{conn}") or 2)

    def seed(conn: str, dataset: str) -> None:
        for key in ("overrides", "overrides_draft", "recommendations", "docs", "column_config", "seed"):
            (roots[key] / conn / dataset / "entity").mkdir(parents=True)
            (roots[key] / conn / dataset / "entity" / "Order.yaml").write_text("x: 1")
        (roots["drafts"] / conn).mkdir(parents=True, exist_ok=True)
        (roots["drafts"] / conn / f"{dataset}.yaml").write_text("x: 1")
        (roots["context_graph"] / "default" / conn).mkdir(parents=True, exist_ok=True)
        (roots["context_graph"] / "default" / conn / f"{dataset}.json").write_text("{}")

    for conn, dataset in (("workspace", "luxexperience"), ("workspace", "main"), ("other", "luxexperience")):
        seed(conn, dataset)
    return roots, unregistered


def _left(roots, conn: str) -> dict[str, list[str]]:
    out = {}
    for key, root in roots.items():
        base = root / ("default" if key == "context_graph" else "") / conn if key == "context_graph" else root / conn
        out[key] = sorted(p.name for p in base.iterdir()) if base.exists() else []
    return out


def test_a_removed_dataset_takes_its_ontology_trees_and_its_documentation_and_nothing_else(trees):
    from aughor.ontology.removal import purge

    roots, unregistered = trees
    got = purge("workspace", "luxexperience")
    assert got == {"ontology_trees": 6, "context_graph": 1, "schema_docs": 1}
    left = _left(roots, "workspace")
    assert all(names in (["main"], ["main.yaml"], ["main.json"]) for key, names in left.items() if key != "seed")
    assert left["seed"] == ["luxexperience", "main"]                           # the shipped layer is never touched
    assert _left(roots, "other")["overrides"] == ["luxexperience"]             # another connection's stays
    assert unregistered == ["doctree::workspace::luxexperience"]


def test_a_removed_connection_takes_every_tree_it_has(trees):
    from aughor.ontology.removal import purge

    roots, unregistered = trees
    got = purge("workspace")
    assert got == {"ontology_trees": 6, "context_graph": 1, "schema_docs": 2}
    assert {k: v for k, v in _left(roots, "workspace").items() if k != "seed"} == {
        k: [] for k in roots if k != "seed"}
    assert _left(roots, "workspace")["seed"] == ["luxexperience", "main"]
    assert unregistered == ["all:workspace"]
    assert purge("workspace") == {"ontology_trees": 0, "context_graph": 0, "schema_docs": 2}   # idempotent


@pytest.fixture
def metrics(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGHOR_METRICS_PATH", str(tmp_path / "metrics.instance.json"))
    monkeypatch.setenv("AUGHOR_METRICS_SEED_PATH", str(tmp_path / "seed_metrics.json"))
    from aughor.semantic.metrics import MetricDefinition, save_metric

    def add(name, conn, sql, schema=None):
        save_metric(MetricDefinition(name=name, connection=conn, label=name, sql=sql, tables=[], schema_name=schema))

    add("aov", "workspace", "SELECT SUM(gmv_eur) / COUNT(order_id) FROM luxexperience.orders", "luxexperience")
    add("csat", "workspace", "SELECT AVG(csat) FROM luxexperience.customer_service")       # its SQL names it
    add("revenue", "workspace", "SELECT SUM(price) FROM main.sales", "main")
    add("everywhere", "workspace", "SELECT 1", "*")                                         # promoted to the connection
    add("aov", "other", "SELECT SUM(gmv_eur) / COUNT(order_id) FROM luxexperience.orders", "luxexperience")
    add("global_one", "*", "SELECT 1")


def _names(conn):
    from aughor.semantic.metrics import list_metrics
    return sorted(m.name for m in list_metrics() if m.connection == conn)


def test_a_removed_dataset_takes_its_metrics_the_connection_keeps_its_own(metrics):
    from aughor.semantic.metrics import purge_scope

    assert purge_scope("workspace", "luxexperience") == 2
    assert _names("workspace") == ["everywhere", "revenue"]
    assert _names("other") == ["aov"] and _names("*") == ["global_one"]


def test_a_removed_connection_takes_every_metric_it_owns_and_no_one_elses(metrics):
    from aughor.semantic.metrics import purge_scope

    assert purge_scope("workspace") == 4
    assert _names("workspace") == []
    assert _names("other") == ["aov"] and _names("*") == ["global_one"]
    assert purge_scope("*") == 0                                               # the install's global layer: never


def test_the_purges_run_on_every_removal(trees, metrics):
    """Registered where every removal runs them: a connection delete and a schema delete."""
    from aughor.kernel.registries import purge_hooks

    names = purge_hooks.registered_hook_names()
    assert {"ontology_trees", "metrics"} <= set(names["conn"])
    assert {"ontology_trees", "metrics"} <= set(names["schema"])
    got = purge_hooks.run_schema_purge_hooks("workspace", "luxexperience")
    assert got["ontology_trees"] == 6 and got["metrics"] == 2


def test_a_removed_dataset_is_cleared_through_its_door_and_a_listed_one_is_not(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from aughor import govern
    from aughor.db import purge, registry
    from aughor.routers import catalog
    from aughor.routers import connections as R

    app = FastAPI()
    app.include_router(R.router)
    client = TestClient(app)
    guarded = []
    monkeypatch.setattr(registry, "is_registered", lambda c: c == "workspace")
    monkeypatch.setattr(registry, "get_conn_type", lambda c: "local_upload")
    listed = {"value": [{"name": "main"}]}
    monkeypatch.setattr(catalog, "quick_schemas", lambda c, t: listed["value"])
    monkeypatch.setattr(govern, "guard", lambda action, scope="", **k: guarded.append((action, scope)))
    monkeypatch.setattr(purge, "purge_schema_artifacts",
                        lambda c, s: {"ontology_trees": 6, "metrics": 4, "profile": 1, "canvases": 0})

    assert client.post("/connections/workspace/schemas/main/purge").status_code == 409
    assert client.post("/connections/gone/schemas/x/purge").status_code == 404
    listed["value"] = None
    assert client.post("/connections/workspace/schemas/luxexperience/purge").status_code == 503
    assert guarded == []                                                       # every refusal before the gate
    listed["value"] = [{"name": "main"}]
    got = client.post("/connections/workspace/schemas/luxexperience/purge").json()
    assert guarded == [("connection.schema.delete", "workspace:luxexperience")]
    assert got["removed"] == {"ontology_trees": 6, "metrics": 4} and got["invalidated"] == ["profile"]
