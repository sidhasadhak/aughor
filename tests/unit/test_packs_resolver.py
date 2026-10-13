"""Entity-binding resolver — proposal engine (P1, 2026-06-27).

A pack declares ROLES, not tables; the resolver proposes role→table/column for a specific
warehouse with evidence + confidence, which is why packs are portable. This tests the pure
proposal engine against synthetic SchemaFacts (the profiler adapter + dry-run verify are the
deferred live-connection half). See aughor/packs/resolver.py.
"""
from aughor.packs import (
    SchemaFacts, TableFact, ColumnFact, propose_bindings, binding_report, load_pack,
)
from aughor.packs.models import RoleSpec
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _retail_facts(business_model="transactional", customer_has_signup=True):
    cust_cols = [ColumnFact("customer_id", "text", is_identity=True)]
    if customer_has_signup:
        cust_cols.append(ColumnFact("signup_ts", "timestamp", is_date=True))
    return SchemaFacts(
        business_model=business_model,
        tables=[
            TableFact("dim_customers", cust_cols, references={}, row_count=1),
            TableFact("fct_orders",
                      [ColumnFact("order_id", "text", is_identity=True),
                       ColumnFact("order_ts", "timestamp", is_date=True),
                       ColumnFact("customer_id", "text")],
                      references={"customer_id": "dim_customers"}, row_count=1),
            TableFact("fct_sessions",
                      [ColumnFact("session_ts", "timestamp", is_date=True),
                       ColumnFact("customer_id", "text")],
                      references={"customer_id": "dim_customers"}, row_count=1),
        ],
    )


def _roles():
    # Mirrors the shipped customer-analytics entities.yaml.
    return {
        "customer": RoleSpec(expects={"kind": "entity", "identity": True}),
        "event": RoleSpec(expects={"kind": "event", "has_timestamp": True, "references": "customer"}),
        "cohort_anchor": RoleSpec(expects={"kind": "date", "of": "customer"}, default="first_event"),
        "active_definition": RoleSpec(
            one_of=["purchased_in_window", "session_in_window", "subscription_open"],
            default="purchased_in_window"),
    }


def test_resolves_customer_to_most_referenced_identity_table():
    props = propose_bindings(_roles(), _retail_facts())
    c = props["customer"]
    assert c.bound and c.table == "dim_customers" and c.column == "customer_id"
    assert c.confidence > 0.6   # referenced by 2 tables → confident


def test_resolves_event_to_dated_fact_referencing_customer():
    props = propose_bindings(_roles(), _retail_facts())
    e = props["event"]
    assert e.bound and e.table in ("fct_orders", "fct_sessions") and e.column.endswith("_ts")
    assert e.confidence >= 0.8   # has FK to the entity


def test_cohort_anchor_uses_entity_date_when_present():
    props = propose_bindings(_roles(), _retail_facts(customer_has_signup=True))
    a = props["cohort_anchor"]
    assert a.bound and a.table == "dim_customers" and a.column == "signup_ts"


def test_cohort_anchor_falls_back_to_first_event():
    props = propose_bindings(_roles(), _retail_facts(customer_has_signup=False))
    a = props["cohort_anchor"]
    assert a.bound and a.value == "first_event" and a.table is None


def test_active_definition_follows_business_model():
    sub = propose_bindings(_roles(), _retail_facts(business_model="subscription"))
    assert sub["active_definition"].value == "subscription_open"
    txn = propose_bindings(_roles(), _retail_facts(business_model="transactional"))
    assert txn["active_definition"].value == "purchased_in_window"


def test_unbindable_entity_is_surfaced_not_guessed():
    # No identity column anywhere → customer can't bind; reported bound=False with evidence.
    facts = SchemaFacts(tables=[TableFact("flat", [ColumnFact("x", "int")])])
    props = propose_bindings({"customer": RoleSpec(expects={"kind": "entity", "identity": True})}, facts)
    assert props["customer"].bound is False
    assert "identity" in props["customer"].evidence


def test_binding_report_summary():
    rep = binding_report(_roles(), _retail_facts())
    assert rep["total"] == 4
    assert rep["groundable_roles"] == 4
    assert rep["fully_groundable"] is True


def test_resolver_grounds_the_shipped_pack():
    # The dogfooded pack's declared roles all bind against a typical retail schema.
    pack = load_pack(REPO / "packs" / "customer-analytics")
    rep = binding_report(pack.entities, _retail_facts())
    assert rep["fully_groundable"], {k: v.evidence for k, v in rep["proposals"].items()}


# LuxExperience's own layout (Postgres `luxexperience`, read over HTTP 2026-10-13) — the tables the retail roles
# compete over. `ownership` carries the most date columns; order_items has none of its own.
_LUX = {
    "order_items": [("order_item_id", "text"), ("order_id", "text"), ("product_id", "text"), ("quantity", "integer"),
                    ("unit_price_eur", "numeric"), ("cost_eur", "numeric"), ("returned", "boolean")],
    "orders": [("order_id", "text"), ("customer_id", "text"), ("order_date", "date"), ("gmv_eur", "numeric"),
               ("status", "text")],
    "customers": [("customer_id", "text"), ("country", "text"), ("signup_fy", "integer")],
    "products": [("product_id", "text"), ("brand", "text"), ("retail_price_eur", "numeric")],
    "ownership": [("platform", "text"), ("parent_entity", "text"), ("effective_from", "date"), ("effective_to", "date")],
    "web_sessions": [("session_id", "text"), ("customer_id", "text"), ("session_start", "text"),
                     ("converted", "boolean"), ("order_id", "text")],
    "returns": [("return_id", "text"), ("order_item_id", "text"), ("order_id", "text"), ("return_date", "date")],
}


def test_retail_on_luxexperience_proposes_what_is_named_for_each_role_and_never_a_dated_guess():
    """2026-10-13: the retail pack's customer and product are kinds `party` and `catalog`, which the resolver had no
    rule for, so no entity resolved; each event then fell to the table with the most date columns — `ownership`, for
    both order_item and cart — and the Bind dialog pre-picked it."""
    from aughor.packs.adapter import schema_facts_from_table_cols
    facts = schema_facts_from_table_cols({t: [c for c, _ in cols] for t, cols in _LUX.items()},
                                         col_types={t: dict(cols) for t, cols in _LUX.items()})
    props = propose_bindings(load_pack(REPO / "packs" / "retail").entities, facts)
    assert (props["customer"].table, props["customer"].column) == ("customers", "customer_id")
    assert (props["product"].table, props["product"].column) == ("products", "product_id")
    # order_item: the table named for it, though it has no date of its own — said, not hidden
    assert props["order_item"].table == "order_items" and props["order_item"].column is None
    assert "no date or time column" in props["order_item"].evidence
    # cart: no table is named for it, and the pack does not declare it is about the customer — so nothing is proposed
    assert props["cart"].bound is False and props["cart"].table is None
    assert "no table is named for cart" in props["cart"].evidence
    assert all(p.table != "ownership" for p in props.values())
