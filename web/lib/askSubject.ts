"use client";

/**
 * Arc FA-2 — what a question is about, carried from a dashboard to the Data Canvas in memory, never in the address.
 *
 * A reader ticks objects in a table, or asks about the set a piece reads; the piece keeps the subject here and asks the
 * shell for the Data Canvas (`requestTab`, which carries the connection and nothing else). The canvas shows the subject
 * above its input, with a way to take it off, and sends it as the turn's `focus`; the server reads it again through the
 * object door under the reader's row policy and says what it read on the turn's receipt. No key rides a query string.
 */
import { useSyncExternalStore } from "react";

import { plural, typeWord } from "@/lib/dashboards/objectView";
import { formatCount } from "@/lib/format";
import { requestTab } from "@/lib/navigate";

/** The most objects one subject names — the server's own bound, and a press's (`MAX_TICKED_RUNS`). */
export const MAX_SUBJECT = 50;

interface Common {
  /** The connection the subject was chosen on: a canvas on another one does not send it. */
  connectionId: string;
  /** How its objects are called, one and many: ["order", "orders"]. */
  noun: [string, string];
}
export type AskSubject =
  | Common & { kind: "objects"; refs: string[]; label?: string }
  | Common & { kind: "set"; dashboard: string; owner?: string; set: string; label: string; total?: number | null;
      values: Record<string, unknown>; chosen: Record<string, string>; filters: Record<string, unknown>[]; narrowed: boolean }
  // a segment the ontology names, read by a piece directly — sent with the conditions the piece reads it under
  | Common & { kind: "segment"; entity: string; segment: string; label: string; total?: number | null;
      filters: Record<string, unknown>[]; narrowed: boolean };

let current: AskSubject | null = null;
const listeners = new Set<() => void>();

export function askSubject(): AskSubject | null {
  return current;
}

export function setAskSubject(next: AskSubject | null): void {
  current = next;
  for (const l of listeners) l();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

export function useAskSubject(): AskSubject | null {
  return useSyncExternalStore(subscribe, askSubject, () => null);
}

/** Keep the subject and open the Data Canvas on its connection. */
export function askAbout(subject: AskSubject): void {
  setAskSubject(subject);
  requestTab("chat", { conn: subject.connectionId });
}

/** How a type's objects are called, from the type the object door names: ["order", "orders"]. */
export function nounOf(typeId: string | null | undefined): [string, string] {
  const one = typeWord(typeId).toLowerCase() || "object";
  return [one, plural(one)];
}

/** The subject in a line, as the canvas shows it: "Asking about 12 orders · from Late dispatch". */
export function subjectWords(s: AskSubject): string {
  if (s.kind === "objects") {
    const n = s.refs.length;
    return `Asking about ${formatCount(n)} ${n === 1 ? s.noun[0] : s.noun[1]}${s.label ? ` · from ${s.label}` : ""}`;
  }
  const held = s.total == null ? "" : ` · ${formatCount(s.total)} ${s.total === 1 ? s.noun[0] : s.noun[1]}`;
  return `Asking about ${s.label}${held}${s.narrowed ? " · narrowed by your filters" : ""}`;
}

/** The subject as the ask door takes it (`AskFocus`): references, or a dashboard's set by name with the values and the
 *  objects chosen on the page and the reader's own filters — never what the set reads. */
export function focusOf(s: AskSubject): Record<string, unknown> {
  if (s.kind === "objects") return { kind: "objects", objects: s.refs.slice(0, MAX_SUBJECT), ...(s.label ? { label: s.label.slice(0, 80) } : {}) };
  if (s.kind === "segment") return { kind: "set", entity: s.entity, segment: s.segment, label: s.label.slice(0, 80),
    filters: s.filters.slice(0, 20), narrowed: s.narrowed };
  return { kind: "set", dashboard: s.dashboard, ...(s.owner ? { owner: s.owner } : {}), set: s.set, values: s.values,
    chosen: s.chosen, filters: s.filters.slice(0, 20) };
}

/** The dashboard a page's key names — `<connection>:<id>`, its builder preview `…:preview`, or another person's
 *  published one `shared:<owner>:<id>` — or null when it names none a server could read a set from. */
export function dashboardOf(key: string | undefined, connectionId: string): { dashboard: string; owner?: string } | null {
  if (!key) return null;
  let rest = key.startsWith(`${connectionId}:`) ? key.slice(connectionId.length + 1) : key;
  if (rest.endsWith(":preview")) rest = rest.slice(0, -":preview".length);
  let owner: string | undefined;
  if (rest.startsWith("shared:")) {
    const inner = rest.slice("shared:".length);
    const at = inner.lastIndexOf(":");
    if (at <= 0) return null;
    owner = inner.slice(0, at);
    rest = inner.slice(at + 1);
  } else if (!key.startsWith(`${connectionId}:`)) {
    return null;
  }
  return /^[a-z0-9][a-z0-9-]{0,47}$/.test(rest) ? { dashboard: rest, ...(owner ? { owner } : {}) } : null;
}
