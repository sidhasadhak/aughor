""""Needs a formula" and "the formula was rejected" are different facts.

The build-time audit blanks a `value_sql` it cannot trust and returns {metric: reason};
`infer.py` logged that map and threw it away. The catalogue then saw a metric with no
SQL and labelled it ``needs_formula`` — "the columns are identified but no SQL was
proposed. Open it and supply one."

For theLook that sentence is false and expensive. All six of its metrics HAD formulas;
they were dropped because nothing binds on that connection (its BigQuery default dataset
resolves to `<project>.thelook` while the data lives in
`bigquery-public-data.thelook_ecommerce`). The label sends a reader to write SQL when the
fault is the connection, and writing SQL would not fix it.

So the reason is persisted beside the profile — not on `BusinessProfile`, which IS the
generation schema and would describe the field to the model on every inference — and the
catalogue reports ``formula_rejected`` carrying the audit's own words.
"""
from aughor.semantic import metric_catalogue as mc


class _Metric:
    def __init__(self, name, value_sql="", maps_to="order_items.sale_price"):
        self.name = name
        self.value_sql = value_sql
        self.maps_to = maps_to
        self.unit_or_range = "USD"
        self.definition = "d"
        self.why_it_matters = "w"


class _Profile:
    def __init__(self, metrics):
        self.north_star_metrics = metrics


def _entries(monkeypatch, metrics, rejections):
    """Drive `_explorer_entries` over a stored profile + its persisted verdicts."""
    from aughor.business_profile import store as profile_store
    monkeypatch.setattr(profile_store, "load", lambda *a, **k: _Profile(metrics))
    monkeypatch.setattr(profile_store, "load_raw", lambda *a, **k: {"rejections": rejections})
    return {e.label: e for e in mc._explorer_entries("conn", None)}


def test_a_rejected_formula_says_so_and_says_why(monkeypatch):
    rows = _entries(monkeypatch, [_Metric("GMV")], {"GMV": "does not bind: Table must be qualified"})
    gmv = rows["GMV"]
    assert gmv.state == mc.STATE_FORMULA_REJECTED
    assert "does not bind" in gmv.reason, "the audit's own words must reach the row"


def test_a_metric_that_never_had_one_still_needs_a_formula(monkeypatch):
    """The distinction is the whole point: no verdict means nobody wrote SQL, and the
    honest instruction there really is "supply one"."""
    rows = _entries(monkeypatch, [_Metric("GMV")], {})
    assert rows["GMV"].state == mc.STATE_NEEDS_FORMULA
    assert rows["GMV"].reason == ""


def test_a_metric_that_kept_its_formula_is_unaffected(monkeypatch):
    """A stale verdict must never override the SQL actually present — a metric recovered
    by the recipe-grounded regeneration is proposed, not rejected."""
    rows = _entries(monkeypatch, [_Metric("GMV", value_sql="SELECT 1")],
                    {"GMV": "does not bind: stale"})
    assert rows["GMV"].state == mc.STATE_PROPOSED
    assert rows["GMV"].reason == "", "a live formula carries no rejection"


def test_an_older_profile_with_no_verdicts_is_not_guessed_about(monkeypatch):
    """Payloads written before verdicts were recorded have none. Those rows stay
    `needs_formula` rather than being assumed rejected — an unknown reason is not a
    reason, and inventing one is the failure this whole change is about."""
    from aughor.business_profile import store as profile_store
    monkeypatch.setattr(profile_store, "load", lambda *a, **k: _Profile([_Metric("GMV")]))
    monkeypatch.setattr(profile_store, "load_raw", lambda *a, **k: {})   # no key at all
    e = mc._explorer_entries("conn", None)[0]
    assert e.state == mc.STATE_NEEDS_FORMULA and e.reason == ""


def test_a_missing_profile_payload_does_not_break_the_catalogue(monkeypatch):
    """`load_raw` is best-effort; a store that raises must cost the reason, not the row."""
    from aughor.business_profile import store as profile_store

    def _boom(*a, **k):
        raise RuntimeError("store unavailable")

    monkeypatch.setattr(profile_store, "load", lambda *a, **k: _Profile([_Metric("GMV")]))
    monkeypatch.setattr(profile_store, "load_raw", _boom)
    rows = mc._explorer_entries("conn", None)
    assert len(rows) == 1 and rows[0].state == mc.STATE_NEEDS_FORMULA


def test_the_verdict_survives_a_round_trip_through_the_store(tmp_path, monkeypatch):
    """The reason is worthless if `save` drops it — it lives beside the profile, and the
    profile model must stay the model the LLM is asked to fill."""
    from aughor.business_profile.models import BusinessProfile
    assert "rejections" not in BusinessProfile.model_fields, (
        "the verdict must NOT be a profile field: BusinessProfile is the generation "
        "schema, so a field here is described to the model on every inference"
    )
    import inspect
    from aughor.business_profile import store as profile_store
    assert "rejections" in inspect.signature(profile_store.save).parameters
