"""The 2027 study's close-out, C8 — the second deep vertical of §P, B2B SaaS, drafted as a package
(`packs/b2b-saas/`), and the rule its provenance is held to.

What these hold: the package loads and validates with no error; it is a DRAFT a person must review (gate 6) and
cannot be promoted while any source it cites is `unread` — every one is, because the publishers' pages were blocked
where it was drafted; an unread source carries no figures, and the static gate refuses one that does; every rule of
the static gate but the dataset's holds on it (gate 3 run with the anatomy forced finds the missing dataset and
nothing else); its priors say where they were measured or say none; its terms are proposable on connect; and a
`published` date may be as coarse as the month or the year the publisher gives.
"""
from __future__ import annotations

import copy

import pytest

from aughor.packs import priors as P
from aughor.packs.gate3 import run_gate3
from aughor.packs.loader import load_pack
from aughor.packs.roots import pack_dir
from aughor.packs.validate import validate_loaded

PACK = "b2b-saas"


@pytest.fixture(scope="module")
def pack():
    root = pack_dir(PACK)
    assert root is not None, "the B2B SaaS package ships under packs/"
    return load_pack(root)


def test_the_package_loads_validates_and_is_a_draft_nobody_reads_yet(pack):
    report = validate_loaded(pack)
    assert report.errors == [], report.errors
    assert pack.manifest.status == "draft" and pack.manifest.anatomy == 0 and not pack.manifest.steers
    assert {m.name for m in pack.metrics} == {"monthly_recurring_revenue", "annual_recurring_revenue", "net_revenue_retention",
                                              "gross_revenue_retention", "cac_payback_months", "sales_cycle_days",
                                              "activation_rate", "arr_growth_rate"}
    assert set(pack.entities) == {"subscription", "account_period", "opportunity", "acquisition_period", "signup", "company_period"}
    assert {o.name for o in pack.ontology.objects} >= {"Account", "Contact", "Opportunity", "Subscription", "Invoice", "Plan", "Seat", "Ticket"}
    assert len(pack.playbooks) == 9 and sum(1 for p in pack.playbooks if p.kind == "data_quality") == 3
    assert len(pack.evals) == 8 and all("dataset" not in g.expect for g in pack.evals)


def test_every_static_rule_but_the_datasets_holds_when_the_anatomy_is_forced(pack):
    forced = copy.deepcopy(pack)
    forced.manifest.anatomy = 1
    lines = run_gate3(forced).lines()
    assert lines == ["[anatomy] pack: anatomy 1 needs datasets/*.yaml"], lines


def test_every_source_is_unread_and_so_carries_no_figures_and_says_how_it_was_reached(pack):
    assert pack.sources and all(s.unread for s in pack.sources)
    assert all(not s.figures for s in pack.sources)
    assert all("NOT READ HERE" in s.notes and "as indexed" in s.notes.lower() for s in pack.sources)
    assert all(s.retrieved == "2026-10-05" for s in pack.sources)
    # a published date as coarse as the publisher gives: a month from an upload path, or the report's year
    by_id = {s.id: s for s in pack.sources}
    assert by_id["saas-capital-retention-2025"].published == "2025-09" and by_id["benchmarkit-2025"].published == "2025"
    # every band and every play cites a declared source, and says it is as indexed
    ids = set(by_id)
    for m in pack.metrics:
        assert m.sane_range is not None and set(m.sane_range.sources) <= ids and "indexed" in m.sane_range.basis.lower(), m.name
    for p in pack.playbooks:
        assert p.sources and set(p.sources) <= ids, p.id


def test_an_unread_source_keeps_the_package_a_draft(tmp_path):
    """The promotion door refuses `active` while a cited source is unread — the review IS reading them."""
    import shutil

    from aughor.packs.promote import PromotionRefused, set_status
    shutil.copytree(pack_dir(PACK), tmp_path / PACK)
    with pytest.raises(PromotionRefused) as exc:
        set_status(PACK, "active", packs_dir=tmp_path, actor="user:ana")
    assert "marked unread" in str(exc.value) and "saas-capital-retention-2025" in str(exc.value)
    assert load_pack(tmp_path / PACK).manifest.status == "draft"


def test_the_priors_say_where_they_were_measured_or_say_none_and_the_templates_name_what_the_kernel_has(pack):
    assert P.prior_problems(pack) == []
    rows = {r["id"]: r for r in P.monitor_priors(pack)}
    assert rows["net_revenue_retention"]["low"] == 0.98 and rows["net_revenue_retention"]["measured_on"] == ["saas-capital-retention-2025"]
    assert rows["cac_payback_months"]["high"] == 25
    assert all("unmeasured" in rows[k]["status"] for k in ("activation_rate", "win_rate", "pipeline_coverage"))
    missions = {t["id"]: t for t in P.mission_templates(pack)}
    assert set(missions) == {"hold_net_retention_above_a_floor", "find_churn_risk_early", "improve_forecast_accuracy"}
    assert missions["hold_net_retention_above_a_floor"]["body"]["objective"]["metric"] == "net_revenue_retention"
    assert {s["id"] for s in P.scenario_templates(pack)} == {"runway", "capacity_to_bookings", "loss_of_a_named_account", "conversion_assumption"}
    assert all(s["method"] == "identity" and s["formula"] for s in P.scenario_templates(pack))


def test_the_packages_terms_are_proposable_on_connect(pack):
    from aughor.packs.connect import pack_terms
    terms = {(t["subject_kind"], t["subject_id"], t["synonym"]) for t in pack_terms(pack)}
    assert ("metric", "net_revenue_retention", "nrr") in terms and ("metric", "monthly_recurring_revenue", "mrr") in terms
    assert all(k == "metric" for k, _, _ in terms)          # the objects' terms wait for a graph
