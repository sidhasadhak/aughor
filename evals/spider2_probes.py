"""B1 — the probe-and-repair back half of SOMA-lite (the missing half of the candidates stage).

`spider2_candidates.py` is SOMA's *front half*: strategy-diverse generation + deterministic
execution-signature selection. It already computes the free disagreement signal
(`n_signatures`, `agreed`) — and then ships the plurality winner and stops. SOMA's own ablation
puts most of the gain in the *back half* (probing + evidence-gated repair; +30.6 EX on instances
where no candidate was correct). This module is that back half, leaned out along three
Aughor-specific improvisations (design: docs/SOMA_LEVERAGE_AND_AMBIGUITY_LEDGER_2026-07-06.md):

  * **I2 — deterministic AST-diff disagreement extraction.** The paper spends an LLM call to
    diff candidates; we own sqlglot, so pairwise normalized-AST feature diff classifies each
    delta into the paper's taxonomy (AmbiValue / AmbiIntent{grain,aggregation,window} /
    AmbiSchema) with no model call. Cheaper, reproducible, receipt-ready.
  * **I3 — deterministic-first probe battery.** For each taxonomy class Aughor already owns the
    probe the paper plans with an LLM (filter-literal binding for AmbiValue, the grain check for
    AmbiIntent-grain, …). The harness supplies those as callables; only the AmbiIntent residue
    the guards can't resolve keeps an (optional, capped) LLM probe.
  * **I7 — evidence-typed repair gates.** Their "repair faithfulness 0.96" is LLM-audited; ours
    is a deterministic *gate*: an adopted answer (an existing candidate, or a minimal repair)
    must (a) execute, (b) clear the probed dimension, (c) not change any clause the evidence
    doesn't cover, (d) not regress an unresolved dimension. Any gate fails ⇒ keep the seed
    (their fallback, our never-go-backwards discipline). Monotonic by construction — the whole
    point, since two cheap levers already died under the measurement protocol this week.

Trigger discipline (the harness enforces it): this runs ONLY when the candidates stage reports
`n_signatures > 1`. Agreement ⇒ ship the plurality answer, zero extra cost.

Like `spider2_candidates.py` this is PURE orchestration — every effect (execute, probe, repair)
arrives through a callable, so the taxonomy extraction and the acceptance gates are unit-tested
offline with no DB and no LLM.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence

import sqlglot
from sqlglot import exp

# ── clause classes ────────────────────────────────────────────────────────────
# The unit of the faithfulness gate: a repair may touch only the clause classes the
# cited evidence covers. Each taxonomy facet maps to the classes a legitimate fix for
# it is allowed to move (a re-grain naturally restructures projection + aggregation, so
# "grain" permits those too; a literal fix may touch only the predicate literal).
WHERE_LITERALS = "where_literals"
GROUP_BY = "group_by"
AGGREGATION = "aggregation"
COLUMNS = "columns"
WINDOW = "window"

_FACET_ALLOWED: dict[str, frozenset[str]] = {
    "literal": frozenset({WHERE_LITERALS}),
    "grain": frozenset({GROUP_BY, COLUMNS, AGGREGATION}),
    "aggregation": frozenset({AGGREGATION, COLUMNS}),
    "window": frozenset({WINDOW, WHERE_LITERALS}),
    "column": frozenset({COLUMNS, WHERE_LITERALS}),
}
# The deterministic-probe key the harness registers per facet (I3). AmbiSchema has no owned
# deterministic probe — it resolves only if an LLM probe is wired, else stays seed.
_FACET_PROBE_KEY: dict[str, str] = {
    "literal": "value", "grain": "grain", "aggregation": "aggregation",
    "window": "window", "column": "schema",
}

_DATE_FUNCS = {"strftime", "date", "datetime", "julianday", "date_trunc", "extract",
               "year", "month", "day", "date_part", "unixepoch"}
_DATE_LITERAL = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")


@dataclass(frozen=True)
class Dimension:
    """A resolved (dimension, options, evidence) triple — the paper's ambiguity dimension,
    derived deterministically from the candidate AST diff (I2)."""
    kind: str        # "AmbiValue" | "AmbiIntent" | "AmbiSchema"
    facet: str       # "literal" | "grain" | "aggregation" | "window" | "column"
    subject: str     # the column/clause the disagreement is about (receipt text)
    options: tuple[str, ...]   # the differing readings observed across candidates
    evidence: tuple[str, ...]  # the differing SQL fragments (receipt-ready)

    def allowed_clauses(self) -> frozenset[str]:
        return _FACET_ALLOWED.get(self.facet, frozenset())

    def probe_key(self) -> str:
        return _FACET_PROBE_KEY.get(self.facet, "")


@dataclass(frozen=True)
class _Features:
    """The normalized, clause-classed feature view of one SQL — the atom of both the diff
    (I2) and the faithfulness gate (I7). Every field is order-normalized so cosmetic rewrites
    (row order, whitespace) don't read as disagreement."""
    where_predicates: frozenset  # (col, op, literal) normalized — column-attributed literals
    where_literals: frozenset    # bare literal values in WHERE/HAVING (coarse fallback)
    group_by: frozenset          # normalized GROUP BY expression strings
    aggregations: frozenset      # {"SUM","AVG","COUNT","COUNT_DISTINCT",...}
    distinct: bool               # SELECT DISTINCT present
    columns: frozenset           # physical column names referenced anywhere
    window: frozenset            # date/window function calls + (op,date-literal) tuples


def _norm(node: exp.Expression) -> str:
    try:
        return node.sql(dialect="sqlite", normalize=True, comments=False).lower().strip()
    except Exception:
        return str(node).lower().strip()


def _features(sql: str) -> Optional[_Features]:
    """Parse one candidate into its clause-classed feature view. None on a parse failure —
    the caller treats un-parseable SQL as un-diffable / un-verifiable (fail-safe)."""
    try:
        tree = sqlglot.parse_one(sql, dialect="sqlite", error_level=sqlglot.ErrorLevel.RAISE)
    except Exception:
        return None
    if tree is None:
        return None

    where_nodes = [n for n in (tree.find(exp.Where), tree.find(exp.Having)) if n is not None]
    preds: set = set()
    literals: set = set()
    windows: set = set()
    for wn in where_nodes:
        for lit in wn.find_all(exp.Literal):
            v = str(lit.this).lower()
            literals.add(v)
        for cmp_cls, op in ((exp.EQ, "="), (exp.NEQ, "!="), (exp.GT, ">"),
                            (exp.GTE, ">="), (exp.LT, "<"), (exp.LTE, "<=")):
            for cn in wn.find_all(cmp_cls):
                col = lit = None
                if isinstance(cn.left, exp.Column) and isinstance(cn.right, exp.Literal):
                    col, lit = cn.left, cn.right
                elif isinstance(cn.right, exp.Column) and isinstance(cn.left, exp.Literal):
                    col, lit = cn.right, cn.left
                if col is not None and lit is not None:
                    val = str(lit.this).lower()
                    preds.add((col.name.lower(), op, val))
                    if _DATE_LITERAL.match(val):
                        windows.add((op, val))  # a date-boundary comparison → window facet

    # date/window function calls anywhere in the tree
    for fn in tree.find_all(exp.Func):
        name = (fn.sql_name() or fn.key or "").lower()
        if name in _DATE_FUNCS:
            windows.add(_norm(fn))

    group = tree.find(exp.Group)
    group_by = frozenset(_norm(e) for e in group.expressions) if group else frozenset()

    aggs: set = set()
    for agg_cls, label in ((exp.Sum, "SUM"), (exp.Avg, "AVG"), (exp.Min, "MIN"),
                           (exp.Max, "MAX"), (exp.Count, "COUNT")):
        for a in tree.find_all(agg_cls):
            if agg_cls is exp.Count and a.find(exp.Distinct) is not None:
                aggs.add("COUNT_DISTINCT")
            else:
                aggs.add(label)

    select = tree.find(exp.Select)
    distinct = bool(select and select.args.get("distinct"))
    columns = frozenset((c.name or "").lower() for c in tree.find_all(exp.Column) if c.name)

    return _Features(
        where_predicates=frozenset(preds),
        where_literals=frozenset(literals),
        group_by=group_by,
        aggregations=frozenset(aggs),
        distinct=distinct,
        columns=columns,
        window=frozenset(windows),
    )


def changed_clauses(seed_sql: str, other_sql: str) -> set[str]:
    """The clause classes that differ between two SQLs — the atom of the faithfulness gate.
    Un-parseable either side ⇒ a sentinel that fails every subset check (fail-safe: an
    edit we can't verify is treated as unfaithful, so the seed is kept)."""
    fa, fb = _features(seed_sql), _features(other_sql)
    if fa is None or fb is None:
        return {"__unparsed__"}
    changed: set[str] = set()
    if fa.where_predicates != fb.where_predicates or fa.where_literals != fb.where_literals:
        changed.add(WHERE_LITERALS)
    if fa.group_by != fb.group_by:
        changed.add(GROUP_BY)
    if fa.aggregations != fb.aggregations or fa.distinct != fb.distinct:
        changed.add(AGGREGATION)
    if fa.columns != fb.columns:
        changed.add(COLUMNS)
    if fa.window != fb.window:
        changed.add(WINDOW)
    # a where-literal that is a date boundary lives in BOTH classes; don't double-punish a
    # pure boundary move by also flagging where_literals when only the date tuple moved.
    if changed == {WHERE_LITERALS, WINDOW} and (fa.where_literals - fa.window) == (fb.where_literals - fb.window):
        changed.discard(WHERE_LITERALS)
    return changed


def _dimension_slice(feats: _Features, dim: Dimension):
    """The feature slice one dimension concerns — the unit of the no-regress gate. Finer than a
    clause CLASS: an AmbiValue on `city` and one on `status` share the `where_literals` class but
    slice to their own column's predicates, so a repair that clobbers the untouched sibling is
    caught even though faithfulness (class-level) would wave it through."""
    if dim.facet == "literal":
        if dim.subject and dim.subject != "filter literal":
            return frozenset((c, o, v) for c, o, v in feats.where_predicates if c == dim.subject)
        return feats.where_literals
    if dim.facet == "grain":
        return feats.group_by
    if dim.facet == "aggregation":
        return (feats.aggregations, feats.distinct)
    if dim.facet == "window":
        date_preds = frozenset((c, o, v) for c, o, v in feats.where_predicates if _DATE_LITERAL.match(v))
        return (feats.window, date_preds)
    if dim.facet == "column":
        return feats.columns
    return None


def dimension_untouched(seed_sql: str, cand_sql: str, dim: Dimension) -> bool:
    """True iff `dim`'s own feature slice is identical between seed and candidate. Un-parseable
    either side ⇒ False (fail closed: an unverifiable edit is treated as a regression)."""
    fa, fb = _features(seed_sql), _features(cand_sql)
    if fa is None or fb is None:
        return False
    return _dimension_slice(fa, dim) == _dimension_slice(fb, dim)


def evidence_faithful(seed_sql: str, cand_sql: str, dims: Sequence[Dimension]) -> tuple[bool, set[str]]:
    """Gate (d): the clauses a repair changed must be covered by the cited evidence. Returns
    (faithful, changed_clauses). A no-op (nothing changed) is NOT faithful — there's nothing to
    adopt. `__unparsed__` never subsets a real allow-set, so unverifiable edits fail closed."""
    allowed: set[str] = set()
    for d in dims:
        allowed |= d.allowed_clauses()
    changed = changed_clauses(seed_sql, cand_sql)
    return (bool(changed) and changed.issubset(allowed)), changed


# ── I2 · deterministic disagreement extraction ────────────────────────────────
def _subject_for_literal(feats: Sequence[_Features]) -> tuple[str, tuple[str, ...]]:
    """Which column's literal VALUE disagrees, and the option values — for the AmbiValue
    subject. Value divergence only (a same-literal/different-operator delta is a boundary, not
    a value, ambiguity — see `_boundary_divergent`)."""
    by_col: dict[str, set] = {}
    for f in feats:
        for col, _op, val in f.where_predicates:
            by_col.setdefault(col, set()).add(val)
    diff_cols = {c: vs for c, vs in by_col.items() if len(vs) > 1}
    if diff_cols:
        col = sorted(diff_cols)[0]
        return col, tuple(sorted(diff_cols[col]))
    # fall back to the bare-literal symmetric difference (only if genuinely divergent)
    if len({f.where_literals for f in feats}) > 1:
        return "filter literal", tuple(sorted({v for f in feats for v in f.where_literals}))
    return "filter literal", ()


def _boundary_divergent(feats: Sequence[_Features]) -> bool:
    """Same column + same literal but a different comparison operator across candidates
    (`age > 18` vs `age >= 18`) — an off-by-one / boundary ambiguity, an AmbiIntent facet."""
    ops_by_colval: dict[tuple, set] = {}
    for f in feats:
        for col, op, val in f.where_predicates:
            ops_by_colval.setdefault((col, val), set()).add(op)
    return any(len(ops) > 1 for ops in ops_by_colval.values())


def extract_disagreements(sqls: Sequence[str]) -> list[Dimension]:
    """Pairwise normalized-AST feature diff over the live candidates → the paper's
    (dimension, options, evidence) triples, derived with zero model calls (I2).

    Precision-first, like `grain_intent`: a dimension is emitted only when a clause class
    genuinely differs across candidates. Over-emission is self-correcting downstream (a probe
    that finds no evidence leaves the seed untouched); under-emission just forgoes a repair."""
    feats = [(_features(s), s.strip()) for s in sqls if (s or "").strip()]
    feats = [(f, s) for f, s in feats if f is not None]
    if len({s for _f, s in feats}) < 2:
        return []  # need ≥2 distinct parseable readings to have a disagreement
    fs = [f for f, _s in feats]
    dims: list[Dimension] = []

    subj, opts = _subject_for_literal(fs)
    if len(set(opts)) > 1:   # genuine VALUE divergence (NYC vs New York), not an operator delta
        dims.append(Dimension("AmbiValue", "literal", subj, opts,
                              tuple(sorted({f"{c}{o}{v}" for f in fs for c, o, v in f.where_predicates}))[:6]))

    if len({f.group_by for f in fs}) > 1:
        opts = tuple(sorted({(", ".join(sorted(f.group_by)) or "∅") for f in fs}))
        dims.append(Dimension("AmbiIntent", "grain", "result grain (GROUP BY)", opts,
                              tuple(sorted({e for f in fs for e in f.group_by}))[:6]))

    # Aggregation ambiguity is a CHOICE (SUM vs AVG, COUNT vs COUNT DISTINCT), not the mere
    # presence of an aggregate — going per-row → per-group necessarily ADDS an aggregate, and
    # that transition is owned by the grain facet (whose allowed clauses include aggregation).
    # So flag it only when the candidates that DO aggregate disagree on which, or DISTINCT toggles.
    agg_nonempty = {f.aggregations for f in fs if f.aggregations}
    if len(agg_nonempty) > 1 or len({f.distinct for f in fs}) > 1:
        opts = tuple(sorted({(", ".join(sorted(f.aggregations)) + ("+DISTINCT" if f.distinct else "")) or "∅"
                             for f in fs}))
        dims.append(Dimension("AmbiIntent", "aggregation", "aggregation / distinctness", opts,
                              tuple(sorted({a for f in fs for a in f.aggregations}))[:6]))

    if len({f.window for f in fs}) > 1 or _boundary_divergent(fs):
        wins = {str(w) for f in fs for w in f.window}
        wins |= {f"{c} {o} {v}" for f in fs for c, o, v in f.where_predicates if _DATE_LITERAL.match(v)}
        opts = tuple(sorted({(", ".join(sorted(str(w) for w in f.window)) or "∅") for f in fs}))
        dims.append(Dimension("AmbiIntent", "window", "date axis / boundary", opts,
                              tuple(sorted(wins))[:6]))

    # AmbiSchema (same-role column swap): only when NO value/grain/agg/window facet already
    # explains the divergence, so a literal/grain change isn't mislabelled a schema swap. No
    # owned deterministic probe → only resolvable via an LLM probe; emitted for completeness
    # + the Trust Receipt (I6) regardless.
    if not dims and len({f.columns for f in fs}) > 1:
        uniq = sorted({c for f in fs for c in f.columns
                       if any(c not in g.columns for g in fs)})
        if uniq:
            dims.append(Dimension("AmbiSchema", "column", "column choice", tuple(uniq)[:6],
                                  tuple(uniq)[:6]))
    return dims


# ── I3 · probe battery ────────────────────────────────────────────────────────
@dataclass
class ProbeResult:
    dimension: Dimension
    resolved: bool
    finding: str                     # receipt-ready description of what the probe showed
    preferred_sql: Optional[str] = None   # a candidate SQL the evidence supports, if any
    hint: str = ""                   # a directive for the repair LLM when no full SQL is preferred
    source: str = "unresolved"       # "det:value" | "det:grain" | "llm" | "unresolved"


def run_probes(
    dimensions: Sequence[Dimension],
    *,
    det_probes: dict[str, Callable[[Dimension], Optional[ProbeResult]]],
    llm_probe: Optional[Callable[[Dimension], Optional[ProbeResult]]] = None,
    max_llm: int = 3,
) -> list[ProbeResult]:
    """For each dimension, prefer the owned deterministic probe (I3); fall back to ONE capped
    LLM probe per unresolved AmbiIntent dimension (the paper uses 8–9 all-LLM probes)."""
    out: list[ProbeResult] = []
    llm_used = 0
    for dim in dimensions:
        probe = det_probes.get(dim.probe_key())
        res = probe(dim) if probe else None
        if (res is None or not res.resolved) and dim.kind == "AmbiIntent" \
                and llm_probe is not None and llm_used < max_llm:
            llm_used += 1
            alt = llm_probe(dim)
            if alt is not None and alt.resolved:
                res = alt
        out.append(res or ProbeResult(dim, False, "no probe resolved this dimension"))
    return out


# ── I7 · resolution + evidence-typed repair ───────────────────────────────────
@dataclass
class RepairOutcome:
    sql: str
    changed: bool
    accepted: bool
    reason: str
    source: str = "seed"                       # "seed" | "alternate:<strategy>" | "repair"
    gates: dict = field(default_factory=dict)
    dimensions: list[Dimension] = field(default_factory=list)
    resolved_dims: list[Dimension] = field(default_factory=list)


def build_repair_instruction(question: str, resolved: Sequence[ProbeResult]) -> str:
    """The paper's minimal-repair contract, conditioned on OUR probe evidence: edit only what
    the evidence covers, keep it localized."""
    lines = [f"QUESTION: {question}", "",
             "A live probe of the database resolved the following ambiguities in the query. "
             "Apply ONLY these changes, keep every other clause exactly as written, and return "
             "the full corrected SQL:"]
    for r in resolved:
        d = r.dimension
        detail = r.hint or r.finding
        lines.append(f"- {d.kind}/{d.facet} on {d.subject}: {detail}")
    return "\n".join(lines)


def _gate(seed_sql: str, cand_sql: str, resolved: Sequence[Dimension], unresolved: Sequence[Dimension],
          execute_fn: Callable[[str], tuple], reprobe: dict[str, Callable[[str, Dimension], bool]]) -> tuple[bool, dict, str]:
    """The four acceptance gates (I7). Returns (ok, gates, reason). Any failure ⇒ keep seed."""
    gates: dict = {}
    ok, _rows, err = execute_fn(cand_sql)
    gates["executes"] = bool(ok)
    if not ok:
        return False, gates, f"candidate did not execute: {str(err)[:80]}"
    faithful, changed = evidence_faithful(seed_sql, cand_sql, resolved)
    gates["faithful"] = faithful
    gates["changed_clauses"] = sorted(changed)
    if not faithful:
        allowed = sorted({c for d in resolved for c in d.allowed_clauses()})
        return False, gates, f"edit touched clauses outside the evidence {sorted(changed)} (allowed {allowed})"
    # (c) no-regress: every UNRESOLVED dimension's own feature slice must be unchanged. Finer
    # than faithfulness — catches a same-clause-class sibling (two literals, one unresolved) the
    # class-level faithfulness gate can't see.
    regressed = [d for d in unresolved if not dimension_untouched(seed_sql, cand_sql, d)]
    gates["no_regress"] = not regressed
    if regressed:
        return False, gates, f"edit regressed an unresolved dimension: {regressed[0].facet} on {regressed[0].subject}"
    # (b) clears the probed dimension — re-run the deterministic probe against the candidate
    cleared = True
    for d in resolved:
        fn = reprobe.get(d.probe_key())
        if fn is not None and not fn(cand_sql, d):
            cleared = False
            break
    gates["cleared"] = cleared
    if not cleared:
        return False, gates, "candidate did not clear the probed dimension"
    return True, gates, "adopted"


def resolve(
    question: str,
    seed_sql: str,
    dimensions: Sequence[Dimension],
    probe_results: Sequence[ProbeResult],
    *,
    execute_fn: Callable[[str], tuple],
    repair_fn: Optional[Callable[[str, str], Optional[str]]] = None,
    alternatives: Sequence[str] = (),
    reprobe: Optional[dict[str, Callable[[str, Dimension], bool]]] = None,
) -> RepairOutcome:
    """Adopt the evidence-consistent reading, gated (I7). Two candidate sources, cheapest first:
      1. an EXISTING candidate a probe already prefers (free — no LLM), or one named in a
         probe's `preferred_sql`;
      2. else a minimal `repair_fn` edit conditioned on the probe evidence (≤1 LLM call).
    The first candidate that clears all four gates is adopted; nothing clears ⇒ keep the seed
    (never go backwards). `resolved` = the dimensions a probe actually settled."""
    reprobe = reprobe or {}
    resolved_dims = [r.dimension for r in probe_results if r.resolved]
    unresolved_dims = [r.dimension for r in probe_results if not r.resolved]
    base = RepairOutcome(seed_sql.strip(), False, False, "no probe resolved a dimension",
                         dimensions=list(dimensions), resolved_dims=resolved_dims)
    if not resolved_dims:
        return base

    seed_norm = seed_sql.strip()
    # 1 · probe-preferred existing candidates (free), in evidence order.
    for r in probe_results:
        if r.resolved and r.preferred_sql and r.preferred_sql.strip() != seed_norm:
            ok, gates, reason = _gate(seed_sql, r.preferred_sql, resolved_dims, unresolved_dims,
                                      execute_fn, reprobe)
            if ok:
                return RepairOutcome(r.preferred_sql.strip(), True, True, reason,
                                     source=f"alternate:{r.source}", gates=gates,
                                     dimensions=list(dimensions), resolved_dims=resolved_dims)

    # 2 · minimal evidence-gated repair (≤1 LLM call).
    if repair_fn is not None:
        instruction = build_repair_instruction(question, [r for r in probe_results if r.resolved])
        try:
            cand = repair_fn(seed_sql, instruction)
        except Exception:
            cand = None
        if cand and cand.strip() != seed_norm:
            ok, gates, reason = _gate(seed_sql, cand, resolved_dims, unresolved_dims,
                                      execute_fn, reprobe)
            if ok:
                return RepairOutcome(cand.strip(), True, True, reason, source="repair", gates=gates,
                                     dimensions=list(dimensions), resolved_dims=resolved_dims)
            base = RepairOutcome(seed_sql.strip(), False, False,
                                 f"repair rejected by gates: {reason}", gates=gates,
                                 dimensions=list(dimensions), resolved_dims=resolved_dims)
    return base
