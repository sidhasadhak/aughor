"""Intake injection — where a specialist actually steers a live run (flag-gated).

This is the one engine touch-point: at decomposition, if the `specialist_packs` flag is on and
an ACTIVE pack matches the question AND grounds on the connection, its persona + recipes +
diagnostics + grain are rendered into the planner's context. Off by default → zero behavior
change. The executors and SQL guards still run identically; the pack only sharpens the plan.
Best-effort throughout: any failure returns None / "" so a normal run never breaks.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from aughor.kernel.flags import flag_enabled
from aughor.packs.loader import load_pack, list_packs
from aughor.packs.models import Pack
from aughor.packs.routing import select_pack
from aughor.packs.adapter import schema_facts_from_table_cols
from aughor.packs.resolver import binding_report, BindingCandidate
from aughor.packs.bindings import load_binding
from aughor.packs.inject import build_injection, PackInjection

_PACKS_DIR = Path(__file__).resolve().parents[2] / "packs"


def active_packs(packs_dir=None) -> list[Pack]:
    """Loadable, status==active packs under the packs dir (best-effort)."""
    base = Path(packs_dir or _PACKS_DIR)
    out: list[Pack] = []
    for pid in list_packs(base):
        try:
            p = load_pack(base / pid)
        except Exception as e:
            from aughor.kernel.errors import tolerate
            tolerate(e, f"skip pack {pid} during active scan", counter="packs.active_scan")
            continue
        if p.manifest.status == "active":
            out.append(p)
    return out


def _cand_to_binding(c: BindingCandidate) -> dict:
    return {"table": c.table, "column": c.column, "value": c.value, "confidence": c.confidence}


def injection_for_question(
    question: str,
    connection_id: str,
    table_cols: dict,
    business_model: str = "",
    currency_code: str = "",
    packs: Optional[list[Pack]] = None,
) -> Optional[PackInjection]:
    """Resolve the steering payload for this question, or None when nothing should steer
    (flag off · no matching active pack · the pack can't ground on this warehouse). A pinned
    binding wins; otherwise the resolver proposes one on the fly and we steer only if it's
    fully bound — never inject a half-ground recipe."""
    if not flag_enabled("specialist_packs"):
        return None
    pool = packs if packs is not None else active_packs()
    if not pool:
        return None
    hit = select_pack(question, pool)
    if not hit:
        return None
    pack, _score = hit

    binding: Optional[dict] = None
    pinned = load_binding(pack.id, connection_id) if connection_id else None
    if pinned and pinned.get("bindings"):
        binding = pinned["bindings"]
    else:
        rep = binding_report(pack.entities, schema_facts_from_table_cols(table_cols, business_model))
        if not rep["fully_bound"]:
            return None
        binding = {role: _cand_to_binding(c) for role, c in rep["proposals"].items()}

    return build_injection(pack, binding=binding, business_model=business_model,
                           currency_code=currency_code)


def render_injection(inj: PackInjection) -> str:
    """Render the injection as a prompt block prepended to the planner's context."""
    lines = [f"SPECIALIST CONTEXT — the '{inj.pack_id}' expert owns this question. Reason in its "
             f"stance and prefer its grounded recipes over generic aggregates.",
             f"Default temporal grain: {inj.default_temporal_grain}."]
    if inj.persona.strip():
        lines.append("\nEXPERT STANCE:\n" + inj.persona.strip())
    if inj.metrics:
        lines.append("\nGROUNDED METRIC RECIPES (use these exact definitions):")
        for m in inj.metrics:
            lines.append(f"- {m['name']}: {m.get('formula','').strip()}"
                         + (f"\n    grain: {m['grain'].strip()}" if m.get('grain') else ""))
    if inj.diagnostics:
        lines.append("\nDIAGNOSTIC QUESTIONS this expert always asks:\n"
                     + "\n".join(f"- {d}" for d in inj.diagnostics))
    return "\n".join(lines) + "\n\n"
