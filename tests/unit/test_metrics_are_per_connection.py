"""Two connections do not share a formula, even in the same industry.

theLook and LuxExperience are both e-commerce. Revenue on one is `SUM(sale_price)` over
`order_items`; on the other it is a different column on a different table. The store has
always known this — `save_metric` upserts by the (connection, name) PAIR, and
`get_metric` resolves scoped-shadows-global.

The API did not. `MetricRequest` carried no `connection`, so every write through the
route fell back to the model default `"*"`:

  • `POST` refused a second connection's own `revenue`, because it looked for a
    duplicate by NAME alone;
  • `PUT` rebuilt the definition from that same request, so EDITING a connection-scoped
    metric silently republished it as global.

Seen live 2026-09-19: `sales_volume_by_category`, materialised for theLook with
`SELECT COUNT(id) FROM inventory_items …`, existed twice — once scoped to `8233e4fd`
and once as `*` — and so appeared in LuxExperience's Metrics tab, whose warehouse has no
`inventory_items` at all.
"""
import pytest
from fastapi.testclient import TestClient

from aughor.semantic.metrics import GLOBAL_CONNECTION


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """A registry in a temp file — these tests WRITE metrics."""
    from aughor.semantic import metrics as m
    monkeypatch.setattr(m, "_DEFAULT_PATH", tmp_path / "metrics.json", raising=False)
    monkeypatch.setenv("AUGHOR_METRICS_PATH", str(tmp_path / "metrics.json"))
    from aughor.api import app
    with TestClient(app) as c:
        yield c


def _body(**over):
    b = {"name": "revenue", "label": "Revenue", "sql": "SUM(sale_price)",
         "tables": ["order_items"]}
    b.update(over)
    return b


def test_two_connections_each_keep_their_own_revenue(client):
    """The case the duplicate check used to refuse."""
    a = client.post("/metrics", json=_body(connection="conn_a", sql="SUM(sale_price)"))
    b = client.post("/metrics", json=_body(connection="conn_b", sql="SUM(gmv_eur)"))
    assert a.status_code == 201, a.text
    assert b.status_code == 201, b.text

    seen_a = client.get("/metrics?connection_id=conn_a").json()
    seen_b = client.get("/metrics?connection_id=conn_b").json()
    assert [m["sql"] for m in seen_a if m["name"] == "revenue"] == ["SUM(sale_price)"]
    assert [m["sql"] for m in seen_b if m["name"] == "revenue"] == ["SUM(gmv_eur)"]


def test_the_same_connection_still_refuses_a_duplicate(client):
    """Scoping the check must not disable it."""
    assert client.post("/metrics", json=_body(connection="conn_a")).status_code == 201
    dup = client.post("/metrics", json=_body(connection="conn_a"))
    assert dup.status_code == 409
    assert "conn_a" in dup.json()["detail"], "the refusal should name the scope it refused in"


def test_editing_a_scoped_metric_leaves_it_scoped(client):
    """An edit must leave the metric where it was, and make no global twin."""
    client.post("/metrics", json=_body(connection="conn_a"))
    r = client.put("/metrics/revenue", json=_body(connection="conn_a", sql="SUM(sale_price) * 1.0"))
    assert r.status_code == 200, r.text
    assert r.json()["connection"] == "conn_a"
    everything = client.get("/metrics").json()
    assert [m for m in everything if m["name"] == "revenue"
            and m["connection"] == GLOBAL_CONNECTION] == []


def test_a_new_scoped_override_is_not_born_approved(client):
    """The governance hole behind the leak.

    `get_metric(name, connection_id=…)` RESOLVES: with no scoped definition it returns
    the global one. Treating that as "the metric being edited" carried its status,
    version and approver onto the connection's brand-new formula — so a per-connection
    `revenue` nobody had reviewed arrived stamped `approved` by whoever signed off the
    house default. A different formula has not been approved just because its name was.
    """
    client.post("/metrics", json=_body(sql="SUM(global_amount)"))          # the house default
    client.post("/metrics/revenue/transition", json={"action": "propose", "actor": "t"})
    client.post("/metrics/revenue/transition", json={"action": "approve", "actor": "t"})
    approved = [m for m in client.get("/metrics").json() if m["name"] == "revenue"]
    assert approved and approved[0]["status"] == "approved", "fixture must start approved"

    house = approved[0]
    assert house["version"] >= 1, "fixture must have a governance history to inherit"

    # conn_a now writes its OWN revenue. Asserted on `version`/`proposed_by` rather than
    # on `status`: an edit that CHANGES the formula of an approved metric already drops
    # it back to `proposed`, so a status assertion here passes with or without the fix
    # and proves nothing. The lineage fields carry across regardless, and they are the
    # honest tell — this definition has no history on this connection.
    r = client.put("/metrics/revenue", json=_body(connection="conn_a", sql="SUM(sale_price)"))
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["connection"] == "conn_a"
    assert got["version"] == 0, (
        f"a brand-new scoped definition inherited the global metric's version "
        f"({got['version']}) — it has no history of its own"
    )
    assert not got.get("proposed_by"), "nor the global's proposer"
    assert not got.get("approved_by"), "nor its approver"


def test_a_global_metric_is_still_one_call(client):
    """`*` stays the default, so an intentionally house-wide metric needs no ceremony."""
    r = client.post("/metrics", json=_body(name="house_rule"))
    assert r.status_code == 201
    assert r.json()["connection"] == GLOBAL_CONNECTION
    # …and it is visible from a connection that has no scoped definition of its own.
    names = [m["name"] for m in client.get("/metrics?connection_id=conn_z").json()]
    assert "house_rule" in names


def test_a_scoped_metric_shadows_the_global_one(client):
    """The store's rule, asserted through the door: the connection's own wins."""
    client.post("/metrics", json=_body(sql="SUM(global_amount)"))                   # global
    client.post("/metrics", json=_body(connection="conn_a", sql="SUM(sale_price)"))  # scoped
    seen = [m for m in client.get("/metrics?connection_id=conn_a").json()
            if m["name"] == "revenue"]
    assert [m["sql"] for m in seen] == ["SUM(sale_price)"]


def test_approval_is_scoped_to_the_connection_it_governs(client):
    """Live 2026-09-19: approving theLook's draft `revenue` was refused with "cannot
    approve a metric in state 'approved'" — because the route resolved by NAME and found
    the SAMPLES `revenue`, which was already approved. The draft stayed unapproved and
    nothing said why. Approval is per formula."""
    client.post("/metrics", json=_body(sql="SUM(global_amount)"))            # the house default
    client.post("/metrics/revenue/transition", json={"action": "propose", "actor": "t"})
    client.post("/metrics/revenue/transition", json={"action": "approve", "actor": "t"})

    client.post("/metrics", json=_body(connection="conn_a", sql="SUM(sale_price)"))
    for action in ("propose", "approve"):
        r = client.post("/metrics/revenue/transition",
                        json={"action": action, "actor": "t", "connection": "conn_a"})
        assert r.status_code == 200, f"{action}: {r.text}"

    scoped = [m for m in client.get("/metrics").json()
              if m["name"] == "revenue" and m["connection"] == "conn_a"]
    assert scoped and scoped[0]["status"] == "approved"
    # …and the house default is untouched by a transition aimed elsewhere.
    house = [m for m in client.get("/metrics").json()
             if m["name"] == "revenue" and m["connection"] == GLOBAL_CONNECTION]
    assert house and house[0]["sql"] == "SUM(global_amount)"


def test_a_transition_for_a_connection_with_no_definition_is_a_404(client):
    """It must not silently govern the house default instead."""
    client.post("/metrics", json=_body(sql="SUM(global_amount)"))
    r = client.post("/metrics/revenue/transition",
                    json={"action": "propose", "actor": "t", "connection": "conn_never"})
    assert r.status_code == 404 and "conn_never" in r.json()["detail"]


def test_deleting_one_connection_s_metric_leaves_the_others(client):
    """Delete resolved by name alone, so retiring one warehouse's `revenue` took every
    other warehouse's with it — including, per the route's own docstring, a formula
    carrying `approved_by: Finance`."""
    client.post("/metrics", json=_body(connection="conn_a", sql="SUM(sale_price)"))
    client.post("/metrics", json=_body(connection="conn_b", sql="SUM(gmv_eur)"))

    r = client.delete("/metrics/revenue?connection=conn_a")
    assert r.status_code == 200, r.text
    left = [(m["name"], m["connection"]) for m in client.get("/metrics").json()
            if m["name"] == "revenue"]
    assert left == [("revenue", "conn_b")], f"only conn_a's should be gone, got {left}"


def test_an_unscoped_delete_still_retires_the_name_everywhere(client):
    """The old behaviour is the right one for retiring a name outright — keep it."""
    client.post("/metrics", json=_body(connection="conn_a"))
    client.post("/metrics", json=_body(connection="conn_b"))
    assert client.delete("/metrics/revenue").status_code == 200
    assert [m for m in client.get("/metrics").json() if m["name"] == "revenue"] == []
