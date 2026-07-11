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


def injection_for_question(
    question: str,
    connection_id: str,
    schema: str = "",
    business_model: str = "",
    currency_code: str = "",
    packs: Optional[list[Pack]] = None,
) -> Optional[PackInjection]:
    """Resolve the steering payload for this question, or None when nothing should steer
    (flag off · no matching active pack · the pack is not DEPLOYED on this connection).

    Safety: steering requires a human-confirmed PINNED binding (load_binding). Auto-proposals
    from the resolver are for the deploy/review UI only — they can be wrong on real schemas, so
    a live run never steers off an unconfirmed guess. Deploy a pack (propose → confirm → pin)
    before it can sharpen a run."""
    if not flag_enabled("specialist_packs"):
        return None
    pool = packs if packs is not None else active_packs()
    # agents.user_defined — an active user-agent with EXPLICIT pack bindings
    # restricts selection to its packs (a preference, not a safety bypass: the
    # pinned-binding deploy gate below applies unchanged). No agent, or an agent
    # without pack bindings → the pool is untouched.
    try:
        from aughor.user_agents.context import agent_pack_ids
        _agent_packs = agent_pack_ids()
        if _agent_packs:
            pool = [p for p in pool if p.id in set(_agent_packs)]
    except Exception as e:
        from aughor.kernel.errors import tolerate
        tolerate(e, "agent pack-preference is advisory; full pool proceeds",
                 counter="packs.agent_pool")
    if not pool:
        return None
    hit = select_pack(question, pool)
    if not hit:
        return None
    pack, _score = hit

    pinned = load_binding(pack.id, connection_id, schema) if connection_id else None
    if not pinned or not pinned.get("bindings"):
        return None                        # not deployed here — don't steer off a guess

    return build_injection(pack, binding=pinned["bindings"], business_model=business_model,
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
