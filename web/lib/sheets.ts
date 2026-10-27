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
import { fastApiError, type QueryShown } from "@/lib/api";
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

export type ViewKind = "grid" | "board" | "calendar";

export interface SheetView {
  id: string;
  name: string;
  filter: Condition[];
  sort: { column: string; desc: boolean }[];
  hidden: string[];
  search: string;
  made_by: string;
  /** SH-3: a grid (grouped by `group`, or not), a board with lanes by `group`, a calendar by `date`. */
  kind: ViewKind;
  group: string;
  date: string;
  /** The columns a board's or a calendar's card shows under its title. */
  card: string[];
  /** Shared with everyone who reads the sheet, or its owner's alone. */
  shared: boolean;
  owner: string;
}

/** A declared rule marking the rows meeting its conditions (SH-3). */
export interface SheetRule { id: string; name: string; conditions: Condition[]; tone: RuleTone; made_by: string }

export type RuleTone = "amber" | "red" | "green" | "blue" | "violet";
export const RULE_TONES: RuleTone[] = ["amber", "red", "green", "blue", "violet"];

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
  /** The views the reader sees: every shared one, and the ones they keep to themselves. */
  views: SheetView[];
  key: string;
  rules: SheetRule[];
  /** How many rows each view shows — null for a view whose filter no longer reads. */
  view_rows: Record<string, number | null>;
  rule_rows: Record<string, number | null>;
  /** The person reading, as the server names them. */
  me: string;
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

export type Changed = Record<string, Record<string, { by: string; at: string; version: number }>>;
/** Row → column → the version a change to that cell must name: set, or put back by an undo (then not in `changed`). */
export type Versions = Record<string, Record<string, number>>;

export interface RowsPage {
  rows: unknown[][];
  total: number;
  offset: number;
  totals: Record<string, ColumnTotals>;
  groups: { value: unknown; rows: number }[];
  changed: Changed;
  versions?: Versions;
  columns: string[];
  source_rows: number;
  /** With `sheets.views`: row → the rules marking it. */
  marks?: Record<string, string[]>;
}

export interface GroupsPage {
  group: string;
  total: number;
  /** Over every row the view shows, as the grid's foot. */
  totals: Record<string, ColumnTotals>;
  groups: { value: unknown; rows: number; totals: Record<string, ColumnTotals>; shown: unknown[][] }[];
  groups_total: number;
  groups_not_listed: number;
  columns: string[];
  changed: Changed;
  versions?: Versions;
  marks?: Record<string, string[]>;
}

export interface BoardPage {
  column: string;
  total: number;
  lanes: { value: unknown; rows: number; cards: unknown[][] }[];
  not_shown: { value: unknown; rows: number }[];
  columns: string[];
  movable: boolean;
  changed: Changed;
  versions?: Versions;
  marks: Record<string, string[]>;
}

export interface CalendarPage {
  column: string;
  month: string;
  /** The month a calendar opens on: the latest holding at least one in a hundred of the view's dated rows. */
  where_rows_end: string;
  total: number;
  undated: number;
  earliest: string | null;
  latest: string | null;
  days: { day: string; rows: number }[];
  month_rows: number;
}


export interface RecordField {
  column: string; name: string; kind: Kind; role: Role; value: unknown; source: string; description: string;
}

export interface SheetRecord {
  row: number;
  /** The row's key, or its first text column's value. */
  title: string;
  came_from: string;
  fields: RecordField[];
  linked: { sheet: string; name: string; through: string; direction: "to" | "from"; columns: string[];
    kinds: { kind: Kind; currency: string }[]; rows: { row: number; values: unknown[] }[]; count: number }[];
  marks: { id: string; name: string; tone: RuleTone }[];
  history: { event: string; column: string; value: unknown; previous: unknown; by: string; at: string;
    origin: string }[];
  comments: { id: string; text: string; by: string; at: string }[];
}

export interface ChangeRow extends SheetChange { values: number; definition: number }

export interface ProposedChange {
  type: "view" | "computed_column" | "column" | "link" | "total" | "rule";
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
  call<{ sheets: SheetSummary[]; uploads: UploadedFile[]; shared_with: string; me: string }>("", undefined,
    "Reading the sheets");

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

const extra = (q: RowsQuery, more: Record<string, string | number>) => {
  const base = rowsQuery(q);
  const p = new URLSearchParams(base.slice(1));
  for (const [k, v] of Object.entries(more)) p.set(k, String(v));
  return `?${p.toString()}`;
};

export const readGroups = (id: string, q: RowsQuery, group: string, perGroup = 3) =>
  call<GroupsPage>(`/${id}/groups${extra({ ...q, group: undefined }, { group, per_group: perGroup })}`, undefined,
    "Reading the groups");

export const readBoard = (id: string, q: RowsQuery, column: string, perLane = 20) =>
  call<BoardPage>(`/${id}/board${extra({ ...q, group: undefined }, { column, per_lane: perLane })}`, undefined,
    "Reading the board");

export const readCalendar = (id: string, q: RowsQuery, column: string, month = "") =>
  call<CalendarPage>(`/${id}/calendar${extra({ ...q, group: undefined, sort: undefined },
    month ? { column, month } : { column })}`, undefined, "Reading the calendar");

/** A piece offered for a dashboard made from a sheet (SH-6): a query card of the sheet, run once to say what it shows. */
export interface DashboardPiece {
  key: string;
  title: string;
  kind: "figure" | "bar" | "line" | "table";
  size: "small" | "wide" | "full";
  why: string;
  column?: string;
  currency?: string;
  shown: Partial<QueryShown>;
  preview?: { value?: number | string | null; values?: { x: unknown; v: number | null }[]; of?: number; points?: number;
    first?: unknown; last?: unknown; most?: number | null; rows?: number; more?: boolean };
  refused?: string[];
}

export interface DashboardProposal {
  sheet: string;
  title: string;
  connection_id: string;
  /** What every card reads: the sheet's table, narrowed to the view's rows when the view has a filter. */
  sql: string;
  where: string;
  rows: number | null;
  view: string;
  pieces: DashboardPiece[];
  refused?: string[];
}

export const proposeDashboard = (id: string, view = "") =>
  call<DashboardProposal>(`/${id}/dashboard${view ? `?view=${encodeURIComponent(view)}` : ""}`, undefined,
    "Reading what a dashboard of this sheet would show");

export const saveRule = (id: string, rule: Partial<SheetRule>) =>
  call<Sheet>(`/${id}/rules`, json("PUT", { rule }), "Keeping the rule");

export const removeRule = (id: string, ruleId: string) =>
  call<Sheet>(`/${id}/rules/${ruleId}`, { method: "DELETE" }, "Taking the rule off");

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
  on: "on", marked: "marked", not_marked: "not marked",
};

/** The filter ops a column's kind offers, in the order a person reaches for them. */
export function opsFor(kind: Kind): string[] {
  if (kind === "number" || kind === "money") return ["is", "is_not", "gt", "gte", "lt", "lte", "empty", "not_empty"];
  if (kind === "date") return ["is", "before", "after", "empty", "not_empty"];
  if (kind === "datetime") return ["on", "before", "after", "empty", "not_empty"];
  if (kind === "yesno") return ["is", "empty", "not_empty"];
  if (kind === "choice") return ["is", "is_not", "in", "not_in", "empty", "not_empty"];
  return ["contains", "not_contains", "is", "is_not", "empty", "not_empty"];
}

export const opWords = (op: string) => OP_WORDS[op] ?? op;

/** A filter said in words: "order_status is none of delivered, canceled · estimate before Oct 17, 2018". */
export function filterWords(conditions: Condition[], columns: SheetColumn[], rules: SheetRule[] = []): string {
  return conditions.map(c => {
    if (c.op === "marked" || c.op === "not_marked") {
      const rule = rules.find(r => r.id === c.value);
      return `${opWords(c.op)} ${rule ? rule.name : "by a rule that was taken off"}`;
    }
    if (c.op === "on") {
      const col = columns.find(x => x.id === c.column);
      return `${col?.name ?? c.column} on ${showDate(String(c.value ?? ""), false)}`;
    }
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

/** What a sheet's rows are called, from its name: "Olist orders" → "orders"; anything else → "rows". The same reading
 *  the server's first view takes ("All orders"). */
export function rowNoun(sheetName: string): string {
  const last = (sheetName.trim().split(/\s+/).pop() ?? "").toLowerCase();
  return last.length > 2 && last.endsWith("s") ? last : "rows";
}

/** A count of a sheet's rows in its own words: "1 order", "96,478 orders", "3 rows". */
export function rowsWord(n: number, sheetName: string): string {
  const noun = rowNoun(sheetName);
  return `${formatCount(n)} ${n === 1 ? noun.replace(/s$/, "") : noun}`;
}

/** When something happened, as a list says it: "today", "yesterday", or "Oct 27" (with the year when not this one). */
export function whenWords(at: string, now: Date = new Date()): string {
  const d = new Date(at);
  if (isNaN(d.getTime())) return "";
  const day = (x: Date) => `${x.getFullYear()}-${x.getMonth()}-${x.getDate()}`;
  if (day(d) === day(now)) return "today";
  const y = new Date(now);
  y.setDate(now.getDate() - 1);
  if (day(d) === day(y)) return "yesterday";
  return `${MONTHS[d.getMonth()]} ${d.getDate()}${d.getFullYear() === now.getFullYear() ? "" : `, ${d.getFullYear()}`}`;
}

/** A sheet's last change as its home lists it: "made by you · today", or "Paid: sum of … · ana · Oct 26". The making
 *  of a sheet says who made it — where it came from is the column beside. */
export function lastChangeWords(change: SheetChange, me = "", now?: Date): string {
  const when = change.at ? whenWords(change.at, now) : "";
  const by = who(change.by, me);
  if (/^made\b/.test(change.what)) return `made by ${by}${when ? ` · ${when}` : ""}`;
  return [change.what, by, when].filter(Boolean).join(" · ");
}

/** A value a board's lane or a group's head holds, in words: "Yes", "No", "empty", or the value as its column shows it. */
export function valueWords(value: unknown, column: Pick<SheetColumn, "kind" | "currency"> | undefined): string {
  if (value === null || value === undefined || value === "") return "empty";
  return column ? showValue(value, column) || String(value) : String(value);
}

/** The condition that narrows a view to one group's, lane's or day's rows — the same reading the server counted it by. */
export function valueCondition(column: SheetColumn, value: unknown): Condition {
  if (value === null || value === undefined || value === "") return { column: column.id, op: "empty" };
  return { column: column.id, op: "is", value };
}

/** A month's weeks, Monday first: each week seven days as "YYYY-MM-DD", or "" outside the month. */
export function monthWeeks(month: string): string[][] {
  const m = /^(\d{4})-(\d{2})$/.exec(month);
  if (!m) return [];
  const y = Number(m[1]);
  const mo = Number(m[2]);
  const days = new Date(Date.UTC(y, mo, 0)).getUTCDate();
  const lead = (new Date(Date.UTC(y, mo - 1, 1)).getUTCDay() + 6) % 7;
  const cells = [...Array(lead).fill(""), ...Array.from({ length: days }, (_, i) =>
    `${m[1]}-${m[2]}-${String(i + 1).padStart(2, "0")}`)];
  while (cells.length % 7) cells.push("");
  return Array.from({ length: cells.length / 7 }, (_, w) => cells.slice(w * 7, w * 7 + 7));
}

/** The month before or after: shiftMonth("2018-12", 1) → "2019-01". */
export function shiftMonth(month: string, by: number): string {
  const [y, m] = month.split("-").map(Number);
  const at = y * 12 + (m - 1) + by;
  return `${Math.floor(at / 12)}-${String((at % 12) + 1).padStart(2, "0")}`;
}

/** "September 2018". */
export function monthWords(month: string): string {
  const [y, m] = month.split("-").map(Number);
  const NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
    "November", "December"];
  return NAMES[m - 1] ? `${NAMES[m - 1]} ${y}` : month;
}
