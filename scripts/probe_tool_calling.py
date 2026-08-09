"""One live call that answers: does `complete_with_tools` work against a real backend?

`complete_with_tools` passes `response_model=None` through instructor. That is faux-proven
and is instructor's documented pass-through, but no real provider has confirmed it. This
spends exactly ONE request to find out.

    python scripts/probe_tool_calling.py

The point of the script rather than a one-liner is that FOUR different things can fail here
and three of them look alike from a traceback:

  1. instructor rejects `response_model=None`          → the design is wrong, rework needed
  2. the model does not support tool calling at all    → change the model, code is fine
  3. the model supports tools but ignored them         → prompt/model quality, code is fine
  4. the tool-call wire shape differs from faux's      → parser needs a real-world case

Only (1) and (4) are code problems. Read the verdict, not the traceback.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# A bare script does NOT load .env — the API does. Without this the call 401s, and it
# does so SILENTLY enough to look like a tool-calling failure.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except ImportError:
    print("! python-dotenv not importable; relying on the ambient environment")

WEATHER_TOOL = [{
    "type": "function",
    "function": {
        "name": "get_row_count",
        "description": "Return the number of rows in a named table. Call this when asked "
                       "how many rows a table has — do not guess.",
        "parameters": {
            "type": "object",
            "properties": {"table": {"type": "string", "description": "The table name."}},
            "required": ["table"],
        },
    },
}]


def main() -> int:
    from aughor.llm.provider import get_provider

    provider = get_provider("coder")
    print(f"binding      : backend={provider.backend!r} model={provider._model!r} "
          f"role={provider.role!r}")
    # ⚠️ `data/llm_config.json` OUTRANKS the AUGHOR_BACKEND env var — setting the env var
    # does NOT make this a dry run, and assuming it does spends a real request. The line
    # above is the authority on what this call will hit; read it before continuing.
    if os.getenv("AUGHOR_BACKEND") and os.getenv("AUGHOR_BACKEND") != provider.backend:
        print(f"! AUGHOR_BACKEND={os.getenv('AUGHOR_BACKEND')!r} was IGNORED — the stored "
              f"config in data/llm_config.json won. This call hits {provider.backend!r}.")
    if not os.getenv("AUGHOR_SECRET_KEY"):
        print("! AUGHOR_SECRET_KEY is unset — if this backend needs it, the call 401s")
    if provider.backend == "faux":
        print("VERDICT: backend is 'faux' — this proves nothing. Point AUGHOR_BACKEND at a "
              "real provider and re-run.")
        return 2
    if provider.backend == "anthropic":
        print("VERDICT: complete_with_tools does not support the anthropic binding "
              "(it speaks client.messages). Probe an OpenAI-compatible backend.")
        return 2

    print("calling      : one request, one tool offered ...")
    try:
        turn = provider.complete_with_tools(
            "You answer questions about a data warehouse.",
            "How many rows are in the orders table?",
            WEATHER_TOOL,
            temperature=0.0,          # pinned: a probe must be reproducible
        )
    except TypeError as exc:
        print(f"\nRAW ERROR    : {type(exc).__name__}: {exc}")
        print("VERDICT (1)  : instructor rejected the call shape — most likely "
              "`response_model=None` is NOT a pass-through on this instructor version. "
              "This IS a code problem: complete_with_tools needs a different seam.")
        return 1
    except Exception as exc:
        text = str(exc).lower()
        if "tool" in text and ("support" in text or "not supported" in text or "invalid" in text):
            print(f"\nRAW ERROR    : {type(exc).__name__}: {exc}")
            print("VERDICT (2)  : the MODEL does not support tool calling. The code is "
                  "fine — pick a tool-capable model and re-run. (On OpenRouter free tier, "
                  "not every ':free' model supports tools.)")
            return 2
        print(f"\nRAW ERROR    : {type(exc).__name__}: {exc}")
        print("VERDICT (?)  : neither a call-shape rejection nor an obvious "
              "tool-unsupported error. Read the message above before concluding "
              "anything — a 401/429 here is a credential or quota problem, not a "
              "tool-calling result.")
        return 3

    print(f"\nToolTurn     : chose_tool={turn.chose_tool} "
          f"malformed={turn.malformed!r}")
    if turn.chose_tool:
        print(f"tool name    : {turn.tool_call.name!r}")
        print(f"arguments    : {turn.tool_call.arguments!r}")
        if turn.tool_call.name == "get_row_count":
            print("\nVERDICT: PASS. instructor passed through, the tools array reached the "
                  "model, it chose the offered tool, and the wire shape parsed exactly as "
                  "faux scripts it. complete_with_tools is live-verified.")
            return 0
        print("\nVERDICT (4): a tool was called but not the one offered — check the parser "
              "against this shape.")
        return 1
    if turn.malformed:
        print("\nVERDICT (4): the model chose a tool and the arguments did not parse. The "
              "pass-through WORKS (that is the important half); the real-world argument "
              "shape needs a look.")
        return 1
    print(f"text         : {turn.text!r}")
    if turn.text:
        print("\nVERDICT (3): the call succeeded and instructor passed through — so the "
              "code path is confirmed — but the model answered in prose instead of using "
              "the tool. A model/prompt quality signal, NOT a defect.")
        return 0
    # NEITHER a tool call NOR text. This is not "answered in prose" — it is an EMPTY turn,
    # and calling it prose is how a parser gap gets recorded as a model preference.
    print("\nVERDICT (4): instructor passed through (no exception, so the seam WORKS) but "
          "the turn came back EMPTY — no tool call and no text. Most likely the parser is "
          "not reading this backend's shape: reasoning models often leave `content` null "
          "and put the reply on `reasoning`/`reasoning_content`. Raw dump below.")
    print("             The transport logs the message SHAPE at WARNING level for exactly "
          "this case — re-run with `-W` visible logging to see which field carried the "
          "reply (look for 'could not read'). That names the parser gap.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
