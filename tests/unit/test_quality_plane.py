"""Wave Q — the quality plane: rules, one results store, candidates, caveats.

Three carrying tests, one per structural rule the scoping doc set before any code:

- :func:`test_editing_a_note_does_not_change_the_fingerprint` — if it did, every stored
  result would detach from its rule and nobody would ever annotate a rule.
- :class:`TestOneResultsStore` — J12. Quality results already lived in five
  mutually-unaware places; a sixth was one convenient table away.
- :func:`test_the_same_concern_renders_once` — three producers emit caveat-shaped strings,
  and a caveat seen twice in different words is one people stop reading.
"""
from __future__ import annotations

import pytest

from aughor.quality.caveats import (
    assemble,
    blocking_reasons,
    candidates_from_profile,
    caveat_for,
    caveats_for_answer,
)
from aughor.quality.results import Result, latest_for_tables, new_run_id, record
from aughor.quality.rules import (
    CHECK_KINDS,
    CRITICALITIES,
    Rule,
    RuleError,
    RuleSet,
    compile_rule,
    metadata_fields,
    rule_from_dict,
)


@pytest.fixture(autouse=True)
def quality_db(tmp_path, monkeypatch):
    """Never the real store."""
    import aughor.quality.results as R

    monkeypatch.setattr(R, "_DB_PATH", tmp_path / "quality.db")


def _rule(**kw) -> Rule:
    base = {"name": "orders_id_not_null", "table": "orders", "kind": "not_null",
            "column": "order_id"}
    return Rule(**{**base, **kw})


# ── Q1: the fingerprint rule ────────────────────────────────────────────────────────

def test_editing_a_note_does_not_change_the_fingerprint():
    """Stored results are keyed by the fingerprint of the rule that produced them. If a
    note changed it, history would detach and nobody would ever annotate a rule."""
    a = _rule(note="checked with finance")
    b = _rule(note="completely different prose", owner="data-eng")
    assert a.fingerprint == b.fingerprint


def test_criticality_is_excluded_too():
    """The less obvious call: warn->error changes what a failure MEANS, not what was
    measured, and re-fingerprinting would detach the history that makes the escalation
    reviewable."""
    assert _rule(criticality="warn").fingerprint == _rule(criticality="error").fingerprint
    assert "criticality" in metadata_fields()


def test_changing_what_the_rule_computes_does_change_it():
    assert _rule(column="order_id").fingerprint != _rule(column="customer_id").fingerprint
    assert _rule(filter="status <> 'x'").fingerprint != _rule().fingerprint
    assert _rule(kind="unique").fingerprint != _rule().fingerprint


def test_a_ruleset_fingerprint_is_order_independent():
    """Reordering a YAML file is not a change to what runs."""
    a = RuleSet("c1", [_rule(name="a"), _rule(name="b", column="c2")])
    b = RuleSet("c1", [_rule(name="b", column="c2"), _rule(name="a")])
    assert a.fingerprint == b.fingerprint


# ── Q1: validation refuses rather than skips ────────────────────────────────────────

@pytest.mark.parametrize("kw,match", [
    ({"name": ""}, "needs a name"),
    ({"table": ""}, "needs a table"),
    ({"kind": "vibes"}, "unknown kind"),
    ({"criticality": "maybe"}, "unknown criticality"),
    ({"kind": "not_null", "column": ""}, "needs a column"),
    ({"kind": "in_list", "args": {}}, "needs args.values"),
    ({"kind": "range", "args": {}}, "needs args.min or args.max"),
    ({"kind": "freshness", "args": {}}, "needs args.max_age_hours"),
    ({"kind": "foreign_key", "args": {}}, "needs args.references"),
])
def test_a_malformed_rule_raises_rather_than_being_skipped(kw, match):
    """A skipped check reports healthy because it never ran — the worst possible quality
    signal."""
    with pytest.raises(RuleError, match=match):
        _rule(**kw).validate()


def test_duplicate_rule_names_are_refused():
    with pytest.raises(RuleError, match="duplicate rule name"):
        RuleSet("c1", [_rule(), _rule()]).validate()


def test_criticality_is_data_not_code():
    """The same check warns on one table and errors on another."""
    warn = _rule(table="staging_orders", criticality="warn")
    err = _rule(table="orders", criticality="error")
    warn.validate()
    err.validate()
    assert set(CRITICALITIES) == {"warn", "error"}


def test_for_each_column_expands():
    r = _rule(column="", for_each_column=("a", "b"))
    expanded = r.expand()
    assert [x.column for x in expanded] == ["a", "b"]
    assert all(x.name.startswith("orders_id_not_null:") for x in expanded)


def test_an_unexpanded_rule_refuses_to_compile():
    with pytest.raises(RuleError, match="must be expanded"):
        compile_rule(_rule(column="", for_each_column=("a",)))


# ── Q1: compilation ─────────────────────────────────────────────────────────────────

def test_not_null_counts_violations():
    sql = compile_rule(_rule())
    assert "COUNT(*)" in sql and "order_id IS NULL" in sql


def test_a_check_counts_and_never_selects_rows():
    """Offending rows are warehouse data and a result store has no clearance model."""
    for kind, kw in [("not_null", {}), ("unique", {"args": {"columns": ["order_id"]}}),
                     ("in_list", {"args": {"values": ["a", "b"]}}),
                     ("range", {"args": {"min": 0}})]:
        sql = compile_rule(_rule(kind=kind, **kw))
        assert "COUNT(" in sql.upper()


def test_in_list_values_are_quoted():
    sql = compile_rule(_rule(kind="in_list", args={"values": ["a'b", "c"]}))
    assert "''" in sql          # the embedded quote is escaped


def test_a_filter_is_applied():
    sql = compile_rule(_rule(filter="status <> 'test'"))
    assert "status" in sql and "IS NULL" in sql


def test_foreign_key_compiles_to_an_anti_join():
    sql = compile_rule(_rule(kind="foreign_key", column="customer_id",
                             args={"references": "customers",
                                   "references_column": "id"}))
    assert "LEFT JOIN" in sql.upper() and "IS NULL" in sql.upper()


def test_every_declared_kind_compiles():
    """A kind in the closed set with no compiler would be a check that never runs."""
    args = {"in_list": {"values": ["x"]}, "range": {"min": 0},
            "freshness": {"max_age_hours": 24},
            "foreign_key": {"references": "t", "references_column": "id"},
            "unique": {"columns": ["order_id"]}}
    for kind in CHECK_KINDS:
        assert compile_rule(_rule(kind=kind, args=args.get(kind, {})))


def test_a_transpile_failure_falls_back_rather_than_refusing_to_check():
    """Refusing to check a table because a transpiler had an opinion turns a cosmetic
    problem into a coverage gap."""
    sql = compile_rule(_rule(), dialect="not-a-real-dialect")
    assert "COUNT(*)" in sql


# ── Q3: J12, one results store ──────────────────────────────────────────────────────

class TestOneResultsStore:
    def test_a_check_and_a_monitor_land_in_the_same_table(self):
        """J12. A check result looks exactly like a monitor alert, so the sixth surface
        was one convenient table away."""
        from aughor.quality.results import record_monitor_alert

        run = new_run_id()
        record(Result(connection_id="c1", table_name="orders", producer="check",
                      rule_name="not_null", passed=False, violations=3, run_id=run))
        record_monitor_alert("c1", "orders", monitor_name="revenue_drop",
                             severity="critical", message="down 40%", run_id=run)

        rows = latest_for_tables("c1", ["orders"])
        assert {r.producer for r in rows} == {"check", "monitor"}

    def test_there_is_exactly_one_write_path(self):
        """Every producer comes through `record`; a second writer is a second store with
        extra steps."""
        import aughor.quality.results as R

        writers = [n for n in dir(R)
                   if n.startswith(("record", "save", "insert", "write"))]
        assert sorted(writers) == ["record", "record_monitor_alert"]

    def test_an_unknown_producer_is_refused(self):
        with pytest.raises(ValueError, match="unknown producer"):
            record(Result(connection_id="c1", table_name="t", producer="mystery"))

    def test_latest_is_per_rule_not_per_table(self):
        """A table with a passing freshness check and a failing not-null check has BOTH
        facts; collapsing to one row hides whichever ran second."""
        record(Result(connection_id="c1", table_name="orders", rule_name="fresh",
                      passed=True, checked_at="2026-07-28T10:00:00+00:00"))
        record(Result(connection_id="c1", table_name="orders", rule_name="not_null",
                      passed=False, checked_at="2026-07-28T11:00:00+00:00"))
        rows = latest_for_tables("c1", ["orders"])
        assert {r.rule_name for r in rows} == {"fresh", "not_null"}

    def test_the_run_id_ties_a_run_together(self):
        from aughor.quality.results import results_for_run

        run = new_run_id()
        record(Result(connection_id="c1", table_name="a", run_id=run))
        record(Result(connection_id="c1", table_name="b", run_id=run))
        record(Result(connection_id="c1", table_name="c", run_id="other"))
        assert len(results_for_run(run)) == 2

    def test_table_names_are_normalised(self):
        record(Result(connection_id="c1", table_name="shop.Orders"))
        assert latest_for_tables("c1", ["orders"])


def test_a_verdict_ages_in_Vs_vocabulary():
    """A verdict computed against yesterday's data is not authoritative today — the
    mistake N3 found when a `fresh` badge sat over an empty graph."""
    fresh = Result(connection_id="c", table_name="t",
                   checked_at="2026-07-28T12:00:00+00:00")
    assert fresh.staleness(now="2026-07-28T13:00:00+00:00") == "fresh"
    assert fresh.staleness(now="2026-07-30T13:00:00+00:00") == "stale"
    assert Result(connection_id="c", table_name="t").staleness() == "unknown"


def test_only_error_criticality_blocks():
    assert Result(connection_id="c", table_name="t", passed=False,
                  criticality="error").blocking
    assert not Result(connection_id="c", table_name="t", passed=False,
                      criticality="warn").blocking
    assert not Result(connection_id="c", table_name="t", passed=True,
                      criticality="error").blocking


# ── Q4: one caveat path ─────────────────────────────────────────────────────────────

def test_a_caveat_names_the_rule_and_the_run():
    """'Data quality issue detected' is the phrasing that trains people to ignore the
    banner."""
    r = Result(connection_id="c", table_name="orders", rule_name="freshness",
               passed=False, violations=2, run_id="run123",
               detail="failed freshness (expected daily)")
    text = caveat_for(r)
    assert "orders" in text and "freshness" in text and "run123" in text and "2" in text


def test_a_passing_result_has_no_caveat():
    assert caveat_for(Result(connection_id="c", table_name="t", passed=True)) == ""


def test_the_same_concern_renders_once():
    """Three producers emit caveat-shaped strings. A caveat seen twice in different words
    is one people stop reading."""
    dup = "`orders` failed freshness"
    out = assemble(declaration_caveats=[dup], trust_caveats=[dup, "  " + dup + " "])
    assert out == [dup]


def test_all_three_producers_render_through_one_path():
    r = Result(connection_id="c", table_name="orders", passed=False, detail="failed x")
    out = assemble(health=[r], declaration_caveats=["decl issue"],
                   trust_caveats=["trust issue"])
    assert len(out) == 3 and out[0].startswith("`orders`")


def test_health_caveats_come_first():
    """A failing table is the most actionable, and the dedup keeps the first rendering."""
    r = Result(connection_id="c", table_name="orders", passed=False, detail="failed x")
    out = assemble(health=[r], declaration_caveats=["something else"])
    assert "orders" in out[0]


def test_a_stale_verdict_says_so_in_its_caveat():
    """A caveat citing a week-old check is worse than none: it teaches the reader the
    health signal is noise."""
    r = Result(connection_id="c", table_name="orders", passed=False, detail="failed",
               checked_at="2020-01-01T00:00:00+00:00")
    assert "stale" in caveat_for(r)


def test_blocking_is_separate_from_annotating():
    """If a caller could block on the list it annotates with, every warning would
    eventually become a block by accident and the plane would get switched off."""
    results = [Result(connection_id="c", table_name="a", passed=False, criticality="warn"),
               Result(connection_id="c", table_name="b", passed=False, criticality="error")]
    assert len(assemble(health=results)) == 2
    assert len(blocking_reasons(results)) == 1


def test_an_unreadable_health_store_never_fails_an_answer(monkeypatch):
    """A quality plane that can break answers is a quality plane operators disable."""
    def _boom(*a, **k):
        raise RuntimeError("store down")

    monkeypatch.setattr("aughor.quality.results.latest_for_tables", _boom)
    out = caveats_for_answer("c1", ["orders"], declaration_caveats=["still rendered"])
    assert out == ["still rendered"]


def test_caveats_for_an_answer_only_cover_failing_tables():
    record(Result(connection_id="c1", table_name="orders", passed=False,
                  rule_name="not_null", detail="failed not_null"))
    record(Result(connection_id="c1", table_name="returns", passed=True,
                  rule_name="fresh"))
    out = caveats_for_answer("c1", ["orders", "returns"])
    assert len(out) == 1 and "orders" in out[0]


# ── Q2: candidates reuse O4's type ──────────────────────────────────────────────────

def test_profiler_candidates_reuse_the_O4_type():
    """Q's proposals are a different KIND, not a different type. A second candidate model
    is a second queue with extra steps (J10)."""
    from aughor.ontology.candidates import Candidate

    got = candidates_from_profile("c1", "orders", [
        {"name": "order_id", "null_ratio": 0.0, "distinct_count": 100_000}])
    assert got and all(isinstance(c, Candidate) for c in got)


def test_a_never_null_column_proposes_a_not_null_check():
    got = candidates_from_profile("c1", "orders", [{"name": "id", "null_ratio": 0.0}])
    assert any("not_null" in c.proposal for c in got)


def test_a_low_cardinality_column_proposes_a_value_dictionary():
    got = candidates_from_profile("c1", "products", [
        {"name": "category", "distinct_count": 8}])
    assert any("value dictionary" in c.proposal for c in got)


def test_a_mostly_empty_column_is_flagged_for_review():
    got = candidates_from_profile("c1", "t", [{"name": "c", "null_ratio": 0.9}])
    assert any("mostly empty" in c.proposal for c in got)


def test_thresholds_are_conservative():
    """A queue that proposes something about every column is one nobody opens twice."""
    got = candidates_from_profile("c1", "t", [
        {"name": "c", "null_ratio": 0.2, "distinct_count": 5000}])
    assert got == []


def test_candidates_carry_their_evidence():
    got = candidates_from_profile("c1", "t", [{"name": "c", "null_ratio": 0.0}])
    assert got[0].evidence and got[0].source_rank == "mined"


def test_rule_from_dict_round_trips():
    r = rule_from_dict({"name": "n", "table": "orders", "kind": "not_null",
                        "column": "id", "criticality": "error"})
    assert r.criticality == "error" and r.to_dict()["fingerprint"]
