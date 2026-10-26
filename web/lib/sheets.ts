/**
 * Sheets — the tables people make, edit, combine and chat with (Arc SH; `aughor/routers/sheets.py`).
 *
 * The calls to the sheets' routes, the shapes they answer with, and the pure helpers the Spreadsheets screens share:
 * how a value of each kind is shown, how a typed value is read before it is sent, how a filter is said in words, and
 * whether something said in the chat asks a question or asks for a change.
 *
 * Every write is the server's to check — the kinds, the versions, who may — and a refusal comes back as an Error
 * carrying the server's own sentence, which the screen shows as said.
 */
import { fastApiError } from "@/lib/api";
import { getApiBase } from "@/lib/config";
import { formatCount, formatMoney } from "@/lib/format";
import { currencySymbol } from "@/lib/orgSettings";

export type Kind = "text" | "number" | "money" | "date" | "datetime" | "choice" | "yesno" | "email" | "link";
export type Role = "stored" | "computed" | "lookup" | "total";

export const KIND_LABEL: Record<Kind, string> = {
  text: "Text", number: "Number", money: "Money", date: "Date", datetime: "Date & time", choice: "Choice",
  yesno: "Yes/No", email: "Email", link: "Link",
};

/** The kinds a person may give a new column (a link is made in Combine). */
export const NEW_COLUMN_KINDS: Kind[] = ["text", "number", "money", "date", "datetime", "choice", "yesno", "email"];

export interface SheetColumn {
  id: string;
  name: string;
  kind: Kind;
  integer: boolean;
  description: string;
  role: Role;
  source: string;
  currency: string;
  choices: string[];
  hidden: boolean;
  expression: string;
  link: { sheet: string; column: string; matched: number; missed: number } | null;
  via: string;
  of: string;
  sheet: string;
  key: string;
  by: string;
  how: string;
  made_by: string;
}

export interface Condition { column: string; op: string; value?: unknown }

export interface SheetView {
  id: string;
  name: string;
  filter: Condition[];
  sort: { column: string; desc: boolean }[];
  hidden: string[];
  search: string;
  made_by: string;
}

export interface SheetChange { id: string; what: string; by: string; at: string; origin: string }

export interface SheetSummary {
  id: string;
  name: string;
  table: string;
  rows: number;
  columns: number | SheetColumn[];
  came_from: string;
  source: { kind: "file" | "blank" | "rows"; file: string; tab: string; rows: number; sql: string;
    connection_id: string; schema_name: string; upload: Record<string, string>; imported_at: string };
  last_change: SheetChange;
  created_by: string;
  created_at: string;
  version: number;
  shared_with: string;
}

export interface Sheet extends Omit<SheetSummary, "columns"> {
  columns: SheetColumn[];
  views: SheetView[];
  key: string;
}

export interface UploadedFile { schema: string; file: string; size: number }

export interface ColumnReading {
  name: string;
  suggested: Kind;
  offered: Kind[];
  filled: number;
  empty: number;
  integer: boolean;
  first: string | null;
  values: [string, number][];
  distinct: number;
  misfits: Partial<Record<Kind, number>>;
  note: string;
}

export interface StagedFile {
  token: string;
  file: string;
  size: number;
  tabs: { tab: string; rows: number; columns: ColumnReading[] }[];
  upload?: { schema: string; file: string };
}

export interface ColumnTotals {
  filled?: number; sum?: number | string | null; average?: number | null; min?: unknown; max?: unknown;
  earliest?: string | null; latest?: string | null; yes?: number; distinct?: number;
}

export interface RowsPage {
  rows: unknown[][];
  total: number;
  offset: number;
  totals: Record<string, ColumnTotals>;
  groups: { value: unknown; rows: number }[];
  changed: Record<string, Record<string, { by: string; at: string; version: number }>>;
  columns: string[];
  source_rows: number;
}

export interface CellStory {
  row: number;
  column: string;
  came_from: string;
  version: number;
  changed: boolean;
  events: { event: string; value: unknown; previous: unknown; by: string; at: string; origin: string;
    version: number; change_id: string }[];
}

export interface RecordField {
  column: string; name: string; kind: Kind; role: Role; value: unknown; source: string; description: string;
}

export interface SheetRecord {
  row: number;
  came_from: string;
  fields: RecordField[];
  linked: { sheet: string; name: string; through: string; direction: "to" | "from"; columns: string[];
    rows: { row: number; values: unknown[] }[]; count: number }[];
  history: { event: string; column: string; value: unknown; previous: unknown; by: string; at: string;
    origin: string }[];
  comments: { id: string; text: string; by: string; at: string }[];
}

export interface ChangeRow extends SheetChange { values: number; definition: number }

export interface ProposedChange {
  type: "view" | "computed_column" | "column" | "link" | "total";
  name?: string;
  said: string;
  rows?: number;
  [key: string]: unknown;
}

export interface Proposal {
  id: string;
  state: "staged" | "applied";
  words: string;
  changes: ProposedChange[];
  sheet?: string;
  new_sheet?: boolean;
  name?: string;
  file?: string;
  rows?: number;
  columns?: { name: string; kind: Kind; filled: number; empty: number; note: string }[];
}

export type ProposeOutcome = { staged: true; proposal: Proposal } | { staged: false; sentences: string[] };

export interface Grounding {
  found: boolean;
  name?: string;
  table?: string;
  rows?: number;
  summary: string;
  view?: { name: string; where: string; rows: number };
}

// ── calls ────────────────────────────────────────────────────────────────────────────────────────────────────────────

async function call<T>(path: string, init: RequestInit | undefined, what: string): Promise<T> {
  const res = await fetch(`${getApiBase()}/sheets${path}`, init);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(fastApiError(body, `${what} failed (${res.status})`));
  }
  return res.json() as Promise<T>;
}

const json = (method: string, body: unknown): RequestInit => ({
  method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
});

export const listSheets = () =>
  call<{ sheets: SheetSummary[]; uploads: UploadedFile[]; shared_with: string }>("", undefined, "Reading the sheets");

export const readSheet = (id: string) => call<Sheet>(`/${id}`, undefined, "Reading the sheet");

export function stageFile(file: File): Promise<StagedFile> {
  const form = new FormData();
  form.append("file", file);
  return call<StagedFile>("/files", { method: "POST", body: form }, "Reading the file");
}

export const stageUploaded = (schema: string, file: string) =>
  call<StagedFile>("/files/uploaded", json("POST", { schema_name: schema, file }), "Reading the file");

export interface TabPlan { tab: string; name: string; kinds: Record<string, Kind> }

export const createFromFile = (token: string, tabs: TabPlan[], upload?: { schema: string; file: string }) =>
  call<{ sheets: Sheet[] }>("", json("POST", { source: "file", token, tabs, upload: upload ?? {} }), "Making the sheet");

export const createBlank = (name: string, columns: { name: string; kind: Kind }[]) =>
  call<{ sheets: Sheet[] }>("", json("POST", { source: "blank", name, columns }), "Making the sheet");

export const createFromRows = (name: string, connectionId: string, sql: string, schemaName = "") =>
  call<{ sheets: Sheet[] }>("", json("POST", {
    source: "rows", name, connection_id: connectionId, sql, schema_name: schemaName,
  }), "Keeping the rows as a sheet");

export const removeSheet = (id: string) =>
  call<{ removed: string }>(`/${id}`, { method: "DELETE" }, "Removing the sheet");

export interface RowsQuery {
  view?: string; filter?: Condition[]; sort?: { column: string; desc: boolean }[]; search?: string;
  group?: string; offset?: number; limit?: number;
}

export function rowsQuery(q: RowsQuery): string {
  const p = new URLSearchParams();
  if (q.view) p.set("view", q.view);
  if (q.filter) p.set("filter", JSON.stringify(q.filter));
  if (q.sort) p.set("sort", JSON.stringify(q.sort));
  if (q.search) p.set("search", q.search);
  if (q.group) p.set("group", q.group);
  if (q.offset) p.set("offset", String(q.offset));
  if (q.limit) p.set("limit", String(q.limit));
  const s = p.toString();
  return s ? `?${s}` : "";
}

export const readRows = (id: string, q: RowsQuery) =>
  call<RowsPage>(`/${id}/rows${rowsQuery(q)}`, undefined, "Reading the rows");

export const csvUrl = (id: string, q: RowsQuery) => `${getApiBase()}/sheets/${id}/csv${rowsQuery(q)}`;

export const setCells = (id: string, cells: { row: number; column: string; value: unknown; version?: number }[]) =>
  call<{ change_id: string; cells: { row: number; column: string; value: unknown; version: number }[] }>(
    `/${id}/cells`, json("PATCH", { cells }), "Changing the cell");

export const addRow = (id: string, values: Record<string, unknown> = {}) =>
  call<{ change_id: string; row: number }>(`/${id}/rows`, json("POST", { values }), "Adding the row");

export const removeRows = (id: string, rows: number[]) =>
  call<{ change_id: string }>(`/${id}/rows/remove`, json("POST", { rows }), "Removing the row");

export const addColumn = (id: string, name: string, kind: Kind, description = "") =>
  call<Sheet>(`/${id}/columns`, json("POST", { name, kind, description }), "Adding the column");

export const updateColumn = (id: string, column: string,
  change: { name?: string; description?: string; kind?: Kind; hidden?: boolean }) =>
  call<Sheet>(`/${id}/columns/${encodeURIComponent(column)}`, json("PATCH", change), "Changing the column");

export const removeColumn = (id: string, column: string) =>
  call<Sheet>(`/${id}/columns/${encodeURIComponent(column)}`, { method: "DELETE" }, "Taking the column off");

export const renameSheet = (id: string, name: string) =>
  call<Sheet>(`/${id}`, json("PATCH", { name }), "Renaming the sheet");

export const saveView = (id: string, view: Partial<SheetView>) =>
  call<Sheet>(`/${id}/views`, json("PUT", { view }), "Keeping the view");

export const removeView = (id: string, viewId: string) =>
  call<Sheet>(`/${id}/views/${viewId}`, { method: "DELETE" }, "Taking the view off");

export const readChanges = (id: string) =>
  call<{ changes: ChangeRow[]; can_undo: string; can_redo: string }>(`/${id}/changes`, undefined,
    "Reading the history");

/** Undo the person's latest change. `removing` only for the change that made the sheet — undoing it removes the sheet. */
export const undo = (id: string, removing = false) => call<{ change_id: string; removed: boolean }>(
  `/${id}/undo${removing ? "?removing=true" : ""}`, { method: "POST" }, "Undoing");

export const redo = (id: string) => call<{ change_id: string; removed: boolean }>(`/${id}/redo`, { method: "POST" },
  "Redoing");

export const readCell = (id: string, row: number, column: string) =>
  call<CellStory>(`/${id}/cells/${row}/${encodeURIComponent(column)}`, undefined, "Reading the cell's history");

export const readRecord = (id: string, row: number) =>
  call<SheetRecord>(`/${id}/records/${row}`, undefined, "Reading the row");

export const comment = (id: string, row: number, text: string) =>
  call<{ text: string; by: string; at: string }>(`/${id}/records/${row}/comments`, json("POST", { text }),
    "Keeping the comment");

export const readGrounding = (id: string, view = "") =>
  call<Grounding>(`/${id}/grounding${view ? `?view=${encodeURIComponent(view)}` : ""}`, undefined,
    "Reading what the chat sees");

export const propose = (id: string, words: string) =>
  call<ProposeOutcome>(`/${id}/propose`, json("POST", { words }), "Proposing the change");

export const proposeNewSheet = (token: string, words: string, upload?: { schema: string; file: string }) =>
  call<ProposeOutcome>("/proposals/new", json("POST", { token, words, upload: upload ?? {} }), "Proposing the sheet");

export const applyProposal = (proposalId: string, picks: number[] | null) =>
  call<{ change_id: string; applied: number[]; sheet: string }>(`/proposals/${proposalId}/apply`,
    json("POST", { picks }), "Applying the proposal");

export interface LinkPreview {
  rows: number; matched: number; missed: number; empty: number; some_misses: string[]; other_repeats: number;
  other_name: string; can_bring: { id: string; name: string; kind: Kind }[];
}

export const previewLink = (id: string, column: string, other: string, otherColumn: string) =>
  call<LinkPreview>(`/${id}/links/preview`, json("POST", { column, other, other_column: otherColumn }),
    "Counting the link");

export const keepLink = (id: string, column: string, other: string, otherColumn: string, bring: string[]) =>
  call<Sheet>(`/${id}/links`, json("POST", { column, other, other_column: otherColumn, bring }), "Keeping the link");

export interface TotalPreview {
  rows_with: number; rows_without: number; other_rows_counted: number; other_rows_unmatched: number;
  total: unknown; how: string; other_name: string;
}

export interface TotalAsk { by_column: string; other: string; other_key: string; how: string; of: string; name?: string }

export const previewTotal = (id: string, ask: TotalAsk) =>
  call<TotalPreview>(`/${id}/totals/preview`, json("POST", ask), "Counting the total");

export const keepTotal = (id: string, ask: TotalAsk) =>
  call<Sheet>(`/${id}/totals`, json("POST", ask), "Keeping the total");

export interface MergePreview {
  rows_added: number; cells_changed: number; rows_changed: number; misfit: number; kept_as_is: number;
  no_key: number; file: string; basis: string; token: string; key: string;
  changes: { row: number; column: string; name: string; old: unknown; new: unknown; key: string }[];
  additions: { key: string; values: Record<string, unknown> }[];
  file_columns_not_in_sheet: string[]; sheet_columns_not_in_file: string[];
}

export const previewMerge = (id: string, token: string, key: string) =>
  call<MergePreview>(`/${id}/merge/preview`, json("POST", { token, key }), "Comparing the file");

export const applyMerge = (id: string, token: string, key: string, basis: string) =>
  call<{ change_id: string; cells_changed: number; rows_added: number }>(`/${id}/merge`,
    json("POST", { token, key, basis }), "Merging the file");

// ── pure helpers ─────────────────────────────────────────────────────────────────────────────────────────────────────

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** A date as the grid shows it: "Oct 18, 2017"; with its time, "Oct 2, 2017 10:56". Read from the ISO text the server
 *  sends, never through the viewer's clock — a Date value has no time zone to shift it by. */
export function showDate(v: string, withTime: boolean): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2}))?/.exec(v);
  if (!m) return v;
  const day = `${MONTHS[Number(m[2]) - 1]} ${Number(m[3])}, ${m[1]}`;
  return withTime && m[4] ? `${day} ${m[4]}:${m[5]}` : day;
}

/** A value of a column as the grid shows it. Empty is "" — the grid draws it as empty, never as a zero. */
export function showValue(value: unknown, column: Pick<SheetColumn, "kind" | "currency">): string {
  if (value === null || value === undefined || value === "") return "";
  switch (column.kind) {
    case "money": {
      const n = Number(value);
      return isNaN(n) ? String(value) : formatMoney(n, currencySymbol(column.currency));
    }
    case "number": {
      const n = Number(value);
      if (isNaN(n)) return String(value);
      return Number.isInteger(n) ? formatCount(n) : String(Math.round(n * 1e6) / 1e6);
    }
    case "date": return showDate(String(value), false);
    case "datetime": return showDate(String(value), true);
    case "yesno": return value === true || value === "true" ? "Yes" : "No";
    default: return String(value);
  }
}

/** What a person typed, as the text the server reads for the column's kind. A Yes/No is sent as a boolean; anything
 *  else as typed — the server reads it as the kind or refuses it in a sentence. Empty clears the cell. */
export function typedValue(text: string, kind: Kind): unknown {
  const t = text.trim();
  if (t === "") return null;
  if (kind === "yesno") return /^(y|yes|true|1)$/i.test(t);
  return t;
}

/** A column's totals at the foot, in words: "sum R$ 16.01M · avg R$ 160.99", "earliest Oct 20, 2016", "3 yes". */
export function totalWords(totals: ColumnTotals | undefined, column: SheetColumn, rows: number): string {
  if (!totals) return "";
  const filled = totals.filled ?? 0;
  if (filled === 0) return rows ? "empty" : "";
  if (column.kind === "money" || column.kind === "number") {
    const show = (v: unknown) => showValue(v, column);
    const parts = [`sum ${show(totals.sum)}`];
    if (totals.average !== null && totals.average !== undefined) parts.push(`avg ${show(round2(totals.average))}`);
    return parts.join(" · ");
  }
  if (column.kind === "date" || column.kind === "datetime") {
    return totals.earliest ? `earliest ${showDate(String(totals.earliest), false)}` : "";
  }
  if (column.kind === "yesno") return `${formatCount(totals.yes ?? 0)} yes`;
  const distinct = totals.distinct ?? 0;
  return `${formatCount(distinct)} value${distinct === 1 ? "" : "s"}`;
}

function round2(n: number): number { return Math.round(n * 100) / 100; }

const OP_WORDS: Record<string, string> = {
  is: "is", is_not: "is not", in: "is one of", not_in: "is none of", contains: "contains", not_contains: "lacks",
  gt: ">", gte: "≥", lt: "<", lte: "≤", before: "before", after: "after", empty: "is empty", not_empty: "is filled",
};

/** The filter ops a column's kind offers, in the order a person reaches for them. */
export function opsFor(kind: Kind): string[] {
  if (kind === "number" || kind === "money") return ["is", "is_not", "gt", "gte", "lt", "lte", "empty", "not_empty"];
  if (kind === "date" || kind === "datetime") return ["is", "before", "after", "empty", "not_empty"];
  if (kind === "yesno") return ["is", "empty", "not_empty"];
  if (kind === "choice") return ["is", "is_not", "in", "not_in", "empty", "not_empty"];
  return ["contains", "not_contains", "is", "is_not", "empty", "not_empty"];
}

export const opWords = (op: string) => OP_WORDS[op] ?? op;

/** A filter said in words: "order_status is none of delivered, canceled · estimate before Oct 17, 2018". */
export function filterWords(conditions: Condition[], columns: SheetColumn[]): string {
  return conditions.map(c => {
    const col = columns.find(x => x.id === c.column);
    const name = col?.name ?? c.column;
    if (c.op === "empty" || c.op === "not_empty") return `${name} ${opWords(c.op)}`;
    const v = Array.isArray(c.value) ? c.value.join(", ")
      : col ? showValue(c.value, col) || String(c.value ?? "") : String(c.value ?? "");
    return `${name} ${opWords(c.op)} ${v}`;
  }).join(" · ");
}

const ASKING_FOR_A_CHANGE = /^(please\s+)?(add|make|create|flag|mark|show\s+only|keep\s+only|hide|sort|group|link|join|total|sum\s+up|count\s+up|rename|compute|calculate|put|give\s+me\s+a\s+(view|column)|set\s+up|split|combine|bring)\b/i;

/**
 * Whether something said in the chat beside a sheet asks for a change (proposed, then applied by the person) or asks
 * a question (answered by a query). Read from its first words — an instruction starts with what to do — and shown on
 * the answer, with the other way one click away, so a misreading costs a click and never a change.
 */
export function asksForAChange(words: string): boolean {
  const t = words.trim();
  if (!t || t.endsWith("?")) return false;
  return ASKING_FOR_A_CHANGE.test(t);
}

/** The view's name, then how many rows it shows of the sheet's: "Overdue, still open · 1,729 of 99,441". */
export function viewCount(shown: number, all: number): string {
  return shown === all ? `${formatCount(all)} rows` : `${formatCount(shown)} of ${formatCount(all)} rows`;
}

/** Who made a change, for a person: "you" when it was the reader, else the name after `user:`. */
export function who(by: string, me?: string): string {
  if (!by) return "someone";
  if (me && by === me) return "you";
  return by.replace(/^user:/, "");
}
