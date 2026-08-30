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

import { applyConnect, clearBinding, draftToFlow, type Vocabulary } from "@/lib/automationFlow";
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
