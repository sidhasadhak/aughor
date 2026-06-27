"""Build the steering metadata a selected pack injects into the engine at intake.

This is the seam where intent meets the (unchanged) engine: the pack contributes a persona,
its metric recipes, the resolved entity bindings, diagnostic sub-questions, the default
temporal grain, explorer angles and playbooks. The executors and SQL guards run identically
with or without it — the pack only *steers*. Template tokens ({{business_model}},
{{currency_code}}, {{role.X}}) are filled from the connection's profile + the binding so the
same persona reads correctly per warehouse. Pure; never raises.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from aughor.packs.models import Pack

_TOKEN = re.compile(r"\{\{\s*([a-z0-9_.]+)\s*\}\}", re.I)


@dataclass
class PackInjection:
    pack_id: str
    persona: str = ""                                  # expertise.md, template-filled
    default_temporal_grain: str = "period"
    metrics: list[dict] = field(default_factory=list)  # recipe dicts (name/formula/grain/anti_patterns)
    bindings: dict = field(default_factory=dict)       # role -> {table,column,value}
    diagnostics: list[str] = field(default_factory=list)
    explorer_angles: list[str] = field(default_factory=list)
    playbooks: list[dict] = field(default_factory=list)


def _fill(text: str, ctx: dict) -> str:
    """Replace {{key}} / {{role.X}} from ctx; leave unknown tokens untouched (never crash)."""
    def sub(m):
        key = m.group(1)
        if key in ctx and ctx[key] is not None:
            return str(ctx[key])
        return m.group(0)
    return _TOKEN.sub(sub, text or "")


def build_injection(
    pack: Pack,
    binding: Optional[dict] = None,
    business_model: str = "",
    currency_code: str = "",
) -> PackInjection:
    """Assemble the steering payload. `binding` is the resolved role→{table,column,value} map
    (from the binding store); its entries also fill `{{role.<name>}}` tokens in the persona and
    metric grain so recipes read against real columns."""
    binding = binding or {}
    ctx = {"business_model": business_model, "currency_code": currency_code}
    for role, b in binding.items():
        # role.cohort_anchor → "dim_customers.signup_ts" (or the value for value-roles)
        if isinstance(b, dict):
            if b.get("column") and b.get("table"):
                ctx[f"role.{role}"] = f"{b['table']}.{b['column']}"
            elif b.get("value"):
                ctx[f"role.{role}"] = b["value"]
            elif b.get("table"):
                ctx[f"role.{role}"] = b["table"]

    metrics = []
    for m in pack.metrics:
        metrics.append({
            "name": m.name,
            "aliases": m.aliases,
            "definition": _fill(m.definition, ctx),
            "formula": _fill(m.formula, ctx),
            "grain": _fill(m.grain, ctx),
            "anti_patterns": m.anti_patterns,
        })

    return PackInjection(
        pack_id=pack.id,
        persona=_fill(pack.expertise, ctx),
        default_temporal_grain=pack.manifest.default_temporal_grain,
        metrics=metrics,
        bindings=binding,
        diagnostics=list(pack.questions.diagnostic),
        explorer_angles=list(pack.questions.explorer_angles),
        playbooks=[p.model_dump() for p in pack.playbooks],
    )
