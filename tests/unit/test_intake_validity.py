"""JD-2 — the rules that keep the intake-validity number honest.

Hermetic: no LLM, no warehouse, no checkpoint store. `evals/intake_validity_eval.py`'s pure
helpers are imported the way `tests/unit/test_ablation_framed_arm.py` imports the ablation
harness's, so the eval keeps a CI gate without `evals/` joining the suite.

Each test here pins a rule that moves the measured rate DOWN. That direction is the point: a
harness whose mistakes inflate its own finding is worthless as evidence.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evals.intake_validity_eval import classify, how_wrong, measure  # noqa: E402

REF = {
    "tables": {"luxexperience.orders", "luxexperience.order_items", "main.orders"},
    "columns": {"luxexperience.orders.order_date", "luxexperience.order_items.brand_tier",
                "main.orders.ship_date"},
    "schemas": {"luxexperience", "main"},
    "warehouses": ["test.duckdb"],
}


def _spec(**kw):
    base = {"conn": "c1", "investigation_id": "inv", "question": "q",
            "metric_table": "luxexperience.orders", "date_column": "luxexperience.orders.order_date",
            "dimensions": []}
    base.update(kw)
    return base


def test_a_schema_we_cannot_read_is_unverifiable_never_invalid():
    """A failed probe and a true negative look identical. BigQuery and a `missimi` schema
    present in no local warehouse are counted in NEITHER the numerator nor the denominator."""
    assert classify("bigquery_public.thelook.orders", REF["tables"], REF["schemas"]) == "unverifiable"
    assert classify("missimi.order_items", REF["tables"], REF["schemas"]) == "unverifiable"

    out = measure({"t": _spec(metric_table="missimi.order_items")}, {"t": 1}, REF)
    f = out["by_field"]["metric_table"]
    assert (f["invalid"], f["unverifiable"], f["verifiable"]) == (0, 1, 0)
    assert f["invalid_rate"] is None, "a rate over an empty denominator is not zero, it is absent"


def test_a_name_is_not_invalid_for_its_casing():
    """SQL identifiers are case-insensitive; marking `LuxExperience.Orders` invalid would be
    the harness inventing a failure."""
    assert classify("LuxExperience.Orders", REF["tables"], REF["schemas"]) == "valid"
    assert classify("  luxexperience.orders  ", REF["tables"], REF["schemas"]) == "valid"


def test_an_absent_pick_is_neither_valid_nor_invalid():
    for empty in (None, "", "NONE", "none", "null", "N/A"):
        assert classify(empty, REF["columns"], REF["schemas"]) == "none"


def test_one_investigation_counts_once_however_many_checkpoints_it_wrote():
    """A run stamps its spec into every checkpoint it takes. Counting checkpoints would turn
    one bad pick into five and inflate the headline."""
    bad = _spec(metric_table="luxexperience.brand_collaborations")
    out = measure({"one-thread": bad}, {"one-thread": 1}, REF)
    assert out["investigations_with_a_spec"] == 1
    assert out["by_field"]["metric_table"]["invalid"] == 1
    assert out["runs_with_at_least_one_invalid"] == 1


def test_a_run_is_counted_once_even_with_several_bad_names():
    """The run-level number answers "how many investigations were affected", not "how many
    bad names were there" — the two must not be conflated."""
    out = measure({"t": _spec(metric_table="luxexperience.ghost",
                              date_column="luxexperience.ghost.when",
                              dimensions=["luxexperience.ghost.a", "luxexperience.ghost.b"])},
                  {"t": 1}, REF)
    assert out["runs_with_at_least_one_invalid"] == 1
    assert sum(f["invalid"] for f in out["by_field"].values()) == 4


def test_how_a_name_is_wrong_separates_invention_from_drift():
    """A table in no schema was invented. A real table or column in the WRONG schema cannot be
    drift — the name was right and the place was not."""
    assert how_wrong("luxexperience.clienteling_interactions", REF) == "table does not exist in any warehouse"
    assert how_wrong("main.order_items.brand_tier", REF) == "right table and column, wrong schema"
    assert how_wrong("main.order_items", REF) == "right table, wrong schema"
    assert how_wrong("luxexperience.orders.invented_column", REF) == "real table, column does not exist"


def test_the_falsifier_fires_when_the_free_text_picks_were_fine():
    """JD-2 claims a closed list removes a failure. If nothing is failing it removes nothing,
    and the harness must say so rather than reporting a clean 0% as a win."""
    clean = measure({"t": _spec(dimensions=["luxexperience.order_items.brand_tier"])}, {"t": 1}, REF)
    assert clean["falsifier"]["nothing_to_fix"] is True

    dirty = measure({"t": _spec(metric_table="luxexperience.ghost")}, {"t": 1}, REF)
    assert dirty["falsifier"]["nothing_to_fix"] is False


def test_an_empty_corpus_is_inconclusive_not_a_pass():
    """A zero read as a pass is how a guard passes for the wrong reason."""
    out = measure({}, {}, REF)
    assert out["inconclusive"] is True
    assert out["runs_with_at_least_one_invalid"] == 0


def test_a_spec_that_changed_mid_run_is_reported():
    """The companion fact that decides what the rate MEANS: a spec rewritten mid-run was a
    proposal the repair caught, and one that never changed is what the run actually used."""
    specs = {"a": _spec(), "b": _spec()}
    assert measure(specs, {"a": 1, "b": 1}, REF)["threads_whose_spec_changed_mid_run"] == 0
    assert measure(specs, {"a": 3, "b": 1}, REF)["threads_whose_spec_changed_mid_run"] == 1
