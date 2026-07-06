#!/usr/bin/env python3
"""Per-question diagnostic + single-instance run-and-score loop (WS5, throttled-endpoint mode).

The full-set runner is the wrong tool when the endpoint throttles and when the work is
accuracy, not throughput. This is the tight loop: inspect ONE question — its gold intent,
our SQL, where the result diverges — then (optionally) re-run just it (one LLM call) and
score it inline against gold with the OFFICIAL evaluator, so a fix is verified per-question.

Integrity: this reads gold RESULTS to diagnose and to score (allowed — self-eval). It never
tunes a prompt to a specific gold answer; fixes must be general mechanisms (build-the-feature,
not the bench-hack). Gold SQL is only partially released, so diagnosis is result-driven.

Usage:
  uv run python evals/spider2_diag.py show local021          # offline: full diagnostic
  uv run python evals/spider2_diag.py run  local021          # re-run one (1 LLM call) + score
  uv run python evals/spider2_diag.py run  local021 --bench-projection
  uv run python evals/spider2_diag.py list                   # the current miss set
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

_REPO = Path(__file__).parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

try:
    from dotenv import load_dotenv
    load_dotenv(_REPO / ".env")
except Exception:
    pass

from evals.spider2 import LITE, load_instances, run_instance  # noqa: E402

OUT = Path("evals/spider2_out")
GOLD_RESULT = LITE / "evaluation_suite" / "gold" / "exec_result"
GOLD_SQL = LITE / "evaluation_suite" / "gold" / "sql"
EVAL_SUITE = LITE / "evaluation_suite"


def _eval_meta(iid: str) -> dict:
    for line in (EVAL_SUITE / "gold" / "spider2lite_eval.jsonl").open():
        d = json.loads(line)
        if d["instance_id"] in (iid, f"sf_{iid}"):
            return d
    return {}


def _record(iid: str) -> dict:
    for r in load_instances("local"):
        if r["instance_id"] == iid:
            return r
    return {}


def _head(path: Path, n: int = 6) -> str:
    if not path.exists():
        return "(missing)"
    lines = path.read_text().splitlines()
    out = "\n".join("    " + line[:200] for line in lines[: n + 1])
    if len(lines) > n + 1:
        out += f"\n    … ({len(lines) - 1} data rows total)"
    return out


def _gold_variants(iid: str):
    return sorted(GOLD_RESULT.glob(f"{iid}_*.csv")) or sorted(GOLD_RESULT.glob(f"{iid}.csv"))


def score_one(iid: str, sql_dir: Path) -> bool | None:
    """Score a single instance with the OFFICIAL evaluator (temp result_dir of one)."""
    src = sql_dir / f"{iid}.sql"
    if not src.exists():
        return None
    tmp = Path(tempfile.mkdtemp(prefix=f"diag-{iid}-"))
    (tmp / f"{iid}.sql").write_text(src.read_text())
    proc = subprocess.run(
        [sys.executable, "evaluate.py", "--mode", "sql",
         "--result_dir", str(tmp), "--gold_dir", "gold"],
        cwd=EVAL_SUITE, capture_output=True, text=True,
    )
    for line in proc.stdout.splitlines():
        if line.startswith("{") and iid.replace("local", "") in line:
            try:
                d = json.loads(line.replace("'", '"'))
                for k, v in d.items():
                    if iid in k:
                        return bool(v)
            except Exception:
                pass
    if "Correct examples: 1" in proc.stdout:
        return True
    if "Correct examples: 0" in proc.stdout:
        return False
    return None


def show(iid: str, sql_dir: Path = OUT / "sql") -> None:
    rec = _record(iid)
    meta = _eval_meta(iid)
    print(f"\n{'='*78}\n {iid}  —  db: {rec.get('db')}\n{'='*78}")
    print(f"QUESTION:\n  {rec.get('question', '(?)')}")
    if rec.get("external_knowledge"):
        print(f"\nEXTERNAL KNOWLEDGE DOC: {rec['external_knowledge']}")
    print(f"\ncondition_cols: {meta.get('condition_cols', 'ALL')}   "
          f"ignore_order: {meta.get('ignore_order', False)}   gold_toks: {meta.get('toks', '?')}")
    print(f"\nOUR SQL ({sql_dir}):\n    " + (sql_dir / f"{iid}.sql").read_text().strip()
          .replace("\n", "\n    ") if (sql_dir / f"{iid}.sql").exists() else "(none)")
    print("\nOUR RESULT:")
    print(_head(OUT / "exec_result" / f"{iid}.csv"))
    gsql = GOLD_SQL / f"{iid}.sql"
    if gsql.exists():
        print("\nGOLD SQL:\n    " + gsql.read_text().strip().replace("\n", "\n    "))
    else:
        print("\nGOLD SQL: (not released for this instance)")
    print("\nGOLD RESULT(S):")
    for g in _gold_variants(iid):
        print(f"  [{g.name}]")
        print(_head(g))
    verdict = score_one(iid, sql_dir)
    print(f"\nVERDICT: {'✅ PASS' if verdict else '❌ FAIL' if verdict is False else '? (unknown)'}")


def run(iid: str, bench_projection: bool = False) -> None:
    rec = _record(iid)
    if not rec:
        print(f"no such local instance: {iid}")
        return
    run_dir = Path(tempfile.mkdtemp(prefix=f"diagrun-{iid}-"))
    print(f"running {iid} (bench_projection={bench_projection}) …")
    r = run_instance(rec, run_dir, temperature=0.0, use_ek=True, bench_projection=bench_projection)
    print(f"  exec_ok={r.get('ok')} rounds={r.get('rounds')} rows={r.get('rows')}")
    # copy the fresh SQL/CSV into a view and score
    show(iid, sql_dir=run_dir / "sql")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    cmd = sys.argv[1]
    if cmd == "list":
        fa = OUT / "fail_analysis.json"
        if fa.exists():
            for m in json.loads(fa.read_text())["misses"]:
                print(f"  {m['id']:10} {m['cat']:13} {'EK' if m['ek'] else '  '} {m['q']}")
        return 0
    if cmd in ("show", "run") and len(sys.argv) >= 3:
        iid = sys.argv[2]
        if cmd == "show":
            show(iid)
        else:
            run(iid, bench_projection="--bench-projection" in sys.argv)
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
