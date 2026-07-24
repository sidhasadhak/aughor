"""Wave R3 — the two-tier schema catalog and the error-path autoload.

The error-path autoload is the part that changes outcomes rather than just cost: a binder
error ("no such column: x on table y") is unfixable if y's columns are not in front of the
model, and schema-linking structurally cannot supply them — it selects tables from the
QUESTION, before the query has failed.

Everything else here is a cost change, so the tests that matter most are the ones proving
it degrades to "send everything" whenever narrowing would be a guess. Dropping a table the
repair needed turns a recoverable error into an unanswered question.
"""
from __future__ import annotations

import pytest

from aughor.agent import schema_focus as SF


def _schema(*tables: str) -> str:
    blocks = []
    for t in tables:
        cols = "\n".join(f"  {t}_col{i} INTEGER" for i in range(1, 21))
        blocks.append(f"TABLE: {t}  (10,000 rows)\n{cols}\n")
    return "\n".join(blocks) + "\nJOIN HINTS:\n  orders.customer_id -> customers.id\n"


BIG = _schema(*[f"t{i}" for i in range(1, 41)], "orders", "customers", "shipments")
assert len(BIG) > SF.FOCUS_MIN_CHARS, "the fixture must be past the threshold to exercise focusing"


# ── parsing ───────────────────────────────────────────────────────────────────

def test_table_headers_are_found_in_order():
    names = [n for n, _ in SF.table_headers(BIG)]
    assert names[:3] == ["t1", "t2", "t3"] and "orders" in names


def test_the_manifest_lists_every_table_with_its_column_count():
    m = SF.manifest(BIG)
    assert m.count("TABLE:") == len(SF.table_headers(BIG))
    assert "[20 columns]" in m
    assert len(m) < len(BIG) / 3          # a manifest that is not much smaller is not one


def test_the_manifest_survives_a_schema_with_no_blank_lines():
    m = SF.manifest("TABLE: a  (1 rows)\n  x INTEGER\nTABLE: b  (2 rows)\n  y INTEGER")
    assert "TABLE: a" in m and "TABLE: b" in m and m.count("[1 columns]") == 2


# ── which tables get full DDL ─────────────────────────────────────────────────

def test_tables_referenced_by_the_sql_are_found():
    known = [n for n, _ in SF.table_headers(BIG)]
    found = SF.tables_in_sql("SELECT o.x FROM orders o JOIN customers c ON o.customer_id = c.id", known)
    assert found == {"orders", "customers"}


def test_unparseable_sql_still_finds_its_tables():
    """This runs on SQL that just FAILED, so a parse error is the common case, not the
    exception. The fallback over-matches on purpose — the result is intersected with the
    declared tables, so a stray word cannot invent one."""
    known = [n for n, _ in SF.table_headers(BIG)]
    found = SF.tables_in_sql("SELECT FROM orders WHERE ((( broken", known)
    assert "orders" in found


def test_a_word_that_is_not_a_declared_table_cannot_invent_one():
    known = [n for n, _ in SF.table_headers(BIG)]
    assert SF.tables_in_sql("SELECT * FROM nowhere_at_all", known) == set()


def test_the_error_message_pulls_in_the_table_it_names():
    """The error-path autoload. Schema-linking selects from the question and has no way to
    know which table a failure that has not happened yet will name."""
    known = [n for n, _ in SF.table_headers(BIG)]
    named = SF.tables_named_in_error(
        'Binder Error: Table "shipments" does not have a column named "delivered_at"', known)
    assert named == {"shipments"}


def test_an_error_naming_no_declared_table_pulls_in_nothing():
    known = [n for n, _ in SF.table_headers(BIG)]
    assert SF.tables_named_in_error("syntax error at or near ')'", known) == set()
    assert SF.tables_named_in_error("", known) == set()


def test_the_error_table_is_included_even_when_the_sql_never_mentioned_it():
    """The whole point: the fix needs a table the broken query did not use."""
    out, info = SF.focused_schema(
        BIG, sql="SELECT x FROM orders",
        error='Binder Error: column "delivered_at" not found; candidate table: shipments')
    assert info["focused"]
    assert set(info["tables"]) == {"orders", "shipments"}
    assert "shipments_col1" in out and "orders_col1" in out


# ── the safe-direction policy ─────────────────────────────────────────────────

def test_a_small_schema_is_returned_byte_identical():
    """Below the threshold, narrowing could only lose ground — a schema this small is not
    what is straining a context window."""
    small = _schema("orders", "customers")
    assert len(small) < SF.FOCUS_MIN_CHARS
    out, info = SF.focused_schema(small, sql="SELECT * FROM orders", error="")
    assert out == small and not info["focused"]


def test_an_unrecognised_schema_format_is_returned_untouched():
    blob = "some other schema rendering entirely\n" * 800
    out, info = SF.focused_schema(blob, sql="SELECT * FROM orders", error="boom")
    assert out == blob and not info["focused"]


def test_an_empty_focus_set_sends_everything():
    """'I could not tell what matters' must mean 'send everything', never 'send nothing'."""
    out, info = SF.focused_schema(BIG, sql="SELECT 1", error="syntax error")
    assert out == BIG and not info["focused"]


def test_narrowing_that_saves_nothing_keeps_the_original():
    """Focusing onto every table is a second copy of the manifest bolted onto the same DDL."""
    every = " ".join(f"FROM {n}" for n, _ in SF.table_headers(BIG))
    out, info = SF.focused_schema(BIG, sql=f"SELECT 1 {every}", error="")
    assert out == BIG and not info["focused"]


def test_the_focused_block_actually_saves_characters_and_reports_it():
    out, info = SF.focused_schema(BIG, sql="SELECT * FROM orders", error="")
    assert info["focused"] and info["after"] < info["before"]
    assert len(out) == info["after"]


def test_the_manifest_still_names_the_tables_that_were_narrowed_away():
    """The model must be able to decide the fix needs a table not detailed below —
    otherwise this trades a token saving for an unfixable query."""
    out, _ = SF.focused_schema(BIG, sql="SELECT * FROM orders", error="")
    assert "TABLE: t17" in out                       # named in the manifest…
    assert "t17_col1" not in out                     # …but its DDL was not sent


# ── the wiring ────────────────────────────────────────────────────────────────

def test_for_repair_is_identity_when_the_flag_is_off(monkeypatch):
    monkeypatch.delenv("AUGHOR_SCHEMA_TWO_TIER_CATALOG", raising=False)
    assert SF.for_repair(BIG, "SELECT * FROM orders", "boom") == BIG


def test_for_repair_focuses_when_the_flag_is_on(monkeypatch):
    monkeypatch.setenv("AUGHOR_SCHEMA_TWO_TIER_CATALOG", "1")
    out = SF.for_repair(BIG, "SELECT * FROM orders", "boom")
    assert out != BIG and "orders_col1" in out and "ALL TABLES" in out


def test_for_repair_never_raises(monkeypatch):
    """A repair prompt is on the recovery path. A helper that can raise there converts a
    recoverable SQL error into a failed run."""
    monkeypatch.setenv("AUGHOR_SCHEMA_TWO_TIER_CATALOG", "1")
    monkeypatch.setattr(SF, "focused_schema",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert SF.for_repair(BIG, "SELECT * FROM orders", "boom") == BIG


@pytest.mark.parametrize("mod", ["aughor.agent.nodes", "aughor.agent.explore"])
def test_both_repair_paths_share_one_definition(mod, monkeypatch):
    """The guard battery in this repo is ~5 re-assembled sites split by path. This does not
    add a sixth: both call the same function."""
    import importlib

    m = importlib.import_module(mod)
    monkeypatch.delenv("AUGHOR_SCHEMA_TWO_TIER_CATALOG", raising=False)
    assert m._focus_schema_for_repair({"schema_context": BIG}, "SELECT * FROM orders", "e") == BIG
    monkeypatch.setenv("AUGHOR_SCHEMA_TWO_TIER_CATALOG", "1")
    assert m._focus_schema_for_repair({"schema_context": BIG}, "SELECT * FROM orders", "e") != BIG
