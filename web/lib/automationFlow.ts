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
import type { AutoCondition, AutoEffect, GuardClause, GuardOp } from "@/lib/api";

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

/** W1 — every `alias.key` an EARLIER step publishes, for a guard's subject picker.
 *
 * Open-set producers (the declared-action kind, `publishes: null`) contribute nothing:
 * their keys are that action's own outcome shape, which no client can enumerate, and a
 * picker cannot honestly offer a name it does not know. The wire still accepts such a
 * guard — the model is more expressive than this form, which is the right way round.
 */
/** A guard as sentences, for a node face. Pure — the same reason everything else in
 *  this module is: jsdom draws no edges, so what a test can catch has to live outside
 *  the canvas. Operator WORDS come from the server's vocabulary, never a local map. */
export function guardSentences(clauses: GuardClause[], ops: GuardOp[]): string[] {
  const label = new Map(ops.map(o => [o.op, o.label]));
  const unary = new Set(ops.filter(o => o.unary).map(o => o.op));
  const side = (v: unknown): string => {
    const ref = bindingRef(v);
    if (ref !== null) return ref;
    // An empty literal must still occupy the sentence — the server's renderer says the
    // same thing the same way, so a node and a run cannot word one guard differently.
    if (v === null || v === undefined) return "nothing";
    return v === "" ? '""' : String(v);
  };
  return clauses.map(c => {
    const word = label.get(c.op) ?? c.op;
    return unary.has(c.op)
      ? `${side(c.left)} ${word}`
      : `${side(c.left)} ${word} ${side(c.right)}`;
  });
}

export function upstreamKeys(effects: AutoEffect[], index: number, vocab: Vocabulary):
    { ref: string; alias: string; key: string }[] {
  const out: { ref: string; alias: string; key: string }[] = [];
  effects.slice(0, index).forEach((e, i) => {
    for (const key of vocab[e.kind]?.publishes ?? []) {
      const alias = aliasFor(e, i);
      out.push({ ref: `${alias}.${key}`, alias, key });
    }
  });
  return out;
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
  /** W1 — this step's guard. A node that omits it draws a step that always runs. */
  when: GuardClause[];
  whenLogic: "all" | "any";
  /** W2 — how this step's fan-out READS ("EMEA, NA" or "rows.items"), or "" when it
   *  runs exactly once. A node that omits it draws one send where N happen. */
  forEach: string;
  /** W2 — the reference a BOUND fan-out reads, for the edge it draws. */
  forEachRef: string | null;
}

export interface FlowEdgeSpec {
  from: string;        // producer alias
  key: string;         // published key the edge carries
  to: string;          // consumer alias
  field: string;       // consumer config field, or GUARD_FIELD
  /** W1 — this edge feeds the step's guard: it DECIDES whether the step runs rather
   *  than filling one of its fields. Drawn to the node's own guard port. */
  guard?: boolean;
  /** W2 — this edge carries the LIST the step runs once per item of. */
  fan?: boolean;
}

/** The pseudo-field a guard edge lands on. Not a config key — the guard is not one. */
export const GUARD_FIELD = "__guard";

/** W2 — the pseudo-field a fan-out's SOURCE edge lands on. A list is not a config field
 *  either: it decides how many times the step runs, not what one run says. */
export const FAN_FIELD = "__for_each";

/** W2 — a fan-out as one line on a node face.
 *
 * Mirrors the server's `graph.fan_label` because the design canvas draws the UNSAVED
 * draft and the server has not seen it yet — the same departure B1 made for ports. Only
 * the FORMATTING lives in two places; the law (what may be fanned over) stays the
 * server's, fetched, and is mirrored nowhere.
 */
export function fanLabel(source: unknown): string {
  if (source === null || source === undefined) return "";
  const ref = bindingRef(source);
  if (ref !== null) return ref;
  if (!Array.isArray(source)) return "";
  const scalars = source.filter(i => typeof i !== "object" || i === null);
  if (scalars.length !== source.length) return `${source.length} items`;
  const shown = scalars.slice(0, 3).map(i => String(i).slice(0, 24));
  const more = scalars.length - shown.length;
  return shown.join(", ") + (more ? ` +${more} more` : "");
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
      when: e.when ?? [],
      whenLogic: e.when_logic ?? "all",
      forEach: fanLabel(e.for_each?.source),
      forEachRef: bindingRef(e.for_each?.source),
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
    // W1 — a guard reads the chain exactly as a param does, so it draws. The server's
    // graph does the same from `effect_refs`; the design canvas derives from the DRAFT
    // and must not be the one reader that omits it.
    for (const clause of s.when) {
      for (const side of [clause.left, clause.right]) {
        const ref = bindingRef(side);
        if (!ref) continue;
        const dot = ref.indexOf(".");
        if (dot <= 0 || !known.has(ref.slice(0, dot))) continue;
        edges.push({ from: ref.slice(0, dot), key: ref.slice(dot + 1), to: s.alias,
                     field: GUARD_FIELD, guard: true });
      }
    }
    // W2 — a fan-out's source is dataflow too. The server derives it from the same
    // `effect_refs` as everything else; the canvas that omitted it would draw a step
    // running once from nothing.
    if (s.forEachRef) {
      const dot = s.forEachRef.indexOf(".");
      const from = s.forEachRef.slice(0, dot);
      if (dot > 0 && known.has(from)) {
        edges.push({ from, key: s.forEachRef.slice(dot + 1), to: s.alias,
                     field: FAN_FIELD, fan: true });
      }
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

/* ── DS-4 · duplicating and pasting a step ──────────────────────────────────────
 *
 * The sharp edge in this whole wave. A step's name is POSITIONAL — `aliasFor` derives
 * `step3` from where it sits — while every binding is a STRING naming another step
 * (`{"$from": "step1.answer"}`). So a copy carries references that mean "whatever is in
 * that position", and pasted somewhere else they quietly mean something different.
 *
 * `validate_chain` cannot save us here: it refuses an UNKNOWN step and a FORWARD one, and
 * a ref that now resolves to a *different* existing step is neither. The save succeeds,
 * the canvas draws a confident edge, and at 09:00 a Slack message carries another step's
 * answer. That is the worst failure this plane can produce — a well-formed wrong result —
 * so the rule is: **a reference whose producer is not present and upstream is DROPPED,
 * never repointed**, and the caller is told which ones went.
 */

/** Every alias in use, by the same rule the server names steps. */
function aliasesOf(effects: AutoEffect[]): Set<string> {
  return new Set(effects.map((e, i) => aliasFor(e, i)));
}

/**
 * A free name for a step landing at `index`.
 *
 * An explicit alias is dropped rather than uniquified: `numbers` copied beside `numbers`
 * is a collision, and `numbers-2` is a name the person never chose and would have to
 * rename anyway. The copy takes its positional name — unless something else has already
 * claimed that exact string as an explicit alias, in which case a suffix is the honest
 * way out of a name that is genuinely taken.
 */
function freeAlias(taken: Set<string>, index: number): string | undefined {
  const positional = `step${index + 1}`;
  if (!taken.has(positional)) return undefined;   // undefined = let it default
  let n = 2;
  while (taken.has(`${positional}-${n}`)) n += 1;
  return `${positional}-${n}`;
}

export interface PasteResult {
  draft: Draft;
  /** What was cut loose, in the words the surface uses — for a sentence, not a log. */
  dropped: string[];
}

/**
 * Append a copy of `step`, keeping every reference that still means what it meant and
 * dropping every one that does not.
 *
 * Appending is what makes the surviving references safe: a step at the END has every
 * other step upstream of it, so a ref that resolves at all resolves to the same producer
 * it named in the original. The item alias survives only alongside the `for_each` that
 * defines it — a per-iteration name means nothing without the iteration, and it is passed
 * in rather than spelled here because the server owns that reserved word.
 */
export function pasteEffect(
  draft: Draft, step: AutoEffect, itemAlias: string,
): PasteResult {
  const taken = aliasesOf(draft.effects);
  const index = draft.effects.length;
  const dropped: string[] = [];

  const resolves = (ref: string | null, hasFan: boolean): boolean => {
    if (!ref) return true;                       // not a reference at all
    const dot = ref.indexOf(".");
    if (dot <= 0) return false;
    const from = ref.slice(0, dot);
    if (from === itemAlias) return hasFan;       // only meaningful inside its own fan-out
    return taken.has(from);
  };

  // The fan source first: whether it survives decides whether `item.…` means anything.
  let forEach = step.for_each;
  if (forEach && !resolves(bindingRef(forEach.source), false)) {
    forEach = undefined;
    dropped.push("for each");
  }
  const hasFan = !!forEach;

  const config: Record<string, unknown> = {};
  for (const [field, value] of Object.entries(step.config ?? {})) {
    const ref = bindingRef(value);
    if (ref && !resolves(ref, hasFan)) {
      config[field] = "";                        // the field stays, its wiring does not
      dropped.push(field);
      continue;
    }
    config[field] = value;
  }

  // A guard with a dangling side cannot be evaluated, and half a comparison is not a
  // weaker guard — it is a different one. The clause goes.
  const when = (step.when ?? []).filter(clause => {
    const ok = resolves(bindingRef(clause.left), hasFan)
      && resolves(bindingRef(clause.right), hasFan);
    if (!ok) dropped.push("only if");
    return ok;
  });

  const copy: AutoEffect = {
    ...step,
    alias: freeAlias(taken, index),
    config,
    ...(when.length ? { when } : { when: undefined }),
    for_each: forEach,
  };
  return { draft: { ...draft, effects: [...draft.effects, copy] }, dropped };
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


/* ── DS-1 · placing what the palette hands over ──────────────────────────────────
 *
 * Both halves live here rather than in the canvas for this module's standing reason:
 * jsdom measures every element as 0×0 and draws no edges, so anything a test must be
 * able to catch has to be a function that never mounts a canvas. Placement arithmetic
 * is exactly that kind of thing — it is wrong by a viewport, silently, and a screenshot
 * is the only other way to see it.
 */

/** The config a brand-new row of `kind` starts with.
 *
 * Derived from `AUTOMATION_REQUIRED_KEYS` rather than written per kind: the server
 * validates required config keys at CONSTRUCTION, so a default that omits one is a 422
 * the moment it is saved, and a hand-written default per kind is one more place for that
 * to be got wrong. Empty strings are deliberate — `missingKeys` then reports the row as
 * incomplete on screen, which is the honest state of a step nobody has filled in yet.
 *
 * `schedule` is the one seeded with a real value: a cron is the only required key in this
 * plane that has a sensible default, and shipping it keeps "Add Trigger" one click from a
 * valid automation, exactly as it was before the palette existed.
 */
const KIND_SEED: Record<string, Record<string, unknown>> = {
  schedule: { cron: "0 9 * * *" },
};

export function seedConfig(
  kind: string, required: Record<string, string[]>,
): Record<string, unknown> {
  const blanks = Object.fromEntries((required[kind] ?? []).map(k => [k, ""]));
  return { ...blanks, ...(KIND_SEED[kind] ?? {}) };
}

/**
 * DS-4 · what a declared-action step has actually been seen to publish.
 *
 * The declared-action kind's published keys are an OPEN set — `PUBLISHED_KEYS` says
 * `null` because the keys are that action's own outcome shape, which no client can
 * enumerate. Until now the canvas asked for the key with a `window.prompt`, which is
 * both homely and blind: a typo produces an edge the run then skips.
 *
 * The honest source is the run itself. The server already computes each node's
 * `produced` from the real `EffectOutcome.data` and ships it on the execution graph, so
 * the keys a step HAS published are known — no ontology build, no second contract. A
 * step that has never run contributes nothing, which is exactly when the free-text tail
 * is the only honest offer.
 */
export function producedByAlias(
  graph: { nodes: { id: string; produced?: string[] }[] } | null | undefined,
): Record<string, string[]> {
  const out: Record<string, string[]> = {};
  for (const node of graph?.nodes ?? []) {
    const keys = (node.produced ?? []).filter(Boolean);
    if (keys.length) out[node.id] = [...new Set(keys)].sort();
  }
  return out;
}

/**
 * DS-4 · the arrangement to persist: only steps that still exist, at whole pixels.
 *
 * Pruning is the half that rots silently. A step removed from the chain — or one dropped
 * from the palette and then discarded — leaves a coordinate behind, and a layout that
 * only ever grows eventually opens a canvas carrying the ghosts of everything anyone
 * deleted. Rounding is smaller but the same idea: a drag ends on a subpixel, and storing
 * `312.7000000000001` puts noise in a row a person may one day read.
 */
export function layoutToPersist(
  positions: Record<string, { x: number; y: number }>, alive: Set<string>,
): Record<string, { x: number; y: number }> {
  // `Math.round(-0.4)` is `-0`, which survives into a stored coordinate as a signed zero
  // — harmless once JSON flattens it, and confusing to anyone who reads the row or
  // compares two layouts. Normalise it where it is made.
  const px = (n: number): number => (Math.round(n) === 0 ? 0 : Math.round(n));
  const out: Record<string, { x: number; y: number }> = {};
  for (const [alias, at] of Object.entries(positions)) {
    if (alive.has(alias)) out[alias] = { x: px(at.x), y: px(at.y) };
  }
  return out;
}

/* ── DS-3 · a run, while it is still running ────────────────────────────────────
 *
 * The engine writes two `session_events` rows per executed step — a `tool_call` on entry
 * and a `tool_call_result` on exit — committed as it goes, under `trace_id == run_id`.
 * That is the whole substrate: a run in flight is already legible, it simply had nothing
 * reading it. This turns those rows into a status per STEP.
 *
 * **Matched on the step's alias, never on ordinal position.** A step held by its guard, a
 * fan-out refused at save, an unresolved binding — each appends an outcome and emits no
 * span at all, so counting spans against effects puts every later status on the wrong
 * card. That is the same bug `group_outcomes` was written for on the server side.
 */

export type LiveStatus = "running" | "done" | "failed";

/** The fields this reads off a session event. Structural, so a test does not have to
 *  build a twenty-field row to assert one rule. */
export interface LiveEvent {
  kind: string;
  span_id: string | null;
  ok: boolean | null;
  payload: Record<string, unknown> | null;
}

/** A fanned step emits one span per ITEM, labelled `alias[1/3]`. They are all the one
 *  node, so the suffix comes off before anything is counted. */
function baseAlias(step: string): string {
  const bracket = step.indexOf("[");
  return bracket > 0 ? step.slice(0, bracket) : step;
}

/**
 * What each step is doing right now.
 *
 * A step is `running` while any of its spans has opened and not closed — which is what an
 * unpaired `tool_call` means, and why the engine emits the call before the work rather
 * than after. It is `failed` if any of its spans came back not-ok: one failed item of a
 * fan-out is a failure of that step, and averaging it away would draw a green card over a
 * message nobody received.
 */
export function liveStatuses(events: LiveEvent[]): Record<string, LiveStatus> {
  const spanStep = new Map<string, string>();
  const open = new Map<string, number>();
  const status: Record<string, LiveStatus> = {};

  for (const e of events) {
    const step = typeof e.payload?.step === "string" ? baseAlias(e.payload.step) : "";
    if (!step) continue;               // not an automation step span; nothing to place
    if (e.kind === "tool_call") {
      if (e.span_id) spanStep.set(e.span_id, step);
      open.set(step, (open.get(step) ?? 0) + 1);
      if (!status[step]) status[step] = "running";
    } else if (e.kind === "tool_call_result") {
      open.set(step, Math.max(0, (open.get(step) ?? 0) - 1));
      // A failure sticks: a later item succeeding does not un-fail the ones that did not.
      if (e.ok === false) status[step] = "failed";
      else if (status[step] !== "failed" && (open.get(step) ?? 0) === 0) {
        status[step] = "done";
      }
    }
  }

  // A step whose spans all closed while another was still open settles here rather than
  // being left mid-flight by the ordering of two rows written microseconds apart.
  for (const [step, still] of open) {
    if (still > 0 && status[step] !== "failed") status[step] = "running";
  }
  return status;
}

export interface Viewport { x: number; y: number; zoom: number }
export interface Size { width: number; height: number }

/**
 * Where a node dropped by a CLICK should land: the middle of what the reader is
 * currently looking at, in flow coordinates.
 *
 * ReactFlow's viewport is a pan/zoom transform over the flow plane, so the centre of the
 * pane in flow terms is `(-pan + half the pane) / zoom`. `nodeWidth` shifts the result
 * left by half a card so the node is centred on that point rather than starting at it —
 * without it a clicked node lands visibly right of centre, which reads as a bug and is
 * the kind of thing only a browser would have told us.
 *
 * A zero or missing zoom (a canvas that has not measured yet) falls back to 1: placing a
 * node at a plausible spot beats dividing by zero and putting it at infinity.
 */
export function viewportCenter(vp: Viewport, size: Size, nodeWidth = 0): { x: number; y: number } {
  const zoom = vp.zoom > 0 ? vp.zoom : 1;
  return {
    x: (-vp.x + size.width / 2) / zoom - nodeWidth / 2,
    y: (-vp.y + size.height / 2) / zoom,
  };
}
