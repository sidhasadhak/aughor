"""R4 — the ablation harness's safety classification + that the canonical trap shapes
trip the deterministic guards it composes. Hermetic (no live connection, no LLM)."""
from __future__ import annotations

from aughor.sql.fanout import detect_fanout, measure_times_key_arithmetic
from evals.ablation_eval import _classify_plain, _classify_guarded


_OK = {"execution_success": 1.0, "result_set_match": 1.0, "row_count_match": 1.0}
_WRONG = {"execution_success": 1.0, "result_set_match": 0.0, "row_count_match": 0.0}
_EXEC_FAIL = {"execution_success": 0.0, "error": "Generated failed: boom"}


def test_classify_plain_trichotomy():
    assert _classify_plain(_OK, "SELECT 1") == "correct"
    assert _classify_plain(_WRONG, "SELECT 1") == "silent-wrong"   # executed but wrong = dangerous
    assert _classify_plain(_EXEC_FAIL, "SELECT 1") == "error"
    assert _classify_plain({}, None) == "error"                    # generation produced nothing


def test_classify_guarded_caught_beats_silent():
    # A wrong result that a guard FLAGGED is 'caught' (safe), not 'silent-wrong' (dangerous).
    assert _classify_guarded(_WRONG, "SELECT 1", ["fanout"]) == "caught"
    assert _classify_guarded(_WRONG, "SELECT 1", []) == "silent-wrong"
    # Correct wins regardless of whether a guard fired.
    assert _classify_guarded(_OK, "SELECT 1", ["fanout"]) == "correct"
    # A guard fired but the rewrite didn't bind → still flagged (caught), never silently shipped.
    assert _classify_guarded(_EXEC_FAIL, "SELECT 1", ["value_domain"]) == "caught"
    assert _classify_guarded(_EXEC_FAIL, "SELECT 1", []) == "error"
    assert _classify_guarded({}, None, []) == "error"


def test_canonical_traps_trip_the_guards():
    """The deterministic guards `apply_guards` composes fire on the exact plausible-wrong
    shapes a naive agent writes — the headline of the ablation."""
    tcols = {
        "orders": ["order_id", "customer_id", "order_value", "order_status"],
        "order_items": ["order_id", "order_item_id", "unit_price", "unit_cost"],
    }
    # Fan-out: an order-grain measure summed across a join to a line-grain child.
    ff = detect_fanout(
        "SELECT SUM(o.order_value) AS rev FROM orders o "
        "JOIN order_items oi ON o.order_id = oi.order_id",
        tcols, "duckdb")
    assert ff is not None, "fan-out across the orders→order_items chasm must be detected"

    # id-arithmetic: a measure multiplied by a key/id column fabricates a magnitude.
    hint = measure_times_key_arithmetic(
        "SELECT SUM(unit_price * order_item_id) AS rev FROM order_items", tcols, "duckdb")
    assert hint and "id" in hint.lower(), "SUM(measure × id) must be flagged"

    # A clean, additive aggregate trips neither.
    assert detect_fanout("SELECT SUM(unit_price) FROM order_items", tcols, "duckdb") is None
    assert not measure_times_key_arithmetic("SELECT SUM(unit_price) FROM order_items", tcols, "duckdb")


# ── ON-0: the harness must not spend on an arm that cannot differ, and must say what answered ──

def test_ontology_arms_are_dropped_when_there_is_nothing_to_inject():
    from evals.ablation_eval import _arms_after_ontology_check
    arms = ("raw", "guarded", "ontology", "ontology_guarded")
    kept, dropped = _arms_after_ontology_check(arms, "")
    assert kept == ("raw", "guarded")
    assert dropped == ("ontology", "ontology_guarded")
    # a real block keeps every arm; no ontology arm requested → nothing to drop
    assert _arms_after_ontology_check(arms, "ENTITY MODEL …") == (arms, ())
    assert _arms_after_ontology_check(("raw", "guarded"), "") == (("raw", "guarded"), ())


def test_load_graph_reads_the_served_json_when_mapped_and_the_store_otherwise(tmp_path):
    """`--graph-json` is the door for a run beside a serving API: the store is system.db,
    a redirected store is empty, and the file is what GET /ontology returned."""
    import json
    from aughor.ontology.prompt_reach import fixture_graph
    from evals.ablation_eval import _load_graph
    g = fixture_graph()
    path = tmp_path / "served.json"
    path.write_text(json.dumps(g.model_dump(mode="json"), default=str))
    graph, source = _load_graph("conn", "sch", {"conn/sch": str(path)})
    assert source == f"file:{path}"
    assert set(graph.entities) == set(g.entities)
    # a connection-only label also matches (datasets without a schema)
    graph2, source2 = _load_graph("conn", "sch", {"conn": str(path)})
    assert source2.startswith("file:") and set(graph2.entities) == set(g.entities)
    # no mapping → the store, which the hermetic conftest leaves empty
    assert _load_graph("conn", "sch", None) == (None, "store")


def test_llm_identity_is_a_receipt_never_an_abort(monkeypatch):
    from evals.ablation_eval import _llm_identity
    monkeypatch.setenv("AUGHOR_FALLBACK_BACKENDS", "none")
    ident = _llm_identity()
    assert set(ident) >= {"backend", "model", "role", "fallback_chain"}
    assert ident["role"] == "coder"
    if ident["fallback_chain"] is not None:            # resolved → the pin is honoured
        assert ident["fallback_chain"] == []


def test_summary_and_report_carry_the_model_and_the_dropped_arms(capsys):
    from evals.ablation_eval import _summarize, _print_report
    arms = ("raw", "guarded")
    rows = [
        {"id": "q1", "trap": "control", "question": "?",
         "raw": {"sql": "SELECT 1", "class": "correct", "match": 1.0},
         "guarded": {"sql": "SELECT 1", "class": "correct", "guards_fired": [], "match": 1.0},
         "latency_s": 0.1},
        {"id": "q2", "trap": "grain", "question": "?",
         "raw": {"sql": "SELECT 2", "class": "silent-wrong", "match": 0.0},
         "guarded": {"sql": "SELECT 2", "class": "caught", "guards_fired": ["fanout"], "match": 0.0},
         "latency_s": 0.1},
    ]
    s = _summarize(rows, arms)
    s.update({"llm": {"backend": "gemini", "model": "m-1", "role": "coder", "fallback_chain": []},
              "arms_dropped": ["ontology", "ontology_guarded"], "ontology_source": "store",
              "ontology_available": False, "reference_failed": []})
    _print_report(rows, s, arms)
    out = capsys.readouterr().out
    assert "Model: gemini · m-1" in out and "fallback chain: none" in out
    assert "Dropped arms" in out and "ontology_guarded" in out
    assert s["saves"] == ["q2"] and s["guarded_safe_rate"] == 1.0
