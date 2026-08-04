"""The trust sidecar — what standing each node has earned (Wave P3).

Graphify's `reflect` scores a node by the outcomes of the answers that cited it: signed,
time-decayed, and promoted to "preferred" only on corroboration by several distinct
results, because one save must not mint a trusted lesson. This is that shape, over
Aughor's stores — with one correction that changed the design.

**The premise check that moved the scope.** P3 was scoped to aggregate human verdicts and
evidence-ledger feedback. Measured against the real data first (the rule that has now gone
seven for seven): there are **zero verdicts and no evidence-ledger rows** — neither store
even exists on disk. Built as scoped, every node would read "no signal" forever: a feature
that is BUILT and never leveraged. So the primary signal is the one that *does* exist —
**how many distinct findings a node carries, and whether they agree** — and the human
channel is wired as an additional input that lights up when the first verdict is cast.

**The distinction the labels must not blur.** A table that fourteen findings depend on is
*heavily used*, not *verified*. Corroboration by citation says the platform keeps coming
back to a node; only a human verdict says anyone checked the answer. So the default
standing for a well-used node is **`unchecked`**, not "trusted" — and on a warehouse where
nobody has recorded a verdict yet, every node being `unchecked` is the honest report, and
arguably the most useful thing this surface says.

**A sidecar, never the graph.** Nothing here is written to the artifact. Standing is
derived at read time from the graph plus the verdict store, the same discipline as the
warrant class (Wave P2) and the reason Graphify keeps its `learning_*` fields out of
`graph.json`: structural truth and experiential annotation age differently, and a
conclusion stamped into the structure outlives the evidence for it.

**It does not touch a prompt.** Wave L2 measured finding read-back and found no
attributable gain, so nothing here is injected into planning. This is display-time
annotation for a human deciding what to check. If it ever wants into a prompt, it goes
through the E6 gate like everything else.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from aughor.kernel.errors import tolerate

#: How many DISTINCT findings must agree about a node before it counts as corroborated.
#: Two is the smallest number that can mean "more than once"; Graphify's rule — one save
#: cannot mint a trusted lesson — is the same instinct.
CORROBORATION_MIN = 2

#: Half-life of a human verdict, in days. A verdict from a year ago still counts, at a
#: fraction: warehouses change, and a rejection recorded before a table was rebuilt should
#: not outrank an acceptance recorded after it.
VERDICT_HALF_LIFE_DAYS = 180.0

#: Standing values, strongest claim to weakest. `unchecked` is deliberately NOT last: an
#: unchecked node is not worse than a contested one, it is a different state, and ordering
#: it below "contested" would rank silence as more damning than a live disagreement.
STANDING = ("confirmed", "contested", "disputed", "corroborated", "unchecked")

STANDING_MEANING: dict[str, str] = {
    "confirmed": "A person has accepted findings that rest on this.",
    "contested": "Two analyses of this disagree on the numbers. Nobody has settled it.",
    "disputed": "A person has rejected findings that rest on this.",
    "corroborated": "Several separate analyses have relied on this and none disagreed — "
                    "but nobody has checked them.",
    "unchecked": "Nothing here has been confirmed by a person.",
}


@dataclass
class NodeTrust:
    node_id: str
    standing: str = "unchecked"
    findings: int = 0          # distinct findings grounded in this node
    contested: int = 0         # of those, how many carry an unsettled disagreement
    stale: int = 0             # of those, how many stand on data that has since vanished
    accepts: float = 0.0       # time-decayed human accepts
    rejects: float = 0.0       # time-decayed human rejects (incl. corrections)
    detail: str = ""

    def to_dict(self) -> dict:
        return {"node_id": self.node_id, "standing": self.standing,
                "findings": self.findings, "contested": self.contested,
                "stale": self.stale, "accepts": round(self.accepts, 2),
                "rejects": round(self.rejects, 2), "detail": self.detail,
                "meaning": STANDING_MEANING.get(self.standing, "")}


@dataclass
class TrustSidecar:
    """Standing for every node that has any — merged at display time, never stored."""

    connection_id: str
    nodes: dict[str, NodeTrust] = field(default_factory=dict)
    verdicts_seen: int = 0       # verdicts read from the store
    verdicts_matched: int = 0    # …of those, how many reached a node in this graph

    def get(self, node_id: str) -> Optional[NodeTrust]:
        return self.nodes.get(node_id)

    def summary(self) -> dict:
        by: dict[str, int] = {s: 0 for s in STANDING}
        for t in self.nodes.values():
            by[t.standing] = by.get(t.standing, 0) + 1
        return {"by_standing": by, "scored_nodes": len(self.nodes),
                "verdicts_seen": self.verdicts_seen,
                "verdicts_matched": self.verdicts_matched,
                # MATCHED, not merely seen. A verdict the graph could not attach to any
                # node contributed nothing, and reporting it as human signal would let the
                # summary contradict the per-node standings it sits above.
                "human_signal": bool(self.verdicts_matched),
                # Named so an operator can act on it: verdicts that reached nothing mean
                # the graph is missing the findings they judged, not that nobody reviewed.
                "verdicts_unmatched": max(0, self.verdicts_seen - self.verdicts_matched)}

    def to_dict(self) -> dict:
        return {"connection_id": self.connection_id,
                "nodes": {k: v.to_dict() for k, v in sorted(self.nodes.items())},
                "meanings": dict(STANDING_MEANING),
                **self.summary()}


#: Weight given to a verdict whose timestamp cannot be read. NOT 1.0: an undated row
#: would otherwise be scored as if cast today and could single-handedly flip a node's
#: standing — fail-open in the wrong direction for the signal this module treats as
#: ground truth. It still counts, at the weight of a verdict one half-life old.
UNDATED_WEIGHT = 0.5


def _age_days(stamp: str, now: datetime) -> Optional[float]:
    """Age in days, or ``None`` when the timestamp is missing or unreadable."""
    if not stamp:
        return None
    try:
        dt = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0.0, (now - dt).total_seconds() / 86400.0)
    except Exception:
        return None


def _decay(age_days: Optional[float], half_life: float = VERDICT_HALF_LIFE_DAYS) -> float:
    if age_days is None:
        return UNDATED_WEIGHT
    return 0.5 ** (age_days / half_life) if half_life > 0 else 1.0


def build_trust(graph, *, verdicts: Optional[list] = None,
                now: Optional[datetime] = None) -> TrustSidecar:
    """Standing for every node in ``graph``. Pure over its inputs and deterministic:
    given the same graph, the same verdicts and the same ``now``, the output is identical.

    ``verdicts`` are rows from :mod:`aughor.feedback.verdicts` (``list_verdicts``). Passed
    in rather than read here so the function stays pure and testable, and so a caller that
    already has them does not read the store twice.
    """
    now = now or datetime.now(timezone.utc)
    sc = TrustSidecar(connection_id=getattr(graph, "connection_id", ""))
    if graph is None or not getattr(graph, "nodes", None):
        return sc

    # 1. Citation structure: which nodes each finding grounds in, and what state that
    #    finding is in. This is the signal that exists on every real connection.
    finding_state: dict[str, dict] = {}
    for n in graph.nodes.values():
        if n.kind == "finding":
            finding_state[n.id] = n.data or {}

    # finding node → the nodes it grounds in. Built ONCE and reused for the verdict pass:
    # re-scanning every edge per verdict is 500 verdicts × a 20k-edge graph on a real
    # warehouse, for an index that is already in hand.
    grounds_in: dict[str, list[str]] = {}
    for e in graph.edges.values():
        if e.kind != "grounded_in" or e.from_id not in finding_state:
            continue
        grounds_in.setdefault(e.from_id, []).append(e.to_id)
        data = finding_state[e.from_id]
        t = sc.nodes.setdefault(e.to_id, NodeTrust(node_id=e.to_id))
        t.findings += 1
        if data.get("contested"):
            t.contested += 1
        if data.get("stale"):
            t.stale += 1

    # A verdict is filed under an INVESTIGATION id; a finding node is keyed by the Ledger
    # artifact id, which is a fresh uuid. The two are different namespaces and matching
    # them by name would silently score nothing, so the projection carries the
    # investigation id onto the node (`data["investigation_id"]`) and the join happens
    # here. The node-id form is also accepted, for callers that already hold one.
    by_investigation: dict[str, str] = {}
    for nid, data in finding_state.items():
        inv = str(data.get("investigation_id") or "")
        if inv:
            by_investigation.setdefault(inv, nid)

    # 2. Human verdicts, signed and time-decayed. `correct` counts as a rejection of the
    #    number, not a half-accept: "right direction, wrong detail" means the figure a
    #    reader would have quoted was wrong.
    for v in (verdicts or []):
        sc.verdicts_seen += 1
        inv = str((v or {}).get("investigation_id") or "").strip()
        if not inv:
            continue
        node_id = (by_investigation.get(inv)
                   or (inv if inv in finding_state else None)
                   or (f"finding:{inv}" if f"finding:{inv}" in finding_state else None))
        touched = grounds_in.get(node_id or "", [])
        if not touched:
            # Counted as seen but NOT as matched. Reporting both is what keeps the summary
            # from contradicting itself: "10 verdicts, human_signal true" over a graph
            # where every one was discarded is the shape this wave exists to refuse.
            continue
        sc.verdicts_matched += 1
        weight = _decay(_age_days(str(v.get("created_at") or ""), now))
        verdict = str(v.get("verdict") or "").lower()
        for tid in touched:
            t = sc.nodes.setdefault(tid, NodeTrust(node_id=tid))
            if verdict == "accept":
                t.accepts += weight
            elif verdict in ("reject", "correct"):
                t.rejects += weight

    for t in sc.nodes.values():
        t.standing, t.detail = _standing(t)
    return sc


def _standing(t: NodeTrust) -> tuple[str, str]:
    """The label, and the sentence that justifies it.

    Order of precedence is a claim about what a reader most needs to know: a live
    disagreement outranks a tally of accepts, because the tally cannot settle it.
    """
    if t.contested:
        return "contested", (f"{t.contested} of {t.findings} findings here disagree on the "
                             f"numbers and nobody has settled it")
    if t.rejects > 0 and t.rejects >= t.accepts:
        # A TIE is not a confirmation. One accept and one reject of equal age is two
        # reviewers disagreeing, and rendering that as "a person has accepted this" —
        # with the rejection omitted from the sentence — reports agreement where there
        # is none.
        verb = "disputed" if t.rejects > t.accepts else "contested"
        return ("disputed" if t.rejects > t.accepts else "contested",
                f"{verb}: {t.rejects:.1f} weighted rejections vs {t.accepts:.1f} accepted")
    if t.accepts > 0:
        return "confirmed", f"accepted by a person ({t.accepts:.1f} weighted verdicts)"
    if t.findings >= CORROBORATION_MIN and not t.stale:
        return "corroborated", (f"{t.findings} separate analyses relied on this and none "
                                f"disagreed — none was checked by a person")
    if t.stale:
        return "unchecked", (f"{t.stale} of {t.findings} findings here stand on data that "
                             f"is no longer in the ontology")
    return "unchecked", (f"{t.findings} finding(s) here, none confirmed by a person"
                         if t.findings else "nothing has been checked here")


def trust_for_connection(connection_id: str, graph, *, org_id: str = "") -> TrustSidecar:
    """Store-backed: :func:`build_trust` with this connection's verdicts folded in.

    Degrades to citation-only standing when the verdict store is unavailable — which is
    also the state of every warehouse that has not recorded a verdict yet, so the
    degraded path is the common path and must be the honest one, not an error.
    """
    rows: list = []
    try:
        from aughor.feedback.verdicts import list_verdicts
        rows = list_verdicts(connection_id, limit=500)
    except Exception as exc:
        tolerate(exc, "human verdicts are one input to node standing; citation-based "
                      "standing still computes without them",
                 counter="graph_trust.verdicts")
    return build_trust(graph, verdicts=rows)
