/**
 * Home — the one page that prepares for a person and trades with them (ROADMAP §3.54,
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
  text: string;
}

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
  return { about, text: `${said}. Did the team do anything that explains it?` };
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
      out.push({ on: day(d.review_on), what: `"${d.chosen || d.question}" is due for its review` });
    }
  }
  for (const p of predictions) {
    const on = day(p.next_check || p.statement.range_end);
    if (!p.superseded_by && p.state !== "scored" && ahead(on)) {
      out.push({ on, what: `A forecast settles: ${p.statement.text}` });
    }
  }
  return out.sort((a, b) => a.on.localeCompare(b.on));
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

export async function bookSaid(body: { connection_id: string; text: string; about: string; asked: string; by?: string }): Promise<Claim> {
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

export async function readYou(by?: string): Promise<YourRecord> {
  return json(await fetch(`${getApiBase()}/record/you${by ? `?by=${encodeURIComponent(by)}` : ""}`));
}
