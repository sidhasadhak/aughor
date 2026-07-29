"""Wave H4 — hire an analyst from a Domain Expertise Pack.

A pack already carries what a persona is made of: a stance (`expertise.md`), a role
description (`pack.yaml::persona`), the questions the domain actually asks, and the metric
recipes with their anti-patterns. Creating an agent from one is a projection, not an import
— nothing is copied into a second store, and the pack stays the authority for its own
content (the agent binds it by id via ``pack_ids``).

**What this deliberately does NOT do, and why it matters.** The wave scoped H4 as "the
pack's question/eval YAML seeded as goldens, so a template agent is born measured". Measuring
the premise first showed that is not possible and should not be faked:

* ``user_agent_goldens.reference_sql`` is ``NOT NULL`` — a golden is ground truth, and
  :mod:`aughor.user_agents.quality` grades by EXECUTING it and comparing result sets.
* A pack's ``evals/*.yaml`` carry behavioural expectations (``uses_recipe``, ``grain``,
  ``must_not``) — no SQL. Its ``metrics/*.yaml`` carry a prose formula with ``{{role.*}}``
  placeholders and a ``binds.required`` list — not executable, and only resolvable against a
  specific connection.
* The one way to manufacture the missing SQL would be to generate it with the same model the
  golden exists to grade. A suite the model wrote for itself measures nothing, and a pass
  chip standing on it is worse than no chip: it reads as evidence.

So the questions come back as **suggestions that name what they still need**, and the agent
is born with a stance rather than a score. Same discipline as the S4 digest: report what is
measurable, name what is not, and say what would make it so.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

#: Why a suggested question is not yet a golden. One sentence, shown verbatim in the UI —
#: a caller that renders "0 goldens" without it has told the user nothing actionable.
NEEDS_REFERENCE_SQL = (
    "needs reference SQL for this connection before it can be measured — "
    "a golden is graded by executing it, and the pack cannot know your schema"
)


def _packs_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "packs"


def compose_instructions(persona: str, expertise: str) -> str:
    """The agent's pinned instructions: the pack's role line, then its reasoning stance.

    Both are prose written for a model to read, which is what ``instructions`` already is —
    so this is a concatenation, not a translation. Capped at the column's limit, cutting the
    stance rather than the role (a truncated role would lose who the agent is; a truncated
    stance loses the tail of how it thinks, which degrades more gracefully).
    """
    from aughor.user_agents.models import INSTRUCTIONS_MAX

    role = " ".join((persona or "").split())
    stance = (expertise or "").strip()
    # Drop a leading H1: it titles the DOCUMENT ("# Customer Analytics — reasoning stance")
    # and instructs nothing, so it is noise to the model and to anyone reading the persona
    # card. Sub-headings stay — those organise the guidance itself.
    if stance.startswith("# "):
        stance = stance.split("\n", 1)[1].strip() if "\n" in stance else ""
    if not stance:
        return role[:INSTRUCTIONS_MAX]
    head = f"{role}\n\n" if role else ""
    return (head + stance)[:INSTRUCTIONS_MAX]


def template_from_pack(pack) -> dict:
    """Project a loaded :class:`~aughor.packs.models.Pack` into an agent template."""
    m = pack.manifest
    questions = list(pack.questions.canonical) + list(pack.questions.diagnostic)
    return {
        "pack_id": pack.id,
        "name": m.name,
        "persona": " ".join((m.persona or "").split()),
        "domains": list(m.domains or []),
        "status": m.status,
        "instructions": compose_instructions(m.persona, pack.expertise),
        # Suggestions, not goldens. Each says what it still needs — see the module docstring.
        "suggested_goldens": [{"question": q, "needs": NEEDS_REFERENCE_SQL} for q in questions],
        "metric_recipes": [mt.name for mt in pack.metrics],
    }


def list_templates() -> list[dict]:
    """Every pack under ``packs/``, projected. A pack that fails to load is skipped with a
    log line rather than breaking the list — one malformed pack must not hide the others."""
    from aughor.packs.loader import list_packs, load_pack

    root = _packs_dir()
    if not root.is_dir():
        return []
    out: list[dict] = []
    for pid in list_packs(root):
        try:
            out.append(template_from_pack(load_pack(root / pid)))
        except Exception:
            logger.warning("pack %s could not be loaded as an agent template", pid, exc_info=True)
    return out


def get_template(pack_id: str) -> Optional[dict]:
    from aughor.packs.loader import load_pack

    pack_dir = _packs_dir() / pack_id
    if not (pack_dir / "pack.yaml").is_file():
        return None
    try:
        return template_from_pack(load_pack(pack_dir))
    except Exception:
        logger.warning("pack %s could not be loaded as an agent template", pack_id, exc_info=True)
        return None


def create_from_template(pack_id: str, *, name: str = "", connection_id: str = "",
                         schema_scope: str = "") -> Optional[dict]:
    """Create a UserAgent from a pack. Returns ``{agent, suggested_goldens}`` or None.

    The pack is BOUND (``pack_ids``), not absorbed: its recipes and anti-patterns keep
    steering from the pack itself, so improving the pack improves every agent hired from it.
    No goldens are written — see the module docstring — and the suggestions ride back on the
    response so the creator is asked for the reference SQL while they still have the context.
    """
    tpl = get_template(pack_id)
    if tpl is None:
        return None
    from aughor.user_agents import create_agent

    agent = create_agent(
        name=name.strip() or tpl["name"],
        instructions=tpl["instructions"],
        connection_id=connection_id,
        schema_scope=schema_scope,
        pack_ids=[pack_id],
    )
    return {"agent": agent.model_dump(), "suggested_goldens": tpl["suggested_goldens"]}
