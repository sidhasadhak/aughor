/**
 * The route step said "Multi-hypothesis analysis" of every Agent answer (2026-10-02); a describe answer measured
 * what was asked and tested none. The shape comes from the route frame while the run streams, then the report.
 * Since 2026-10-15 a question's shape is one vocabulary — describe · check · diagnose · survey — and the step
 * reads each of the four; a body mode (direct, investigate, explore) is not a shape and reads as nothing.
 */
import { describe, expect, it } from "vitest";
import { shapeReading, turnToTraceState } from "@/components/ThinkingTrace";
import type { ChatTurn } from "@/lib/chatTurn";

describe("the route step's reading of a question's shape", () => {
  it("has a reading for each of the four shapes", () => {
    expect(shapeReading("describe")).toBe("Measured what was asked");
    expect(shapeReading("check")).toBe("Checked the data — a verdict and its counts");
    expect(shapeReading("diagnose")).toBe("Looked for the cause");
    expect(shapeReading("survey")).toBe("Mapped the landscape");
  });

  it("says nothing of a shape it does not know, or of none", () => {
    expect(shapeReading("")).toBeNull();
    expect(shapeReading(null)).toBeNull();
    expect(shapeReading(undefined)).toBeNull();
    expect(shapeReading("direct")).toBeNull();   // a body, not a shape
  });

  it("reads the route frame while streaming, then the report", () => {
    const base = { phases: [], queriesExecuted: [], hypotheses: [], subQuestions: [], subqAnswers: [], route: null, deepReport: null } as unknown as ChatTurn;
    expect(turnToTraceState({ ...base, route: { shape: "describe" } } as unknown as ChatTurn, false).routeReasoning)
      .toBe("Measured what was asked");
    expect(turnToTraceState({ ...base, route: { shape: "check" } } as unknown as ChatTurn, false).routeReasoning)
      .toBe("Checked the data — a verdict and its counts");
    expect(turnToTraceState({ ...base, deepReport: { question_shape: "describe" } } as unknown as ChatTurn, false).routeReasoning)
      .toBe("Measured what was asked");
    expect(turnToTraceState(base, false).routeReasoning).toBeNull();
  });
});
