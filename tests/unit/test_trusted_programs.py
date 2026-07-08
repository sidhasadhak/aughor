"""Unit tests for the trusted-program store (Rec 4, Stage C) — save/retrieve/idempotence/burn-down.

Hermetic: conftest points AUGHOR_TRUSTED_PROGRAMS_DB at a throwaway temp file.
"""
from __future__ import annotations

from aughor.semantic.trusted_programs import (
    TrustedProgram,
    list_trusted_programs,
    record_program_hit,
    retrieve_trusted_program,
    save_trusted_program,
)

_PROG = {"steps": [{"id": "s0", "kind": "data", "writes": "rows", "sql": "SELECT 1 AS n"}],
         "rationale": "count"}


def test_save_then_retrieve_by_token_overlap():
    save_trusted_program(TrustedProgram(
        connection_id="c1", org_id="o1", question="which tickets are urgent this week", program=_PROG))
    hit = retrieve_trusted_program("show the urgent tickets this week", "c1", org_id="o1")
    assert hit is not None
    tp, score = hit
    assert tp.connection_id == "c1" and tp.program == _PROG and score > 0


def test_unrelated_question_does_not_match():
    save_trusted_program(TrustedProgram(
        connection_id="c2", org_id="o1", question="total revenue by region last quarter", program=_PROG))
    assert retrieve_trusted_program("the meaning of life", "c2", org_id="o1") is None


def test_natural_key_idempotent_updates_one_row():
    q = "average order value by month"
    save_trusted_program(TrustedProgram(connection_id="c3", org_id="o1", question=q, program=_PROG))
    first = list_trusted_programs("c3", org_id="o1")
    assert len(first) == 1
    record_program_hit(first[0].id)                    # bump use_count + set last_used_at
    # a re-save of the same question updates the SAME row and preserves verified_at + use_count
    save_trusted_program(TrustedProgram(connection_id="c3", org_id="o1", question=q,
                                        program={"steps": [], "rationale": "changed"}))
    rows = list_trusted_programs("c3", org_id="o1")
    assert len(rows) == 1
    assert rows[0].verified_at == first[0].verified_at
    assert rows[0].use_count == 1                       # preserved across the re-save


def test_scoped_by_connection_and_org():
    save_trusted_program(TrustedProgram(connection_id="c4", org_id="oA", question="orders by day", program=_PROG))
    assert retrieve_trusted_program("orders by day", "c4", org_id="oB") is None   # different org
    assert retrieve_trusted_program("orders by day", "c9", org_id="oA") is None   # different connection
    assert retrieve_trusted_program("orders by day", "c4", org_id="oA") is not None
