"""Phase 6 of the 2027 study, P6-1 — packs as claims with priors (`aughor/packs/priors.py`,
`record/writers.book_pack_claims`, the loader's new parts).

What these hold: a pack's watches, scenario and mission templates load from their own files; a
prior that states a number says where it was measured or says none, and the static gate refuses one
that does neither; a template names a method the ladder has and a cadence the report keeps; the two
verticals' packs (commerce and banking) pass the gate; a pack's map measured against a connection is
booked into the Record as hypotheses the pack made — open while the data cannot speak, supported or
refuted once it has, restated on the next build — by the pack writer, the fourth of the study's five
claim shapes; the mission templates are read through the Record's door as bodies a person writes from.
"""
from __future__ import annotations

import uuid

import pytest

from aughor.ontology.models import OntologyEntity, OntologyGraph, OntologyRelationship
from aughor.packs import priors as P
from aughor.packs.loader import load_pack
from aughor.packs.models import Pack, PackManifest, PackMissionTemplate, PackMonitorPrior, PackPlaybook, PackScenarioTemplate
from aughor.packs.roots import pack_dir
from aughor.packs.validate import validate_loaded
from aughor.record import claims as C


def _conn():
    return "conn-" + uuid.uuid4().hex[:6]


def _pack(**kw) -> Pack:
    base = dict(manifest=PackManifest(id="t", name="t"))
    base.update(kw)
    return Pack(**base)


# ── the priors' rule ───────────────────────────────────────────────────────────────────────

def test_a_prior_says_where_it_was_measured_or_says_none_and_the_gate_refuses_a_bare_number():
    bare = _pack(monitors=[PackMonitorPrior(id="m", metric="return_rate", low=0.02, high=0.06)])
    problems = P.prior_problems(bare)
    assert len(problems) == 1 and "states a band" in problems[0] and "measured_on" in problems[0] and "unmeasured: true" in problems[0]
    assert any("states a band" in e for e in validate_loaded(bare).errors)
    measured = _pack(monitors=[PackMonitorPrior(id="m", metric="return_rate", low=0.02, high=0.06, measured_on=["thelook"])])
    assert P.prior_problems(measured) == []
    said_none = _pack(monitors=[PackMonitorPrior(id="m", metric="return_rate", unmeasured=True)])
    assert P.prior_problems(said_none) == []
    both = _pack(monitors=[PackMonitorPrior(id="m", metric="x", low=1, high=2, measured_on=["a"], unmeasured=True)])
    assert any("one or the other" in e for e in P.prior_problems(both))
    upside_down = _pack(monitors=[PackMonitorPrior(id="m", metric="x", low=2, high=1, measured_on=["a"])])
    assert any("is above high" in e for e in P.prior_problems(upside_down))
    rows = P.monitor_priors(_pack(monitors=measured.monitors + said_none.monitors))
    assert rows[0]["low"] == 0.02 and rows[0]["status"].startswith("prior range measured on thelook")
    assert rows[1]["low"] is None and rows[1]["status"].startswith("unmeasured prior")


def test_a_plays_base_rate_follows_the_same_rule_and_carries_its_count():
    play = PackPlaybook(id="p", trigger_metric="m", recommendation="do x", base_rate=0.6)
    assert any("states a base rate" in e for e in P.prior_problems(_pack(playbooks=[play])))
    play.measured_on = ["olist"]
    assert any("base_rate_n" in e for e in P.prior_problems(_pack(playbooks=[play])))
    play.base_rate_n = 12
    assert P.prior_problems(_pack(playbooks=[play])) == []
    assert P.base_rates(_pack(playbooks=[play]))[0]["status"] == "measured on olist over 12 cases"
    assert any("0 to 1" in e for e in P.prior_problems(_pack(playbooks=[PackPlaybook(id="q", trigger_metric="m", recommendation="y",
                                                                                      base_rate=1.4, unmeasured=True)])))


def test_a_template_names_what_the_kernel_has():
    bad = _pack(scenarios=[PackScenarioTemplate(id="s1", method="learned"), PackScenarioTemplate(id="s2", method="identity"),
                           PackScenarioTemplate(id="s3", method="intervention")],
                missions=[PackMissionTemplate(id="t1", name="x", objective={}, cadence="daily"),
                          PackMissionTemplate(id="t2", name="y", objective={"metric": "m", "direction": "sideways"},
                                              constraints=[{"metric": "", "bound": "roughly"}])])
    problems = P.prior_problems(bad)
    assert any("not on the ladder" in e for e in problems) and any("names its formula" in e for e in problems)
    assert any("names the kind of decision" in e for e in problems)
    assert any("names a metric" in e and "t1" in e for e in problems) and any("cadence 'daily'" in e for e in problems)
    assert any("up, down or hold" in e for e in problems) and any("at_least or at_most" in e for e in problems)
    assert any("a constraint names a metric" in e for e in problems)


def test_the_two_verticals_packs_ship_priors_and_templates_that_pass_the_gate():
    for pid, monitors, missions, scenarios in (("core-ecommerce", {"delivery_promise_breach_rate", "return_rate"},
                                                {"protect_gross_margin", "cut_returns_without_hurting_conversion", "keep_stock_cover_inside_a_band"},
                                                {"price_identity", "promotion_pause"}),
                                               ("banking", {"net_interest_margin", "noncurrent_loan_rate", "approval_rate"},
                                                {"hold_cost_of_risk"}, {"liquidity_runoff"}),
                                               ("b2b-saas", {"net_revenue_retention", "gross_revenue_retention", "cac_payback_months",
                                                             "activation_rate", "win_rate", "pipeline_coverage"},
                                                {"hold_net_retention_above_a_floor", "find_churn_risk_early", "improve_forecast_accuracy"},
                                                {"runway", "capacity_to_bookings", "loss_of_a_named_account", "conversion_assumption"})):
        pack = load_pack(pack_dir(pid))
        assert {m.id for m in pack.monitors} == monitors and {t.id for t in pack.missions} == missions
        assert {s.id for s in pack.scenarios} == scenarios
        assert P.prior_problems(pack) == []
        report = validate_loaded(pack)
        assert not [e for e in report.errors if "prior" in e or "template" in e or "band" in e], report.errors
    commerce = load_pack(pack_dir("core-ecommerce"))
    priors = {r["id"]: r for r in P.monitor_priors(commerce)}
    assert priors["delivery_promise_breach_rate"]["measured_on"] == ["olist-2026-09-24", "thelook-2026-09-24"]
    assert priors["delivery_promise_breach_rate"]["low"] == 0.0811 and priors["return_rate"]["low"] is None
    assert "unmeasured" in priors["return_rate"]["status"]
    banking = load_pack(pack_dir("banking"))
    nim = next(r for r in P.monitor_priors(banking) if r["id"] == "net_interest_margin")
    assert nim["measured_on"] == ["fdic-financials-2025-q2"] and nim["high"] == 0.09415
    body = P.mission_templates(banking)[0]["body"]
    assert body["objective"]["metric"] == "net_charge_off_rate" and body["constraints"][0]["metric"] == "approval_rate"
    assert body["state"] == "proposed" and "a person writes the mission" in P.mission_templates(banking)[0]["note"]


# ── the pack writer ────────────────────────────────────────────────────────────────────────

def _graph(conn: str) -> OntologyGraph:
    g = OntologyGraph(connection_id=conn, schema_name="shop", schema_fingerprint="fp-1")
    g.entities["Order"] = OntologyEntity(id="Order", display_name="Order", source_tables=["shop.orders"], identity_key="order_id",
                                         grain_verified=True)
    g.entities["Customer"] = OntologyEntity(id="Customer", display_name="Customer", source_tables=["shop.customers"],
                                            identity_key="customer_id", grain_verified=True)
    g.relationships["Order_Customer"] = OntologyRelationship(
        id="Order_Customer", from_entity="Order", to_entity="Customer", cardinality="N:1",
        join_sql="orders.customer_id = customers.customer_id", from_table="shop.orders", from_col="customer_id",
        to_table="shop.customers", to_col="customer_id", measured_cardinality="N:1", cardinality_note="measured N:1")
    return g


def test_a_packs_map_measured_on_connect_is_booked_into_the_record_as_the_packs_hypotheses():
    from aughor.packs.ontology_map import apply_core_claims, record_claims, resolve_ontology
    from aughor.record.writers import book_pack_claims, pack_claims
    conn = _conn()
    graph = _graph(conn)
    report = apply_core_claims(graph, resolve_ontology("core-ecommerce"), "core-ecommerce", None)
    out = book_pack_claims(report, connection_id=conn, schema_name="shop", fingerprint=graph.schema_fingerprint)
    assert out["booked"] == len(report.claims) and out["by_state"]["supported"] >= 3 and out["by_state"]["open"] >= 5
    booked = {(c.extra["claim_kind"], c.extra["subject"]): c for c in pack_claims(conn, pack_id="core-ecommerce")}
    order = booked[("object", "Order")]
    assert order.kind == "hypothesis" and order.state == "supported" and order.tier == "mined" and order.author == "pack:core-ecommerce"
    assert order.warrants[0].kind == "run" and order.warrants[0].ref == f"ontology:{conn}:shop:fp-1"
    assert "the pack expects present" in order.statement.text and "measured: Order (shop.orders)" in order.statement.text
    shipment = booked[("object", "Shipment")]
    assert shipment.state == "open" and shipment.tier == "said" and shipment.warrants == [] and shipment.status == "Provisional"
    link = booked[("link", "Order → Customer")]
    assert link.state == "supported" and link.extra["measured"] == "N:1"
    # the next build restates every claim in place — one claim per subject, its history kept
    again = record_claims(apply_core_claims(graph, resolve_ontology("core-ecommerce"), "core-ecommerce", None), graph, conn, "shop")
    assert again["booked"] == out["booked"]
    latest = C.latest(order.key)
    assert latest.version == 2 and latest.supersedes == order.id and len(pack_claims(conn, pack_id="core-ecommerce")) == len(report.claims)
    # a measured-false claim is refuted
    graph.relationships["Order_Customer"].measured_cardinality = "N:N"
    refuted = apply_core_claims(graph, resolve_ontology("core-ecommerce"), "core-ecommerce", None)
    record_claims(refuted, graph, conn, "shop")
    assert C.latest(link.key).state == "refuted" and C.latest(link.key).version == 3
    assert book_pack_claims(report, connection_id="", schema_name="shop")["booked"] == 0


def test_mission_templates_are_read_through_the_records_door():
    from aughor.routers import record as R
    out = R.list_record_mission_templates(pack_id="core-ecommerce")
    assert out["packs"] == ["core-ecommerce"] and {t["id"] for t in out["templates"]} == {
        "protect_gross_margin", "cut_returns_without_hurting_conversion", "keep_stock_cover_inside_a_band"}
    assert out["templates"][0]["body"]["cadence"] in ("monthly", "weekly")
    empty = R.list_record_mission_templates(connection_id=_conn())
    assert empty["templates"] == [] and "no pack is bound" in empty["note"]
    with pytest.raises(Exception):
        R.list_record_mission_templates(connection_id=None, pack_id="no-such-pack")["templates"][0]
