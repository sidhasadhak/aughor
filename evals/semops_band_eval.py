"""JD-3's receipt — the banded cascade against today's sampled one, on the same rows.

`semantic_filter` has two ways to spend the strong ("champion") tier, and this harness runs both
over the SAME rows and the SAME predicate and counts what each one spends:

* **sampled** (today, flag off) — the cheap tier judges every row in batches of 25, the champion
  re-judges an evenly spread sample of ``validate_sample`` rows, and if more than 20% of that sample
  disagrees the champion re-runs EVERY row.
* **banded** (JD-3, flag ``semops.banded_cascade``) — the cheap tier states a probability per row
  through JD-1's seam, and only rows inside the 0.30-0.70 band (or unanswered) go to the champion.

A third arm, **reference**, runs the champion alone on every row — the answer the sampled cascade
converges to when it escalates, and the yardstick both arms are scored against. An optional fourth,
**banded-jev**, keeps the banded algorithm and the same champion but puts TypeSafe's Jev behind the
seam as the cheap tier (§3.20 JD-5, which is on HOLD for PRODUCTION; this harness is a measurement,
not a binding, and says what it sends and where).

**The receipt** (roadmap §3.20): strong-tier calls per filter, at equal agreement with the
reference. **The falsifier**: banding spends MORE champion calls than sampling at equal agreement —
then keep the sampled cascade. A run where the two arms' agreement differs by more than
``--tolerance`` settles nothing either way and says ``inconclusive``.

**Every arm runs the production code.** `semantic_filter` itself, with the flag set per arm by
``flag_overrides``; the harness only wraps the providers `get_provider` hands back, to count calls
per tier. The Jev arm swaps the seam's ``judge`` for the cheap tier alone, so `_banded_filter` runs
unchanged around it.

**What this touches.** Before importing `aughor` it isolates every store the way a live drive does
(`scripts/dump_openapi._isolate_stores`), so no process but the running API opens `data/`. Models
therefore resolve from the ENVIRONMENT (`AUGHOR_BACKEND`, `AUGHOR_FAST_NARRATOR_MODEL`,
`AUGHOR_CODER_MODEL` and their keys, loaded with ``--env-file``) — or, to measure the models a
deployment actually runs, from a COPY of its saved config named by ``AUGHOR_LLM_CONFIG_PATH`` (a JSON
file, copied, never read in place; its keys decrypt with ``AUGHOR_SECRET_KEY`` from the env file).
The output names the backend and model each tier resolved to. Rows come from a file: fetch them once
through the running API (see ``fetch_rows_sql``), never by opening a connection here.

Usage:

    # plan it — no model call
    uv run python evals/semops_band_eval.py --rows rows.json --dry-run
    # run it — model calls, the operator's spend
    uv run python evals/semops_band_eval.py --rows rows.json --env-file ../aughor/.env \\
        --output evals/semops_band_results.json [--jev]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

#: What production passes (`aughor/routers/query.py`), so the sampled arm is today's cascade.
DEFAULT_SAMPLE = 8
DEFAULT_BATCH = 25
#: Two arms "agree equally" when their agreement with the reference is within this.
DEFAULT_TOLERANCE = 0.02

#: Predicates over theLook's product names: one crisp, two with a real grey zone, because a
#: cascade that is only ever asked easy questions never escalates and measures nothing.
DEFAULT_PREDICATES = (
    "the product is outerwear: a coat, jacket, parka, blazer or vest",
    "the product is aimed at women",
    "the product is an accessory rather than a garment (e.g. a bag, belt, hat, scarf, jewellery)",
)

JEV_URL = "https://api.typesafe.ai/v1/systemone"
JEV_DEFAULT_MODEL = "jev-latest"


def fetch_rows_sql(limit: int = 200) -> str:
    """The query that produced the rows, for the record: theLook's product names, a spread sample
    by a stable hash so a re-fetch returns the same rows while the catalogue is unchanged."""
    return ("SELECT CAST(id AS STRING) AS id, name FROM `bigquery-public-data.thelook_ecommerce.products` "
            f"WHERE name IS NOT NULL ORDER BY FARM_FINGERPRINT(CAST(id AS STRING)) LIMIT {int(limit)}")


# ── pure helpers (the hermetic companion test imports these) ──────────────────────────────────

def load_rows(path: Path) -> list[str]:
    """A JSON list of strings, a list of objects with a ``name``, or ``{"rows": [...]}``."""
    data = json.loads(Path(path).read_text())
    if isinstance(data, dict):
        data = data.get("rows") or []
    out = []
    for r in data:
        if isinstance(r, str):
            out.append(r)
        elif isinstance(r, Mapping) and r.get("name"):
            out.append(str(r["name"]))
        elif isinstance(r, (list, tuple)) and r:
            out.append(str(r[-1]))
    if not out:
        raise ValueError(f"{path}: no rows")
    return out


def planned_calls(n: int, *, batch: int = DEFAULT_BATCH, sample: int = DEFAULT_SAMPLE,
                  jev: bool = False, reference: bool = True) -> dict:
    """Calls each arm can make on ``n`` rows, as ``{arm: {tier: (min, max)}}``. The band's and the
    escalation's spend depend on the answers, so each is a range — the dry run's honest number."""
    b = max(1, batch)
    per = math.ceil(n / b)
    k = min(sample, n)
    plan = {
        "sampled": {"cheap": (per, per), "champion": (math.ceil(k / b), math.ceil(k / b) + per)},
        "banded": {"cheap": (per, per), "champion": (0, per)},
    }
    if reference:
        plan["reference"] = {"champion": (per, per)}
    if jev:
        plan["banded-jev"] = {"jev": (per, per), "champion": (0, per)}
    return plan


def total_range(plan: Mapping[str, Mapping[str, tuple]]) -> tuple[int, int]:
    lo = sum(r[0] for tiers in plan.values() for r in tiers.values())
    hi = sum(r[1] for tiers in plan.values() for r in tiers.values())
    return lo, hi


def agreement(a: set, b: set, n: int, *, exclude: frozenset = frozenset()) -> float:
    """Share of the ``n`` rows two arms decide the same way (kept by both, or by neither), over
    the rows not in ``exclude``."""
    pop = [i for i in range(n) if i not in exclude]
    if not pop:
        raise ValueError("agreement over no rows is undefined")
    return sum(1 for i in pop if (i in a) == (i in b)) / len(pop)


def accuracy(kept: set, gold: Mapping[int, bool], *, exclude: frozenset = frozenset()) -> float:
    """Share of the LABELLED rows (minus ``exclude``) an arm decides the way the gold set does."""
    pop = [i for i in gold if i not in exclude]
    if not pop:
        raise ValueError("accuracy over no labelled rows is undefined")
    return sum(1 for i in pop if (i in kept) == bool(gold[i])) / len(pop)


#: Row indices a prompt carries: today's batch prompt lists ``[gi] text``, the seam ``- r<gi> [...]``.
_ROW_MARKS = (re.compile(r"^\[(\d+)\]", re.M), re.compile(r"^- r(\d+) \[", re.M))


def rows_in(prompt: str) -> set[int]:
    return {int(m) for pat in _ROW_MARKS for m in pat.findall(prompt or "")}


@dataclass
class ArmResult:
    name: str
    available: bool
    kept: set = field(default_factory=set)
    #: Rows some call of this arm failed on. A failed batch is KEPT by the operator (fail-open),
    #: so without this a row no model judged would score as a decision.
    unjudged: set = field(default_factory=set)
    calls: dict = field(default_factory=dict)          # tier -> calls
    prompt_chars: dict = field(default_factory=dict)   # tier -> chars sent (≈ 4 chars a token)
    tokens: dict = field(default_factory=dict)         # tier -> tokens a provider REPORTED
    notes: list = field(default_factory=list)
    reason: str = ""

    def __post_init__(self) -> None:
        if not self.available and not self.reason.strip():
            raise ValueError(f"{self.name}: an unavailable arm must carry its reason")

    def as_dict(self, n: int, reference: Optional["ArmResult"], *, gold: Optional[Mapping[int, bool]] = None,
                exclude: frozenset = frozenset()) -> dict:
        d = {"arm": self.name, "available": self.available, "reason": self.reason,
             "calls": dict(self.calls), "approx_prompt_tokens": {t: c // 4 for t, c in self.prompt_chars.items()},
             "reported_tokens": dict(self.tokens), "kept": len(self.kept),
             "kept_rows": sorted(self.kept), "unjudged_rows": sorted(self.unjudged), "notes": list(self.notes)}
        if self.available and reference is not None and reference.available:
            d["agreement_with_reference"] = round(agreement(self.kept, reference.kept, n, exclude=exclude), 4)
        if self.available and gold:
            d["accuracy_vs_gold"] = round(accuracy(self.kept, gold, exclude=exclude), 4)
        return d


def verdict(arms: Mapping[str, ArmResult], n: int, *, tolerance: float = DEFAULT_TOLERANCE,
            banded: str = "banded", gold: Optional[Mapping[int, bool]] = None,
            exclude: frozenset = frozenset()) -> dict:
    """The receipt for one predicate: does ``banded`` spend fewer champion calls than ``sampled``
    at equal quality? Quality is accuracy against ``gold`` when a gold set is given, else agreement
    with the reference arm — always over the same rows, minus ``exclude``.
    Typed: ``holds`` · ``falsified`` · ``inconclusive``."""
    s, b, ref = arms.get("sampled"), arms.get(banded), arms.get("reference")
    needed = (("sampled", s), (banded, b)) + (() if gold else (("reference", ref),))
    missing = [name for name, a in needed if a is None or not a.available]
    if missing:
        return {"verdict": "inconclusive", "reason": f"no reading from {', '.join(missing)}"}
    if gold:
        yardstick, q_s, q_b = "gold", accuracy(s.kept, gold, exclude=exclude), accuracy(b.kept, gold, exclude=exclude)
    else:
        yardstick = "reference"
        q_s, q_b = (agreement(s.kept, ref.kept, n, exclude=exclude),
                    agreement(b.kept, ref.kept, n, exclude=exclude))
    cs, cb = s.calls.get("champion", 0), b.calls.get("champion", 0)
    out = {"yardstick": yardstick, "sampled_champion_calls": cs, "banded_champion_calls": cb,
           "sampled_score": round(q_s, 4), "banded_score": round(q_b, 4), "tolerance": tolerance,
           "excluded_rows": len(exclude)}
    if abs(q_s - q_b) > tolerance:
        better = banded if q_b > q_s else "sampled"
        return {**out, "verdict": "inconclusive",
                "reason": f"the arms do not score equally against the {yardstick} ({q_s:.1%} vs {q_b:.1%}; "
                          f"{better} is better), so their spend is not comparable"}
    if cb > cs:
        return {**out, "verdict": "falsified",
                "reason": f"banding spent MORE champion calls ({cb} vs {cs}) at equal quality — "
                          "keep the sampled cascade"}
    return {**out, "verdict": "holds",
            "reason": f"banding spent {cb} champion call(s) against sampling's {cs}, at equal quality"}


# ── the providers, counted ────────────────────────────────────────────────────────────────────

class Counted:
    """A provider that counts its calls and the characters it sends, per tier, and otherwise IS the
    provider it wraps — `complete` is the only structured call the cascade makes."""

    def __init__(self, inner, tier: str, arm: ArmResult):
        self._inner, self._tier, self._arm = inner, tier, arm

    def complete(self, **kw):
        self._arm.calls[self._tier] = self._arm.calls.get(self._tier, 0) + 1
        chars = len(str(kw.get("system") or "")) + len(str(kw.get("user") or ""))
        self._arm.prompt_chars[self._tier] = self._arm.prompt_chars.get(self._tier, 0) + chars
        try:
            return self._inner.complete(**kw)
        except Exception:
            self._arm.unjudged |= rows_in(str(kw.get("user") or ""))
            raise

    def __getattr__(self, name):
        return getattr(self._inner, name)


class JevBackend:
    """TypeSafe's Jev behind the seam: one ``POST /v1/systemone`` per bundle, each row a ``noul``
    question whose instructions carry the row as data. The request shape is the vendor's documented
    one (docs.typesafe.ai/api, read 2026-09-21). ``post`` is injectable so the companion test never
    touches the network."""

    def __init__(self, api_key: str, arm: ArmResult, *, model: str = JEV_DEFAULT_MODEL,
                 url: str = JEV_URL, post: Optional[Callable[[str, dict, dict], dict]] = None,
                 retries: int = 4, backoff: float = 1.5):
        self.api_key, self.arm, self.model, self.url = api_key, arm, model, url
        self._post = post or _http_post
        self.retries, self.backoff = retries, backoff

    def judge(self, state: str, questions: Sequence[Any]) -> dict:
        from aughor.judgment.seam import NOUL, Answer, Noul
        qs = list(questions)
        if not all(isinstance(q, Noul) for q in qs):
            raise ValueError("this harness sends Jev noul questions only")
        body = {"model": self.model, "state": state,
                "questions": {q.id: {"type": "noul", "instructions": q.proposition} for q in qs}}
        self.arm.calls["jev"] = self.arm.calls.get("jev", 0) + 1
        self.arm.prompt_chars["jev"] = self.arm.prompt_chars.get("jev", 0) + len(json.dumps(body))
        try:
            got = self._with_backoff(body)
        except Exception as exc:  # noqa: BLE001 — a failed bundle is an answer, as the seam says
            self.arm.unjudged |= _row_ids(q.id for q in qs)
            return {q.id: Answer(q.id, NOUL, False, reason=f"the Jev call failed: {exc}") for q in qs}
        usage = got.get("usage") or {}
        for k in ("input_tokens", "output_tokens"):
            self.arm.tokens[f"jev_{k}"] = self.arm.tokens.get(f"jev_{k}", 0) + int(usage.get(k) or 0)
        answers = got.get("answers") or {}
        out = {}
        for q in qs:
            a = answers.get(q.id) or {}
            p = a.get("noul")
            if not isinstance(p, (int, float)) or not 0.0 <= float(p) <= 1.0:
                self.arm.unjudged |= _row_ids([q.id])
                out[q.id] = Answer(q.id, NOUL, False, reason=f"Jev returned no noul for {q.id}: {a!r}"[:200])
                continue
            p = float(p)
            out[q.id] = Answer(q.id, NOUL, True, value=p >= 0.5, probability=p if p >= 0.5 else 1 - p,
                               distribution={"true": p, "false": 1 - p})
        return out

    def _with_backoff(self, body: dict) -> dict:
        delay = self.backoff
        for attempt in range(self.retries + 1):
            try:
                return self._post(self.url, body, {"Authorization": f"Bearer {self.api_key}"})
            except _Retryable:
                if attempt == self.retries:
                    raise
                time.sleep(delay)
                delay *= 2
        raise RuntimeError("unreachable")


def _row_ids(ids) -> set[int]:
    """The rows behind the seam's question ids (``r<gi>``)."""
    return {int(i[1:]) for i in ids if str(i)[1:].isdigit()}


class _Retryable(Exception):
    """A 429 or 529: back off and retry, as the vendor's documentation asks."""


def _http_post(url: str, body: dict, headers: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        if exc.code in (429, 529):
            raise _Retryable(f"HTTP {exc.code}") from exc
        detail = exc.read().decode(errors="replace")[:300]
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc


# ── running one arm through the production operator ───────────────────────────────────────────

def run_arm(name: str, rows: Sequence[str], predicate: str, *, banded: bool,
            cheap: Any, champion: Any, sample: int = DEFAULT_SAMPLE, batch: int = DEFAULT_BATCH,
            role: str = "fast") -> ArmResult:
    """One arm: `semantic_filter` as production runs it, with the flag set for this arm alone and
    `get_provider` answering the two tiers this arm names. ``cheap`` is a provider, or a
    :class:`JevBackend` for the Jev arm; ``champion`` is a provider."""
    from aughor.agent.state import QueryResult
    from aughor.judgment import seam
    from aughor.kernel.flags import flag_overrides
    from aughor.semops import operators as ops

    arm = ArmResult(name, True)
    tiers = {role: cheap, ops.CHAMPION_ROLE: champion}
    # Named by the role, not by position: the reference arm runs the champion as its ONLY role.
    wrapped = {r: (p if isinstance(p, JevBackend)
                   else Counted(p, "champion" if r == ops.CHAMPION_ROLE else "cheap", arm))
               for r, p in tiers.items()}
    if isinstance(cheap, JevBackend):
        cheap.arm = arm
    original_get, original_judge = ops.get_provider, seam.judge

    def get_provider(r, **kw):
        if r not in wrapped:
            raise RuntimeError(f"the harness gave this arm no provider for role {r!r}")
        return wrapped[r]

    def judge(state, questions, *, provider=None, **kw):
        if isinstance(provider, JevBackend):
            return provider.judge(state, questions)
        return original_judge(state, questions, provider=provider, **kw)

    result = QueryResult(hypothesis_id="semops_band_eval", sql="-- semops_band_eval", columns=["i", "text"],
                         rows=[[i, t] for i, t in enumerate(rows)], row_count=len(rows))
    ops.get_provider, seam.judge = get_provider, judge
    try:
        with flag_overrides({"semops.banded_cascade": banded}):
            out = ops.semantic_filter(result, "text", predicate, role=role, batch=batch,
                                      validate_sample=sample, max_rows=max(len(rows), 1))
    finally:
        ops.get_provider, seam.judge = original_get, original_judge
    arm.kept = {r[0] for r in out.result.rows}
    arm.notes = list(out.notes)
    return arm


def run_reference(rows: Sequence[str], predicate: str, champion: Any, *,
                  batch: int = DEFAULT_BATCH) -> ArmResult:
    """The champion alone on every row, through the same operator with no cascade — the answer the
    sampled cascade converges to when it escalates."""
    from aughor.semops import operators as ops
    return run_arm("reference", rows, predicate, banded=False, cheap=champion, champion=champion,
                   sample=0, batch=batch, role=ops.CHAMPION_ROLE)


def run_predicate(rows: Sequence[str], predicate: str, *, cheap, champion, jev: Optional[JevBackend],
                  sample: int, batch: int, tolerance: float, reference: bool = True,
                  gold: Optional[Mapping[int, bool]] = None) -> dict:
    arms: dict[str, ArmResult] = {}
    if reference:
        arms["reference"] = run_reference(rows, predicate, champion, batch=batch)
    arms["sampled"] = run_arm("sampled", rows, predicate, banded=False, cheap=cheap,
                              champion=champion, sample=sample, batch=batch)
    arms["banded"] = run_arm("banded", rows, predicate, banded=True, cheap=cheap,
                             champion=champion, sample=sample, batch=batch)
    if jev is not None:
        arms["banded-jev"] = run_arm("banded-jev", rows, predicate, banded=True, cheap=jev,
                                     champion=champion, sample=sample, batch=batch)
    return score_predicate(predicate, len(rows), arms, tolerance=tolerance, gold=gold)


def score_predicate(predicate: str, n: int, arms: Mapping[str, ArmResult], *, tolerance: float,
                    gold: Optional[Mapping[int, bool]] = None) -> dict:
    """Every arm scored on the SAME rows: any row some call failed on, in any arm, is excluded from
    all of them — a fail-open row is a row no model decided, and scoring it would reward the arm
    that happened to fail on it."""
    exclude = frozenset().union(*(a.unjudged for a in arms.values()))
    ref = arms.get("reference")
    out = {"predicate": predicate, "rows": n, "excluded_rows": sorted(exclude),
           "yardstick": "gold" if gold else "reference",
           "arms": {k: a.as_dict(n, ref, gold=gold, exclude=exclude) for k, a in arms.items()},
           "verdict": verdict(arms, n, tolerance=tolerance, gold=gold, exclude=exclude)}
    if "banded-jev" in arms:
        out["verdict_jev"] = verdict(arms, n, tolerance=tolerance, banded="banded-jev", gold=gold, exclude=exclude)
    return out


# ── entry point ───────────────────────────────────────────────────────────────────────────────

def _isolate() -> None:
    """Every store off `data/` before `aughor` is imported — the live-drive isolation, reused."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("_dump_openapi", REPO / "scripts" / "dump_openapi.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod._isolate_stores()


def _load_env_file(path: Path) -> list[str]:
    """``KEY=VALUE`` lines into the environment WITHOUT overriding what is set (so the isolation
    above wins over any store path the file names). Returns the keys loaded — never the values."""
    loaded = []
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip().removeprefix("export ").strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v
            loaded.append(k)
    return loaded


def load_gold(path: Path) -> dict[str, dict[int, bool]]:
    """``{predicate: {row: label}}`` from a gold file: a list of ``{predicate, gold: {row: bool}}``."""
    data = json.loads(Path(path).read_text())
    return {e["predicate"]: {int(i): bool(v) for i, v in (e.get("gold") or {}).items()} for e in data}


def rescore(results: Mapping[str, Any], gold: Mapping[str, Mapping[int, bool]], *,
            tolerance: float) -> list[dict]:
    """Score a saved run again — against a gold set, say — with no model call."""
    out = []
    for p in results.get("predicates") or []:
        arms = {}
        for name, a in (p.get("arms") or {}).items():
            if "kept_rows" not in a:
                raise ValueError(f"{name} on {p['predicate']!r} carries no kept_rows: that run predates rescoring")
            arms[name] = ArmResult(name, bool(a.get("available", True)), kept=set(a["kept_rows"]),
                                   unjudged=set(a.get("unjudged_rows") or []), calls=dict(a.get("calls") or {}),
                                   notes=list(a.get("notes") or []), reason=a.get("reason") or "")
        out.append(score_predicate(p["predicate"], int(p["rows"]), arms, tolerance=tolerance,
                                   gold=gold.get(p["predicate"])))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rows", required=True, help="JSON rows file (see load_rows)")
    ap.add_argument("--predicate", action="append", help="repeatable; defaults to three over product names")
    ap.add_argument("--sample", type=int, default=DEFAULT_SAMPLE)
    ap.add_argument("--batch", type=int, default=DEFAULT_BATCH)
    ap.add_argument("--tolerance", type=float, default=DEFAULT_TOLERANCE)
    ap.add_argument("--no-reference", action="store_true", help="skip the champion-on-every-row arm")
    ap.add_argument("--jev", action="store_true", help="add the Jev arm (needs TYPESAFE_API_KEY)")
    ap.add_argument("--jev-model", default=JEV_DEFAULT_MODEL)
    ap.add_argument("--env-file", help="load model keys from this file (values are never printed)")
    ap.add_argument("--dry-run", action="store_true", help="print the planned calls and stop")
    ap.add_argument("--gold", help="gold labels (see load_gold): score accuracy against them")
    ap.add_argument("--rescore", help="a saved results file to score again — no model call")
    ap.add_argument("--output", default="")
    args = ap.parse_args()
    gold = load_gold(Path(args.gold)) if args.gold else {}

    if args.rescore:
        report = json.loads(Path(args.rescore).read_text())
        report["predicates"] = rescore(report, gold, tolerance=args.tolerance)
        _print(report["predicates"])
        if args.output:
            Path(args.output).write_text(json.dumps(report, indent=2))
            print(f"\nwrote {args.output}")
        return

    rows = load_rows(Path(args.rows))
    predicates = tuple(args.predicate or DEFAULT_PREDICATES)
    plan = planned_calls(len(rows), batch=args.batch, sample=args.sample, jev=args.jev,
                         reference=not args.no_reference)
    lo, hi = total_range(plan)
    print(f"{len(rows)} rows × {len(predicates)} predicate(s); per predicate: {json.dumps(plan)}")
    print(f"model calls in total: {lo * len(predicates)} to {hi * len(predicates)}")
    if args.dry_run:
        return

    _isolate()
    if args.env_file:
        keys = _load_env_file(Path(args.env_file))
        print(f"loaded {len(keys)} key(s) from {args.env_file} (values not shown)")
    from aughor.llm import provider as llm
    from aughor.semops import operators as ops
    cheap, champion = llm.get_provider(ops.DEFAULT_ROLE), llm.get_provider(ops.CHAMPION_ROLE)
    cfg = llm.current_config()                    # the same effective view GET /llm/config serves
    models = {"backend": cfg.get("backend"), "cheap": (cfg.get("models") or {}).get(ops.DEFAULT_ROLE),
              "champion": (cfg.get("models") or {}).get(ops.CHAMPION_ROLE),
              "config": os.environ.get("AUGHOR_LLM_CONFIG_PATH") or "(isolated: environment only)"}
    print(f"tiers resolved: {models}")
    if models["cheap"] and models["cheap"] == models["champion"]:
        print("⚠️ the cheap and champion tiers are the SAME model: the cascade's escalations re-ask it")

    jev = None
    if args.jev:
        key = os.environ.get("TYPESAFE_API_KEY", "")
        if not key:
            raise SystemExit("--jev needs TYPESAFE_API_KEY (in the environment or --env-file); nothing was sent")
        print(f"the Jev arm sends these {len(rows)} product names to {JEV_URL} ({args.jev_model})")
        jev = JevBackend(key, ArmResult("banded-jev", True), model=args.jev_model)

    report = {"rows_file": args.rows, "rows": len(rows), "sample": args.sample, "batch": args.batch,
              "models": models, "jev_model": args.jev_model if jev else None,
              "fetched_with": fetch_rows_sql(len(rows)), "predicates": []}
    for pred in predicates:
        res = run_predicate(rows, pred, cheap=cheap, champion=champion, jev=jev, sample=args.sample,
                            batch=args.batch, tolerance=args.tolerance, reference=not args.no_reference,
                            gold=gold.get(pred))
        report["predicates"].append(res)
        _print([res])
    if args.output:
        Path(args.output).write_text(json.dumps(report, indent=2))
        print(f"\nwrote {args.output}")


def _print(predicates: Sequence[Mapping[str, Any]]) -> None:
    for res in predicates:
        v = res["verdict"]
        print(f"\n{res['predicate']}\n  {v['verdict']}: {v['reason']}"
              f"  [excluded {len(res.get('excluded_rows') or [])} unjudged row(s)]")
        for a in res["arms"].values():
            print(f"  {a['arm']:<11} calls={a['calls']} kept={a['kept']} "
                  f"agree={a.get('agreement_with_reference', '-')} gold={a.get('accuracy_vs_gold', '-')}")
        if "verdict_jev" in res:
            print(f"  jev: {res['verdict_jev']['verdict']}: {res['verdict_jev']['reason']}")


if __name__ == "__main__":
    main()
