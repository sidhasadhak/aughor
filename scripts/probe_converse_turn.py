"""One LIVE converse turn through the real `/ask` route — Wave 5's last receipt.

Everything else about the converse body is proven offline against the faux backend. That
proves the shapes faux can emit and nothing else: the `(completion, None)` pass-through bug
found earlier today passed twenty offline tests while metering every live turn as zero
tokens. So the flag's definition of done asks for one real turn, and this is it.

    uv run python scripts/probe_converse_turn.py

Costs a handful of provider requests (a converse turn is several: one per loop step plus the
answering turn). Prints the RESOLVED BINDING FIRST — `data/llm_config.json` outranks
AUGHOR_BACKEND, so an env var does not make this a dry run.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")          # a bare script does not load .env; without it we 401
except ImportError:
    print("! python-dotenv not importable; relying on the ambient environment")

CONN = os.environ.get("AUGHOR_PROBE_CONN", "8d36d4c2")     # Superstore demo
QUESTION = os.environ.get("AUGHOR_PROBE_Q", "How many orders are there in total?")


def main() -> int:
    os.environ["AUGHOR_ASK_CONVERSE"] = "1"                # the whole point

    from aughor.llm.provider import get_provider
    p = get_provider("coder")
    print(f"binding   : backend={p.backend!r} model={p._model!r}")
    if p.backend == "faux":
        print("VERDICT: backend is 'faux' — this proves nothing. Point the stored config at "
              "a real provider and re-run.")
        return 2

    from fastapi.testclient import TestClient

    from aughor.api import app
    from aughor.routers.investigations import _converse_eligible

    # Fail fast if the door would not route here anyway — otherwise a green run below
    # would be the QUICK body answering and we would have proven nothing about converse.
    from types import SimpleNamespace
    eligible = _converse_eligible(
        SimpleNamespace(escalate=False, insight_id=None, seed_sql=None),
        SimpleNamespace(depth="quick"))
    print(f"eligible  : {eligible}")
    if not eligible:
        print("VERDICT: the route would NOT pick converse — the flag or the predicate is "
              "not what this probe assumes. Nothing was spent.")
        return 2

    frames: list[tuple[str, dict]] = []
    with TestClient(app) as client:
        with client.stream("POST", "/ask", json={
            # /ask takes `depth`, not `mode` — "quick" is the tier converse is a peer of.
            "connection_id": CONN, "question": QUESTION, "depth": "quick",
        }) as r:
            if r.status_code != 200:
                print(f"VERDICT: /ask returned {r.status_code} — {r.read()[:300]!r}")
                return 3
            for line in r.iter_lines():
                if line and line.startswith("data:"):
                    try:
                        payload = json.loads(line[5:].strip())
                    except Exception:
                        continue
                    frames.append((payload.get("type"), payload))

    types = [t for t, _ in frames]
    print(f"\nframes    : {len(frames)}")
    print(f"sequence  : {' → '.join(types)}")

    steps = [p for t, p in frames if t == "converse_step"]
    headline = next((p.get("headline") for t, p in frames if t == "headline"), None)
    receipts = [p for t, p in frames if t == "guard_receipt"]

    print(f"tool steps: {len(steps)}" + (f" — {[s.get('tool') for s in steps]}" if steps else ""))
    print(f"receipts  : {len(receipts)}")
    print(f"headline  : {headline!r}")

    if "converse_step" not in types:
        print("\nVERDICT (?): no converse_step frame — the QUICK body may have answered. "
              "This did not exercise the conversation.")
        return 1
    if not headline:
        print("\nVERDICT: converse ran but produced no headline — the turn reached no answer.")
        return 1
    print("\nVERDICT: PASS. /ask served a live conversation: the model chose tools, the "
          "guarded pipeline ran beneath them, and the turn closed with a real answer.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
