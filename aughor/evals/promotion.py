"""The flag promotion gate (Wave E6) — a flag graduates when its suite earns it.

Generalises ``packs/evalgate.evaluate_activation``'s shape (a decision that separates
"passes" from "deployable", reporting actionable blockers) from pack-activation to
**flag graduation**: a default-off flag has *earned* default-on when an eval suite
bound to it passes at or above a baseline, on a run with no errors and no flaky cases.

The load-bearing design decision — and the reason this module records a decision rather
than flipping anything:

    Graduation produces EVIDENCE, not an action. It records a receipted decision so a
    human can flip ``FLAG_DEFAULT`` in a reviewed change. It deliberately does NOT set a
    runtime override, because a flag turned ON in the ledger while the code default stays
    OFF is *exactly* the drift the 2026-07-22 flag-graduation audit existed to remove
    (19 features were ON in one developer's ledger while every fresh clone and CI got the
    OFF code default — CI validated a configuration nobody ran). A promotion gate that set
    an override would re-manufacture that drift with a receipt stapled to it.

Pure; never raises. The runner that produces the ``run_summary`` (E3/E4) and the store
that persists the decision are the connection-dependent halves, kept separate.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class GraduationDecision:
    flag: str
    can_graduate: bool = False
    pass_rate: Optional[float] = None
    baseline_pass_rate: Optional[float] = None
    #: The bar the run was actually judged against (the baseline when given, else min_pass_rate).
    bar: Optional[float] = None
    reasons: list[str] = field(default_factory=list)  # blockers — empty iff can_graduate
    run_id: str = ""
    suite_id: str = ""
    #: What FLAG_DEFAULT already says. A flag already default-on can still be *re-evidenced*,
    #: but the decision says so rather than pretending it flipped something.
    current_default: bool = False
    already_default_on: bool = False

    def to_dict(self) -> dict:
        return {
            "flag": self.flag,
            "can_graduate": self.can_graduate,
            "pass_rate": self.pass_rate,
            "baseline_pass_rate": self.baseline_pass_rate,
            "bar": self.bar,
            "reasons": list(self.reasons),
            "run_id": self.run_id,
            "suite_id": self.suite_id,
            "current_default": self.current_default,
            "already_default_on": self.already_default_on,
        }


def evaluate_graduation(
    flag: str,
    run_summary: Optional[dict[str, Any]],
    *,
    registered_flags: set[str],
    current_default: bool = False,
    baseline_pass_rate: Optional[float] = None,
    min_pass_rate: float = 1.0,
    delta: Any = None,
) -> GraduationDecision:
    """Decide whether ``flag`` has EARNED graduation to default-on, from one eval run.

    Blockers are reported separately and actionably, so "the suite passes" is never
    confused with "the flag has earned it":

      1. the flag is not registered (an unknown name cannot graduate);
      2. there is no run to judge;
      3. the suite has no cases (a run over nothing proves nothing);
      4. the run errored (a graduation cannot rest on a run that errored);
      5. the run has flaky cases (graduation needs STABLE passes, not a coin-flip —
         a flaky case is E3's first-class verdict precisely so it is not rounded away);
      6. the pass rate is below the bar — the baseline when one is given, otherwise
         ``min_pass_rate`` (default 1.0: with no baseline to beat, a candidate must be
         clean).

    ``baseline_pass_rate`` is the honest bar: the flag-OFF run's pass rate, so graduation
    means "at least as good as without the flag". Producing that baseline is a flag-off /
    flag-on A/B — the E4 experiments plane's job; this gate scores the result.

    ``delta`` is that A/B's :class:`aughor.evals.fidelity.Delta`. It is required whenever
    a baseline is given, because **clearing the bar is not the same as beating it** —
    the difference is the noise floor. Without it this gate once said `can_graduate=True`
    about the exact +0.023 that ``fidelity.compare`` was simultaneously refusing to
    attribute against a 0.182 band (7 blocker, below). J3 binds J9: a flag cannot
    graduate on a delta the harness will not stand behind.
    """
    reasons: list[str] = []
    bar = baseline_pass_rate if baseline_pass_rate is not None else min_pass_rate

    if flag not in registered_flags:
        reasons.append(f"unknown flag {flag!r} — not in the flag registry")

    if not run_summary:
        reasons.append("no run to evaluate — run the suite first")
        return GraduationDecision(
            flag=flag, reasons=reasons, baseline_pass_rate=baseline_pass_rate,
            bar=bar, current_default=current_default, already_default_on=current_default,
        )

    total = int(run_summary.get("total", 0) or 0)
    errors = int(run_summary.get("errors", 0) or 0)
    flaky = int(run_summary.get("flaky", 0) or 0)
    pass_rate = run_summary.get("pass_rate")

    if total == 0:
        reasons.append("the suite has no cases — a run over nothing cannot earn a default")
    if errors:
        reasons.append(f"{errors} case(s) errored — a graduation cannot rest on a run that errored")
    if flaky:
        reasons.append(f"{flaky} flaky case(s) — graduation needs stable passes, not a coin-flip")
    if pass_rate is None:
        reasons.append("the run reported no pass_rate")
    elif pass_rate < bar:
        detail = "baseline" if baseline_pass_rate is not None else f"min {min_pass_rate:g}"
        reasons.append(f"pass_rate {pass_rate:g} is below the bar {bar:g} ({detail})")

    # Clearing the bar is not the same as BEATING it, and the difference is the noise
    # floor. Found by running the first real grid: fidelity refused a +0.023 delta
    # against a 0.182 band while this gate independently said `can_graduate=True` —
    # the two halves of the same discipline, disagreeing, because only one of them had
    # ever looked at the floor. A gate that graduates on a delta the harness refuses to
    # attribute is a gate that graduates on noise.
    if delta is not None and not getattr(delta, "attributable", True):
        reasons.append(
            "the delta is not attributable: " + str(getattr(delta, "verdict", "")
                                                    or "the noise floor was not met"))
    elif delta is None and baseline_pass_rate is not None:
        # A baseline implies an A/B ran. An A/B without its floor is the shape that
        # produced this bug, so it is named rather than silently allowed.
        reasons.append(
            "no floor evidence supplied for a baseline comparison — pass the "
            "fidelity.compare() result as `delta` so the gate can see whether the "
            "difference clears the noise band")

    return GraduationDecision(
        flag=flag,
        can_graduate=not reasons,
        pass_rate=pass_rate,
        baseline_pass_rate=baseline_pass_rate,
        bar=bar,
        reasons=reasons,
        run_id=str(run_summary.get("run_id", "")),
        suite_id=str(run_summary.get("suite_id", "")),
        current_default=current_default,
        already_default_on=current_default,
    )
