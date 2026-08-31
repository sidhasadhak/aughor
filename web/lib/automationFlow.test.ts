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
  applyConnect, clearBinding, draftToFlow, FAN_FIELD, GUARD_FIELD, guardSentences,
  layoutToPersist, producedByAlias, seedConfig, upstreamKeys, viewportCenter,
  type Vocabulary,
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
