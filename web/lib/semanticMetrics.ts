/**
 * Where each metric of a connection stands, for the Semantic Layer's Metrics tab (`aughor-v2/CLARITY.md`): the figures
 * it opens on, what goes under "Needs you", and the group each row of the list sits in.
 *
 * Read from what the tab already holds — the connection's catalogue (`GET /metrics/catalogue/{id}`) and its stored
 * definitions (`GET /metrics?connection_id=`); nothing here fetches or decides a write. The screen only lays it out.
 *
 * The question it answers (the user, 2026-10-12: why LuxExperience's metrics "had not popped up"): of what applies to
 * this connection, what is approved AND measured, what waits for a person's review, what is approved but cannot be
 * measured — no SQL, or no date column, so no figure for a period — and which industry metrics are not bound here.
 *
 * Not `lib/metricStanding.ts`: that one says, for a Briefing tile matched by name, only whether its metric is approved,
 * a draft, a suggestion or absent. This one is the Semantic Layer's own reading of each row, measurement included.
 */
import type { CatalogueMetric, Metric, RemovedProposal } from "@/lib/api";
import { MONTHS_SHORT } from "@/lib/format";

/** "*" — every dataset of the connection. */
export const ALL = "*";

/** The dataset a stored definition belongs to, as the server resolved it. */
export const homeOf = (m: Metric) => m.home_schema ?? m.schema_name ?? ALL;
export const sameDataset = (a?: string | null, b?: string | null) => (a || ALL).toLowerCase() === (b || ALL).toLowerCase();
export const datasetWords = (ds?: string | null) => (!ds || ds === ALL ? "every dataset" : ds);
/** A catalogue row's identity: two datasets may each have their own metric of one name. */
export const rowKey = (r: CatalogueMetric) => `${r.source}:${r.schema ?? ALL}:${r.name}`;

/**
 * Where one row stands. The first four are approved definitions; then the governance states of the rest of the
 * registry; then what the catalogue computes but nobody has made a definition of yet.
 */
export type Standing =
  | "measured"      // approved, with SQL and a date column: a figure for any period
  | "no_date"       // approved, with SQL, no date column: it cannot be measured for a period
  | "date_unread"   // approved, with SQL and a date on a table the SQL does not read: it cannot be measured for a period
  | "no_sql"        // approved, with no SQL: it cannot be measured at all
  | "unchecked"     // approved, but its stored definition could not be read — whether it is measured is not known
  | "proposed"      // waiting for a person's review
  | "draft"
  | "retired"       // deprecated
  | "suggested"     // computable here, not a definition yet (the explorer's, or an industry package's)
  | "needs_sql"     // a suggestion that came with no SQL
  | "sql_rejected"  // a suggestion whose SQL the build-time audit refused
  | "check_failed"  // a proposal a gate refused — its figures never move, sit outside its range, … (Arc MC)
  | "not_bound";    // an industry metric naming data this connection has not bound

export type Group = "approved" | "review" | "draft" | "suggested" | "not_bound" | "retired";

/** The list's groups, in the order a reader meets them. A folded group is one line with its count until opened. */
export const GROUPS: readonly { id: Group; label: string; folded?: boolean }[] = [
  { id: "approved", label: "Approved" },
  { id: "review", label: "Waiting for review" },
  { id: "draft", label: "Drafts" },
  { id: "suggested", label: "Suggested" },
  { id: "not_bound", label: "Industry, not bound" },
  { id: "retired", label: "Retired", folded: true },
];

const GROUP_OF: Record<Standing, Group> = {
  measured: "approved", no_date: "approved", date_unread: "approved", no_sql: "approved", unchecked: "approved",
  proposed: "review", draft: "draft", retired: "retired",
  suggested: "suggested", needs_sql: "suggested", sql_rejected: "suggested", check_failed: "suggested",
  not_bound: "not_bound",
};
export const groupOf = (s: Standing): Group => GROUP_OF[s];

/** Whether a stored definition says how it is measured for a date range. */
export const hasDates = (m: Metric | null | undefined) => !!(m?.time_kind && m.time_column);

/**
 * Where a row stands. `stored` is its definition in the registry (a defined row's). With none — the registry could not
 * be read, or holds no definition the row matches — an approved row's dates are not known, and it says so rather than
 * guess either way.
 */
export function standingOf(row: CatalogueMetric, stored: Metric | null | undefined): Standing {
  if (row.source !== "defined" || row.state !== "defined") {
    if (row.state === "needs_binding") return "not_bound";
    if (row.state === "needs_formula") return "needs_sql";
    if (row.state === "formula_rejected") return "sql_rejected";
    if (row.state === "gate_failed") return "check_failed";
    return "suggested";
  }
  const status = stored?.status || row.status || "draft";
  if (status === "proposed") return "proposed";
  if (status === "deprecated") return "retired";
  if (status !== "approved") return "draft";
  const sql = (stored?.sql ?? row.sql ?? "").trim();
  if (!sql) return "no_sql";
  if (!stored) return "unchecked";
  if (!hasDates(stored)) return "no_date";
  // The server read whether the date can measure it: a date on a table the SQL does not read stood as
  // "✓ measured" for two days (Gross Margin %, 2026-10-15). An older list without the field keeps the old reading.
  return stored.measurable === false ? "date_unread" : "measured";
}

/** A row with where it stands and the stored definition behind it. */
export interface Placed {
  row: CatalogueMetric;
  key: string;
  standing: Standing;
  stored: Metric | null;
  /** Two stored definitions share its name in its dataset — the backend reads the newer. */
  duplicate: boolean;
}

/** The stored definition behind a row: same name AND dataset, else the only one of that name. */
export function storedFor(metrics: Metric[], name: string, ds: string): Metric | undefined {
  return metrics.find(m => m.name === name && sameDataset(homeOf(m), ds))
    ?? (metrics.filter(m => m.name === name).length === 1 ? metrics.find(m => m.name === name) : undefined);
}

export function place(rows: CatalogueMetric[], metrics: Metric[]): Placed[] {
  return rows.map(row => {
    const stored = row.source === "defined" ? storedFor(metrics, row.name, row.schema) ?? null : null;
    return {
      row, key: rowKey(row), stored,
      standing: standingOf(row, stored),
      duplicate: row.source === "defined"
        && metrics.filter(m => m.name === row.name && sameDataset(homeOf(m), row.schema)).length > 1,
    };
  });
}

/** The list, grouped in `GROUPS` order; a group with no row is left out. */
export function grouped(placed: Placed[]): { id: Group; label: string; folded: boolean; items: Placed[] }[] {
  return GROUPS.map(g => ({ id: g.id, label: g.label, folded: !!g.folded, items: placed.filter(p => groupOf(p.standing) === g.id) }))
    .filter(g => g.items.length > 0);
}

// ── The figures ─────────────────────────────────────────────────────────────────────────────────────────────────────

export interface StandingFigures {
  approved: number;
  measured: number;
  noDate: number;
  /** Approved, dated, but the date is on a table the SQL does not read — not measurable for a period either. */
  dateUnread: number;
  noSql: number;
  /** Approved, but the registry could not be read, so whether each is measured is not known. */
  unchecked: number;
  review: number;
  drafts: number;
  suggested: number;
  notBound: number;
  retired: number;
}

export function figures(placed: Placed[]): StandingFigures {
  const n = (...s: Standing[]) => placed.filter(p => s.includes(p.standing)).length;
  return {
    approved: n("measured", "no_date", "date_unread", "no_sql", "unchecked"),
    measured: n("measured"), noDate: n("no_date"), dateUnread: n("date_unread"), noSql: n("no_sql"), unchecked: n("unchecked"),
    review: n("proposed"), drafts: n("draft"), suggested: n("suggested", "needs_sql", "sql_rejected"),
    notBound: n("not_bound"), retired: n("retired"),
  };
}

// ── Needs you ───────────────────────────────────────────────────────────────────────────────────────────────────────

/** One kind of thing that needs a person, with every row of that kind — said once, its rows its buttons. */
export interface Need {
  kind: "review" | "no_sql" | "no_date" | "not_bound" | "duplicate";
  items: Placed[];
}

/** What needs a person, in the order to take it: decisions first, then what stops an approved metric being measured,
 *  then the industry metrics this connection has not bound, then a name defined twice. */
export function needs(placed: Placed[]): Need[] {
  const of = (kind: Need["kind"], items: Placed[]): Need[] => (items.length ? [{ kind, items }] : []);
  return [
    ...of("review", placed.filter(p => p.standing === "proposed")),
    ...of("no_sql", placed.filter(p => p.standing === "no_sql")),
    ...of("no_date", placed.filter(p => p.standing === "no_date" || p.standing === "date_unread")),
    ...of("not_bound", placed.filter(p => p.standing === "not_bound")),
    ...of("duplicate", placed.filter(p => p.duplicate)),
  ];
}

/** The data an unbound industry metric names and this connection has not bound, each once. */
export function missingRoles(items: Placed[]): string[] {
  return [...new Set(items.flatMap(p => p.row.missing_roles))];
}

/** The packages unbound industry metrics come from, each once. */
export function packsOf(items: Placed[]): string[] {
  return [...new Set(items.map(p => p.row.pack_id).filter(Boolean))];
}

// ── The last decision ───────────────────────────────────────────────────────────────────────────────────────────────

export interface LastDecision {
  at: string;
  action: "approved" | "proposed" | "removed";
  /** The metric the latest decision was about. */
  label: string;
  by: string;
  /** Decisions of the same kind on the same day, the latest included: a batch is said once, as a count. */
  count: number;
}

/**
 * The newest decision on these metrics: an approval, a proposal, or a suggestion a person removed. Only the
 * decisions the registry stamps with a time are known here — an edit carries none, so this is "last decision", never
 * "last change".
 */
export function lastDecision(stored: Metric[], removed: RemovedProposal[]): LastDecision | null {
  type Ev = { at: string; t: number; action: LastDecision["action"]; label: string; by: string };
  const evs: Ev[] = [];
  const push = (at: string | null | undefined, action: Ev["action"], label: string, by: string | null | undefined) => {
    const t = at ? Date.parse(at) : NaN;
    if (!Number.isNaN(t)) evs.push({ at: at as string, t, action, label, by: by || "" });
  };
  for (const m of stored) {
    push(m.approved_at, "approved", m.label || m.name, m.approved_by);
    if (m.status === "proposed") push(m.proposed_at, "proposed", m.label || m.name, m.proposed_by);
  }
  for (const r of removed) push(r.at, "removed", r.label || r.name, r.by);
  if (!evs.length) return null;
  evs.sort((a, b) => b.t - a.t);
  const top = evs[0];
  const day = top.at.slice(0, 10);
  const count = evs.filter(e => e.action === top.action && e.at.slice(0, 10) === day).length;
  return { at: top.at, action: top.action, label: top.label, by: top.by, count };
}

/** A day as the figure says it: "today", "yesterday", else "8 Oct" (with the year when it is not this one). */
export function dayWords(iso: string, now: Date = new Date()): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const ymd = (x: Date) => `${x.getFullYear()}-${x.getMonth()}-${x.getDate()}`;
  if (ymd(d) === ymd(now)) return "today";
  const y = new Date(now);
  y.setDate(now.getDate() - 1);
  if (ymd(d) === ymd(y)) return "yesterday";
  const dm = `${d.getDate()} ${MONTHS_SHORT[d.getMonth()]}`;
  return d.getFullYear() === now.getFullYear() ? dm : `${dm} ${d.getFullYear()}`;
}

// ── Short words for a row ───────────────────────────────────────────────────────────────────────────────────────────

/** A unit as a row carries it: "EUR, typically 300-2000 for luxury…" → "EUR"; "ratio 0-1 (e-commerce…)" → "ratio 0-1".
 *  The whole text stays on the definition. */
export function shortUnit(unit: string | null | undefined): string {
  const u = (unit ?? "").trim();
  if (!u) return "";
  return u.split(/[,(;]/)[0].trim();
}

/** A date column as a row shows it — its table and column, without the project and dataset in front. */
export function shortColumn(col: string | null | undefined): string {
  const parts = (col ?? "").split(".").filter(Boolean);
  return parts.slice(-2).join(".");
}

/** How a stored definition is measured for a date range, in one sentence. */
export function datesSentence(m: Metric): string {
  if (!m.time_kind || !m.time_column) return "Not set — this metric cannot be measured for a date range yet.";
  if (m.time_kind === "cohort") {
    const settles = m.settles_after_days != null ? `, settles after ${m.settles_after_days} days` : ", settling time not yet measured";
    return `Cohort — tied to ${m.time_column}, completed by ${m.outcome_column ?? "?"}${settles}.`;
  }
  if (m.time_kind === "stock") return `Stock — a row counts from ${m.time_column} until ${m.until_column ?? "?"}.`;
  return `Flow — a row counts on the day of ${m.time_column}.`;
}

/** Why the dates, as set, cannot measure the metric — the server's reading — or "". Said beside the dates sentence. */
export function datesProblem(m: Metric): string {
  if (m.measurable !== false || !m.time_kind || !m.time_column) return "";
  return `${m.measurable_why || "its date is on a table its SQL does not read"} — it can't be measured for a period until the SQL reads it.`;
}

// ── A row's state, as a chip ────────────────────────────────────────────────────────────────────────────────────────

/** Where a suggestion came from, in a few words. */
export function sourceWords(r: CatalogueMetric): string {
  if (r.source === "industry") return `${r.pack_id || "industry"} package`;
  if (r.source === "explorer") return "explorer";
  if (r.source === "coverage") return ORIGIN_WORDS[r.origin ?? ""] ?? "coverage";
  return "defined";
}

/** How a coverage proposal was made, in a few words (Arc MC). */
export const ORIGIN_WORDS: Record<string, string> = {
  recipe: "package recipe", ontology: "ontology", pattern: "knowledge base", area: "written for its area",
  blind_spot: "explorer keeps computing it",
};

const SOURCE_TITLE: Record<string, string> = {
  industry: "A recipe from the knowledge package for the industry set in Settings — computable here, not yet a definition.",
  explorer: "Proposed by the explorer from this connection's own tables and columns — not yet a definition.",
  coverage: "Proposed for an area of the business this connection's data covers, and checked before it was listed — not yet a definition.",
};

export type ChipTone = "plain" | "up" | "amber" | "violet";

/** The chip a row wears: where it stands in a few words, the whole of it on hover. Amber — it needs a person; violet —
 *  a model's or a package's, not yet confirmed; green — approved and measured. */
export function standingChip(p: Placed): { tone: ChipTone; text: string; title: string } {
  const r = p.row, m = p.stored;
  switch (p.standing) {
    case "measured":
      return { tone: "up", text: "✓ measured", title: m ? datesSentence(m) : "Approved, with SQL and a date column." };
    case "no_date":
      return { tone: "amber", text: "no date column", title: "Approved, but it has no date column — it can't be measured for a period." };
    case "date_unread":
      return { tone: "amber", text: "date on a table it doesn't read",
        title: `Approved, but ${m?.measurable_why || "its date is on a table its SQL does not read"} — it can't be measured for a period. Join that table in the SQL, then choose the date.` };
    case "no_sql":
      return { tone: "amber", text: "no SQL", title: "Approved, but it has no SQL — it can't be measured." };
    case "unchecked":
      return { tone: "plain", text: "not checked",
        title: "Its stored definition could not be read, so whether it can be measured is not known." };
    case "proposed":
      return { tone: "amber", text: "waiting for review",
        title: `Proposed${m?.proposed_by ? ` by ${m.proposed_by}` : ""} — approve or reject it.` };
    case "draft":
      return { tone: "plain", text: "draft", title: "Saved, not yet proposed for approval." };
    case "retired":
      return { tone: "plain", text: "retired", title: "Deprecated — propose it again to bring it back." };
    case "suggested":
      return { tone: "violet", text: `suggested · ${sourceWords(r)}`, title: SOURCE_TITLE[r.source] ?? "" };
    case "needs_sql":
      return { tone: "violet", text: "suggested · no SQL",
        title: "The columns are identified but no SQL was proposed. Open it and supply one." };
    case "sql_rejected":
      // Distinct from "no SQL" on purpose: SQL WAS written and the build-time audit refused to trust it, so the work is
      // to fix what it names — often the connection rather than the SQL.
      return { tone: "violet", text: "SQL rejected",
        title: r.reason || "SQL was proposed and the audit could not trust it, so it was dropped." };
    case "check_failed":
      return { tone: "amber", text: "failed a check",
        title: r.reason || "A check refused it when it was proposed. Fix it in its editor before adopting it." };
    case "not_bound":
      return { tone: "amber", text: r.missing_roles.length ? `not bound · ${r.missing_roles.join(", ")}` : "not bound",
        title: `It names data this connection has not bound to the ${r.pack_id || "industry"} package, so it cannot be computed here yet.` };
  }
}
