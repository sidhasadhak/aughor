"""A suite is found by its KEY; its title is free to change (2026-10-06).

Suites were found by NAME, and their runs and graduation receipts hang off the row that name
found — so a receipt said "DO NOT rename", and the eval suites could not be named by purpose.
"""
from __future__ import annotations

from aughor.evals import store


def test_an_unkeyed_suite_is_adopted_under_its_former_name_and_keeps_its_id_and_runs():
    old = store.create_suite("context graph — finding consolidation (N3) [kt1]", target="consolidation")
    run_id = store.start_run(old["id"])

    suite, created = store.ensure_suite(
        "kt1_consolidation", "Context graph — consolidating findings keeps every one checkable [kt1]",
        formerly=("context graph — finding consolidation (N3) [kt1]",))

    assert created is False and suite["id"] == old["id"]
    row = store.get_suite(old["id"])
    assert row["name"].startswith("Context graph — consolidating") and row["key"] == "kt1_consolidation"
    assert [r["id"] for r in store.list_runs(old["id"])] == [run_id]
    assert sum(1 for s in store.list_suites(500) if s["id"] == old["id"]) == 1


def test_a_new_title_renames_in_place_by_key():
    first, created = store.ensure_suite("kt2", "First title [kt2]")
    again, created_again = store.ensure_suite("kt2", "Second title [kt2]")
    assert created and not created_again and again["id"] == first["id"]
    assert store.get_suite(first["id"])["name"] == "Second title [kt2]"
    assert not [s for s in store.list_suites(500) if s["name"] == "First title [kt2]"]


def test_a_keyed_suite_is_never_adopted_by_another_key():
    a, _ = store.ensure_suite("kt3a", "Shared title [kt3]")
    b, created = store.ensure_suite("kt3b", "Shared title [kt3]")
    assert created and b["id"] != a["id"]
