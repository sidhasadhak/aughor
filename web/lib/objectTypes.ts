/**
 * ON-3b — the entity-type map's doors (ROADMAP §3.15, amended 2026-09-11): every object type with the facts its
 * card shows, one type as the entity-type panel shows it, and the paths from one type to another; plus the writes the
 * panel offers — declare a display property, bind or remove a further source (ON-1b), and measure what was declared.
 *
 * The shapes mirror `aughor/semantic/object_types.py` and `aughor/ontology/display.py`. The routes return plain
 * dicts, so `api.gen.ts` types their paths but not their bodies — these do. A refusal is an answer, not an error.
 */
import { getApiBase } from "@/lib/config";

/** One object type on the map: the measured facts its card and its rail row show. */
export interface TypeMapRow {
  object_type: string;
  id: string;
  display_name: string;
  role: string;
  domain: string;
  key: string;
  key_verified: boolean | null;
  rows: number | null;
  table: string;
  display_property: string;
  display_is_key: boolean;
  properties: number;
  bindings: number;
  proposed_bindings: number;
  links: number;
  traversable_links: number;
  actions: number;
  metrics: number;
  /** ON-7 — who made the type: the builder from a table, a person, or an explorer's proposal. */
  origin?: "table" | "human" | "model";
  /** ON-7 — the type this one is a PART of (its api name), "" when it stands on its own. */
  absorbed_into?: string;
  /** ON-7 — the types that are parts of this one, each with the binding it is read through. */
  parts?: TypePart[];
  /** ON-7b — who said a declared type exists when a model did: `model:<id>@<version>`, kept once a person confirms. */
  provenance?: string;
  /** ON-7b — what an explorer proposed on this card that no person has confirmed yet: the type itself, and its bindings. */
  unconfirmed?: number;
  /** ON-8 — the connection this type's objects are read from; in an organisation's ontology each type names its own. */
  connection_id?: string;
}

/** ON-7 — a type that is a part of another: an order's lines under Order. */
export interface TypePart {
  object_type: string;
  display_name: string;
  binding: string;
  kind: string;
  /** ON-7b — `model` while the binding the part is read through is an explorer's unconfirmed proposal. */
  origin?: "human" | "model";
  provenance?: string;
}

/** One link between two types, read from → to. */
export interface TypeMapLink {
  relationship: string;
  from: string;
  to: string;
  name: string;
  reverse_name: string;
  business_name: string;
  verb: string;
  cardinality: string;
  measured: boolean;
  traversable: boolean;
  why_not?: string;
  /** ON-7 — the type each end is DRAWN as: a part's links are drawn from its parent's card. */
  shown_from?: string;
  shown_to?: string;
  origin?: "join_map" | "human" | "model";
  /** ON-7b — `model:<id>@<version>` for a link an explorer proposed. */
  provenance?: string;
  /** ON-8 — `cross-source` when its two types live on two connections: the compiler reads the far side by key. */
  traversal?: "join" | "cross-source";
}

export interface TypeMap {
  connection_id: string;
  schema_name: string;
  generated_at: string;
  /** ON-8 — `org/domain` when this is an organisation's ontology rather than one connection's. */
  domain?: string;
  object_types: TypeMapRow[];
  links: TypeMapLink[];
  /** ON-9 — every declared process and rule, one short row each. Absent on an API older than ON-9. */
  processes?: ProcessRow[];
  rules?: RuleRow[];
}

/** What titles one object of a type, and on what warrant. `source` "key" means nothing else names it — or a
 *  proposal was refuted, named in `refuted`. */
export interface DisplayPropertyFact {
  property: string;
  source: "proposed" | "human" | "key";
  is_key: boolean;
  verified: boolean | null;
  rows: number | null;
  non_null: number | null;
  distinct: number | null;
  note: string;
  refuted?: string;
}

/** Where a property is read from: a binding and its column, or the overlay of accepted edits. `kind` is set for a
 *  further binding (ON-1b), and `read` is false when the compiler does not read that binding yet. */
export interface PropertySource {
  binding: string;
  table?: string;
  column?: string;
  edits?: number;
  kind?: "static" | "timeseries" | "detail";
  read?: boolean;
  /** ON-5 — set when the property is a FRAME over the readings rather than a column of the source. */
  frame?: string;
  /** ON-7 — set when the property is a ROLLUP over a detail binding's rows rather than a column of the source. */
  rollup?: string;
}

export interface TypeProperty {
  name: string;
  display_name: string;
  role: string;
  data_type: string;
  unit: string;
  is_key: boolean;
  null_rate: number | null;
  description: string;
  source: PropertySource;
}

/** One binding a type reads properties through. The first is its backing, whose rows ARE its objects; a further one
 *  (ON-1b) is a table or keyed SELECT joined on the object's key — static (one row per object) or timeseries (many
 *  rows over time). `usable` says whether the compiler and the object page read it, and `why_not` why not. */
export interface TypeBinding {
  name: string;
  primary: boolean;
  kind: "static" | "timeseries" | "detail";
  reads: "table" | "query";
  table?: string;
  sql?: string;
  key: string;
  object_key: string;
  time_column?: string;
  /** `model` — an explorer bound its own proposal (ON-7b): read like any other, proposed until a person confirms it. */
  source: "backing" | "human" | "proposed" | "model";
  provenance?: string;
  verified: boolean | null;
  rows: number | null;
  non_null?: number | null;
  distinct?: number | null;
  objects?: number | null;
  covered?: number | null;
  orphans?: number | null;
  note: string;
  supplies: number;
  skipped?: Record<string, string>;
  usable: boolean;
  why_not?: string;
  /** ON-5 — property name → what its frame over the readings is, in words. */
  frames?: Record<string, string>;
  /** ON-7 — property name → what its rollup over the rows is, in words. */
  rollups?: Record<string, string>;
  /** ON-8 — the connection the source lives on; a further binding names one only when it is not the type's own. */
  connection_id?: string;
}

/** ON-5 — a frame over a timeseries binding's readings: what it reads, how the readings inside the frame are
 *  reduced, and how far the frame reaches. `offset` is "the reading N back", which takes neither an aggregate nor
 *  a window. Each frame becomes a property of the type, read at the object's latest reading. */
export interface FrameSpec {
  column: string;
  agg?: "sum" | "avg" | "min" | "max" | "count";
  range?: "current" | "cumulative" | "trailing" | "leading" | "all";
  window?: number;
  offset?: number;
}

/** What a person sends to bind a source: its table or SELECT, the column holding the object's key, its kind, and —
 *  optionally — `{property: column}` to name what it supplies and `{property: frame}` to compute one. */
export interface BindingSpec {
  kind: "static" | "timeseries" | "detail";
  key: string;
  table?: string;
  sql?: string;
  time_column?: string;
  properties?: Record<string, string>;
  frames?: Record<string, FrameSpec>;
  /** ON-7 — a DETAIL binding (many rows per object, no clock) supplies exactly these, each one value per object. */
  rollups?: Record<string, RollupSpec>;
  /** ON-7 — mark the bound table's own type a PART of this one; the mark holds only while the binding does. */
  absorb?: boolean;
  /** ON-8 — in an organisation's ontology: the connection the source lives on, and the schema that qualifies its table. */
  connection_id?: string;
  schema_name?: string;
}

/** ON-7 — one rollup over a detail binding's rows: the column it reads and how the rows reduce to one value. */
export interface RollupSpec {
  column: string;
  agg?: "sum" | "avg" | "min" | "max" | "count";
}

/** A binding the data proposes — another type's table carrying this type's key, measured one row per object. Nothing
 *  reads it until a person binds it with `spec`. */
export interface ProposedBinding {
  name: string;
  kind: "static" | "timeseries" | "detail";
  table: string;
  key: string;
  object_key: string;
  rows: number | null;
  distinct: number | null;
  objects: number | null;
  covered: number | null;
  orphans: number | null;
  verified: boolean | null;
  note: string;
  supplies: string[];
  skipped: Record<string, string>;
  spec: BindingSpec;
}

/** A link as read from the type it leaves. A refused one carries the compiler's reason. */
export interface TypeLink {
  name: string;
  business_name: string;
  business_name_source: "human" | "proposed" | "";
  verb: string;
  relationship: string;
  direction: "out" | "in";
  to: string;
  to_type: string;
  to_name: string;
  cardinality: string;
  measured: boolean;
  kind: "to-one" | "to-many";
  on: string;
  traversable: boolean;
  why_not?: string;
  /** ON-7 — a link a person declared (or an explorer proposed) can be withdrawn; a found one is named, never deleted. */
  origin?: "join_map" | "human" | "model";
  /** ON-7b — `model:<id>@<version>` for a link an explorer proposed, kept once a person confirms it. */
  provenance?: string;
  /** ON-8 — `cross-source` when the two types live on two connections. */
  traversal?: "join" | "cross-source";
}

export interface TypeAction {
  id: string;
  display_name: string;
  description: string;
  kind: string;
  risk: string;
  why: string;
  params: { name: string; kind: "value" | "object"; object_type: string; data_type: string; required: boolean }[];
  edits: { object: string; property: string }[];
}

export interface TypeMetric {
  id: string;
  display_name: string;
  unit: string;
  formula_sql: string;
}

export interface ObjectTypeDetail {
  path: "object_type";
  connection_id: string;
  schema_name: string;
  object_type: string;
  id: string;
  display_name: string;
  description: string;
  role: string;
  domain: string;
  key: { property: string; verified: boolean | null; rows: number | null; note: string };
  display_property: DisplayPropertyFact;
  /** ON-7 — who made the type, its parts, and the type it is a part of (a lapsed mark says why). */
  origin?: "table" | "human" | "model";
  /** ON-7b — `model:<id>@<version>` when an explorer proposed the type. */
  provenance?: string;
  parts?: TypePart[];
  part_of?: PartOf | null;
  time: string;
  properties: TypeProperty[];
  properties_truncated: boolean;
  bindings: TypeBinding[];
  proposed_bindings: ProposedBinding[];
  links: TypeLink[];
  actions: TypeAction[];
  metrics: TypeMetric[];
  unverified_metrics: string[];
  segments: string[];
  /** ON-9 — the processes this type takes part in, and what declared processes and rules derive on it. */
  processes?: TypeProcessRole[];
  derived?: DerivedRows;
  lifecycle: { property: string; states: string[]; terminal: string[]; verified: boolean | null; note: string } | null;
  counts: {
    properties: number; bindings: number; proposed_bindings: number; links: number; traversable_links: number;
    actions: number; metrics: number; parts?: number;
  };
  summary: string;
}

/** ON-7 — the type this one is a part of. `holds` is false when the parent no longer binds this type's table;
 *  `note` says so. */
export interface PartOf {
  object_type: string;
  id: string;
  display_name: string;
  holds: boolean;
  note: string;
}

/** ON-7 — a business entity a person declares: the noun first, then the source bound into it. */
export interface DeclaredEntitySpec {
  id: string;
  display_name: string;
  description?: string;
  domain?: string;
  entity_type?: "reference_data" | "business_object" | "event" | "standalone";
  /** ON-8 — in an organisation's ontology the backing names the connection its rows live on, and the schema that
   *  qualifies its table there. */
  backing: { table?: string; sql?: string; primary_key: string; connection_id?: string; schema_name?: string };
}

/** ON-7 — a link a person declares between two types: a business verb and the column each side joins on. */
export interface DeclaredLinkSpec {
  from_entity: string;
  to_entity: string;
  name: string;
  from_column: string;
  to_column: string;
  cardinality?: "1:1" | "1:N" | "N:1" | "N:N";
  reverse_name?: string;
}

export interface PathHop {
  link: string;
  business_name: string;
  verb: string;
  from: string;
  from_name: string;
  to: string;
  to_name: string;
  direction: "out" | "in";
  cardinality: string;
  kind: "to-one" | "to-many";
  measured: boolean;
  traversable: boolean;
  why_not?: string;
}

/** One chain of links. `compiles_as` says what the compiler builds along it; empty when it builds nothing. */
export interface TypePath {
  hops: PathHop[];
  length: number;
  traversable: boolean;
  reach: "to-one" | "to-many";
  path: string;
  compiles_as: string[];
  why_not?: string;
}

export interface TypePaths {
  path: "paths";
  connection_id: string;
  schema_name: string;
  from: string;
  from_name: string;
  to: string;
  to_name: string;
  max_hops: number;
  compiler_max_hops: number;
  paths: TypePath[];
  found: number;
  truncated: boolean;
}

export interface TypeRefusal {
  path: "refused";
  refused: string;
  available: string[];
  connection_id: string;
  schema_name: string;
}

/** ON-8 — an organisation's ontology is a scope of its own, carried where a connection id goes: `domain:<name>`. A door
 *  that reads domains is sent `?domain=`; one that does not reads the scope as a connection nobody registered and
 *  answers nothing, rather than another connection's graph. */
const DOMAIN_SCOPE = "domain:";

export function domainScope(name = "default"): string {
  return `${DOMAIN_SCOPE}${name}`;
}

/** The domain a scope names, or null when the scope is a connection. */
export function scopeDomain(connectionId: string): string | null {
  return connectionId.startsWith(DOMAIN_SCOPE) ? connectionId.slice(DOMAIN_SCOPE.length) || "default" : null;
}

function scope(connectionId: string, schemaName?: string, extra: Record<string, string> = {}): string {
  const q = new URLSearchParams({ connection_id: connectionId, ...extra });
  const domain = scopeDomain(connectionId);
  if (domain) q.set("domain", domain);
  else if (schemaName) q.set("schema_name", schemaName);
  return q.toString();
}

/** ON-8 — one of the organisation's ontologies: what it holds, and the connections it reads. */
export interface DomainRow {
  domain: string;
  key: string;
  object_types: number;
  links: number;
  cross_source_links: number;
  connections: string[];
}

export async function getDomains(): Promise<{ org: string; default: string; domains: DomainRow[] }> {
  const res = await fetch(`${getApiBase()}/ontology/domains`);
  if (!res.ok) throw new Error(await detailOf(res));
  return res.json();
}

async function detailOf(res: Response): Promise<string> {
  const body = (await res.json().catch(() => null)) as { detail?: unknown } | null;
  return typeof body?.detail === "string" ? body.detail : `HTTP ${res.status}`;
}

export async function getTypeMap(connectionId: string, schemaName?: string): Promise<TypeMap> {
  const res = await fetch(`${getApiBase()}/object-types?${scope(connectionId, schemaName)}`);
  if (!res.ok) throw new Error(await detailOf(res));
  return res.json();
}

export async function getObjectType(
  objectType: string, connectionId: string, schemaName?: string,
): Promise<ObjectTypeDetail | TypeRefusal> {
  const res = await fetch(
    `${getApiBase()}/object-types/${encodeURIComponent(objectType)}?${scope(connectionId, schemaName)}`);
  if (!res.ok) throw new Error(await detailOf(res));
  return res.json();
}

export async function getTypePaths(
  source: string, target: string, connectionId: string, schemaName?: string, maxHops = 4,
): Promise<TypePaths | TypeRefusal> {
  const extra = { source, target, max_hops: String(maxHops) };
  const res = await fetch(`${getApiBase()}/object-paths?${scope(connectionId, schemaName, extra)}`);
  if (!res.ok) throw new Error(await detailOf(res));
  return res.json();
}

/** Declare the property that names one object of a type. The server refuses a property the type does not have,
 *  and merges the declaration into the type's other human edits rather than replacing them. */
export async function declareDisplayProperty(
  connectionId: string, entityId: string, property: string, schemaName?: string,
): Promise<void> {
  const res = await fetch(
    `${getApiBase()}/ontology/entities/${encodeURIComponent(entityId)}?${scope(connectionId, schemaName)}`,
    { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ display_property: property }) });
  if (!res.ok) throw new Error(await detailOf(res));
}

/** Measure the ontology against the data — cardinalities, lifecycles, keys, display properties and bindings, and the
 *  bindings the data proposes. No model call. */
export async function measureOntology(connectionId: string, schemaName?: string): Promise<void> {
  const res = await fetch(`${getApiBase()}/ontology/measure?${scope(connectionId, schemaName)}`, { method: "POST" });
  if (!res.ok) throw new Error(await detailOf(res));
}

function bindingUrl(connectionId: string, entityId: string, name: string, schemaName?: string): string {
  return `${getApiBase()}/ontology/entities/${encodeURIComponent(entityId)}/bindings/${encodeURIComponent(name)}`
    + `?${scope(connectionId, schemaName)}`;
}

/** Bind a further source to a type (ON-1b). The server reads the source's columns and counts it against the objects
 *  before it answers; a spec that does not bind is refused with the reason and nothing is written. */
export async function addBinding(
  connectionId: string, entityId: string, name: string, spec: BindingSpec, schemaName?: string,
): Promise<void> {
  const res = await fetch(bindingUrl(connectionId, entityId, name, schemaName),
    { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(spec) });
  if (!res.ok) throw new Error(await detailOf(res));
}

/** Remove a binding a person set; the properties it supplied stop resolving on the next read. */
export async function removeBinding(connectionId: string, entityId: string, name: string, schemaName?: string): Promise<void> {
  const res = await fetch(bindingUrl(connectionId, entityId, name, schemaName), { method: "DELETE" });
  if (!res.ok) throw new Error(await detailOf(res));
}


/** Name a link by its business verb (ON-3b). The mechanical names stay and still resolve; this one is accepted
 *  beside them. Refused when it is not snake_case, or already names another link or a property on either type
 *  the link joins — a path segment must name exactly one thing. */
export async function nameLink(
  connectionId: string, relationshipId: string, name: string, schemaName?: string,
): Promise<void> {
  const res = await fetch(
    `${getApiBase()}/ontology/links/${encodeURIComponent(relationshipId)}?${scope(connectionId, schemaName)}`,
    { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name }) });
  if (!res.ok) throw new Error(await detailOf(res));
}


/** ON-7 — declare a business entity. The server reads the source's columns and counts its key before anything is
 *  written; a table that already backs a type is refused with the reason. Returns the type as the panel shows it. */
export async function declareEntity(
  connectionId: string, spec: DeclaredEntitySpec, schemaName?: string,
): Promise<ObjectTypeDetail> {
  const res = await fetch(`${getApiBase()}/ontology/entities?${scope(connectionId, schemaName)}`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(spec) });
  if (!res.ok) throw new Error(await detailOf(res));
  return (await res.json()).entity;
}

/** ON-7 — withdraw a DECLARED entity. A type the builder made from a table is refused: absorb it instead. */
export async function deleteEntity(connectionId: string, entityId: string, schemaName?: string): Promise<void> {
  const res = await fetch(
    `${getApiBase()}/ontology/entities/${encodeURIComponent(entityId)}?${scope(connectionId, schemaName)}`,
    { method: "DELETE" });
  if (!res.ok) throw new Error(await detailOf(res));
}

/** ON-7 — declare a link between two types. Both columns must exist, the name must be free, and each side is
 *  counted before anything is written; the compiler follows it exactly as a found link — measured, not N:N. */
export async function declareLink(connectionId: string, spec: DeclaredLinkSpec, schemaName?: string): Promise<void> {
  const res = await fetch(`${getApiBase()}/ontology/links?${scope(connectionId, schemaName)}`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(spec) });
  if (!res.ok) throw new Error(await detailOf(res));
}

/** ON-7 — withdraw a DECLARED link. A found link is named, never deleted. */
export async function deleteLink(connectionId: string, relationshipId: string, schemaName?: string): Promise<void> {
  const res = await fetch(
    `${getApiBase()}/ontology/links/${encodeURIComponent(relationshipId)}?${scope(connectionId, schemaName)}`,
    { method: "DELETE" });
  if (!res.ok) throw new Error(await detailOf(res));
}

/** ON-7 — mark a type a part of another ("" releases it). Bound against the graph: the parent must carry a binding
 *  over this type's own table, and the mark holds only while it does. */
export async function setPartOf(
  connectionId: string, entityId: string, parentId: string, schemaName?: string,
): Promise<void> {
  const res = await fetch(
    `${getApiBase()}/ontology/entities/${encodeURIComponent(entityId)}?${scope(connectionId, schemaName)}`,
    { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ absorbed_into: parentId }) });
  if (!res.ok) throw new Error(await detailOf(res));
}

/** ON-7b — where an explorer's proposal stands NOW, read from the served graph; `refused` is what the data said when it
 *  was proposed. */
export type ProposalTier = "proposed" | "confirmed" | "released" | "withdrawn" | "refused";

/** ON-7b — one thing an explorer proposed: an entity, a part (a table read under an entity), or a link. */
export interface DraftProposal {
  key: string;
  kind: "entity" | "part" | "link";
  tier: ProposalTier;
  sentence: string;
  /** What the measurement said — the counts it rests on, or why it was refused. */
  note: string;
  /** The model's own reason. */
  reason: string;
  provenance: string;
  target: { entity?: string; binding?: string; table?: string; part?: string; relationship?: string };
  /** The type to open to see it where it lives ("" when nothing was written). */
  object_type: string;
}

/** ON-7b — one explorer run: the model that ANSWERED (a fallback link may stand in for the one asked) and what came of it. */
export interface DraftRun {
  id: string;
  at: string;
  backend: string;
  model: string;
  fallback: boolean;
  version: number;
  provenance: string;
  /** The run's trace — its model call and what it wrote, replayable in Activity. */
  trace_id?: string;
  catalogue_chars: number;
  said: { entities?: number; parts?: number; links?: number };
  written: number;
  refused: number;
  already: number;
  withdrawn: number;
}

export interface OntologyDraft {
  connection_id: string;
  schema_name: string;
  /** Newest first. */
  runs: DraftRun[];
  proposals: DraftProposal[];
  counts: Record<ProposalTier, number>;
  /** How the tables group into business entities: each card's tables. */
  grouping: Record<string, string[]>;
}

/** ON-7b — a declaration a person makes theirs: a declared entity, a declared link, or the binding a part is read through. */
export interface ConfirmTarget {
  kind: "entity" | "binding" | "link";
  entity?: string;
  binding?: string;
  relationship?: string;
}

export interface ConfirmResult extends OntologyDraft {
  confirmed: ConfirmTarget[];
  refused: (ConfirmTarget & { why: string })[];
}

/** ON-7b — the scope's explorer draft. No model call. */
export async function getOntologyDraft(connectionId: string, schemaName?: string): Promise<OntologyDraft> {
  const res = await fetch(`${getApiBase()}/ontology/draft?${scope(connectionId, schemaName)}`);
  if (!res.ok) throw new Error(await detailOf(res));
  return res.json();
}

/** ON-7b — ask an explorer to draft the business: ONE model call. Every proposal is measured before it lands, and what
 *  survives is written through the declaration doors, proposed until a person confirms it. */
export async function exploreOntology(connectionId: string, schemaName?: string): Promise<OntologyDraft> {
  const res = await fetch(`${getApiBase()}/ontology/explore?${scope(connectionId, schemaName)}`, { method: "POST" });
  if (!res.ok) throw new Error(await detailOf(res));
  return res.json();
}

/** ON-7b — make proposals a person's: every one still the model's (`all`), or the named ones. A target that is not a
 *  model's proposal comes back in `refused` with the reason. */
export async function confirmProposals(
  connectionId: string, request: { all?: boolean; targets?: ConfirmTarget[] }, schemaName?: string,
): Promise<ConfirmResult> {
  const res = await fetch(`${getApiBase()}/ontology/draft/confirm?${scope(connectionId, schemaName)}`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(request) });
  if (!res.ok) throw new Error(await detailOf(res));
  return res.json();
}


// ── ON-9: processes, promises and rules ────────────────────────────────────────────────────

export type DeclarationOrigin = "human" | "model" | "pack";

/** ON-9 — one declared process as the map's rail lists it. */
export interface ProcessRow {
  id: string;
  display_name: string;
  /** The api name of the type that goes through it. */
  entity: string;
  origin: DeclarationOrigin;
  verified: boolean | null;
  objects: number | null;
  stages: string[];
  promises: { stage: string; name: string; breach_rate: number | null; verified: boolean | null; flags: number }[];
}

/** ON-9 — one declared rule as the map's rail lists it. */
export interface RuleRow {
  id: string;
  display_name: string;
  entity: string;
  kind: "value_set" | "condition";
  origin: DeclarationOrigin;
  verified: boolean | null;
  admitted: number | null;
  objects: number | null;
  flags: number;
}

/** ON-9 — a name a declared process or rule derives on a type, and whether the compiler reads it yet. */
export interface DerivedRow {
  name: string;
  kind: "segment" | "property" | "metric";
  source: string;
  description: string;
  usable: boolean;
  why_not?: string;
  caveats?: string[];
  target_value?: number;
}

export interface DerivedRows {
  segments: DerivedRow[];
  properties: DerivedRow[];
  metrics: DerivedRow[];
}

/** ON-9 — a process a type takes part in: as the type that goes through it, or as the type a promise is kept per. */
export interface TypeProcessRole {
  id: string;
  display_name: string;
  roles: string[];
  verified: boolean | null;
  stages: string[];
}

/** The move from the previous stage, timed in calendar days. */
export interface ProcessTransition {
  from: string;
  both: number | null;
  skipped: number | null;
  out_of_order: number | null;
  p50_days: number | null;
  p90_days: number | null;
  p95_days: number | null;
  /** The derived property that holds the lag, per object. */
  lag: string;
}

/** A promise about reaching a stage, with what the data counted and the names it derives. */
export interface ProcessPromise {
  name: string;
  kind: "deadline" | "within_days";
  deadline: string;
  within_days: number | null;
  /** The api name of the type the promise is kept per, and its id. */
  grain: string;
  grain_id: string;
  via: string;
  target: number | null;
  objects: number | null;
  reached: number | null;
  breached: number | null;
  kept: number | null;
  open: number | null;
  open_overdue: number | null;
  breach_rate: number | null;
  as_of: string;
  verified: boolean | null;
  flags: string[];
  note: string;
  segment: string;
  metric: string;
}

export interface ProcessStageDetail {
  name: string;
  display_name: string;
  anchor: { timestamp: string } | { state: string[]; property: string };
  reached: number | null;
  share: number | null;
  verified: boolean | null;
  note: string;
  transition: ProcessTransition | null;
  promise: ProcessPromise | null;
}

/** ON-9 — one declared process, as `GET /ontology/processes` describes it. */
export interface ProcessDetail {
  id: string;
  display_name: string;
  description: string;
  entity: string;
  entity_id: string;
  owner: string;
  origin: DeclarationOrigin;
  provenance: string;
  objects: number | null;
  verified: boolean | null;
  note: string;
  measured_at: string;
  stages: ProcessStageDetail[];
  derived: DerivedRows;
}

/** ON-9 — one declared rule, as `GET /ontology/processes` describes it. */
export interface RuleDetail {
  id: string;
  display_name: string;
  description: string;
  owner: string;
  entity: string;
  entity_id: string;
  kind: "value_set" | "condition";
  property: string;
  values: string[];
  conditions: Record<string, unknown>[];
  origin: DeclarationOrigin;
  provenance: string;
  objects: number | null;
  admitted: number | null;
  observed: Record<string, number>;
  missing: string[];
  verified: boolean | null;
  flags: string[];
  note: string;
  segment: string;
}

export interface ProcessesAndRules {
  /** One connection's ontology; an organisation's names its `domain` instead (ON-8). */
  connection_id?: string;
  schema_name?: string;
  domain?: string;
  processes: ProcessDetail[];
  rules: RuleDetail[];
}

/** ON-9 — a process a person declares: the type that goes through it and its stages in order. */
export interface DeclaredProcessSpec {
  id: string;
  display_name?: string;
  description?: string;
  entity: string;
  owner?: string;
  stages: {
    name: string;
    display_name?: string;
    timestamp?: string;
    state?: string[];
    property?: string;
    promise?: { name?: string; within_days?: number; deadline?: string; grain?: string; via?: string; target?: number };
  }[];
}

/** The schemas of one connection that have an ontology built, beside the one its registry names — a read of the store;
 *  no connection is opened. */
export async function listOntologySchemas(connectionId: string): Promise<string[]> {
  const res = await fetch(`${getApiBase()}/ontology/schemas?${new URLSearchParams({ connection_id: connectionId })}`);
  if (!res.ok) throw new Error(await detailOf(res));
  return ((await res.json()) as { schemas?: string[] }).schemas ?? [];
}

/** A schema picker's list with `found` added after what it already offers, each once and in the order found. */
export function withSchemas(current: string[], found: string[]): string[] {
  return [...current, ...found.filter((name, i) => name && !current.includes(name) && found.indexOf(name) === i)];
}

/** ON-9 — every declared process and rule on the scope, with what their measurement counted. */
export async function getProcesses(connectionId: string, schemaName?: string): Promise<ProcessesAndRules> {
  const res = await fetch(`${getApiBase()}/ontology/processes?${scope(connectionId, schemaName)}`);
  if (!res.ok) throw new Error(await detailOf(res));
  return res.json();
}

/** ON-9 — declare a process. Every anchor is resolved and the whole declaration is counted before anything is written;
 *  a declaration the data cannot hold is refused with the reason. Returns the process as the panel shows it. */
export async function declareProcess(
  connectionId: string, spec: DeclaredProcessSpec, schemaName?: string,
): Promise<ProcessDetail> {
  const res = await fetch(`${getApiBase()}/ontology/processes?${scope(connectionId, schemaName)}`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(spec) });
  if (!res.ok) throw new Error(await detailOf(res));
  return (await res.json()).process;
}

/** ON-9 — withdraw a declared process; every name it derives stops resolving on the next read. */
export async function deleteProcess(connectionId: string, processId: string, schemaName?: string): Promise<void> {
  const res = await fetch(
    `${getApiBase()}/ontology/processes/${encodeURIComponent(processId)}?${scope(connectionId, schemaName)}`,
    { method: "DELETE" });
  if (!res.ok) throw new Error(await detailOf(res));
}

/** ON-9 — withdraw a declared rule; the segment it named stops resolving on the next read. */
export async function deleteRule(connectionId: string, ruleId: string, schemaName?: string): Promise<void> {
  const res = await fetch(
    `${getApiBase()}/ontology/rules/${encodeURIComponent(ruleId)}?${scope(connectionId, schemaName)}`,
    { method: "DELETE" });
  if (!res.ok) throw new Error(await detailOf(res));
}
