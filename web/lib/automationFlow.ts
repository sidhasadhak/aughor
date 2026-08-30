/**
 * B1 — the draft as a flow: typed ports, and connections that ARE bindings.
 *
 * Pure on purpose (the `TraceFlow` lesson, twice proven): ReactFlow inside jsdom
 * renders zero edges no matter what it is given, so everything a test must catch has
 * to live in functions that never mount a canvas. This module owns the mapping both
 * ways — draft → nodes/edges for drawing, and a dragged connection → a
 * `{"$from": "alias.key"}` binding written into the draft.
 *
 * **A port is the vocabulary, drawn.** The server declares what each effect kind
 * publishes (`/automations/vocabulary`, the same `PUBLISHED_KEYS` `validate_chain`
 * refuses against) and which fields may bind. An output dot exists because the key
 * does; an input dot exists because the dispatcher reads that field. Nothing here
 * invents a port the engine would not honour — the Langflow look on Aughor's law.
 */
import type { AutoCondition, AutoEffect } from "@/lib/api";

export interface KindVocabulary {
  /** Keys this kind publishes into the chain context. `null` = an OPEN set
   *  (the declared-action kind — that action's own outcome shape). */
  publishes: string[] | null;
  /** Config fields a `{"$from": …}` binding may land on. */
  bindable: string[];
}
export type Vocabulary = Record<string, KindVocabulary>;

export interface Draft {
  conditions: AutoCondition[];
  effects: AutoEffect[];
}

/** A step's name: its own alias, else its 1-based position — the server's rule. */
export function aliasFor(e: AutoEffect, index: number): string {
  return e.alias || `step${index + 1}`;
}

function bindingRef(value: unknown): string | null {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    const keys = Object.keys(value as object);
    if (keys.length === 1 && keys[0] === "$from") {
      return String((value as Record<string, unknown>)["$from"]);
    }
  }
  return null;
}

export interface FlowStep {
  alias: string;
  index: number;
  kind: string;
  config: Record<string, unknown>;
  /** Output ports. `["*"]` renders the open set as one wildcard port. */
  publishes: string[];
  openSet: boolean;
  /** Input ports, each with what it is currently bound to (or null). */
  inputs: { field: string; boundTo: string | null }[];
}

export interface FlowEdgeSpec {
  from: string;        // producer alias
  key: string;         // published key the edge carries
  to: string;          // consumer alias
  field: string;       // consumer config field
}

/**
 * The design, as steps-with-ports and the edges its bindings already are.
 *
 * Derived from the DRAFT — the one departure from "the server owns the graph", and a
 * deliberate one: an editor that cannot show your unsaved edit is not an editor. The
 * server stays the authority for EXECUTION (a run decorated with truth); this is the
 * design being edited, drawn from the same object the Save button will send.
 */
export function draftToFlow(draft: Draft, vocab: Vocabulary): {
  steps: FlowStep[]; edges: FlowEdgeSpec[];
} {
  const steps: FlowStep[] = draft.effects.map((e, i) => {
    const v = vocab[e.kind] ?? { publishes: [], bindable: [] };
    const inputs = (v.bindable ?? []).map(field => ({
      field,
      boundTo: bindingRef((e.config ?? {})[field]),
    }));
    return {
      alias: aliasFor(e, i),
      index: i,
      kind: e.kind,
      config: (e.config ?? {}) as Record<string, unknown>,
      publishes: v.publishes === null ? ["*"] : v.publishes,
      openSet: v.publishes === null,
      inputs,
    };
  });

  const known = new Map(steps.map(s => [s.alias, s]));
  const edges: FlowEdgeSpec[] = [];
  for (const s of steps) {
    for (const inp of s.inputs) {
      if (!inp.boundTo) continue;
      const dot = inp.boundTo.indexOf(".");
      if (dot <= 0) continue;
      const from = inp.boundTo.slice(0, dot);
      if (!known.has(from)) continue;  // validate_chain refuses these at save; do not draw a lie
      edges.push({ from, key: inp.boundTo.slice(dot + 1), to: s.alias, field: inp.field });
    }
  }
  return { steps, edges };
}

/**
 * A dragged connection becomes a binding — or a sentence explaining why not.
 *
 * The refusals mirror `validate_chain`'s, deliberately: what the canvas refuses at
 * drag time and what the server refuses at save must be the same law, or the canvas
 * teaches a rule the engine does not have. Returns a NEW draft; never mutates.
 */
export function applyConnect(draft: Draft, vocab: Vocabulary, c: {
  fromAlias: string; key: string; toAlias: string; field: string;
}): { draft: Draft; error: string } {
  const aliases = draft.effects.map((e, i) => aliasFor(e, i));
  const fromIdx = aliases.indexOf(c.fromAlias);
  const toIdx = aliases.indexOf(c.toAlias);
  if (fromIdx < 0 || toIdx < 0) return { draft, error: "unknown step" };
  if (fromIdx === toIdx) return { draft, error: "a step cannot bind to itself" };
  if (fromIdx > toIdx) {
    return { draft, error: `${c.toAlias} runs before ${c.fromAlias} — a chain cannot run backwards` };
  }
  const producer = draft.effects[fromIdx];
  const declared = vocab[producer.kind]?.publishes;
  if (declared !== null && declared !== undefined && !declared.includes(c.key)) {
    return { draft, error: `a ${producer.kind} step has no '${c.key}'` };
  }
  const consumer = draft.effects[toIdx];
  const bindable = vocab[consumer.kind]?.bindable ?? [];
  if (!bindable.includes(c.field)) {
    return { draft, error: `${consumer.kind} does not read '${c.field}'` };
  }
  const effects = draft.effects.map((e, i) =>
    i === toIdx
      ? { ...e, config: { ...e.config, [c.field]: { $from: `${c.fromAlias}.${c.key}` } } }
      : e);
  return { draft: { ...draft, effects }, error: "" };
}

/** Remove one binding — the field goes back to plain (empty) text. */
export function clearBinding(draft: Draft, toAlias: string, field: string): Draft {
  const effects = draft.effects.map((e, i) => {
    if (aliasFor(e, i) !== toAlias) return e;
    const config = { ...e.config };
    if (bindingRef(config[field]) !== null) config[field] = "";
    return { ...e, config };
  });
  return { ...draft, effects };
}
