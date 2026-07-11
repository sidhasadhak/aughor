#!/usr/bin/env python3
"""P7 model bake-off — compare candidate ``coder`` models on the golden dataset,
scored deterministically, logged to MLflow as directly comparable evaluation runs.

The instrument that turns P7 ("pin a frontier coder model") into an
evidence-based decision: one MLflow evaluation run per candidate — execution
accuracy × guard verdicts × latency × tokens — compared in the MLflow UI
(runs of the ``aughor-bakeoff`` experiment) or the printed table.

Usage::

    # one arm per candidate model, each in its OWN subprocess (the provider
    # resolves AUGHOR_CODER_MODEL at binding time and caches per process —
    # env-per-subprocess is the only clean isolation):
    uv run --extra observability python -m evals.model_bakeoff \
        --models "glm-5.2:cloud,qwen3-coder-next:cloud" --limit 20

    # a single arm in-process (what the parent spawns; also usable standalone):
    uv run --extra observability python -m evals.model_bakeoff \
        --model glm-5.2:cloud --limit 20

Scorers are deterministic only (no LLM judges) — see ``evals/mlflow_scorers.py``.
Generation reuses ``evals.run_golden``'s live pipeline verbatim (mode ``full`` =
the intelligence-injected production mirror; ``raw`` = schema-only prompt), so
the eval measures real platform quality, not a re-implementation.

Tracking: ``AUGHOR_MLFLOW_TRACKING_URI`` if set (share the compose ``obs``
server with the ``obs.mlflow`` runtime traces), else a local
``sqlite:///evals/bakeoff_out/mlruns.db`` store. Requires
``uv sync --extra observability``, a seeded connection (``aughor seed``), and
live LLM credentials for the arms.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_DEFAULT_DATASET = str(_REPO_ROOT / "evals" / "golden_sql_expanded.jsonl")
_DEFAULT_OUT = str(_REPO_ROOT / "evals" / "bakeoff_out")
_METRIC_KEYS = ("execution_accuracy", "exec_success", "trust_verify")


# ── Pure helpers (unit-tested) ────────────────────────────────────────────────

def load_records(dataset: str, limit: int = 0) -> list[dict]:
    records = []
    with open(dataset) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records[:limit] if limit else records


def build_rows(records: list[dict]) -> list[dict]:
    """The mlflow.genai.evaluate dataset: one row per golden record."""
    return [{"inputs": {"question": r["question"], "record": r}} for r in records]


def sanitize_model_id(model: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", model)


def arm_command(argv0_module: str, args: argparse.Namespace, model: str) -> list[str]:
    """The subprocess command for one bake-off arm (same interpreter, -m form)."""
    cmd = [sys.executable, "-m", argv0_module, "--model", model,
           "--dataset", args.dataset, "--connection", args.connection,
           "--mode", args.mode, "--output-dir", args.output_dir,
           "--experiment", args.experiment,
           "--temperature", str(args.temperature)]
    if args.limit:
        cmd += ["--limit", str(args.limit)]
    if args.tracking_uri:
        cmd += ["--tracking-uri", args.tracking_uri]
    return cmd


def aggregate_arm(metrics: dict, timings: list[dict], n: int) -> dict:
    """Collapse an arm's evaluate() metrics + per-question timings into the
    comparison-table row. Tolerant of metric-key shape (`name` vs `name/mean`)."""
    def _metric(name: str) -> float | None:
        for key in (name, f"{name}/mean", f"{name}/v1/mean"):
            if key in (metrics or {}):
                return float(metrics[key])
        return None

    lat = sorted(t.get("latency_ms", 0.0) for t in timings) or [0.0]
    toks = [t.get("total_tokens", 0) for t in timings]
    return {
        "n": n,
        "execution_accuracy": _metric("execution_accuracy"),
        "exec_success": _metric("exec_success"),
        "trust_verify": _metric("trust_verify"),
        "latency_p50_ms": round(statistics.median(lat), 1),
        "tokens_per_q": round(sum(toks) / max(len(toks), 1), 1),
    }


def print_comparison(arms: list[dict]) -> None:
    """The stdout ranking — MLflow UI has the full drill-down."""
    def _fmt(v, pct=False):
        if v is None:
            return "—"
        return f"{v * 100:.1f}%" if pct else f"{v:,.1f}"

    arms = sorted(arms, key=lambda a: (a.get("execution_accuracy") or 0.0),
                  reverse=True)
    print("\n=== P7 bake-off ===")
    header = f"{'model':<40} {'exec_acc':>9} {'exec_ok':>8} {'trust':>7} {'p50 ms':>9} {'tok/q':>8}"
    print(header)
    print("-" * len(header))
    for a in arms:
        if a.get("error"):
            print(f"{a['model']:<40} FAILED: {a['error']}")
            continue
        print(f"{a['model']:<40} {_fmt(a.get('execution_accuracy'), pct=True):>9} "
              f"{_fmt(a.get('exec_success'), pct=True):>8} "
              f"{_fmt(a.get('trust_verify'), pct=True):>7} "
              f"{_fmt(a.get('latency_p50_ms')):>9} {_fmt(a.get('tokens_per_q')):>8}")
    print()


# ── One arm ───────────────────────────────────────────────────────────────────

def run_arm(args: argparse.Namespace, db=None) -> dict:
    """Evaluate ONE candidate coder model and log it as an MLflow run.

    ``db`` is injectable for tests; by default the connection is opened via the
    registry like every other eval harness.
    """
    model = args.model
    os.environ["AUGHOR_CODER_MODEL"] = model
    # One scorer worker: determinism + the DuckDB connection in the scorer
    # closure is not safe for concurrent use.
    os.environ.setdefault("MLFLOW_GENAI_EVAL_MAX_WORKERS", "1")

    import mlflow

    # Importing run_golden also loads .env (its module-level load_dotenv) — but
    # AUGHOR_CODER_MODEL was exported above and load_dotenv never overrides
    # existing env, so the arm's model pin survives.
    from evals import run_golden
    from evals.mlflow_scorers import exec_success, make_execution_accuracy, trust_verify
    from evals.sql_accuracy import _safe_exec
    from aughor.kernel import metering

    records = load_records(args.dataset, args.limit)
    if db is None:
        from aughor.db.connection import open_connection_for
        db = open_connection_for(args.connection)
    schema = db.get_schema() if args.mode == "raw" else ""

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    mlflow.set_tracking_uri(args.tracking_uri
                            or os.getenv("AUGHOR_MLFLOW_TRACKING_URI")
                            or f"sqlite:///{out_dir / 'mlruns.db'}")
    mlflow.set_experiment(args.experiment)

    timings: list[dict] = []

    def predict_fn(question: str, record: dict) -> dict:
        token = metering.start()
        t0 = time.monotonic()
        try:
            if args.mode == "full":
                sql = run_golden.generate_sql_full_pipeline(
                    question, args.connection, db, temperature=args.temperature)
            else:
                sql = run_golden.generate_sql_chat(
                    question, args.connection, schema, temperature=args.temperature)
            ok, _cols, _rows, err = _safe_exec(db, sql)
        except Exception as e:  # a generation failure is a scored outcome, not a crash
            sql, ok, err = "", False, f"generation failed: {e}"
        latency_ms = round((time.monotonic() - t0) * 1000, 1)
        snap = metering.snapshot() or {}
        metering.reset(token)
        timing = {"latency_ms": latency_ms,
                  "total_tokens": int(snap.get("total_tokens") or 0)}
        timings.append(timing)
        return {"sql": sql, "ok": ok, "error": err or "", **timing}

    arm: dict = {"model": model, "mode": args.mode, "dataset": args.dataset,
                 "connection": args.connection}
    try:
        with mlflow.start_run(run_name=f"bakeoff:{model}") as active:
            mlflow.log_params({"coder_model": model, "mode": args.mode,
                               "dataset": Path(args.dataset).name,
                               "connection": args.connection,
                               "n": len(records),
                               "temperature": args.temperature})
            result = mlflow.genai.evaluate(
                data=build_rows(records),
                predict_fn=predict_fn,
                scorers=[make_execution_accuracy(db), exec_success, trust_verify],
            )
            arm.update(aggregate_arm(getattr(result, "metrics", {}) or {},
                                     timings, len(records)))
            mlflow.log_metrics({"latency_p50_ms": arm["latency_p50_ms"],
                                "tokens_per_q": arm["tokens_per_q"]})
            arm["run_id"] = active.info.run_id
    except Exception as e:
        arm["error"] = f"{type(e).__name__}: {e}"

    out_path = out_dir / f"{sanitize_model_id(model)}.json"
    out_path.write_text(json.dumps(arm, indent=2))
    print(f"[bakeoff] {model}: "
          + (arm.get("error") or f"exec_acc={arm.get('execution_accuracy')}")
          + f" → {out_path}")
    return arm


# ── Parent: one subprocess per candidate ──────────────────────────────────────

def run_all(args: argparse.Namespace) -> list[dict]:
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    arms = []
    for model in models:
        cmd = arm_command("evals.model_bakeoff", args, model)
        env = {**os.environ, "AUGHOR_CODER_MODEL": model}
        proc = subprocess.run(cmd, env=env)
        out_path = Path(args.output_dir) / f"{sanitize_model_id(model)}.json"
        if out_path.exists():
            arms.append(json.loads(out_path.read_text()))
        else:
            arms.append({"model": model,
                         "error": f"arm exited {proc.returncode} with no result file"})
    print_comparison(arms)
    return arms


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--models", help="comma-separated candidate coder model ids "
                                        "(one subprocess arm each)")
    group.add_argument("--model", help="a single candidate (runs in-process)")
    parser.add_argument("--dataset", default=_DEFAULT_DATASET)
    parser.add_argument("--connection", default="samples")
    parser.add_argument("--limit", type=int, default=0, help="0 = all records")
    parser.add_argument("--mode", choices=("full", "raw"), default="full",
                        help="full = production-mirror pipeline; raw = schema-only prompt")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--tracking-uri", default="",
                        help="MLflow tracking URI (default: AUGHOR_MLFLOW_TRACKING_URI "
                             "or a local sqlite store under --output-dir)")
    parser.add_argument("--experiment", default="aughor-bakeoff")
    parser.add_argument("--output-dir", default=_DEFAULT_OUT)
    args = parser.parse_args()

    if args.models:
        arms = run_all(args)
        return 1 if any(a.get("error") for a in arms) else 0
    arm = run_arm(args)
    return 1 if arm.get("error") else 0


if __name__ == "__main__":
    sys.exit(main())
