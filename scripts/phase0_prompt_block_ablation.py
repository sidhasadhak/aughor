"""Phase 0 of the 2027 study — the paid ablation of the ontology prompt blocks (ROADMAP §3.53;
§6 item 15(d); kill 6 of §4.9: "re-measure each repair loop and prompt block against a current
model; delete the ones that no longer fire").

What it measures. The investigation's prompt carries ontology blocks the R4 ablation harness
can switch arm by arm: `raw` (no block), `ontology` (the description block), `framed` (the
declared terms, resolved by code), and their `_guarded` twins. §6 item 15(d) found the
description block lifted nothing twice and said that removing it "is its own measured change".
This script IS that change's measurement: the same harness, the same hard sets, a current model,
and one rule applied afterwards.

The rule. On a set where `raw` is NOT at ceiling, a block stays only if its arm beats `raw` by
more than the noise band (the harness's paired comparison); a block whose arm ties or loses on
every set is deleted from the prompt in the PR that cites this run. `framed` is expected to
stay — it is the one measured accuracy gain in the repo (5/16 → 16/16 and 7/15 → 14/15 on
2026-09-15). `ontology` is the block under sentence.

Runs on the user's machine (it spends model calls — ~2 arms × ~40 questions × 3 sets). This
container has no model key, so the script is prepared here and run there:

    uv run python scripts/phase0_prompt_block_ablation.py            # the three hard sets
    uv run python scripts/phase0_prompt_block_ablation.py --dry-run  # print the commands only

It writes `evals/prompt_block_ablation_<date>.json` per set through the harness's own
`--output`, then prints one table. Nothing here changes a prompt: the deletion is a separate,
reviewed edit that cites the receipt.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]

#: The sets where raw is NOT at ceiling — the only ones where a block can show a lift
#: (ROADMAP §3.15: `samples/ecommerce` is 12/12 on every arm, a ceiling, so it is left out).
SETS = (
    "evals/ablation_luxexperience_hard.jsonl",
    "evals/ablation_olist_business.jsonl",
    "evals/ablation_missimi_hard.jsonl",
)
ARMS = "raw,ontology,framed"


def _run(cmd: list[str], dry: bool) -> int:
    print("$", " ".join(cmd), flush=True)
    if dry:
        return 0
    return subprocess.call(cmd, cwd=REPO)


def _table(outputs: list[pathlib.Path]) -> None:
    rows: list[tuple[str, str, str]] = []
    for out in outputs:
        if not out.exists():
            rows.append((out.name, "—", "no output written (the run failed or was dry)"))
            continue
        try:
            data = json.loads(out.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 — an unreadable receipt is said, not hidden
            rows.append((out.name, "—", f"unreadable: {exc}"))
            continue
        arms = data.get("arms") or data.get("summary") or {}
        if isinstance(arms, dict):
            line = " · ".join(f"{a}: {v.get('accuracy', v) if isinstance(v, dict) else v}"
                              for a, v in arms.items())
        else:
            line = str(arms)[:200]
        rows.append((out.name, str(data.get("n") or data.get("count") or "?"), line))
    width = max(len(r[0]) for r in rows) if rows else 10
    print()
    print(f"{'set':<{width}}  n    arms")
    for name, n, line in rows:
        print(f"{name:<{width}}  {n:<4} {line}")
    print()
    print("The rule: on a set where raw is not at ceiling, a block stays only if its arm beats raw by more "
          "than the noise band; `ontology` is the block under sentence, `framed` is expected to stay. "
          "Cite these files in the PR that deletes a block.")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="print the harness commands and stop")
    ap.add_argument("--arms", default=ARMS, help=f"harness arms, comma-separated (default {ARMS})")
    ap.add_argument("--limit", type=int, default=None, help="questions per set (default: all)")
    args = ap.parse_args(argv)

    stamp = _dt.date.today().isoformat()
    outputs: list[pathlib.Path] = []
    rc = 0
    for rel in SETS:
        dataset = REPO / rel
        if not dataset.exists():
            print(f"skipping {rel}: not in this checkout", file=sys.stderr)
            continue
        out = REPO / "evals" / f"prompt_block_ablation_{stamp}_{dataset.stem.replace('ablation_', '')}.json"
        outputs.append(out)
        cmd = [sys.executable, "evals/ablation_eval.py", "--dataset", rel, "--arms", args.arms,
               "--output", str(out.relative_to(REPO))]
        if args.limit:
            cmd += ["--limit", str(args.limit)]
        rc = _run(cmd, args.dry_run) or rc
    _table(outputs)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
