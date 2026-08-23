"""Move a pack between `draft`, `active` and `deprecated` — the rung that was missing.

`status` was read in four places (`routing.select_pack`, `intake.active_packs`, the packs
router's response) and **written in none**. Import lands a pack at `draft` and the
ingester's own contract says "nothing imported reaches a prompt until someone promotes
it" — but there was no way to promote it. Hand-editing `pack.yaml` was the entire
mechanism, which is not a review path, leaves no record of who decided, and is invisible
to anything that would want to ask.

Three decisions shape this file:

**Activation is where the lint belongs, not import.** Import is a copy onto disk; a draft
pack steers nothing and is read by nobody. Activation is the moment third-party prose
becomes reachable from a prompt, so that is the door worth guarding — and it guards
hand-placed packs too, which never passed the importer at all. A pack whose prose BLOCKS
cannot be activated, and the finding says why.

**The record ships with the act.** Who promoted what, and when, lands on the journal in
the same call. An entitlement nobody can review is indistinguishable from no policy, and
that lesson has already been paid for here once.

**A prose pack and a grounded pack do not share a gate.** `evalgate.evaluate_activation`
(Bet 2) demands a pinned+verified binding covering every role, declared evals, and a clean
pass — and an imported skill can satisfy none of the three: it has no roles, no evals and
nothing to run. That gate is right for a pack that STEERS A PLAN and meaningless for one
that can only be READ, whose risk is prompt content rather than wrong SQL. So the fork is
explicit: a `partial` pack is gated by the lint, a grounded one by its evals, and this
function refuses to activate a grounded pack without the gate's verdict rather than
quietly becoming a way around Bet 2. ⚠️ That verdict was already being COMPUTED — by
`POST /packs/{id}/evaluate` — and thrown away, because nothing anywhere wrote `status`.

**Only `status` is rewritten.** The manifest is re-dumped from the raw YAML mapping, not
from the parsed model — a round trip through `PackManifest` would silently drop any key
the model does not declare, and provenance (`source_url`, `licence`) is exactly the kind
of key that gets added later and must survive a promotion made before that day.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import yaml

from aughor.packs.loader import PROSE_FILE, PacksError, load_pack
from aughor.packs.models import Pack

logger = logging.getLogger(__name__)

#: The full vocabulary. `deprecated` is not a delete: a pack that steered real answers
#: should stop steering without its history becoming unreadable.
STATUSES = ("draft", "active", "deprecated")


class PromotionRefused(Exception):
    """Activation was refused. Carries the findings so a caller can show them."""

    def __init__(self, message: str, findings: Optional[list] = None):
        super().__init__(message)
        self.findings = findings or []


def _packs_dir(packs_dir=None) -> Path:
    if packs_dir is not None:
        return Path(packs_dir)
    from aughor.packs.intake import packs_root
    return packs_root()


def lint_pack_prose(root: Path) -> list:
    """Run the skill import gate over a pack's prose. No prose → nothing to refuse.

    Deliberately the SAME linter the importer uses. Two copies of "is this prose safe to
    put in front of a model" drift into two answers for one file, and the one that ends up
    guarding the prompt would be whichever was edited last.
    """
    from aughor.skills.lint import lint_skill

    prose = root / PROSE_FILE
    if not prose.is_file():
        return []
    return lint_skill(prose.read_text(), name=root.name)


def set_status(pack_id: str, status: str, *, packs_dir=None, actor: str = "",
               gate_decision=None) -> Pack:
    """Set a pack's status. Returns the reloaded pack.

    ``gate_decision`` is an :class:`~aughor.packs.evalgate.ActivationDecision` and is
    REQUIRED to activate a grounded (non-``partial``) pack — that is Bet 2's gate, and it
    needs a connection to produce, so it is computed by the caller that has one.

    Raises ``ValueError`` for an unknown status, ``PacksError`` for an unknown pack, and
    ``PromotionRefused`` when activation would put blocked prose in front of a model or
    would promote a grounded pack its own evals have not cleared.
    """
    if status not in STATUSES:
        raise ValueError(f"unknown status '{status}' — one of {', '.join(STATUSES)}")

    base = _packs_dir(packs_dir)
    root = base / pack_id
    manifest_file = root / "pack.yaml"
    # The slug reaches here from a route parameter; assert containment locally rather than
    # trusting whatever validated it upstream.
    if root.parent.resolve() != base.resolve() or not manifest_file.is_file():
        raise PacksError(f"no pack '{pack_id}' under {base}")

    if status == "active":
        findings = lint_pack_prose(root)
        from aughor.skills.lint import blocks
        refused = blocks(findings)
        if refused:
            raise PromotionRefused(
                f"'{pack_id}' cannot be activated: "
                + "; ".join(f"{f.rule} (line {f.line})" for f in refused),
                findings=findings)

        # Demotion is never gated — taking something out of service must not require
        # passing a test. Only this direction asks anything.
        if not load_pack(root).manifest.partial:
            if gate_decision is None:
                raise PromotionRefused(
                    f"'{pack_id}' declares entities or metrics, so it steers plans and its "
                    f"evals decide activation. Run POST /packs/{pack_id}/evaluate against a "
                    f"connection and activate through that verdict.")
            if not getattr(gate_decision, "can_activate", False):
                raise PromotionRefused(
                    f"'{pack_id}' was refused by its own evals: "
                    + "; ".join(getattr(gate_decision, "reasons", []) or ["no reason given"]))

    with manifest_file.open() as f:
        raw = yaml.safe_load(f) or {}
    if not isinstance(raw, dict):
        raise PacksError(f"{manifest_file.name} must be a YAML mapping")
    before = str(raw.get("status", "draft"))
    raw["status"] = status
    manifest_file.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True))

    _journal(pack_id, before, status, actor, raw)
    return load_pack(root)


def _journal(pack_id: str, before: str, after: str, actor: str, raw: dict) -> None:
    """Record the decision. Best-effort: a journal that cannot be written must not undo a
    status change that already landed on disk — the file is the authority, this is the
    trail, and a half-applied promotion would be worse than an unrecorded one."""
    try:
        from aughor.kernel.ledger import Ledger
        Ledger.default().emit("pack.status_changed", {
            "pack_id": pack_id,
            "from": before,
            "to": after,
            "actor": actor,
            # The two facts that make the record worth reading later: where the prose came
            # from, and whether the pack it activated actually knows anything about data.
            "source": str(raw.get("source") or ""),
            "source_url": str(raw.get("source_url") or ""),
            "licence": str(raw.get("licence") or ""),
            "partial": bool(raw.get("partial") or False),
        })
    except Exception as exc:
        logger.warning("pack %s status %s→%s was applied but not journalled: %s",
                       pack_id, before, after, exc)
