/**
 * The attribution rule, tested where it lives. These are the cases that decide whether
 * the corpus MI-3 exports is trustworthy: a wrong (question → unrelated SQL) pair teaches
 * a falsehood with full confidence, which is worse than the pair being absent.
 */
import { describe, expect, it } from "vitest";

import { soleSqlOfEvents, soleSqlOfSteps } from "./verdictSql";

describe("soleSqlOfSteps", () => {
  it("attributes when exactly one step ran SQL", () => {
    expect(soleSqlOfSteps([{ sql: "SELECT 1" }, { sql: "" }])).toBe("SELECT 1");
  });

  it("refuses to attribute when several steps ran SQL", () => {
    // The case that matters: naming the last one would be a fabricated attribution.
    expect(soleSqlOfSteps([{ sql: "SELECT 1" }, { sql: "SELECT 2" }])).toBe("");
  });

  it("ignores errored steps rather than counting them as candidates", () => {
    expect(soleSqlOfSteps([{ sql: "SELECT good" }, { sql: "SELECT bad", error: "boom" }]))
      .toBe("SELECT good");
  });

  it("returns empty when nothing ran SQL", () => {
    expect(soleSqlOfSteps([{ sql: "   " }, {}])).toBe("");
  });
});

describe("soleSqlOfEvents", () => {
  const call = (input: string) => ({ kind: "tool_call", payload: { input } });

  it("attributes a single executed statement", () => {
    expect(soleSqlOfEvents([call("SELECT 1"), { kind: "llm_call", payload: {} }]))
      .toBe("SELECT 1");
  });

  it("counts DISTINCT statements, so a retry stays attributable", () => {
    // A re-emitted identical query is one query; treating it as two would suppress a
    // perfectly unambiguous attribution.
    expect(soleSqlOfEvents([call("SELECT 1"), call("SELECT 1")])).toBe("SELECT 1");
  });

  it("refuses to attribute when the run issued different statements", () => {
    expect(soleSqlOfEvents([call("SELECT 1"), call("SELECT 2")])).toBe("");
  });

  it("ignores non-tool events and empty inputs", () => {
    expect(soleSqlOfEvents([{ kind: "final_response", payload: { input: "SELECT nope" } },
                            { kind: "tool_call", payload: {} }])).toBe("");
  });
});
