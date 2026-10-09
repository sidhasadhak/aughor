/**
 * The action designer's draft — an action as a person decides it, in their own words, and the declaration it becomes.
 *
 * The walk-through of 2026-10-09 (job 2) found one form of fourteen inputs and seven dropdowns mixing the business
 * decision with a webhook, a free-text box for what the action is about, and three fields pre-filled with someone
 * else's refund rule. Here the decision comes first — what it is about, what a press does, what the person pressing it
 * says, when it may be pressed, who decides — and a call to another system is its own step, only when the action makes
 * one. Ids are made from the words (`idFrom`), and a draft that cannot be read yet always says why (`notReady`).
 */
import { DEEP_ANALYSIS_EFFECT } from "@/lib/api";
import type { DeclaredActionSpec } from "@/lib/objectTypes";
import { freshId, idFrom } from "@/lib/processDraft";

export type AskType = "text" | "number" | "yes_no" | "date";

/** Something the person pressing the action is asked for. */
export interface AskDraft {
  label: string;
  type: AskType;
  required: boolean;
}

/** One condition a press must meet: a property of the object, holding (or not holding) one of the values chosen. */
export interface ConditionDraft {
  property: string;
  label: string;
  negate: boolean;
  values: string[];
  /** What the person is told when it refuses — "" for the sentence made from the condition. */
  message: string;
}

/** A call to another system — a developer's step, only for an action that makes one. */
export interface CallDraft {
  method: "POST" | "PUT" | "PATCH" | "GET" | "DELETE";
  url: string;
  authHeader: string;
  secret: string;
  body: string;
  /** The read that proves the call took effect, over the action's answers (`{reason}`). */
  check: string;
  expects: "rows" | "no_rows";
  /** `irreversible`, or the declared action that takes it back. */
  undo: "irreversible" | "action";
  undoAction: string;
  undoHours: string;
}

export interface ActionDraft {
  name: string;
  description: string;
  /** The type the action is about (a type map row's `object_type`), and what a reader calls it. */
  entity: string;
  entityLabel: string;
  /** What a press does: marks the object, tells a saved destination, starts a deep analysis, or calls a system. */
  does: "mark" | "tell" | "analyse" | "call";
  mark: { label: string; value: string; noteFrom: string };
  /** A destination saved in Notifications, by id, and the message it gets — answers in braces (`{reason}`). */
  tell: { destination: string; message: string };
  /** The question the deep analysis asks — answers in braces. */
  analysis: { question: string };
  asks: AskDraft[];
  conditions: ConditionDraft[];
  approval: boolean;
  call: CallDraft;
}

export const EMPTY_CALL: CallDraft = {
  method: "POST", url: "", authHeader: "", secret: "", body: "", check: "", expects: "rows",
  undo: "irreversible", undoAction: "", undoHours: "",
};

export function emptyAction(entity = "", entityLabel = ""): ActionDraft {
  return {
    name: "", description: "", entity, entityLabel, does: "mark",
    mark: { label: "", value: "yes", noteFrom: "reason" },
    tell: { destination: "", message: "" },
    analysis: { question: "" },
    asks: [{ label: "Reason", type: "text", required: true }],
    conditions: [], approval: false, call: { ...EMPTY_CALL },
  };
}

const TYPES: Record<AskType, string> = { text: "VARCHAR", number: "NUMERIC", yes_no: "BOOLEAN", date: "DATE" };

/** "an order", "a shipment" — how a sentence names one object of the type. */
export function oneOf(label: string): string {
  const word = (label || "object").toLowerCase();
  return `${/^[aeiou]/.test(word) ? "an" : "a"} ${word}`;
}

/** The sentence a condition is refused with when the person wrote none. */
export function conditionMessage(c: ConditionDraft, d: Pick<ActionDraft, "name" | "entityLabel">): string {
  if (c.message.trim()) return c.message.trim();
  const values = c.values.length > 1 ? `${c.values.slice(0, -1).join(", ")} or ${c.values[c.values.length - 1]}` : c.values[0] ?? "";
  return `${d.name.trim() || "This action"} is only for ${oneOf(d.entityLabel)} whose ${c.label.toLowerCase()} is ${c.negate ? "not " : ""}${values}.`;
}

/** The parameter the object a press is on arrives as — named after the type, never like one of the answers asked. */
export function subjectName(d: ActionDraft): string {
  const base = idFrom(d.entityLabel || d.entity) || "object";
  return d.asks.some(a => idFrom(a.label) === base) ? `${base}_object` : base;
}

const literal = (v: string) => JSON.stringify(v);

/** Why the draft cannot be read yet, in words — "" when it can. */
export function notReady(d: ActionDraft): string {
  if (!d.name.trim()) return "Name the action.";
  if (!idFrom(d.name)) return "Give the action a name with at least one letter or digit.";
  if (!d.entity) return "Choose what the action is about.";
  const asked = d.asks.map(a => idFrom(a.label));
  for (let i = 0; i < d.asks.length; i++) {
    if (!d.asks[i].label.trim() || !asked[i]) return `Name question ${i + 1}, or take it off.`;
  }
  const twice = asked.find((id, i) => asked.indexOf(id) !== i);
  if (twice) return `Two questions are named alike (${twice}) — name each differently.`;
  for (let i = 0; i < d.conditions.length; i++) {
    const c = d.conditions[i];
    if (!c.values.length) return `Choose the ${c.label.toLowerCase()} values condition ${i + 1} allows, or take it off.`;
  }
  if (d.does === "mark") {
    if (!d.mark.label.trim() || !idFrom(d.mark.label)) return `Name the mark a press leaves on ${oneOf(d.entityLabel)}.`;
    if (!d.mark.value.trim()) return "Say what the mark reads once it is set.";
    if (d.mark.noteFrom && !asked.includes(d.mark.noteFrom)) return "The mark's note is kept from a question the action no longer asks.";
    return "";
  }
  if (d.does === "tell") {
    if (!d.tell.destination) return "Choose who is told — a destination saved in Notifications.";
    if (!d.tell.message.trim()) return "Write the message they get.";
    return "";
  }
  if (d.does === "analyse") {
    if (!d.analysis.question.trim()) return "Write the question the deep analysis asks.";
    return "";
  }
  const c = d.call;
  if (!/^https:\/\/\S+$/.test(c.url.trim())) return "Give the address the call is sent to — it begins https://.";
  if (c.body.trim()) {
    try { JSON.parse(c.body); } catch { return "The message sent is not valid JSON."; }
  }
  if (c.secret && !c.authHeader.trim()) return "Name the header the credential is sent in.";
  if (!c.check.trim()) return "Say how to check the call worked — a read that finds a row once it has.";
  if (c.undo === "action" && !c.undoAction.trim()) return "Choose the action that takes the call back, or say it cannot be taken back.";
  return "";
}

/** The declaration a ready draft becomes, under an id made from its name that no declared action holds. ``undoTakes`` is
 *  what the action that takes a call back asks for: each is answered from this action's answer of the same name. */
export function toActionSpec(d: ActionDraft, takenIds: Iterable<string> = [], undoTakes: string[] = []): { id: string; spec: DeclaredActionSpec } {
  const id = freshId(idFrom(d.name), takenIds);
  const who = subjectName(d);
  const spec: DeclaredActionSpec = {
    display_name: d.name.trim(),
    ...(d.description.trim() ? { description: d.description.trim() } : {}),
    kind: d.does === "mark" ? "annotate" : "side_effect",
    risk: d.approval ? "high" : "low",
    object_type: d.entity,
    params: [
      { name: who, display_name: d.entityLabel || d.entity, kind: "object", object_type: d.entity },
      ...d.asks.map(a => ({ name: idFrom(a.label), display_name: a.label.trim(), kind: "value" as const,
                             data_type: TYPES[a.type], required: a.required })),
    ],
    submission_criteria: d.conditions.map(c => ({
      expr: `${who}.${c.property} ${c.negate ? "not in" : "in"} [${c.values.map(literal).join(", ")}]`,
      message: conditionMessage(c, d),
    })),
  };
  if (d.does === "mark") {
    spec.edits = [{ object: who, property: idFrom(d.mark.label), value: d.mark.value.trim(),
                    note: d.mark.noteFrom ? `{${d.mark.noteFrom}}` : "" }];
    return { id, spec };
  }
  // A message and a deep analysis are the platform's own to perform and record: the record proves them, and neither
  // can be taken back — a message cannot be unsent, an analysis's model calls cannot be unspent.
  if (d.does === "tell") {
    spec.side_effects = [{ kind: "notify", config: { destination: d.tell.destination, message: d.tell.message.trim() } }];
    spec.reversibility = "irreversible";
    return { id, spec };
  }
  if (d.does === "analyse") {
    spec.side_effects = [{ kind: DEEP_ANALYSIS_EFFECT, config: { question: d.analysis.question.trim() } }];
    spec.reversibility = "irreversible";
    return { id, spec };
  }
  const c = d.call;
  spec.side_effects = [{ kind: "http", config: {
    method: c.method, url: c.url.trim(),
    ...(c.body.trim() ? { body: JSON.parse(c.body) } : {}),
    ...(c.authHeader.trim() ? { auth_header: c.authHeader.trim() } : {}),
    ...(c.secret ? { auth_secret: c.secret } : {}),
  } }];
  spec.verification = { sql: c.check.trim(), expects: c.expects };
  if (c.undo === "irreversible") spec.reversibility = "irreversible";
  else {
    spec.reversibility = "compensable";
    const ours = new Set(spec.params.map(p => p.name));
    const params = Object.fromEntries(undoTakes.filter(n => ours.has(n)).map(n => [n, `{${n}}`]));
    spec.undo = { action_id: c.undoAction.trim(), window_hours: Number(c.undoHours) || 0, ...(Object.keys(params).length ? { params } : {}) };
  }
  return { id, spec };
}

// ── a draft kept in this browser — a convenience, never the record ───────────────────────────────────────────────────

const KEY = (connectionId: string, schema?: string) => `aughor:action-draft:${connectionId}:${schema ?? ""}`;

export function keepAction(connectionId: string, schema: string | undefined, d: ActionDraft): boolean {
  // The credential is never kept in the browser: a draft is a convenience, and a key in localStorage is a key leaked.
  try { localStorage.setItem(KEY(connectionId, schema), JSON.stringify({ ...d, call: { ...d.call, secret: "" } })); return true; } catch { return false; }
}

export function keptAction(connectionId: string, schema?: string): ActionDraft | null {
  try {
    const raw = localStorage.getItem(KEY(connectionId, schema));
    if (!raw) return null;
    const d = JSON.parse(raw) as ActionDraft;
    const empty = emptyAction();
    return d && Array.isArray(d.asks) && Array.isArray(d.conditions)
      ? { ...empty, ...d, call: { ...EMPTY_CALL, ...d.call }, tell: { ...empty.tell, ...d.tell },
          analysis: { ...empty.analysis, ...d.analysis } }
      : null;
  } catch { return null; }
}

export function dropAction(connectionId: string, schema?: string): void {
  try { localStorage.removeItem(KEY(connectionId, schema)); } catch { /* nothing kept, nothing to drop */ }
}
