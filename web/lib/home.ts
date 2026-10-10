/**
 * Home — the one page that prepares for a person and trades with them (ROADMAP §3.55,
 * `docs/HOME_STUDY_2026-10-06.md`). What each section shows is picked here, by code, from
 * records the install already keeps; no section calls a model. Every pick is deterministic, so
 * the same records give the same page.
 */
import { getApiBase } from "@/lib/config";
import type { Claim, Decision } from "@/lib/record";

export interface Analysis {
  id: string;
  question: string;
  started_at: string;
  status: string;
  headline: string | null;
  kind?: string;
  connection_id?: string;
}

/** `OBSERVATION_HEADER` in `aughor/automations/temporal.py`: a scheduled run's question opens with it. */
export const SCHEDULED_HEADER = "[Scheduled-run context — written by code, not inferred]";

export const isScheduled = (a: Analysis) => (a.question || "").startsWith(SCHEDULED_HEADER);

/** `_normalize_question` in `aughor/db/history.py` — the same question, however it was spaced. */
export function normalizeQuestion(q: string): string {
  return (q || "").trim().toLowerCase().replace(/\s+/g, " ").replace(/[?.!\s]+$/, "");
}

const done = (a: Analysis, connectionId: string) =>
  a.status === "complete" && (!connectionId || !a.connection_id || a.connection_id === connectionId);

/** The largest percentage a headline states, or null. */
export function percentOf(text: string | null | undefined): number | null {
  const found = [...String(text ?? "").matchAll(/(\d+(?:\.\d+)?)\s*%/g)].map(m => Math.abs(parseFloat(m[1])));
  return found.length ? Math.max(...found) : null;
}

export interface Lead {
  run: Analysis;
  /** True when nothing notable arrived since the last visit and this is the newest one before it. */
  stale: boolean;
}

/**
 * The one thing to know: the largest move the daily run reported since the last visit — a
 * scheduled run that did not call its own move normal variance, ranked by the percentage its
 * headline states (one that states none ranks below one that does), then newest. With nothing
 * new since the last visit, the newest notable run, said as such.
 */
export function pickLead(all: Analysis[], since: string | null, connectionId: string): Lead | null {
  const notable = all
    .filter(a => done(a, connectionId) && isScheduled(a) && a.headline && !/within normal/i.test(a.headline))
    .sort((a, b) => (b.started_at > a.started_at ? 1 : -1));
  if (!notable.length) return null;
  const fresh = since ? notable.filter(a => a.started_at > since) : notable;
  if (!fresh.length) return { run: notable[0], stale: true };
  const ranked = [...fresh].sort((a, b) => {
    const pa = percentOf(a.headline), pb = percentOf(b.headline);
    if (pa !== pb) return (pb ?? -1) - (pa ?? -1);
    return b.started_at > a.started_at ? 1 : -1;
  });
  return { run: ranked[0], stale: false };
}

export interface Standing {
  question: string;
  count: number;
  latest: Analysis;
  first_at: string;
}

/** Questions this connection was asked three or more times, most-asked first. */
export function standingQuestions(all: Analysis[], connectionId: string, min = 3, max = 4): Standing[] {
  const groups = new Map<string, Analysis[]>();
  for (const a of all) {
    if (!done(a, connectionId) || isScheduled(a) || !a.question?.trim()) continue;
    const key = normalizeQuestion(a.question);
    groups.set(key, [...(groups.get(key) ?? []), a]);
  }
  return [...groups.values()]
    .filter(g => g.length >= min)
    .map(g => {
      const sorted = [...g].sort((a, b) => (b.started_at > a.started_at ? 1 : -1));
      return { question: sorted[0].question, count: g.length, latest: sorted[0], first_at: sorted[sorted.length - 1].started_at };
    })
    .sort((a, b) => b.count - a.count || (b.latest.started_at > a.latest.started_at ? 1 : -1))
    .slice(0, max);
}

/** The words that make a headline an explanation: it credits something for a move. */
const CREDITS_A_CAUSE = /\b(driven by|due to|because of|caused by|credit(?:s|ed)? to|led by|thanks to)\b/i;

export const ANSWERS = ["A campaign", "A price change", "Nothing we did", "I don't know"] as const;

export interface PersonQuestion {
  about: Analysis;
  /** The question as booked: the headline, then what the person is asked. */
  text: string;
  /** What it is about — the analysis's own headline, said once. */
  subject: string;
}

/** What the person is asked about a headline that credits a cause. */
export const ASKED = "Did the team do anything that explains it?";

/**
 * A question for you — decided default (ROADMAP §6 item 45 b, c): the newest analysis whose
 * headline credits a cause that no person has spoken to yet, asked in words composed from its
 * own headline. A person knows what the team did; the data does not.
 */
export function pickQuestion(all: Analysis[], connectionId: string, answered: ReadonlySet<string>): PersonQuestion | null {
  const about = all
    .filter(a => done(a, connectionId) && !isScheduled(a) && a.headline && CREDITS_A_CAUSE.test(a.headline) && !answered.has(a.id))
    .sort((a, b) => (b.started_at > a.started_at ? 1 : -1))[0];
  if (!about) return null;
  const said = String(about.headline).trim().replace(/[.\s]+$/, "");
  return { about, text: `${said}. ${ASKED}`, subject: said };
}

export interface Finding {
  id: string;
  text: string;
  domain: string;
  generated_at: string;
}

export function flattenFindings(domains: Record<string, { findings?: unknown[] }>): Finding[] {
  const out: Finding[] = [];
  for (const [domain, block] of Object.entries(domains ?? {})) {
    for (const raw of block?.findings ?? []) {
      const f = raw as Record<string, unknown>;
      const text = String(f.finding ?? f.headline ?? "").trim();
      if (f.id && text) out.push({ id: String(f.id), text, domain, generated_at: String(f.generated_at ?? "") });
    }
  }
  return out;
}

/**
 * Worth another look — decided default (ROADMAP §6 item 45 d): a finding nobody acted on, where
 * acting is dismissing it, deciding on it, or answering about it here. Newest first.
 */
export function pickWorthALook(findings: Finding[], acted: ReadonlySet<string>, skip: ReadonlySet<string> = new Set()): Finding | null {
  return [...findings]
    .filter(f => !acted.has(f.id) && !skip.has(f.id))
    .sort((a, b) => (b.generated_at > a.generated_at ? 1 : b.generated_at < a.generated_at ? -1
      : a.domain.localeCompare(b.domain) || a.id.localeCompare(b.id)))[0] ?? null;
}

export interface Due {
  on: string;
  what: string;
  kind: "review" | "forecast";
  /** A forecast's metric and the range it expects, as its record holds them. */
  metric?: string;
  low?: number | null;
  high?: number | null;
  unit?: string;
  /** The period a forecast is for: its first and last day. */
  from?: string;
  to?: string;
}

const day = (iso: string) => String(iso || "").slice(0, 10);

function addDays(today: string, n: number): string {
  const d = new Date(`${today}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

/** What lands in the next seven days — only what is still ahead; what is due today is Now's. */
export function weekAhead(decisions: Decision[], predictions: Claim[], today: string): Due[] {
  const end = addDays(today, 7);
  const ahead = (on: string) => on > today && on <= end;
  const out: Due[] = [];
  for (const d of decisions) {
    if (!d.superseded_by && ahead(day(d.review_on))) {
      out.push({ on: day(d.review_on), what: `"${d.chosen || d.question}" is due for its review`, kind: "review" });
    }
  }
  for (const p of predictions) {
    const on = day(p.next_check || p.statement.range_end);
    if (!p.superseded_by && p.state !== "scored" && ahead(on)) {
      const x = (p.extra ?? {}) as { low?: unknown; high?: unknown };
      const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);
      out.push({ on, what: `A forecast settles: ${p.statement.text}`, kind: "forecast", metric: p.statement.metric,
                 low: num(x.low), high: num(x.high), unit: p.statement.unit, from: day(p.statement.range_start),
                 to: day(p.statement.range_end) });
    }
  }
  return out.sort((a, b) => a.on.localeCompare(b.on));
}

export interface DueDay {
  on: string;
  reviews: Due[];
  forecasts: Due[];
}

/** What a forecast's unit says it measures, read from the words its record holds ("USD", "ratio 0..1", "percent 0-100",
 *  "count", "days, roughly 0-30"). */
export type UnitKind = "money" | "count" | "ratio" | "percent" | "days" | "number";
export function unitKind(unit: string | undefined): UnitKind {
  const u = String(unit ?? "").trim().toLowerCase();
  if (u === "$" || /^usd\b/.test(u)) return "money";
  if (u === "%" || u.startsWith("percent")) return "percent";
  if (u.startsWith("ratio") || u.startsWith("share") || u.startsWith("fraction")) return "ratio";
  if (u.startsWith("count")) return "count";
  if (u.startsWith("day")) return "days";
  return "number";
}

const ORDER: Record<UnitKind, number> = { money: 0, count: 1, percent: 2, ratio: 2, days: 3, number: 4 };

/** The week ahead, a day at a time: what is due for review and what settles — a day's forecasts money first, then
 *  counts, then shares, each kind in the order it came. */
export function byDay(due: Due[]): DueDay[] {
  const days = new Map<string, DueDay>();
  for (const d of due) {
    const slot = days.get(d.on) ?? { on: d.on, reviews: [], forecasts: [] };
    (d.kind === "review" ? slot.reviews : slot.forecasts).push(d);
    days.set(d.on, slot);
  }
  for (const slot of days.values()) {
    slot.forecasts = slot.forecasts.map((f, i) => [f, i] as const)
      .sort((a, b) => ORDER[unitKind(a[0].unit)] - ORDER[unitKind(b[0].unit)] || a[1] - b[1]).map(([f]) => f);
  }
  return [...days.values()].sort((a, b) => a.on.localeCompare(b.on));
}

/** A metric's id in a reader's words: "net_merchandise_revenue" → "Net merchandise revenue". An id that ends in its
 *  own initials says them once: "average_order_value_aov" → "Average order value". */
export function metricWords(id: string | undefined): string {
  const words = String(id ?? "").replace(/[_-]+/g, " ").trim().split(/\s+/).filter(Boolean);
  const last = words[words.length - 1] ?? "";
  if (words.length > 2 && last.length >= 2 && last.toLowerCase() === words.slice(0, -1).map(x => x[0]).join("").toLowerCase()) {
    words.pop();
  }
  const w = words.join(" ");
  return w ? w[0].toUpperCase() + w.slice(1) : "";
}

const short = (n: number, money: boolean): string => {
  const a = Math.abs(n);
  const body = a >= 1e6 ? `${(a / 1e6).toFixed(1)}M` : a >= 1e3 ? `${(a / 1e3).toFixed(1)}K` : a >= 10 ? a.toFixed(0) : a.toFixed(2);
  return `${n < 0 ? "-" : ""}${money ? "$" : ""}${body}`;
};

/** A forecast's range as a reader reads it, by what its unit says: money short ("$79.4K – $98.0K", "$76 – $83"), a
 *  ratio or a percent as a percent ("9.2% – 11.1%"), a count whole ("1,595 – 1,924"), days as days ("1.9 – 2.1 days"). */
export function rangeText(low: number | null | undefined, high: number | null | undefined, unit: string | undefined): string {
  if (low == null || high == null) return "";
  const kind = unitKind(unit);
  if (kind === "money") return `${short(low, true)} – ${short(high, true)}`;
  if (kind === "ratio") return `${(low * 100).toFixed(1)}% – ${(high * 100).toFixed(1)}%`;
  if (kind === "percent") return `${low.toFixed(1)}% – ${high.toFixed(1)}%`;
  if (kind === "days") return `${low.toFixed(1)} – ${high.toFixed(1)} days`;
  // a count is written whole, with separators; a small quantity to two decimals
  const digits = kind === "count" || Math.max(Math.abs(low), Math.abs(high)) >= 10 ? 0 : 2;
  const w = (n: number) => n.toLocaleString("en-US", { maximumFractionDigits: digits });
  return `${w(low)} – ${w(high)}`;
}

const part = (d: Date, o: Intl.DateTimeFormatOptions) => d.toLocaleDateString("en-US", { ...o, timeZone: "UTC" });

/** A day and its month as Home writes them: "12 Oct", "2 Sep". */
export function dayMonth(iso: string): string {
  const d = new Date(`${day(iso)}T00:00:00Z`);
  return isNaN(d.getTime()) ? iso : `${d.getUTCDate()} ${part(d, { month: "short" })}`;
}

/** A day as Home writes it: "Mon 12 Oct". */
export function dayWords(iso: string): string {
  const d = new Date(`${day(iso)}T00:00:00Z`);
  return isNaN(d.getTime()) ? iso : `${part(d, { weekday: "short" })} ${dayMonth(iso)}`;
}

/** Whole days between a day and today (0 when it is today or later). */
export function daysBehind(observed: string, today: string): number {
  const a = Date.parse(`${day(observed)}T00:00:00Z`), b = Date.parse(`${day(today)}T00:00:00Z`);
  return Number.isNaN(a) || Number.isNaN(b) ? 0 : Math.max(0, Math.round((b - a) / 86_400_000));
}

/** The lead's figure, read from its analysis's own baseline numbers — never from its sentences. */
export interface LeadFigure {
  metric: string;
  /** The day the figure is for, ISO. */
  day: string;
  /** The value and its change, as the analysis wrote them ("$19,087.76", "+$209.55"). */
  value: string;
  change: string | null;
  /** The change as a ratio (0.011 for +1.1%), when the analysis measured one. */
  pct: number | null;
  /** What the baseline said of it ("within normal range"), and whether that is unusual. */
  verdict: string | null;
  unusual: boolean;
}

type Row = Record<string, unknown>;
const rows = (v: unknown): Row[] => (Array.isArray(v) ? v.filter((x): x is Row => !!x && typeof x === "object") : []);

/** The figure a scheduled run reported, from the finding of its baseline phase that states a value and its change;
 *  null when the analysis holds none (a report of another shape says its headline instead). */
export function leadFigure(report: unknown): LeadFigure | null {
  const rep = (report && typeof report === "object" ? report : {}) as Row;
  const baseline = rows(rep.phases).find(p => p.phase_id === "baseline");
  const findings = rows(baseline?.findings);
  for (const f of findings) {
    const kn = rows(f.key_numbers).find(k => k.delta != null && String(k.delta).trim() !== "");
    if (!kn) continue;
    const cols = Array.isArray(f.columns) ? (f.columns as unknown[]).map(String) : [];
    const first = Array.isArray(f.rows) && Array.isArray((f.rows as unknown[])[0]) ? (f.rows as unknown[][])[0] : [];
    const at = (name: string) => (cols.indexOf(name) >= 0 ? first[cols.indexOf(name)] : undefined);
    const pct = Number(at("pct_change"));
    const windows = rows((rep.period_as_measured as Row | undefined)?.windows);
    const observed = String(at("observation_date") ?? windows[0]?.start ?? "").slice(0, 10);
    const note = findings.map(x => String(x.stat_note ?? "")).find(n => /—/.test(n)) ?? "";
    const verdict = note ? note.split("—").pop()!.trim() : null;
    const metric = String((rep.spec as Row | undefined)?.metric_label ?? "").trim()
      || String(kn.label ?? "").replace(/^[A-Z][a-z]{2} \d{1,2}\s+/, "").trim();
    return { metric, day: observed, value: String(kn.value ?? ""), change: String(kn.delta), pct: Number.isFinite(pct) ? pct : null,
             verdict, unusual: !!verdict && /outside|anomal|unusual|significant/i.test(verdict) && !/within/i.test(verdict) };
  }
  return null;
}

export interface LeadDetail {
  summary: string;
  figure: LeadFigure | null;
  /** The analysis's confidence, and why it is not higher — said beside the figure when it is below HIGH. */
  confidence: string;
  why: string;
}

/** The lead's analysis, read once: its summary, its figure, its confidence. */
export async function leadDetail(id: string): Promise<LeadDetail> {
  const row = await json<{ report?: unknown }>(await fetch(`${getApiBase()}/investigations/${encodeURIComponent(id)}`));
  const report = (typeof row.report === "string" ? JSON.parse(row.report || "{}") : (row.report ?? {})) as Row;
  return { summary: String(report.executive_summary ?? ""), figure: leadFigure(report),
           confidence: String(report.confidence ?? ""), why: String(report.confidence_justification ?? "") };
}

// ── doors ───────────────────────────────────────────────────────────────────────────────

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.json().catch(() => null) as { detail?: string } | null;
    throw new Error(body?.detail || `${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export interface AskedBefore {
  count: number;
  first_at: string;
  last_at: string;
  latest: { id: string; kind: string; headline: string; asked_at: string } | null;
}

/** What is already on record for this exact question (`GET /ask/prior`). */
export async function askedBefore(connectionId: string, question: string): Promise<AskedBefore> {
  const q = new URLSearchParams({ connection_id: connectionId, question });
  return json(await fetch(`${getApiBase()}/ask/prior?${q}`));
}

export async function domainFindings(connectionId: string): Promise<Finding[]> {
  const domains = await json<Record<string, { findings?: unknown[] }>>(
    await fetch(`${getApiBase()}/exploration/${encodeURIComponent(connectionId)}/domains`));
  return flattenFindings(domains);
}

export async function dismissFinding(connectionId: string, id: string, reason: string): Promise<void> {
  await json(await fetch(
    `${getApiBase()}/exploration/${encodeURIComponent(connectionId)}/findings/${encodeURIComponent(id)}/dismiss`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ reason }) }));
}

/** Re-run a finding's own stored SQL once, with no model: `confirmed`, or `drifted` and how. */
export async function recheckFinding(connectionId: string, id: string): Promise<{ status?: string; note?: string }> {
  return json(await fetch(
    `${getApiBase()}/exploration/${encodeURIComponent(connectionId)}/findings/${encodeURIComponent(id)}/revalidate`,
    { method: "POST" }));
}

/** Booked as said by the person signed in — the server's record of who, never a name sent here. */
export async function bookSaid(body: { connection_id: string; text: string; about: string; asked: string }): Promise<Claim> {
  return json(await fetch(`${getApiBase()}/record/claims/said`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }));
}

export interface YourRecord {
  principal: string;
  n: number;
  by_kind: Record<string, number>;
  predictions: { scored: number; inside: number; coverage_observed: number | null };
  note?: string;
}

/** The reader's own record — whoever the server says is reading, not a name the page sends. */
export async function readYou(): Promise<YourRecord> {
  return json(await fetch(`${getApiBase()}/record/you`));
}
