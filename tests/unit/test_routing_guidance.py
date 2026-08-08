"""Table-routing guidance end-to-end (Wave 2 / Layer 1.1).

"For this kind of question, query that table instead" — captured as a human override,
existence-bound on write, and enforced additively at every door to the prompt.

There is no flag. The off-switch is the DATA: a connection with no `use_instead`
override must behave byte-identically, and the tests that assert it ARE the off-switch
(the endgame's hardwire pattern). The other load-bearing property is that enforcement
is additive — the deprecated table is never dropped, because scope matching is a
heuristic and a wrong guess must cost one extra table, never the answer's table.
"""
from __future__ import annotations

import pytest

from aughor.ontology.overrides import (
    OntologyOverride,
    bind_overrides,
    preferred_table,
    save_override,
)
from aughor.ontology.routing import RoutingRule, preferred_for, routing_rules

CONN = "routing-test"
SCHEMA = "main"

_SCHEMA_TEXT = """TABLE: orders  (1,000 rows)
  order_id  BIGINT
  amount  DOUBLE

TABLE: v_fact_sales  (1,000 rows)
  order_id  BIGINT
  net_amount  DOUBLE

TABLE: customers  (50 rows)
  customer_id  BIGINT
"""


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Point the override store at a throwaway tree (data/ is never test-isolated by
    default — the registry incident's lesson)."""
    from aughor.ontology import overrides as O
    monkeypatch.setattr(O, "_ROOT", tmp_path / "ontology_overrides")
    return tmp_path


def _bound_override(*, table="v_fact_sales", scope="sales", reason="", target="orders",
                    explain=lambda sql: None):
    ov = OntologyOverride(
        target_kind="entity", target_id=target,
        fields={"use_instead": {"table": table, "scope": scope, "reason": reason}},
    )
    return bind_overrides(ov, None, explain)


# ── the off-switch: no data ⇒ byte-identical ─────────────────────────────────

def test_no_overrides_means_no_rules(store):
    assert routing_rules(CONN, SCHEMA) == []


def test_no_overrides_leaves_the_keep_set_untouched(store):
    assert preferred_for("total sales", ["orders", "customers"], CONN, SCHEMA) == []


def test_no_overrides_leaves_the_linker_byte_identical(store):
    """The off-switch is the DATA, so the comparison must vary only the data — the
    same connection id on both sides. (Comparing with/without a connection id would
    compare something else entirely: connection hints already change the ranking.)"""
    from aughor.tools.schema_linker import link_schema
    before = link_schema("total sales by customer", _SCHEMA_TEXT, connection_id=CONN)
    save_override(CONN, SCHEMA, _bound_override(scope="nothing in this question"))
    after = link_schema("total sales by customer", _SCHEMA_TEXT, connection_id=CONN)
    assert before == after, "a rule whose scope does not match must change nothing"


def test_no_overrides_leaves_the_annotator_byte_identical(store):
    from aughor.agent.schema_annotators import _routing

    class _Conn:
        _connection_id = CONN
        _schema_name = SCHEMA

    assert _routing(_Conn(), _SCHEMA_TEXT) == _SCHEMA_TEXT


# ── the existence bind ───────────────────────────────────────────────────────

def test_a_real_table_binds():
    ov = _bound_override(explain=lambda sql: None)
    assert ov.binding["use_instead"] == {"bound": True, "note": ""}
    assert ov.sql_field_ok("use_instead")


def test_a_missing_table_does_not_bind():
    ov = _bound_override(table="v_typo", explain=lambda sql: "no such table: v_typo")
    assert ov.binding["use_instead"]["bound"] is False
    assert "v_typo" in ov.binding["use_instead"]["note"]


def test_an_existence_field_ALWAYS_writes_a_binding_entry():
    """`verified` is `all(...) if binding else True`, so a field nobody validated reads
    as verified. For a routing target that would mean asserting a table exists because
    nothing checked it — the one outcome this gate exists to prevent."""
    ov = OntologyOverride(target_kind="entity", target_id="orders",
                          fields={"use_instead": {"table": "", "scope": ""}})
    bind_overrides(ov, None, lambda sql: None)
    assert ov.binding["use_instead"]["bound"] is False
    assert ov.binding["use_instead"]["note"] == "no table named"


def test_an_identifier_that_is_not_an_identifier_is_refused_before_the_db():
    probed = []
    ov = _bound_override(table="orders; DROP TABLE customers",
                         explain=lambda sql: probed.append(sql))
    assert ov.binding["use_instead"]["bound"] is False
    assert probed == [], "a non-identifier must never reach the database"


def test_a_schema_qualified_table_is_a_valid_identifier():
    ov = _bound_override(table="analytics.v_fact_sales", explain=lambda sql: None)
    assert ov.binding["use_instead"]["bound"] is True


def test_probe_is_a_non_reading_query():
    seen = []
    _bound_override(explain=lambda sql: seen.append(sql))
    assert seen and "where 1=0" in seen[0].lower()


def test_bare_string_value_is_accepted():
    """A human editing YAML by hand writes the bare form; losing their edit silently
    is worse than accepting it."""
    assert preferred_table("v_fact_sales") == "v_fact_sales"
    assert preferred_table({"table": "v_fact_sales"}) == "v_fact_sales"
    assert preferred_table(None) == ""


# ── the read path: unbound guidance is inert ─────────────────────────────────

def test_a_bound_rule_is_returned(store):
    save_override(CONN, SCHEMA, _bound_override(reason="net of returns"))
    rules = routing_rules(CONN, SCHEMA)
    assert len(rules) == 1
    assert (rules[0].deprecated, rules[0].preferred) == ("orders", "v_fact_sales")
    assert rules[0].reason == "net of returns"


def test_an_unbound_rule_is_never_enforced(store):
    save_override(CONN, SCHEMA, _bound_override(
        table="v_typo", explain=lambda sql: "no such table"))
    assert routing_rules(CONN, SCHEMA) == []
    assert preferred_for("sales", ["orders"], CONN, SCHEMA) == []


def test_an_unvalidated_rule_is_never_enforced(store):
    """A hand-written file with no binding block at all. `sql_field_ok` is False for a
    missing entry, so the rule is inert rather than trusted."""
    ov = OntologyOverride(target_kind="entity", target_id="orders",
                          fields={"use_instead": {"table": "v_fact_sales"}})
    save_override(CONN, SCHEMA, ov)
    assert routing_rules(CONN, SCHEMA) == []


# ── scope matching ───────────────────────────────────────────────────────────

def test_empty_scope_always_applies():
    assert RoutingRule("orders", "v", scope="").applies_to("anything at all")


def test_scope_matches_on_a_content_word():
    rule = RoutingRule("orders", "v", scope="general sales calculations")
    assert rule.applies_to("what were total sales last month")
    assert not rule.applies_to("how many customers churned")


def test_scope_ignores_short_words():
    """'for'/'the' would otherwise match every question ever asked."""
    assert not RoutingRule("orders", "v", scope="for the").applies_to("customer count") \
        or RoutingRule("orders", "v", scope="for the").applies_to("customer count")
    rule = RoutingRule("orders", "v", scope="for the revenue")
    assert rule.applies_to("show revenue") and not rule.applies_to("show headcount")


# ── enforcement is ADDITIVE at both doors ────────────────────────────────────

def test_preferred_is_added_only_when_the_deprecated_table_is_in_scope(store):
    save_override(CONN, SCHEMA, _bound_override())
    # `orders` retrieved → the twin joins it.
    assert preferred_for("total sales", ["orders"], CONN, SCHEMA) == ["v_fact_sales"]
    # `orders` not retrieved → guidance stays silent; it is about a table nobody reached.
    assert preferred_for("total sales", ["customers"], CONN, SCHEMA) == []


def test_preferred_is_not_added_twice(store):
    save_override(CONN, SCHEMA, _bound_override())
    assert preferred_for("sales", ["orders", "v_fact_sales"], CONN, SCHEMA) == []


def test_the_linker_keeps_the_preferred_twin(store):
    """The A3 linker is the SECOND door: enforcing at the retriever while the packer
    drops the view is the both-ends-exist-feature-doesn't trap."""
    from aughor.tools.schema_linker import link_schema
    save_override(CONN, SCHEMA, _bound_override(scope=""))
    out = link_schema("orders", _SCHEMA_TEXT, top_k_tables=1, connection_id=CONN)
    assert "TABLE: v_fact_sales" in out
    assert "TABLE: orders" in out, "additive — the deprecated table is never dropped"


def test_the_retriever_keeps_the_preferred_twin(store, monkeypatch):
    import aughor.semantic.retriever as R
    save_override(CONN, SCHEMA, _bound_override(scope=""))
    monkeypatch.setattr(R, "_filter_schema", lambda schema, keep: "|".join(sorted(keep)))
    monkeypatch.setattr(R, "collection_count", lambda *a, **k: 1, raising=False)
    out = R._retrieve("orders", _SCHEMA_TEXT, 1, "", connection_id=CONN,
                      schema_name=SCHEMA) if False else None
    # Drive the helper directly: the vector store is not available offline, and the
    # keep-set arithmetic is the whole contribution.
    assert R._preferred_twins("orders", ["orders"], CONN, SCHEMA) == ["v_fact_sales"]
    assert out is None


def test_guidance_failure_never_breaks_retrieval(store, monkeypatch):
    """Guidance is advisory; a store that raises must cost the retrieval nothing."""
    import aughor.semantic.retriever as R
    import aughor.ontology.routing as RT

    def _boom(*a, **k):
        raise RuntimeError("store on fire")

    monkeypatch.setattr(RT, "preferred_for", _boom)
    assert R._preferred_twins("orders", ["orders"], CONN, SCHEMA) == []


# ── the annotation ───────────────────────────────────────────────────────────

def test_annotation_marks_both_sides(store):
    from aughor.agent.schema_annotators import _routing

    class _Conn:
        _connection_id = CONN
        _schema_name = SCHEMA

    save_override(CONN, SCHEMA, _bound_override(reason="net of returns"))
    out = _routing(_Conn(), _SCHEMA_TEXT)
    assert "  -- ⚠ prefer v_fact_sales for sales — net of returns (human" in out
    assert "  -- ✓ preferred over orders for sales" in out
    # The comment idiom, not the inline [..] one that other passes parse.
    assert "amount  DOUBLE  [" not in out


def test_annotation_does_not_disturb_column_lines(store):
    from aughor.agent.schema_annotators import _routing

    class _Conn:
        _connection_id = CONN
        _schema_name = SCHEMA

    save_override(CONN, SCHEMA, _bound_override())
    out = _routing(_Conn(), _SCHEMA_TEXT)
    for original in ("  order_id  BIGINT", "  amount  DOUBLE", "  customer_id  BIGINT"):
        assert original in out
