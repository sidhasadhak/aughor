/**
 * The Catalog's right panel, read the way `aughor-v2/CLARITY.md` says a screen reads — every catalog, one catalog (or
 * one schema of it), one table. Pure functions over what the screen already reads: the catalog tree, each
 * connection's datasets (maturity, stage, off, program), its metrics, its ontology and the search index's status.
 * Nothing here fetches or decides what to draw.
 *
 * Two rules it holds:
 *  - **Unknown is said, never zero.** A table with no row count is "not counted", a maturity with no number is "not
 *    given", a read that failed is "not read" — none of them is a 0 that teaches the reader the thing is empty.
 *  - **"Listed twice" says only what is visible.** The API cannot prove two connections read one dataset (each DSN is
 *    masked, each credential encrypted). It can show two connections of one type listing the same tables with the
 *    same row counts — and that is all `findDuplicates` claims, and all the screen says.
 */
import type {
  CatalogEntry, CatalogTree, DatasetSchema, DatasetTable, DatasetsView, KnowledgeStatus, Metric, OntologyEntity,
  OntologyGraph, OntologyRelationship,
} from "@/lib/api";
import { columnTypeKind } from "@/lib/format";
import { bare } from "@/lib/tableName";

// ── Words ────────────────────────────────────────────────────────────────────────────────────────────────────────

/** A business object's name as a reader writes it — "Inventory item", "Order line", "SKU code": the ontology's
 *  display name when it has one, else its id split ("InventoryItem" → "Inventory item"). A capitalised word after
 *  the first is lowered; an acronym keeps its capitals. */
export function objectWords(id: string, displayName?: string | null): string {
  const raw = (displayName ?? "").trim() || id
    .replace(/[_-]+/g, " ")
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/([A-Z]+)([A-Z][a-z])/g, "$1 $2");
  return raw.split(/\s+/).filter(Boolean)
    .map((w, i) => (i === 0 ? w.charAt(0).toUpperCase() + w.slice(1) : /^[A-Z][a-z]+$/.test(w) ? w.toLowerCase() : w))
    .join(" ");
}

/** "52 of 52 questions asked" → { n: 52, of: 52 }. With `noun`, only a count of that noun ("metrics dated"). A note
 *  carrying no count is null — never a 0. */
export function ofCount(note: string | null | undefined, noun?: string): { n: number; of: number } | null {
  const re = noun ? new RegExp(`(\\d[\\d,]*) of (\\d[\\d,]*) ${noun}`) : /(\d[\d,]*) of (\d[\d,]*)/;
  const m = (note ?? "").match(re);
  if (!m) return null;
  const n = Number(m[1].replace(/,/g, "")), of = Number(m[2].replace(/,/g, ""));
  return Number.isFinite(n) && Number.isFinite(of) ? { n, of } : null;
}

const GRAIN_WORD: Record<string, string> = {
  day: "daily", week: "weekly", month: "monthly", quarter: "quarterly", year: "yearly",
};

/** How often a set of schemas is watched, from the date grains their program reads: "watched daily". */
export function watchedWord(schemas: DatasetSchema[]): string {
  const read = new Set(schemas.flatMap(s => Object.keys(s.program?.watch ?? {})));
  const grains = Object.keys(GRAIN_WORD).filter(g => read.has(g));
  return grains.length ? `watched ${grains.map(g => GRAIN_WORD[g]).join(" and ")}` : "watched";
}

export type StateTone = "up" | "accent" | "muted" | "amber";
/** A state said in a word or two, its mark and its colour: ✓ watched daily (green), ● exploring (accent). */
export interface StateWord { word: string; tone: StateTone; mark: "✓" | "●" | "" }

const NOT_READ: StateWord = { word: "not read", tone: "muted", mark: "" };

/** One table's state, from its dataset's reading. A table the datasets read does not list is "not read". */
export function tableState(t: DatasetTable | undefined, schema: DatasetSchema | undefined): StateWord {
  if (!t || !schema) return NOT_READ;
  if (schema.off || t.off) return { word: "off", tone: "muted", mark: "" };
  if (t.maturity.stage === "watching") return { word: watchedWord([schema]), tone: "up", mark: "✓" };
  if (t.maturity.stage === "exploring") return { word: "exploring", tone: "accent", mark: "●" };
  return { word: t.maturity.structure.share === 1 ? "learned" : "learning", tone: "muted", mark: "●" };
}

/** A catalog's or a schema's state, folded over its schemas: watched only when every one that is on is watched. */
export function scopeState(schemas: DatasetSchema[]): StateWord {
  if (!schemas.length) return { word: "nothing to read", tone: "muted", mark: "" };
  const on = schemas.filter(s => !s.off);
  if (!on.length) return { word: "turned off", tone: "muted", mark: "" };
  if (on.every(s => s.maturity.stage === "watching")) return { word: watchedWord(on), tone: "up", mark: "✓" };
  if (on.some(s => s.maturity.stage !== "learning")) return { word: "exploring", tone: "accent", mark: "●" };
  return { word: on.every(s => s.maturity.structure.share === 1) ? "learned" : "learning", tone: "muted", mark: "●" };
}

/** How far the platform has explored a set of schemas: their numbers, weighted by their tables. A schema whose number
 *  is not given is left out and counted in `given`/`of`; with none given the share is null — "not given", never 0%. */
export function explored(schemas: DatasetSchema[]): { percent: number | null; given: number; of: number } {
  const on = schemas.filter(s => !s.off);
  const given = on.filter(s => s.maturity.percent != null);
  const weight = (s: DatasetSchema) => Math.max(1, s.tables.length);
  const total = given.reduce((a, s) => a + weight(s), 0);
  const percent = given.length
    ? Math.round(given.reduce((a, s) => a + (s.maturity.percent as number) * weight(s), 0) / total)
    : null;
  return { percent, given: given.length, of: on.length };
}

// ── Listed twice ─────────────────────────────────────────────────────────────────────────────────────────────────

/** Two connections listing the same tables with the same row counts — all that can be seen, so all that is said. */
export interface Duplicate {
  /** The connection whose listing repeats another's: the one explored less (or, with neither read, listed later). */
  copy: { id: string; name: string; schemas: string[] };
  of: { id: string; name: string; schemas: string[] };
  tables: number;
  rows: number;
}

/** A schema's tables and row counts as one string, or null when they cannot be compared: no table, a table with no
 *  count (two unknowns are not "the same"), or nothing in them (two empty listings prove nothing). */
function listing(tables: { name: string; row_count: number | null }[]): string | null {
  if (!tables.length || tables.some(t => t.row_count == null)) return null;
  if (!(tables.reduce((a, t) => a + Number(t.row_count), 0) > 0)) return null;
  return tables.map(t => `${bare(t.name)}=${Number(t.row_count)}`).sort().join("|");
}

/**
 * Schemas of two different connections of one type that list the same table names with the same row counts. The copy
 * is the connection explored less, so the one the platform has learned stays the one counted; `percent` is each
 * connection's explored number (null or absent — not read yet), and with neither read the tree's order decides.
 * Two schemas of ONE connection are never "listed twice".
 */
export function findDuplicates(
  entries: CatalogEntry[], percent: (connId: string) => number | null | undefined = () => null,
): Duplicate[] {
  const order = entries.map((e, i) => ({ e, i, p: percent(e.conn_id) ?? -1 })).sort((a, b) => b.p - a.p || a.i - b.i);
  const first = new Map<string, { e: CatalogEntry; schema: string }>();
  const pairs = new Map<string, Duplicate>();
  for (const { e } of order) {
    for (const s of e.schemas) {
      const sig = listing(s.tables);
      if (!sig) continue;
      const key = `${e.conn_type}\u0000${sig}`;
      const had = first.get(key);
      if (!had) { first.set(key, { e, schema: s.name }); continue; }
      if (had.e.conn_id === e.conn_id) continue;
      const pair = `${e.conn_id}\u0000${had.e.conn_id}`;
      const d = pairs.get(pair) ?? {
        copy: { id: e.conn_id, name: e.name, schemas: [] }, of: { id: had.e.conn_id, name: had.e.name, schemas: [] },
        tables: 0, rows: 0,
      };
      d.copy.schemas.push(s.name);
      d.of.schemas.push(had.schema);
      d.tables += s.tables.length;
      d.rows += s.tables.reduce((a, t) => a + Number(t.row_count), 0);
      pairs.set(pair, d);
    }
  }
  return [...pairs.values()];
}

const pairKey = (connId: string, schema: string) => `${connId}\u0000${schema}`;

/** The schemas that repeat another connection's listing, to count their tables once. */
export function copiedSchemas(dups: Duplicate[]): Set<string> {
  return new Set(dups.flatMap(d => d.copy.schemas.map(s => pairKey(d.copy.id, s))));
}

/** "BigQuery lists the same 7 tables as theLook, with the same row counts" — what is visible, and nothing more. */
export function duplicateWords(d: Duplicate): string {
  return `${d.copy.name} lists the same ${d.tables === 1 ? "table" : `${d.tables} tables`} as ${d.of.name}, `
    + `with the same row count${d.tables === 1 ? "" : "s"}`;
}

// ── Every catalog ────────────────────────────────────────────────────────────────────────────────────────────────

/** A catalog's datasets: read (a view), still being read (undefined) or failed (null). */
export type Views = Record<string, DatasetsView | null | undefined>;

export interface HomeFigures {
  catalogs: string[];
  /** Tables, each once. */
  tables: number;
  /** Tables a second connection lists again — counted once above. */
  twice: number;
  /** Counted rows, each table once; null when no table carries a count. */
  rows: number | null;
  counted: number;
  uncounted: number;
  off: { schemas: number; tables: number; read: number; failed: number; of: number };
}

export function homeFigures(entries: CatalogEntry[], dups: Duplicate[], views: Views): HomeFigures {
  const copies = copiedSchemas(dups);
  let tables = 0, twice = 0, rows = 0, counted = 0, uncounted = 0;
  for (const e of entries) {
    for (const s of e.schemas) {
      if (copies.has(pairKey(e.conn_id, s.name))) { twice += s.tables.length; continue; }
      for (const t of s.tables) {
        tables++;
        if (t.row_count == null) uncounted++;
        else { counted++; rows += Number(t.row_count); }
      }
    }
  }
  const off = { schemas: 0, tables: 0, read: 0, failed: 0, of: entries.length };
  for (const e of entries) {
    const v = views[e.conn_id];
    if (v === null) { off.failed++; continue; }
    if (!v) continue;
    off.read++;
    for (const s of v.schemas) {
      if (s.off) off.schemas++;
      else off.tables += s.tables.filter(t => t.off).length;
    }
  }
  return { catalogs: entries.map(e => e.name), tables, twice, rows: counted ? rows : null, counted, uncounted, off };
}

export interface CatalogRow {
  id: string;
  name: string;
  /** What it is, in a few words: "BigQuery · thelook", "uploaded files · 2 schemas". */
  what: string;
  tables: number;
  /** Counted rows; null when no table of it carries a count. */
  rows: number | null;
  uncounted: number;
  explored: { percent: number | null; given: number; of: number } | "reading" | "failed";
  state: StateWord;
  copyOf: { id: string; name: string } | null;
}

/** What a catalog is, in a few words — never its connection string. */
export function whatItIs(entry: CatalogEntry, label: (connType: string) => string, copyOf?: string | null): string {
  if (copyOf) return `the same tables as ${copyOf}`;
  if (entry.conn_type === "aughor_ops") return "the platform itself";
  const n = entry.schemas.length;
  const where = n === 1 ? entry.schemas[0].name : n ? `${n} schemas` : "";
  const kind = entry.conn_type === "local_upload" ? "uploaded files" : label(entry.conn_type);
  return where ? `${kind} · ${where}` : kind;
}

export function catalogRows(
  entries: CatalogEntry[], dups: Duplicate[], views: Views, label: (connType: string) => string,
): CatalogRow[] {
  return entries.map(e => {
    const dup = dups.find(d => d.copy.id === e.conn_id);
    const v = views[e.conn_id];
    const tables = e.schemas.flatMap(s => s.tables);
    const counted = tables.filter(t => t.row_count != null);
    const state: StateWord = dup ? { word: "listed twice", tone: "amber", mark: "" }
      : v === undefined ? { word: "reading…", tone: "muted", mark: "" }
      : v === null ? NOT_READ
      : scopeState(v.schemas);
    return {
      id: e.conn_id, name: e.name, what: whatItIs(e, label, dup?.of.name), tables: tables.length,
      rows: counted.length ? counted.reduce((a, t) => a + Number(t.row_count), 0) : null,
      uncounted: tables.length - counted.length,
      explored: v === undefined ? "reading" : v === null ? "failed" : explored(v.schemas),
      state, copyOf: dup ? { id: dup.of.id, name: dup.of.name } : null,
    };
  });
}

export interface TableRef { connId: string; catalog: string; schema: string; name: string; rows: number }

/** The largest counted tables across every catalog, each once (a listing repeated by a second connection is left
 *  out), largest first. */
export function largestTables(entries: CatalogEntry[], dups: Duplicate[], n = 8): TableRef[] {
  const copies = copiedSchemas(dups);
  return entries.flatMap(e => e.schemas
    .filter(s => !copies.has(pairKey(e.conn_id, s.name)))
    .flatMap(s => s.tables.filter(t => t.row_count != null)
      .map(t => ({ connId: e.conn_id, catalog: e.name, schema: s.name, name: t.name, rows: Number(t.row_count) }))))
    .sort((a, b) => b.rows - a.rows)
    .slice(0, n);
}

// ── Documents the search cannot reach ────────────────────────────────────────────────────────────────────────────

export interface Unsearchable {
  /** The connection a schema document was compiled for; null for a person's upload. */
  connId: string | null;
  /** The schema it documents, for a compiled schema document. */
  schemas: string[];
  documents: number;
  /** Parts the registry lists that the search index does not hold. */
  missing: number;
  claimed: number;
}

/** Documents registered with more parts than the search index holds — the parts that cannot be searched — grouped by
 *  the connection a compiled schema document belongs to (`doctree::<connection>::<schema>`). A document the index
 *  holds MORE of is not unsearchable and is left out. */
export function unsearchable(status: KnowledgeStatus | null | undefined): Unsearchable[] {
  const groups = new Map<string, Unsearchable>();
  for (const [docId, n] of Object.entries(status?.consistency?.mismatched_documents ?? {})) {
    if (!(n.store < n.registry)) continue;
    const parts = docId.startsWith("doctree::") ? docId.split("::") : null;
    const connId = parts && parts[1] ? parts[1] : null;
    const key = connId ?? "\u0000uploads";
    const g = groups.get(key) ?? { connId, schemas: [], documents: 0, missing: 0, claimed: 0 };
    g.documents++;
    g.missing += n.registry - n.store;
    g.claimed += n.registry;
    if (parts && parts[2]) g.schemas.push(parts[2]);
    groups.set(key, g);
  }
  return [...groups.values()];
}

// ── One catalog, or one schema of it ─────────────────────────────────────────────────────────────────────────────

/** The approved metrics of a connection — of one schema when `schema` is given (its own, and those of every schema). */
export function approvedMetrics(metrics: Metric[], schema?: string): Metric[] {
  return metrics.filter(m => m.status === "approved" && (!schema || !m.home_schema || m.home_schema === "*"
    || m.home_schema.toLowerCase() === schema.toLowerCase()));
}

/** How many of `metrics` read a table, by the tables each declares it reads. */
export function metricsReading(metrics: Metric[], table: string): number {
  const t = bare(table);
  return metrics.filter(m => (m.tables ?? []).some(x => bare(x) === t)).length;
}

/** Each table's business object, from the ontology's entities and the tables they are read from — keyed by schema
 *  and table, so two schemas' `orders` stay apart. */
export function objectsByTable(graphs: OntologyGraph[]): Map<string, OntologyEntity> {
  const out = new Map<string, OntologyEntity>();
  for (const g of graphs) {
    for (const e of Object.values(g.entities ?? {})) {
      for (const t of e.source_tables ?? []) {
        const k = pairKey((g.schema_name ?? "").toLowerCase(), bare(t));
        if (!out.has(k)) out.set(k, e);
      }
    }
  }
  return out;
}

/** The business object read from `schema.table` — by its schema, or by its name alone when one graph was read. */
export function objectFor(
  objects: Map<string, OntologyEntity>, graphs: OntologyGraph[], schema: string, table: string,
): OntologyEntity | null {
  const hit = objects.get(pairKey(schema.toLowerCase(), bare(table)));
  if (hit) return hit;
  if (graphs.length !== 1) return null;
  const only = (graphs[0].schema_name ?? "").toLowerCase();
  return objects.get(pairKey(only, bare(table))) ?? null;
}

export interface ScopeTable {
  key: string;
  schema: string;
  name: string;
  rows: number | null;
  object: { id: string; words: string } | null;
  /** Questions asked of it alone, of the questions it has; null when its reading carries no count. */
  questions: { n: number; of: number } | null;
  questionsNote: string;
  /** Approved metrics that read it; null when the metrics were not read. */
  metrics: number | null;
  state: StateWord;
  maturity: DatasetTable["maturity"] | null;
}

export interface Know {
  key: "structure" | "questions" | "metrics" | "objects";
  label: string;
  meta: string;
  /** n of `of`; both null when it was not read or does not apply — `note` says which, `short` in a word or two. */
  n: number | null;
  of: number | null;
  /** How full its bar is: n of `of`, or the reading's own share when its note carries no count; null — unknown. */
  share: number | null;
  note: string;
  /** What stands where "n of m" would: "40%", "none", "not built", "not given". Empty when n of m is shown. */
  short: string;
}

export interface ScopeSummary {
  tables: ScopeTable[];
  rows: number | null;
  counted: number;
  uncounted: number;
  /** "5 watched daily · 2 learned". */
  stages: string;
  state: StateWord;
  explored: { percent: number | null; given: number; of: number } | null;
  /** Approved metrics in scope; null when the metrics were not read. */
  metrics: number | null;
  lastRun: { at: string; newFindings: number; outcome: string; failures: number } | null;
  newest: { through: string; readAt: string; grain: string } | null;
  knows: Know[];
  /** Schemas whose questions wait for a person to set their layer. */
  waiting: string[];
  held: string | null;
  budgetSpent: string | null;
}

export interface ScopeInput {
  entry: CatalogEntry;
  /** One schema of it; every schema when absent. */
  schema?: string;
  /** Its datasets: read, being read (undefined) or failed (null). */
  view: DatasetsView | null | undefined;
  metrics: Metric[] | null | undefined;
  ontology: OntologyGraph[] | null | undefined;
}

const STAGE_ORDER: StateTone[] = ["up", "accent", "muted", "amber"];

/** Everything one catalog's — or one schema's — page says, folded once. */
export function scopeSummary({ entry, schema, view, metrics, ontology }: ScopeInput): ScopeSummary {
  const treeSchemas = entry.schemas.filter(s => !schema || s.name === schema);
  const dsSchemas = (view?.schemas ?? []).filter(s => !schema || s.name === schema);
  const dsOf = (name: string) => dsSchemas.find(s => s.name === name);
  const objects = ontology ? objectsByTable(ontology) : null;
  const inScope = metrics ? approvedMetrics(metrics, schema) : null;

  const tables: ScopeTable[] = treeSchemas.flatMap(s => s.tables.map(t => {
    const ds = dsOf(s.name);
    const dt = ds?.tables.find(x => x.name === t.name);
    const ent = objects && ontology ? objectFor(objects, ontology, s.name, t.name) : null;
    const q = dt?.maturity.questions;
    return {
      key: pairKey(s.name, t.name), schema: s.name, name: t.name,
      rows: t.row_count == null ? null : Number(t.row_count),
      object: ent ? { id: ent.id, words: objectWords(ent.id, ent.display_name) } : null,
      questions: ofCount(q?.note, "questions"), questionsNote: q?.note ?? "",
      metrics: inScope ? metricsReading(inScope, t.name) : null,
      state: view === undefined ? { word: "reading…", tone: "muted" as const, mark: "" as const }
        : tableState(dt, ds),
      maturity: dt?.maturity ?? null,
    };
  })).sort((a, b) => (b.rows ?? -1) - (a.rows ?? -1));

  const counted = tables.filter(t => t.rows != null);
  const stageCount = new Map<string, { n: number; tone: StateTone }>();
  for (const t of tables) {
    if (t.state === NOT_READ || t.state.word === "reading…") continue;
    const c = stageCount.get(t.state.word) ?? { n: 0, tone: t.state.tone };
    c.n++;
    stageCount.set(t.state.word, c);
  }
  const stages = [...stageCount.entries()]
    .sort((a, b) => STAGE_ORDER.indexOf(a[1].tone) - STAGE_ORDER.indexOf(b[1].tone))
    .map(([word, c]) => `${c.n} ${word}`).join(" · ");

  const on = dsSchemas.filter(s => !s.off);
  const runs = on.map(s => s.program?.last_run ? { s, r: s.program.last_run } : null)
    .filter((x): x is { s: DatasetSchema; r: NonNullable<DatasetSchema["program"]["last_run"]> } => !!x && !!x.r.ended_at)
    .sort((a, b) => b.r.ended_at.localeCompare(a.r.ended_at));
  const last = runs[0];

  let newest: ScopeSummary["newest"] = null;
  for (const s of on) {
    for (const [grain, w] of Object.entries(s.program?.watch ?? {})) {
      if (!w?.through) continue;
      if (!newest || w.through > newest.through) newest = { through: w.through, readAt: w.read_at, grain };
    }
  }

  return {
    tables, rows: counted.length ? counted.reduce((a, t) => a + (t.rows as number), 0) : null,
    counted: counted.length, uncounted: tables.length - counted.length, stages,
    state: view ? scopeState(dsSchemas) : view === null ? NOT_READ : { word: "reading…", tone: "muted", mark: "" },
    explored: view ? explored(dsSchemas) : null,
    metrics: inScope ? inScope.length : null,
    lastRun: last ? {
      at: last.r.ended_at, newFindings: last.r.new_findings ?? 0, outcome: last.r.outcome,
      failures: last.s.program.failures ?? 0,
    } : null,
    newest,
    knows: knows(tables, on, view, ontology),
    waiting: on.filter(s => !s.layer?.set && s.layer?.proposed?.layer).map(s => s.name),
    held: on.map(s => s.program?.held?.why).find(Boolean) ?? null,
    budgetSpent: view?.budget?.spent_out ? view.budget.sentence : null,
  };
}

/** A reading's note in a word or two, where its bar's figure would be. */
function shortNote(note: string): string {
  if (note === "reading…" || note === "not read") return note;
  if (note === "the ontology is not built") return "not built";
  if (/^no approved metric/.test(note)) return "no metric";
  return "not given";
}

type Bar = "questions" | "time";

function knows(
  tables: ScopeTable[], on: DatasetSchema[], view: DatasetsView | null | undefined, ontology: OntologyGraph[] | null | undefined,
): Know[] {
  const unread = view === undefined ? "reading…" : "not read";
  const sum = (parts: ({ n: number; of: number } | null)[]) => {
    const got = parts.filter((p): p is { n: number; of: number } => !!p);
    return got.length ? { n: got.reduce((a, p) => a + p.n, 0), of: got.reduce((a, p) => a + p.of, 0) } : null;
  };
  /** The schemas' own share of a reading, when every schema that is on gives one and none gives a count. */
  const own = (bar: Bar) => (on.length && on.every(s => s.maturity[bar].share != null)
    ? on.reduce((a, s) => a + (s.maturity[bar].share as number), 0) / on.length : null);
  const dated = (note: string) => {
    const got = ofCount(note, "metrics dated");
    if (got) return got;
    const none = note.match(/none of its (\d+) approved metrics/);
    return none ? { n: 0, of: Number(none[1]) } : null;
  };

  const readTables = tables.filter(t => t.maturity);
  const counted = (k: Know["key"], label: string, meta: string, got: { n: number; of: number } | null, note: string,
    fallback: number | null = null): Know => {
    const share = got ? (got.of ? got.n / got.of : null) : fallback;
    return {
      key: k, label, meta, n: got?.n ?? null, of: got?.of ?? null, share, note,
      short: got ? (got.of ? "" : "none") : share != null ? `${Math.round(share * 100)}%` : shortNote(note),
    };
  };
  const q = view ? sum(on.map(s => ofCount(s.maturity.questions.note, "questions"))) : null;
  const m = view ? sum(on.map(s => dated(s.maturity.time.note))) : null;
  return [
    counted("structure", "Structure", "tables, keys, joins",
      view ? { n: readTables.filter(t => t.maturity!.structure.share === 1).length, of: readTables.length } : null,
      view ? "" : unread),
    counted("questions", "Questions", "asked of each table", q,
      !view ? unread : q ? "" : (on[0]?.maturity.questions.note ?? "not given"), view && !q ? own("questions") : null),
    counted("metrics", "Metrics dated", "newest day read", m,
      !view ? unread : m ? "" : (on[0]?.maturity.time.note ?? "no approved metric"), view && !m ? own("time") : null),
    counted("objects", "Business objects", "mapped from tables",
      ontology ? { n: tables.filter(t => t.object).length, of: tables.length } : null,
      ontology ? "" : ontology === undefined ? "reading…" : "the ontology is not built"),
  ];
}

// ── One table ────────────────────────────────────────────────────────────────────────────────────────────────────

export interface ColumnRow {
  name: string;
  type: string;
  /** What it means, from the ontology's property description (else the schema's comment). */
  means: string;
  key: boolean;
  /** The table it links to. */
  link: string | null;
  /** How many lifecycle states it holds, when it is the business object's status column. */
  states: number | null;
  time: boolean;
}

/** A table's columns with what each means and its marks — ✓ key, → linked table, N states, time. */
export function columnRows(
  columns: { name: string; type: string; description?: string }[],
  entity: OntologyEntity | null,
  relationships: OntologyRelationship[],
  table: string,
): ColumnRow[] {
  const props = new Map(Object.values(entity?.properties ?? {}).map(p => [p.name.toLowerCase(), p]));
  const t = bare(table);
  return columns.map(c => {
    const p = props.get(c.name.toLowerCase());
    const link = relationships.find(r => bare(r.from_table) === t && r.from_col.toLowerCase() === c.name.toLowerCase());
    const kind = columnTypeKind(c.type || p?.data_type);
    const isStatus = !!entity?.lifecycle_column && entity.lifecycle_column.toLowerCase() === c.name.toLowerCase();
    return {
      name: c.name, type: c.type || p?.data_type || "", means: p?.description || c.description || "",
      key: !!p?.is_primary_key || (!!entity?.identity_key && entity.identity_key.toLowerCase() === c.name.toLowerCase()),
      link: link ? bare(link.to_table) : null,
      states: isStatus ? (entity!.lifecycle_states ?? []).length : null,
      time: p?.semantic_type === "timestamp" || kind === "time" || kind === "date",
    };
  });
}

/** "1 key · 1 link · 4 times" — the marks a table's columns carry, counted. */
export function columnMarks(rows: ColumnRow[]): string {
  const keys = rows.filter(r => r.key).length;
  const links = rows.filter(r => r.link).length;
  const times = rows.filter(r => r.time).length;
  const parts = [
    keys ? `${keys} key${keys === 1 ? "" : "s"}` : "",
    links ? `${links} link${links === 1 ? "" : "s"}` : "",
    times ? `${times} time${times === 1 ? "" : "s"}` : "",
  ].filter(Boolean);
  return parts.length ? parts.join(" · ") : "no key, link or time read";
}

export interface Lifecycle { column: string; states: { name: string; ends: boolean }[]; ends: number }

/** A business object's lifecycle — its status column's states, each one that ends it marked. No counts: the ontology
 *  holds the states, not how many objects sit in each. */
export function lifecycleOf(entity: OntologyEntity | null): Lifecycle | null {
  if (!entity?.lifecycle_column || !(entity.lifecycle_states ?? []).length) return null;
  const ending = new Set((entity.terminal_states ?? []).map(s => s.toLowerCase()));
  const states = entity.lifecycle_states.map(name => ({ name, ends: ending.has(name.toLowerCase()) }));
  return { column: entity.lifecycle_column, states, ends: states.filter(s => s.ends).length };
}

/** One finding as the explorer's read carries it — typed here by what this screen reads of it. */
export interface TableFinding {
  id: string;
  finding: string;
  question?: string;
  domain?: string;
  angle?: string;
  entities_involved?: string[];
  signature?: { tables?: string[] };
  generated_at?: string;
}

/** The findings list from the explorer's read (`GET /exploration/{id}/findings`, its current key `findings`); null
 *  when the read carries no list — "not read", never "none". */
export function findingsIn(read: unknown): TableFinding[] | null {
  const list = (read as { findings?: unknown } | null | undefined)?.findings;
  return Array.isArray(list) ? (list as TableFinding[]) : null;
}

/** The findings about one table: those whose query read it, or — for a finding that does not say what it read —
 *  those about its business object. */
export function findingsAbout(list: TableFinding[], table: string, objectId: string | null): TableFinding[] {
  const t = bare(table);
  return list.filter(f => f.signature?.tables
    ? f.signature.tables.some(x => bare(x) === t)
    : !!objectId && (f.entities_involved ?? []).includes(objectId));
}

// ── Favorites and recents ────────────────────────────────────────────────────────────────────────────────────────

export interface CatalogItem {
  /** `conn::` · `conn:schema:` · `conn:schema:table` — the keys favorites and recents are stored under. */
  key: string;
  name: string;
  type: "Catalog" | "Schema" | "Table";
  path: string;
  rows: number | null;
  connId: string;
  schemaName?: string;
  tableName?: string;
}

export const itemKey = {
  catalog: (connId: string) => `${connId}::`,
  schema: (connId: string, schema: string) => `${connId}:${schema}:`,
  table: (connId: string, schema: string, table: string) => `${connId}:${schema}:${table}`,
};

/** Every catalog, schema and table of the tree as one list — what favorites and recents are looked up in. */
export function catalogItems(tree: CatalogTree | null): CatalogItem[] {
  if (!tree) return [];
  return tree.sections.flatMap(sec => sec.entries.flatMap(cat => [
    { key: itemKey.catalog(cat.conn_id), name: cat.name, type: "Catalog" as const, path: sec.label, rows: null, connId: cat.conn_id },
    ...cat.schemas.flatMap(sc => [
      { key: itemKey.schema(cat.conn_id, sc.name), name: sc.name, type: "Schema" as const, path: cat.name, rows: null,
        connId: cat.conn_id, schemaName: sc.name },
      ...sc.tables.map(t => ({
        key: itemKey.table(cat.conn_id, sc.name, t.name), name: t.name, type: "Table" as const, path: `${cat.name}.${sc.name}`,
        rows: t.row_count, connId: cat.conn_id, schemaName: sc.name, tableName: t.name,
      })),
    ]),
  ]));
}
