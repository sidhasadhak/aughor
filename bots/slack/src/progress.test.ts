/**
 * The card mapper's rules, which are all about identity and honesty:
 * one phase is ONE card that fills in, a card keeps its name across updates,
 * and no outcome is promoted to something better than it was.
 */
import { describe, expect, it } from "vitest";

import { createProgressCards } from "./progress.js";

describe("createProgressCards", () => {
  it("one phase is one card — progress then completion share the phase's id", () => {
    const cards = createProgressCards();
    const [running] = cards({ type: "phase_progress", phase_id: "root_cause", done: 2, total: 5, current: "channel" });
    const [done] = cards({
      type: "phase_complete",
      phase: { phase_id: "root_cause", phase_name: "Root cause", status: "complete", summary: "Discounting." },
    });

    expect(running).toMatchObject({ id: "phase-root_cause", status: "in_progress", details: "Scanning channel · 2/5" });
    expect(done).toMatchObject({ id: "phase-root_cause", status: "complete", output: "Discounting." });
    // Same id ⇒ Slack updates the card in place instead of stacking a second one.
    expect((running as { id: string }).id).toBe((done as { id: string }).id);
  });

  it("a card keeps its name once it has one — an update must re-send the title", () => {
    const cards = createProgressCards();
    cards({ type: "phase_complete", phase: { phase_id: "p1", phase_name: "Segment scan", status: "running" } });
    const [again] = cards({ type: "phase_progress", phase_id: "p1", done: 1, total: 2 });
    expect(again).toMatchObject({ title: "Segment scan" });
  });

  it("falls back to a humanized id, never a raw one", () => {
    const cards = createProgressCards();
    const [c] = cards({ type: "phase_progress", phase_id: "cohort_split", done: 1, total: 4 });
    expect(c).toMatchObject({ title: "Cohort split", details: "Scanning dimensions · 1/4" });
  });

  it("skipped and partial phases say so — Slack's four statuses must not launder an outcome", () => {
    const cards = createProgressCards();
    const [skipped] = cards({
      type: "phase_complete",
      phase: { phase_id: "a", phase_name: "Seasonality", status: "skipped", skipped_reason: "no date column" },
    });
    const [partial] = cards({
      type: "phase_complete",
      phase: { phase_id: "b", phase_name: "Mix", status: "partial", summary: "two of five dimensions" },
    });
    const [failed] = cards({
      type: "phase_complete",
      phase: { phase_id: "c", phase_name: "Cohorts", status: "error", summary: "query failed" },
    });

    expect(skipped).toMatchObject({ status: "complete", output: "Skipped — no date column" });
    expect(partial).toMatchObject({ status: "complete", output: "Partial — two of five dimensions" });
    expect(failed).toMatchObject({ status: "error", output: "query failed" });
  });

  it("the wave's plan names every sub-question up front, then each answer lands on its own card", () => {
    const cards = createProgressCards();
    const plan = cards({
      type: "explore_plan",
      sub_questions: [{ id: "s1", question: "Which regions fell?" }, { id: "s2", question: "Which products?" }],
    });
    expect(plan[0]).toEqual({ type: "plan_update", title: "Exploration · 2 sub-questions" });
    expect(plan.slice(1)).toEqual([
      { type: "task_update", id: "subq-s1", title: "Which regions fell?", status: "pending" },
      { type: "task_update", id: "subq-s2", title: "Which products?", status: "pending" },
    ]);

    const [answered] = cards({ type: "subq_answer", subq_id: "s1", question: "Which regions fell?", insight: "East, by 12%." });
    expect(answered).toMatchObject({ id: "subq-s1", status: "complete", output: "East, by 12%." });
  });

  it("a sub-question that errored is not reported as answered", () => {
    const cards = createProgressCards();
    const [c] = cards({ type: "subq_answer", subq_id: "s3", question: "Why?", error: "no such column: tier", answer: "" });
    expect(c).toMatchObject({ status: "error", output: "no such column: tier" });
  });

  it("a tool call lands as a settled card carrying its own verdict", () => {
    const cards = createProgressCards();
    expect(cards({ type: "converse_step", index: 1, tool: "answer_question", ok: true, detail: "142 rows" })[0])
      .toMatchObject({ id: "step-1", title: "Answer question", status: "complete", output: "142 rows" });
    expect(cards({ type: "converse_step", index: 2, tool: "run_sql", ok: false, detail: "syntax error" })[0])
      .toMatchObject({ id: "step-2", status: "error" });
  });

  it("a provider hop is visible — the failover's failure mode is that it works silently", () => {
    const cards = createProgressCards();
    const [c] = cards({ type: "chain_state", event: "link_failed", from: "gemini", to: "openrouter", detail: "429" });
    expect(c).toMatchObject({ title: "Model unavailable", status: "complete", details: "gemini → openrouter" });
  });

  it("frames with no honest card map to nothing", () => {
    const cards = createProgressCards();
    for (const f of [
      { type: "sql", sql: "SELECT 1" },
      { type: "rows", rows: [[1]] },
      { type: "guard_receipt", guard: "x" },
      { type: "headline", headline: "done" },
      { type: "phase_progress" },            // no phase_id — nothing to key a card on
      { type: "subq_answer", question: "?" }, // no subq_id
    ]) {
      expect(cards(f)).toEqual([]);
    }
  });

  it("long text is capped — a card is a label, not the answer", () => {
    const cards = createProgressCards();
    const [c] = cards({
      type: "phase_complete",
      phase: { phase_id: "p", phase_name: "x".repeat(300), status: "complete", summary: "y".repeat(600) },
    });
    const card = c as { title: string; output: string };
    expect(card.title.length).toBeLessThanOrEqual(120);
    expect(card.output.length).toBeLessThanOrEqual(300);
    expect(card.output.endsWith("…")).toBe(true);
  });
});
