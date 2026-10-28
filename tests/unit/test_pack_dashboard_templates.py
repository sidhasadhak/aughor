"""Arc FA, FA-6 (ROADMAP §3.60) — a pack's dashboard template, kept by a person (`aughor/packs/templates.py`, flag
`packs.dashboard_templates`).

What these hold. A template is a declaration in `dashboards/*.yaml`: the pack kit's static gate refuses one whose
cards name a metric the pack does not carry, or that places a card it does not list. Off, nothing is listed and the
draft door is closed. On, the templates of the active packs bound on a connection are listed, each card saying whether
the connection can make it; a draft is staged through the dashboards' one proposal path with no model call — a metric
the connection has not registered and approved is skipped and SAID — and the kept dashboard's source names the pack
and its version.

Run against the real stores and the real rules (node and the bundle); the warehouse is stood in for, as in
`test_dashboard_propose.py`, and no model is called.
"""
from __future__ import annotations

import shutil
import uuid
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aughor.actions import inbox
from aughor.cards import doors
from aughor.dashboards import propose, validate as DV, versions
from aughor.dashboards.home import Home, approver
from aughor.kernel.flags import flag_overrides
from aughor.packs import bindings as B
from aughor.packs import kit
from aughor.packs import templates as T
from aughor.packs.loader import load_pack
from aughor.packs.roots import pack_dir
from aughor.semantic.metrics import MetricDefinition, save_metric

needs_rules = pytest.mark.skipif(shutil.which("node") is None or not DV._BUNDLE.exists(),
                                 reason="the dashboard's rules need node + validate.bundle.mjs")

PACK_YAML = "id: tmpl-test\nname: Template test\nversion: 3\nstatus: draft\n"
ENTITIES = "roles:\n  line:\n    description: a sold line\n"
METRIC = ("name: line_rate\ntitle: Line rate\nformula: SUM(1) / NULLIF(COUNT(*), 0)\nunit: ratio\n"
          "binds:\n  required: [line]\n")


def _conn() -> str:
    return "conn-" + uuid.uuid4().hex[:6]


def _client() -> TestClient:
    from aughor.routers.packs import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


class Warehouse:
    def __init__(self):
        self.ran: list[str] = []

    def __call__(self, connection_id, sql, *, query_id, schema=None):
        self.ran.append(sql)
        return SimpleNamespace(error=None, row_count=1, columns=["_v"], rows=[["0.12"]])


@pytest.fixture
def warehouse(monkeypatch, tmp_path) -> Warehouse:
    monkeypatch.setenv("AUGHOR_METRICS_PATH", str(tmp_path / "metrics.json"))
    monkeypatch.setenv("AUGHOR_TRUSTED_QUERIES_PATH", str(tmp_path / "trusted_queries.json"))
    w = Warehouse()
    monkeypatch.setattr(doors, "run_guarded", w)
    monkeypatch.setattr(propose, "findings", lambda conn_id, schema=None: [])
    return w


def _register(conn: str, name: str, status: str = "approved") -> None:
    save_metric(MetricDefinition(name=name, connection=conn, label=name.replace("_", " ").capitalize(), unit="ratio",
                                 sql="SELECT AVG(CASE WHEN returned_at IS NOT NULL THEN 1.0 ELSE 0 END) FROM lines",
                                 tables=["lines"], status=status, version=1))


# ── the declaration and its static gate ──────────────────────────────────────────────────────

def test_the_retail_pack_ships_one_template_over_its_own_metrics_and_passes_the_gate():
    retail = load_pack(pack_dir("retail"))
    assert [t.id for t in retail.dashboards] == ["checkout-and-returns"]
    t = retail.dashboards[0]
    assert {c.metric for c in t.cards} <= {m.name for m in retail.metrics}
    assert T.template_problems(retail) == []
    from aughor.packs.validate import validate_pack
    assert validate_pack(pack_dir("retail")).ok


def test_the_kit_refuses_a_template_that_names_a_metric_the_pack_lacks_or_places_what_it_does_not_list():
    bad = ("id: Bad Id\ntitle: Lines at 12.5%\ncards:\n  - {key: rate, metric: line_rate}\n"
           "  - {key: rate, metric: no_such_metric}\n  - {key: lonely, metric: line_rate}\n"
           "sections:\n  - title: Lines\n    cards: [rate, ghost]\n")
    out = kit.check({"pack.yaml": PACK_YAML, "entities.yaml": ENTITIES, "metrics/line_rate.yaml": METRIC,
                     "dashboards/bad.yaml": bad})
    assert out["ok"] is False and out["declares"]["dashboards"] == 1
    said = " | ".join(out["errors"])
    for token in ("an id is 2 to 63 characters", "the title states a figure", "two cards share the key 'rate'",
                  "names metric 'no_such_metric', which is not one of this pack's metrics",
                  "places 'ghost', which is no card of the template", "card 'lonely' is placed in no section"):
        assert token in said, token
    good = ("id: lines\ntitle: Lines\ndescription: d\ncards:\n  - {key: rate, metric: line_rate}\n"
            "sections:\n  - title: Lines\n    cards: [rate]\n")
    ok = kit.check({"pack.yaml": PACK_YAML, "entities.yaml": ENTITIES, "metrics/line_rate.yaml": METRIC,
                    "dashboards/lines.yaml": good})
    assert ok["ok"] is True, ok["errors"]
    # a pack with no template reads exactly as it always did: no count is added to what it declares
    plain = kit.check({"pack.yaml": PACK_YAML, "entities.yaml": ENTITIES, "metrics/line_rate.yaml": METRIC})
    assert "dashboards" not in plain["declares"]


# ── off ──────────────────────────────────────────────────────────────────────────────────────

def test_off_nothing_is_listed_the_draft_door_is_closed_and_the_guide_does_not_describe_templates():
    conn = _conn()
    B.save_binding("retail", conn, {}, version=1)
    client = _client()
    with flag_overrides({T.FLAG: False, "dashboard.composed": True}):
        assert client.get(f"/packs/templates?connection_id={conn}").status_code == 404
        r = client.post("/packs/retail/templates/checkout-and-returns/draft", json={"connection_id": conn})
        assert r.status_code == 404
        assert not any(a["file"] == "dashboards/*.yaml" for a in kit.guide()["anatomy"])
    with flag_overrides({T.FLAG: True}):
        assert any(a["file"] == "dashboards/*.yaml" for a in kit.guide()["anatomy"])


def test_off_a_draft_without_a_template_is_staged_and_kept_as_it_always_was(warehouse):
    conn = _conn()
    _register(conn, "return_rate")
    home = Home(conn, "u" + uuid.uuid4().hex[:6], "plain-" + uuid.uuid4().hex[:6])
    spec, _ = T.spec_for(load_pack(pack_dir("retail")).dashboards[0], {"return-rate"})
    with flag_overrides({"dashboard.composed": True}):
        drafted = propose.draft(home, mode=propose.MODE_NEW, spec=spec,
                                cards=[{"key": "return-rate", "metric": "return_rate"}], reasoning="By hand.")
    assert drafted.staged, drafted.refusals
    p = drafted.proposal
    assert "template" not in p.params and "template" not in p.detail and "source" not in p.detail
    assert p.source == "agent"
    result, _ = inbox.accept_proposal(p.id, actor=approver(home.owner))
    assert result.ok, result.message
    assert versions.latest(home)["source"] == f"proposal {p.id}"


# ── on ───────────────────────────────────────────────────────────────────────────────────────

def test_on_the_bound_packs_templates_are_listed_each_card_saying_whether_this_connection_can_make_it(warehouse):
    conn = _conn()
    client = _client()
    with flag_overrides({T.FLAG: True}):
        assert client.get(f"/packs/templates?connection_id={conn}").json()["templates"] == []   # nothing bound
        B.save_binding("retail", conn, {}, version=1)
        _register(conn, "return_rate")
        _register(conn, "cart_to_order_conversion_rate", status="draft")
        body = client.get(f"/packs/templates?connection_id={conn}").json()
    [t] = body["templates"]
    assert (t["pack"], t["id"], t["version"], t["source"]) == ("retail", "checkout-and-returns", 1,
                                                                "pack:retail@1 template")
    cards = {c["metric"]: c for c in t["cards"]}
    assert cards["return_rate"]["ready"] is True and t["ready"] == 1
    assert cards["cart_to_order_conversion_rate"]["ready"] is False
    assert cards["cart_to_order_conversion_rate"]["why"].startswith("registered here and draft")


@needs_rules
def test_a_template_becomes_one_draft_skipping_and_saying_a_metric_the_connection_lacks_and_is_kept_with_its_source(warehouse):
    conn = _conn()
    client = _client()
    B.save_binding("retail", conn, {}, version=1)
    _register(conn, "return_rate")                         # cart conversion is not registered on this connection
    with flag_overrides({T.FLAG: True, "dashboard.composed": True}):
        r = client.post("/packs/retail/templates/checkout-and-returns/draft", json={"connection_id": conn})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["staged"] is True, out["sentences"]
    assert out["skipped"] == [{"key": "cart-conversion", "metric": "cart_to_order_conversion_rate",
                               "title": "Cart-to-order conversion rate", "why": "not registered on this connection"}]
    assert out["dropped_sections"] == ["Checkout"]
    assert "Left out: Cart-to-order conversion rate — not registered on this connection." in out["summary"]
    assert out["source"] == "pack:retail@1 template"
    # one card was run before it was offered; no model, no other query
    assert len(warehouse.ran) == 1
    p = inbox.get_proposal(out["proposal_id"])
    assert p.kind == propose.KIND and p.source == "pack:retail" and p.status == "pending"
    assert p.params["template"] == {"pack": "retail", "version": 1, "id": "checkout-and-returns"}
    assert p.detail["source"] == "pack:retail@1 template"
    assert [c["name"] for c in p.params["cards"]] == ["return_rate"]
    # kept by the person it was drafted for: the dashboard's source names the pack and its version
    result, _ = inbox.accept_proposal(p.id, actor=approver(p.params["home"]["owner"]))
    assert result.ok, result.message
    home = Home.of(p.params["home"])
    kept = versions.latest(home)
    assert kept["source"] == "pack:retail@1 template" and kept["version"] == 1


@needs_rules
def test_a_template_with_no_card_this_connection_can_make_is_not_drafted_and_says_why(warehouse):
    conn = _conn()
    client = _client()
    B.save_binding("retail", conn, {}, version=1)
    with flag_overrides({T.FLAG: True, "dashboard.composed": True}):
        r = client.post("/packs/retail/templates/checkout-and-returns/draft", json={"connection_id": conn})
        assert r.status_code == 200
        out = r.json()
        assert out["staged"] is False and out["proposal_id"] == ""
        assert out["sentences"][0].startswith("None of the template's metrics can make a card on this connection")
        assert "Return rate is not registered on this connection" in out["sentences"][0]
        assert warehouse.ran == []
        # a pack not bound here, and a template the pack does not carry
        other = _conn()
        assert client.post("/packs/retail/templates/checkout-and-returns/draft",
                           json={"connection_id": other}).status_code == 409
        assert client.post("/packs/retail/templates/nope/draft", json={"connection_id": conn}).status_code == 404
    with flag_overrides({T.FLAG: True, "dashboard.composed": False}):
        assert client.post("/packs/retail/templates/checkout-and-returns/draft",
                           json={"connection_id": conn}).status_code == 404


def test_the_flag_is_part_of_the_platform(monkeypatch):
    """Queued to graduate until 2026-10-28; always on since (ROADMAP §3.65) — on with nothing set."""
    from aughor.kernel.flags import FLAG_ENV, flag_disposition, flag_enabled
    monkeypatch.delenv(FLAG_ENV[T.FLAG], raising=False)
    assert flag_disposition(T.FLAG) == "always_on" and flag_enabled(T.FLAG) is True
