/**
 * The six destinations (the 2027 study §U) — a destination is a question a person brings,
 * never a store the platform keeps. This file is the whole map: which pages each destination
 * holds, where each page lives in the shell's state, and which destination every tab id that
 * ever existed now opens — so a link saved in 2026 still opens, on the page that absorbed it.
 *
 * Pure on purpose: the shell reads it to draw the rail and the page row, and
 * `destinations.test.ts` reads it to hold the one promise a rearrangement can silently break —
 * that no id a person may have bookmarked resolves to nowhere.
 */

export type DestinationId = "now" | "inquiries" | "decisions" | "missions" | "record" | "operations";

/** Where a page lives in the shell: the tab that renders it and, for a workspace, the layer inside. */
export interface PageAt {
  tab: string;
  layer?: string;
}

export interface DestinationPage {
  id: string;
  label: string;
  /** One line for the tab's tooltip: what the page answers. */
  blurb: string;
  at: PageAt;
  /** Present only while this flag is on. */
  flag?: string;
}

export interface Destination {
  id: DestinationId;
  label: string;
  icon: string;
  /** The question a person brings here — the rail's tooltip. */
  question: string;
  pages: DestinationPage[];
}

export const DESTINATIONS: Destination[] = [
  {
    id: "now", label: "Now", icon: "home", question: "What needs me, this week?",
    pages: [
      { id: "now", label: "This week", blurb: "What used a slot, what waits on you, and what was held", at: { tab: "now" } },
      { id: "briefing", label: "Briefing", blurb: "What moved in the range, why, and what is being done", at: { tab: "intelligence", layer: "briefing" } },
    ],
  },
  {
    id: "inquiries", label: "Inquiries", icon: "search", question: "Why is this happening?",
    pages: [
      { id: "inquiries", label: "Inquiries", blurb: "What is established, what is open and what would settle it", at: { tab: "inquiries" } },
      { id: "runs", label: "Runs", blurb: "Every analysis that ran, with how it ended", at: { tab: "recents" } },
      { id: "health", label: "Health", blurb: "The scorecard of each process", at: { tab: "health" } },
    ],
  },
  {
    id: "decisions", label: "Decisions", icon: "scales", question: "What are we choosing, and what did we choose?",
    pages: [
      { id: "decisions", label: "Decisions", blurb: "What was chosen, what was expected and what became of it", at: { tab: "decisions" } },
      { id: "proposed", label: "Proposed", blurb: "Recommendations waiting for a person to accept or reject", at: { tab: "inbox" } },
    ],
  },
  {
    id: "missions", label: "Missions", icon: "compass", question: "What are we continuously trying to achieve?",
    pages: [
      { id: "missions", label: "Missions", blurb: "Each objective against its baseline, and what it cost", at: { tab: "missions" } },
      { id: "monitors", label: "Monitors", blurb: "The metric watches a mission reads", at: { tab: "operations", layer: "monitors" } },
      { id: "cockpits", label: "Cockpits", blurb: "The cards a person keeps watching", at: { tab: "intelligence", layer: "cockpit" }, flag: "cockpit.composed" },
    ],
  },
  {
    id: "record", label: "Record", icon: "layers", question: "What do we hold true, and what have we learned?",
    pages: [
      { id: "claims", label: "Claims", blurb: "What is held true about a thing, as of any date", at: { tab: "record" } },
      { id: "corrections", label: "Corrections", blurb: "What the platform was wrong about, and what replaced it", at: { tab: "corrections" } },
      { id: "definitions", label: "Definitions", blurb: "Metrics, entities and the glossary, with their versions", at: { tab: "data", layer: "semantic" } },
      { id: "catalog", label: "Catalog", blurb: "Tables, schemas and profiles", at: { tab: "data", layer: "catalog" } },
      { id: "map", label: "Map", blurb: "Types, links, processes, promises and rules", at: { tab: "intelligence", layer: "ontology" } },
      { id: "graph", label: "Graph", blurb: "The connection's knowledge graph", at: { tab: "intelligence", layer: "graph" } },
      { id: "profile", label: "Profile", blurb: "What the data is, by domain", at: { tab: "intelligence", layer: "hub" } },
      { id: "evidence", label: "Evidence", blurb: "Findings and the feedback on them", at: { tab: "intelligence", layer: "evidence" } },
      { id: "memory", label: "Memory", blurb: "What the closed loop has learned", at: { tab: "intelligence", layer: "memory" } },
      { id: "org", label: "Organisation", blurb: "What holds across connections", at: { tab: "intelligence", layer: "org" } },
      { id: "brain", label: "Brain map", blurb: "Every store behind the Record, with live counts", at: { tab: "intelligence", layer: "brain" } },
      { id: "documents", label: "Documents", blurb: "The authored material the platform reasons with", at: { tab: "documents" } },
      { id: "canvases", label: "Canvases", blurb: "A working view over a set of tables", at: { tab: "canvases" } },
    ],
  },
  {
    id: "operations", label: "Operations", icon: "process", question: "What is the system doing, and what may it do?",
    pages: [
      { id: "work", label: "Work", blurb: "The week by duty: what ran, what failed and how, what it cost", at: { tab: "work" } },
      { id: "action-centre", label: "Action centre", blurb: "Every kind of action, the level it may run at, and its record", at: { tab: "action-centre" } },
      { id: "agents", label: "Agents", blurb: "Each agent's runs, quality and setup", at: { tab: "agentic-ops" } },
      { id: "integrations", label: "Integrations", blurb: "Connect Google, Slack and Microsoft", at: { tab: "operations", layer: "integrations" } },
      { id: "notifications", label: "Notifications", blurb: "Webhook, Slack and Jira triggers", at: { tab: "operations", layer: "actions" } },
      { id: "spend", label: "Spend", blurb: "Usage, caps and the governance feed", at: { tab: "operations", layer: "spend" } },
      { id: "audit", label: "Audit", blurb: "Access, sensitive data and the audit trail", at: { tab: "operations", layer: "security" } },
      { id: "evals", label: "Evals", blurb: "Suites, runs and experiments", at: { tab: "evals" } },
      { id: "sql", label: "SQL editor", blurb: "Inspect and correct a statement", at: { tab: "data", layer: "query" } },
      { id: "admin", label: "Admin", blurb: "Every door and what guards it, policies, groups and settings", at: { tab: "admin" } },
      { id: "developer", label: "Developer", blurb: "Packs, doors, principals, kits and the agent contract", at: { tab: "developer" } },
    ],
  },
];

/** A working surface with no page of its own in a row — it still belongs to a destination,
 *  so the rail says where the reader is. `chat` is Ask, which is a bar and belongs to none. */
const SURFACE_OF: Record<string, DestinationId> = {
  "canvas-workspace": "record",
  playbook: "record",
  metrics: "record",
};

export interface Location {
  destination: Destination | null;
  page: DestinationPage | null;
}

/** Which destination and page the shell is showing, from its tab and that tab's layer. */
export function locate(tab: string, layer?: string | null): Location {
  let onTab: { destination: Destination; page: DestinationPage } | null = null;
  for (const destination of DESTINATIONS) {
    for (const page of destination.pages) {
      if (page.at.tab !== tab) continue;
      if (page.at.layer === undefined || page.at.layer === layer) return { destination, page };
      onTab ??= { destination, page };
    }
  }
  const surface = SURFACE_OF[tab];
  if (surface) return { destination: DESTINATIONS.find(d => d.id === surface) ?? null, page: null };
  // A workspace on a layer no page names (a stale `?layer=`) still belongs to a destination.
  return onTab ? { destination: onTab.destination, page: null } : { destination: null, page: null };
}

export function destination(id: DestinationId): Destination {
  return DESTINATIONS.find(d => d.id === id)!;
}

/** The pages of a destination a reader can open now — a flagged page only while its flag is on. */
export function pagesOf(d: Destination, flags: Record<string, boolean> = {}): DestinationPage[] {
  return d.pages.filter(p => !p.flag || flags[p.flag]);
}

/**
 * Tab ids from 2026 that no longer name a screen of their own, and the page each now opens.
 * `resolveLegacy` is applied before anything else reads a tab id, on every path a link can
 * arrive by (a cold load, a navigate event, Back).
 */
const RETIRED: Record<string, PageAt & { was: string }> = {
  home: { tab: "now", was: "Home" },
  settings: { tab: "admin", was: "Settings" },
};

export function resolveLegacy(tab: string): PageAt | null {
  const r = RETIRED[tab];
  return r ? { tab: r.tab, layer: r.layer } : null;
}

/**
 * What to say, once, when a saved link opens the page that absorbed its screen. Keyed by the
 * id the link carried; absent for an id whose screen is still where it was.
 */
const MOVED_FROM: Record<string, string> = {
  home: "Home",
  settings: "Settings",
  inbox: "The Inbox",
  recents: "Agent runs",
  health: "Health",
  intelligence: "The Briefing",
  briefing: "The Briefing",
  monitors: "Monitors",
  catalog: "The Catalog",
  semantic: "The Semantic Layer",
  builder: "The SQL editor",
  query: "The SQL editor",
  documents: "Documents",
  canvases: "The Data Canvas",
  ontology: "The Ontology",
  "agentic-ops": "Agent Ops",
  actions: "Notifications",
  integrations: "Integrations",
  spend: "Spend",
  security: "Security & Audit",
  activity: "The audit log",
  evals: "Evals",
};

/** "The Inbox is now Decisions ▸ Proposed." — or null when the link's screen did not move. */
export function movedNotice(linkTab: string, at: Location): string | null {
  // An older alias of a screen (several ids once opened Agent Ops) is told by where it landed.
  const was = MOVED_FROM[linkTab] ?? MOVED_FROM[at.page?.at.tab ?? ""];
  if (!was || !at.destination) return null;
  const where = at.page && at.page.label !== at.destination.label
    ? `${at.destination.label} ▸ ${at.page.label}` : at.destination.label;
  return `${was} is now ${where}.`;
}
