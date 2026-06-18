"""Self-improving context loop — the engine proposes reviewable ontology fixes.

nao's "propose-context-fix": when the live path reveals that the ontology is
missing something, surface a concrete, human-reviewable edit rather than silently
re-deriving it every query. Here the first (and most defensible) trigger is a
GENUINE GAP — a recurring metric the ontology doesn't encode:

  The model keeps aggregating a currency measure (e.g. SUM(order_items.line_total)
  at category grain) for which NO canonical metric exists. Fork A proved that
  adding that exact metric override causally steers the model and fixes the
  answer. This loop NOTICES the pattern on its own and proposes that override.

Why this trigger and not the guards: a fan-out / measure-grain / divergence guard
firing means the ontology was already RIGHT and the model disobeyed it — the fix
belongs in the prompt, not the ontology. A currency measure with no covering
metric is a real ontology gap the data team should close.

Safeguards against proposing the model's own mistakes:
  • usage-driven — only measures actually aggregated in real queries are proposed;
  • single pre-computed measure columns only — SUM(line_total), never the model's
    SUM(quantity*unit_price) re-derivation (which would bake a guess into context);
  • currency-semantic + grain-sane — the column must be a currency measure and not
    per_unit (SUM of a per-unit price is wrong without ×quantity);
  • uncovered — skip measures a canonical metric already governs;
  • recurrence-gated — a one-off doesn't surface; `support` must reach a threshold;
  • human-reviewed — a recommendation is a PROPOSAL; `accept()` is what turns it
    into an override (through the proven, EXPLAIN-bound override path).
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field

from aughor.ontology.models import OntologyGraph

_ROOT = Path(__file__).parent.parent.parent / "data" / "ontology_recommendations"

# A measure must look like money and not be per-unit to be SUM-proposable.
_CURRENCY_HINTS = ("currency", "money", "usd", "revenue", "amount", "spend", "sales")
SURFACE_SUPPORT = 2  # a recommendation is "ripe" (surfaced) once seen this many times


class OntologyRecommendation(BaseModel):
    """A proposed ontology override, accumulated from live-path evidence.

    ``id`` is stable per (kind, entity, measure) so recurrences merge and bump
    ``support`` instead of piling up duplicates.
    """
    id: str
    kind: str = "metric"                       # only "metric" in v1
    target_id: str                             # proposed metric id
    entity: str
    proposed_fields: dict = Field(default_factory=dict)  # formula_sql, entity, display_name, unit, grain
    reason: str = ""
    support: int = 1                           # distinct sightings
    evidence: list[dict] = Field(default_factory=list)    # [{question, sql}] capped
    status: str = "pending"                    # pending | accepted | dismissed
    first_seen: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_seen: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def ripe(self) -> bool:
        return self.status == "pending" and self.support >= SURFACE_SUPPORT


# ── filesystem store (mirrors overrides.py) ─────────────────────────────────

def _safe(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.=-]", "_", s or "default")


def _path(conn: str, schema: str, rec_id: str) -> Path:
    return _ROOT / _safe(conn) / _safe(schema) / f"{_safe(rec_id)}.yaml"


def save_recommendation(conn: str, schema: str, rec: OntologyRecommendation) -> None:
    try:
        p = _path(conn, schema, rec.id)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(yaml.safe_dump(rec.model_dump(), sort_keys=False, allow_unicode=True))
    except Exception:
        pass


def load_recommendations(conn: str, schema: str) -> list[OntologyRecommendation]:
    base = _ROOT / _safe(conn) / _safe(schema)
    out: list[OntologyRecommendation] = []
    if not base.exists():
        return out
    for f in sorted(base.glob("*.yaml")):
        try:
            out.append(OntologyRecommendation.model_validate(yaml.safe_load(f.read_text()) or {}))
        except Exception:
            continue
    return out


def get_recommendation(conn: str, schema: str, rec_id: str) -> Optional[OntologyRecommendation]:
    return next((r for r in load_recommendations(conn, schema) if r.id == rec_id), None)


def delete_recommendation(conn: str, schema: str, rec_id: str) -> bool:
    try:
        p = _path(conn, schema, rec_id)
        if p.exists():
            p.unlink()
            return True
    except Exception:
        pass
    return False


# ── detector: turn one query into proposed metric recommendations ───────────

def _sum_targets(sql: str, dialect: str = "duckdb") -> list[tuple[str, list[str]]]:
    """Parse the SQL's SUM(...) calls into ('direct', [col]) and ('expr', [cols]).

    'direct'  — SUM(single column): a candidate measure to propose verbatim.
    'expr'    — SUM(arithmetic over >=2 columns), e.g. SUM(quantity*unit_price):
                NOT proposed verbatim (it's the model's re-derivation), but used as
                EVIDENCE that the owning entity needs its pre-computed measure metric.
    """
    out: list[tuple[str, list[str]]] = []
    try:
        import sqlglot
        from sqlglot import expressions as exp
        tree = sqlglot.parse_one(sql, read=dialect)
        for s in tree.find_all(exp.Sum):
            inner = s.this
            if isinstance(inner, exp.Column):
                out.append(("direct", [inner.name.lower()]))
            elif isinstance(inner, (exp.Mul, exp.Div, exp.Add, exp.Sub, exp.Paren)):
                cols = [c.name.lower() for c in inner.find_all(exp.Column)]
                if len(cols) >= 2:
                    out.append(("expr", cols))
    except Exception:
        # regex fallback: direct single-column sums only
        for m in re.finditer(r"\bsum\s*\(\s*(?:[`\"']?\w+[`\"']?\.)?[`\"']?(\w+)[`\"']?\s*\)",
                             sql, re.IGNORECASE):
            out.append(("direct", [m.group(1).lower()]))
    return out


def _entity_for_column(graph: OntologyGraph, col: str):
    """Return (entity, property) that owns ``col`` as a first-class property, or (None, None)."""
    for e in graph.entities.values():
        p = e.properties.get(col)
        if p is not None:
            return e, p
    return None, None


def _entity_for_columns(graph: OntologyGraph, cols: list[str]):
    """Return the entity owning the most of ``cols`` (the fact table of an arithmetic measure)."""
    best, best_n = None, 0
    for e in graph.entities.values():
        n = sum(1 for c in cols if c in e.properties)
        if n > best_n:
            best, best_n = e, n
    return best


def _uncovered_pre_computed_measure(graph: OntologyGraph, ent):
    """A currency, non-per_unit, uncovered measure property on ``ent`` (the metric the
    model SHOULD have used instead of re-deriving), or None."""
    for p in ent.properties.values():
        if (_is_currency_measure(p) and p.measure_grain != "per_unit"
                and not _covered_by_canonical(graph, ent.id, p.name)):
            return p
    return None


def _is_currency_measure(prop) -> bool:
    hay = f"{prop.value_interpretation} {prop.unit} {prop.name}".lower()
    return prop.semantic_type == "measure" and any(h in hay for h in _CURRENCY_HINTS)


def _covered_by_canonical(graph: OntologyGraph, entity_id: str, col: str) -> bool:
    """True if a canonical metric on this entity already aggregates this column."""
    pat = re.compile(rf"\bsum\s*\(\s*(?:[`\"']?\w+[`\"']?\.)?[`\"']?{re.escape(col)}[`\"']?\s*\)",
                     re.IGNORECASE)
    for m in graph.metrics.values():
        if m.entity == entity_id and pat.search(m.formula_sql or ""):
            return True
    return False


def observe(conn: str, schema: str, question: str, sql: str,
            graph: Optional[OntologyGraph], dialect: str = "duckdb") -> list[str]:
    """Inspect one (question, sql) and accrue metric-gap recommendations.

    Returns the ids of recommendations created or reinforced. Best-effort and
    idempotent per (entity, column): a recurrence bumps ``support`` and appends
    evidence rather than creating a duplicate.
    """
    if graph is None or not sql:
        return []
    touched: list[str] = []
    try:
        # Resolve each SUM(...) into a target (entity, uncovered measure) + evidence kind.
        # A direct SUM(col) is the proposable measure; a SUM(arithmetic) is the model's
        # re-derivation — it doesn't become the formula, but it's EVIDENCE the entity's
        # pre-computed measure should be a metric.
        targets: dict[tuple[str, str], tuple] = {}
        for kind, cols in _sum_targets(sql, dialect):
            if kind == "direct":
                ent, prop = _entity_for_column(graph, cols[0])
                if (ent and prop and _is_currency_measure(prop)
                        and prop.measure_grain != "per_unit"
                        and not _covered_by_canonical(graph, ent.id, cols[0])):
                    targets.setdefault((ent.id, prop.name), (ent, prop, "direct"))
            else:
                ent = _entity_for_columns(graph, cols)
                prop = _uncovered_pre_computed_measure(graph, ent) if ent else None
                if ent and prop:
                    targets.setdefault((ent.id, prop.name), (ent, prop, "rederived"))

        now = datetime.now(timezone.utc).isoformat()
        for (ent_id, col), (ent, prop, kind) in targets.items():
            rec_id = f"metric__{ent_id}__{col}".lower()
            rec = get_recommendation(conn, schema, rec_id)
            if rec is None:
                label = f"{ent.display_name} Revenue".strip()
                desc = (f"{ent.display_name}-grain revenue: SUM({col}). Use for revenue "
                        f"sliced by a product/line dimension where order-level totals cannot "
                        f"be apportioned. Do not re-derive from unit price × quantity.")
                rec = OntologyRecommendation(
                    id=rec_id, kind="metric", target_id=f"{ent.id.lower()}_{col}",
                    entity=ent.id,
                    proposed_fields={
                        "entity": ent.id, "display_name": label,
                        "formula_sql": f"SUM({col})", "unit": prop.unit or "USD",
                        "description": desc,
                    },
                    reason=(f"{ent.display_name}.{col} is a currency measure aggregated in queries "
                            f"but no canonical metric covers it — propose SUM({col}) as a metric."),
                )
            else:
                rec.support += 1
                rec.last_seen = now
            if rec.status == "dismissed":
                continue  # respect a human dismissal — never resurrect
            note = " [re-derived as a product — should use the pre-computed column]" if kind == "rederived" else ""
            if question and len(rec.evidence) < 3 and not any(e.get("question") == question for e in rec.evidence):
                rec.evidence.append({"question": f"{question}{note}", "sql": " ".join(sql.split())[:300]})
            save_recommendation(conn, schema, rec)
            touched.append(rec_id)
    except Exception:
        return touched
    return touched


# ── accept: promote a recommendation into a (bound) human override ──────────

def accept(conn: str, schema: str, rec_id: str, graph: Optional[OntologyGraph],
           explain) -> Optional[dict]:
    """Turn a pending recommendation into an EXPLAIN-bound metric override.

    ``explain(sql) -> error|None`` is the same binder the override endpoints use.
    Returns the bind result, or None if the recommendation is unknown.
    """
    from aughor.ontology.overrides import OntologyOverride, bind_overrides, save_override
    rec = get_recommendation(conn, schema, rec_id)
    if rec is None:
        return None
    ov = OntologyOverride(
        target_kind="metric", target_id=rec.target_id, fields=dict(rec.proposed_fields),
        note=f"accepted from recommendation {rec_id}: {rec.reason}")
    bind_overrides(ov, graph, explain)
    save_override(conn, schema, ov)
    rec.status = "accepted"
    save_recommendation(conn, schema, rec)
    return {"override": ov.model_dump(),
            "bound": all(b.get("bound") for b in ov.binding.values()) if ov.binding else True}
