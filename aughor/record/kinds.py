"""Decision kinds — the kinds of decision an organisation declares (the decision-framework study §3.1 and §8 step 4,
`docs/DECISION_FRAMEWORK_STUDY_2026-10-26.md`).

A kind — a price change, a supplier switch, a budget move — declares who must approve one, whether it must say what
it expects, how long until it is reviewed, the authority ceiling for any action it runs, and the metrics it usually
moves. Packs may ship defaults; a person confirms them. Two things then become possible that were not:

1. **A decision of a declared kind keeps its kind's rules at the door**: refused without an expectation when its
   kind requires one, its approvers and review date defaulted from its kind, the kind kept on the decision.
2. **Past decisions of the same kind are its base rate**: method 4 (`record/scenario.intervention`) reads the
   decisions of this kind rather than guessing "the same kind" from a question's words, and the platform can
   *propose* a decision of a declared kind under a mission (:func:`proposals_for`) with what each option is
   predicted to do — composed by code from the kind, the mission and the Record, never by a model.

Laws, at the door, as for missions: **people declare kinds; a model never does** (an agent or the system as author is
refused); a kind is superseded, never deleted — retiring one keeps every decision that named it readable. Kernel
artifact kind ``decision_kind`` — no new store.
"""
from __future__ import annotations

import re
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

KIND = "decision_kind"
#: The days a kind's decisions are reviewed after, when it says nothing else — the review's own default.
DEFAULT_REVIEW_DAYS = 30
STATES: tuple[str, ...] = ("active", "retired")


class KindRefused(ValueError):
    """A kind, or a decision of one, that the door will not keep — the message says what would have been needed."""


class DecisionKind(BaseModel):
    name: str                                       # "a price change", in the organisation's words
    description: str = ""
    approvers: list[str] = Field(default_factory=list)   # who must approve one: person:<name> or a group's name
    expectation_required: bool = False              # a decision of this kind must say what it expects
    review_days: int = DEFAULT_REVIEW_DAYS          # reviewed this many days after, plus the settling lag
    authority_ceiling: Optional[int] = None         # L0–L5 for any action a decision of this kind runs
    metrics: list[str] = Field(default_factory=list)     # the metrics it usually moves
    state: Literal["active", "retired"] = "active"
    declared_by: str = ""
    extra: dict[str, Any] = Field(default_factory=dict)
    # read-only, filled by the ledger
    id: str = ""
    key: str = ""
    version: int = 0
    recorded_at: str = ""
    superseded_by: str = ""


def _ledger():
    from aughor.kernel.ledger import Ledger
    return Ledger.default()


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (name or "").strip().lower()).strip("_")[:60]


def kind_key(name: str) -> str:
    return f"{KIND}:{slug(name)}"


def _is_person(by: str, by_kind: str) -> bool:
    who = (by or "").strip()
    return by_kind == "person" and bool(who) and not who.startswith(("agent:", "system", "monitor:", "automation:"))


def _from(art: Optional[dict]) -> Optional[DecisionKind]:
    if not art:
        return None
    k = DecisionKind.model_validate(dict(art.get("payload") or {}))
    k.id = str(art.get("id") or "")
    k.key = str(art.get("natural_key") or "")
    k.version = int(art.get("version") or 0)
    k.recorded_at = str(art.get("created_at") or "")
    k.superseded_by = str(art.get("superseded_by") or "")
    return k


def write_kind(k: DecisionKind, *, by: str, by_kind: str = "person") -> DecisionKind:
    """A person declares a kind (or edits one: a new version under the same name, the old kept). Refuses one written
    by an agent or the system, one with no name, a review the loop cannot keep, or a ceiling off the ladder."""
    if not _is_person(by, by_kind):
        raise KindRefused("people declare kinds of decision; a model never does — the author is a person, named")
    if not slug(k.name):
        raise KindRefused("a kind of decision has a name")
    if not 1 <= int(k.review_days) <= 366:
        raise KindRefused("a kind's decisions are reviewed between 1 and 366 days after")
    if k.authority_ceiling is not None and not 0 <= int(k.authority_ceiling) <= 5:
        raise KindRefused("a kind's authority ceiling is a level L0–L5")
    if k.state not in STATES:
        raise KindRefused(f"a kind's state is one of {', '.join(STATES)}")
    k.declared_by = by.strip()
    data = k.model_dump()
    for read_only in ("id", "key", "version", "recorded_at", "superseded_by"):
        data.pop(read_only, None)
    data["metrics"] = sorted({m.strip() for m in k.metrics if m and m.strip()})
    aid = _ledger().artifact_write(KIND, kind_key(k.name), data)
    return _from(_ledger().artifact_by_id(aid)) or k


def get_kind(ref: str) -> Optional[DecisionKind]:
    """A kind by its key (``decision_kind:price_change``), its id, or its name — as it stands now."""
    ref = (ref or "").strip()
    if not ref:
        return None
    key = ref if ref.startswith(f"{KIND}:") else kind_key(ref)
    got = _from(_ledger().artifact_latest(key))
    if got is None:
        art = _ledger().artifact_by_id(ref)
        got = _from(art) if art and art.get("kind") == KIND else None
        if got is not None and got.superseded_by:
            got = _from(_ledger().artifact_latest(got.key)) or got
    return got


def list_kinds(*, state: Optional[str] = None) -> list[DecisionKind]:
    out = [k for k in (_from(a) for a in _ledger().artifacts_of_kind(KIND, limit=500)) if k is not None]
    out = [k for k in out if not k.superseded_by]
    return [k for k in out if state is None or k.state == state]


def rules_for(ref: str, *, expectation: Optional[dict], approvers: Optional[list[str]]) -> tuple[DecisionKind, list[str]]:
    """The kind a decision is declared as, and its approvers: refused when the kind is not declared or retired, or when
    it requires an expectation and none was named; the kind's approvers when the decision named none."""
    k = get_kind(ref)
    if k is None:
        raise KindRefused(f"no kind of decision named {ref!r} is declared — a person declares it first")
    if k.state != "active":
        raise KindRefused(f"{k.name} is retired as a kind of decision; declare the decision without it, or as its successor")
    if k.expectation_required and not (expectation or {}).get("metric"):
        raise KindRefused(f"a decision of the kind {k.name} says what it expects — name the metric it should move")
    return k, list(approvers or []) or list(k.approvers)


# ── the proposal (reading B): a decision of a declared kind under a mission, composed by code ──────────────────────

def proposals_for(mission, *, report: Optional[dict] = None) -> list[dict]:
    """What the platform proposes under an active mission: one decision per declared kind that usually moves the
    mission's objective metric — its options (the kind, and not acting), what each is predicted to do, and what a
    person would book. Predictions come from the Record only: not acting is the objective's own history as the
    mission's report measured it; acting is method 4 over past decisions of this kind, or "too few cases", said.
    A model writes none of it; a person decides, through the declare door, with the kind's rules."""
    from aughor.record import scenario as S
    obj = mission.objective
    want = (obj.metric or "").strip().lower()
    names = {want, str((obj.spec or {}).get("metric_name") or "").strip().lower(),
             str((obj.spec or {}).get("metric_label") or "").strip().lower()} - {""}
    conn = mission.scope.connections[0] if mission.scope.connections else ""
    base = (report or {}).get("objective") or {}
    out: list[dict] = []
    for k in list_kinds(state="active"):
        if not names & {m.strip().lower() for m in k.metrics}:
            continue
        p = S.intervention(metric=obj.metric, connection_id=conn, kind=k.key)
        act = ({"method": "intervention", "effect_low": p.low, "effect_high": p.high, "effect": p.value,
                "says": " · ".join(p.must_say)} if p.value is not None
               else {"method": "intervention", "says": p.note or "no past decision of this kind has a measured outcome"})
        hold = ({"method": "history", "low": base.get("baseline_low"), "high": base.get("baseline_high"),
                 "value": base.get("baseline"), "says": str(base.get("baseline_note") or "")}
                if base.get("baseline") is not None else
                {"method": "history", "says": str(base.get("note") or base.get("baseline_note")
                                                  or "the objective's history was not measured this period")})
        out.append({
            "kind": k.key, "kind_name": k.name, "mission": mission.id,
            "question": f"{k.name} toward “{mission.name}”?",
            "options": [{"option": k.name, "predicted": act}, {"option": "not act", "predicted": hold}],
            "approvers": list(k.approvers), "expectation_required": k.expectation_required,
            "expectation": {"metric": obj.metric, "direction": obj.direction or ""},
            "review_days": k.review_days, "connection_id": conn,
            "composed_by": "code, from the declared kind, the mission and the Record — no model",
        })
    return out
