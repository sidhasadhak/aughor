"""Arc NV-1 — a text column's date notation is a fact about every value, or it is withheld and said.

`aughor.tools.date_format` transfers NVIDIA's method (study §5.3): a winner parses EVERY distinct value with the year
in [1900, 2099], candidates in specificity order, and DD/MM against MM/DD is refused rather than guessed. These tests
pin the three verdicts — a notation, an ambiguity, nothing — and the builder's copy of them onto the property, which
the ENTITY MODEL block prints. The profiler probe itself is exercised on an in-memory DuckDB below, so the fact is
shown to travel from a real column to the rendered block — a fixture that hand-sets the slot cannot show that.
"""
from __future__ import annotations

import duckdb
import pytest

from aughor.tools.date_format import (
    CANDIDATES, MAX_DISTINCT, DateFormat, infer_date_format, looks_like_date_column,
)


# ── the verdicts ──────────────────────────────────────────────────────────────────────────

def test_compact_iso_is_found_and_said():
    v = infer_date_format(["20260131", "20251201", "20240229"])
    assert v is not None and v.found and not v.ambiguous
    assert v.notation == "YYYYMMDD" and v.strptime == "%Y%m%d" and v.n_values == 3
    assert "every one of 3 distinct values parses" in v.note


def test_iso_dashed_beats_the_less_specific_forms():
    v = infer_date_format(["2026-01-31", "2026-02-01"])
    assert v is not None and v.notation == "YYYY-MM-DD"


def test_a_timestamp_is_told_apart_from_its_date():
    v = infer_date_format(["2026-01-31 13:05:00", "2026-02-01 00:00:00"])
    assert v is not None and v.notation == "YYYY-MM-DD HH:MM:SS"


def test_unpadded_us_dates_parse_when_a_day_above_twelve_decides():
    # Superstore-style: '11/8/2016' is month-first only because '12/25/2016' cannot be day-first.
    v = infer_date_format(["11/8/2016", "12/25/2016", "1/3/2017"])
    assert v is not None and v.notation == "MM/DD/YYYY" and not v.ambiguous


def test_day_first_when_a_day_above_twelve_decides():
    v = infer_date_format(["31/01/2026", "05/02/2026"])
    assert v is not None and v.notation == "DD/MM/YYYY"


def test_dd_mm_against_mm_dd_is_refused_and_said():
    """Every day ≤ 12: both notations parse every value, and the coin flip is refused by name."""
    v = infer_date_format(["01/02/2026", "03/04/2026", "05/06/2026"])
    assert v is not None and v.found and v.ambiguous
    assert v.notation == "" and v.strptime == ""
    assert "DD/MM/YYYY" in v.note and "MM/DD/YYYY" in v.note and "not stated" in v.note


def test_one_value_that_does_not_parse_withholds_the_notation():
    """A notation is a claim about the WHOLE column: one stray value and nothing is said."""
    assert infer_date_format(["20260131", "20251201", "not a date"]) is None


def test_a_year_outside_the_range_is_not_a_date():
    assert infer_date_format(["00010101", "00020202"]) is None


def test_free_text_and_numbers_are_not_dates():
    assert infer_date_format(["shipped", "delivered"]) is None
    assert infer_date_format(["12.50", "99.00"]) is None
    assert infer_date_format(["1", "2", "3"]) is None


def test_null_spellings_and_blanks_are_skipped_not_counted():
    v = infer_date_format([None, "", "NULL", "20260131", "20260201"])
    assert v is not None and v.notation == "YYYYMMDD" and v.n_values == 2


def test_values_past_the_cap_are_not_read_and_the_verdict_says_how_many_it_rests_on():
    """Superstore's `Order Date` holds 1,237 distinct values: the probe is bounded, not blind. A stray value past
    the cap is never seen — which is why the profiler's note adds the column's own distinct count beside it."""
    many = [f"{y}{m:02d}{d:02d}" for y in (2020, 2021, 2022, 2023, 2024, 2025, 2026) for m in range(1, 13) for d in range(1, 29)]
    assert len(many) > MAX_DISTINCT
    v = infer_date_format(many + ["not a date"])      # the stray value is past the cap: not read
    assert v is not None and v.notation == "YYYYMMDD" and v.n_values == MAX_DISTINCT
    assert infer_date_format(many[:50] + ["not a date"]) is None   # within the cap, one stray value withholds it


def test_candidates_are_specific_first_and_every_notation_is_named():
    pats = [p for p, _ in CANDIDATES]
    assert pats.index("%Y-%m-%d %H:%M:%S") < pats.index("%Y-%m-%d") < pats.index("%d/%m/%Y")
    assert all(n for _, n in CANDIDATES)
    assert len(set(pats)) == len(pats)


def test_found_is_the_property_gate():
    assert not DateFormat().found
    assert DateFormat(notation="YYYYMMDD").found
    assert DateFormat(ambiguous=True).found


# ── which columns are worth the probe ─────────────────────────────────────────────────────

def test_typed_dates_and_numbers_never_qualify():
    assert not looks_like_date_column("order_date", "DATE")
    assert not looks_like_date_column("order_date", "TIMESTAMP")
    assert not looks_like_date_column("order_date", "INTEGER", ["20260131"])


def test_a_date_named_text_column_qualifies_by_name():
    assert looks_like_date_column("order_date", "VARCHAR")
    assert looks_like_date_column("created_at", "TEXT")


def test_an_unnamed_text_column_qualifies_only_by_its_values():
    assert not looks_like_date_column("notes", "VARCHAR", ["hello", "world"])
    assert looks_like_date_column("period", "VARCHAR", ["2026-01", "2026-02"])
    assert not looks_like_date_column("period", "VARCHAR", ["2026-01"])      # one value proves nothing


# ── from a real column to the property and the block ──────────────────────────────────────

@pytest.fixture
def warehouse(tmp_path):
    from aughor.db.connection import DuckDBConnection
    path = tmp_path / "wh.duckdb"
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE bookings (booking_id INTEGER, booked_on VARCHAR, flown_on VARCHAR, note VARCHAR, fare DOUBLE)")
    con.executemany("INSERT INTO bookings VALUES (?, ?, ?, ?, ?)", [
        (1, "20260131", "01/02/2026", "late", 120.0),
        (2, "20260201", "03/04/2026", "ok", 80.0),
        (3, "20260205", "05/06/2026", "ok", 95.5),
        (4, "20260210", None, "late", 70.0),
    ])
    con.close()
    conn = DuckDBConnection(str(path), connection_id="")
    yield conn
    conn.close()


def test_the_profiler_writes_the_notation_and_the_builder_prints_it(warehouse):
    from aughor.ontology.builder import extract_structural_ontology, render_ontology_annotations
    from aughor.tools.profiler import build_column_profiles, build_table_profile

    columns = [("booking_id", "INTEGER"), ("booked_on", "VARCHAR"), ("flown_on", "VARCHAR"), ("note", "VARCHAR"),
               ("fare", "DOUBLE")]
    tp = build_table_profile(warehouse, "bookings", columns, set())
    cps = build_column_profiles(warehouse, "bookings", columns, set(), tp.row_count)
    by = {cp.column: cp for cp in cps}
    assert by["booked_on"].date_format == "YYYYMMDD"
    assert "distinct values read" not in by["booked_on"].date_format_note    # a complete read says nothing about a cap
    assert by["flown_on"].date_format == "" and "ambiguous" in by["flown_on"].date_format_note
    assert by["note"].date_format == "" and by["note"].date_format_note == ""
    assert by["fare"].date_format == ""

    graph = extract_structural_ontology("c", "main", "fp", {"bookings": tp},
                                        {f"bookings.{cp.column}": cp for cp in cps}, {"joins": []}, {})
    props = graph.entities["Booking"].properties
    assert props["booked_on"].format == "YYYYMMDD"
    assert props["flown_on"].format == "" and props["flown_on"].format_note.startswith("ambiguous")

    block = render_ontology_annotations(graph)
    assert "text dates (cast before comparing): booked_on written YYYYMMDD; flown_on ambiguous" in block
    assert "DD/MM/YYYY" in block and "MM/DD/YYYY" in block     # the withheld notation is SAID, both readings named


def test_a_profile_cached_before_nv1_reads_as_no_notation():
    from aughor.tools.profiler import ColumnProfile
    cp = ColumnProfile.from_dict({"table": "t", "column": "c", "dtype": "VARCHAR", "semantic_type": "dimension"})
    assert cp.date_format == "" and cp.date_format_note == ""
    assert "date_format" in cp.to_dict()
