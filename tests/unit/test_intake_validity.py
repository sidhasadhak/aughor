"""JD-2's premise test — and the rules that stopped it measuring the wrong thing.

Hermetic: no LLM, no warehouse, no checkpoint store. `evals/intake_validity_eval.py`'s pure
helpers are imported the way `tests/unit/test_ablation_framed_arm.py` imports the ablation
harness's, so the eval keeps a CI gate without `evals/` joining the suite.

The history matters, because it is what these tests exist to prevent. A first version of this
harness compared three months of intake specs against the warehouses in `data/*.duckdb` and
reported ~20% of picks naming tables that did not exist. Every headline example was real: the
`workspace` connection is a `local_upload` store under `data/uploads/`, one connection points
at a DuckDB outside `data/` entirely, schemas have since been removed and some connections the
corpus used no longer exist. The harness had not looked at the right warehouse, and a failed
probe reads exactly like a true negative.

So the ground truth is now the schema block PERSISTED WITH EACH RUN. It cannot drift, because
it travels with the thing it describes.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evals.intake_validity_eval import measure, shown_tokens, was_shown  # noqa: E402

BLOCK = """
## luxexperience.orders
| Column | Type |
| order_id | VARCHAR |
| order_date | DATE |
| gmv_eur | DOUBLE |

## data_co.data_co_supplychain
| shipping date (DateOrders) | VARCHAR |
"""
TOKENS = shown_tokens(BLOCK)


def _spec(**kw):
    base = {"conn": "workspace", "investigation_id": "inv", "question": "q",
            "metric_table": "luxexperience.orders",
            "date_column": "luxexperience.orders.order_date",
            "dimensions": [], "schema_shown": BLOCK}
    base.update(kw)
    return base


def test_a_pick_counts_as_shown_only_when_its_tokens_are_in_the_block():
    assert was_shown("luxexperience.orders", TOKENS) == "shown"
    assert was_shown("luxexperience.orders.order_date", TOKENS) == "shown"
    assert was_shown("luxexperience.platforms", TOKENS) == "not_shown"
    assert was_shown("luxexperience.orders.invented", TOKENS) == "column_not_shown"


def test_membership_is_by_token_not_substring():
    """A substring test would count `order` as shown because `order_id` is — and that error
    flatters the refutation, because it makes the model look like it picked something real."""
    assert "order" not in TOKENS and "order_id" in TOKENS
    assert was_shown("luxexperience.orders.order", TOKENS) == "column_not_shown"


def test_a_column_name_with_spaces_and_brackets_still_matches():
    """Real columns are not all identifiers — `shipping date (DateOrders)` is one of yours."""
    assert was_shown("data_co.data_co_supplychain.shipping date (DateOrders)", TOKENS) == "shown"


def test_matching_ignores_case():
    assert was_shown("LuxExperience.Orders.ORDER_DATE", TOKENS) == "shown"


def test_an_absent_pick_is_not_scored():
    for empty in (None, "", "NONE", "none", "null", "N/A"):
        assert was_shown(empty, TOKENS) == "none"
    out = measure({"t": _spec(date_column="NONE")}, {"t": 1})
    assert out["by_field"]["date_column"]["none"] == 1
    assert out["by_field"]["date_column"]["scored"] == 0


def test_a_run_that_persisted_no_schema_is_excluded_never_scored_as_a_miss():
    """Otherwise the harness would invent misses out of its own blind spot — which is exactly
    the failure the first version of this file shipped."""
    out = measure({"t": _spec(schema_shown="")}, {"t": 1})
    assert out["threads_with_no_schema_persisted"] == 1
    assert out["overall"]["picks_scored"] == 0
    assert out["inconclusive"] is True


def test_one_thread_counts_once_however_many_checkpoints_it_wrote():
    out = measure({"one": _spec(dimensions=["luxexperience.orders.gmv_eur"])}, {"one": 1})
    assert out["threads_with_a_spec"] == 1
    assert out["overall"]["picks_scored"] == 3


def test_threads_and_investigations_are_counted_separately():
    """Two probe threads share one investigation_id in the live corpus, so 202 threads are
    201 investigations. Pairing one numerator with the other label is a real mislabel."""
    specs = {"a": _spec(investigation_id="same"), "b": _spec(investigation_id="same")}
    out = measure(specs, {"a": 1, "b": 1})
    assert out["threads_with_a_spec"] == 2
    assert out["investigations_with_a_spec"] == 1


def test_the_falsifier_fires_when_the_field_already_picks_from_the_list():
    """JD-2's whole argument is that a closed list removes picks naming what does not exist.
    If the free-text field already picks from what it was shown, it removes nothing."""
    clean = measure({"t": _spec(dimensions=["luxexperience.orders.gmv_eur"])}, {"t": 1})
    assert clean["falsifier"]["nothing_to_fix"] is True

    dirty = {f"t{i}": _spec(metric_table="luxexperience.platforms") for i in range(50)}
    assert measure(dirty, {k: 1 for k in dirty})["falsifier"]["nothing_to_fix"] is False


def test_a_spec_that_changed_mid_run_is_reported():
    specs = {"a": _spec(), "b": _spec()}
    assert measure(specs, {"a": 1, "b": 1})["threads_whose_spec_changed_mid_run"] == 0
    assert measure(specs, {"a": 3, "b": 1})["threads_whose_spec_changed_mid_run"] == 1
