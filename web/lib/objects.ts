/**
 * ON-3 — the object plane's read doors (ROADMAP §3.15): one object by type and key, one page of
 * the objects a link reaches from it, and the catalog of object types.
 *
 * The shapes mirror `aughor/semantic/object_instances.py` and `object_context.py`. The object
 * routes return plain dicts, so `api.gen.ts` types their paths but not their bodies — these do.
 * A refusal and a 404 are answers here, not errors: the page renders what they say.
 */
import { getApiBase } from "@/lib/config";

export interface ObjectProperty {
  name: string;
  value: unknown;
  display_name: string;
  semantic_type: string;
  data_type: string;
  unit: string;
  description: string;
}

/** A link from this object. A to-one link resolves to the linked object's key, a to-many link to
 *  a count; one the compiler refuses carries `why_not` and is never traversed. */
export interface ObjectLink {
  name: string;
  to: string;
  to_type: string;
  cardinality: string;
  on: string;
  kind: "to-one" | "to-many";
  usable: boolean;
  why_not?: string;
  pk?: string | null;
  count?: number;
}

/** A verified metric compiled with this object as the filter — on its own type, or across a
 *  to-many link (`via`). A refusal or an error is shown, never a number. */
export interface ObjectMetric {
  metric: string;
  display_name: string;
  unit?: string | null;
  on: string;
  via: string;
  value?: unknown;
  sql?: string;
  refused?: string;
  error?: string;
}

/** A finding or an answer whose SQL filters this object's key by its exact value (`matched`). */
export interface ObjectCitation {
  kind: "finding" | "answer";
  id: string;
  text: string;
  matched: string;
  domain?: string;
  question?: string;
  at?: string | null;
}

export interface ObjectNote {
  column: string;
  kind: string;
  body: string;
  source: string;
  at: string;
}

export interface ObjectActionParam {
  name: string;
  display_name: string;
  data_type: string;
  required: boolean;
  description: string;
  value: unknown;
}

/** A declared action that takes this object — `prefilled` names the parameters carrying its key. */
export interface ObjectAction {
  id: string;
  display_name: string;
  description: string;
  kind: string;
  risk: string;
  params: ObjectActionParam[];
  prefilled: string[];
  why: string;
}

export interface ObjectRelated {
  metrics: ObjectMetric[];
  findings: ObjectCitation[];
  notes: ObjectNote[];
  actions: ObjectAction[];
}

export interface ObjectPage {
  path: "object";
  connection_id: string;
  schema_name: string;
  object_type: string;
  type_id: string;
  type_name: string;
  key: string;
  pk: string;
  title: string | null;
  properties: ObjectProperty[];
  links: ObjectLink[];
  caveats: string[];
  related: ObjectRelated;
}

/** The compiler's refusal — it says why and names what exists. */
export interface ObjectRefusal {
  path: "refused";
  refused: string;
  available: string[];
  connection_id: string;
  schema_name: string;
}

/** 404 — no object has that key, or no ontology is built for the scope. */
export interface ObjectMissing {
  path: "missing";
  detail: string;
}

export interface LinkedObjectsPage {
  path: "links";
  connection_id: string;
  schema_name: string;
  link: string;
  object_type: string;
  type_id: string;
  type_name: string;
  key: string;
  title_column: string | null;
  cardinality: string;
  offset: number;
  limit: number;
  columns: string[];
  rows: unknown[][];
  has_more: boolean;
}

export interface ObjectCatalogLink {
  name: string;
  to: string;
  cardinality: string;
  on: string;
  usable: boolean;
  why_not?: string;
}

export interface ObjectCatalogType {
  object_type: string;
  id: string;
  display_name: string;
  key: string;
  key_unique: boolean | null;
  time: string;
  properties: Record<string, string[]>;
  links: ObjectCatalogLink[];
  segments: string[];
  metrics: string[];
}

export interface ObjectCatalog {
  connection_id: string;
  schema_name: string;
  object_types: ObjectCatalogType[];
}

/** An omitted connection is the server's default, never an empty `connection_id=`. */
function scope(connectionId?: string, schemaName?: string, extra: Record<string, string> = {}): string {
  const q = new URLSearchParams(extra);
  if (connectionId) q.set("connection_id", connectionId);
  if (schemaName) q.set("schema_name", schemaName);
  const s = q.toString();
  return s ? `?${s}` : "";
}

async function detailOf(res: Response): Promise<string> {
  const body = (await res.json().catch(() => null)) as { detail?: unknown } | null;
  return typeof body?.detail === "string" ? body.detail : `HTTP ${res.status}`;
}

function objectPath(objectType: string, pk: string): string {
  return `${getApiBase()}/objects/${encodeURIComponent(objectType)}/${encodeURIComponent(pk)}`;
}

export async function getObjectPage(
  objectType: string, pk: string, connectionId?: string, schemaName?: string,
): Promise<ObjectPage | ObjectRefusal | ObjectMissing> {
  const res = await fetch(`${objectPath(objectType, pk)}${scope(connectionId, schemaName)}`);
  if (res.status === 404) return { path: "missing", detail: await detailOf(res) };
  if (!res.ok) throw new Error(await detailOf(res));
  return res.json();
}

export async function getLinkedObjects(
  objectType: string, pk: string, link: string, connectionId?: string, schemaName?: string,
  page: { limit?: number; offset?: number } = {},
): Promise<LinkedObjectsPage | ObjectRefusal | ObjectMissing> {
  const extra = { limit: String(page.limit ?? 25), offset: String(page.offset ?? 0) };
  const res = await fetch(
    `${objectPath(objectType, pk)}/links/${encodeURIComponent(link)}${scope(connectionId, schemaName, extra)}`);
  if (res.status === 404) return { path: "missing", detail: await detailOf(res) };
  if (!res.ok) throw new Error(await detailOf(res));
  return res.json();
}

export async function getObjectCatalog(connectionId?: string, schemaName?: string): Promise<ObjectCatalog> {
  const res = await fetch(`${getApiBase()}/objects/catalog${scope(connectionId, schemaName)}`);
  if (!res.ok) throw new Error(await detailOf(res));
  return res.json();
}

const catalogs = new Map<string, Promise<ObjectCatalog | null>>();

/** The catalog once per connection per tab — every answer table in a thread reads it. A failure
 *  (no ontology built yet) is not remembered, so a later table asks again. */
export function cachedObjectCatalog(connectionId: string): Promise<ObjectCatalog | null> {
  const hit = catalogs.get(connectionId);
  if (hit) return hit;
  const pending = getObjectCatalog(connectionId).catch(() => {
    catalogs.delete(connectionId);
    return null;
  });
  catalogs.set(connectionId, pending);
  return pending;
}
