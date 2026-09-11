/**
 * ON-3b — the entity-type map's doors (ROADMAP §3.15, amended 2026-09-11): every object type with the facts its
 * card shows, one type as the entity-type panel shows it, and the paths from one type to another; plus the two
 * writes the panel offers — declare a display property, and measure what was declared.
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

/** Where a property is read from: a binding and its column, or the overlay of accepted edits. */
export interface PropertySource {
  binding: string;
  table?: string;
  column?: string;
  edits?: number;
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

export interface TypeBinding {
  name: string;
  kind: "table" | "query";
  table?: string;
  sql?: string;
  key: string;
  verified: boolean | null;
  rows: number | null;
  note: string;
  supplies: number;
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
  links: TypeLink[];
  actions: TypeAction[];
  metrics: TypeMetric[];
  unverified_metrics: string[];
  segments: string[];
  lifecycle: { property: string; states: string[]; terminal: string[]; verified: boolean | null; note: string } | null;
  counts: { properties: number; bindings: number; links: number; traversable_links: number; actions: number; metrics: number };
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

/** Measure the ontology against the data — cardinalities, lifecycles, keys and display properties. No model call. */
export async function measureOntology(connectionId: string, schemaName?: string): Promise<void> {
  const res = await fetch(`${getApiBase()}/ontology/measure?${scope(connectionId, schemaName)}`, { method: "POST" });
  if (!res.ok) throw new Error(await detailOf(res));
}
