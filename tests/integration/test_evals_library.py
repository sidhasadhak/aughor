"""Wave E2 — the evaluator library over the deterministic guard battery.

The library adds no detection logic: every evaluator delegates to a guard that
already exists and is already tested. So these tests check the things the
*adapter layer* can get wrong — wiring, argument shapes, skip-vs-fail semantics
and result normalisation — not whether the guards work.

The most valuable test here is ``test_no_evaluator_skips_on_a_signature_error``.
Registration is a table of function references and argument builders; a mismatch
raises a TypeError that the fail-open runner tolerates, and a tolerated
evaluator scores exactly like one that found nothing. That bug shipped once
during development (``integer_division_risk`` takes no ``dialect``) and was
invisible until a live run printed the tolerate line.
"""
from __future__ import annotations

import duckdb
import pytest

from aughor.evals import (
    EvalCase,
    EvalObservation,
    deterministic_evaluators,
    get_evaluator,
    registered_evaluators,
    run_all,
    run_evaluator,
)
from aughor.trust import BLOCK, Scope

_TABLE_COLS = {
    "orders": ["order_id", "customer_id", "amount"],
    "items": ["item_id", "order_id", "qty"],
}


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    """A real DuckDB with a genuine 1:N fan-out — the guards probe live data, so
    a mock connection would test the mock."""
    path = tmp_path_factory.mktemp("evals") / "t.duckdb"
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE orders(order_id INT, customer_id INT, amount DECIMAL(10,2))")
    con.execute("CREATE TABLE items(item_id INT, order_id INT, qty INT)")
    con.execute("INSERT INTO orders VALUES (1,10,100.0),(2,10,50.0),(3,11,25.0)")
    con.execute("INSERT INTO items VALUES (1,1,2),(2,1,3),(3,2,1),(4,3,5)")
    con.close()

    from aughor.db.connection import DuckDBConnection
    conn = DuckDBConnection(str(path), connection_id="evaltest")
    yield conn
    conn.close()


def _case(sql, db=None, **kw):
    return EvalCase(artifact=sql, table_cols=_TABLE_COLS,
                    scope=Scope(conn=db, dialect="duckdb"), **kw)


def _fired(scores):
    return {s.evaluator for s in scores if not s.passed and not s.skipped}


def _skipped(scores):
    return {s.evaluator: s.rationale for s in scores if s.skipped}


# ── the contract that keeps the table honest ──────────────────────────────────

def test_no_evaluator_skips_on_a_signature_error(db):
    """A mis-registered evaluator raises TypeError, gets tolerated, and then
    scores identically to one that found nothing. Every registration must
    actually be callable with what the case supplies."""
    case = _case("SELECT customer_id, SUM(amount) FROM orders GROUP BY customer_id",
                 db=db, question="revenue by customer")
    obs = EvalObservation(sql=case.artifact, columns=["customer_id", "sum"],
                          rows=[[10, 150.0]], row_count=1, narrative="A leads")

    signature_errors = {
        s.evaluator: s.rationale
        for s in run_all(case, obs)
        if s.skipped and ("TypeError" in s.rationale or "argument" in s.rationale)
    }
    assert not signature_errors, (
        f"evaluators silently skipped on a call-signature mismatch: {signature_errors}")


def test_every_registered_evaluator_satisfies_the_protocol():
    from aughor.evals.evaluator import REQUIREMENTS, Evaluator

    for name in registered_evaluators():
        ev = get_evaluator(name)
        assert isinstance(ev, Evaluator), f"{name} does not satisfy the protocol"
        assert ev.name == name
        assert set(ev.requires) <= set(REQUIREMENTS), \
            f"{name} requires something the runner cannot supply: {ev.requires}"


def test_the_builtin_set_is_all_deterministic():
    """Our differentiator is that these are guards, not judges. A judge-backed
    evaluator arriving in the builtin set silently would change what a passing
    suite means."""
    assert deterministic_evaluators() == registered_evaluators()


# ── wiring: the guards actually fire through the adapters ─────────────────────

def test_fanout_is_caught_on_a_real_join(db):
    """The dominant wrong-number class — SUM over a 1:N join double-counts."""
    sql = ("SELECT o.customer_id, SUM(o.amount) FROM orders o "
           "JOIN items i ON o.order_id = i.order_id GROUP BY o.customer_id")
    scores = run_all(_case(sql, db=db), EvalObservation(sql=sql))
    assert "guard.grain_fanout" in _fired(scores)

    score = run_evaluator("guard.grain_fanout", _case(sql, db=db), EvalObservation(sql=sql))
    assert score.checks and "over-count" in score.checks[0].reason.lower()
    assert score.detail["finding_count"] >= 1


def test_a_clean_aggregate_is_not_flagged_by_the_fanout_family(db):
    """Guards are positive-only and high-precision: a correct query must come
    back clean, or the battery is worse than useless."""
    sql = "SELECT customer_id, SUM(amount) FROM orders GROUP BY customer_id"
    fired = _fired(run_all(_case(sql, db=db), EvalObservation(sql=sql)))
    assert not {f for f in fired if "chasm" in f or "fanout" in f}, fired


def test_mutating_sql_is_a_blocker(db):
    score = run_evaluator("guard.readonly", _case("DELETE FROM orders", db=db),
                          EvalObservation())
    assert score.passed is False
    assert score.checks[0].severity == BLOCK
    assert score.blockers


def test_disallowed_function_is_a_blocker(db):
    sql = "SELECT pg_read_file('/etc/passwd')"
    score = run_evaluator("guard.disallowed_functions", _case(sql, db=db),
                          EvalObservation(sql=sql))
    assert score.passed is False
    assert score.checks[0].severity == BLOCK
    assert "PG_READ_FILE" in score.checks[0].detail["value"]


def test_denylist_is_dialect_sensitive(db):
    """Documenting existing guard behaviour, not asserting it is right:
    ``version()`` is on the denylist and is caught with no dialect, but under
    duckdb sqlglot resolves it to a known builtin and it slips through. Changing
    that is a detection-logic decision, which this PR deliberately does not make
    — but it should not be discovered by surprise later either."""
    from aughor.sql.readonly import disallowed_functions

    assert disallowed_functions("SELECT version()") == {"VERSION"}
    assert disallowed_functions("SELECT version()", "duckdb") == set()


# ── skip semantics ────────────────────────────────────────────────────────────

def test_probe_guards_skip_without_a_connection_rather_than_fail():
    """"Not applicable" must never be recorded as "broken" — that is how a suite
    starts overstating its own coverage."""
    sql = "SELECT * FROM orders o JOIN items i ON o.order_id = i.order_id"
    scores = run_all(_case(sql), EvalObservation(sql=sql))      # no conn

    skipped = _skipped(scores)
    assert "guard.grain_fanout" in skipped
    assert "conn" in skipped["guard.grain_fanout"]
    # A skip is not a failure.
    assert all(s.passed for s in scores if s.skipped)


def test_pure_guards_still_run_without_a_connection():
    sql = "DELETE FROM orders"
    scores = run_all(_case(sql), EvalObservation(sql=sql))
    assert "guard.readonly" in _fired(scores)


def test_composite_key_gets_set_valued_columns(db):
    """fanout wants lists, composite_key wants sets — one trap, coerced in the
    adapter so a caller never has to know which guard it is feeding."""
    sql = ("SELECT SUM(o.amount) FROM orders o JOIN items i ON o.order_id = i.order_id")
    score = run_evaluator("guard.partial_composite_key", _case(sql, db=db),
                          EvalObservation(sql=sql))
    assert not score.skipped, score.rationale     # must not TypeError on set-vs-list


def test_unregistered_evaluator_returns_none():
    assert run_evaluator("guard.nope", _case("SELECT 1"), EvalObservation()) is None


# ── result normalisation ──────────────────────────────────────────────────────

def test_score_serialises_for_a_receipt(db):
    sql = "DELETE FROM orders"
    d = run_evaluator("guard.readonly", _case(sql, db=db), EvalObservation(sql=sql)).to_dict()
    assert d["evaluator"] == "guard.readonly"
    assert d["passed"] is False
    assert d["checks"][0]["severity"] == BLOCK
    import json
    json.dumps(d)      # must survive the trip to a receipt / API response


def test_findings_with_set_fields_stay_json_safe(db):
    """composite_key findings carry sets, which json.dumps rejects outright."""
    import json

    from aughor.evals.adapters import _detail_of
    from aughor.sql.composite_key import KeyFinding

    detail = _detail_of(KeyFinding(left_table="a", right_table="b",
                                   used={"x"}, missing={"y", "z"}))
    json.dumps(detail)
    assert detail["missing"] == ["y", "z"]


def test_a_raising_evaluator_is_skipped_not_failed(db):
    """The guards' own contract is fail-open; a suite that turned a guard's
    internal error into a red test would punish the case, not the bug."""
    from aughor.evals.adapters import HintEvaluator, sql_only
    from aughor.evals.registry import register_evaluator

    def _boom(sql):
        raise RuntimeError("guard exploded")

    register_evaluator(HintEvaluator("guard.__boom", _boom, args=sql_only))
    try:
        score = run_evaluator("guard.__boom", _case("SELECT 1"), EvalObservation(sql="SELECT 1"))
        assert score.skipped is True
        assert score.passed is True
        assert "RuntimeError" in score.rationale
    finally:
        from aughor.evals.registry import _EVALUATORS
        _EVALUATORS.pop("guard.__boom", None)


def test_covers_everything_query_validate_finds(db):
    """E2's decision gate. ``/query/validate`` hand-projects six guard families
    into six differently-shaped lists; the evaluator set must find everything it
    finds before that endpoint can ever be refactored onto this library.

    Coverage is asserted as a superset, not equality: the endpoint's
    ``Verifier.scan`` stops at the first hit per query, while the library runs
    every detector, so the library legitimately reports more.
    """
    from aughor.agent.verifier import Verifier
    from aughor.sql.grain_guard import detect_fanout
    from aughor.sql.join_guard import check_filter_value_domains, check_join_value_domains
    from aughor.sql.trust_checks import run_trust_checks

    from aughor.evals.probe import probe_fn_for

    corpus = [
        "SELECT customer_id, SUM(amount) FROM orders GROUP BY customer_id",
        "SELECT o.customer_id, SUM(o.amount) FROM orders o "
        "JOIN items i ON o.order_id=i.order_id GROUP BY o.customer_id",
        "SELECT COUNT(*) FROM orders o JOIN items i ON o.order_id=i.order_id",
        "SELECT AVG(o.amount) FROM orders o JOIN items i ON o.order_id=i.order_id",
    ]
    family = {
        "fanout": lambda n: any(k in n for k in ("chasm", "fanout", "id_arithmetic")),
        "join_domain": lambda n: "join_value_domain" in n,
        "filter_domain": lambda n: "filter_value_domain" in n,
        "grain": lambda n: "grain_fanout" in n,
        "e1": lambda n: "e1_semantics" in n,
    }

    for sql in corpus:
        endpoint = set()
        if Verifier.scan([sql], _TABLE_COLS, "duckdb"):
            endpoint.add("fanout")
        if check_join_value_domains(db, sql):
            endpoint.add("join_domain")
        if check_filter_value_domains(db, sql):
            endpoint.add("filter_domain")
        if detect_fanout(sql, probe_fn_for(db), dialect="duckdb"):
            endpoint.add("grain")
        if run_trust_checks(sql, dialect="duckdb"):
            endpoint.add("e1")

        fired = _fired(run_all(_case(sql, db=db), EvalObservation(sql=sql)))
        library = {fam for fam, pred in family.items() if any(pred(n) for n in fired)}

        assert endpoint <= library, (
            f"library misses {endpoint - library} that /query/validate finds\n  sql: {sql}")


def test_registry_clear_and_restore():
    from aughor.evals import register_builtins
    from aughor.evals.registry import clear

    before = registered_evaluators()
    clear()
    assert registered_evaluators() == []
    register_builtins()
    assert registered_evaluators() == before
