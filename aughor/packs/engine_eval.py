"""Engine adapter for the eval runner (Bet 2, live half).

run_pack_evals needs an `ask_fn(question) -> meta` that runs a golden question THROUGH the
engine; this builds it. We run the explore PLANNER (decompose_exploration) for each question —
cheap relative to a full run, and enough to score the structural expectations that matter
(did it decompose? at what grain? did it engage the expert's recipe?). `extract_plan_meta` is
pure/testable; make_ask_fn is the live wiring. Deeper answer-text checks (must_not on the final
narrative) would need a full run — a later depth knob.
"""
from __future__ import annotations

from typing import Callable, Optional

from aughor.packs.models import Pack

_PERIOD_KW = ("month", "quarter", "week", "monthly", "quarterly", "over time", "trend")


def extract_plan_meta(plan_out: dict, pack: Pack) -> dict:
    """Derive eval metadata from a decompose_exploration result. Pure."""
    subqs = plan_out.get("sub_questions", []) or []
    text = " ".join(getattr(sq, "question", "") for sq in subqs).lower()
    grain = "cohort" if "cohort" in text else ("period" if any(k in text for k in _PERIOD_KW) else "")
    used: list[str] = []
    for m in pack.metrics:
        for name in [m.name, *m.aliases]:
            if name and name.lower() in text:
                used.append(m.name)
                break
    steered = [c.split(":", 1)[1] for c in plan_out.get("verification_checks", [])
               if isinstance(c, str) and c.startswith("specialist:")]
    return {
        "recipe_used": used,
        "grain": grain,
        "ran_decomposition": len(subqs) >= 3,
        "text": text,
        "steered_by": steered,
    }


def make_ask_fn(connection_id: str, schema: Optional[str], pack: Pack) -> Callable[[str], dict]:
    """Build the live ask_fn: run the explore planner for a question against the connection and
    return its plan metadata. Raises only if the connection can't be opened (caller handles)."""
    from aughor.routers.connections import open_connection_for
    from aughor.tools.schema import build_schema_context
    from aughor.agent import explore as EX

    conn = open_connection_for(connection_id)
    raw = getattr(conn, "raw", None) or getattr(conn, "_conn", None) or conn
    ctx = build_schema_context(raw, schema_name=schema, connection_id=connection_id)

    # Force the pack to steer during evaluation (pre-activation check) — independent of the
    # global flag / active status — using its pinned binding when present.
    pre_block = ""
    try:
        from aughor.packs.bindings import load_binding
        from aughor.packs.inject import build_injection
        from aughor.packs.intake import render_injection
        b = load_binding(pack.id, connection_id)
        binding = b.get("bindings") if b else None
        if binding:
            pre_block = render_injection(build_injection(pack, binding=binding))
    except Exception:
        pre_block = ""

    def ask(question: str) -> dict:
        state = {"question": question, "schema_context": ctx, "scan_context": "",
                 "connection_id": connection_id, "scope_schema": schema or "",
                 "_pack_injection_block": pre_block, "_pack_id": pack.id}
        out = EX.decompose_exploration(state)
        return extract_plan_meta(out, pack)

    return ask
