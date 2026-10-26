"""Adopting a SET of proposed metrics in one door, asked for approval once (the user's decision, 2026-10-23).

The Olist study, Gaps 22 and 24: adopting the explorer's eight suggestions took Customise → Dates → Propose →
Approve → approve-the-approval, per metric — eight self-granted allowlists by the person approving. Now one
call adopts the set: each metric is dated by the date a person confirmed, proposed and approved; the set's
approval is asked once, under a scope that names the dataset and every metric in it; a metric that cannot
be adopted as asked is skipped with its reason and the rest go on.
"""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from aughor.routers import metrics as R
from aughor.semantic.metrics import MetricDefinition

ORDERS = "olist.olist_orders_dataset"


def _draft(name, label, sql="SUM(price)", tables=(ORDERS,), status="draft", time_column=None):
    return MetricDefinition(name=name, label=label, connection="workspace", sql=sql, tables=list(tables),
                            status=status, time_column=time_column, schema_name="olist")


@pytest.fixture
def door(monkeypatch):
    drafts = {"gmv": _draft("gmv", "GMV"), "aov": _draft("aov", "AOV", sql="AVG(price)"),
              "nps": _draft("nps", "NPS", sql=""), "late": _draft("late", "Late rate")}
    seen = SimpleNamespace(guards=[], saved=[], events=[])
    import aughor.semantic.metric_catalogue as MC
    monkeypatch.setattr(MC, "find_entry", lambda conn, name, ds: SimpleNamespace(label=drafts[name].label))
    monkeypatch.setattr(MC, "materialise", lambda conn, name, ds, actor="": drafts[name])
    import aughor.govern as G
    monkeypatch.setattr(G, "guard", lambda action, scope="", **k: seen.guards.append((action, scope)))
    monkeypatch.setattr(R, "_declared_schema", lambda conn: "olist")
    monkeypatch.setattr(R, "caller", lambda: "amit")
    monkeypatch.setattr(R, "_twin_check", lambda m, conn: None)
    monkeypatch.setattr(R, "save_metric", lambda m: seen.saved.append(m))
    monkeypatch.setattr(R, "_restate_briefings", lambda conn: None)
    monkeypatch.setattr(R, "_reopen_questions", lambda *a: None)
    import aughor.kernel.ledger as L
    monkeypatch.setattr(L.Ledger, "default", classmethod(lambda cls: SimpleNamespace(
        emit=lambda kind, payload: seen.events.append(payload),
        kv_get=lambda store, key, default=None: default)))     # no flag overrides: every flag at its default
    return seen


def _adopt(*items, schema="olist"):
    return R.adopt_metrics("workspace", R._AdoptRequest(items=[R._AdoptItem(**i) for i in items]), schema=schema)


def test_a_set_is_approved_once_and_each_metric_carries_the_date_a_person_confirmed(door):
    out = _adopt({"name": "gmv", "time_column": f"{ORDERS}.order_purchase_timestamp"},
                 {"name": "aov", "time_column": f"{ORDERS}.order_purchase_timestamp", "time_kind": "flow"})
    assert door.guards == [("metric.approve", "olist: AOV, GMV")]       # once, naming the set
    assert [a["name"] for a in out["adopted"]] == ["gmv", "aov"] and out["skipped"] == []
    saved = {m.name: m for m in door.saved}
    assert {m.status for m in saved.values()} == {"approved"}
    assert saved["gmv"].time_column == f"{ORDERS}.order_purchase_timestamp"
    assert saved["gmv"].time_confirmed_by == "amit" and saved["gmv"].approved_by == "amit"
    assert all(e["batch"] == "olist: AOV, GMV" for e in door.events)


def test_what_cannot_be_adopted_is_skipped_with_its_reason_and_the_rest_go_on(door):
    out = _adopt({"name": "gmv", "time_column": f"{ORDERS}.order_purchase_timestamp"},
                 {"name": "nps", "time_column": f"{ORDERS}.order_purchase_timestamp"},
                 {"name": "late"},
                 {"name": "aov", "time_column": "olist.olist_order_items_dataset.shipping_limit_date"})
    assert [a["name"] for a in out["adopted"]] == ["gmv"]
    why = {s["name"]: s["reason"] for s in out["skipped"]}
    assert why["nps"].startswith("it has no formula for this connection yet")
    assert why["late"] == "it has no date — choose the column it is dated by"
    assert "which this definition does not read" in why["aov"]                # the date's table is not read


def test_a_refused_approval_adopts_nothing(door, monkeypatch):
    import aughor.govern as G

    def refuse(action, scope="", **k):
        raise HTTPException(status_code=428, detail={"error": "approval_required", "action": action, "scope": scope})
    monkeypatch.setattr(G, "guard", refuse)
    with pytest.raises(HTTPException) as held:
        _adopt({"name": "gmv", "time_column": f"{ORDERS}.order_purchase_timestamp"})
    assert held.value.status_code == 428 and held.value.detail["scope"] == "olist: GMV"
    assert door.saved == []
