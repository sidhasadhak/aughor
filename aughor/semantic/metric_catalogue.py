"""The metrics that apply to ONE connection — the industry's, the explorer's, and the org's own.

Asked for 2026-09-18: *"per connection list of metrics derived by the explorer agent listed
in the Metrics sub-tab … combination of Industry type that user selects in the settings +
plus analysis of the explorer agent and its judgement."*

Three sources, one list:

1. **Defined** — a `MetricDefinition` already in the registry for this connection
   (`list_metrics(connection_id=…)`, which applies connection-shadows-global itself).
2. **Industry** — the metric recipes carried by the ACTIVE knowledge packages this
   connection's industry reads. Gate 6 (§3.17) decides what "active" means: a draft
   package is still being authored, so `banking` and `customer-analytics` are correctly
   absent until a person reviews them. Which industry a connection reads is
   `industry_scope()`'s answer — it already prefers the org's declared industry (Settings ▸
   Organization) over the connection's profiled one, and already honours the industries
   chosen at install (IP-2).
3. **Explorer** — the `north_star_metrics` the explorer inferred for THIS connection,
   grounded in its real tables and columns. The explorer never looks beyond its own
   connection (the user's rule of 2026-09-14), so these are per-connection by construction.

## Why this is computed, not stored

A pack metric is a **role-bound recipe** — `SUM({{role.financial_period.interest_expense}})`
— not SQL. It becomes concrete for a connection only once that connection's data is bound
to those roles (`packs/bindings.py`). Copying it into `data/metrics.json` at connection
time would freeze a shared, versioned, upstream definition into a tracked file, per
connection, where it would drift the moment the package shipped a new formula.

So the catalogue is **computed on read and materialised on first edit**
(`materialise()`): editing an industry or explorer metric writes a connection-scoped
`MetricDefinition` at that moment, and from then on source (1) shadows it — the same
override-wins discipline `list_metrics` and `data/ontology_overrides/` already practise.

## What a state means

- ``defined``       — a real `MetricDefinition`; editable in place.
- ``needs_binding`` — an industry recipe whose required roles are NOT bound to this
  connection, so it cannot be computed here. Listed on purpose (the user asked for every
  applicable metric) but never as though it were available. `unmeasured ⇒ never read`.
- ``formula_rejected`` — an explorer metric that HAD a `value_sql` and lost it: the
  build-time audit could not trust it and blanked it, and the recipe-grounded
  regeneration did not recover it. The row carries the audit's own reason. This is
  deliberately NOT ``needs_formula``: on a connection where nothing binds (a warehouse
  whose default dataset does not resolve) every metric fails this way, and labelling it
  "needs a formula" sends the reader to write SQL when the fault is the connection.
- ``needs_formula`` — an explorer metric that names its columns but gave no `value_sql`.
  Measured on the live corpus 2026-09-18: 18 of 77 stored north-star metrics (23%) have
  none. It is still applicable and still editable — supplying the formula IS the edit —
  but a table that showed it like the other rows would imply a metric that is ready.
- ``proposed``      — a recipe this connection COULD compute: an industry metric whose
  roles are bound, or an explorer metric grounded in real columns. Still not a governed
  definition: nothing here is `approved`, because the live catalogue having zero approved
  metrics is what holds outbound KPI sends under law 2, and auto-approving a derived
  formula would lift that hold without anyone reviewing a number.

A pack's `sane_range` travels as provenance (band + the basis and sources that published
it), never as a measured figure for this connection — gate 6's rule that a package's
figures reach a surface only once measured.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

#: Source ids, in precedence order — earlier shadows later on a name collision.
SOURCE_DEFINED = "defined"
SOURCE_INDUSTRY = "industry"
SOURCE_EXPLORER = "explorer"
_PRECEDENCE = (SOURCE_DEFINED, SOURCE_INDUSTRY, SOURCE_EXPLORER)

STATE_DEFINED = "defined"
STATE_NEEDS_BINDING = "needs_binding"
STATE_NEEDS_FORMULA = "needs_formula"
STATE_FORMULA_REJECTED = "formula_rejected"
STATE_PROPOSED = "proposed"


def normalize_name(text: str) -> str:
    """A metric's identity for collision purposes: lowercase snake_case, punctuation dropped.

    'Gross Merchandise Value (GMV)' and 'gross_merchandise_value_gmv' are the same metric
    arriving from two sources, and listing both would be the duplicate the Metrics tab
    already warns about."""
    t = re.sub(r"[^a-z0-9]+", "_", str(text or "").lower())
    return t.strip("_")


@dataclass
class CatalogueEntry:
    """One row of the connection's metric catalogue."""
    name: str
    label: str
    source: str
    state: str
    sql: str = ""
    unit: str = ""
    definition: str = ""
    grain: str = ""
    dimensions: list[str] = field(default_factory=list)
    tables: list[str] = field(default_factory=list)
    anti_patterns: list[str] = field(default_factory=list)
    #: Industry only — the package this recipe came from, and the roles it needs.
    pack_id: str = ""
    required_roles: list[str] = field(default_factory=list)
    missing_roles: list[str] = field(default_factory=list)
    #: Industry only — the published band, carried as provenance, never as a measurement.
    sane_range: Optional[dict] = None
    #: Explorer only — why an operator in this industry watches it.
    why_it_matters: str = ""
    #: Explorer only — the audit's own words for why this metric's formula was dropped.
    #: Empty for every other state; a `formula_rejected` row without one would be the
    #: same unexplained dead end this state exists to replace.
    reason: str = ""
    #: Defined only — the governance status of the stored definition.
    status: str = ""
    version: int = 0
    owner: str = ""
    #: True when this row can be edited in place; False means `materialise()` runs first.
    editable: bool = False

    def as_dict(self) -> dict:
        from dataclasses import asdict
        return asdict(self)


# ── Source 1: the registry ────────────────────────────────────────────────────

def _defined_entries(connection_id: str) -> list[CatalogueEntry]:
    from aughor.semantic.metrics import list_metrics

    out: list[CatalogueEntry] = []
    for m in list_metrics(connection_id=connection_id):
        out.append(CatalogueEntry(
            name=m.name, label=m.label or m.name, source=SOURCE_DEFINED,
            state=STATE_DEFINED, sql=m.sql or "", unit=m.unit or "",
            definition=m.caveats or "", dimensions=list(m.dimensions or []),
            tables=list(m.tables or []), anti_patterns=list(m.wrong_usage_examples or []),
            status=m.status or "draft", version=int(m.version or 0),
            owner=m.owner or "", editable=True,
        ))
    return out


# ── Source 2: the industry's active knowledge packages ────────────────────────

def _industry_packages(connection_id: str, schema_name: Optional[str]) -> list:
    """The ACTIVE knowledge packages this connection reads: its own industry's, plus the
    function and base packages every industry shares. `industry_scope` answers None when
    nothing is known about the industry — then no industry-layer package is claimed,
    rather than every one of them."""
    from aughor.business_profile.metric_kb import industry_scope
    from aughor.packs import knowledge

    try:
        scope = industry_scope(connection_id, schema_name)
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "industry scope is best-effort; the catalogue lists the shared "
                      "packages only", counter="metric_catalogue.scope")
        scope = None
    out = []
    for pkg in knowledge.packages():
        if pkg.layer == "industry":
            if scope and pkg.industry == scope:
                out.append(pkg)
        else:
            out.append(pkg)          # function / base — read by every industry
    return out


def _bound_roles(pack_id: str, connection_id: str, schema_name: Optional[str]) -> set[str]:
    """The roles this connection has bound for a package. Empty on any trouble, which
    reads as 'nothing bound' — the honest answer, and the one that keeps an unbindable
    recipe out of the computable list."""
    from aughor.packs.bindings import load_binding

    try:
        rec = load_binding(pack_id, connection_id, schema_name or "")
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "binding lookup is best-effort; the recipe is reported as needing a "
                      "binding", counter="metric_catalogue.binding")
        return set()
    return set((rec or {}).get("bindings") or {})


def _industry_entries(connection_id: str, schema_name: Optional[str]) -> list[CatalogueEntry]:
    from aughor.packs.loader import load_pack

    out: list[CatalogueEntry] = []
    for pkg in _industry_packages(connection_id, schema_name):
        try:
            pack = load_pack(pkg.directory)
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, f"package {pkg.pack_id} did not load; its metrics are skipped",
                     counter="metric_catalogue.pack_load")
            continue
        metrics = list(getattr(pack, "metrics", None) or [])
        if not metrics:
            continue
        bound = _bound_roles(pkg.pack_id, connection_id, schema_name)
        for pm in metrics:
            required = list(getattr(pm.binds, "required", None) or [])
            missing = [r for r in required if r not in bound]
            sr = getattr(pm, "sane_range", None)
            out.append(CatalogueEntry(
                name=pm.name, label=pm.title or pm.name, source=SOURCE_INDUSTRY,
                state=STATE_NEEDS_BINDING if missing else STATE_PROPOSED,
                sql=(pm.formula or "").strip(),
                unit=pm.unit or pm.unit_or_range or "",
                definition=(pm.definition or "").strip(),
                grain=(pm.grain or "").strip(),
                anti_patterns=list(pm.anti_patterns or []),
                pack_id=pkg.pack_id, required_roles=required, missing_roles=missing,
                sane_range=(sr.model_dump() if hasattr(sr, "model_dump") else sr),
                editable=False,
            ))
    return out


# ── Source 3: the explorer's judgement ────────────────────────────────────────

def _explorer_entries(connection_id: str, schema_name: Optional[str]) -> list[CatalogueEntry]:
    from aughor.business_profile import store as profile_store

    try:
        profile = profile_store.load(connection_id, schema_name)
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the business profile is best-effort; the catalogue lists the other "
                      "sources", counter="metric_catalogue.profile")
        return []
    # The audit's verdicts, persisted beside the profile. Best-effort: an older payload
    # written before they were recorded simply has none, and those rows stay
    # `needs_formula` — which is honest, because for them we genuinely do not know.
    rejections: dict = {}
    try:
        raw = profile_store.load_raw(connection_id, schema_name) or {}
        rejections = raw.get("rejections") or {}
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "metric rejection reasons are best-effort; the row still lists",
                 counter="metric_catalogue.rejections")

    out: list[CatalogueEntry] = []
    for m in (getattr(profile, "north_star_metrics", None) or []):
        # `maps_to` is prose naming real columns ("order_items.sale_price, …"); split it
        # back into the tables it touches so the row can say where the metric lives.
        tables = sorted({p.split(".")[0] for p in re.findall(r"[\w.]+\.[\w]+", m.maps_to or "")})
        value_sql = (getattr(m, "value_sql", "") or "").strip()
        reason = "" if value_sql else str(rejections.get(m.name) or "").strip()
        if value_sql:
            state = STATE_PROPOSED
        elif reason:
            state = STATE_FORMULA_REJECTED   # it HAD one; say why it went
        else:
            state = STATE_NEEDS_FORMULA
        out.append(CatalogueEntry(
            name=normalize_name(m.name), label=m.name, source=SOURCE_EXPLORER,
            state=state, sql=value_sql, reason=reason,
            unit=m.unit_or_range or "", definition=(m.definition or "").strip(),
            tables=tables, why_it_matters=(m.why_it_matters or "").strip(),
            editable=False,
        ))
    return out


# ── The catalogue ─────────────────────────────────────────────────────────────

def catalogue_for(connection_id: str, schema_name: Optional[str] = None) -> list[CatalogueEntry]:
    """Every metric that applies to this connection, best source first, deduped by name.

    Precedence is `defined` → `industry` → `explorer`: an edited definition shadows the
    recipe it came from, and a reviewed industry recipe shadows an inferred one. The
    shadowed row is dropped rather than listed twice — the tab already warns about
    duplicate names, and two rows for one metric is that warning, self-inflicted."""
    if not connection_id:
        return []
    by_source = {
        SOURCE_DEFINED: _defined_entries(connection_id),
        SOURCE_INDUSTRY: _industry_entries(connection_id, schema_name),
        SOURCE_EXPLORER: _explorer_entries(connection_id, schema_name),
    }
    seen: set[str] = set()
    out: list[CatalogueEntry] = []
    for src in _PRECEDENCE:
        for entry in by_source[src]:
            key = normalize_name(entry.name)
            if key in seen:
                continue
            seen.add(key)
            out.append(entry)
    return out


def find_entry(connection_id: str, name: str,
               schema_name: Optional[str] = None) -> Optional[CatalogueEntry]:
    """One catalogue row by name, matched the way the catalogue dedupes."""
    key = normalize_name(name)
    for entry in catalogue_for(connection_id, schema_name):
        if normalize_name(entry.name) == key:
            return entry
    return None


# ── Copy-on-write ─────────────────────────────────────────────────────────────

class MaterialiseError(Exception):
    """The row cannot become an editable definition, and why."""


def materialise(connection_id: str, name: str, schema_name: Optional[str] = None,
                actor: str = "") -> "object":
    """Turn an industry or explorer row into a connection-scoped `MetricDefinition`.

    This is the edit step: the catalogue is computed, so there is nothing to write into
    until someone wants to change one. The copy is scoped to THIS connection, so it
    shadows the recipe for this connection only — another connection reading the same
    package still gets the package's version, and a package update still reaches every
    connection that has not customised it.

    It lands as ``draft``. Never ``approved``: the live catalogue having zero approved
    metrics is what holds outbound KPI sends under law 2, and a formula nobody has
    reviewed must not lift that hold. `status` is moved by the governance transitions the
    Metrics tab already exposes (draft → proposed → approved), by a person.

    A ``needs_binding`` row is refused. Its formula still carries `{{role.x.y}}`
    placeholders, so materialising it would write a definition that cannot execute, and a
    stored definition that cannot execute is worse than an honest absence — it shadows the
    recipe and reads as available.
    """
    from aughor.semantic.metrics import MetricDefinition, get_metric, save_metric

    entry = find_entry(connection_id, name, schema_name)
    if entry is None:
        raise MaterialiseError(f"no metric named {name!r} applies to this connection")
    if entry.source == SOURCE_DEFINED:
        existing = get_metric(entry.name, connection_id=connection_id)
        if existing is not None:
            return existing
        raise MaterialiseError(f"{name!r} is already defined but could not be read back")
    # STATE_NEEDS_FORMULA is deliberately NOT refused: the copy exists so the user can
    # supply the formula, and it lands `draft`, which the coherence guard already skips
    # (it reads only metrics with a non-empty `sql`). Refusing here would leave the one
    # row that most needs editing as the only one that cannot be.
    if entry.state == STATE_NEEDS_BINDING:
        roles = ", ".join(entry.missing_roles) or "its required roles"
        raise MaterialiseError(
            f"{entry.label!r} needs {roles} bound to this connection before it can be "
            f"edited — its formula still names roles, not columns")

    metric = MetricDefinition(
        name=normalize_name(entry.name),
        connection=connection_id,
        label=entry.label or entry.name,
        sql=entry.sql,
        tables=list(entry.tables),
        dimensions=list(entry.dimensions),
        unit=entry.unit or None,
        caveats=entry.definition or None,
        wrong_usage_examples=list(entry.anti_patterns),
        lineage=([f"{entry.source}: {entry.pack_id}"] if entry.pack_id
                 else [entry.source]),
        status="draft",
        proposed_by=actor or None,
    )
    save_metric(metric)
    logger.info("materialised %s metric %r for connection %s", entry.source, metric.name,
                connection_id)
    return metric
