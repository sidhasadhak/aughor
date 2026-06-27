"""Deploy spine — profiler adapter + binding store (P1b, 2026-06-27).

schema_facts_from_table_cols turns a table/column map into the resolver's SchemaFacts;
the binding store pins a resolved mapping per org/pack/connection. See aughor/packs/.
"""
import pytest

from aughor.packs import schema_facts_from_table_cols, propose_bindings
from aughor.packs.models import RoleSpec
from aughor.org.context import using_org
import aughor.packs.bindings as bnd


TABLE_COLS = {
    "dim_customers": ["customer_id", "signup_ts", "country"],
    "fct_orders": ["order_id", "order_ts", "customer_id", "amount"],
    "fct_sessions": ["session_ts", "customer_id"],
}


def test_adapter_detects_identity_dates_and_fks():
    facts = schema_facts_from_table_cols(TABLE_COLS, business_model="transactional")
    cust = facts.table("dim_customers")
    assert any(c.name == "customer_id" and c.is_identity for c in cust.columns)
    assert any(c.name == "signup_ts" and c.is_date for c in cust.columns)
    orders = facts.table("fct_orders")
    assert orders.references.get("customer_id") == "dim_customers"
    assert any(c.name == "order_ts" and c.is_date for c in orders.columns)


def test_adapter_facts_ground_the_roles():
    facts = schema_facts_from_table_cols(TABLE_COLS, business_model="transactional")
    roles = {
        "customer": RoleSpec(expects={"kind": "entity", "identity": True}),
        "event": RoleSpec(expects={"kind": "event", "references": "customer"}),
        "cohort_anchor": RoleSpec(expects={"kind": "date", "of": "customer"}, default="first_event"),
    }
    props = propose_bindings(roles, facts)
    assert props["customer"].table == "dim_customers"
    assert props["event"].bound and props["event"].column.endswith("_ts")
    assert props["cohort_anchor"].column == "signup_ts"


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(bnd, "_DB_PATH", tmp_path / "pack_bindings.db")
    return bnd


def test_binding_save_load_roundtrip(store):
    with using_org("org-a"):
        store.save_binding("customer-analytics", "conn1",
                           {"customer": {"table": "dim_customers", "column": "customer_id"}},
                           verified=True)
        b = store.load_binding("customer-analytics", "conn1")
        assert b["bindings"]["customer"]["table"] == "dim_customers"
        assert b["verified"] is True
        assert store.is_bound("customer-analytics", "conn1", require_verified=True)


def test_binding_unbound_and_unverified(store):
    with using_org("org-a"):
        assert store.load_binding("x", "y") is None
        assert store.is_bound("x", "y") is False
        store.save_binding("p", "c", {"customer": {}}, verified=False)
        assert store.is_bound("p", "c") is True
        assert store.is_bound("p", "c", require_verified=True) is False


def test_binding_org_scoped(store):
    with using_org("org-a"):
        store.save_binding("p", "c", {"x": {}}, verified=True)
    with using_org("org-b"):
        assert store.load_binding("p", "c") is None
