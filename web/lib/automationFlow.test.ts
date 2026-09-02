/**
 * B1 — the draft⇄flow mapping, asserted where it can actually fail.
 *
 * Everything here is pure (the TraceFlow lesson: jsdom draws zero edges no matter
 * what a canvas is given), and the properties are the ones the canvas stakes its
 * honesty on: a port exists because the vocabulary says so, an edge exists because a
 * binding does, and a drag is refused by exactly the law `validate_chain` enforces
 * at save — the canvas must never teach a rule the engine does not have.
 */
import { describe, expect, it } from "vitest";

import {
  applyConnect, bindingRefs, clearBinding, draftToFlow, ELSE_FIELD, FAN_FIELD,
  GUARD_FIELD, guardSentences, aliasFor, layoutToPersist, liveStatuses, pasteEffect,
  producedByAlias, rootAliases, seedConfig, upstreamKeys, viewportCenter,
  visibleFields, type Vocabulary,
} from "@/lib/automationFlow";
import type { AutoEffect } from "@/lib/api";

const VOCAB: Vocabulary = {
  investigate: { publishes: ["investigation_id", "answer"], bindable: ["question"] },
  slack_post: { publishes: ["ts", "channel"], bindable: ["message", "thread_ts", "channel"] },
  notify: { publishes: [], bindable: ["message"] },
  kinetic_action: { publishes: null, bindable: ["params"] },
};

const eff = (kind: AutoEffect["kind"], config: Record<string, unknown> = {},
             alias = ""): AutoEffect => ({ kind, alias, config });

const draft = (...effects: AutoEffect[]) => ({ conditions: [], effects });

describe("draftToFlow", () => {
  it("draws a port per published key and per bindable field — the vocabulary, drawn", () => {
    const { steps } = draftToFlow(
      draft(eff("investigate", { question: "sales?" }, "numbers")), VOCAB);
    expect(steps[0].publishes).toEqual(["investigation_id", "answer"]);
    expect(steps[0].inputs.map(i => i.field)).toEqual(["question"]);
  });

  it("renders the open set as one wildcard port rather than none", () => {
    // The declared-action kind publishes that action's own outcome shape. No port
    // would say "publishes nothing", which is the opposite of the truth.
    const { steps } = draftToFlow(draft(eff("kinetic_action", { action_id: "a" })), VOCAB);
    expect(steps[0].publishes).toEqual(["*"]);
    expect(steps[0].openSet).toBe(true);
  });

  it("an edge exists because a binding does — and carries field and key", () => {
    const { edges } = draftToFlow(draft(
      eff("investigate", { question: "q" }, "numbers"),
      eff("slack_post", { channel: "#c", message: { $from: "numbers.answer" } }),
    ), VOCAB);
    expect(edges).toEqual([
      { from: "numbers", key: "answer", to: "step2", field: "message" },
    ]);
  });

  it("does not draw an edge from a step that does not exist", () => {
    // validate_chain refuses these at save; drawing one meanwhile would be a lie
    // with an arrowhead.
    const { edges } = draftToFlow(draft(
      eff("slack_post", { message: { $from: "ghost.answer" } }),
    ), VOCAB);
    expect(edges).toEqual([]);
  });
});

describe("applyConnect — the drag IS the binding, under the save-time law", () => {
  const base = draft(
    eff("investigate", { question: "q" }, "numbers"),
    eff("slack_post", { channel: "#c", message: "" }),
  );

  it("writes the binding into the consumer's config", () => {
    const r = applyConnect(base, VOCAB,
      { fromAlias: "numbers", key: "answer", toAlias: "step2", field: "message" });
    expect(r.error).toBe("");
    expect(r.draft.effects[1].config.message).toEqual({ $from: "numbers.answer" });
    // and never mutates — the original draft is what Discard restores
    expect(base.effects[1].config.message).toBe("");
  });

  it("refuses a backward drag with the chain's own sentence", () => {
    const r = applyConnect(base, VOCAB,
      { fromAlias: "step2", key: "ts", toAlias: "numbers", field: "question" });
    expect(r.error).toMatch(/cannot run backwards/);
    expect(r.draft).toBe(base);
  });

  it("refuses a key the producer kind cannot publish — validate_chain's rule, at drag time", () => {
    const r = applyConnect(base, VOCAB,
      { fromAlias: "numbers", key: "nonsense", toAlias: "step2", field: "message" });
    expect(r.error).toMatch(/has no 'nonsense'/);
  });

  it("accepts any key from an open-set producer", () => {
    const open = draft(
      eff("kinetic_action", { action_id: "a" }, "act"),
      eff("slack_post", { channel: "#c" }),
    );
    const r = applyConnect(open, VOCAB,
      { fromAlias: "act", key: "whatever_the_action_says", toAlias: "step2", field: "message" });
    expect(r.error).toBe("");
  });

  it("refuses a field the consumer does not read", () => {
    // An edge onto a field nothing reads is a picture of dataflow the engine does
    // not have — the decorative arrow VA-4b's docstring warned about.
    const r = applyConnect(base, VOCAB,
      { fromAlias: "numbers", key: "answer", toAlias: "step2", field: "subject" });
    expect(r.error).toMatch(/does not read 'subject'/);
  });

  it("refuses a self-binding", () => {
    const r = applyConnect(base, VOCAB,
      { fromAlias: "step2", key: "ts", toAlias: "step2", field: "message" });
    expect(r.error).toMatch(/itself/);
  });
});

describe("clearBinding", () => {
  it("returns the field to plain text and leaves everything else alone", () => {
    const d = draft(
      eff("investigate", { question: "q" }, "numbers"),
      eff("slack_post", { channel: "#c", message: { $from: "numbers.answer" } }),
    );
    const out = clearBinding(d, "step2", "message");
    expect(out.effects[1].config.message).toBe("");
    expect(out.effects[1].config.channel).toBe("#c");
    // a field that was NOT a binding is untouched — clearing must not blank prose
    const noop = clearBinding(d, "step2", "channel");
    expect(noop.effects[1].config.channel).toBe("#c");
  });
});

/* ── W1 · the guard ─────────────────────────────────────────────────────────── */

const OPS = [
  { op: "truthy", label: "is set", unary: true },
  { op: "gt", label: ">", unary: false },
];

describe("the guard, drawn", () => {
  it("draws a guard reference as an edge — onto the guard port, not a field", () => {
    // The engine follows this reference (`effect_refs`), so the picture must too. An
    // arrow the run takes and the canvas omits is the disagreement this module exists
    // to prevent — and it lands on the step's own guard port, because a guard DECIDES
    // whether the step runs rather than filling one of its fields.
    const { edges } = draftToFlow(draft(
      eff("investigate", { question: "sales?" }, "numbers"),
      { ...eff("slack_post", { channel: "#ops" }), when: [{ left: { $from: "numbers.answer" }, op: "truthy" }] },
    ), VOCAB);
    expect(edges).toEqual([
      { from: "numbers", key: "answer", to: "step2", field: GUARD_FIELD, guard: true },
    ]);
  });

  it("does not draw a guard onto a step that is not there", () => {
    // `validate_chain` refuses these at save; drawing one would be a picture of a
    // chain the engine would never run.
    const { edges } = draftToFlow(draft(
      { ...eff("slack_post", { channel: "#ops" }), when: [{ left: { $from: "ghost.answer" }, op: "truthy" }] },
    ), VOCAB);
    expect(edges).toEqual([]);
  });

  it("draws BOTH sides of a comparison between two steps", () => {
    const { edges } = draftToFlow(draft(
      eff("investigate", { question: "sales?" }, "a"),
      eff("slack_post", { channel: "#ops" }, "b"),
      { ...eff("notify", { trigger_id: "t" }), when: [{
        left: { $from: "a.answer" }, op: "gt", right: { $from: "b.ts" } }] },
    ), VOCAB);
    expect(edges.map(e => `${e.from}.${e.key}`)).toEqual(["a.answer", "b.ts"]);
  });

  it("carries the guard onto the step so a node can show it", () => {
    const { steps } = draftToFlow(draft(
      { ...eff("notify", { trigger_id: "t" }), when: [{ left: 1, op: "gt", right: 0 }],
        when_logic: "any" as const },
    ), VOCAB);
    expect(steps[0].when).toHaveLength(1);
    expect(steps[0].whenLogic).toBe("any");
  });
});

describe("guardSentences", () => {
  it("uses the SERVER's word for each operator, and a binding reads as its path", () => {
    expect(guardSentences([{ left: { $from: "step1.answer" }, op: "truthy" }], OPS))
      .toEqual(["step1.answer is set"]);
  });

  it("omits the right side for a unary operator rather than printing an empty one", () => {
    expect(guardSentences([{ left: { $from: "s.a" }, op: "truthy", right: "ignored" }], OPS))
      .toEqual(["s.a is set"]);
  });

  it("falls back to the raw operator when the vocabulary has not arrived yet", () => {
    // A page that renders before the fetch lands must say something true rather than
    // blank out the one line telling the reader the step is conditional.
    expect(guardSentences([{ left: { $from: "s.a" }, op: "gt", right: 5 }], []))
      .toEqual(["s.a gt 5"]);
  });
});

describe("upstreamKeys", () => {
  it("offers only what runs BEFORE this step — the rule validate_chain enforces", () => {
    const effects = [eff("investigate", {}, "a"), eff("slack_post", {}, "b"),
                     eff("notify", {}, "c")];
    expect(upstreamKeys(effects, 1, VOCAB).map(u => u.ref))
      .toEqual(["a.investigation_id", "a.answer"]);
    expect(upstreamKeys(effects, 0, VOCAB)).toEqual([]);
  });

  it("offers nothing for an open-set producer rather than inventing a key", () => {
    const effects = [eff("kinetic_action", {}, "act"), eff("notify", {}, "n")];
    expect(upstreamKeys(effects, 1, VOCAB)).toEqual([]);
  });
});

describe("a preview never wears a real run's words", () => {
  it("marks every node so a chip can say 'would run' instead of 'executed'", async () => {
    // The engine's honest word for a dry-run step is `executed` — it ran to completion,
    // through an inert dispatcher. On screen, under a banner reading "nothing was sent",
    // that is exactly the wrong word. Found by driving it.
    const { toFlow } = await import("@/components/AutomationGraph");
    const { nodes } = toFlow({
      nodes: [{ id: "s1", type: "effect", label: "s1", status: "executed" }],
      edges: [], mode: "execution", dry_run: true,
    });
    expect(nodes[0].data.dryRun).toBe(true);
  });

  it("leaves a REAL run's nodes unmarked", async () => {
    const { toFlow } = await import("@/components/AutomationGraph");
    const { nodes } = toFlow({
      nodes: [{ id: "s1", type: "effect", label: "s1", status: "executed" }],
      edges: [], mode: "execution",
    });
    expect(nodes[0].data.dryRun).toBe(false);
  });
});

describe("one arrow per claim, not per reference", () => {
  it("draws a key bound BOTH as a field and in a guard exactly once", async () => {
    // `build_graph` reports both — they are different claims about the chain — but an
    // execution edge has no per-field handle to land on, so the two are one arrow drawn
    // twice under one id. React logged a duplicate-key error; found by driving it.
    const { toFlow } = await import("@/components/AutomationGraph");
    const { edges } = toFlow({
      nodes: [{ id: "numbers", type: "effect", label: "numbers" },
              { id: "step2", type: "effect", label: "step2" }],
      edges: [
        { from: "numbers", to: "step2", type: "data", label: "answer", guard: false },
        { from: "numbers", to: "step2", type: "data", label: "answer", guard: true },
      ],
      mode: "execution",
    });
    expect(edges).toHaveLength(1);
    expect(new Set(edges.map(e => e.id)).size).toBe(edges.length);
  });

  it("keeps two edges when they carry DIFFERENT keys", async () => {
    const { toFlow } = await import("@/components/AutomationGraph");
    const { edges } = toFlow({
      nodes: [{ id: "a", type: "effect", label: "a" }, { id: "b", type: "effect", label: "b" }],
      edges: [
        { from: "a", to: "b", type: "data", label: "answer" },
        { from: "a", to: "b", type: "data", label: "investigation_id" },
      ],
      mode: "execution",
    });
    expect(edges).toHaveLength(2);
  });
});

/**
 * W2 — the fan-out, in the same mapping.
 *
 * A step that runs once per item is a DESIGN fact: a canvas that omitted it would draw
 * one send where N happen. Its source is dataflow like any binding, so a bound source
 * draws an edge — to a port of its own, because a list decides how many times a step
 * runs rather than filling one of its fields.
 */
describe("for_each", () => {
  const fanned = (source: unknown, alias = "posts"): AutoEffect => ({
    kind: "slack_post", alias,
    config: { channel: "#ops", message: { $from: "item.value" } },
    for_each: { source },
  });

  it("labels a literal list by its items — the author typed them", () => {
    const { steps } = draftToFlow(draft(fanned(["EMEA", "NA"])), VOCAB);
    expect(steps[0].forEach).toBe("EMEA, NA");
    expect(steps[0].forEachRef).toBeNull();
  });

  it("counts a long list instead of spelling it out", () => {
    const { steps } = draftToFlow(draft(fanned(["a", "b", "c", "d", "e"])), VOCAB);
    expect(steps[0].forEach).toBe("a, b, c +2 more");
  });

  it("counts dict items rather than rendering their fields — a payload is not a label", () => {
    const { steps } = draftToFlow(draft(fanned([{ region: "EMEA" }, { region: "NA" }])), VOCAB);
    expect(steps[0].forEach).toBe("2 items");
  });

  it("draws a bound source as an edge to the fan port", () => {
    const { steps, edges } = draftToFlow(
      draft(eff("kinetic_action", { action_id: "a1" }, "rows"),
            fanned({ $from: "rows.items" })), VOCAB);
    expect(steps[1].forEach).toBe("rows.items");
    const fan = edges.filter(e => e.fan);
    expect(fan).toHaveLength(1);
    expect(fan[0]).toMatchObject({ from: "rows", key: "items", to: "posts",
                                   field: FAN_FIELD });
  });

  it("draws no fan edge for a literal list — there is no upstream to point at", () => {
    const { edges } = draftToFlow(draft(fanned(["EMEA"])), VOCAB);
    expect(edges.filter(e => e.fan)).toHaveLength(0);
  });

  it("says nothing about a step that runs once", () => {
    const { steps } = draftToFlow(draft(eff("slack_post", { channel: "#ops" })), VOCAB);
    expect(steps[0].forEach).toBe("");
  });

  it("does not mistake the item reference for a chain edge", () => {
    // `item.value` is resolved per ITERATION against the item, not against a step. An
    // edge from a step called "item" would be a picture of dataflow that does not exist.
    const { edges } = draftToFlow(draft(fanned(["EMEA"])), VOCAB);
    expect(edges.some(e => e.from === "item")).toBe(false);
  });
});

/* ── DS-1 · what the palette places, and where ─────────────────────────────── */

describe("seedConfig", () => {
  const REQUIRED = {
    schedule: ["cron"], metric: ["monitor_id"],
    slack_post: ["bot_id", "channel"], investigate: ["question"],
  };

  it("seeds every key the save REQUIRES, so a placed step is never missing one", () => {
    // The server validates required config keys at construction: a default that omits
    // one is a 422 the moment it is saved, from a row the reader did nothing wrong to.
    expect(Object.keys(seedConfig("slack_post", REQUIRED)).sort()).toEqual(["bot_id", "channel"]);
  });

  it("leaves them empty so the row reports itself incomplete", () => {
    // `missingKeys` reads blank required keys and marks the row — which is the honest
    // state of a step nobody has filled in yet. Inventing a plausible value would hide it.
    expect(seedConfig("investigate", REQUIRED)).toEqual({ question: "" });
  });

  it("keeps a schedule one click from valid", () => {
    expect(seedConfig("schedule", REQUIRED)).toEqual({ cron: "0 9 * * *" });
  });

  it("returns an empty config for a kind that requires nothing", () => {
    expect(seedConfig("brief", REQUIRED)).toEqual({});
  });
});

describe("viewportCenter", () => {
  it("puts a clicked node in the middle of what the reader is looking at", () => {
    // Pan 0, zoom 1: the centre of an 800×400 pane is (400, 200) in flow terms.
    expect(viewportCenter({ x: 0, y: 0, zoom: 1 }, { width: 800, height: 400 }))
      .toEqual({ x: 400, y: 200 });
  });

  it("reads the pan back out", () => {
    // Panned right by 200, the same screen centre is 200 further into the flow plane.
    expect(viewportCenter({ x: -200, y: -100, zoom: 1 }, { width: 800, height: 400 }))
      .toEqual({ x: 600, y: 300 });
  });

  it("divides by the zoom rather than ignoring it", () => {
    // Zoomed to 2×, the pane covers HALF as much flow — the centre is half as far out.
    expect(viewportCenter({ x: 0, y: 0, zoom: 2 }, { width: 800, height: 400 }))
      .toEqual({ x: 200, y: 100 });
  });

  it("centres the CARD on that point, not its left edge", () => {
    // Without the half-width shift a clicked node lands visibly right of centre — the
    // kind of off-by-a-viewport only a browser would otherwise have reported.
    expect(viewportCenter({ x: 0, y: 0, zoom: 1 }, { width: 800, height: 400 }, 280).x)
      .toBe(260);
  });

  it("survives a canvas that has not measured itself yet", () => {
    // zoom 0 is what an unmeasured canvas reports; dividing by it puts the node at
    // infinity, which is indistinguishable from the node never having been added.
    const at = viewportCenter({ x: 0, y: 0, zoom: 0 }, { width: 800, height: 400 });
    expect(Number.isFinite(at.x) && Number.isFinite(at.y)).toBe(true);
  });
});

describe("producedByAlias", () => {
  it("reads the keys a step was SEEN to publish", () => {
    // The open set's only honest source: what the run actually recorded. No ontology
    // build, no second contract — the server already computes this for the canvas.
    const graph = { nodes: [
      { id: "step1", produced: ["annotation", "id"] },
      { id: "step2", produced: [] },
    ] };
    expect(producedByAlias(graph)).toEqual({ step1: ["annotation", "id"] });
  });

  it("sorts and de-duplicates, so a fanned-out step lists each key once", () => {
    // A `for_each` step appends one outcome per item, and the server's `produced` is a
    // union — a picker offering "ts, ts, ts" would read as three different keys.
    expect(producedByAlias({ nodes: [{ id: "s", produced: ["ts", "channel", "ts"] }] }))
      .toEqual({ s: ["channel", "ts"] });
  });

  it("offers nothing for a step that has never run", () => {
    // Which is exactly when the typed field is the only honest offer.
    expect(producedByAlias({ nodes: [{ id: "s" }] })).toEqual({});
  });

  it("survives no graph at all", () => {
    expect(producedByAlias(null)).toEqual({});
    expect(producedByAlias(undefined)).toEqual({});
  });
});

describe("layoutToPersist", () => {
  const at = (x: number, y: number) => ({ x, y });

  it("keeps only steps that still exist", () => {
    // A removed step — or a palette add that was discarded — must not keep a coordinate
    // forever, or the canvas eventually opens carrying the ghosts of everything deleted.
    const positions = { __trigger: at(0, 60), step1: at(9, 9), step2: at(1, 1) };
    expect(layoutToPersist(positions, new Set(["__trigger", "step1"])))
      .toEqual({ __trigger: at(0, 60), step1: at(9, 9) });
  });

  it("rounds, so a drag's subpixel does not land in the row", () => {
    expect(layoutToPersist({ s: at(312.7000000000001, -0.4) }, new Set(["s"])))
      .toEqual({ s: at(313, 0) });
  });

  it("persists an empty arrangement rather than refusing to", () => {
    // Every node removed is a real arrangement — and the whole-replace save is what
    // clears the row, so returning nothing here would leave the old layout standing.
    expect(layoutToPersist({ gone: at(1, 1) }, new Set())).toEqual({});
  });
});

/* ── DS-4 · duplicating and pasting a step ─────────────────────────────────── */

describe("pasteEffect", () => {
  const eff = (over: Partial<AutoEffect> = {}): AutoEffect =>
    ({ kind: "slack_post", config: { channel: "#ops" }, ...over } as AutoEffect);
  const from = (ref: string) => ({ $from: ref });
  const chain = (...effects: AutoEffect[]) => ({ conditions: [], effects });

  it("appends the copy", () => {
    const { draft } = pasteEffect(chain(eff()), eff({ config: { channel: "#two" } }), "item");
    expect(draft.effects).toHaveLength(2);
    expect(draft.effects[1].config.channel).toBe("#two");
  });

  it("KEEPS a reference whose producer is still there and upstream", () => {
    // The copy lands at the end, so everything it named is upstream of it and still
    // means what it meant. Dropping these would make duplicate useless.
    const source = eff({ config: { message: from("step1.answer") } });
    const { draft, dropped } = pasteEffect(
      chain(eff({ kind: "investigate" } as Partial<AutoEffect>), source), source, "item");

    expect(draft.effects[2].config.message).toEqual(from("step1.answer"));
    expect(dropped).toEqual([]);
  });

  it("DROPS a reference whose producer is not in this chain — never repoints it", () => {
    // The trap this whole function exists for. `validate_chain` refuses an UNKNOWN step
    // and a FORWARD one; a ref that now resolves to a DIFFERENT existing step is
    // neither, so it saves, draws a confident edge, and posts the wrong step's answer.
    const pasted = eff({ config: { message: from("numbers.answer") } });
    const { draft, dropped } = pasteEffect(chain(eff()), pasted, "item");

    expect(draft.effects[1].config.message).toBe("");
    expect(dropped).toContain("message");
  });

  it("keeps the FIELD when it drops the wiring", () => {
    // A dropped binding must leave a field to type into, not a hole where one was.
    const { draft } = pasteEffect(chain(eff()),
                                  eff({ config: { channel: "#x", message: from("gone.k") } }),
                                  "item");
    expect(Object.keys(draft.effects[1].config).sort()).toEqual(["channel", "message"]);
    expect(draft.effects[1].config.channel).toBe("#x");
  });

  it("drops a guard clause with a dangling side rather than half of it", () => {
    // Half a comparison is not a weaker guard — it is a different one, and it would
    // decide whether the step runs.
    const pasted = eff({ when: [{ left: from("gone.answer"), op: "truthy" }] } as Partial<AutoEffect>);
    const { draft, dropped } = pasteEffect(chain(eff()), pasted, "item");

    expect(draft.effects[1].when ?? []).toEqual([]);
    expect(dropped).toContain("only if");
  });

  it("keeps a guard whose subject survives", () => {
    const pasted = eff({ when: [{ left: from("step1.ts"), op: "truthy" }] } as Partial<AutoEffect>);
    const { draft, dropped } = pasteEffect(chain(eff()), pasted, "item");

    expect(draft.effects[1].when).toHaveLength(1);
    expect(dropped).toEqual([]);
  });

  it("drops a fan-out whose list is gone, and the item refs that depended on it", () => {
    // `item.value` is defined BY the fan-out. Keeping it after the source went would
    // leave a reference to a name that no longer exists in the step at all.
    const pasted = eff({
      for_each: { source: from("gone.rows") },
      config: { message: from("item.value") },
    } as Partial<AutoEffect>);
    const { draft, dropped } = pasteEffect(chain(eff()), pasted, "item");

    expect(draft.effects[1].for_each).toBeUndefined();
    expect(draft.effects[1].config.message).toBe("");
    expect(dropped).toEqual(expect.arrayContaining(["for each", "message"]));
  });

  it("keeps item refs when the fan-out itself survives", () => {
    const pasted = eff({
      for_each: { source: ["EMEA", "NA"] },
      config: { message: from("item.value") },
    } as Partial<AutoEffect>);
    const { draft, dropped } = pasteEffect(chain(eff()), pasted, "item");

    expect(draft.effects[1].config.message).toEqual(from("item.value"));
    expect(dropped).toEqual([]);
  });

  it("uses the SERVER's word for the item alias, not a hardcoded one", () => {
    const pasted = eff({
      for_each: { source: ["a"] }, config: { message: from("each.value") },
    } as Partial<AutoEffect>);
    expect(pasteEffect(chain(eff()), pasted, "each").draft.effects[1].config.message)
      .toEqual(from("each.value"));
  });

  it("drops an explicit alias rather than duplicating a name", () => {
    // Two steps called `numbers` is a collision; `numbers-2` is a name nobody chose.
    // The copy takes its positional name.
    const { draft } = pasteEffect(chain(eff({ alias: "numbers" })),
                                  eff({ alias: "numbers" }), "item");
    expect(draft.effects[1].alias).toBeUndefined();
    expect(aliasFor(draft.effects[1], 1)).toBe("step2");
  });

  it("suffixes only when the positional name is genuinely taken", () => {
    // Someone explicitly aliased an earlier step "step2"; the copy landing at index 1
    // cannot also be step2, so it says so rather than colliding silently.
    const { draft } = pasteEffect(chain(eff({ alias: "step2" })), eff(), "item");
    expect(draft.effects[1].alias).toBe("step2-2");
  });

  it("never mutates the draft it was given", () => {
    const original = chain(eff());
    pasteEffect(original, eff(), "item");
    expect(original.effects).toHaveLength(1);
  });
});

/* ── DS-3 · a run while it is still running ────────────────────────────────── */

describe("liveStatuses", () => {
  const call = (step: string, span = step) =>
    ({ kind: "tool_call", span_id: span, ok: null, payload: { step } });
  const result = (step: string, span = step, ok = true) =>
    ({ kind: "tool_call_result", span_id: span, ok, payload: { step } });

  it("reads an unpaired call as RUNNING — which is why the engine emits it first", () => {
    expect(liveStatuses([call("step1")])).toEqual({ step1: "running" });
  });

  it("settles a step when its result arrives", () => {
    expect(liveStatuses([call("step1"), result("step1")])).toEqual({ step1: "done" });
  });

  it("keeps earlier steps settled while a later one runs", () => {
    // The shape the canvas exists to show: done, done, running, untouched.
    expect(liveStatuses([
      call("step1"), result("step1"), call("step2"), result("step2"), call("step3"),
    ])).toEqual({ step1: "done", step2: "done", step3: "running" });
  });

  it("matches on the step ALIAS, never on position", () => {
    // A guarded, refused or unresolved step emits NO span at all. Counting spans against
    // effects would put every later status on the wrong card — the bug `group_outcomes`
    // was written for on the server side.
    expect(liveStatuses([call("post"), result("post")])).toEqual({ post: "done" });
  });

  it("folds a fanned step's per-item spans onto its one node", () => {
    // W2 emits `alias[1/3]`, `alias[2/3]`, … — three spans, one card.
    expect(liveStatuses([
      call("step2[1/2]", "s1"), result("step2[1/2]", "s1"),
      call("step2[2/2]", "s2"),
    ])).toEqual({ step2: "running" });
  });

  it("settles a fanned step only when every item has closed", () => {
    expect(liveStatuses([
      call("step2[1/2]", "s1"), result("step2[1/2]", "s1"),
      call("step2[2/2]", "s2"), result("step2[2/2]", "s2"),
    ])).toEqual({ step2: "done" });
  });

  it("lets ONE failed item fail the step, and does not let a later success undo it", () => {
    // Averaging a fan-out's failures away would draw a green card over a message nobody
    // received.
    expect(liveStatuses([
      call("s[1/2]", "a"), result("s[1/2]", "a", false),
      call("s[2/2]", "b"), result("s[2/2]", "b", true),
    ])).toEqual({ s: "failed" });
  });

  it("ignores events that are not automation steps", () => {
    // The trace carries the agent's own spans too — a model call inside `investigate`
    // has no `step`, and must not invent a node.
    expect(liveStatuses([
      { kind: "tool_call", span_id: "x", ok: null, payload: { span_kind: "llm" } },
      { kind: "tool_call", span_id: "y", ok: null, payload: null },
    ])).toEqual({});
  });

  it("says nothing about a run that has emitted nothing", () => {
    // A gated or not-fired run returns before any span. The canvas must not spin.
    expect(liveStatuses([])).toEqual({});
  });
});

/* ── DS-6 · branch and join ─────────────────────────────────────────────────────── */

const HOLDS = [{ left: { $from: "numbers.answer" }, op: "truthy" }];

/** alerts / daily as the two arms of one route, fed by an investigate. */
const routed = (): AutoEffect[] => [
  eff("investigate", { question: "did revenue fall?" }, "numbers"),
  { kind: "slack_post", alias: "alerts", when: HOLDS,
    config: { channel: "#alerts", message: "fell" } },
  { kind: "slack_post", alias: "daily", else_of: "alerts",
    config: { channel: "#daily", message: "steady" } },
];

describe("the route, drawn", () => {
  it("emits one route edge from the deciding step to its otherwise arm", () => {
    const { steps, edges } = draftToFlow(draft(...routed()), VOCAB);
    expect(steps[2].elseOf).toBe("alerts");
    expect(edges).toContainEqual(
      { from: "alerts", key: "", to: "daily", field: ELSE_FIELD, route: true });
  });

  it("does not draw a route onto a step that does not exist", () => {
    const { edges } = draftToFlow(draft(
      { kind: "slack_post", alias: "daily", else_of: "ghost",
        config: { channel: "#c" } }), VOCAB);
    expect(edges.filter(e => e.route)).toEqual([]);
  });
});

describe("the join, drawn", () => {
  const joined = (): AutoEffect[] => [...routed(),
    { kind: "slack_post", alias: "summary",
      config: { channel: "#c",
                thread_ts: { $from_any: ["alerts.ts", "daily.ts"] } } }];

  it("draws one arrow per alternative — every candidate is dataflow", () => {
    const { edges } = draftToFlow(draft(...joined()), VOCAB);
    const into = edges.filter(e => e.to === "summary" && e.field === "thread_ts");
    expect(into.map(e => `${e.from}.${e.key}`)).toEqual(["alerts.ts", "daily.ts"]);
  });

  it("the bound chip reads as the whole wiring, oldest candidate first", () => {
    const { steps } = draftToFlow(draft(...joined()), VOCAB);
    const chip = steps[3].inputs.find(i => i.field === "thread_ts");
    expect(chip?.boundTo).toBe("alerts.ts or daily.ts");
  });

  it("a malformed join is not wiring — bindingRefs offers nothing to draw", () => {
    // The server refuses it at save; meanwhile the canvas must not draw a confident
    // edge from a shape the engine would refuse.
    expect(bindingRefs({ $from_any: "alerts.ts" })).toEqual([]);
    expect(bindingRefs({ $from_any: [] })).toEqual([]);
    expect(bindingRefs({ $from_any: ["alerts.ts", 3] })).toEqual([]);
  });

  it("guardSentences reads a join side as its candidates", () => {
    const ops = [{ op: "truthy", label: "is set", unary: true }];
    expect(guardSentences(
      [{ left: { $from_any: ["alerts.ts", "daily.ts"] }, op: "truthy" }], ops))
      .toEqual(["alerts.ts or daily.ts is set"]);
  });
});

describe("applyConnect — dragging the other arm is a join, not a replacement", () => {
  const base = draft(...routed(),
    { kind: "slack_post", alias: "summary",
      config: { channel: "#c", thread_ts: { $from: "alerts.ts" } } });

  it("merges the two arms of one route into $from_any", () => {
    const { draft: next, error } = applyConnect(base, VOCAB, {
      fromAlias: "daily", key: "ts", toAlias: "summary", field: "thread_ts" });
    expect(error).toBe("");
    expect(next.effects[3].config.thread_ts)
      .toEqual({ $from_any: ["alerts.ts", "daily.ts"] });
  });

  it("still replaces for a producer that is not the other arm", () => {
    const { draft: next } = applyConnect(base, VOCAB, {
      fromAlias: "numbers", key: "answer", toAlias: "summary", field: "thread_ts" });
    expect(next.effects[3].config.thread_ts).toEqual({ $from: "numbers.answer" });
  });

  it("re-dragging a candidate the field already carries changes nothing", () => {
    const joinedBase = draft(...routed(),
      { kind: "slack_post", alias: "summary",
        config: { channel: "#c",
                  thread_ts: { $from_any: ["alerts.ts", "daily.ts"] } } });
    const { draft: next, error } = applyConnect(joinedBase, VOCAB, {
      fromAlias: "alerts", key: "ts", toAlias: "summary", field: "thread_ts" });
    expect(error).toBe("");
    expect(next.effects[3].config.thread_ts)
      .toEqual({ $from_any: ["alerts.ts", "daily.ts"] });
  });
});

describe("clearBinding clears a join whole", () => {
  it("the ✕ removes every candidate the chip showed, not half of them", () => {
    const base = draft(...routed(),
      { kind: "slack_post", alias: "summary",
        config: { channel: "#c",
                  thread_ts: { $from_any: ["alerts.ts", "daily.ts"] } } });
    const next = clearBinding(base, "summary", "thread_ts");
    expect(next.effects[3].config.thread_ts).toBe("");
  });
});

describe("pasteEffect — the route and the join under the drop-never-repoint law", () => {
  it("keeps a join's surviving candidates and reports the ones that went", () => {
    const { draft: next, dropped } = pasteEffect(
      draft(...routed()),
      { kind: "slack_post",
        config: { channel: "#c",
                  thread_ts: { $from_any: ["alerts.ts", "ghost.ts"] } } },
      "item");
    const pasted = next.effects[next.effects.length - 1];
    expect(pasted.config.thread_ts).toEqual({ $from_any: ["alerts.ts"] });
    expect(dropped).toContain("thread_ts");
  });

  it("a join with no surviving candidate goes back to plain text", () => {
    const { draft: next, dropped } = pasteEffect(
      draft(eff("investigate", { question: "q" }, "numbers")),
      { kind: "slack_post",
        config: { channel: "#c",
                  thread_ts: { $from_any: ["ghost.ts", "phantom.ts"] } } },
      "item");
    expect(next.effects[next.effects.length - 1].config.thread_ts).toBe("");
    expect(dropped).toContain("thread_ts");
  });

  it("keeps the route when its target is still present, guarded and unfanned", () => {
    const { draft: next, dropped } = pasteEffect(
      draft(...routed()),
      { kind: "slack_post", else_of: "alerts", config: { channel: "#x" } },
      "item");
    expect(next.effects[next.effects.length - 1].else_of).toBe("alerts");
    expect(dropped).not.toContain("otherwise");
  });

  it("drops the route when the target is absent — never repoints it", () => {
    const { draft: next, dropped } = pasteEffect(
      draft(eff("investigate", { question: "q" }, "numbers")),
      { kind: "slack_post", else_of: "alerts", config: { channel: "#x" } },
      "item");
    expect(next.effects[next.effects.length - 1].else_of).toBeUndefined();
    expect(dropped).toContain("otherwise");
  });

  it("drops the route when the same-named target has lost its guard", () => {
    // A silently kept route onto an unguarded step is an arm that can never run —
    // and the save would refuse it with a message about a step this paste created.
    const { draft: next, dropped } = pasteEffect(
      draft(eff("slack_post", { channel: "#a" }, "alerts")),
      { kind: "slack_post", else_of: "alerts", config: { channel: "#x" } },
      "item");
    expect(next.effects[next.effects.length - 1].else_of).toBeUndefined();
    expect(dropped).toContain("otherwise");
  });
});

describe("rootAliases — where a parallel automation's spine attaches", () => {
  it("a step is a root until something it reads exists in the chain", () => {
    const roots = rootAliases(draft(
      eff("investigate", { question: "sales?" }, "numbers"),
      eff("investigate", { question: "costs?" }, "costs"),
      eff("slack_post", { channel: "#c", message: { $from: "numbers.answer" } }),
    ));
    expect(roots).toEqual(["numbers", "costs"]);
  });

  it("guard sides, fan sources and the route all count as being fed", () => {
    const roots = rootAliases(draft(
      eff("investigate", { question: "q" }, "numbers"),
      { kind: "slack_post", alias: "guarded", config: { channel: "#c" },
        when: [{ left: { $from: "numbers.answer" }, op: "truthy" }] },
      { kind: "slack_post", alias: "arm", else_of: "guarded",
        config: { channel: "#d" } },
      { kind: "slack_post", alias: "fanned",
        config: { channel: { $from: "item.value" }, message: "hi" },
        for_each: { source: { $from: "numbers.answer" } } },
    ));
    expect(roots).toEqual(["numbers"]);
  });

  it("the per-iteration item alias is not a step — a fanned literal stays a root", () => {
    const roots = rootAliases(draft(
      { kind: "slack_post", alias: "fan",
        config: { channel: { $from: "item.value" }, message: "hi" },
        for_each: { source: ["#a", "#b"] } },
    ));
    expect(roots).toEqual(["fan"]);
  });
});

describe("visibleFields — a binding is wiring, and wiring must draw", () => {
  const primary = [{ field: "channel", placeholder: "#channel" },
                   { field: "message", placeholder: "message" }];

  it("a bound non-primary field earns its row (found by driving: thread_ts's join "
     + "edges were silently dropped without a port to land on)", () => {
    const fields = visibleFields(primary, [
      { field: "message", boundTo: null },
      { field: "thread_ts", boundTo: "alerts.ts or daily.ts" },
      { field: "channel", boundTo: "alerts.channel" },
    ]);
    expect(fields.map(f => f.field)).toEqual(["channel", "message", "thread_ts"]);
  });

  it("an unbound non-primary field stays hidden — a node holding every field is a "
     + "form wearing a node costume", () => {
    const fields = visibleFields(primary, [
      { field: "message", boundTo: null },
      { field: "thread_ts", boundTo: null },
    ]);
    expect(fields.map(f => f.field)).toEqual(["channel", "message"]);
  });
});

/* ── DS-1 P1 · the edge dropped on empty canvas ─────────────────────────────── */

describe("landPrebound — the palette choice lands wired to the dropped edge", () => {
  const P1_VOCAB: Vocabulary = {
    ...VOCAB,
    metric_value: { publishes: ["value", "unit", "label"], bindable: [] },
  };

  it("canConsume is the filter's whole law: an input port exists", async () => {
    const { canConsume } = await import("@/lib/automationFlow");
    expect(canConsume(P1_VOCAB, "slack_post")).toBe(true);
    expect(canConsume(P1_VOCAB, "kinetic_action")).toBe(true);
    expect(canConsume(P1_VOCAB, "metric_value")).toBe(false);
    expect(canConsume(P1_VOCAB, "no_such_kind")).toBe(false);
  });

  it("appends AND binds in one result, through applyConnect's own law", async () => {
    const { landPrebound } = await import("@/lib/automationFlow");
    const base = draft(eff("investigate", { question: "q" }, "numbers"));
    const r = landPrebound(base, P1_VOCAB, eff("slack_post", { channel: "#c" }),
                           { from: "numbers", key: "answer" });
    expect(r.error).toBe("");
    expect(r.alias).toBe("step2");
    expect(r.field).toBe("message");
    expect(r.draft.effects[1].config.message).toEqual({ $from: "numbers.answer" });
  });

  it("the wire goes to the FIRST declared input port — where the eye goes", async () => {
    const { bindTargetField } = await import("@/lib/automationFlow");
    expect(bindTargetField(P1_VOCAB, "slack_post")).toBe("message");
    expect(bindTargetField(P1_VOCAB, "metric_value")).toBeNull();
  });

  it("an open-set drop appends unbound and names the field for the key picker", async () => {
    // "*" cannot know its key at drag time; pre-writing `{"$from": "act.*"}` would be
    // a binding the engine resolves to nothing. The caller parks it for the picker.
    const { landPrebound } = await import("@/lib/automationFlow");
    const base = draft(eff("kinetic_action", { action_id: "a" }, "act"));
    const r = landPrebound(base, P1_VOCAB, eff("slack_post", { channel: "#c" }),
                           { from: "act", key: "*" });
    expect(r.error).toBe("");
    expect(r.field).toBe("message");
    expect(r.draft.effects[1].config.message).toBeUndefined();
  });

  it("a consumer-less kind still lands — unwired, and says so", async () => {
    // The filter should prevent this, but the gate must not trust the filter: a step
    // someone forced through arrives on the canvas rather than vanishing, with the
    // sentence naming why it carries no wire.
    const { landPrebound } = await import("@/lib/automationFlow");
    const base = draft(eff("investigate", { question: "q" }, "numbers"));
    const r = landPrebound(base, P1_VOCAB, eff("metric_value", { metric: "revenue" }),
                           { from: "numbers", key: "answer" });
    expect(r.draft.effects).toHaveLength(2);
    expect(r.error).toMatch(/no input to bind/);
  });

  it("a refused wire keeps the step and reports applyConnect's sentence", async () => {
    // Same shape as a hand-dragged refusal: the step is real, the wire is not.
    const { landPrebound } = await import("@/lib/automationFlow");
    const base = draft(eff("investigate", { question: "q" }, "numbers"));
    const r = landPrebound(base, P1_VOCAB, eff("slack_post", { channel: "#c" }),
                           { from: "numbers", key: "no_such_key" });
    expect(r.draft.effects).toHaveLength(2);
    expect(r.draft.effects[1].config.message).toBeUndefined();
    expect(r.error).toMatch(/has no 'no_such_key'/);
  });
});
