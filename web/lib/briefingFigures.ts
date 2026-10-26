/**
 * Which figures a reader keeps on the Briefing's front, which read under the desk by area, and which they hide (the
 * user, 2026-10-26: "how can a user choose what appears in the briefing and what not?" and "the longer the list gets the
 * lower Trends and Gaps get… no point having a structure which doesn't adapt"; design-mockups/briefing-figures.html).
 *
 * The front holds six figures beside the lead, so Trends · Gaps · Decide stay where they are at any count. Every other
 * figure reads in "Every figure, by area" under the desk; a figure whose data ended is one line per day it stopped; a
 * figure that cannot be measured keeps its reason in plain view. A Briefing whose figures all fit on the front reads
 * exactly as before. Kept per reader, per dataset (`briefing_figures` in the person's preferences, beside the
 * Briefing's switches); what is measured is the platform's.
 */
import type { PaperNumber } from "@/components/brief/BriefPaper";

/** The figures the front holds — `BRIEFING_FRONT_MAX` in `aughor/db/user_prefs.py`. */
export const FRONT_MAX = 6;
export const PREF_KEY = "briefing_figures";

export interface FigureChoice { front: string[]; hidden: string[] }
export type FiguresPref = Record<string, FigureChoice>;
export type Place = "front" | "below" | "hidden";

/** A dataset's key in the preference: the connection, and the dataset when one is in view. */
export const scopeKey = (connectionId: string, schema?: string | null) => (schema ? `${connectionId}:${schema}` : connectionId);

/** A figure's identity: its metric's name — what a choice names — else the row's own key. */
export const idOf = (r: PaperNumber) => r.metric ?? r.key;

const names = (v: unknown) => (Array.isArray(v) ? v.filter((n): n is string => typeof n === "string" && !!n.trim()) : []);

export function normalizeFigures(raw: unknown): FiguresPref {
  const out: FiguresPref = {};
  if (!raw || typeof raw !== "object") return out;
  for (const [scope, choice] of Object.entries(raw as Record<string, unknown>)) {
    const c = (choice && typeof choice === "object" ? choice : {}) as { front?: unknown; hidden?: unknown };
    const hidden = names(c.hidden);
    const front = names(c.front).filter(n => !hidden.includes(n)).slice(0, FRONT_MAX);
    if (front.length || hidden.length) out[scope] = { front, hidden };
  }
  return out;
}

export function choiceFor(pref: FiguresPref, scope: string): FigureChoice {
  return pref[scope] ?? { front: [], hidden: [] };
}

export interface Arranged {
  front: PaperNumber[];
  /** The measured figures not on the front, by area, in reading order. */
  below: { area: string; rows: PaperNumber[] }[];
  /** Figures that cannot be measured, not on the front: each with its reason. */
  blanks: PaperNumber[];
  /** Figures whose data ended before the range, not on the front, by the day each stopped. */
  stopped: { day: string; rows: PaperNumber[] }[];
  hidden: PaperNumber[];
  /** True when every figure fits on the front and nothing was chosen — the Briefing reads exactly as it did. */
  fits: boolean;
}

const measured = (r: PaperNumber) => !r.unknown;

/** The front as chosen — the reader's figures, in their order — else the first six figures that have a value. */
function frontOf(rows: PaperNumber[], choice: FigureChoice): PaperNumber[] {
  const visible = rows.filter(r => !choice.hidden.includes(idOf(r)));
  if (choice.front.length) {
    const by = new Map(visible.map(r => [idOf(r), r]));
    return choice.front.map(id => by.get(id)).filter((r): r is PaperNumber => !!r);
  }
  return visible.filter(measured).slice(0, FRONT_MAX);
}

export function arrange(rows: PaperNumber[], choice: FigureChoice): Arranged {
  const chosen = choice.front.length > 0 || choice.hidden.length > 0;
  if (!chosen && rows.length <= FRONT_MAX) {
    return { front: rows, below: [], blanks: [], stopped: [], hidden: [], fits: true };
  }
  const front = frontOf(rows, choice);
  const onFront = new Set(front.map(idOf));
  const hidden = rows.filter(r => choice.hidden.includes(idOf(r)));
  const rest = rows.filter(r => !onFront.has(idOf(r)) && !choice.hidden.includes(idOf(r)));
  const below: Arranged["below"] = [];
  for (const r of rest.filter(measured)) {
    const area = r.area || "Other figures";
    const group = below.find(g => g.area === area);
    if (group) group.rows.push(r); else below.push({ area, rows: [r] });
  }
  const stopped: Arranged["stopped"] = [];
  for (const r of rest.filter(x => x.unknown && x.ended)) {
    const day = r.ends ?? "";
    const group = stopped.find(g => g.day === day);
    if (group) group.rows.push(r); else stopped.push({ day, rows: [r] });
  }
  stopped.sort((a, b) => (a.day < b.day ? -1 : a.day > b.day ? 1 : 0));
  return { front, below, blanks: rest.filter(x => x.unknown && !x.ended), stopped, hidden, fits: false };
}

/** Where one figure stands for this reader. */
export function placeOf(rows: PaperNumber[], choice: FigureChoice, id: string): Place {
  if (choice.hidden.includes(id)) return "hidden";
  return frontOf(rows, choice).some(r => idOf(r) === id) ? "front" : "below";
}

/** The choice with one figure moved. Choosing a front writes down the front as it reads, so moving one figure never
 *  reshuffles the rest, and a full front takes no seventh. Hiding a figure while the front is still the default lets
 *  the next figure take its place. */
export function moved(rows: PaperNumber[], choice: FigureChoice, id: string, to: Place): FigureChoice {
  const explicit = choice.front.length > 0;
  let front = (explicit ? choice.front : frontOf(rows, choice).map(idOf)).filter(n => n !== id);
  const hidden = choice.hidden.filter(n => n !== id);
  if (to === "front") {
    if (front.length >= FRONT_MAX) return choice;
    front.push(id);
  }
  if (to === "hidden") {
    hidden.push(id);
    if (!explicit) front = [];
  }
  return { front, hidden };
}

/** The preference with one dataset's choice replaced — an empty choice is dropped. */
export function withChoice(pref: FiguresPref, scope: string, choice: FigureChoice): FiguresPref {
  const next = { ...pref };
  if (choice.front.length || choice.hidden.length) next[scope] = choice; else delete next[scope];
  return next;
}
