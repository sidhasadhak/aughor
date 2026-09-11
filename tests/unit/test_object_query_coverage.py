"""ON-2's falsifier receipt, ratcheted (evals/object_query_coverage.py).

The object queries written for the two hard reference sets compile against the committed MEASURED
ontologies, or are refused for a named reason — and on the samples warehouse, seeded here with the
SQL every install gets, every compiled answer equals its reference. The LuxExperience half is
executed where its demo file exists (the receipt in §3.15); its compile verdicts hold everywhere.
"""
from __future__ import annotations

from evals.object_query_coverage import measure, refusal_kind


def test_the_samples_half_compiles_ten_of_twelve_and_every_compiled_answer_equals_its_reference(tmp_path):
    out = measure(datasets=["evals/ablation_samples_ecommerce.jsonl"], samples_db=str(tmp_path / "samples.duckdb"))
    rows = {r["id"]: r for r in out["rows"]}
    refused = {i: r["refusal_kind"] for i, r in rows.items() if r["path"] == "refused"}
    assert refused == {"s10_avg_rating_by_category": "graph", "s12_review_coverage": "graph"}
    wrong = {i: (r.get("class"), r.get("error")) for i, r in rows.items()
             if r["path"] == "compiled" and r.get("class") != "correct"}
    assert not wrong, wrong
    assert out["summary"]["compiled"] == 10 and out["summary"]["falsifier"]["fires"] is False


def test_the_lux_half_compiles_against_its_measured_graph_and_is_refused_only_where_a_link_is_missing():
    out = measure(datasets=["evals/ablation_luxexperience_hard.jsonl"], compile_only=True)
    refused = {r["id"]: r["refusal_kind"] for r in out["rows"] if r["path"] == "refused"}
    assert refused == {"l05_shipping_cost_share": "graph", "l09_never_shipped": "graph"}
    assert out["summary"]["falsifier"]["ir_refusals"] == 0


def test_a_refusal_is_classed_by_what_would_fix_it():
    assert refusal_kind("no link 'review' from Order (in 'review') — its links: order_to_customer") == "graph"
    assert refusal_kind("link x (A → B, N:N) is N:N by measurement — neither side is unique") == "graph"
    assert refusal_kind("measure sum(order.gmv): … that is the fan-out. Anchor the query on Order") == "law"
    assert refusal_kind("Order has no property 'gmv' (in 'gmv')") == "name"
    # measured 2026-09-11: a model filled `metric` AND `path` on 5 of 26 questions — a malformed fill,
    # which the first classifier filed as `ir` and so read as the algebra being too narrow
    assert refusal_kind("measure total_revenue: a named metric carries its own formula — drop `path` "
                        "and `where`, or measure a property with `agg`") == "form"
    assert refusal_kind("filter 'status in' needs `values`: a list of 1–1000") == "form"
    assert refusal_kind("something the algebra has no word for") == "ir"
