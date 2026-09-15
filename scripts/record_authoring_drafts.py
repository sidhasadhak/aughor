"""SP-M — draft the thirty authoring asks ONCE, and record what was staged.

THE ONE SPENDING STEP of the measurement, run only on the user's word: each ask goes
through the real converse loop with the real coder model, so ~30 asks cost roughly
30–90 model calls. Everything after this is free — `aughor.agent.authoring_measure`
scores the recordings in CI with no model, forever.

Isolation: every store is redirected to a scratch directory (the same
`_isolate_stores` the OpenAPI dump uses, since 2026-09-15 covering ALL stores), so
nothing here stages onto the live inbox or touches `data/`. Only the MODEL is live.

Usage:
    .venv/bin/python scripts/record_authoring_drafts.py --yes-spend [--connection ID]

Writes ``evals/authoring/recorded.jsonl`` — one line per ask: the ask, the tool calls
the model chose, every staged proposal row (params + detail, verbatim), and the final
answer. Re-running OVERWRITES: the corpus is drafted once per deliberate run, not
accreted.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from dump_openapi import _isolate_stores  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes-spend", action="store_true",
                    help="acknowledge that this run spends real model calls")
    ap.add_argument("--connection", default="fixture",
                    help="connection id to draft against (default: the builtin fixture)")
    args = ap.parse_args()
    if not args.yes_spend:
        print("This drafts 30 asks through the live coder model (~30-90 calls). "
              "Re-run with --yes-spend to proceed.")
        return 2

    _isolate_stores()
    from aughor.actions.inbox import list_proposals
    from aughor.agent.converse_tools import converse

    corpus = [json.loads(l) for l in
              (Path(__file__).parent.parent / "evals" / "authoring_asks.jsonl")
              .read_text().splitlines() if l.strip()]
    out_path = Path(__file__).parent.parent / "evals" / "authoring" / "recorded.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    records = []
    for row in corpus:
        seen = {p.id for p in list_proposals(args.connection)}
        result = converse(args.connection, row["ask"])
        staged = [p.model_dump() for p in list_proposals(args.connection)
                  if p.id not in seen]
        records.append({
            "id": row["id"], "family": row["family"], "ask": row["ask"],
            "steps": [{"tool": s.tool, "ok": s.ok} for s in result.steps],
            "staged": staged,
            "answer": result.answer or "",
        })
        print(f"{row['id']}: {len(result.steps)} step(s), {len(staged)} staged")

    out_path.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    print(f"recorded {len(records)} asks → {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
