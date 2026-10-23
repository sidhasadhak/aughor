// @vitest-environment jsdom
/**
 * A run its budget stopped is said so, not "cancelled" (the Olist study, Gap 20, 2026-10-22): the kernel records it
 * CANCELLED — a person's Stop's word — and keeps the cause in its error. Agent Ops reads the cause, and never folds a
 * budget stop into a person's cancel of the same run.
 */
import { describe, expect, it } from "vitest";

import { foldRuns } from "@/components/FleetOverviewPanel";
import type { FleetJob } from "@/lib/api";
import { isBudgetStop, saidState } from "@/lib/runState";

const job = (id: string, state: string, error: string | null = null): FleetJob => ({
  id, kind: "exploration", state, conn_id: "workspace", canvas_id: null, created_at: "2026-10-22T22:50:00Z",
  started_at: null, finished_at: null, error, agent: { agent: "Scout", blurb: "", icon: "" }, title: "Explore olist",
  cost: null, duration_ms: null,
});

describe("a budget stop", () => {
  it("is its own said state; a person's cancel and a failure stay as they were", () => {
    expect(isBudgetStop("budget exceeded: token budget (200,000 tokens)")).toBe(true);
    expect(saidState("CANCELLED", "budget exceeded: token budget (200,000 tokens)")).toBe("BUDGET_STOP");
    expect(saidState("CANCELLED", null)).toBe("CANCELLED");
    expect(saidState("FAILED", "budget exceeded: time budget (900s)")).toBe("FAILED");
  });

  it("is folded apart from a person's cancel of the same run", () => {
    const groups = foldRuns([job("a", "CANCELLED", "budget exceeded: token budget (200,000 tokens)"), job("b", "CANCELLED")]);
    expect(groups.map(g => g.state).sort()).toEqual(["BUDGET_STOP", "CANCELLED"]);
  });
});
