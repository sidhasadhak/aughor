"""Wave S4 — the weekly digest over Aughor's own exhaust.

Briefs dogfooded: the platform reports on itself using the same delivery path a customer
brief uses, rather than a parallel reporting surface.

**The pre-check reshaped this, and the finding is worth stating up front.** The S scoping
doc listed four sections — volume, abstentions, feedback trend, top curation actions.
Measured on the reference connection before writing any of them:

===================  ====================================================================
volume               ✅ 795 answer receipts, a real daily distribution
usage                ✅ 273 model calls, attributable by feature (G3a)
feedback             ✅ real but TINY — 3 verdicts, 1 correction, in `verify/verdicts.py`
curation queue       ✅ readable, currently 0 staged proposals
**abstentions**      ❌ **no structured field exists — prose only**
===================  ====================================================================

Two of those corrected a wrong assumption of mine mid-check: verdicts are NOT ledger
events (they live in their own store, and looking in the wrong place is the same mistake
G3b's `llm_call` reader made), and the proposal inbox is `kinetic/inbox`, not
`automations/store`.

**Abstentions are reported as NOT COUNTABLE rather than counted from prose.** Three of 795
receipts contain an abstention-shaped phrase, and matching headline text for "abstain" or
"within normal variance" would produce a number that looks authoritative and is a regex
opinion — the wolf-crying Wave N1 caught in the divergence detector and Wave N3 caught in
its own first cut. A digest section that says "not yet measurable, and here is what would
make it measurable" is worth more than a plausible 3.

**Every number cites where it came from.** A digest is read fast and trusted by default, so
each line names its source store. A figure a reader cannot trace is a figure they cannot
act on — the same rule Q4's caveats follow.

Deterministic and read-only: no model call, no writes. The narrative is assembled from
counted facts rather than generated, because a digest whose prose a model wrote is a
digest that can be confidently wrong about the platform's own behaviour.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

#: The window a weekly digest covers.
DEFAULT_WINDOW_DAYS = 7


@dataclass
class Section:
    """One digest section: a headline number, its detail, and where it came from."""

    key: str
    title: str
    value: Optional[Any] = None
    detail: str = ""
    source: str = ""              # the store this was counted from
    measurable: bool = True       # False ⇒ we cannot count this yet, and say so

    def line(self) -> str:
        if not self.measurable:
            return f"{self.title}: not yet measurable — {self.detail}"
        head = f"{self.title}: {self.value}" if self.value is not None else self.title
        return f"{head}{(' — ' + self.detail) if self.detail else ''}"

    def to_dict(self) -> dict:
        return {"key": self.key, "title": self.title, "value": self.value,
                "detail": self.detail, "source": self.source,
                "measurable": self.measurable, "line": self.line()}


@dataclass
class Digest:
    """The workspace digest — counted facts, each citing its store."""

    connection_id: str
    window_days: int = DEFAULT_WINDOW_DAYS
    generated_at: str = ""
    sections: list[Section] = field(default_factory=list)

    @property
    def unmeasurable(self) -> list[Section]:
        return [s for s in self.sections if not s.measurable]

    def narrative(self) -> str:
        """The digest as text. Assembled from counted facts, never generated.

        A digest whose prose a model wrote is a digest that can be confidently wrong about
        the platform's own behaviour — and this one reports on the platform to the people
        who would have to notice.
        """
        lines = [f"Workspace digest — last {self.window_days} days on "
                 f"`{self.connection_id}`", ""]
        lines += [f"  • {s.line()}" for s in self.sections if s.measurable]
        if self.unmeasurable:
            # Named, never omitted: a section quietly dropped reads as "nothing to report",
            # which is a different claim from "we cannot measure this yet".
            lines += ["", "  Not yet measurable:"]
            lines += [f"  • {s.line()}" for s in self.unmeasurable]
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {"connection_id": self.connection_id, "window_days": self.window_days,
                "generated_at": self.generated_at,
                "sections": [s.to_dict() for s in self.sections],
                "narrative": self.narrative()}


def _cutoff(window_days: int) -> str:
    from datetime import datetime, timedelta, timezone

    return (datetime.now(timezone.utc) - timedelta(days=max(1, int(window_days)))).isoformat()


def _volume(connection_id: str, cutoff: str) -> Section:
    from aughor.kernel.ledger import Ledger
    from aughor.ontology.context_graph_build import RECEIPT_KINDS

    arts = Ledger.default().artifacts_of_kind(
        list(RECEIPT_KINDS), conn_id=connection_id, limit=5000) or []
    recent = [a for a in arts if str(a.get("created_at") or "") >= cutoff]
    days = len({str(a.get("created_at") or "")[:10] for a in recent})
    return Section(
        key="volume", title="Questions answered", value=len(recent),
        detail=f"across {days} active day(s)" if recent else "no activity in the window",
        source="evidence ledger (answer receipts)")


def _usage(connection_id: str) -> Section:
    from aughor.obs.usage import usage_report

    report = usage_report(axes=("feature",), scan=20000)
    top = ", ".join(f"{r.key['feature']} {r.calls}" for r in report.rows[:3])
    return Section(
        key="usage", title="Model calls", value=report.total_calls,
        detail=f"by feature: {top}" if top else "none recorded",
        source="session log (G3a rollup)")


def _feedback(connection_id: str) -> Section:
    """Verdicts and corrections.

    Reads `verify/verdicts.py`, NOT ledger events — my first pre-check looked in the wrong
    place and found zero, which is the same wrong-source mistake G3b's `llm_call` reader
    made. Worth the comment because the ledger is the obvious guess and it is wrong.
    """
    from aughor.feedback.verdicts import list_corrections, list_verdicts

    verdicts = list_verdicts(connection_id) or []
    corrections = list_corrections(connection_id) or []
    if not verdicts and not corrections:
        return Section(
            key="feedback", title="Feedback", value=0,
            detail="nobody has corrected or confirmed an answer yet",
            source="verdict store")
    return Section(
        key="feedback", title="Feedback", value=len(verdicts),
        detail=f"{len(corrections)} correction(s) recorded",
        source="verdict store")


def _curation(connection_id: str) -> Section:
    from aughor.actions.inbox import list_proposals

    staged = list_proposals() or []
    return Section(
        key="curation", title="Curation queue", value=len(staged),
        detail=("proposals waiting for a decision" if staged
                else "nothing waiting for a decision"),
        source="A4 resolve-once inbox")


def _health(connection_id: str) -> Section:
    """Q3's failing checks. Counted per table so the number means something."""
    from aughor.quality.results import count_failing

    try:
        failing = count_failing(connection_id)
    except Exception as exc:
        from aughor.kernel.errors import tolerate

        tolerate(exc, "digest health section is best-effort",
                 counter="digest.health")
        return Section(key="health", title="Data quality", measurable=False,
                       detail="the quality store could not be read",
                       source="quality results")
    return Section(
        key="health", title="Data quality", value=failing,
        detail="failing check(s)" if failing else "no failing checks",
        source="quality results (Q3)")


def _abstentions() -> Section:
    """The section the pre-check refused to fabricate.

    Only 3 of 795 receipts carry an abstention-shaped phrase, and there is NO structured
    field — matching headline prose for "abstain" or "within normal variance" would
    produce an authoritative-looking number that is really a regex opinion. Reported as
    not-yet-measurable, with what would fix it, because a digest section that says so is
    worth more than a plausible 3.
    """
    return Section(
        key="abstentions", title="Abstentions", measurable=False,
        detail=("no structured field records an abstention — counting them would mean "
                "pattern-matching headline prose. A receipt field set where the answer "
                "path already decides to abstain would make this countable"),
        source="answer receipts (prose only)")


def build_digest(connection_id: str, *, window_days: int = DEFAULT_WINDOW_DAYS) -> Digest:
    """Assemble the digest. Every section is best-effort; one failure never sinks the rest."""
    from aughor.kernel.errors import tolerate
    from aughor.util.time import now_iso

    cutoff = _cutoff(window_days)
    builders = [
        ("volume", lambda: _volume(connection_id, cutoff)),
        ("usage", lambda: _usage(connection_id)),
        ("health", lambda: _health(connection_id)),
        ("feedback", lambda: _feedback(connection_id)),
        ("curation", lambda: _curation(connection_id)),
        ("abstentions", _abstentions),
    ]
    sections: list[Section] = []
    for key, build in builders:
        try:
            sections.append(build())
        except Exception as exc:
            tolerate(exc, f"digest section {key!r} is best-effort",
                     counter="digest.section")
            # A section that failed is reported as unmeasurable rather than dropped: a
            # missing section reads as "nothing to report", which is a different claim.
            sections.append(Section(key=key, title=key.title(), measurable=False,
                                    detail="could not be computed this run"))
    return Digest(connection_id=connection_id, window_days=window_days,
                  generated_at=now_iso(), sections=sections)
