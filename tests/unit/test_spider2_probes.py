"""B1 — probe-and-repair back half: deterministic disagreement extraction (I2) + the four
evidence-typed acceptance gates (I7).

Offline and pure: no DB, no LLM. Every effect (execute, probe, repair) is a stub, so what's
pinned here is the taxonomy classification and the never-go-backwards gate contract — the
properties that make B1 monotonic-by-construction (the reason it's the one inference-time lever
worth endpoint-hours after two died under the measurement protocol).
"""
from __future__ import annotations

from evals.spider2_probes import (
    Dimension,
    ProbeResult,
    evidence_faithful,
    extract_disagreements,
    resolve,
    run_probes,
)


# ── I2 · disagreement extraction / taxonomy classification ────────────────────
def _facets(a, b):
    return [(d.kind, d.facet) for d in extract_disagreements([a, b])]


def test_value_divergence_is_ambivalue():
    fs = _facets("SELECT * FROM t WHERE city='NYC'", "SELECT * FROM t WHERE city='New York'")
    assert fs == [("AmbiValue", "literal")]


def test_operator_only_delta_is_boundary_not_value():
    # same literal, different comparison operator → AmbiIntent/window (boundary), never AmbiValue
    fs = _facets("SELECT COUNT(*) FROM t WHERE dt >= '2020-01-01'",
                 "SELECT COUNT(*) FROM t WHERE dt > '2020-01-01'")
    assert fs == [("AmbiIntent", "window")]
    fs = _facets("SELECT * FROM t WHERE age > 18", "SELECT * FROM t WHERE age >= 18")
    assert fs == [("AmbiIntent", "window")]


def test_group_by_delta_is_grain():
    fs = _facets("SELECT p, SUM(r) FROM b GROUP BY p",
                 "SELECT p, m, SUM(r) FROM b GROUP BY p, m")
    assert ("AmbiIntent", "grain") in fs


def test_aggregation_delta_is_ambiintent():
    assert _facets("SELECT AVG(x) FROM t", "SELECT SUM(x) FROM t") == [("AmbiIntent", "aggregation")]
    # COUNT vs COUNT(DISTINCT) is an aggregation ambiguity too
    assert ("AmbiIntent", "aggregation") in _facets(
        "SELECT COUNT(id) FROM t", "SELECT COUNT(DISTINCT id) FROM t")


def test_per_row_vs_per_group_is_grain_only_not_aggregation():
    # going per-row → per-group necessarily ADDS an aggregate; that transition is owned by the
    # grain facet, so no separate (unresolved) aggregation dimension is emitted — otherwise the
    # no-regress gate would block every legitimate grain repair.
    fs = _facets("SELECT region, amount FROM sales",
                 "SELECT region, SUM(amount) FROM sales GROUP BY region")
    assert ("AmbiIntent", "grain") in fs
    assert ("AmbiIntent", "aggregation") not in fs


def test_column_swap_is_ambischema_only_when_unexplained():
    # a pure projection swap with no other facet → AmbiSchema
    assert _facets("SELECT primary_factor FROM c", "SELECT violation_category FROM c") == \
        [("AmbiSchema", "column")]
    # but when a value delta already explains the divergence, don't ALSO emit a schema swap
    fs = _facets("SELECT * FROM t WHERE city='NYC'", "SELECT * FROM t WHERE city='New York'")
    assert not any(k == "AmbiSchema" for k, _ in fs)


def test_identical_and_single_candidate_yield_no_dimension():
    assert extract_disagreements(["SELECT a FROM t", "SELECT a FROM t"]) == []
    assert extract_disagreements(["SELECT a FROM t"]) == []
    # unparseable candidates are skipped (fail-safe), leaving <2 readings → no dimension
    assert extract_disagreements(["SELECT a FROM t", ")))not sql((("]) == []


# ── I7 · faithfulness / changed-clause accounting ─────────────────────────────
def test_value_fix_is_faithful_to_a_literal_dimension():
    dims = extract_disagreements(["SELECT * FROM t WHERE city='NYC'",
                                  "SELECT * FROM t WHERE city='New York'"])
    ok, changed = evidence_faithful("SELECT * FROM t WHERE city='NYC'",
                                    "SELECT * FROM t WHERE city='New York'", dims)
    assert ok and changed == {"where_literals"}


def test_edit_outside_the_evidence_is_unfaithful():
    # evidence covers only a literal; the "repair" ALSO re-groups → outside the allowance
    literal_dim = [Dimension("AmbiValue", "literal", "city", ("nyc", "new york"), ())]
    ok, changed = evidence_faithful(
        "SELECT c, SUM(x) FROM t WHERE city='NYC' GROUP BY c",
        "SELECT c, d, SUM(x) FROM t WHERE city='New York' GROUP BY c, d", literal_dim)
    assert not ok
    assert "group_by" in changed


def test_noop_is_not_faithful():
    dims = [Dimension("AmbiValue", "literal", "city", ("a", "b"), ())]
    ok, changed = evidence_faithful("SELECT * FROM t WHERE city='NYC'",
                                    "SELECT * FROM t WHERE city='NYC'", dims)
    assert not ok and not changed


def test_unparseable_candidate_fails_the_gate_closed():
    dims = [Dimension("AmbiValue", "literal", "city", ("a", "b"), ())]
    ok, changed = evidence_faithful("SELECT * FROM t WHERE city='NYC'", ")) not sql", dims)
    assert not ok and "__unparsed__" in changed


# ── I3 · probe battery ────────────────────────────────────────────────────────
def test_deterministic_probe_preferred_over_llm_and_llm_capped():
    dims = [Dimension("AmbiIntent", "grain", "g", ("a", "b"), ()),
            Dimension("AmbiIntent", "window", "w", ("a", "b"), ()),
            Dimension("AmbiIntent", "aggregation", "agg", ("a", "b"), ())]
    llm_calls = {"n": 0}

    def det(dim):  # only the grain probe resolves deterministically
        if dim.facet == "grain":
            return ProbeResult(dim, True, "grain resolved", source="det:grain")
        return None

    def llm(dim):
        llm_calls["n"] += 1
        return ProbeResult(dim, True, "llm resolved", source="llm")

    out = run_probes(dims, det_probes={"grain": det}, llm_probe=llm, max_llm=1)
    # grain resolved deterministically (no llm); window used the 1 llm budget; aggregation over budget
    assert out[0].source == "det:grain"
    assert out[1].source == "llm"
    assert out[2].resolved is False
    assert llm_calls["n"] == 1


# ── I7 · resolve() end-to-end gate contract ───────────────────────────────────
_SEED = "SELECT * FROM t WHERE city='NYC'"
_FIX = "SELECT * FROM t WHERE city='New York'"
_DIMS = extract_disagreements([_SEED, _FIX])


def _exec_ok(sql):
    return True, [("r",)], ""


def test_no_resolved_dimension_keeps_seed():
    probes = [ProbeResult(_DIMS[0], resolved=False, finding="x")]
    out = resolve("q", _SEED, _DIMS, probes, execute_fn=_exec_ok,
                  repair_fn=lambda s, i: _FIX)
    assert not out.accepted and out.sql == _SEED and out.source == "seed"


def test_prefers_existing_alternative_for_free_before_repairing():
    probes = [ProbeResult(_DIMS[0], resolved=True, finding="live probe: 'New York' matches rows",
                          preferred_sql=_FIX, source="det:value")]
    repair_calls = {"n": 0}

    def repair(s, i):
        repair_calls["n"] += 1
        return _FIX

    out = resolve("q", _SEED, _DIMS, probes, execute_fn=_exec_ok, repair_fn=repair)
    assert out.accepted and out.sql == _FIX and out.source.startswith("alternate")
    assert repair_calls["n"] == 0  # the free candidate won; no LLM repair spent


def test_repair_adopted_when_all_gates_pass():
    probes = [ProbeResult(_DIMS[0], resolved=True, finding="fix the literal", source="det:value")]
    out = resolve("q", _SEED, _DIMS, probes, execute_fn=_exec_ok, repair_fn=lambda s, i: _FIX)
    assert out.accepted and out.sql == _FIX and out.source == "repair"
    assert out.gates.get("executes") and out.gates.get("faithful") and out.gates.get("cleared")


def test_repair_rejected_when_it_touches_clauses_outside_evidence():
    # evidence is a value literal; the repair also re-grains → unfaithful → keep seed
    probes = [ProbeResult(_DIMS[0], resolved=True, finding="fix literal", source="det:value")]
    bad = "SELECT c, SUM(x) FROM t WHERE city='New York' GROUP BY c"
    out = resolve("q", _SEED, _DIMS, probes, execute_fn=_exec_ok, repair_fn=lambda s, i: bad)
    assert not out.accepted and out.sql == _SEED
    assert out.gates.get("faithful") is False


def test_repair_rejected_when_it_does_not_execute():
    probes = [ProbeResult(_DIMS[0], resolved=True, finding="fix", source="det:value")]

    def exec_fail(sql):
        return False, None, "syntax error"

    out = resolve("q", _SEED, _DIMS, probes, execute_fn=exec_fail, repair_fn=lambda s, i: _FIX)
    assert not out.accepted and out.sql == _SEED and out.gates.get("executes") is False


def test_repair_rejected_when_it_fails_the_reprobe():
    probes = [ProbeResult(_DIMS[0], resolved=True, finding="fix", source="det:value")]
    # the re-probe says the candidate still didn't clear the dimension → keep seed
    out = resolve("q", _SEED, _DIMS, probes, execute_fn=_exec_ok, repair_fn=lambda s, i: _FIX,
                  reprobe={"value": lambda sql, dim: False})
    assert not out.accepted and out.sql == _SEED and out.gates.get("cleared") is False


def test_repair_rejected_when_it_regresses_a_same_class_sibling():
    # two AmbiValue literals sharing the where_literals class: city (resolved) + status
    # (unresolved). A repair that fixes city AND clobbers status is faithful at the CLASS level
    # but regresses the untouched status dimension → the finer no-regress gate keeps the seed.
    seed = "SELECT * FROM t WHERE city='NYC' AND status='open'"
    city_dim = Dimension("AmbiValue", "literal", "city", ("new york", "nyc"), ())
    status_dim = Dimension("AmbiValue", "literal", "status", ("closed", "open"), ())
    dims = [city_dim, status_dim]
    probes = [ProbeResult(city_dim, resolved=True, finding="fix city", source="det:value"),
              ProbeResult(status_dim, resolved=False, finding="status unresolved")]
    clobber = "SELECT * FROM t WHERE city='New York' AND status='closed'"
    # sanity: the edit IS class-level faithful (only where_literals changed)…
    ok, changed = evidence_faithful(seed, clobber, [city_dim])
    assert ok and changed == {"where_literals"}
    # …but the finer no-regress gate rejects it because the untouched status literal moved.
    out = resolve("q", seed, dims, probes, execute_fn=_exec_ok, repair_fn=lambda s, i: clobber)
    assert not out.accepted and out.sql == seed
    assert out.gates.get("no_regress") is False
    # and a repair that fixes ONLY city (leaves status alone) is adopted.
    clean = "SELECT * FROM t WHERE city='New York' AND status='open'"
    out2 = resolve("q", seed, dims, probes, execute_fn=_exec_ok, repair_fn=lambda s, i: clean)
    assert out2.accepted and out2.sql == clean
