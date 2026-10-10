/**
 * The process designer's draft — what a person is designing, in their own words, and the declaration it becomes.
 *
 * The walk-through of 2026-10-09 typed "Delivery time", stages "Shipped" and "Delivered", and the old form's button
 * stayed disabled with no reason: it wanted snake_case. Here a person names things in words; the ids are made from them
 * (`idFrom`), each unique where it must be, and a draft that cannot be counted yet always says why (`notReady`) — never
 * a disabled button with nothing beside it.
 */
import type { DeclaredProcessSpec, ProcessDetail } from "@/lib/objectTypes";

export type Anchor =
  | { kind: "moment"; path: string }
  | { kind: "state"; property: string; values: string[] };

export type PromiseDraft =
  | { kind: "days" | "hours"; amount: string; name: string; target: string }
  | { kind: "deadline"; deadline: string; name: string; target: string };

export interface StageDraft {
  label: string;
  anchor: Anchor | null;
  promise: PromiseDraft | null;
  /** A declared stage's own name, kept while it is changed — renaming one renames everything it derives. */
  id?: string;
}

/** A move a person expects between two stages, by the stages' names, or out of the process (`to: "left"`). */
export interface MoveDraft {
  from: string;
  to: string;
}

export interface ProcessDraft {
  name: string;
  entity: string;
  owner: string;
  description: string;
  stages: StageDraft[];
  leaves: { property: string; values: string[] } | null;
  /** The questions a person answered "they really are late" to, by check id. */
  late: string[];
  /** Arc OC-5 — the moves a person declared as expected; null: each stage to the next (none declared). */
  moves?: MoveDraft[] | null;
  /** Set while a declared process is changed: its id never changes. */
  id?: string;
}

/** The word a move's `to` uses for leaving the process. */
export const LEFT = "left";

export const EMPTY_STAGE: StageDraft = { label: "", anchor: null, promise: null };

export function emptyDraft(entity = ""): ProcessDraft {
  return { name: "", entity, owner: "", description: "", stages: [{ ...EMPTY_STAGE }, { ...EMPTY_STAGE }], leaves: null, late: [],
           moves: null };
}

/** The stage's name as the declaration writes it: a declared stage keeps its own. */
export function stageId(s: StageDraft): string {
  return s.id || idFrom(s.label);
}

function percent(target: number | null): string {
  return target == null ? "" : String(Math.round(target * 1000) / 10);
}

/** A declared process as a draft to change — every stage keeping its name, so nothing it derives is renamed. */
export function draftFromProcess(p: ProcessDetail): ProcessDraft {
  return {
    id: p.id, name: p.display_name, entity: p.entity_id, owner: p.owner, description: p.description, late: [],
    stages: p.stages.map(s => {
      const anchor: Anchor = "timestamp" in s.anchor ? { kind: "moment", path: s.anchor.timestamp }
        : { kind: "state", property: s.anchor.property, values: [...s.anchor.state] };
      const q = s.promise;
      const promise: PromiseDraft | null = !q ? null : q.kind === "deadline"
        ? { kind: "deadline", deadline: q.deadline, name: q.name, target: percent(q.target) }
        : { kind: q.kind === "within_hours" ? "hours" : "days", name: q.name, target: percent(q.target),
            amount: String((q.kind === "within_hours" ? q.within_hours : q.within_days) ?? "") };
      return { id: s.name, label: s.display_name || s.name, anchor, promise };
    }),
    leaves: p.leaves ? { property: p.leaves.property, values: [...p.leaves.values] } : null,
    moves: p.transitions?.length ? p.transitions.map(t => ({ from: t.from_stage, to: t.to_stage })) : null,
  };
}

/** A lower-case id made from a person's words: "Delivery time" → `delivery_time`, "2-day dispatch" → `p_2_day_dispatch`. */
export function idFrom(words: string): string {
  const base = words.normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase()
    .replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 60);
  if (!base) return "";
  return /^[a-z]/.test(base) ? base : `p_${base}`.slice(0, 64);
}

/** ``base``, or ``base_2``, ``base_3``… — the first not taken. */
export function freshId(base: string, taken: Iterable<string>): string {
  const held = new Set(taken);
  if (!held.has(base)) return base;
  let n = 2;
  while (held.has(`${base}_${n}`)) n += 1;
  return `${base}_${n}`;
}

/** A new cockpit's id, as the server makes one (`cockpit.home.new_id`): the name in lower-case words joined by hyphens,
 *  then six random hex characters — a cockpit id is `[a-z0-9][a-z0-9-]{0,47}`, and keeping a spec under an id a person
 *  already has would add a version to THAT cockpit, so the suffix is random, never counted. */
export function cockpitIdFor(name: string, random: () => string = randomHex): string {
  const slug = name.normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLowerCase()
    .replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 32).replace(/-+$/, "") || "cockpit";
  return `${slug}-${random()}`;
}

function randomHex(): string {
  try { return crypto.randomUUID().replace(/-/g, "").slice(0, 6); } catch { return Math.random().toString(16).slice(2, 8).padEnd(6, "0"); }
}

/** Why the draft cannot be counted yet, in words — "" when it can. */
export function notReady(d: ProcessDraft): string {
  if (!d.name.trim()) return "Name the process.";
  if (!idFrom(d.name)) return "Give the process a name with at least one letter or digit.";
  if (!d.entity) return "Choose what moves through the process.";
  if (d.stages.length < 2) return "A process has at least two stages.";
  for (let i = 0; i < d.stages.length; i++) {
    const s = d.stages[i];
    const which = s.label.trim() || `stage ${i + 1}`;
    if (!s.label.trim() || !idFrom(s.label)) return `Name stage ${i + 1}.`;
    if (!s.anchor) return `Choose when an object reaches ${which}.`;
    if (s.anchor.kind === "state" && !s.anchor.values.length) return `Choose the ${s.anchor.property} values that place an object in ${which}.`;
    const p = s.promise;
    if (!p) continue;
    if (p.kind !== "deadline") {
      if (i === 0) return `${which} is the first stage — there is no stage before it to count a promise from.`;
      if (d.stages[i - 1].anchor?.kind !== "moment") return `${which}'s promise counts from the stage before it, which is reached by a status and has no moment to count from.`;
      if (s.anchor.kind !== "moment") return `${which} is reached by a status, which has no moment — a promise needs the moment an object reaches the stage.`;
      if (!/^\d+$/.test(p.amount.trim()) || Number(p.amount) < (p.kind === "hours" ? 1 : 0)) return `Say how many ${p.kind} the promise on ${which} allows.`;
    } else {
      if (s.anchor.kind !== "moment") return `${which} is reached by a status, which has no moment to compare with a deadline.`;
      if (!p.deadline) return `Choose the deadline the promise on ${which} is kept by.`;
    }
    if (p.target.trim() && !(Number(p.target) > 0 && Number(p.target) <= 100)) return `The target on ${which} is a percentage above 0, at most 100.`;
  }
  const ids = d.stages.map(stageId);
  const twice = ids.find((id, i) => ids.indexOf(id) !== i);
  if (twice) return `Two stages are named alike (${twice}) — name each stage differently.`;
  const gone = (d.moves ?? []).find(m => !ids.includes(m.from) || ![...ids, LEFT].includes(m.to));
  if (gone) return `A move you expect names a stage that is not here (${gone.from} → ${gone.to}) — mark the moves again.`;
  return "";
}

/** The declaration a ready draft becomes — ids made from the words, the words kept as the names a reader sees. */
export function toSpec(d: ProcessDraft, takenIds: Iterable<string> = []): DeclaredProcessSpec {
  const id = d.id || freshId(idFrom(d.name), takenIds);
  const spec: DeclaredProcessSpec = {
    id, display_name: d.name.trim(), entity: d.entity,
    ...(d.owner.trim() ? { owner: d.owner.trim() } : {}),
    ...(d.description.trim() ? { description: d.description.trim() } : {}),
    stages: d.stages.map(s => {
      const anchor = s.anchor;
      const base = { name: stageId(s), display_name: s.label.trim() };
      const at = !anchor ? {} : anchor.kind === "moment" ? { timestamp: anchor.path }
        : { property: anchor.property, state: [...anchor.values] };
      const p = s.promise;
      if (!p) return { ...base, ...at };
      const target = p.target.trim() ? { target: Math.round(Number(p.target) * 10) / 1000 } : {};
      const named = p.name.trim() && idFrom(p.name) ? { name: idFrom(p.name) } : {};
      const terms = p.kind === "deadline" ? { deadline: p.deadline }
        : p.kind === "hours" ? { within_hours: Number(p.amount) } : { within_days: Number(p.amount) };
      return { ...base, ...at, promise: { ...named, ...terms, ...target } };
    }),
    ...(d.leaves && d.leaves.values.length ? { leaves: { property: d.leaves.property, values: [...d.leaves.values] } } : {}),
    ...(d.moves && d.moves.length ? { transitions: d.moves.map(m => ({ from: m.from, to: m.to })) } : {}),
  };
  return spec;
}

// ── a draft kept in this browser — a convenience, never the record ───────────────────────────────────────────────────

const KEY = (connectionId: string, schema?: string) => `aughor:process-draft:${connectionId}:${schema ?? ""}`;

export function keepDraft(connectionId: string, schema: string | undefined, d: ProcessDraft): boolean {
  try { localStorage.setItem(KEY(connectionId, schema), JSON.stringify(d)); return true; } catch { return false; }
}

export function keptDraft(connectionId: string, schema?: string): ProcessDraft | null {
  try {
    const raw = localStorage.getItem(KEY(connectionId, schema));
    if (!raw) return null;
    const d = JSON.parse(raw) as ProcessDraft;
    return d && Array.isArray(d.stages) ? { ...emptyDraft(), ...d } : null;
  } catch { return null; }
}

export function dropDraft(connectionId: string, schema?: string): void {
  try { localStorage.removeItem(KEY(connectionId, schema)); } catch { /* nothing kept, nothing to drop */ }
}


/** The moves a draft declares after a person marks ``move`` expected or not: the moves the data shows as declared
 *  (none declared: each stage to the next) are the starting set, so the first mark keeps the rest as they read. */
export function toggledMoves(d: ProcessDraft, shown: { from_stage: string; to_stage: string; declared: boolean }[],
                             move: MoveDraft, expected: boolean): MoveDraft[] {
  const start = d.moves ?? shown.filter(m => m.declared).map(m => ({ from: m.from_stage, to: m.to_stage }));
  const rest = start.filter(m => !(m.from === move.from && m.to === move.to));
  return expected ? [...rest, move] : rest;
}
