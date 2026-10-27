"""A metric whose date cannot bound its rows is said where it is listed and refused at approval (the user,
2026-10-26: "Make sure that this never happens again").

LuxExperience's gross margin read ``order_items LEFT JOIN orders`` dated on orders, and its marketing ROAS read campaigns
WHERE EXISTS a ``dim_date`` row of the same fiscal year, dated on ``dim_date.date``. Both were approved; the first read
its all-time figure in every period for weeks and a decision's review was booked on it, and the Briefing met both as
"not measured" with the reason in a tooltip. Now the Metrics tab says it beside the metric (``measurable_why``), and
the approval refuses it with the fix — a Briefing, a review or a mission never meets it first.
"""
from __future__ import annotations

import uuid

from aughor.semantic.metrics import MetricDefinition, save_metric
from tests.unit.test_metric_twins import client, con  # noqa: F401 — fixtures by name

MARGIN = "SELECT SUM(oi.sale_price) AS sales FROM order_items oi LEFT JOIN orders o ON oi.order_id = o.order_id"


def _proposed(conn: str, name: str, sql: str, time_column: str = "orders.created_at") -> None:
    save_metric(MetricDefinition(name=name, label=name.replace("_", " ").title(), sql=sql, connection=conn,
                                 status="proposed", time_kind="flow", time_column=time_column))


def _listed(client, conn: str, name: str) -> dict:  # noqa: F811
    return next(x for x in client.get(f"/metrics?connection_id={conn}").json() if x["name"] == name)


def test_a_date_that_cannot_bound_the_rows_is_said_where_the_metric_is_listed_and_refused_at_approval(client):  # noqa: F811
    conn = f"c{uuid.uuid4().hex[:6]}"
    _proposed(conn, "gross_margin", MARGIN)
    listed = _listed(client, conn, "gross_margin")
    assert listed["measurable"] is False
    assert "optional side of a LEFT JOIN" in listed["measurable_why"] and "join it inner" in listed["measurable_why"]

    refused = client.post("/metrics/gross_margin/transition", json={"action": "approve", "connection": conn})
    assert refused.status_code == 409, refused.text
    detail = refused.json()["detail"]
    assert detail["reason"] == "window_unbounded"
    assert detail["message"].startswith("Gross Margin cannot be approved: its date table orders sits on the optional")
    assert _listed(client, conn, "gross_margin")["status"] == "proposed"


def test_a_date_read_only_inside_a_filter_is_refused_the_same_way(client):  # noqa: F811
    conn = f"c{uuid.uuid4().hex[:6]}"
    _proposed(conn, "marketing_roas", "SELECT SUM(mc.gmv) / NULLIF(SUM(mc.spend), 0) FROM marketing_campaigns mc "
                                      "WHERE EXISTS (SELECT 1 FROM dim_date d WHERE d.fiscal_year = mc.fiscal_year)",
              time_column="dim_date.date")
    assert "read only inside a filter, matched on fiscal_year" in _listed(client, conn, "marketing_roas")["measurable_why"]
    refused = client.post("/metrics/marketing_roas/transition", json={"action": "approve", "connection": conn})
    assert refused.status_code == 409 and refused.json()["detail"]["reason"] == "window_unbounded"


def test_a_bounded_date_or_no_date_at_all_is_approved_as_before(client):  # noqa: F811
    conn = f"c{uuid.uuid4().hex[:6]}"
    _proposed(conn, "gross_margin", MARGIN.replace("LEFT JOIN", "JOIN"))
    assert _listed(client, conn, "gross_margin")["measurable"] is True
    ok = client.post("/metrics/gross_margin/transition", json={"action": "approve", "connection": conn})
    assert ok.status_code == 200, ok.text
    # a metric with no dates is not measured for a period — said — but approving it is not this refusal
    save_metric(MetricDefinition(name="units", label="Units", sql="SELECT COUNT(*) AS units FROM order_items",
                                 connection=conn, status="proposed"))
    assert client.post("/metrics/units/transition", json={"action": "approve", "connection": conn}).status_code == 200
