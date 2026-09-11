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


def test_dataset_can_name_its_duckdb_file_and_bypass_the_registry(tmp_path):
    """A registered connection id resolves to nothing under the hermetic registry; a record
    that names its DuckDB file opens it directly — read-only — and the label is untouched."""
    import duckdb
    from evals.ablation_eval import _open_dataset_db
    path = tmp_path / "wh.duckdb"
    con = duckdb.connect(str(path)); con.execute("CREATE SCHEMA lux; CREATE TABLE lux.orders (order_id INT, gmv DOUBLE)")
    con.execute("INSERT INTO lux.orders VALUES (1, 10.0), (2, 20.0)"); con.close()
    db = _open_dataset_db({"connection_id": "deadbeef", "schema": "lux", "duckdb_path": str(path)})
    try:
        assert "orders" in db.get_schema()
        r = db.execute("__t__", "SELECT COUNT(*) FROM lux.orders")
        assert not r.error and int(r.rows[0][0]) == 2
        assert getattr(db, "engine_read_only", None) is True
    finally:
        db.close()
    # no file → the registry, which the hermetic conftest leaves empty for a registered id
    import pytest
    with pytest.raises(KeyError, match="deadbeef"):
        _open_dataset_db({"connection_id": "deadbeef", "schema": "lux"})


# ── ON-2 · the objects arm (§6 item 15): a model fills the IR, the compiler writes the SQL ──

def _samples_objects_fixture(tmp_path):
    import json
    from pathlib import Path

    import duckdb

    from aughor.db.connection import open_connection
    from aughor.demo.setup import _seed_ecommerce
    from aughor.ontology.models import OntologyGraph

    path = tmp_path / "samples.duckdb"
    con = duckdb.connect(str(path))
    _seed_ecommerce(con)
    con.close()
    graph = OntologyGraph.model_validate(json.loads(
        (Path(__file__).resolve().parents[2] / "evals" / "ablation_samples_ecommerce_ontology_measured.json").read_text()))
    return open_connection("duckdb", str(path), schema_name="ecommerce", connection_id="objects-arm-t"), graph


def test_the_objects_arm_classes_each_fill_by_what_the_compiler_and_the_scorer_say(tmp_path):
    from evals.ablation_eval import ObjectQueryFill, _FillFilter, _FillMeasure, objects_arm
    db, graph = _samples_objects_fixture(tmp_path)
    share = {"id": "s04", "reference_sql": "SELECT ROUND(100.0 * SUM(CASE WHEN status = 'cancelled' THEN 1 "
                                           "ELSE 0 END) / COUNT(*), 2) FROM orders"}

    def arm(fill):
        return objects_arm("q", share, db, graph, "", "", fill=lambda *_a: fill)

    right = ObjectQueryFill(object_type="order", measures=[_FillMeasure(
        name="pct", where=[_FillFilter(path="status", value="cancelled")], divide_by_agg="count",
        scale=100, decimals=2)])
    assert arm(right)["class"] == "correct"
    misspelt = right.model_copy(deep=True)
    misspelt.measures[0].where[0].value = "canceled"
    assert arm(misspelt)["class"] == "silent-wrong"                  # compiled, ran, wrong: dangerous
    fanout = ObjectQueryFill(object_type="order_item", measures=[_FillMeasure(agg="sum", path="order.total_amount")])
    refused = arm(fanout)
    assert refused["class"] == "refused" and refused["refusal_kind"] == "law"
    assert arm(ObjectQueryFill())["class"] == "declined"

    def boom(*_a):
        raise RuntimeError("provider down")
    assert objects_arm("q", share, db, graph, "", "", fill=boom)["class"] == "error"
    db.close()


def test_the_objects_summary_reports_the_fallback_posture_and_what_it_gained_or_lost():
    from evals.ablation_eval import _summarize
    rows = [
        {"id": "a", "trap": None, "raw": {"class": "correct"},
         "objects": {"class": "refused", "refusal_kind": "graph", "refused": "no link"},
         "objects_fallback": {"class": "correct", "via": "raw"}},
        {"id": "b", "trap": None, "raw": {"class": "silent-wrong"}, "objects": {"class": "correct"},
         "objects_fallback": {"class": "correct", "via": "objects"}},
        {"id": "c", "trap": None, "raw": {"class": "correct"}, "objects": {"class": "silent-wrong"},
         "objects_fallback": {"class": "silent-wrong", "via": "objects"}},
    ]
    s = _summarize(rows, ("raw", "objects"))
    assert s["objects_compiled_share"] == round(2 / 3, 3) and s["objects_accuracy"] == round(1 / 3, 3)
    assert s["objects_gains"] == ["b"] and s["objects_losses"] == ["c"]
    assert s["objects_fallback_accuracy"] == round(2 / 3, 3) and s["objects_fallback_losses"] == ["c"]
    assert [r["id"] for r in s["objects_refused"]] == ["a"]
