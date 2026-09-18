"""The catalogue doors: per-connection listing, and copy-on-write before edit.

`GET /metrics` used to call `list_metrics()` with no argument, so the Metrics sub-tab
showed every metric on every connection — the gap behind the 2026-09-18 request for a
"per connection list of metrics". The argument exists and always did; the door did not
pass it.
"""
import pytest
from fastapi.testclient import TestClient

from aughor.api import app
from aughor.semantic import metric_catalogue as MC


@pytest.fixture
def client():
    return TestClient(app)


class TestTheListNarrows:
    def test_the_door_passes_the_connection_through(self, client, monkeypatch):
        seen = {}

        def _fake(path=None, connection_id=None):
            seen["connection_id"] = connection_id
            return []
        monkeypatch.setattr("aughor.routers.metrics.list_metrics", _fake)
        assert client.get("/metrics?connection_id=abc123").status_code == 200
        assert seen["connection_id"] == "abc123", "the connection never reached list_metrics"

    def test_no_connection_is_still_the_whole_registry(self, client, monkeypatch):
        seen = {}

        def _fake(path=None, connection_id=None):
            seen["connection_id"] = connection_id
            return []
        monkeypatch.setattr("aughor.routers.metrics.list_metrics", _fake)
        assert client.get("/metrics").status_code == 200
        assert seen["connection_id"] is None, "an existing caller must be byte-identical"


class TestTheCatalogueDoor:
    def test_it_returns_rows_and_a_tally(self, client, monkeypatch):
        rows = [
            MC.CatalogueEntry(name="gmv", label="GMV", source=MC.SOURCE_DEFINED,
                              state=MC.STATE_DEFINED, editable=True),
            MC.CatalogueEntry(name="nim", label="NIM", source=MC.SOURCE_INDUSTRY,
                              state=MC.STATE_NEEDS_BINDING, missing_roles=["financial_period"]),
            MC.CatalogueEntry(name="return_rate", label="Return Rate",
                              source=MC.SOURCE_EXPLORER, state=MC.STATE_PROPOSED),
        ]
        monkeypatch.setattr("aughor.semantic.metric_catalogue.catalogue_for",
                            lambda c, s=None: rows)
        body = client.get("/metrics/catalogue/conn1").json()
        assert body["connection_id"] == "conn1"
        # Exact-match on purpose: the tally is the door's contract, so a key added
        # without a decision shows up here. `formula_rejected` is counted apart from
        # `needs_formula` because a connection where every metric lands there is telling
        # you about the CONNECTION, not about missing SQL.
        assert body["counts"] == {"total": 3, "defined": 1, "industry": 1,
                                  "explorer": 1, "needs_binding": 1, "needs_formula": 0,
                                  "formula_rejected": 0}
        assert [m["source"] for m in body["metrics"]] == ["defined", "industry", "explorer"]
        assert body["metrics"][1]["missing_roles"] == ["financial_period"]

    def test_an_unbindable_row_is_refused_with_its_roles(self, client, monkeypatch):
        def _boom(conn, name, schema=None, actor=""):
            raise MC.MaterialiseError("'Net interest margin' needs financial_period bound")
        monkeypatch.setattr("aughor.semantic.metric_catalogue.materialise", _boom)
        res = client.post("/metrics/catalogue/conn1/net_interest_margin/materialise")
        assert res.status_code == 409, "a refusal must not read as a server error"
        assert "financial_period" in res.json()["detail"]

    def test_materialising_returns_the_new_definition(self, client, monkeypatch):
        from aughor.semantic.metrics import MetricDefinition
        made = MetricDefinition(name="gmv", connection="conn1", label="GMV",
                                sql="SUM(sale_price)", status="draft")
        monkeypatch.setattr("aughor.semantic.metric_catalogue.materialise",
                            lambda c, n, s=None, actor="": made)
        res = client.post("/metrics/catalogue/conn1/gmv/materialise")
        assert res.status_code == 201
        assert res.json()["connection"] == "conn1"
        assert res.json()["status"] == "draft", "never approved straight out of the catalogue"
