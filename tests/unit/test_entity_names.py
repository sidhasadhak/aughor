"""A table's entity is named in the singular a reader would write — LuxExperience's `countries` and `corporate_entities`
were the entities "Countrie" and "CorporateEntitie" (2026-10-14)."""
from aughor.ontology.builder import _table_to_entity_name


def test_a_table_name_reads_as_its_singular():
    assert _table_to_entity_name("luxexperience.countries") == "Country"
    assert _table_to_entity_name("corporate_entities") == "CorporateEntity"
    assert _table_to_entity_name("addresses") == "Address"
    assert _table_to_entity_name("order_status") == "OrderStatus"
    assert _table_to_entity_name("analysis") == "Analysis"
    assert _table_to_entity_name("orders") == "Order"                   # unchanged
    assert _table_to_entity_name("order_items") == "OrderItem"
    assert _table_to_entity_name("distribution_centers") == "DistributionCenter"
    assert _table_to_entity_name("dim_customer") == "Customer"
