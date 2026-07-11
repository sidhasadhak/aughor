"""
Unit tests for the P7 model bake-off harness (evals/model_bakeoff.py) and the
deterministic MLflow scorers (evals/mlflow_scorers.py).

Skipped entirely when mlflow isn't installed (uv sync --extra observability);
CI installs all extras, so these run there. No live LLM anywhere: generation
is monkeypatched, execution runs on an in-memory DuckDB, and the end-to-end
run_arm test drives the REAL mlflow.genai.evaluate against a tmp sqlite store —
the leverage gate proving the harness works before anyone burns model credits.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import types

import pytest

pytest.importorskip("mlflow", minversion="3.0")

import duckdb  # noqa: E402

from evals import model_bakeoff as mb  # noqa: E402


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fake_db():
    """A stand-in connection: sql_accuracy._safe_exec uses `_conn` directly."""
    con = duckdb.connect()
    con.execute("CREATE TABLE orders AS SELECT * FROM (VALUES (1, 10.0), (2, 20.0)) t(id, total)")
    return types.SimpleNamespace(_conn=con)


def _record(question="How many orders?", ref="SELECT COUNT(*) AS n FROM orders"):
    return {"id": "q1", "question": question, "reference_sql": ref,
            "difficulty": "easy", "category": "count"}


def _args(tmp_path, **over):
    base = dict(model="stub-model", models=None, dataset=str(tmp_path / "ds.jsonl"),
                connection="samples", limit=0, mode="full", temperature=0.0,
                tracking_uri=str(tmp_path / "mlruns"),  # file store: skinny has no sqlite
                experiment="aughor-bakeoff-test", output_dir=str(tmp_path / "out"))
    base.update(over)
    return argparse.Namespace(**base)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("MLFLOW_GENAI_EVAL_MAX_WORKERS", raising=False)
    monkeypatch.setenv("MLFLOW_ENABLE_ASYNC_TRACE_LOGGING", "false")
    monkeypatch.setenv("MLFLOW_ALLOW_FILE_STORE", "true")  # ≥3.14 gates file stores
    monkeypatch.setenv("AUGHOR_CODER_MODEL", "pre-existing")  # restored by monkeypatch
    yield
    os.environ.pop("MLFLOW_GENAI_EVAL_MAX_WORKERS", None)


# ── Pure helpers ──────────────────────────────────────────────────────────────

def test_load_records_and_limit(tmp_path):
    p = tmp_path / "ds.jsonl"
    p.write_text("\n".join(json.dumps(_record(question=f"q{i}")) for i in range(5)))
    assert len(mb.load_records(str(p))) == 5
    assert len(mb.load_records(str(p), limit=2)) == 2


def test_build_rows_shape():
    rows = mb.build_rows([_record()])
    assert rows[0]["inputs"]["question"] == "How many orders?"
    assert rows[0]["inputs"]["record"]["reference_sql"].startswith("SELECT")


def test_sanitize_model_id():
    assert mb.sanitize_model_id("glm-5.2:cloud") == "glm-5.2_cloud"
    assert mb.sanitize_model_id("Qwen/Qwen2.5-Coder") == "Qwen_Qwen2.5-Coder"


def test_arm_command_roundtrip(tmp_path):
    args = _args(tmp_path, models="a,b", limit=7)
    cmd = mb.arm_command("evals.model_bakeoff", args, "a")
    assert cmd[:3] == [sys.executable, "-m", "evals.model_bakeoff"]
    assert "--model" in cmd and "a" in cmd
    assert "--limit" in cmd and "7" in cmd
    assert "--models" not in cmd  # the arm never recurses into parent mode


def test_aggregate_arm_metric_key_shapes():
    timings = [{"latency_ms": 100.0, "total_tokens": 50},
               {"latency_ms": 300.0, "total_tokens": 150}]
    # bare keys
    a = mb.aggregate_arm({"execution_accuracy": 0.8, "exec_success": 1.0,
                          "trust_verify": 0.9}, timings, 2)
    assert a["execution_accuracy"] == 0.8 and a["n"] == 2
    assert a["latency_p50_ms"] == 200.0 and a["tokens_per_q"] == 100.0
    # name/mean keys (mlflow's aggregate naming)
    b = mb.aggregate_arm({"execution_accuracy/mean": 0.7}, timings, 2)
    assert b["execution_accuracy"] == 0.7
    # missing → None, not a crash
    c = mb.aggregate_arm({}, [], 0)
    assert c["execution_accuracy"] is None and c["latency_p50_ms"] == 0.0


def test_print_comparison_handles_failures(capsys):
    mb.print_comparison([
        {"model": "good", "execution_accuracy": 0.9, "exec_success": 1.0,
         "trust_verify": 1.0, "latency_p50_ms": 120.0, "tokens_per_q": 800.0},
        {"model": "bad", "error": "arm exited 1 with no result file"},
    ])
    out = capsys.readouterr().out
    assert "good" in out and "90.0%" in out
    assert "FAILED: arm exited 1" in out


# ── Scorers ───────────────────────────────────────────────────────────────────

def test_execution_accuracy_scorer():
    from evals.mlflow_scorers import make_execution_accuracy
    db = _fake_db()
    s = make_execution_accuracy(db)
    inputs = {"record": _record()}
    perfect = s(inputs=inputs, outputs={"sql": "SELECT COUNT(*) AS n FROM orders"})
    assert perfect.value == 1.0
    wrong = s(inputs=inputs, outputs={"sql": "SELECT 999 AS n"})
    assert wrong.value < 1.0
    empty = s(inputs=inputs, outputs={"sql": ""})
    assert empty.value == 0.0 and "no SQL" in empty.rationale


def test_trust_verify_scorer_blocks_mutations():
    from evals.mlflow_scorers import trust_verify
    ok = trust_verify(inputs={"record": {}}, outputs={"sql": "SELECT 1"})
    assert ok.value is True
    blocked = trust_verify(inputs={"record": {}}, outputs={"sql": "DROP TABLE orders"})
    assert blocked.value is False
    assert blocked.rationale  # names the reason


def test_exec_success_scorer():
    from evals.mlflow_scorers import exec_success
    assert exec_success(outputs={"ok": True}).value is True
    failed = exec_success(outputs={"ok": False, "error": "syntax error"})
    assert failed.value is False and "syntax" in failed.rationale


# ── run_arm end-to-end (real mlflow.genai.evaluate, no LLM) ──────────────────

def test_run_arm_end_to_end(tmp_path, monkeypatch):
    """A 'perfect model' arm (generation returns the reference SQL) must score
    execution_accuracy == 1.0 through the REAL evaluate harness and write the
    comparison JSON the parent consumes."""
    ds = tmp_path / "ds.jsonl"
    recs = [_record(), _record(question="Total revenue?",
                             ref="SELECT SUM(total) AS revenue FROM orders")]
    ds.write_text("\n".join(json.dumps(r) for r in recs))

    from evals import run_golden
    monkeypatch.setattr(run_golden, "generate_sql_full_pipeline",
                        lambda q, conn_id, db, temperature=0.0: next(
                            r["reference_sql"] for r in recs if r["question"] == q))

    args = _args(tmp_path)
    arm = mb.run_arm(args, db=_fake_db())

    assert not arm.get("error"), arm
    assert arm["execution_accuracy"] == 1.0
    assert arm["exec_success"] == 1.0
    assert arm["trust_verify"] == 1.0
    assert arm["n"] == 2
    assert arm["run_id"]
    assert os.environ["AUGHOR_CODER_MODEL"] == "stub-model"  # the arm pinned it
    out = json.loads((tmp_path / "out" / "stub-model.json").read_text())
    assert out["model"] == "stub-model"
    assert out["execution_accuracy"] == 1.0


def test_run_arm_generation_failure_is_scored_not_crashed(tmp_path, monkeypatch):
    ds = tmp_path / "ds.jsonl"
    ds.write_text(json.dumps(_record()))
    from evals import run_golden
    monkeypatch.setattr(run_golden, "generate_sql_full_pipeline",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("model 404")))
    arm = mb.run_arm(_args(tmp_path), db=_fake_db())
    assert not arm.get("error"), arm  # the ARM succeeds; the QUESTION scores 0
    assert arm["execution_accuracy"] == 0.0
    assert arm["exec_success"] == 0.0
