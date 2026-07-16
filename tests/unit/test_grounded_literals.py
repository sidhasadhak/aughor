"""R7 — the grounded-literal contract, enforced post-generation.

A value entity resolution BOUND (verified present) must reach the SQL
verbatim; a near-miss re-spelling of the same entity is rewritten to the
verified value. A genuinely different literal (a deliberate comparison
entity) is never touched, and a dry-run veto keeps a runnable query over a
broken repair. Pure — no DB, no model.
"""
from __future__ import annotations

from types import SimpleNamespace

from aughor.sql.grounded_literals import enforce_grounded_literals


def _b(table: str, column: str, value: str):
    return SimpleNamespace(noun=value.lower(), table=table, column=column,
                           value=value, confidence=0.95)


def test_respelled_literal_rewritten_to_the_bound_value():
    sql = "SELECT SUM(amount) FROM sales WHERE brand = 'Mytheresea'"
    fixed, repairs = enforce_grounded_literals(sql, [_b("sales", "brand", "Mytheresa")])
    assert "'Mytheresa'" in fixed and "Mytheresea" not in fixed
    assert repairs == [{"column": "sales.brand", "from": "Mytheresea",
                        "to": "Mytheresa", "similarity": repairs[0]["similarity"]}]
    assert repairs[0]["similarity"] >= 0.75


def test_verbatim_literal_untouched():
    sql = "SELECT 1 FROM sales WHERE brand = 'Mytheresa'"
    fixed, repairs = enforce_grounded_literals(sql, [_b("sales", "brand", "Mytheresa")])
    assert fixed == sql and repairs == []


def test_different_entity_never_touched():
    # A deliberate comparison entity on the same column must survive.
    sql = "SELECT 1 FROM sales WHERE brand = 'Zalando'"
    fixed, repairs = enforce_grounded_literals(sql, [_b("sales", "brand", "Mytheresa")])
    assert fixed == sql and repairs == []


def test_in_list_member_drift_rewritten():
    sql = "SELECT 1 FROM sales WHERE brand IN ('Mytheresea', 'Zalando')"
    fixed, repairs = enforce_grounded_literals(sql, [_b("sales", "brand", "Mytheresa")])
    assert "'Mytheresa'" in fixed and "'Zalando'" in fixed
    assert len(repairs) == 1


def test_negations_and_other_columns_untouched():
    sql = ("SELECT 1 FROM sales WHERE brand != 'Mytheresea' "
           "AND region = 'Mytheresea'")
    fixed, repairs = enforce_grounded_literals(sql, [_b("sales", "brand", "Mytheresa")])
    assert fixed == sql and repairs == []      # never weaken a negation; wrong column ignored


def test_alias_resolved_table_matches_binding():
    sql = "SELECT SUM(s.amount) FROM main.sales AS s WHERE s.brand = 'mytheresa'"
    fixed, repairs = enforce_grounded_literals(sql, [_b("sales", "brand", "Mytheresa")])
    assert "'Mytheresa'" in fixed              # case drift on the bound column repaired
    assert len(repairs) == 1


def test_dry_run_veto_keeps_the_original():
    sql = "SELECT 1 FROM sales WHERE brand = 'Mytheresea'"
    fixed, repairs = enforce_grounded_literals(
        sql, [_b("sales", "brand", "Mytheresa")],
        dry_run=lambda s: (False, "nope"))
    assert fixed == sql and repairs == []


def test_unparseable_sql_fails_open():
    sql = "NOT SQL AT ALL (("
    fixed, repairs = enforce_grounded_literals(sql, [_b("sales", "brand", "Mytheresa")])
    assert fixed == sql and repairs == []


def test_no_bindings_is_a_noop():
    sql = "SELECT 1 FROM sales WHERE brand = 'Mytheresea'"
    assert enforce_grounded_literals(sql, []) == (sql, [])
