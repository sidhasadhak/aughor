// @vitest-environment jsdom
/**
 * PX-3 — the intake door's handoffs (the lane's backend is tested in
 * tests/unit/test_ki1_intake_lane.py; what can break HERE is what the panel
 * sends and what it refuses to render):
 *
 *  - A candidate renders under a HUMAN label derived from its payload, never as
 *    machine text (PX-1's law applied to this surface).
 *  - `noop` (identical) candidates are receipts, not decisions: no Accept/Dismiss,
 *    collapsed behind "already declared".
 *  - "Accept every new & changed" marks exactly the non-conflict pending rows —
 *    a conflict must be an individual human act.
 *  - Apply hands resolveIntakeBundle precisely the marked ids, and an edited
 *    payload rides `edits` as parsed JSON.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { IntakeBundle, IntakeCandidate, IntakePlan } from "@/lib/api";

const listIntakeBundles = vi.fn();
const getIntakePlan = vi.fn();
const resolveIntakeBundle = vi.fn();
const getConnections = vi.fn();

vi.mock("@/lib/api", async importOriginal => {
  const actual = await importOriginal<Record<string, unknown>>();
  return {
    ...actual,
    listIntakeBundles: (...a: unknown[]) => listIntakeBundles(...a),
    getIntakePlan: (...a: unknown[]) => getIntakePlan(...a),
    resolveIntakeBundle: (...a: unknown[]) => resolveIntakeBundle(...a),
    getConnections: (...a: unknown[]) => getConnections(...a),
    getIntakeMapperStats: vi.fn().mockResolvedValue({ candidates: 0, edit_rate: null, threshold: 0.5 }),
    exportIntakeBundle: vi.fn(),
    mineIntakeUsage: vi.fn(),
    uploadIntakeBundleYaml: vi.fn(),
    uploadIntakeFile: vi.fn(),
    uploadIntakeProse: vi.fn(),
    uploadIntakeSheet: vi.fn(),
  };
});

const { IntakePanel, candidateLabel } = await import("@/components/intake/IntakePanel");

const bundle: IntakeBundle = {
  id: "ib_1", content_hash: "abc", connection_id: "c1",
  source: "metrics.csv", uploaded_by: "ada@example.test",
  uploaded_at: "2026-09-09T10:00:00Z",
};

const cand = (over: Partial<IntakeCandidate>): IntakeCandidate => ({
  id: "ic_x", bundle_id: "ib_1", kind: "metric", verdict: "new", detail: "",
  payload: {}, status: "pending", resolved_by: "", resolved_at: "",
  edited_payload: null, target_ref: "", apply_result: null, ...over,
});

const plan: IntakePlan = {
  bundle,
  summary: { new: 1, changed: 1, identical: 1, conflict: 1 },
  candidates: [
    cand({ id: "ic_new", kind: "metric", verdict: "new",
      payload: { name: "Gross Margin", sql: "SUM(profit)/SUM(sales)" } }),
    cand({ id: "ic_chg", kind: "rule", verdict: "changed", detail: "differs on: body",
      payload: { title: "Exclude test orders", body: "status != 'test'" } }),
    cand({ id: "ic_conf", kind: "trusted_query", verdict: "conflict",
      detail: "an APPROVED answer for this question differs (v2, verified by ada)",
      payload: { question: "What was revenue last month?", sql: "SELECT 1" } }),
    cand({ id: "ic_same", kind: "glossary", verdict: "identical", status: "noop",
      payload: { table: "orders" } }),
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  listIntakeBundles.mockResolvedValue([bundle]);
  getIntakePlan.mockResolvedValue(plan);
  getConnections.mockResolvedValue([]);
  resolveIntakeBundle.mockResolvedValue({
    bundle: "ib_1", accepted: 1, dismissed: 0, errors: 0,
    results: [{ id: "ic_new", outcome: "accepted", target_ref: "" }],
  });
});

describe("candidateLabel", () => {
  it("derives a human label per kind and never leaks raw JSON", () => {
    expect(candidateLabel("metric", { name: "Revenue", sql: "SUM(x)" })).toBe("Revenue");
    expect(candidateLabel("glossary", { table: "orders" })).toBe("orders");
    expect(candidateLabel("trusted_query", { question: "Why?", sql: "SELECT 1" })).toBe("Why?");
    expect(candidateLabel("pack", { skill_md: "---\nname: x\n---\n# Churn playbook\nbody" }))
      .toBe("Churn playbook");
  });
});

describe("IntakePanel", () => {
  it("opens a bundle's plan and renders candidates under human labels", async () => {
    render(<IntakePanel connId="c1" />);
    fireEvent.click(await screen.findByTestId("intake-bundle-ib_1"));
    await screen.findByText("Gross Margin");
    expect(getIntakePlan).toHaveBeenCalledWith("ib_1");
    expect(screen.getByText("Exclude test orders")).toBeTruthy();
    // The conflict's provenance sentence from the planner is shown to the human.
    expect(screen.getByText(/an APPROVED answer for this question differs/)).toBeTruthy();
  });

  it("treats identical objects as receipts: collapsed, no verdict buttons", async () => {
    render(<IntakePanel connId="c1" />);
    fireEvent.click(await screen.findByTestId("intake-bundle-ib_1"));
    await screen.findByText("Gross Margin");
    // Not rendered as a decidable row…
    expect(screen.queryByTestId("intake-cand-ic_same")).toBeNull();
    // …but present behind the disclosure.
    fireEvent.click(screen.getByText(/1 already declared — nothing to decide/));
    expect(screen.getByText((_, el) =>
      el?.tagName === "LI" && el.textContent === "Glossary: orders")).toBeTruthy();
  });

  it("bulk-accept marks new & changed but never a conflict, and apply hands exactly those ids", async () => {
    render(<IntakePanel connId="c1" />);
    fireEvent.click(await screen.findByTestId("intake-bundle-ib_1"));
    await screen.findByText("Gross Margin");
    fireEvent.click(screen.getByTestId("intake-accept-safe"));
    fireEvent.click(await screen.findByTestId("intake-apply"));
    await waitFor(() => expect(resolveIntakeBundle).toHaveBeenCalledTimes(1));
    const [bundleId, args] = resolveIntakeBundle.mock.calls[0];
    expect(bundleId).toBe("ib_1");
    expect([...(args.accept as string[])].sort()).toEqual(["ic_chg", "ic_new"]);
    expect(args.dismiss).toEqual([]);
    expect(args.edits).toEqual({});
  });

  it("an edited payload is parsed and rides `edits`, and the edit implies accept", async () => {
    render(<IntakePanel connId="c1" />);
    fireEvent.click(await screen.findByTestId("intake-bundle-ib_1"));
    await screen.findByText("Gross Margin");
    fireEvent.click(screen.getByTestId("intake-open-ic_new"));
    fireEvent.click(screen.getByText("Edit before accepting"));
    fireEvent.change(screen.getByTestId("intake-edit-ic_new"), {
      target: { value: '{"name": "Gross Margin", "sql": "SUM(profit)/NULLIF(SUM(sales),0)"}' },
    });
    fireEvent.click(await screen.findByTestId("intake-apply"));
    await waitFor(() => expect(resolveIntakeBundle).toHaveBeenCalledTimes(1));
    const [, args] = resolveIntakeBundle.mock.calls[0];
    expect(args.accept).toEqual(["ic_new"]);
    expect(args.edits).toEqual({
      ic_new: { name: "Gross Margin", sql: "SUM(profit)/NULLIF(SUM(sales),0)" },
    });
  });
});
