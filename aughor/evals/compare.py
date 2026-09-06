"""Derived experiments — A/B run pairs read back out of the run history.

The running half of an experiment already exists twice over: ``run_experiment`` stamps
every run with the cell that produced it (``config.cell_requested``), and
``scripts/flag_ab_grid.py`` drives it with the two guards measurement needs (the
inertness pre-check and the pinned temperature). What was missing is the READING —
``scripts/grid_case_diff.py``'s own docstring calls itself "the reading flag_ab_grid.py
tells you to do and nothing produced", and it lived where no product surface could reach
it. This module is that reading as a library: the routes and the panel consume it, and
the script keeps working unchanged.

Two decisions, both inherited rather than invented:

- **An experiment is DERIVED, never stored.** A pair of runs whose recorded
  configurations differ on exactly one axis IS the experiment; a table repeating that
  fact would be a catalogue that can rot while the runs it describes stay true. The
  graduation gate (``_ab_evidence``) already reads pairs this way.
- **Cells are classified by what the run RECORDED it was asked for**
  (``config.cell_requested``), never by a label — a cell named "control" that actually
  ran with the flag on must not be read as the baseline. Runs recorded before
  ``cell_requested`` existed fall back to ``config.flag_overrides``, which is what
  ``grid_case_diff.py`` always keyed on.

Per-case verdicts follow the script's vocabulary exactly: ``correct`` / ``wrong`` /
``no-ref`` (the case declared no reference, so correctness is unknowable) / ``error`` —
and a case one cell never reached is ``unrun``, not a flip: a killed grid must never
read as "the flag lost ten cases".
"""
from __future__ import annotations

import json
from typing import Optional

from aughor.evals import store

#: How many runs back the pairing looks per suite. Bounded because the pairing is a
#: read-path scan; older pairs remain reachable by naming both run ids explicitly.
_SCAN_LIMIT = 100


def _config_of(run: dict) -> dict:
    cfg = run.get("config") or {}
    if isinstance(cfg, str):  # a raw row from an older reader; list_runs already parses
        try:
            cfg = json.loads(cfg)
        except Exception:
            return {}
    return cfg if isinstance(cfg, dict) else {}


def _requested_flags(run: dict) -> Optional[dict]:
    """The flag map this run was ASKED to hold, or None when it recorded none."""
    cfg = _config_of(run)
    requested = (cfg.get("cell_requested") or {}).get("flags")
    if isinstance(requested, dict) and requested:
        return requested
    fallback = cfg.get("flag_overrides")
    if isinstance(fallback, dict) and fallback:
        return fallback
    return None


def _requested_model(run: dict) -> Optional[str]:
    model = (_config_of(run).get("cell_requested") or {}).get("model")
    return model or None


def _axis_between(a: dict, b: dict) -> Optional[dict]:
    """The single axis on which two runs' recorded requests differ, or None.

    Two shapes qualify: the same one flag requested with opposite values (a flag A/B),
    or the same flag map — usually empty — with two different pinned models (a bakeoff).
    Anything else is not an attributable pair: a delta across two moved axes belongs to
    neither of them.
    """
    fa, fb = _requested_flags(a), _requested_flags(b)
    ma, mb = _requested_model(a), _requested_model(b)

    if fa is not None and fb is not None and set(fa) == set(fb) and len(fa) == 1:
        (flag,) = fa
        if bool(fa[flag]) != bool(fb[flag]) and ma == mb:
            return {"kind": "flag", "name": flag}
    if ma and mb and ma != mb and (fa or {}) == (fb or {}):
        return {"kind": "model", "name": None}
    return None


def _run_brief(run: dict) -> dict:
    summary = run.get("summary") or {}
    return {
        "run_id": run.get("id"),
        "status": run.get("status"),
        "started_at": run.get("started_at"),
        "cell": _config_of(run).get("cell") or "",
        "pass_rate": summary.get("pass_rate"),
        "correct": summary.get("correct"),
        "correctness_known": summary.get("correctness_known"),
        "total": summary.get("total"),
    }


def find_experiments(suite_id: Optional[str] = None, *, limit: int = 50) -> list[dict]:
    """Every A/B pair the run history holds, newest first, each run used once.

    With no ``suite_id`` the scan covers every suite that has runs. ``a`` is the
    baseline side — flag OFF for a flag pair; for a model pair, orientation carries no
    off/on meaning and the OLDER run is called the baseline.
    """
    if suite_id:
        suite_ids = [suite_id]
    else:
        suite_ids = [s["id"] for s in store.list_suites()]

    out: list[dict] = []
    for sid in suite_ids:
        runs = store.list_runs(sid, limit=_SCAN_LIMIT)
        used: set[str] = set()
        for i, first in enumerate(runs):
            if first["id"] in used:
                continue
            for second in runs[i + 1:]:
                if second["id"] in used:
                    continue
                axis = _axis_between(first, second)
                if axis is None:
                    continue
                if axis["kind"] == "flag":
                    flags_first = _requested_flags(first) or {}
                    on, off = ((first, second) if flags_first.get(axis["name"])
                               else (second, first))
                else:
                    off, on = second, first  # runs are newest-first: older = baseline
                    axis["a_model"] = _requested_model(off)
                    axis["b_model"] = _requested_model(on)
                used.update((first["id"], second["id"]))
                out.append({"suite_id": sid, "axis": axis,
                            "a": _run_brief(off), "b": _run_brief(on)})
                break
        if len(out) >= max(1, limit):
            break
    return out[:max(1, limit)]


def _verdict(res: Optional[dict]) -> str:
    if res is None:
        return "missing"
    if res.get("error"):
        return "error"
    correct = res.get("correct")
    if correct is None:
        return "no-ref"
    return "correct" if correct else "wrong"


def _trace_detail(res: Optional[dict]) -> dict:
    for score in (res or {}).get("scores") or []:
        if score.get("evaluator") == "trace.observation":
            return score.get("detail") or {}
    return {}


def _clip(text: str, cap: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= cap else text[: cap - 2] + " …"


def compare_runs(a_run_id: str, b_run_id: str, *, max_rows: int = 200) -> dict:
    """The per-case reading of one pair — verdict in each cell, the flips, and the SQL.

    Accuracy is reported twice on purpose: over each run's own results, and over the
    cases BOTH cells ran — a killed or still-running cell makes the totals
    incomparable, and the paired subset is the honest comparison.
    """
    a_run, b_run = store.get_run(a_run_id), store.get_run(b_run_id)
    if a_run is None or b_run is None:
        raise KeyError("run not found")
    if a_run.get("suite_id") != b_run.get("suite_id"):
        raise ValueError("the two runs belong to different suites and share no cases")

    suite_id = a_run["suite_id"]
    cases = {c["id"]: c for c in store.list_cases(suite_id, limit=1000)}
    res_a = {r["case_id"]: r for r in store.run_results(a_run_id, limit=5000)}
    res_b = {r["case_id"]: r for r in store.run_results(b_run_id, limit=5000)}

    tally = {"same": 0, "gained": 0, "lost": 0, "other": 0, "unrun": 0}
    rows: list[dict] = []
    for case_id, case in cases.items():
        a, b = res_a.get(case_id), res_b.get(case_id)
        va, vb = _verdict(a), _verdict(b)
        if va == "missing" or vb == "missing":
            tally["unrun"] += 1
            continue
        if va == vb:
            tally["same"] += 1
            continue
        if va != "correct" and vb == "correct":
            kind = "gained"
        elif va == "correct" and vb != "correct":
            kind = "lost"
        else:
            kind = "other"
        tally[kind] += 1
        if len(rows) < max(1, max_rows):
            rows.append({
                "case_id": case_id,
                "question": case.get("question", ""),
                "a": va, "b": vb, "kind": kind,
                "a_sql": _clip(_trace_detail(a).get("sql") or "", 400),
                "b_sql": _clip(_trace_detail(b).get("sql") or "", 400),
                "a_error": _clip((a or {}).get("error") or "", 200),
                "b_error": _clip((b or {}).get("error") or "", 200),
            })

    def _accuracy(results: dict) -> dict:
        known = sum(1 for r in results.values() if r.get("correct") is not None)
        return {"correct": sum(1 for r in results.values() if r.get("correct")),
                "known": known}

    both = [cid for cid in cases if cid in res_a and cid in res_b]
    paired = {
        "cases": len(both),
        "a_correct": sum(1 for cid in both if res_a[cid].get("correct")),
        "b_correct": sum(1 for cid in both if res_b[cid].get("correct")),
    }
    has_sql = any(_trace_detail(r) for r in
                  list(res_a.values())[:3] + list(res_b.values())[:3])
    return {
        "suite_id": suite_id,
        "axis": _axis_between(a_run, b_run),
        "a": _run_brief(a_run), "b": _run_brief(b_run),
        "accuracy": {"a": _accuracy(res_a), "b": _accuracy(res_b), "paired": paired},
        "flips": tally,
        "rows": rows,
        "sql_available": has_sql,
    }
