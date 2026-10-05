"""The scenario ladder's first three methods, behind one interface (the 2027 study §L; phase 3,
P3-2), and the scorer that closes a prediction when its range is Final.

A scenario answer carries the METHOD that produced it and takes the weakest method on its path as
its tier. Three methods are built here, each returning a :class:`Projection` that says what it
must say:

1. **identity** — deterministic arithmetic inside a declared formula (price × units, the margin
   tree) over inputs a caller gives; must say what is held fixed. A restricted expression (names,
   numbers, + − × ÷), never ``eval``.
2. **declared** — a person's assumption ("if demand stays elevated for 30 days"), booked as a
   claim at tier ``declared`` with their name on it; must say whose assumption it is.
3. **history** — what the metric's own settled past predicts for a window of the same length: the
   mean of the prior windows and an interval at a stated coverage, with the method's BACKTEST on
   this metric (each past window predicted from the ones before it: mean absolute error, and how
   often the interval would have held). Must say its interval and that error.

4. **intervention** (phase 5, P5-4) — what decisions of this kind did before, on THIS install: the
   measured effects of past Outcome entries (actual against the metric's own history) for decisions
   that ran the same declared action or asked the same question, their mean and band, and how many
   cases that rests on. Reads Outcome entries and nothing else; projects nothing below
   :data:`INTERVENTION_MIN_CASES` and says so. Must say the count of past cases.

Methods 5–6 (simulation, learned) are not here; the interface refuses a method it does not know
rather than guessing. What the platform never does is let a model supply a number on this ladder —
there is no ``llm_inferred`` provenance and no method named for one.

A prediction made under a scenario is a prediction CLAIM (`record/claims.py`) carrying its method,
its band, what it assumed and — where its spec is measurable — how to score it. The settle tick
scores every open prediction whose range is Final (:func:`score_due_predictions`), by code; the
result lands on the claim as ``scored_against`` with the actual, and :func:`calibration` counts
interval coverage by method, metric and author. A scenario with no decision attached is a toy, so
a Scenario is booked FOR a decision, an inquiry or a mission (kind ``scenario``, no new store).
"""
from __future__ import annotations

import ast
import datetime as _dt
import math
import operator
from typing import Any, Callable, Optional

from pydantic import BaseModel, Field

from aughor.record import claims as _claims

KIND = "scenario"
METHODS: tuple[str, ...] = ("identity", "declared", "history", "intervention")
#: How many prior windows the history method reads, and the coverage its interval states.
HISTORY_WINDOWS = 6
HISTORY_COVERAGE = 0.8
#: The fewest past reviewed decisions method 4 projects from — the same floor as history's windows.
INTERVENTION_MIN_CASES = 3
#: Two decisions ask the same question when their content words overlap this far (Jaccard).
SAME_DECISION = 0.5
#: z for an 80% two-sided normal interval — the coverage is STATED, and the backtest says how
#: often it held, which is the number a reader should trust over the z.
_Z80 = 1.2816

RunSql = Callable[[str], tuple]


class Projection(BaseModel):
    method: str
    tier: str = ""                         # a registered method's declared tier; "" for a built-in
    value: Optional[float] = None
    low: Optional[float] = None
    high: Optional[float] = None
    coverage: Optional[float] = None       # the interval's stated coverage
    unit: str = ""
    must_say: list[str] = Field(default_factory=list)
    backtest: dict[str, Any] = Field(default_factory=dict)   # history: {n, mae, mape, held, of, coverage_observed}
    inputs: dict[str, Any] = Field(default_factory=dict)
    claim: str = ""                        # declared: the assumption's claim id
    note: str = ""                         # why a method could not project, when it could not


class Assumption(BaseModel):
    variable: str
    value: Optional[float] = None
    source: str = "declared"               # declared by a person | measured | estimated
    by: str = ""
    text: str = ""
    claim: str = ""


class Scenario(BaseModel):
    for_kind: str                          # decision | inquiry | mission
    for_id: str
    question: str = ""
    assumptions: list[Assumption] = Field(default_factory=list)
    predictions: list[str] = Field(default_factory=list)     # prediction claim ids
    limits: list[str] = Field(default_factory=list)          # in words
    methods: list[str] = Field(default_factory=list)
    tier: str = ""                         # the weakest method on its path
    connection_id: str = ""
    extra: dict[str, Any] = Field(default_factory=dict)
    id: str = ""
    key: str = ""
    version: int = 0
    recorded_at: str = ""


def _ledger():
    from aughor.kernel.ledger import Ledger
    return Ledger.default()


def _today() -> _dt.date:
    return _dt.datetime.now(_dt.timezone.utc).date()


# ── method 1: identity ─────────────────────────────────────────────────────────────────────

_ARITH = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}


class FormulaRefused(ValueError):
    """The formula reached outside arithmetic over named inputs."""


def _arith(node: ast.AST, inputs: dict[str, float]) -> float:
    if isinstance(node, ast.Expression):
        return _arith(node.body, inputs)
    if isinstance(node, ast.BinOp) and type(node.op) in _ARITH:
        left, right = _arith(node.left, inputs), _arith(node.right, inputs)
        if isinstance(node.op, ast.Div) and right == 0:
            raise FormulaRefused("division by zero in the formula")
        return _ARITH[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        v = _arith(node.operand, inputs)
        return -v if isinstance(node.op, ast.USub) else v
    if isinstance(node, ast.Name):
        if node.id not in inputs:
            raise FormulaRefused(f"the formula names '{node.id}', which no input supplies")
        return float(inputs[node.id])
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return float(node.value)
    raise FormulaRefused(f"not arithmetic over named inputs: {type(node).__name__}")


def identity(formula: str, inputs: dict[str, float], *, unit: str = "",
             varied: Optional[list[str]] = None) -> Projection:
    """Method 1 — the arithmetic inside a declared formula, exactly. ``varied`` names the inputs
    the scenario changes; every other input is held fixed, and the projection says so."""
    try:
        tree = ast.parse(str(formula or ""), mode="eval")
    except SyntaxError as exc:
        raise FormulaRefused(f"the formula is not an expression: {exc}") from exc
    value = _arith(tree, {k: float(v) for k, v in (inputs or {}).items()})
    fixed = sorted(k for k in (inputs or {}) if k not in set(varied or []))
    return Projection(method="identity", value=value, low=value, high=value, coverage=1.0, unit=unit,
                      inputs=dict(inputs or {}),
                      must_say=[f"held fixed: {', '.join(fixed)}" if fixed else "nothing held fixed",
                                f"exact under the formula {formula}"])


# ── method 2: declared ─────────────────────────────────────────────────────────────────────

def declared(*, variable: str, value: Optional[float], by: str, text: str = "", unit: str = "",
             connection_id: str = "", low: Optional[float] = None, high: Optional[float] = None) -> Projection:
    """Method 2 — a person's assumption, booked as a claim at tier ``declared`` in their name;
    the projection says whose assumption it is. Refuses an assumption with nobody's name on it."""
    if not (by or "").strip():
        raise _claims.ClaimRefused("a declared assumption carries the name of the person who made it")
    statement = (text or "").strip() or (f"{variable} = {value}{unit}" if value is not None else variable)
    claim = _claims.Claim(
        kind="said", tier="declared",
        about=_claims.About(kind="connection", key=connection_id) if connection_id else _claims.About(kind="organisation", key=""),
        statement=_claims.Statement(text=f"assumption: {statement}"[:1000], metric=variable, value=value, unit=unit),
        status="Provisional", as_of=_today().isoformat(), author=by, author_kind="person",
        extra={"method": "declared", "variable": variable, "low": low, "high": high},
    )
    cid = _claims.book(claim, key=_claims.claim_key("assumption", connection_id or "-", variable,
                                                    _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%S%f")),
                       conn_id=connection_id or None)
    return Projection(method="declared", value=value, low=low if low is not None else value,
                      high=high if high is not None else value, coverage=None, unit=unit, claim=cid,
                      must_say=[f"{by}'s assumption, not a measurement", f"booked as claim {cid}"])


# ── method 3: history ──────────────────────────────────────────────────────────────────────

def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs)


def _sd(xs: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def backtest(values: list[float], *, coverage: float = HISTORY_COVERAGE) -> dict[str, Any]:
    """Each window predicted from the ones before it (from the third on): the mean absolute error,
    the mean absolute percentage error, and how often the stated interval held — the number that
    says what the coverage was worth on THIS metric."""
    z = _Z80 if abs(coverage - 0.8) < 1e-9 else 1.96 if coverage >= 0.95 else _Z80
    errors, pct, held, of = [], [], 0, 0
    for i in range(2, len(values)):
        prior, actual = values[:i], values[i]
        mu, sd = _mean(prior), _sd(prior)
        errors.append(abs(actual - mu))
        if mu:
            pct.append(abs(actual - mu) / abs(mu))
        of += 1
        held += (mu - z * sd) <= actual <= (mu + z * sd)
    return {"n": len(values), "cases": of, "mae": round(_mean(errors), 4) if errors else None,
            "mape": round(_mean(pct), 4) if pct else None,
            "held": held, "coverage_observed": round(held / of, 3) if of else None, "coverage_stated": coverage}


def history(spec: dict, run_sql: RunSql, *, end_day: Optional[_dt.date] = None, windows: int = HISTORY_WINDOWS,
            coverage: float = HISTORY_COVERAGE) -> Projection:
    """Method 3 — what the metric's own past predicts for the window ending ``end_day``: the mean of
    the ``windows`` prior same-length windows, an interval at the stated coverage, and the backtest
    on those windows. A definition that cannot be measured alone, or a past with fewer than three
    readable windows, projects nothing and says why."""
    from aughor.playbook.outcomes import measurement_sql
    end_day = end_day or (_today() - _dt.timedelta(days=1))
    days = max(1, int((spec or {}).get("window_days") or 1))
    values: list[float] = []
    labels: list[str] = []
    for k in range(windows, 0, -1):
        window_end = end_day - _dt.timedelta(days=days * k)
        sql, label, why = measurement_sql(spec or {}, end_day=window_end)
        if sql is None:
            return Projection(method="history", note=why, must_say=[why])
        try:
            columns, rows, error = run_sql(sql)
        except Exception as exc:  # noqa: BLE001 — a window that cannot be read is said, never guessed
            return Projection(method="history", note=f"the window {label} could not be measured: {str(exc)[:120]}")
        if error or not rows or rows[0] is None or rows[0][0] is None:
            continue
        try:
            value = float(rows[0][0])
        except (TypeError, ValueError):
            value = None       # a window whose cell is not a number is not a reading
        if value is None:
            continue
        values.append(value)
        labels.append(label)
    if len(values) < 3:
        return Projection(method="history", note=f"only {len(values)} prior window{'s' if len(values) != 1 else ''} "
                                                 f"held a reading; three are the least a baseline is drawn from",
                          backtest={"n": len(values)})
    mu, sd = _mean(values), _sd(values)
    bt = backtest(values, coverage=coverage)
    low, high = mu - _Z80 * sd, mu + _Z80 * sd
    return Projection(method="history", value=round(mu, 6), low=round(low, 6), high=round(high, 6), coverage=coverage,
                      backtest=bt, inputs={"windows": labels},
                      must_say=[f"{len(values)} prior windows of {days} day{'s' if days != 1 else ''}: {_fmt(low)} to {_fmt(high)} "
                                f"at {int(coverage * 100)}% stated coverage",
                                (f"backtest on this metric: mean absolute error {_fmt(bt['mae'])}"
                                 + (f" ({bt['mape']:.1%})" if bt.get("mape") is not None else "")
                                 + (f"; the interval held {bt['held']} of {bt['cases']} times" if bt.get("cases") else
                                    "; too few windows to test the interval"))])


def _fmt(v: Optional[float]) -> str:
    if v is None:
        return "—"
    return f"{v:,.2f}".rstrip("0").rstrip(".") if abs(v) >= 1000 else f"{v:.4g}"


# ── method 4: intervention ─────────────────────────────────────────────────────────────────

def _same_question(a: str, b: str) -> bool:
    from aughor.record.inquiry import content_words
    wa, wb = content_words(a), content_words(b)
    if not wa or not wb:
        return False
    return len(wa & wb) / len(wa | wb) >= SAME_DECISION


def intervention_cases(*, metric: str, connection_id: str = "", action_id: str = "", like: str = "",
                       min_cases: int = INTERVENTION_MIN_CASES) -> list[dict]:
    """The past cases method 4 reads: every Outcome on this install whose decision ran ``action_id``
    or asked the same question as ``like``, on ``metric``, with a measured effect against the
    metric's own history. Each case is the outcome's id, the decision's, the effect and the verdict."""
    from aughor.record import decisions as D
    want = (metric or "").strip().lower()
    cases: list[dict] = []
    for d in D.list_decisions(conn_id=connection_id or None, limit=2000):
        if not d.outcome:
            continue
        same_action = bool(action_id) and action_id in (d.actions or [])
        same_q = bool(like) and _same_question(like, d.question)
        if not (same_action or same_q):
            continue
        o = D.outcome_by_id(d.outcome)
        if o is None or o.effect.value is None:
            continue
        pred = _claims.get(d.expectation_claim) if d.expectation_claim else None
        case_metric = (pred.statement.metric if pred else "") or str((o.extra.get("spec") or {}).get("metric_label") or "")
        if want and case_metric and case_metric.strip().lower() != want:
            continue
        cases.append({"outcome": o.id, "decision": d.id, "effect": float(o.effect.value), "verdict": o.verdict,
                      "measured_on": o.measured_on, "method": o.effect.method, "question": d.question[:160],
                      "matched_on": "action" if same_action else "question"})
    return cases


def intervention(*, metric: str, connection_id: str = "", action_id: str = "", like: str = "", unit: str = "",
                 min_cases: int = INTERVENTION_MIN_CASES, coverage: float = HISTORY_COVERAGE) -> Projection:
    """Method 4 — the effect decisions of this kind had before, on this install, read from Outcome
    entries and nothing else: the mean measured effect, a band at the stated coverage, the count of
    cases and how many went the wanted way. Projects nothing below ``min_cases`` and says so."""
    if not (action_id or like):
        return Projection(method="intervention", note="method 4 needs the kind of decision: the declared action it ran, "
                                                      "or the question it asked", must_say=["no decision kind named"])
    cases = intervention_cases(metric=metric, connection_id=connection_id, action_id=action_id, like=like, min_cases=min_cases)
    n = len(cases)
    if n < min_cases:
        return Projection(method="intervention", backtest={"n": n},
                          note=f"only {n} past decision{'s' if n != 1 else ''} of this kind {'has' if n == 1 else 'have'} a measured "
                               f"outcome on this install; {min_cases} are the least an effect is read from",
                          inputs={"cases": [c["outcome"] for c in cases]},
                          must_say=[f"{n} past case{'s' if n != 1 else ''} — too few to project from"])
    effects = [c["effect"] for c in cases]
    mu, sd = _mean(effects), _sd(effects)
    held = sum(1 for c in cases if c["verdict"] in ("as_expected", "better"))
    low, high = mu - _Z80 * sd, mu + _Z80 * sd
    return Projection(method="intervention", value=round(mu, 6), low=round(low, 6), high=round(high, 6), coverage=coverage, unit=unit,
                      backtest={"n": n, "held": held, "worse": sum(1 for c in cases if c["verdict"] == "worse"),
                                "cannot_tell": sum(1 for c in cases if c["verdict"] == "cannot_tell")},
                      inputs={"cases": [c["outcome"] for c in cases], "matched_on": sorted({c["matched_on"] for c in cases})},
                      must_say=[f"{n} past decision{'s' if n != 1 else ''} of this kind on this install, each measured against the "
                                f"metric's own history: effect {_fmt(low)} to {_fmt(high)}{unit} at {int(coverage * 100)}% stated coverage",
                                f"{held} of {n} went the wanted way; read from Outcome entries and nothing else"])


def project(method: str, **kw) -> Projection:
    """The one interface: a method by name, or a refusal — never a guess at one."""
    if method == "identity":
        return identity(kw["formula"], kw.get("inputs") or {}, unit=kw.get("unit", ""), varied=kw.get("varied"))
    if method == "declared":
        return declared(variable=kw["variable"], value=kw.get("value"), by=kw.get("by", ""), text=kw.get("text", ""),
                        unit=kw.get("unit", ""), connection_id=kw.get("connection_id", ""),
                        low=kw.get("low"), high=kw.get("high"))
    if method == "history":
        return history(kw["spec"], kw["run_sql"], end_day=kw.get("end_day"), windows=kw.get("windows", HISTORY_WINDOWS))
    if method == "intervention":
        return intervention(metric=kw.get("metric", ""), connection_id=kw.get("connection_id", ""), action_id=kw.get("action_id", ""),
                            like=kw.get("like", ""), unit=kw.get("unit", ""))
    # Phase 7 — a registered method (a forecaster, estimator or simulator with its backtest, run as a
    # foreign tool through the one door); an unknown name is still refused by name.
    from aughor.record import methods as _methods
    if _methods.get_method(method) is not None:
        return _methods.project_registered(method, **kw)
    raise ValueError(f"no method named {method!r} on the ladder or registered; the four built are {', '.join(METHODS)}")


_TIER_BY_METHOD = {"identity": "mined", "declared": "declared", "history": "mined", "intervention": "mined"}


# ── predictions under a scenario ───────────────────────────────────────────────────────────

def predict(*, metric: str, projection: Projection, settles_on: str, author: str, connection_id: str = "",
            direction: str = "", spec: Optional[dict] = None, before: Optional[float] = None,
            assuming: Optional[list[str]] = None, for_ref: str = "") -> str:
    """Book a prediction claim under a projection: the band, the method, what it assumed, and —
    with a measurable ``spec`` — how the settle tick scores it. Returns the claim id."""
    if projection.value is None and projection.low is None:
        raise _claims.ClaimRefused(f"the {projection.method} method projected nothing: {projection.note or 'no value'}")
    tier = projection.tier or _TIER_BY_METHOD.get(projection.method, "said")
    author_kind = "person" if tier == "declared" else "system"
    unit = projection.unit
    low, high, mid = projection.low, projection.high, projection.value
    band = (f"{_fmt(low)} to {_fmt(high)}{unit}" if low is not None and high is not None and low != high
            else f"{_fmt(mid)}{unit}")
    text = f"expected: {metric} {band} by {settles_on} ({projection.method})"
    claim = _claims.Claim(
        kind="prediction", tier=tier,
        about=_claims.About(kind="connection", key=connection_id) if connection_id else _claims.About(kind="organisation", key=""),
        statement=_claims.Statement(text=text[:1000], metric=metric, value=mid, unit=unit, range_end=settles_on),
        status="To date", as_of=_today().isoformat(), author=author or "system", author_kind=author_kind, state="open",
        warrants=([_claims.Warrant(kind="claim", ref=projection.claim, detail="the declared assumption")]
                  if projection.claim else []),
        extra={"method": projection.method, "low": low, "mid": mid, "high": high, "coverage": projection.coverage,
               "settles_on": settles_on, "direction": direction, "backtest": dict(projection.backtest or {}),
               "must_say": list(projection.must_say), "assuming": list(assuming or []),
               **({"spec": dict(spec)} if spec else {}), **({"before": before} if before is not None else {}),
               **({"for": for_ref} if for_ref else {})},
    )
    key = _claims.claim_key("prediction", for_ref or "scenario", metric, settles_on,
                            _dt.datetime.now(_dt.timezone.utc).strftime("%H%M%S%f"))
    return _claims.book(claim, key=key, conn_id=connection_id or None)


def book_scenario(s: Scenario) -> Scenario:
    data = s.model_dump()
    for read_only in ("id", "key", "version", "recorded_at"):
        data.pop(read_only, None)
    if s.methods:
        order = {"identity": 0, "declared": 1, "history": 2, "intervention": 3}
        data["tier"] = s.tier or sorted(s.methods, key=lambda m: order.get(m, 9))[-1]
    key = f"scenario:{s.for_kind}:{s.for_id}:{_dt.datetime.now(_dt.timezone.utc).strftime('%Y%m%dT%H%M%S%f')}"
    aid = _ledger().artifact_write(KIND, key, data, conn_id=s.connection_id or None,
                                   lineage=[("for", s.for_id, s.for_kind)] + [("predicts", p, "") for p in s.predictions])
    art = _ledger().artifact_by_id(aid) or {}
    out = Scenario.model_validate(dict(art.get("payload") or data))
    out.id, out.key = str(art.get("id") or aid), str(art.get("natural_key") or key)
    out.version, out.recorded_at = int(art.get("version") or 1), str(art.get("created_at") or "")
    return out


def scenarios_for(for_id: str) -> list[Scenario]:
    out = []
    for art in _ledger().artifacts_of_kind(KIND, limit=2000):
        if (art.get("payload") or {}).get("for_id") == for_id:
            s = Scenario.model_validate(dict(art.get("payload") or {}))
            s.id, s.key = str(art.get("id") or ""), str(art.get("natural_key") or "")
            s.version, s.recorded_at = int(art.get("version") or 0), str(art.get("created_at") or "")
            out.append(s)
    return out


# ── scoring ────────────────────────────────────────────────────────────────────────────────

def against_band(actual: Optional[float], *, low: Optional[float], high: Optional[float], unit: str = "",
                 before: Optional[float] = None) -> str:
    """Where an actual fell against a prediction's band: ``inside`` · ``above`` · ``below``; a
    relative band (unit %) is read against ``before`` and is ``cannot_tell`` without one;
    ``no expectation`` when there is no band."""
    if low is None and high is None:
        return "no expectation"
    if actual is None:
        return "cannot_tell"
    value: Optional[float] = float(actual)
    if unit == "%":
        value = ((float(actual) - before) / abs(before) * 100.0) if before not in (None, 0) else None
    if value is None:
        return "cannot_tell"
    if low is not None and value < low:
        return "below"
    if high is not None and value > high:
        return "above"
    return "inside"


def score_prediction(claim: _claims.Claim, *, actual: Optional[float], measured_on: str, note: str = "") -> str:
    """Score one open prediction by code and restate it: state ``scored``, ``scored_against``, the
    actual. Returns the new version's id."""
    against = against_band(actual, low=claim.extra.get("low"), high=claim.extra.get("high"),
                           unit=claim.statement.unit, before=claim.extra.get("before"))
    new = claim.model_copy(deep=True)
    new.confidence = None
    new.state = "scored"
    new.extra = {**claim.extra, "scored_against": against, "actual": actual, "scored_on": measured_on,
                 **({"score_note": note} if note else {})}
    conn = claim.about.key if claim.about.kind == "connection" else None
    cid = _claims.restate(claim.key, new, conn_id=conn)
    # Phase 7 — a scored prediction is an event out: journaled and delivered to the subscriptions that asked.
    try:
        payload = {"claim_id": cid, "key": claim.key, "metric": claim.statement.metric, "method": str(claim.extra.get("method") or ""),
                   "scored_against": against, "actual": actual, "low": claim.extra.get("low"), "high": claim.extra.get("high"),
                   "tier": claim.tier, "text": claim.statement.text[:300]}
        _ledger().emit("prediction.scored", payload, conn_id=conn)
        from aughor.record.subscriptions import notify
        notify("prediction.scored", payload, conn_id=conn or "")
    except Exception as exc:  # noqa: BLE001
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the prediction.scored event could not go out; the score stands", counter="scenario.events_out")
    return cid


def due_predictions(now: Optional[_dt.datetime] = None, *, conn_id: Optional[str] = None) -> list[_claims.Claim]:
    """Open predictions whose range is Final — ``settles_on`` has passed — and that carry a spec the
    tick can measure. A prediction without one is scored by the review that owns it, not here."""
    today = (now or _dt.datetime.now(_dt.timezone.utc)).date().isoformat()
    return [c for c in _claims.list_claims(kind="prediction", state="open", conn_id=conn_id, limit=2000)
            if c.extra.get("settles_on") and c.extra["settles_on"] <= today and c.extra.get("spec")]


def score_due_predictions(*, run_sql_for, now: Optional[_dt.datetime] = None) -> list[str]:
    """The settle tick's scorer: measure each due prediction's spec over the window ending on its
    settle date and score it. ``run_sql_for(connection_id, internal=True)`` opens the connection.
    Returns the restated claim ids."""
    from aughor.playbook.outcomes import measure_spec
    now = now or _dt.datetime.now(_dt.timezone.utc)
    out = []
    for c in due_predictions(now):
        conn = c.about.key if c.about.kind == "connection" else ""
        try:
            run_sql = run_sql_for(conn, internal=True)
            value, label, why = measure_spec(c.extra["spec"], run_sql, end_day=_dt.date.fromisoformat(c.extra["settles_on"]))
        except Exception as exc:  # noqa: BLE001 — a prediction that cannot be measured is scored cannot_tell, said
            value, label, why = None, "", f"measurement failed: {str(exc)[:160]}"
        out.append(score_prediction(c, actual=value, measured_on=now.date().isoformat(),
                                    note=why or f"measured over {label}"))
    return out


def calibration(*, conn_id: Optional[str] = None) -> list[dict]:
    """Interval coverage by (method, metric, author) over scored predictions: n, how many fell
    inside their band, the observed coverage against the stated — the number the study calls the
    product's own (§B), counted and never estimated."""
    groups: dict[tuple[str, str, str], dict] = {}
    for c in _claims.list_claims(kind="prediction", state="scored", conn_id=conn_id, limit=5000):
        key = (str(c.extra.get("method") or "declared"), c.statement.metric, c.author)
        g = groups.setdefault(key, {"method": key[0], "metric": key[1], "author": key[2], "n": 0, "inside": 0,
                                    "above": 0, "below": 0, "cannot_tell": 0, "stated_coverage": []})
        g["n"] += 1
        against = str(c.extra.get("scored_against") or "cannot_tell")
        g[against if against in ("inside", "above", "below") else "cannot_tell"] += 1
        if c.extra.get("coverage") is not None:
            g["stated_coverage"].append(float(c.extra["coverage"]))
    out = []
    for g in groups.values():
        judged = g["inside"] + g["above"] + g["below"]
        stated = g.pop("stated_coverage")
        g["coverage_observed"] = round(g["inside"] / judged, 3) if judged else None
        g["coverage_stated"] = round(_mean(stated), 3) if stated else None
        g["signed_error"] = round((g["above"] - g["below"]) / judged, 3) if judged else None
        out.append(g)
    return sorted(out, key=lambda g: (-g["n"], g["method"], g["metric"]))
