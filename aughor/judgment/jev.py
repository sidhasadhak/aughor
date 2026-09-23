"""JD-5 — the hosted judgment backend: TypeSafe's Jev behind JD-1's seam.

One backend among ours, for the CHEAP tier of the banded cascade only — never the champion,
never the verdict path. Built 2026-09-21 on the live receipt (`docs/JEV_LIVE_RECEIPT_2026-09-21.md`:
jev-solo +2.6 points over the sampled cascade at zero champion calls, 2.6x cheaper than the
cheapest LLM arm on file, and the shuffled-context control collapsed below the majority floor —
it reads the state). The receipt also measured where its probabilities stop meaning anything:
inside the 0.30-0.70 band — which is exactly the zone the cascade escalates to the in-house
champion, so the band boundaries and the trust boundaries are the same lines.

Four gates stand between a row and the wire, and each one fails toward the house:

1. **The flag** — ``semops.jev_cheap_tier``, an EXPERIMENT, default OFF.
2. **Configuration is loud** — ``TYPESAFE_API_KEY`` and ``AUGHOR_JEV_MODEL`` must both be set.
   No model id ships in the product (the 2026-08-15 directive and its ratchet test), and
   "jev-latest" is still a model id: the operator writes it, or nothing is sent.
3. **PII never leaves** — the bundle's state is scanned (`security.pii.PiiScanner`) and a
   bundle with ANY redactable cell is withheld whole: its rows come back unanswered, which
   the band already routes to the in-house champion. Conservative on purpose — a governance
   gate that parses its own prompt to be clever about WHICH row leaked is a gate with a
   parsing bug waiting inside it.
4. **The outbound seam** — every call rides ``govern.outbound.external_call`` ("typesafe",
   "systemone"): the usage cap is checked BEFORE the send, the call lands in the waterfall,
   and an ``EXTERNAL_CALL`` session event makes it countable. ``OutboundBlocked`` is an
   unavailable answer, not an exception into the query path.

And one guarantee about failure: :class:`FallbackJudge` wraps this backend over the deployment's
own cheap LLM tier. A bundle Jev cannot answer — withheld, blocked, unconfigured mid-run, or the
service down — is re-judged by the LLM tier through the same seam, so an outage degrades to
exactly yesterday's cascade instead of flooding the champion with 200 "unanswered" rows.

The request shape is the slimmed seam's (rows ride the state once; a question is a short
reference), which is also the batched shape pg-jev measured at 100% on bundles of <=20 rows;
this module inherits the harness's contract (`evals/semops_band_eval.py::JevBackend`), and the
live receipt is its proof of correspondence.
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Mapping, Optional, Sequence

from aughor.judgment.seam import (CHOICE, NOUL, SCORE, Answer, Choice, Noul, Score,
                                  judge as seam_judge, weighted_score)

logger = logging.getLogger(__name__)

#: The vendor's documented endpoint (docs.typesafe.ai/api, read + confirmed live 2026-09-21).
#: A URL is an address, not a model id; override with AUGHOR_JEV_URL (a proxy, a mock).
DEFAULT_URL = "https://api.typesafe.ai/v1/systemone"

#: Bounded politeness on 429/529, as the vendor asks. Small on purpose: this sits on the
#: query path, and the fallback tier exists precisely so we never wait long here.
RETRIES = 2
BACKOFF_S = 0.5
TIMEOUT_S = 30


class _Retryable(Exception):
    """A 429 or 529: back off once or twice, then let the fallback tier have the bundle."""


def _http_post(url: str, body: dict, headers: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        if exc.code in (429, 529):
            raise _Retryable(f"HTTP {exc.code}") from exc
        detail = exc.read().decode(errors="replace")[:200]
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc


def configured_judge(*, post: Optional[Callable[[str, dict, dict], dict]] = None
                     ) -> "tuple[Optional[JevJudge], str]":
    """The deployment's Jev judge, or ``(None, why-not)`` — every reason an operator can act on.

    The flag is NOT checked here (the call site owns its flag, and a test may construct a
    judge directly); configuration is. Absence is a reason, never an exception.
    """
    key = (os.getenv("TYPESAFE_API_KEY") or "").strip()
    if not key:
        return None, "TYPESAFE_API_KEY is not set"
    model = (os.getenv("AUGHOR_JEV_MODEL") or "").strip()
    if not model:
        return None, ("AUGHOR_JEV_MODEL is not set — no model id ships in the product, "
                      "so the operator names the Jev model (the vendor documents one)")
    url = (os.getenv("AUGHOR_JEV_URL") or "").strip() or DEFAULT_URL
    return JevJudge(key, model, url=url, post=post), ""



# ── the wire, per primitive ───────────────────────────────────────────────────────────────

def _kind_of(q: Any) -> str:
    return CHOICE if isinstance(q, Choice) else SCORE if isinstance(q, Score) else NOUL


def _wire(q: Any) -> dict:
    """One question in the vendor's shape. `criteria` is a MAP for a choice and an ORDERED
    LIST for a score — the two are not interchangeable, and a list sent for a choice loses
    the keys the answer comes back under."""
    if isinstance(q, Noul):
        return {"type": "noul", "instructions": q.proposition}
    if isinstance(q, Choice):
        # name → name: see the class docstring. A description only this backend could read
        # would make one question mean two things.
        return {"type": "choice", "instructions": q.question,
                "criteria": {o: o for o in q.options}}
    return {"type": "score", "instructions": q.question, "criteria": list(q.levels)}


def _probabilities(a: Mapping[str, Any], names: Sequence[str]) -> dict[str, float]:
    """The per-name distribution, normalised, keeping ONLY names we declared. A weight
    against a name outside the closed set is dropped rather than renormalised into it."""
    raw = a.get("probabilities")
    if not isinstance(raw, Mapping):
        return {}
    kept = {n: max(0.0, float(raw[n])) for n in names
            if isinstance(raw.get(n), (int, float))}
    total = sum(kept.values())
    return {k: v / total for k, v in kept.items()} if total > 0 else {}


def _read_noul(q: Noul, a: Mapping[str, Any]) -> Answer:
    p = a.get("noul")
    if not isinstance(p, (int, float)) or not 0.0 <= float(p) <= 1.0:
        return Answer(q.id, NOUL, False, reason=f"Jev returned no noul for {q.id}: {a!r}"[:200])
    p = float(p)
    return Answer(q.id, NOUL, True, value=p >= 0.5, probability=p if p >= 0.5 else 1 - p,
                  distribution={"true": p, "false": 1 - p})


def _read_choice(q: Choice, a: Mapping[str, Any]) -> Answer:
    """The winning key must be ONE WE DECLARED.

    Schema-constrained output is the vendor's claim, not our guarantee, and this is the one
    place a violation would be silent: an unrecognised key assigned into `value` travels on
    as though a caller's `match` had a branch for it. Refusing it costs an answer; accepting
    it costs a decision made on an option that does not exist.
    """
    won = a.get("choice")
    if not isinstance(won, str) or won not in q.options:
        return Answer(q.id, CHOICE, False,
                      reason=f"Jev chose {won!r}, which is not one of {list(q.options)}"[:200])
    dist = _probabilities(a, q.options)
    return Answer(q.id, CHOICE, True, value=won,
                  probability=dist.get(won, float(a.get("confidence") or 0.0)),
                  distribution=dist)


def _read_score(q: Score, a: Mapping[str, Any]) -> Answer:
    """`value` is the highest-probability LEVEL and `score` the continuous position.

    `value` is read from the distribution rather than from rounding the vendor's score, so
    it is derived exactly as the house backend derives it and the two cannot disagree about
    what "the level" is. The vendor's own float is kept as `score` — its guidance is to
    threshold that and never round it — and falls back to a weighting of the distribution
    when the field is missing, which is the same number the house backend would compute.
    """
    dist = _probabilities(a, q.levels)
    if not dist:
        return Answer(q.id, SCORE, False,
                      reason=f"Jev returned no usable level probabilities for {q.id}: {a!r}"[:200])
    best = max(q.levels, key=lambda n: dist.get(n, 0.0))
    raw = a.get("score")
    pos = float(raw) if isinstance(raw, (int, float)) else None
    if pos is None or not 0.0 <= pos <= len(q.levels) - 1:
        pos = weighted_score(q.levels, dist)
    return Answer(q.id, SCORE, True, value=best, probability=dist[best],
                  distribution=dist, score=pos)


class JevJudge:
    """The seam-shaped Jev backend: ``judge(state, questions) -> {id: Answer}``, never raises.

    All three primitives are accepted (CP-1). Noul shipped first because the banded cascade
    asked nothing else; Choice and Score land here because Arc CP's treatment judgement needs
    them and the seam has typed them since JD-1.

    **A Choice sends its option NAMES as their own criteria.** The vendor's `criteria` is a
    map of option → description, and `Choice` carries no descriptions — deliberately, because
    the house backend has nowhere to put one: its schema keys probabilities `p0..pN` with the
    names on the sub-fields. A criterion only one backend could read would make the same
    question mean two different things depending on who answered it, which is the exact drift
    the seam exists to prevent. If descriptions are wanted they belong on `Choice`, reaching
    both backends in the same commit.

    ``post`` is injectable so the hermetic tests never touch the network.
    """

    def __init__(self, api_key: str, model: str, *, url: str = DEFAULT_URL,
                 post: Optional[Callable[[str, dict, dict], dict]] = None):
        self.api_key, self.model, self.url = api_key, model, url
        self._post = post or _http_post

    # ── the four gates, then the wire ─────────────────────────────────────────────────────
    def judge(self, state: str, questions: Sequence[Any]) -> dict[str, Answer]:
        qs = list(questions)
        if not qs:
            return {}
        unknown = [q for q in qs if not isinstance(q, (Noul, Choice, Score))]
        if unknown:
            # Misuse by a caller, but this backend still keeps the seam's promise: an
            # answer, carrying the reason, never a raise into the query path.
            return self._unavailable(qs, "the Jev backend answers noul, choice and score only")

        withheld = self._pii_reason(state)
        if withheld:
            return self._unavailable(qs, withheld)

        body = {"model": self.model, "state": state,
                "questions": {q.id: _wire(q) for q in qs}}
        try:
            from aughor.govern.outbound import OutboundBlocked, external_call
            try:
                with external_call("typesafe", "systemone",
                                   attributes={"model": self.model, "questions": len(qs)}) as extra:
                    got = self._with_backoff(body)
                    usage = got.get("usage") or {}
                    extra["input_tokens"] = int(usage.get("input_tokens") or 0)
                    extra["output_tokens"] = int(usage.get("output_tokens") or 0)
            except OutboundBlocked as blocked:
                return self._unavailable(qs, f"outbound to TypeSafe blocked: {blocked.reason}")
        except Exception as exc:  # noqa: BLE001 — a failed bundle is an answer, as the seam says
            return self._unavailable(qs, f"the Jev call failed: {exc}")
        return self._read(qs, got)

    def _pii_reason(self, state: str) -> str:
        """Why this state must not leave, or "". A scanner failure withholds — the gate
        fails CLOSED, unlike a budget: permission unknown is permission absent."""
        try:
            from aughor.security.pii import PiiScanner
            found = PiiScanner.scan_and_redact(columns=["state"], rows=[[state]])
            if found.redacted_count:
                return (f"withheld from the third-party judge: {found.redacted_count} "
                        "redactable value(s) in the bundle's rows")
            return ""
        except Exception as exc:  # noqa: BLE001
            return f"withheld: the PII scan itself failed ({type(exc).__name__})"

    def _with_backoff(self, body: dict) -> dict:
        delay = BACKOFF_S
        for attempt in range(RETRIES + 1):
            try:
                return self._post(self.url, body, {"Authorization": f"Bearer {self.api_key}"})
            except _Retryable:
                if attempt == RETRIES:
                    raise
                time.sleep(delay)
                delay *= 2
        raise RuntimeError("unreachable")

    def _read(self, qs: Sequence[Any], got: Mapping[str, Any]) -> dict[str, Answer]:
        answers = got.get("answers") or {}
        out: dict[str, Answer] = {}
        for q in qs:
            a = answers.get(q.id) or {}
            if isinstance(q, Noul):
                out[q.id] = _read_noul(q, a)
            elif isinstance(q, Choice):
                out[q.id] = _read_choice(q, a)
            else:
                out[q.id] = _read_score(q, a)
        return out

    @staticmethod
    def _unavailable(qs: Sequence[Any], reason: str) -> dict[str, Answer]:
        return {q.id: Answer(q.id, _kind_of(q), False, reason=reason) for q in qs}


class FallbackJudge:
    """Jev first, the house LLM tier when Jev has no answer — an outage is yesterday, not worse.

    A bundle where EVERY answer came back unavailable (withheld, blocked, down) is re-judged
    through the seam on ``fallback`` — the same cheap LLM provider the cascade would have used
    with no Jev at all. Partial bundles are kept as-is: a per-question miss is real signal the
    band should route, not an outage. Counters accumulate for the operator's note.
    """

    def __init__(self, primary: JevJudge, fallback: Any):
        self.primary, self.fallback = primary, fallback
        self.bundles = 0
        self.fell_back = 0
        self.fallback_reasons: list[str] = []

    def judge(self, state: str, questions: Sequence[Any]) -> dict[str, Answer]:
        qs = list(questions)
        out = self.primary.judge(state, qs)
        self.bundles += 1
        if qs and out and all(not a.available for a in out.values()):
            reason = next(iter(out.values())).reason
            self.fell_back += 1
            if reason not in self.fallback_reasons:
                self.fallback_reasons.append(reason)
            logger.info("jev bundle fell back to the house tier: %s", reason)
            return seam_judge(state, qs, provider=self.fallback)
        return out

    def note(self, role: str) -> str:
        """One line for the operator's surface — who judged, and what never left the box."""
        parts = [f"cheap tier judged by TypeSafe Jev ({self.primary.model}) — a third party; "
                 f"{self.bundles} bundle(s)"]
        if self.fell_back:
            parts.append(f"{self.fell_back} answered by the house tier ({role}) instead: "
                         + "; ".join(self.fallback_reasons)[:200])
        return ", ".join(parts)


def cheap_judge_for(cheap_provider: Any, *, post: Optional[Callable] = None
                    ) -> "tuple[Any, str]":
    """What the banded cascade's cheap tier should be: ``(judge-or-provider, note-or-"")``.

    Flag off → the provider it was handed, untouched. Flag on but unconfigured → the
    provider, with the reason as a note so the operator sees WHY nothing changed (a flag
    that silently does nothing is two ways to be confused). Configured → a
    :class:`FallbackJudge` over Jev and that same provider.
    """
    from aughor.kernel.flags import flag_enabled
    if not flag_enabled("semops.jev_cheap_tier"):
        return cheap_provider, ""
    jev, why = configured_judge(post=post)
    if jev is None:
        return cheap_provider, f"semops.jev_cheap_tier is ON but unused: {why}"
    return FallbackJudge(jev, cheap_provider), ""


__all__ = ["JevJudge", "FallbackJudge", "configured_judge", "cheap_judge_for", "DEFAULT_URL"]
