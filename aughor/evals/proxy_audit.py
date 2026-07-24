"""The proxy-inversion audit (Wave E4 loose end).

An eval axis is either the END-TASK metric or a PROXY for it. Aughor's end task is
``accuracy`` — execution-grounded exact-match (``user_agents.quality.results_match``) on the
answer's result set, the thing a user actually cares about. ``pass_rate`` (guard-clean stable
passes) and ``robustness`` (agreement under meaning-preserving perturbation) are PROXIES: cheaper
to read, correlated with quality, but not it.

A proxy is dangerous precisely when it can **invert** — improve while the end-task metric
worsens. This is not hypothetical. The case study the five-repo study cites: gemma-4 quantized KV
scores 7-42% *better* corpus perplexity than fp16 while KL divergence says it drifted *most* —
optimising the proxy (PPL) moved the true metric the wrong way, because an absolute proxy has no
anchor to the task. Aughor has already measured its own version of the same trap: E2's evaluator
sweep found guards firing on KNOWN-CORRECT golden SQL — true positives in our own reference SQL
(the CIDR "benchmarks are broken" pattern), plus false positives on safe 1:N aggregation — so a
rising ``pass_rate`` (fewer guards firing) does not imply rising ``accuracy``, and can move
against it.

The conclusion, and the reason this module exists: classify every axis, and **demote any proxy
that inverts** — keep it out of the fidelity composite so a proxy-only "win" cannot masquerade as
a quality gain. A proxy is demoted two ways:

1. by EVIDENCE — :func:`audit_inversion` over paired runs flags a proxy observed to improve while
   ``accuracy`` dropped. This is the audit the five-repo study asked for, run over real run
   history.
2. by NATURE (the conservative default when there is no evidence yet) — a proxy is *eligible* for
   demotion and the ground-truth axis never is, so a caller that wants a purely task-anchored
   composite can demote every proxy without waiting for one to be caught inverting.

Pure arithmetic over ``RunSummary``-shaped objects; never calls a model or touches a store.
See ``docs/EVALS_PROXY_INVERSION_AUDIT.md``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Optional, Sequence

#: The one execution-grounded end-task metric. Everything else is a proxy for this.
GROUND_TRUTH_AXIS = "accuracy"

#: name → (kind, why). ``ground_truth`` is the end task; ``proxy`` is a stand-in that can invert.
AXIS_KIND: dict[str, tuple[str, str]] = {
    "accuracy": ("ground_truth",
                 "execution exact-match (results_match) on the result set — the end task itself"),
    "pass_rate": ("proxy",
                  "guard-clean stable passes; E2 measured guards firing on known-correct SQL, so "
                  "a higher pass_rate need not mean higher accuracy and can move opposite to it"),
    "robustness": ("proxy",
                   "agreement under meaning-preserving perturbation; a consistently WRONG pipeline "
                   "scores high, so robustness is orthogonal to correctness, not a stand-in for it"),
}


def kind_of(axis: str) -> str:
    """``"ground_truth"`` or ``"proxy"``. An unclassified axis is treated as a proxy — the safe
    default, because assuming an unknown axis is the end task is the mistake this module prevents."""
    return AXIS_KIND.get(axis, ("proxy", "unclassified — treated as a proxy until audited"))[0]


def is_proxy(axis: str) -> bool:
    return kind_of(axis) != "ground_truth"


def _val(summary: Any, name: str) -> Optional[float]:
    """One axis off a RunSummary (or dict), ``None`` if it was not measured (never folded to 0)."""
    value = getattr(summary, name, None)
    if value is None and isinstance(summary, dict):
        value = summary.get(name)
    return None if value is None else float(value)


@dataclass(frozen=True)
class AxisAudit:
    axis: str
    kind: str
    pairs: int          # ordered (before, after) pairs where BOTH this axis and accuracy were read
    inversions: int     # pairs where this axis IMPROVED while accuracy WORSENED (both beyond epsilon)
    inverts: Optional[bool]   # True/False once `pairs >= min_pairs`; None while evidence is thin
    demoted: bool       # keep it out of the composite?
    reason: str

    def to_dict(self) -> dict:
        return {"axis": self.axis, "kind": self.kind, "pairs": self.pairs,
                "inversions": self.inversions, "inverts": self.inverts,
                "demoted": self.demoted, "reason": self.reason}


@dataclass
class InversionReport:
    ground_truth: str
    axes: list[AxisAudit] = field(default_factory=list)

    def demoted_axes(self) -> list[str]:
        return [a.axis for a in self.axes if a.demoted]

    def summary_lines(self) -> list[str]:
        out = [f"ground-truth axis: {self.ground_truth}"]
        for a in self.axes:
            mark = "⤵ demoted" if a.demoted else "kept"
            out.append(f"[{a.kind}] {a.axis}: {mark} — {a.reason}")
        return out

    def to_dict(self) -> dict:
        return {"ground_truth": self.ground_truth, "axes": [a.to_dict() for a in self.axes],
                "demoted": self.demoted_axes()}


def audit_inversion(
    runs: Sequence[Any],
    *,
    ground_truth: str = GROUND_TRUTH_AXIS,
    axes: Optional[Iterable[str]] = None,
    epsilon: float = 0.01,
    min_pairs: int = 3,
    demote_unproven_proxies: bool = False,
) -> InversionReport:
    """Audit whether each proxy axis has ever moved *opposite* to the end-task metric.

    ``runs`` is an ORDERED sequence of RunSummary-shaped objects (dicts or dataclasses). Ordered,
    because the signal is a change between one run and the next — a grid's baseline-then-variants,
    or a suite's run history in time order. Each consecutive pair contributes one observation per
    axis where both that axis and ``ground_truth`` were measured; an ``inversion`` is a pair where
    the proxy improved by more than ``epsilon`` while ``ground_truth`` dropped by more than
    ``epsilon`` (the band keeps run-to-run jitter from reading as a real reversal).

    Demotion:
      * the ground-truth axis is NEVER demoted (it is the thing every proxy is judged against);
      * a proxy with ``inversions > 0`` on ``>= min_pairs`` observations is demoted by EVIDENCE;
      * a proxy below ``min_pairs`` has ``inverts=None`` (evidence too thin to convict) and is
        demoted only when ``demote_unproven_proxies`` — the conservative, task-anchored posture.
    """
    axis_names = list(axes) if axes is not None else sorted(
        set(AXIS_KIND) | {ground_truth} | {"pass_rate", "robustness"})

    audits: list[AxisAudit] = []
    for name in axis_names:
        kind = kind_of(name)
        if name == ground_truth or kind == "ground_truth":
            audits.append(AxisAudit(
                axis=name, kind="ground_truth", pairs=0, inversions=0, inverts=False,
                demoted=False,
                reason="the end-task metric — every proxy is measured against it, so it is never demoted"))
            continue

        pairs = 0
        inversions = 0
        for before, after in zip(runs, runs[1:]):
            pv, av = _val(before, name), _val(before, ground_truth)
            nv, gv = _val(after, name), _val(after, ground_truth)
            if None in (pv, av, nv, gv):
                continue
            pairs += 1
            proxy_up = (nv - pv) > epsilon
            truth_down = (gv - av) < -epsilon
            if proxy_up and truth_down:
                inversions += 1

        if pairs >= min_pairs:
            inverts: Optional[bool] = inversions > 0
        else:
            inverts = None

        if inverts:
            demoted, reason = True, (
                f"DEMOTED: improved while {ground_truth} worsened in {inversions}/{pairs} "
                f"observed pairs — an inverting proxy cannot be trusted as a quality signal")
        elif inverts is False:
            demoted, reason = False, (
                f"kept: never moved opposite to {ground_truth} across {pairs} pairs, so it "
                f"tracks the end task in this history (still a proxy — read beside accuracy)")
        else:
            demoted = demote_unproven_proxies
            reason = (
                f"insufficient evidence ({pairs} < {min_pairs} pairs) to convict or clear it; "
                + ("demoted anyway (task-anchored composite requested)" if demoted
                   else f"a proxy by nature — {AXIS_KIND.get(name, ('', 'unclassified'))[1]}"))

        audits.append(AxisAudit(axis=name, kind=kind, pairs=pairs, inversions=inversions,
                                inverts=inverts, demoted=demoted, reason=reason))

    return InversionReport(ground_truth=ground_truth, axes=audits)
