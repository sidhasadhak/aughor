"""Phase 6 of the 2027 study, P6-2 — the day-one door (`aughor/packs/onboarding.py`, `GET /onboarding`):
onboarding hours as a release gate, the data shopping list, coverage.

What these hold: the hours run from the connection's first build to the first claim a decision
relied on, pass the gate under a day, and read "not yet" — never a number — before any decision
relied on anything; the shopping list names the pack's expected objects no table matched with what
each unlocks, the pack metrics whose roles the binding leaves unresolved with the plays and goldens
that wait on them, and the mission templates whose metric nothing measures; coverage is the
visibility module's number, and a connection never profiled says its denominator is unknown.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from aughor.ontology.models import OntologyEntity, OntologyGraph
from aughor.packs import onboarding as OB
from aughor.record import claims as C
from aughor.record import decisions as D


def _conn():
    return "conn-" + uuid.uuid4().hex[:6]


def _graph(conn: str, built_at: str) -> OntologyGraph:
    g = OntologyGraph(connection_id=conn, schema_name="shop", schema_fingerprint="fp-1", generated_at=built_at)
    g.entities["Order"] = OntologyEntity(id="Order", display_name="Order", source_tables=["shop.orders"], identity_key="order_id",
                                         grain_verified=True)
    return g


def test_onboarding_hours_run_from_the_first_build_to_the_first_relied_on_claim_and_say_not_yet_before():
    conn = _conn()
    built = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)
    graph = _graph(conn, built.isoformat())
    before = OB.onboarding_hours(conn, "shop", graph)
    assert before["hours"] is None and before["passed"] is None and before["note"].startswith("not yet")
    assert before["connected_at"] == built.isoformat() and before["connected_basis"] == "the connection's ontology build"
    claim = C.Claim(kind="observation", tier="said", about=C.About(kind="connection", key=conn),
                    statement=C.Statement(text="Orders were 1,200 last week"), author="system", as_of="2026-10-01")
    cid = C.book(claim, key=C.claim_key("observation", "answer", conn, "inv1"), conn_id=conn)
    decided = (built + timedelta(hours=5, minutes=30)).isoformat()
    D.book_decision(D.Decision(question="raise the threshold?", chosen="yes", decided_by="user:ana", connection_id=conn,
                               relied_on=[cid], decided_at=decided, source=D.Source(kind="declared", ref=uuid.uuid4().hex[:8])))
    D.book_decision(D.Decision(question="later one", chosen="yes", decided_by="user:ana", connection_id=conn, relied_on=[cid],
                               decided_at=(built + timedelta(days=3)).isoformat(), source=D.Source(kind="declared", ref=uuid.uuid4().hex[:8])))
    after = OB.onboarding_hours(conn, "shop", graph)
    assert after["hours"] == 5.5 and after["passed"] is True and after["first_relied_on"]["claim"] == cid
    assert after["first_relied_on"]["decided_by"] == "user:ana" and "the gate is 24" in after["note"]
    slow = OB.onboarding_hours(conn, "shop", _graph(conn, (built - timedelta(days=2)).isoformat()))
    assert slow["hours"] == 53.5 and slow["passed"] is False
    unknown = OB.connected_at(_conn(), "shop", graph=OntologyGraph(connection_id="x", schema_name="s", schema_fingerprint="f", generated_at=""))
    assert unknown["at"] == "" and unknown["basis"].startswith("unknown")


def test_the_shopping_list_names_what_the_data_cannot_answer_and_what_would_unlock_it(monkeypatch):
    conn = _conn()
    graph = _graph(conn, "2026-10-01T09:00:00+00:00")
    items = OB.shopping_list(conn, "shop", graph, pack_id="core-ecommerce")
    objects = {i["what"]: i for i in items if i["kind"] == "object"}
    assert "a table for Order" not in objects and "a table for Customer" in objects and "a table for Shipment" in objects
    assert objects["a table for Customer"]["unlocks"] == ["link Order → Customer"]
    assert objects["a table for Customer"]["tried"][:3] == ["Customer", "customers", "customer"]
    missions = [i for i in items if i["kind"] == "mission"]
    assert {m["unlocks"][0] for m in missions} == {"mission template protect_gross_margin", "mission template cut_returns_without_hurting_conversion",
                                                   "mission template keep_stock_cover_inside_a_band"}
    assert any("gross_margin" in m["what"] for m in missions)
    # a pack with metrics: an unresolved required role lists the plays and goldens that wait on it
    bank = OB.shopping_list(conn, "shop", graph, pack_id="banking")
    metric_lines = [i for i in bank if i["kind"] == "metric"]
    nim = next(i for i in metric_lines if "Net interest margin" in i["what"])
    assert "bind the role financial_period" in nim["what"] and any(u.startswith("play ") for u in nim["unlocks"])
    assert any(u.startswith("question: ") for u in nim["unlocks"]) and nim["why"] == "no binding on this connection resolves the role"
    assert any("approval_rate" in i["what"] for i in bank if i["kind"] == "mission")
    # nothing bound and nothing named: an empty list, said
    assert OB.shopping_list(conn, "shop", graph) == []
    out = OB.onboarding(conn, "shop", graph=graph, universe=["shop.orders", "shop.customers", "shop.payments"])
    assert out["packs"] == [] and "no pack is bound" in out["shopping_note"]
    assert out["coverage"]["tables"]["mapped"] == 1 and out["coverage"]["tables"]["in_scope"] == 3 and out["coverage"]["tables"]["basis"] == "profiler"
    assert out["hours"]["note"].startswith("not yet")
    with_pack = OB.onboarding(conn, "shop", pack_id="core-ecommerce", graph=graph, universe=[])
    assert with_pack["packs"] == ["core-ecommerce"] and with_pack["coverage"]["tables"]["basis"] == "unknown"
    assert {p["id"] for p in with_pack["priors"]} == {"delivery_promise_breach_rate", "return_rate"}
    assert len(with_pack["templates"]["missions"]) == 3 and len(with_pack["templates"]["scenarios"]) == 2
    assert with_pack["shopping_list"] and all("what" in i and "unlocks" in i and "why" in i for i in with_pack["shopping_list"])


def test_the_door_serves_the_day_one_screen_with_its_gate(monkeypatch):
    from aughor.routers import onboarding as R
    conn = _conn()
    graph = _graph(conn, "2026-10-01T09:00:00+00:00")
    import aughor.agent.framing as framing
    monkeypatch.setattr(framing, "served_graph", lambda c, s=None: graph)
    import aughor.tools.profile_cache as pc
    monkeypatch.setattr(pc, "latest_profiled_tables", lambda c: ["shop.orders", "shop.returns"])
    out = R.get_onboarding(connection_id=conn, schema_name="shop", pack_id="core-ecommerce")
    assert out["gate"]["hours"] == 24 and out["hours"]["passed"] is None
    assert out["coverage"]["tables"]["share"] == 0.5 and out["coverage"]["line"].startswith("sees 1 of 2 tables (50%)")
    assert any(i["what"] == "a table for Return" for i in out["shopping_list"])
