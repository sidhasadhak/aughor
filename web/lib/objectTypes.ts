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
}

export interface TypeMap {
  connection_id: string;
  schema_name: string;
  generated_at: string;
  object_types: TypeMapRow[];
  links: TypeMapLink[];
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
  kind?: "static" | "timeseries";
  read?: boolean;
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
  kind: "static" | "timeseries";
  reads: "table" | "query";
  table?: string;
  sql?: string;
  key: string;
  object_key: string;
  time_column?: string;
  source: "backing" | "human" | "proposed";
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
}

/** What a person sends to bind a source: its table or SELECT, the column holding the object's key, its kind, and —
 *  optionally — `{property: column}` to name what it supplies. */
export interface BindingSpec {
  kind: "static" | "timeseries";
  key: string;
  table?: string;
  sql?: string;
  time_column?: string;
  properties?: Record<string, string>;
}

/** A binding the data proposes — another type's table carrying this type's key, measured one row per object. Nothing
 *  reads it until a person binds it with `spec`. */
export interface ProposedBinding {
  name: string;
  kind: "static" | "timeseries";
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
  lifecycle: { property: string; states: string[]; terminal: string[]; verified: boolean | null; note: string } | null;
  counts: {
    properties: number; bindings: number; proposed_bindings: number; links: number; traversable_links: number;
    actions: number; metrics: number;
  };
  summary: string;
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

function scope(connectionId: string, schemaName?: string, extra: Record<string, string> = {}): string {
  const q = new URLSearchParams({ connection_id: connectionId, ...extra });
  if (schemaName) q.set("schema_name", schemaName);
  return q.toString();
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
