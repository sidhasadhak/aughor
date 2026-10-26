"""Arc MC, MC-0 — a metric's figures are checked before it is approved (the user's call, 2026-10-26: refuse at approval).

LuxExperience carried two approved metrics that read 1 in every period: retail's two recipes, their roles bound to the
wrong tables — `order_item` → `returns`, whose every row has a return date, and `cart` → `events`, an id bound to a date.
The return-rate recipe declared a sane range of 0–30% beside a figure of 100%, and nothing compared them. These run the
real measurement on a DuckDB shop through the approval door: with `metrics.figure_gates` on, a figure that never moves,
one outside its recipe's band, and a recipe bound to the wrong columns are each refused with why; off, approval reads as
it did.
"""
from __future__ import annotations

import uuid

from aughor.kernel.flags import flag_overrides
from aughor.semantic import metric_gates as G
from aughor.semantic.metrics import MetricDefinition, save_metric
from tests.unit.test_metric_twins import client, con  # noqa: F401 — fixtures by name

CONSTANT = "SELECT 1.0 * COUNT(*) / NULLIF(COUNT(*), 0) AS share FROM order_items"
RETURNS = ("SELECT SUM(CASE WHEN returned_at IS NOT NULL THEN 1.0 ELSE 0.0 END) / NULLIF(COUNT(*), 0) AS return_rate "
           "FROM order_items")
REVENUE = "SELECT SUM(sale_price) AS revenue FROM order_items"


def _proposed(conn: str, name: str, sql: str, **kw) -> None:
    save_metric(MetricDefinition(name=name, label=kw.pop("label", name.replace("_", " ").title()), sql=sql,
                                 connection=conn, status="proposed", time_kind="flow",
                                 time_column="order_items.created_at", **kw))


def _approve(client, conn: str, name: str):  # noqa: F811
    return client.post(f"/metrics/{name}/transition", json={"action": "approve", "connection": conn})


def test_a_figure_that_reads_one_value_in_every_month_is_refused_with_that_value(client):  # noqa: F811
    conn = f"c{uuid.uuid4().hex[:6]}"
    _proposed(conn, "constant_share", CONSTANT)
    with flag_overrides({G.FLAG: True}):
        refused = _approve(client, conn, "constant_share")
    assert refused.status_code == 409, refused.text
    detail = refused.json()["detail"]
    assert detail["reason"] == "reads_constant"
    assert "it reads 1 in every one of the last 6 months with figures" in detail["message"]
    assert detail["gates"]["moves"]["ok"] is False
    # off, the approval reads as it did: the gate never ran
    assert _approve(client, conn, "constant_share").status_code == 200


def test_a_figure_that_moves_is_approved_and_one_that_cannot_be_read_is_not_refused(client):  # noqa: F811
    conn = f"c{uuid.uuid4().hex[:6]}"
    _proposed(conn, "revenue", REVENUE)
    save_metric(MetricDefinition(name="units", label="Units", sql="SELECT COUNT(*) AS units FROM order_items",
                                 connection=conn, status="proposed"))           # no dates: not measurable, not refused
    with flag_overrides({G.FLAG: True}):
        assert _approve(client, conn, "revenue").status_code == 200
        ok = _approve(client, conn, "units")
    assert ok.status_code == 200, ok.text
    assert ok.json()["audit"]["figure_check"].startswith("not read: moves: its figures could not be read: its dates")


def test_a_return_rate_outside_the_recipes_sane_range_is_refused_with_the_band_and_its_basis(client, monkeypatch):  # noqa: F811
    from aughor.business_profile import metric_kb
    monkeypatch.setattr(metric_kb, "industry_scope", lambda *a, **k: "retail")
    conn = f"c{uuid.uuid4().hex[:6]}"
    _proposed(conn, "return_rate", RETURNS, label="Return rate")    # every third line returned: about 0.33
    with flag_overrides({G.FLAG: True}):
        refused = _approve(client, conn, "return_rate")
    assert refused.status_code == 409, refused.text
    detail = refused.json()["detail"]
    assert detail["reason"] == "outside_sane_range", detail
    assert "outside the Return rate recipe's sane range of 0.0–0.3" in detail["message"]
    assert "NRF" in detail["message"]                                        # the basis travels with the band
    assert detail["gates"]["moves"]["ok"] is True


def test_the_adopt_door_skips_a_figure_that_never_moves_with_the_same_words(client, monkeypatch):  # noqa: F811
    from aughor import govern
    monkeypatch.setattr(govern, "guard", lambda *a, **k: None)
    conn = f"c{uuid.uuid4().hex[:6]}"
    _proposed(conn, "constant_share", CONSTANT)
    _proposed(conn, "revenue", REVENUE)
    with flag_overrides({G.FLAG: True}):
        out = client.post(f"/metrics/catalogue/{conn}/adopt", json={"items": [{"name": "constant_share"},
                                                                              {"name": "revenue"}]})
    assert out.status_code == 200, out.text
    body = out.json()
    assert [a["name"] for a in body["adopted"]] == ["revenue"]
    assert body["skipped"][0]["name"] == "constant_share"
    assert body["skipped"][0]["reason"].startswith("it reads 1 in every one of the last 6 months")


# ── the gates as functions ─────────────────────────────────────────────────────────────────────────────────────────

def test_moves_needs_three_months_and_says_the_value_it_never_leaves():
    assert G.moves([None, None, 0.5])["ok"] is None
    assert G.moves([0.1, 0.1, 0.1, None])["ok"] is False
    assert G.moves([0.1, 0.1, 0.12])["ok"] is True
    assert G.moves(None, "its dates are not set")["why"] == "its figures could not be read: its dates are not set"


def test_a_band_is_read_at_its_scale_and_as_a_percent_of_it():
    band = {"min": 0.0, "max": 0.30, "basis": "a published anchor"}
    assert G.sane([0.1, 0.12, 0.11], band)["ok"] is True
    assert G.sane([11.0, 12.0, 10.5], band)["ok"] is True                    # the same share, written as a percent
    out = G.sane([1.0, 1.0, 1.0], band, "the Return rate recipe")
    assert out["ok"] is False and "1, is outside the Return rate recipe's sane range of 0.0–0.3 (a published" in out["why"]
    assert G.sane([0.5], None)["ok"] is None


def test_the_binding_gate_names_an_id_bound_to_a_date_and_a_presence_test_on_a_column_never_empty():
    """LuxExperience's binding, as it stood: `cart.converted_order_id` → `events.event_date`, and
    `order_item.returned_at` → `returns.return_date`, a date every row of returns carries."""
    from aughor.packs.loader import load_pack
    pack = load_pack("packs/retail")
    bound = {"order_item": {"table": "returns", "columns": {"returned_at": "return_date"}},
             "cart": {"table": "events", "columns": {"converted_order_id": "event_date"}}}
    columns = {"returns.return_date": {"table": "returns", "column": "return_date", "dtype": "date", "null_rate": 0.0},
               "events.event_date": {"table": "events", "column": "event_date", "dtype": "date", "null_rate": 0.0},
               "order_items.returned": {"table": "order_items", "column": "returned", "dtype": "boolean",
                                        "null_rate": 0.0}}
    recipes = {pm.name: pm for pm in pack.metrics}
    cart = G.binding_problems(recipes["cart_to_order_conversion_rate"].formula, pack.entities, bound, columns)
    assert cart[0] == "cart.converted_order_id is an id, and it is bound to events.event_date, a date column"
    assert "events.event_date is never empty — every row of events would count" in cart[1]
    ret = G.binding_problems(recipes["return_rate"].formula, pack.entities, bound, columns)
    assert ret == ["the formula counts a row when order_item.returned_at is set, and returns.return_date is never "
                   "empty — every row of returns would count, so returns is not the table whose rows are order_items"]
    # bound the right way — sold lines, with a column that is empty for a line not returned — there is nothing to say
    right = {"order_item": {"table": "order_items", "columns": {"returned_at": "returned_at"}}}
    columns["order_items.returned_at"] = {"table": "order_items", "column": "returned_at", "dtype": "timestamp",
                                          "null_rate": 0.67}
    assert G.binding_problems(recipes["return_rate"].formula, pack.entities, right, columns) == []


def test_a_metric_that_only_carries_a_recipes_alias_is_not_held_to_its_band(client, monkeypatch):  # noqa: F811
    """Live 2026-10-26: LuxExperience's Item Return Rate (~31% a month, luxury fashion) met retail's return-rate recipe
    through the alias "item return rate"; its 0–30% band would have refused a real figure. An alias names; it does not
    make two metrics one."""
    from aughor.business_profile import metric_kb
    monkeypatch.setattr(metric_kb, "industry_scope", lambda *a, **k: "retail")
    conn = f"c{uuid.uuid4().hex[:6]}"
    _proposed(conn, "item_return_rate", RETURNS, label="Item Return Rate")      # about 0.33, as return_rate above
    with flag_overrides({G.FLAG: True}):
        ok = _approve(client, conn, "item_return_rate")
    assert ok.status_code == 200, ok.text
    m = MetricDefinition(name="item_return_rate", label="Item Return Rate", sql=RETURNS, connection=conn)
    assert G.band_of(m, conn) == (None, "")
    made = m.model_copy(update={"name": "return_rate", "lineage": ["industry: retail"]})
    assert G.band_of(made, conn)[1] == "Return rate"                           # made from it: held to it


def test_a_gate_that_does_not_apply_is_not_said_to_be_unread():
    """Live 2026-10-26: approving Gross Margin on Items recorded "not read: sane_range: no sane range is declared …;
    binding: it is not made from a recipe" — neither went unread; neither applies."""
    verdict = {"moves": {"ok": True, "why": ""},
               "sane_range": {"ok": None, "why": "no sane range is declared for it", "applies": False},
               "binding": {"ok": None, "why": "it is not made from a recipe with roles", "applies": False}}
    assert G.not_read(verdict) == ""
    verdict["moves"] = {"ok": None, "why": "its figures could not be read: the connection could not be opened"}
    assert G.not_read(verdict) == "moves: its figures could not be read: the connection could not be opened"
