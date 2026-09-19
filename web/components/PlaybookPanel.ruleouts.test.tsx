// @vitest-environment jsdom
/**
 * The playbook's default view is the plays a person might act on.
 *
 * Measured on the live deployment 2026-09-19: 486 of 878 entries were data-quality
 * rule-outs the Verifier runs inside a deep report. They outnumbered the readable plays
 * more than two to one, which is how a list stops being read at all.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PlaybookPanel } from "@/components/PlaybookPanel";

const entry = (id: string, tags: string[], recommendation: string) => ({
  id, source_kb_id: null, trigger_metric: `m_${id}`, trigger_condition: "any",
  trigger_operator: "any", trigger_value: 0, recommendation, expected_impact: "",
  typical_timeline: "", owner_role: "Data Analyst", tags, evidence_sources: [],
  historical_success_rate: 0, status: "active" as const,
});

const ROWS = [
  entry("dq1", ["data quality"], "rule out a stale load"),
  entry("dq2", ["data quality"], "rule out a duplicated key"),
  entry("p1", ["customer retention"], "win back lapsed accounts"),
];

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => ROWS })));
});

describe("data-quality rule-outs", () => {
  it("are not listed by default, and the panel SAYS how many it is holding back",
    async () => {
      render(<PlaybookPanel />);
      expect(await screen.findByText("win back lapsed accounts")).toBeInTheDocument();
      expect(screen.queryByText("rule out a stale load")).not.toBeInTheDocument();
      // Silently dropping two thirds of the rows is the defect this avoids.
      expect(screen.getByTestId("playbook-ruleouts-toggle"))
        .toHaveTextContent("2 data-quality rule-outs run in the Verifier — not listed");
    });

  it("come back when asked for", async () => {
    render(<PlaybookPanel />);
    fireEvent.click(await screen.findByTestId("playbook-ruleouts-toggle"));
    expect(await screen.findByText("rule out a stale load")).toBeInTheDocument();
  });

  it("are REACHED by search — a row you named must never be behind a fold", async () => {
    render(<PlaybookPanel />);
    await screen.findByText("win back lapsed accounts");
    fireEvent.change(screen.getByPlaceholderText("Search recommendations…"),
      { target: { value: "data quality" } });
    expect(await screen.findByText("rule out a stale load")).toBeInTheDocument();
  });
});
