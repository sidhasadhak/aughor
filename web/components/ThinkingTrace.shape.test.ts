/**
 * The route step said "Multi-hypothesis analysis" of every Agent answer (2026-10-02); a describe answer measured
 * what was asked and tested none. The shape comes from the route frame while the run streams, then the report.
 */
import { describe, expect, it } from "vitest";
import { shapeReading, turnToTraceState } from "@/components/ThinkingTrace";
import type { ChatTurn } from "@/lib/chatTurn";

describe("the route step's reading of a question's shape", () => {
  it("says a describe answer measured what was asked, and leaves the rest to the default", () => {
    expect(shapeReading("describe")).toBe("Measured what was asked");
    expect(shapeReading("diagnose")).toBeNull();
    expect(shapeReading(undefined)).toBeNull();
  });

  it("reads the route frame while streaming, then the report", () => {
    const base = { phases: [], queriesExecuted: [], hypotheses: [], subQuestions: [], subqAnswers: [], route: null, deepReport: null } as unknown as ChatTurn;
    expect(turnToTraceState({ ...base, route: { shape: "describe" } } as unknown as ChatTurn, false).routeReasoning)
      .toBe("Measured what was asked");
    expect(turnToTraceState({ ...base, deepReport: { question_shape: "describe" } } as unknown as ChatTurn, false).routeReasoning)
      .toBe("Measured what was asked");
    expect(turnToTraceState(base, false).routeReasoning).toBeNull();
  });
});
