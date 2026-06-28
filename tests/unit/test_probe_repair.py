"""Tests for execution-grounded probe-and-repair (aughor/sql/probe_repair.py, B6).

Contract: derive probes from the query, and adopt a repair ONLY when the repairer names a concrete
defect AND the fix executes and returns rows — otherwise keep the original verbatim (the FP-gate
that an unconstrained repair loop lacked).
"""
from __future__ import annotations

from aughor.sql.probe_repair import propose_probes, probe_and_repair, gather_evidence


def test_propose_probes_value_domain_and_grain():
    sql = ("SELECT d.region, SUM(f.amt) FROM fact f "
           "JOIN dim d ON f.region_id = d.region_id "
           "WHERE f.status = 'cancelled' GROUP BY d.region")
    probes = propose_probes(sql, dialect="sqlite")
    purposes = " ".join(p.purpose for p in probes)
    assert "values of fact.status" in purposes        # value-domain probe for the filter
    assert "grain of dim" in purposes                 # join-grain probe


def test_propose_probes_empty_on_plain_query():
    assert propose_probes("SELECT 1", dialect="sqlite") == []


def _exec_factory(rows_for):
    def ex(sql):
        for needle, rows in rows_for.items():
            if needle in sql:
                return True, rows, ""
        return True, [("x",)], ""
    return ex


def test_adopts_concrete_defect_repair_that_returns_rows():
    base = "SELECT SUM(f.amt) FROM fact f JOIN dim d ON f.region_id = d.region_id"
    ex = _exec_factory({"corrected": [(42,)]})
    def repair(sql, evidence):
        return "SELECT SUM(f.amt) /* corrected */ FROM fact f", "grain"
    r = probe_and_repair(base, ex, repair, dialect="sqlite")
    assert r.repaired and "corrected" in r.sql and r.defect_type == "grain"


def test_keeps_original_when_defect_none():
    base = "SELECT SUM(f.amt) FROM fact f JOIN dim d ON f.region_id = d.region_id"
    ex = _exec_factory({})
    def repair(sql, evidence):
        return None, "none"                            # repairer unsure → keep verbatim
    r = probe_and_repair(base, ex, repair, dialect="sqlite")
    assert not r.repaired and r.sql == base


def test_rejects_repair_that_does_not_execute():
    base = "SELECT SUM(f.amt) FROM fact f JOIN dim d ON f.region_id = d.region_id"
    def ex(sql):
        if "corrected" in sql:
            return False, None, "syntax error"         # bad fix
        return True, [(1,)], ""
    def repair(sql, evidence):
        return "SELECT corrected broken", "grain"
    r = probe_and_repair(base, ex, repair, dialect="sqlite")
    assert not r.repaired and r.sql == base             # never adopt a non-executing fix


def test_rejects_repair_that_returns_no_rows():
    base = "SELECT SUM(f.amt) FROM fact f JOIN dim d ON f.region_id = d.region_id"
    def ex(sql):
        if "corrected" in sql:
            return True, [], ""                         # executes but empty
        return True, [(1,)], ""
    def repair(sql, evidence):
        return "SELECT corrected", "grain"
    r = probe_and_repair(base, ex, repair, dialect="sqlite")
    assert not r.repaired and r.sql == base


def test_no_probes_is_noop():
    def ex(sql):
        return True, [(1,)], ""
    def repair(sql, evidence):
        raise AssertionError("repair must not be called when there are no probes")
    r = probe_and_repair("SELECT 1", ex, repair, dialect="sqlite")
    assert not r.repaired and r.receipt["probed"] == 0
