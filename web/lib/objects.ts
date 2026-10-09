/**
 * ON-3 — the object plane's read doors (ROADMAP §3.15): one object by type and key, one page of
 * the objects a link reaches from it, and the catalog of object types.
 *
 * The shapes mirror `aughor/semantic/object_instances.py` and `object_context.py`. The object
 * routes return plain dicts, so `api.gen.ts` types their paths but not their bodies — these do.
 * A refusal and a 404 are answers here, not errors: the page renders what they say.
 */
import { getApiBase } from "@/lib/config";
import { scopeDomain } from "@/lib/objectTypes";

export interface ObjectProperty {
  name: string;
  value: unknown;
  display_name: string;
  semantic_type: string;
  data_type: string;
  unit: string;
  description: string;
  /** ON-4 — set by an accepted action and merged at read time: who, when, and why. */
  overlay?: { by: string; at: string; note: string; origin: string; provenance: string; id: string;
              /** Arc OC-6 — how many times it has been set or withdrawn; a press sends the version it read. */
              version?: number };
  /** PENDING item 27 — a formula evaluated for this object: an expression a person declared, or a computed property
   *  the builder verified. Not a column of the source row. */
  formula?: { expression: string; kind: "expression" | "computed" };
  /** ON-1b — read through a further binding on the object's key: which binding, its source, and the column.
   *  ON-5 — a `timeseries` binding reads the object's LATEST value: `at` is when that was measured, `previous`
   *  is what it read on the reading before that (`previous_at` when), and `note` is the reduction in the
   *  declaration's own words. */
  binding?: {
    name: string;
    kind: string;
    source: string;
    column: string;
    time_column?: string;
    at?: unknown;
    previous?: unknown;
    previous_at?: unknown;
    note?: string;
  };
}

/** A link from this object. A to-one link resolves to the linked object's key, a to-many link to
 *  a count; one the compiler refuses carries `why_not` and is never traversed. */
export interface ObjectLink {
  name: string;
  /** ON-3b — the link's business-verb name, accepted beside `name`; "" when its verb names nothing. */
  business_name?: string;
  verb?: string;
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
  /** PENDING item 13 — absent: the SQL names THIS object. "segment": a finding about the object's
   *  own label value (its country, tier…), named in `segment`. "type": about its type in general. */
  scope?: "segment" | "type";
  segment?: string;
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
  /** ON-4 — the overlay edit behind this note, so it can be withdrawn one edit at a time. */
  id: string;
}

export interface ObjectActionParam {
  name: string;
  display_name: string;
  data_type: string;
  required: boolean;
  description: string;
  value: unknown;
  /** ON-4 — `object` names one object of `object_type`, passed as "<type>:<key>". */
  kind?: "value" | "object";
  object_type?: string;
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
  /** How many findings could not be read — each is skipped and counted, never the end of the list (PENDING item 25). */
  findings_unread?: number;
  notes: ObjectNote[];
  actions: ObjectAction[];
}

/** ON-3b — which property titles this object, and on what warrant: a person's declaration (`human`), a proposal
 *  from the profile (`proposed`), or the key when nothing else names it (a refuted proposal is named in
 *  `refuted`). `value` is the title shown; null when the key names the object. */
export interface ObjectDisplay {
  property: string;
  source: "proposed" | "human" | "key";
  is_key: boolean;
  verified: boolean | null;
  rows: number | null;
  non_null: number | null;
  distinct: number | null;
  note: string;
  refuted?: string;
  value: string | null;
}

/** ON-5 — one timeseries binding's readings for this object, newest first: the value on top of the page is the
 *  first of these. `latest_at` is when that reading was measured; `error` replaces the rows when the history
 *  could not be read. */
export interface ObjectTimeseries {
  binding: string;
  source: string;
  key: string;
  time_column: string;
  note: string;
  limit: number;
  columns: string[];
  rows: unknown[][];
  latest_at?: unknown;
  error?: string;
}

export interface ObjectPage {
  path: "object";
  connection_id: string;
  schema_name: string;
  /** ON-8 — `org/domain` when the object is of an organisation's ontology; `connection_id` is where its rows live. */
  domain?: string;
  object_type: string;
  type_id: string;
  type_name: string;
  key: string;
  pk: string;
  title: string | null;
  display?: ObjectDisplay;
  properties: ObjectProperty[];
  links: ObjectLink[];
  caveats: string[];
  timeseries?: ObjectTimeseries[];
  related: ObjectRelated;
}

/** The compiler's refusal — it says why and names what exists. */
export interface ObjectRefusal {
  path: "refused";
  refused: string;
  available: string[];
  connection_id?: string;
  schema_name?: string;
  domain?: string;
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
  domain?: string;
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
  /** ON-4 — properties accepted edits set on this type's objects. */
  overlay_properties?: string[];
  /** A part stays a type by name and is listed under its parent: the parent's object_type while the mark holds. */
  part_of?: string | null;
  /** The types that are parts of this one, each with the binding it is read through. */
  parts?: { object_type: string; binding: string }[];
}

export interface ObjectCatalog {
  connection_id: string;
  schema_name: string;
  object_types: ObjectCatalogType[];
}

/** An omitted connection is the server's default, never an empty `connection_id=`. ON-8 — an organisation's ontology
 *  travels as `domain:<name>` where a connection goes, and is sent `?domain=` beside it. */
function scope(connectionId?: string, schemaName?: string, extra: Record<string, string> = {}): string {
  const q = new URLSearchParams(extra);
  if (connectionId) q.set("connection_id", connectionId);
  const domain = connectionId ? scopeDomain(connectionId) : null;
  if (domain) q.set("domain", domain);
  else if (schemaName) q.set("schema_name", schemaName);
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


/** ON-4 — withdraw ONE overlay edit: the annotation on a row, or the property an accepted action set on
 *  an object. The next read stops merging it and the object reads as the warehouse holds it — nothing is
 *  restored, because the source was never written. A 404 means it is already gone. */
export async function withdrawEdit(editId: string, connectionId?: string): Promise<void> {
  const q = new URLSearchParams();
  if (connectionId) q.set("connection_id", connectionId);
  const res = await fetch(
    `${getApiBase()}/kinetic-actions/annotations/${encodeURIComponent(editId)}${q.toString() ? `?${q}` : ""}`,
    { method: "DELETE" });
  if (!res.ok) throw new Error(await detailOf(res));
}


/** Arc OC-6 — one version of an edit on an object: who set what (and what it replaced), or who withdrew it. */
export interface EditHistoryRow {
  event: "set" | "withdrawn";
  version: number;
  column: string;
  body: string;
  previous: string;
  note: string;
  actor: string;
  origin: string;
  at: string;
}

/** Arc OC-6 — every version of the edits on one object (and one property), newest first. */
export async function getEditHistory(
  connectionId: string, objectType: string, rowKey: string, column = "",
): Promise<EditHistoryRow[]> {
  const q = new URLSearchParams({ connection_id: connectionId, object_type: objectType, row_key: rowKey });
  if (column) q.set("column", column);
  const res = await fetch(`${getApiBase()}/kinetic-actions/edits/history?${q}`);
  if (!res.ok) throw new Error(await detailOf(res));
  return (await res.json()).history;
}

/** ON-3b — what a set of keys is NAMED: one query over the backing per type. `titles` omits a key nothing
 *  matched, and a type named by its own key resolves nothing and says so in `note`. */
export interface ObjectTitles {
  path: "titles";
  connection_id: string;
  schema_name: string;
  domain?: string;
  object_type: string;
  type_id: string;
  key: string;
  property: string;
  titles: Record<string, string>;
  truncated: boolean;
  note?: string;
}

/** Resolve the names of many objects at once. Refusals and failures are the caller's to ignore: a table whose
 *  titles do not arrive shows the keys it always showed. */
export async function getObjectTitles(
  objectType: string, keys: string[], connectionId?: string, schemaName?: string,
): Promise<ObjectTitles | ObjectRefusal> {
  const res = await fetch(`${getApiBase()}/objects/titles${scope(connectionId, schemaName)}`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ object_type: objectType, keys }),
  });
  if (!res.ok) throw new Error(await detailOf(res));
  return res.json();
}


// ── Arc OC-4 — a page of objects, and running a declared action from a cockpit ─────────────────

/** One page of an entity's objects, or of a segment of it, as `POST /objects/list` returns it. */
export interface ObjectListingPage {
  path: "listed";
  connection_id: string;
  schema_name: string;
  object_type: string;
  type_id: string;
  key: string;
  /** The column that titles each object; empty when the key does. */
  title: string;
  /** One per listed column after the key. `edited` — an accepted edit sets it (or a declared action will). */
  columns: { name: string; path: string; label: string; type: string; edited: boolean }[];
  /** The result's own column names, the key first, in the order of each row's cells. */
  names: string[];
  rows: unknown[][];
  /** The objects the set holds — every page's, not this one's. Null when it could not be counted. */
  total: number | null;
  offset: number;
  limit: number;
  /** The segment read, in words. */
  segment_said: string;
  plan: string[];
  caveats: string[];
  error: string | null;
}

export interface ObjectListingRequest {
  /** The entity listed, by its id or api name. */
  entity: string;
  segment?: string;
  /** Conditions in the object door's shape — the process designer lists the objects a check is about by them. */
  filters?: Record<string, unknown>[];
  columns?: string[];
  order_by?: string;
  descending?: boolean;
  offset?: number;
  limit?: number;
}

export async function listObjects(
  body: ObjectListingRequest, connectionId?: string, schemaName?: string,
): Promise<ObjectListingPage | ObjectRefusal> {
  const res = await fetch(`${getApiBase()}/objects/list${scope(connectionId, schemaName)}`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await detailOf(res));
  return res.json();
}

/** A declared action, as the ontology's actions door returns it (`getDeclaredActions` in `lib/api.ts`). */
export type { DeclaredAction } from "@/lib/api";
export { getDeclaredActions } from "@/lib/api";

/** What a run's declared check found: ``passed`` · ``failed`` · ``unavailable`` (the check could not be read — not a
 *  failed change) · ``not_declared``, with why. */
export interface ActionCheck { status: string; why?: string }

/** What became of pressing an action's button: it ran, with what its check found; it waits for a person in the
 *  Actions inbox; or it was refused, in the action's own words. */
export type ActionOutcome =
  | { status: "ran"; outcome: Record<string, unknown>; verification?: ActionCheck }
  | { status: "proposed"; inbox_id: string }
  | { status: "refused"; message: string };

/** Run a declared action; when running it needs approval, the door stages it for a person to accept instead. */
export async function runOrPropose(
  actionId: string, params: Record<string, unknown>, connectionId: string, schemaName?: string, reasoning = "",
  expected?: Record<string, number>,
): Promise<ActionOutcome> {
  const res = await fetch(`${getApiBase()}/kinetic-actions/${encodeURIComponent(actionId)}/execute${scope(connectionId, schemaName)}`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    // Arc OC-6 — the version of each property the action sets, as this page read it: a run against a version
    // someone changed since is refused (409) and writes nothing
    body: JSON.stringify({ params, propose_if_gated: true, reasoning, ...(expected ? { expected } : {}) }),
  });
  if (!res.ok) return { status: "refused", message: await refusalOf(res) };
  const body = (await res.json()) as {
    status?: string; inbox_id?: string; outcome?: Record<string, unknown>; verification?: ActionCheck;
  };
  return body.status === "proposed" ? { status: "proposed", inbox_id: String(body.inbox_id ?? "") }
    : { status: "ran", outcome: body.outcome ?? {}, verification: body.verification };
}

async function refusalOf(res: Response): Promise<string> {
  const body = (await res.json().catch(() => null)) as { detail?: unknown } | null;
  const d = body?.detail;
  if (typeof d === "string") return d;
  if (d && typeof d === "object" && typeof (d as { message?: unknown }).message === "string") return (d as { message: string }).message;
  return `HTTP ${res.status}`;
}


/** Arc OC-6 — one call a declared action made, as the outbox keeps it. */
export interface ActionSend {
  id: string;
  connection_id: string;
  action_id: string;
  action_name: string;
  status: "queued" | "sending" | "delivered" | "unknown" | "dead" | "dismissed";
  attempts: number;
  next_at: string;
  cause: string;
  last_error: string;
  reconciled: string;
  entry: string;
  params: Record<string, unknown>;
  effect: { kind: string; lane: string; target: string };
  created_at: string;
  updated_at: string;
  resolved_by: string;
  note: string;
}

/** Arc OC-6 — the outbox of a connection's declared actions (empty and `enabled: false` while it is off). */
export async function getSends(connectionId: string): Promise<{ enabled: boolean; sends: ActionSend[] }> {
  const res = await fetch(`${getApiBase()}/kinetic-actions/outbox?connection_id=${encodeURIComponent(connectionId)}`);
  if (!res.ok) throw new Error(await detailOf(res));
  return res.json();
}

/** Arc OC-6 — a person sends a call that waits for them again, now. */
export async function retrySend(connectionId: string, sendId: string): Promise<ActionSend> {
  const res = await fetch(`${getApiBase()}/kinetic-actions/outbox/${encodeURIComponent(sendId)}/retry?connection_id=${encodeURIComponent(connectionId)}`,
    { method: "POST" });
  if (!res.ok) throw new Error(await detailOf(res));
  return (await res.json()).send;
}

/** Arc OC-6 — a person leaves a call that waits for them undelivered, with why. */
export async function dismissSend(connectionId: string, sendId: string, note: string): Promise<ActionSend> {
  const res = await fetch(`${getApiBase()}/kinetic-actions/outbox/${encodeURIComponent(sendId)}/dismiss?connection_id=${encodeURIComponent(connectionId)}`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ note }) });
  if (!res.ok) throw new Error(await detailOf(res));
  return (await res.json()).send;
}
