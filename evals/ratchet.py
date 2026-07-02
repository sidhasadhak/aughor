#!/usr/bin/env python3
"""Delta ratchet — the measurement instrument for the AI-FDE benefit program (P0).

Every phase of that program (close-the-loop, context surface, plan gate, …) must
prove a *measured delta* on the real path before it ships. This module is that
instrument. It runs the curated golden set (``evals/golden_sql_expanded.jsonl``,
trusted local reference SQL against the ``samples`` warehouse — NOT public gold,
which we found ~53–66% wrong) through the REAL generation pipeline and captures
two things per question:

- **accuracy** — execution-grounded, via :func:`evals.sql_accuracy.score_single`
  (multi-reference aware: ``accept_sql`` alternatives don't penalise a correct
  answer that picked a different-but-canonical metric).
- **compute** — tokens · LLM calls · latency, via :mod:`aughor.kernel.metering`
  (honest compute, *not* dollars — the metering contract deliberately avoids a
  drifting price table; a $ figure is derivable later from ``total_tokens``).

Each run is persisted to ``data/eval_baseline.db`` and can be named as a baseline.
:func:`compare_to_baseline` fails loud on an accuracy drop (> ``acc_tol``) or a
compute rise (> ``cost_tol``), so a phase is "done" only when its delta clears
the bar.

Usage::

    # capture a baseline on main (live LLM; pins samples + temperature 0.0)
    .venv/bin/python evals/ratchet.py run --mode full --set-baseline main

    # after a change: re-run and fail-loud if it regresses vs the named baseline
    .venv/bin/python evals/ratchet.py check --baseline main --mode full

    # deterministic plumbing check (no LLM — replays reference SQL)
    .venv/bin/python evals/ratchet.py run --mode reference --limit 5
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from evals.run_golden import run_eval  # noqa: E402

DEFAULT_DATASET = str(_REPO_ROOT / "evals" / "golden_sql_expanded.jsonl")
DEFAULT_DB = _REPO_ROOT / "data" / "eval_baseline.db"
DEFAULT_CONNECTION = "samples"

# Regression tolerances (the delta gate). Accuracy is an absolute drop in the
# mean overall / execution-success score; compute is a relative rise in tokens.
ACC_TOL = 0.02   # > 2% absolute accuracy drop fails
COST_TOL = 0.15  # > 15% token increase fails


# ── Data shapes ──────────────────────────────────────────────────────────────

@dataclass
class RatchetItem:
    qid: str
    difficulty: str
    category: str
    overall: float          # 0..1 execution-grounded score
    exec_success: float     # 0/1 did generated SQL execute
    tokens: int             # total tokens for this question's generation
    llm_calls: int
    latency_ms: float
    error: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RunSummary:
    run_id: str
    git_sha: str
    created_at: str
    mode: str
    connection: str
    dataset: str
    label: str
    n: int
    mean_overall: float
    exec_rate: float
    total_tokens: int
    total_llm_calls: int
    mean_latency_ms: float
    by_difficulty: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


# ── Pure aggregation / comparison (no LLM, no DB — unit-testable) ─────────────

def summarize(items: list[RatchetItem], *, mode: str, connection: str,
              dataset: str, label: str = "", run_id: Optional[str] = None,
              git_sha: Optional[str] = None) -> RunSummary:
    """Collapse per-question items into a run summary. Pure."""
    n = len(items)
    mean_overall = round(sum(i.overall for i in items) / n, 4) if n else 0.0
    exec_rate = round(sum(i.exec_success for i in items) / n, 4) if n else 0.0
    total_tokens = sum(int(i.tokens) for i in items)
    total_calls = sum(int(i.llm_calls) for i in items)
    mean_latency = round(sum(i.latency_ms for i in items) / n, 1) if n else 0.0

    by_diff: dict[str, dict] = {}
    for i in items:
        d = by_diff.setdefault(i.difficulty or "unknown", {"n": 0, "overall": 0.0, "exec": 0.0})
        d["n"] += 1
        d["overall"] += i.overall
        d["exec"] += i.exec_success
    for d in by_diff.values():
        d["overall"] = round(d["overall"] / d["n"], 4)
        d["exec"] = round(d["exec"] / d["n"], 4)

    return RunSummary(
        run_id=run_id or uuid.uuid4().hex[:12],
        git_sha=git_sha if git_sha is not None else _git_sha(),
        created_at=datetime.now(timezone.utc).isoformat(),
        mode=mode, connection=connection, dataset=dataset, label=label,
        n=n, mean_overall=mean_overall, exec_rate=exec_rate,
        total_tokens=total_tokens, total_llm_calls=total_calls,
        mean_latency_ms=mean_latency, by_difficulty=by_diff,
    )


def compare_to_baseline(current: RunSummary, baseline: RunSummary, *,
                        acc_tol: float = ACC_TOL, cost_tol: float = COST_TOL) -> tuple[bool, list[str]]:
    """Return (ok, reasons). Fails loud on accuracy regression or compute rise.

    Comparisons are only meaningful across the SAME dataset+mode; a mismatch is
    surfaced as a blocking reason rather than a silent pass."""
    reasons: list[str] = []

    if current.dataset != baseline.dataset:
        reasons.append(f"dataset mismatch (current={current.dataset}, baseline={baseline.dataset})")
    if current.mode != baseline.mode:
        reasons.append(f"mode mismatch (current={current.mode}, baseline={baseline.mode})")
    if current.n != baseline.n:
        reasons.append(f"question-count mismatch (current n={current.n}, baseline n={baseline.n})")

    acc_drop = round(baseline.mean_overall - current.mean_overall, 4)
    if acc_drop > acc_tol:
        reasons.append(f"accuracy regressed {acc_drop:+.4f} "
                       f"(baseline {baseline.mean_overall:.4f} → current {current.mean_overall:.4f}, tol {acc_tol})")
    exec_drop = round(baseline.exec_rate - current.exec_rate, 4)
    if exec_drop > acc_tol:
        reasons.append(f"execution-success regressed {exec_drop:+.4f} "
                       f"(baseline {baseline.exec_rate:.4f} → current {current.exec_rate:.4f}, tol {acc_tol})")

    # Compute regression only meaningful when the baseline actually spent tokens
    # (reference-mode replays cost 0 tokens — skip the check there).
    if baseline.total_tokens > 0:
        allowed = baseline.total_tokens * (1 + cost_tol)
        if current.total_tokens > allowed:
            rise = current.total_tokens / baseline.total_tokens - 1
            reasons.append(f"compute rose {rise:+.1%} "
                           f"(baseline {baseline.total_tokens:,} → current {current.total_tokens:,} tokens, tol {cost_tol:.0%})")

    return (len(reasons) == 0, reasons)


def _git_sha() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             cwd=str(_REPO_ROOT), capture_output=True, text=True, timeout=5)
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


# ── Persistence (data/eval_baseline.db) ──────────────────────────────────────

def _connect(db_path: Path = DEFAULT_DB) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("""CREATE TABLE IF NOT EXISTS runs (
        run_id TEXT PRIMARY KEY, git_sha TEXT, created_at TEXT, mode TEXT,
        connection TEXT, dataset TEXT, label TEXT, n INTEGER,
        mean_overall REAL, exec_rate REAL, total_tokens INTEGER,
        total_llm_calls INTEGER, mean_latency_ms REAL, by_difficulty TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS run_items (
        run_id TEXT, qid TEXT, difficulty TEXT, category TEXT, overall REAL,
        exec_success REAL, tokens INTEGER, llm_calls INTEGER, latency_ms REAL, error TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS baselines (
        name TEXT PRIMARY KEY, run_id TEXT, set_at TEXT)""")
    conn.commit()
    return conn


def persist_run(summary: RunSummary, items: list[RatchetItem], db_path: Path = DEFAULT_DB) -> str:
    conn = _connect(db_path)
    try:
        conn.execute(
            """INSERT OR REPLACE INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (summary.run_id, summary.git_sha, summary.created_at, summary.mode,
             summary.connection, summary.dataset, summary.label, summary.n,
             summary.mean_overall, summary.exec_rate, summary.total_tokens,
             summary.total_llm_calls, summary.mean_latency_ms,
             json.dumps(summary.by_difficulty)))
        conn.executemany(
            """INSERT INTO run_items VALUES (?,?,?,?,?,?,?,?,?,?)""",
            [(summary.run_id, i.qid, i.difficulty, i.category, i.overall,
              i.exec_success, i.tokens, i.llm_calls, i.latency_ms, i.error) for i in items])
        conn.commit()
        return summary.run_id
    finally:
        conn.close()


def _row_to_summary(row: sqlite3.Row) -> RunSummary:
    return RunSummary(
        run_id=row[0], git_sha=row[1], created_at=row[2], mode=row[3],
        connection=row[4], dataset=row[5], label=row[6], n=row[7],
        mean_overall=row[8], exec_rate=row[9], total_tokens=row[10],
        total_llm_calls=row[11], mean_latency_ms=row[12],
        by_difficulty=json.loads(row[13] or "{}"))


def load_run(run_id: str, db_path: Path = DEFAULT_DB) -> Optional[RunSummary]:
    conn = _connect(db_path)
    try:
        row = conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        return _row_to_summary(row) if row else None
    finally:
        conn.close()


def set_baseline(name: str, run_id: str, db_path: Path = DEFAULT_DB) -> None:
    conn = _connect(db_path)
    try:
        conn.execute("INSERT OR REPLACE INTO baselines VALUES (?,?,?)",
                     (name, run_id, datetime.now(timezone.utc).isoformat()))
        conn.commit()
    finally:
        conn.close()


def get_baseline(name: str, db_path: Path = DEFAULT_DB) -> Optional[RunSummary]:
    conn = _connect(db_path)
    try:
        row = conn.execute("SELECT run_id FROM baselines WHERE name=?", (name,)).fetchone()
        if not row:
            return None
        run_row = conn.execute("SELECT * FROM runs WHERE run_id=?", (row[0],)).fetchone()
        return _row_to_summary(run_row) if run_row else None
    finally:
        conn.close()


# ── Live scoring (needs a connection; needs an LLM for mode=full/raw) ─────────

def score_dataset(dataset: str = DEFAULT_DATASET, connection: str = DEFAULT_CONNECTION,
                  mode: str = "full", limit: Optional[int] = None,
                  ids: Optional[list[str]] = None, temperature: float = 0.0,
                  progress: bool = True) -> list[RatchetItem]:
    """Run the golden set through the real pipeline, metering each question."""
    import aughor.kernel.metering as metering
    from aughor.db.connection import open_connection_for

    records = [json.loads(l) for l in open(dataset) if l.strip()]
    if ids:
        idset = set(ids)
        records = [r for r in records if r["id"] in idset]
    if limit:
        records = records[:limit]

    db = open_connection_for(connection)
    items: list[RatchetItem] = []
    try:
        for idx, rec in enumerate(records, 1):
            rec.setdefault("connection_id", connection)
            t0 = time.time()
            snap: dict = {}
            with metering.metered() as m:
                res = run_eval(rec, db, mode=mode, temperature=temperature)
                if m is not None:
                    snap = m.to_dict()
            latency = round((time.time() - t0) * 1000, 1)
            scores = res.get("scores", {})
            item = RatchetItem(
                qid=rec["id"],
                difficulty=rec.get("difficulty", "unknown"),
                category=rec.get("category", "unknown"),
                overall=float(scores.get("overall", 0.0)),
                exec_success=float(scores.get("execution_success", 0.0)),
                tokens=int(snap.get("total_tokens", 0)),
                llm_calls=int(snap.get("llm_calls", 0)),
                latency_ms=latency,
                error=str(scores.get("error", "")),
            )
            items.append(item)
            if progress:
                print(f"  [{idx}/{len(records)}] {item.qid:8s} "
                      f"overall={item.overall:.2f} exec={item.exec_success:.0f} "
                      f"tok={item.tokens:6d} {item.difficulty}", flush=True)
    finally:
        db.close()
    return items


def run_ratchet(dataset: str = DEFAULT_DATASET, connection: str = DEFAULT_CONNECTION,
                mode: str = "full", limit: Optional[int] = None,
                ids: Optional[list[str]] = None, temperature: float = 0.0,
                label: str = "", db_path: Path = DEFAULT_DB,
                progress: bool = True) -> tuple[RunSummary, list[RatchetItem]]:
    items = score_dataset(dataset, connection, mode, limit, ids, temperature, progress)
    summary = summarize(items, mode=mode, connection=connection,
                        dataset=Path(dataset).name, label=label)
    persist_run(summary, items, db_path)
    return summary, items


# ── CLI ──────────────────────────────────────────────────────────────────────

def _print_summary(s: RunSummary) -> None:
    print(f"\n{'='*64}")
    print(f" run {s.run_id}  ({s.git_sha}, mode={s.mode}, conn={s.connection})")
    print(f"{'='*64}")
    print(f"  questions        : {s.n}")
    print(f"  mean overall     : {s.mean_overall:.4f}")
    print(f"  execution rate   : {s.exec_rate:.4f}")
    print(f"  total tokens     : {s.total_tokens:,}  ({s.total_llm_calls} LLM calls)")
    print(f"  mean latency     : {s.mean_latency_ms:.0f} ms")
    for d, st in sorted(s.by_difficulty.items()):
        print(f"    {d:8s}: overall={st['overall']:.3f} exec={st['exec']:.3f} (n={st['n']})")


def main() -> int:
    ap = argparse.ArgumentParser(description="Aughor delta ratchet (P0 measurement substrate)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def _common(p):
        p.add_argument("--dataset", default=DEFAULT_DATASET)
        p.add_argument("--connection", default=DEFAULT_CONNECTION)
        p.add_argument("--mode", default="full", choices=["full", "raw", "reference"])
        p.add_argument("--limit", type=int, default=None)
        p.add_argument("--ids", default=None, help="comma-separated question ids")
        p.add_argument("--temperature", type=float, default=0.0)
        p.add_argument("--db", default=str(DEFAULT_DB))

    p_run = sub.add_parser("run", help="run the set and persist a new run")
    _common(p_run)
    p_run.add_argument("--label", default="")
    p_run.add_argument("--set-baseline", default=None, metavar="NAME")

    p_check = sub.add_parser("check", help="run the set and fail-loud vs a baseline")
    _common(p_check)
    p_check.add_argument("--baseline", default="main")
    p_check.add_argument("--acc-tol", type=float, default=ACC_TOL)
    p_check.add_argument("--cost-tol", type=float, default=COST_TOL)

    p_show = sub.add_parser("show", help="list runs and baselines")
    p_show.add_argument("--db", default=str(DEFAULT_DB))

    args = ap.parse_args()
    db_path = Path(args.db)

    if args.cmd == "show":
        conn = _connect(db_path)
        try:
            print("Baselines:")
            for name, run_id, set_at in conn.execute("SELECT name, run_id, set_at FROM baselines"):
                print(f"  {name:12s} → {run_id}  ({set_at})")
            print("\nRuns:")
            for r in conn.execute("SELECT run_id, git_sha, mode, n, mean_overall, exec_rate, total_tokens, created_at FROM runs ORDER BY created_at DESC LIMIT 20"):
                print(f"  {r[0]}  {r[1]:10s} mode={r[2]:9s} n={r[3]:3d} "
                      f"overall={r[4]:.3f} exec={r[5]:.3f} tok={r[6]:>8,} {r[7]}")
        finally:
            conn.close()
        return 0

    ids = [s.strip() for s in args.ids.split(",")] if args.ids else None

    if args.cmd == "run":
        summary, _ = run_ratchet(args.dataset, args.connection, args.mode, args.limit,
                                 ids, args.temperature, args.label, db_path)
        _print_summary(summary)
        if args.set_baseline:
            set_baseline(args.set_baseline, summary.run_id, db_path)
            print(f"\n→ set baseline '{args.set_baseline}' = {summary.run_id}")
        return 0

    if args.cmd == "check":
        baseline = get_baseline(args.baseline, db_path)
        if baseline is None:
            print(f"No baseline named '{args.baseline}'. Capture one with:\n"
                  f"  python evals/ratchet.py run --mode {args.mode} --set-baseline {args.baseline}", file=sys.stderr)
            return 2
        summary, _ = run_ratchet(args.dataset, args.connection, args.mode, args.limit,
                                 ids, args.temperature, "", db_path)
        _print_summary(summary)
        ok, reasons = compare_to_baseline(summary, baseline, acc_tol=args.acc_tol, cost_tol=args.cost_tol)
        print(f"\n{'-'*64}")
        if ok:
            print(f"✓ PASS — no regression vs baseline '{args.baseline}' ({baseline.run_id})")
            return 0
        print(f"✗ FAIL — regression vs baseline '{args.baseline}' ({baseline.run_id}):")
        for r in reasons:
            print(f"    · {r}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
