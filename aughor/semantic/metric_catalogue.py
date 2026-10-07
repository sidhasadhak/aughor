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
  applicable metric) but never as though it were available. `unmeasured ⇒ never read`. Never a
  dead end (the user, 2026-10-07): a person binds its roles, writes its SQL over this connection's
  own columns (`materialise` lands it as a draft to write), or removes it.
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


_MEASURED = re.compile(r"\s*\(measured\s*≈[^)]*\)", re.IGNORECASE)


def plain_unit(text) -> str:
    """A unit without the figure the explorer measured once and wrote into it — "USD (measured ≈
    508.18)" is "USD". That figure anchors the explorer's own magnitude check; as a metric's unit it
    is a number frozen at profiling time, shown beside every figure since as if it were current
    (the user, 2026-10-07: "no static or stale metrics")."""
    return _MEASURED.sub("", str(text or "")).strip()


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
    #: The dataset (schema) it belongs to; ``"*"`` — every dataset of the connection. Two datasets
    #: may each have their own `revenue`, so a row is (source, dataset, name), never the name alone.
    schema: str = "*"

    def as_dict(self) -> dict:
        from dataclasses import asdict
        return asdict(self)


# ── Source 1: the registry ────────────────────────────────────────────────────

def _defined_entries(connection_id: str, schema_name: Optional[str] = None) -> list[CatalogueEntry]:
    """The connection's definitions in view: with a dataset, that dataset's and those promoted to
    every dataset (`list_metrics`' own rule); without one, every dataset's. Each says which it is."""
    from aughor.semantic.metrics import ALL_DATASETS, home_schema, list_metrics

    scope = None if schema_name in (None, "", ALL_DATASETS) else schema_name
    out: list[CatalogueEntry] = []
    for m in list_metrics(connection_id=connection_id, schema_name=scope):
        out.append(CatalogueEntry(
            name=m.name, label=m.label or m.name, source=SOURCE_DEFINED,
            state=STATE_DEFINED, sql=m.sql or "", unit=plain_unit(m.unit),
            definition=m.caveats or "", dimensions=list(m.dimensions or []),
            tables=list(m.tables or []), anti_patterns=list(m.wrong_usage_examples or []),
            status=m.status or "draft", version=int(m.version or 0),
            owner=m.owner or "", editable=True, schema=home_schema(m),
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
                editable=False, schema=schema_name or "*",
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
        # The table is everything before the column: `orders.amount` → `orders`, and a qualified
        # `marts.orders.amount` → `marts.orders`, not the dataset alone.
        tables = sorted({p.rsplit(".", 1)[0] for p in re.findall(r"[\w.]+\.[\w]+", m.maps_to or "")})
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
            unit=plain_unit(m.unit_or_range), definition=(m.definition or "").strip(),
            tables=tables, why_it_matters=(m.why_it_matters or "").strip(),
            editable=False, schema=schema_name or "*",
        ))
    return out


# ── The catalogue ─────────────────────────────────────────────────────────────

def _datasets_of(connection_id: str, schema_name: Optional[str]) -> list[Optional[str]]:
    """The datasets whose proposals a view lists: the one in view, or — for every dataset (``"*"``) —
    each dataset the explorer has profiled, else the connection's own profile."""
    from aughor.semantic.metrics import ALL_DATASETS
    if schema_name != ALL_DATASETS:
        return [schema_name or None]
    try:
        from aughor.business_profile.store import profiled_schemas
        return list(profiled_schemas(connection_id)) or [None]
    except Exception as exc:  # noqa: BLE001 — no profile store means the connection's own view
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the profiled datasets could not be listed; the connection's own profile is read",
                 counter="metric_catalogue.datasets")
        return [None]


def _one_unbound_row_per_recipe(rows: list[CatalogueEntry]) -> list[CatalogueEntry]:
    """Across every dataset, an industry recipe no dataset has bound is ONE row for the connection —
    not the same "needs binding" eleven times. A recipe some dataset HAS bound keeps that dataset's row."""
    out: list[CatalogueEntry] = []
    seen_unbound: set[str] = set()
    for r in rows:
        if r.state != STATE_NEEDS_BINDING:
            out.append(r)
            continue
        key = normalize_name(r.name)
        if key in seen_unbound:
            continue
        seen_unbound.add(key)
        r.schema = "*"
        out.append(r)
    return out


def catalogue_for(connection_id: str, schema_name: Optional[str] = None) -> list[CatalogueEntry]:
    """Every metric that applies to this connection, best source first, one row per metric.

    ``schema_name`` — the dataset in view; ``"*"`` — every dataset of the connection at once, each
    row saying which it is (the user, 2026-10-07: *"when I select all schemas … all the metrics across
    all the schemas of the selected connection should be displayed"*). Without either, the
    connection's own view.

    Precedence is `defined` → `industry` → `explorer`: an edited definition shadows the recipe it
    came from, and a reviewed industry recipe shadows an inferred one — WITHIN a dataset. A
    definition promoted to every dataset shadows that name in all of them; one dataset's definition
    shadows only its own. A proposal a person removed is not listed (`removed_for` lists those)."""
    from aughor.semantic.metrics import ALL_DATASETS, dismissed_proposals, is_dismissed

    if not connection_id:
        return []
    every = schema_name == ALL_DATASETS
    defined = _defined_entries(connection_id, schema_name)
    industry: list[CatalogueEntry] = []
    explorer: list[CatalogueEntry] = []
    for ds in _datasets_of(connection_id, schema_name):
        industry += _industry_entries(connection_id, ds)
        explorer += _explorer_entries(connection_id, ds)
    if every:
        industry = _one_unbound_row_per_recipe(industry)
    try:
        removed = dismissed_proposals(connection_id)
    except Exception as exc:  # noqa: BLE001 — an unreadable store removes nothing and says so
        from aughor.kernel.errors import tolerate
        tolerate(exc, "removed proposals could not be read; every proposal is listed",
                 counter="metric_catalogue.removed")
        removed = []

    taken: set[tuple[str, str]] = set()     # (dataset, name) a better source already lists

    def _slot(e: CatalogueEntry) -> tuple[str, str]:
        # One view of one dataset is one namespace; the every-dataset view is one per dataset.
        return ((e.schema or "*").lower() if every else "*", normalize_name(e.name))

    def _shadowed(e: CatalogueEntry) -> bool:
        ds, key = _slot(e)
        if ds == "*":
            return any(n == key for _, n in taken)
        return (ds, key) in taken or ("*", key) in taken

    out: list[CatalogueEntry] = []
    for e in defined:
        if _slot(e) in taken:
            continue
        taken.add(_slot(e))
        out.append(e)
    for batch in (industry, explorer):
        for e in batch:
            if _shadowed(e) or is_dismissed(removed, connection_id, e.schema, e.name):
                continue
            taken.add(_slot(e))
            out.append(e)
    return out


def removed_for(connection_id: str, schema_name: Optional[str] = None) -> list[dict]:
    """The proposals a person removed, as the view in ``schema_name`` would have listed them."""
    from aughor.semantic.metrics import ALL_DATASETS, dismissed_proposals
    rows = dismissed_proposals(connection_id)
    if schema_name in (None, "", ALL_DATASETS):
        return rows
    want = schema_name.lower()
    return [d for d in rows if str(d.get("schema_name") or "*").lower() in (want, "*")]


def find_entry(connection_id: str, name: str,
               schema_name: Optional[str] = None) -> Optional[CatalogueEntry]:
    """One catalogue row by name, matched the way the catalogue dedupes — in the dataset named
    (``"*"``: the row the every-dataset view lists for the connection)."""
    from aughor.semantic.metrics import same_dataset
    key = normalize_name(name)
    rows = [e for e in catalogue_for(connection_id, schema_name) if normalize_name(e.name) == key]
    want = (schema_name or "").strip()
    for entry in rows:
        if not want or same_dataset(entry.schema, want):
            return entry
    return rows[0] if rows else None


# ── Copy-on-write ─────────────────────────────────────────────────────────────

class MaterialiseError(Exception):
    """The row cannot become an editable definition, and why."""


#: `{{role.<role>.<attribute>}}` — the one token an industry formula is written in.
_ROLE_TOKEN = re.compile(r"\{\{\s*role\.([A-Za-z_][\w]*)\.([A-Za-z_][\w]*)\s*\}\}")


def _quote_for(connection_id: str, identifier: str) -> str:
    """`identifier` quoted the way THIS connection's engine quotes identifiers.

    Backtick engines (BigQuery, MySQL) read a double-quoted token as a string; the rest
    read a backtick as one. There is no neutral character, which is why the caller above
    avoids quoting whenever it can."""
    dialect = ""
    try:
        from aughor.db.registry import get_dsn
        from aughor.db.connection import connection_traits
        conn_type, _ = get_dsn(connection_id)
        dialect = str((connection_traits(conn_type) or {}).get("dialect") or "")
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "dialect lookup is best-effort; the identifier is quoted the "
                      "ANSI way", counter="metric_catalogue.dialect")
    if dialect in ("bigquery", "mysql"):
        return "`" + identifier.replace("`", "``") + "`"
    return '"' + identifier.replace('"', '""') + '"'


def _resolve_roles(sql: str, pack_id: str, connection_id: str,
                   schema_name: Optional[str]) -> tuple[str, list[str]]:
    """An industry formula with every role token replaced by the column this connection
    bound to it. Returns (sql, unresolved) — `unresolved` names what had no binding.

    Materialise used to copy `entry.sql` verbatim, so a metric that passed the role gate
    landed as a `defined` metric whose SQL still read `{{role.order_item.returned_at}}` —
    a governed definition nobody can run. The resolver already existed one module away
    (`packs.gate4.bind_expression`, which measures a pack against its own dataset); it
    simply was not reached from the door a person uses.

    Checked per ATTRIBUTE, which the catalogue's `missing_roles` cannot be: that gate is
    role-level, so a formula naming an attribute the connection never bound passes it and
    then renders a token. theLook binds `order_item` and has no `cancelled` column — role
    bound, attribute missing, and only this catches it.
    """
    unresolved: list[str] = []
    try:
        from aughor.packs.bindings import load_binding
        bound = (load_binding(pack_id, connection_id, schema_name or "") or {}).get("bindings") or {}
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "binding lookup is best-effort; the formula is reported unresolved",
                 counter="metric_catalogue.resolve")
        bound = {}

    def _sub(m: "re.Match") -> str:
        role, attribute = m.group(1), m.group(2)
        columns = (bound.get(role) or {}).get("columns") or {}
        column = columns.get(attribute)
        if not column:
            unresolved.append(f"{role}.{attribute}")
            return m.group(0)
        # BARE where it is safe, because the quote character is not portable and getting
        # it wrong is SILENT. `gate4.bind_expression` wraps the column in double quotes,
        # which is right for DuckDB and catastrophic on BigQuery: there `"returned_at"`
        # is a STRING LITERAL, never NULL, so `CASE WHEN "returned_at" IS NOT NULL` is
        # true for every row. Measured on theLook — the metric read 1.0 (a 100% return
        # rate) where the same formula over the bare column reads 0.0987. A wrong number
        # that runs is worse than SQL that fails, and this one runs everywhere.
        #
        # An ordinary identifier needs no quoting in any dialect this platform speaks, so
        # emit it as written and quote only what actually needs it — and then in the
        # dialect's own character.
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", column):
            return column
        return _quote_for(connection_id, column)

    return _ROLE_TOKEN.sub(_sub, sql or ""), unresolved


def materialise(connection_id: str, name: str, schema_name: Optional[str] = None,
                actor: str = "") -> "object":
    """Turn an industry or explorer row into a `MetricDefinition` of THIS connection and dataset.

    This is the edit step: the catalogue is computed, so there is nothing to write into
    until someone wants to change one. The copy is scoped to THIS connection, so it
    shadows the recipe for this connection only — another connection reading the same
    package still gets the package's version, and a package update still reaches every
    connection that has not customised it. And to the row's DATASET: staging's `revenue` and
    marts' `revenue` become two definitions, never one overwriting the other (promoting one to
    the whole connection is a separate, deliberate step).

    It lands as ``draft``. Never ``approved``: the live catalogue having zero approved
    metrics is what holds outbound KPI sends under law 2, and a formula nobody has
    reviewed must not lift that hold. `status` is moved by the governance transitions the
    Metrics tab already exposes (draft → proposed → approved), by a person.

    A recipe whose roles or attributes this connection has not bound lands as a draft WITHOUT
    SQL — its formula carried in the caveats, naming the roles it needs — for the person to write
    over this connection's own columns. It used to be refused, which left the row with no action
    at all (the user, 2026-10-07: *"no 'this requires binding' — that's a dead end"*). A draft
    with no SQL is never measured and never shadows a computable recipe as available: the
    coherence guard and every measurement read only definitions that have SQL.
    """
    from aughor.semantic.metrics import ALL_DATASETS, MetricDefinition, definition_at, save_metric

    entry = find_entry(connection_id, name, schema_name)
    if entry is None:
        raise MaterialiseError(f"no metric named {name!r} applies to this connection")
    dataset = entry.schema or schema_name or ALL_DATASETS
    if entry.source == SOURCE_DEFINED:
        existing = definition_at(entry.name, connection_id, dataset)
        if existing is not None:
            return existing
        raise MaterialiseError(f"{name!r} is already defined but could not be read back")
    # STATE_NEEDS_FORMULA is deliberately NOT refused: the copy exists so the user can
    # supply the formula, and it lands `draft`, which the coherence guard already skips
    # (it reads only metrics with a non-empty `sql`). Refusing here would leave the one
    # row that most needs editing as the only one that cannot be.
    sql, to_write = entry.sql, ""
    if entry.source == SOURCE_INDUSTRY:
        sql, unresolved = _resolve_roles(sql, entry.pack_id, connection_id,
                                         None if dataset == ALL_DATASETS else dataset)
        if entry.state == STATE_NEEDS_BINDING or unresolved:
            needs = sorted(set(unresolved)) or [f"{r}.*" for r in entry.missing_roles]
            to_write = (f"Write this over this connection's own columns. The {entry.pack_id} package's "
                        f"formula is {entry.sql.strip()} — it needs {', '.join(needs)}; binding those "
                        f"roles under Settings ▸ System ▸ Packages lets the package resolve it instead.")
            sql = ""

    from aughor.semantic.metric_statement import as_statement
    caveats = "\n\n".join(t for t in (entry.definition, to_write) if t) or None
    metric = MetricDefinition(
        name=normalize_name(entry.name),
        connection=connection_id,
        schema_name=dataset,
        label=entry.label or entry.name,
        # Every proposal is a statement (2026-09-26): a catalogue formula written as an
        # aggregate is wrapped over its first table, so the editor opens on runnable SQL.
        sql=as_statement(sql, list(entry.tables), [], normalize_name(entry.name)) if sql else "",
        tables=list(entry.tables),
        dimensions=list(entry.dimensions),
        unit=entry.unit or None,
        caveats=caveats,
        wrong_usage_examples=list(entry.anti_patterns),
        lineage=([f"{entry.source}: {entry.pack_id}"] if entry.pack_id
                 else [entry.source]),
        status="draft",
        proposed_by=actor or None,
    )
    from aughor.semantic.metric_time import with_dates
    metric = with_dates(connection_id, metric)
    save_metric(metric)
    logger.info("materialised %s metric %r for connection %s (dataset %s)", entry.source, metric.name,
                connection_id, dataset)
    return metric
