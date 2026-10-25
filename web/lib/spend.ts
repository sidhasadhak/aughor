/**
 * Spend — the figures and folds the Spend screen leads with, computed from the reads it already
 * makes (`/usage`, `/obs/usage-summary`, `/governance/caps`, `/audit/feed`). Pure, so the counts a
 * reader acts on are tested where they are made; `components/SpendPanel.tsx` lays them out to the
 * approved mockup (`design-mockups/spend.html`, 2026-10-10).
 *
 * The one rule every function here keeps: a call with no price is UNKNOWN, never free. A total
 * with unpriced calls under it is a floor and says "at least"; a total with no priced call under
 * it is not a number at all.
 */
import {
  callerFeature,
  type AuditFeedEvent, type CallerFeature, type UsageCap, type UsageReport, type UsageSummary,
} from "@/lib/api";
import { compactNumber, countNoun, formatCount, formatMoney, pct } from "@/lib/format";

export const money = (usd: number): string => formatMoney(usd, "$");

/** Tokens as the mockup writes them: `4.48M`, `167K`, `850`. */
export function tokens(n: number): string {
  if (n >= 1e6) return compactNumber(n, 2);
  if (n >= 1e3) return compactNumber(n, 0);
  return String(Math.round(n));
}

/** A model id without a vendor prefix its own name repeats: `deepseek/deepseek-v4.1-flash` →
 *  `deepseek-v4.1-flash`. `typesafe/jev-router` keeps its prefix — the name does not say whose it is. */
export function modelName(model: string): string {
  const i = model.indexOf("/");
  if (i < 0) return model;
  const org = model.slice(0, i).toLowerCase();
  const rest = model.slice(i + 1);
  return org && rest.toLowerCase().startsWith(org) ? rest : model;
}

// ── The figures ─────────────────────────────────────────────────────────────

export interface SpendTotals {
  calls: number;
  cost: number;
  /** Calls no declared or published rate covers: their cost is unknown, not zero. */
  unpriced: number;
  priced: number;
  failures: number;
  /** The model with the most failed calls, when any failed. */
  worst: string | null;
}

export function spendTotals(report: UsageReport): SpendTotals {
  let cost = 0, unpriced = 0, failures = 0;
  let worst: { model: string; failures: number } | null = null;
  for (const r of report.rows) {
    cost += r.cost_usd;
    unpriced += r.unpriced_calls;
    failures += r.failures;
    if (r.failures > 0 && (!worst || r.failures > worst.failures)) {
      worst = { model: String(r.model ?? ""), failures: r.failures };
    }
  }
  const calls = report.total_calls;
  return { calls, cost, unpriced, priced: Math.max(0, calls - unpriced), failures, worst: worst ? modelName(worst.model) : null };
}

export interface SpentFigure {
  label: string;
  value: string;
  /** The caveat, as an amber chip: how much of the total is priced. */
  caveat: string | null;
  /** The muted line when there is no caveat to make. */
  note: string | null;
  /** True when no call is priced: the value is not a number and is drawn as unknown. */
  unknown: boolean;
}

/** The share of calls priced, as the chip says it — never "0%" for a share that is not zero. */
function pricedShare(priced: number, calls: number): string {
  if (priced <= 0) return "no call priced";
  const share = priced / calls;
  if (share < 0.01) return "<1% of calls priced";
  return `${pct(share)} of calls priced`;
}

export function spentFigure(t: SpendTotals): SpentFigure {
  if (t.calls === 0) return { label: "Spent", value: money(0), caveat: null, note: "no model calls yet", unknown: false };
  if (t.unpriced === 0) return { label: "Spent", value: money(t.cost), caveat: null, note: "every call priced", unknown: false };
  if (t.priced === 0) return { label: "Spent", value: "Unknown", caveat: pricedShare(0, t.calls), note: null, unknown: true };
  return { label: "Spent · at least", value: money(t.cost), caveat: pricedShare(t.priced, t.calls), note: null, unknown: false };
}

export function failedLine(t: SpendTotals): string {
  if (t.failures === 0 || t.calls === 0) return "no call failed";
  const share = pct(t.failures / t.calls, 1);
  return t.worst ? `${share} · most on ${t.worst}` : share;
}

/** The models whose calls carry no price, most calls first. */
export function unpricedModels(report: UsageReport): { name: string; calls: number }[] {
  return report.rows.filter(r => r.unpriced_calls > 0)
    .sort((a, b) => b.unpriced_calls - a.unpriced_calls)
    .map(r => ({ name: modelName(String(r.model ?? "")), calls: r.unpriced_calls }));
}

// ── Caps ────────────────────────────────────────────────────────────────────

export function capAmount(metric: string, n: number): string {
  if (metric === "cost_usd") return money(n);
  if (metric === "total_tokens") return `${tokens(n)} tokens`;
  if (metric === "calls") return countNoun(n, "call");
  return `${formatCount(n)} ${metric.replace(/_/g, " ")}`;
}

/** The cap nearest its limit — the one a reader should see first. */
export function tightestCap(caps: UsageCap[]): UsageCap | null {
  const ratio = (c: UsageCap) => (c.observed != null && c.limit > 0 ? c.observed / c.limit : -1);
  return [...caps].sort((a, b) => ratio(b) - ratio(a))[0] ?? null;
}

// ── Tokens by model ─────────────────────────────────────────────────────────

export interface ModelBar {
  key: string;
  name: string;
  /** provider · calls · what it cost, as far as anyone can say. */
  sub: string;
  tokens: number;
  /** Any call on it with no price: the bar is drawn hatched — unknown, not zero. */
  unpriced: boolean;
  /** The fold of the models past the top few. */
  folded: boolean;
  /** The hover text: everything the row knows, in full. */
  title: string;
}

function modelSub(provider: string, calls: number, cost: number, unpriced: number): string {
  const head = `${provider ? `${provider} · ` : ""}${countNoun(calls, "call")}`;
  if (unpriced === 0) return `${head} · ${cost > 0 ? money(cost) : "free"}`;
  return cost > 0 ? `${head} · at least ${money(cost)}` : head;
}

export function modelBars(report: UsageReport, max = 6): ModelBar[] {
  const rows = [...report.rows].sort((a, b) => b.total_tokens - a.total_tokens);
  const shown = rows.length > max ? rows.slice(0, max - 1) : rows;
  const rest = rows.slice(shown.length);
  const bars: ModelBar[] = shown.map(r => {
    const model = String(r.model ?? "");
    const provider = String(r.provider ?? "");
    return {
      key: `${provider}/${model}`,
      name: modelName(model) || "(unnamed model)",
      sub: modelSub(provider, r.calls, r.cost_usd, r.unpriced_calls),
      tokens: r.total_tokens,
      unpriced: r.unpriced_calls > 0,
      folded: false,
      title: [
        `${model} · ${provider}`, countNoun(r.calls, "call"), `${tokens(r.total_tokens)} tokens`,
        r.failures ? `${formatCount(r.failures)} failed (${pct(r.failure_rate, 1)})` : "none failed",
        r.unpriced_calls ? `${countNoun(r.unpriced_calls, "call")} with no price` : "every call priced",
      ].join(" · "),
    };
  });
  if (rest.length) {
    const calls = rest.reduce((n, r) => n + r.calls, 0);
    const unpriced = rest.reduce((n, r) => n + r.unpriced_calls, 0);
    bars.push({
      key: "(more)",
      name: `${rest.length} more models`,
      sub: modelSub("", calls, rest.reduce((n, r) => n + r.cost_usd, 0), unpriced),
      tokens: rest.reduce((n, r) => n + r.total_tokens, 0),
      unpriced: unpriced > 0,
      folded: true,
      title: rest.map(r => `${String(r.model ?? "")} · ${tokens(r.total_tokens)}`).join("\n"),
    });
  }
  return bars;
}

// ── Where tokens go ─────────────────────────────────────────────────────────

export const FEATURE_LABEL: Record<CallerFeature, string> = {
  deep_analysis: "Deep analysis",
  conversation: "Conversation agent",
  survey: "Survey",
  exploration: "Exploration",
  sql_repair: "SQL repair",
  sql_writing: "Writing SQL",
  business_profile: "Business profile",
  semantic_layer: "Semantic layer",
  ontology: "Ontology",
};

export interface FeatureBar {
  key: string;
  label: string;
  calls: number;
  tokens: number;
  /** The call sites folded into this row, for its hover text. */
  sites: string[];
  /** "Other": what no feature names, and the rows past the top few. */
  other: boolean;
}

/** The window's tokens by what they were spent on. "Other" is the window's own total less the
 *  named rows — so call sites past the summary's top twelve are counted there, not lost. */
export function whereTokensGo(summary: UsageSummary, max = 5): FeatureBar[] {
  const groups = new Map<CallerFeature, FeatureBar>();
  const unnamed: string[] = [];
  for (const s of summary.sites) {
    const f = callerFeature(s.caller);
    if (!f) { unnamed.push(s.caller); continue; }
    const g = groups.get(f) ?? { key: f, label: FEATURE_LABEL[f], calls: 0, tokens: 0, sites: [], other: false };
    g.calls += s.calls;
    g.tokens += s.total_tokens;
    g.sites.push(s.caller);
    groups.set(f, g);
  }
  const named = [...groups.values()].sort((a, b) => b.tokens - a.tokens);
  const shown = named.length >= max ? named.slice(0, max - 1) : named;
  const folded = named.slice(shown.length);
  const calls = summary.calls - shown.reduce((n, g) => n + g.calls, 0);
  const left = summary.tokens - shown.reduce((n, g) => n + g.tokens, 0);
  const rows = [...shown];
  if (calls > 0 || left > 0) {
    rows.push({
      key: "(other)", label: "Other", calls: Math.max(0, calls), tokens: Math.max(0, left), other: true,
      sites: [...folded.flatMap(g => g.sites), ...unnamed],
    });
  }
  return rows;
}

// ── Governance, folded ──────────────────────────────────────────────────────

export type FoldTone = "amber" | "accent" | "green" | "plain";

export interface FeedFold {
  key: string;
  tone: FoldTone;
  title: string;
  sub: string;
  count: number;
  events: AuditFeedEvent[];
}

const words = (s: string) => s.replace(/[._-]+/g, " ").trim();
const detail = (e: AuditFeedEvent) => (e.detail ?? {}) as Record<string, unknown>;

/** A governed action's id in a reader's words: `x.resolve_case` → "resolve case",
 *  `ontology.override` → "ontology override". */
export function actionWords(action: string): string {
  const i = action.indexOf(".");
  const rest = i < 0 ? action : action.slice(i + 1);
  return rest.includes("_") ? words(rest) : words(action);
}

/** An internal probe the platform runs on its own data (`__brief_period__`, `__trust_coltypes__`):
 *  a flag on one of these is the platform talking to itself, and is said as such. */
const isPlatformRead = (e: AuditFeedEvent) => /^__\w+__$/.test(String(detail(e).hypothesis_id ?? ""));
const verdictOf = (e: AuditFeedEvent) => String(detail(e).verdict ?? "") || "unchecked";
/** A query guard's verdict as a reader says it: `suspicious` is "flagged". */
const verdictWords = (v: string) => (v === "suspicious" ? "flagged" : words(v));

/** The approval gate's decisions, grouped as a reader asks about them. A decision this table
 *  does not name is drawn amber with its own words: an unknown outcome is shown, not hidden. */
const DECISIONS: Record<string, { group: string; tone: FoldTone; one: string; many: string }> = {
  criterion_failed: { group: "check_failed", tone: "amber", one: "An action's check failed", many: "Action checks failed" },
  criterion_error: { group: "check_error", tone: "amber", one: "An action's check could not run", many: "Action checks could not run" },
  revoked: { group: "revoked", tone: "amber", one: "An approval was revoked", many: "Approvals were revoked" },
  blocked: { group: "blocked", tone: "amber", one: "An action needed approval", many: "Actions needed approval" },
  executed: { group: "executed", tone: "accent", one: "An action ran", many: "Actions ran" },
  approved: { group: "granted", tone: "green", one: "An approval was granted", many: "Approvals granted" },
  allowlisted: { group: "granted", tone: "green", one: "An approval was granted", many: "Approvals granted" },
  auto: { group: "auto", tone: "plain", one: "A low-risk action was let through", many: "Low-risk actions let through" },
  proposal_rejected: { group: "closed", tone: "plain", one: "A proposal was closed", many: "Proposals closed" },
  proposal_superseded: { group: "closed", tone: "plain", one: "A proposal was closed", many: "Proposals closed" },
  proposal_expired: { group: "closed", tone: "plain", one: "A proposal was closed", many: "Proposals closed" },
};

const TONE_RANK: Record<FoldTone, number> = { amber: 0, accent: 1, green: 2, plain: 3 };

/** Kinds of event the feed carries by an engineering name, said as a reader says them (one, many) — "Llm call" was
 *  the session log's `llm_call` with its first letter raised (theLook, 2026-10-12). */
const KIND_NAMES: Record<string, [string, string]> = {
  llm_call: ["A model call", "Model calls"],
  decision_replay: ["A decision kept for replay", "Decisions kept for replay"],
};

function distinct(xs: string[], max = 3): string {
  const seen = [...new Set(xs.filter(Boolean))];
  return seen.length > max ? `${seen.slice(0, max).join(", ")} +${seen.length - max}` : seen.join(", ");
}

/** The fetched window of governance events said once per kind of thing that happened, with a
 *  count, what needs a person first. `connName` names a connection id; an id it cannot name
 *  is left out of the line rather than printed raw. */
export function foldFeed(events: AuditFeedEvent[], connName: (id: string) => string | undefined): FeedFold[] {
  const folds = new Map<string, FeedFold>();
  const plural = new Map<string, string>();
  const add = (key: string, tone: FoldTone, one: string, many: string, e: AuditFeedEvent) => {
    const f = folds.get(key) ?? { key, tone, title: one, sub: "", count: 0, events: [] };
    f.count += 1;
    f.events.push(e);
    folds.set(key, f);
    plural.set(key, many);
  };
  const conns = (es: AuditFeedEvent[]) => distinct(es.map(e => connName(e.conn_id || String(detail(e).scope ?? "")) ?? ""), 2);

  for (const e of events) {
    const d = detail(e);
    if (e.kind === "query.execution") {
      add("query", "plain", "Query checks", "Query checks", e);
      const v = verdictOf(e);
      if (v !== "safe" && !isPlatformRead(e)) {
        add(`query_${v}`, "amber", `A query was ${verdictWords(v)}`, `Queries were ${verdictWords(v)}`, e);
      }
    } else if (e.kind === "action.approval") {
      const decision = String(d.decision ?? "");
      const known = DECISIONS[decision];
      if (known) add(`action_${known.group}`, known.tone, known.one, known.many, e);
      else add(`action_${decision}`, "amber", `Action ${words(decision) || "decision"}`, `Action ${words(decision) || "decisions"}`, e);
    } else if (e.kind === "mcp.tool_call") {
      if (d.allowed === false) add("mcp_refused", "amber", "An MCP agent was refused", "MCP agents were refused", e);
      else add("mcp", "plain", "Tool call from an MCP agent", "Tool calls from MCP agents", e);
    } else if (KIND_NAMES[e.kind]) {
      const [one, many] = KIND_NAMES[e.kind];
      add(`kind_${e.kind}`, e.category === "enforcement" ? "amber" : "plain", one, many, e);
    } else {
      const said = words(e.kind) || words(e.category);
      const title = said.charAt(0).toUpperCase() + said.slice(1);
      add(`kind_${e.kind}`, e.category === "enforcement" ? "amber" : "plain", title, title, e);
    }
  }

  for (const f of folds.values()) {
    if (f.count > 1) f.title = plural.get(f.key) ?? f.title;
    const es = f.events;
    if (f.key === "query") {
      // Safe, then the platform's own flagged reads named as noise, then every other verdict by its
      // own word — a blocked query is said, never folded into "safe".
      let own = 0;
      const byVerdict = new Map<string, number>();
      for (const e of es) {
        const v = verdictOf(e);
        if (v !== "safe" && isPlatformRead(e)) own += 1;
        else byVerdict.set(v, (byVerdict.get(v) ?? 0) + 1);
      }
      f.sub = [
        `${formatCount(byVerdict.get("safe") ?? 0)} safe`,
        own ? `${formatCount(own)} flagged were the platform's own reads` : "",
        ...[...byVerdict].filter(([v]) => v !== "safe").map(([v, n]) => `${formatCount(n)} ${verdictWords(v)}`),
      ].filter(Boolean).join(" · ");
    } else if (f.key.startsWith("action_")) {
      f.sub = [distinct(es.map(e => actionWords(String(detail(e).action ?? "")))), conns(es)].filter(Boolean).join(" · ");
    } else if (f.key.startsWith("mcp")) {
      const routes = distinct(es.map(e => words(String(detail(e).route ?? "").split("/").filter(Boolean).pop() ?? "")));
      f.sub = [routes, f.key === "mcp" ? "allowed" : "refused"].filter(Boolean).join(" · ");
    } else if (f.key.startsWith("query_")) {
      f.sub = conns(es);
    } else {
      f.sub = es[0]?.summary ?? "";
    }
  }

  return [...folds.values()]
    .sort((a, b) => TONE_RANK[a.tone] - TONE_RANK[b.tone] || b.count - a.count);
}

/** How far back a window of events reaches, from its oldest event to now: "last 90 minutes". */
export function sinceWords(events: AuditFeedEvent[], now = Date.now()): string {
  const times = events.map(e => Date.parse(e.at)).filter(t => !Number.isNaN(t));
  if (!times.length) return "";
  const minutes = Math.max(1, Math.round((now - Math.min(...times)) / 60_000));
  if (minutes < 20) return `last ${countNoun(minutes, "minute")}`;
  if (minutes < 120) return `last ${Math.round(minutes / 10) * 10} minutes`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `last ${hours} hours`;
  return `last ${Math.round(hours / 24)} days`;
}

/** An event's identity inside one fetched window — what "View" uses to show exactly its rows. */
export const eventKey = (e: AuditFeedEvent): string => `${e.at}|${e.kind}|${e.summary}`;

/** Arc TC, TC-5 — the day after a picked `YYYY-MM-DD`, so a "To" day is read inclusive by a feed
 *  whose `until` is exclusive. Computed on the calendar, never through a local clock. */
export function dayAfter(day: string): string {
  const [y, m, d] = day.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d + 1)).toISOString().slice(0, 10);
}
