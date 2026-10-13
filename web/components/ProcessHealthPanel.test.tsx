// @vitest-environment jsdom
/**
 * Health, laid out to CLARITY: four figures (on target · warning · off target · not computed), the metrics off target
 * or at a warning under Needs you with a way to ask why on the row, then the rest — each metric said once, its value
 * against its target with the variance as a chip. With no metric targeted, one line and the way to set a target. The
 * scorecard runs each targeted metric's query on the warehouse, so it is read once — never polled.
 *
 * Every read goes through `fetch`, answered here — nothing reaches the live API from jsdom.
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { Theme } from "@radix-ui/themes";
import { beforeEach, describe, expect, it } from "vitest";

import { ProcessHealthPanel, valueText } from "./ProcessHealthPanel";

let scorecard: unknown;
const reads: string[] = [];
globalThis.fetch = (async (input: RequestInfo | URL) => {
  const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
  reads.push(new URL(url, "http://x").pathname);
  const json = (v: unknown, status = 200) => new Response(JSON.stringify(v), { status, headers: { "Content-Type": "application/json" } });
  return scorecard instanceof Error ? json({ detail: "warehouse unreachable" }, 500) : json(scorecard);
}) as typeof fetch;

const item = (name: string, over: Record<string, unknown> = {}) => ({
  name, label: name, current: 100, target: 100, variance: 0, status: "green", unit: null, target_period: null,
  benchmark_source: null, ...over,
});

const asked: string[] = [];
let openedMetrics = 0;
const mount = () => render(<Theme><ProcessHealthPanel connectionId="8233e4fd" onAsk={q => asked.push(q)}
  onOpenMetrics={() => { openedMetrics += 1; }} /></Theme>);

beforeEach(() => {
  reads.length = 0; asked.length = 0; openedMetrics = 0;
  scorecard = [
    item("Revenue", { current: 231_521.3, target: 250_000, variance: -0.0739, status: "yellow", unit: "$", target_period: "monthly" }),
    item("Return rate", { current: 0.151, target: 0.1, variance: 0.51, status: "red", unit: "%", benchmark_source: "internal: FY2025 plan" }),
    item("Units Sold", { current: 4_476_728, target: 4_400_000, variance: 0.0174, status: "green" }),
    item("Gross margin", { current: null, target: 0.6, variance: null, status: "unknown", unit: "%" }),
  ];
});

describe("Health", () => {
  it("opens on four figures counted from the scorecard", async () => {
    mount();
    const figures = await screen.findByTestId("health-figures");
    expect(within(figures).getByTestId("health-fig-green-value")).toHaveTextContent("1");
    expect(within(figures).getByTestId("health-fig-green")).toHaveTextContent("of 4 metrics with a target");
    expect(within(figures).getByTestId("health-fig-yellow-value")).toHaveTextContent("1");
    expect(within(figures).getByTestId("health-fig-red-value")).toHaveTextContent("1");
    expect(within(figures).getByTestId("health-fig-unknown-value")).toHaveTextContent("1");
  });

  it("puts what is off target or at a warning under Needs you, worst first, with Ask why on the row", async () => {
    mount();
    const needs = await screen.findByTestId("health-needs");
    const rows = within(needs).getAllByTestId("health-row");
    expect(rows.map(r => r.textContent)).toEqual([
      expect.stringContaining("Return rate"),
      expect.stringContaining("Revenue"),
    ]);
    expect(rows[0]).toHaveTextContent("15.1%");
    expect(rows[0]).toHaveTextContent("vs 10.0%");
    expect(rows[0]).toHaveTextContent("+51.0%");
    expect(rows[0]).toHaveTextContent("off target");
    expect(rows[0]).toHaveTextContent("internal: FY2025 plan");
    expect(rows[1]).toHaveTextContent("$231.5K");
    expect(rows[1]).toHaveTextContent("vs $250.0K");
    expect(rows[1]).toHaveTextContent("-7.4%");
    expect(rows[1]).toHaveTextContent("monthly");
    fireEvent.click(within(rows[1]).getByRole("button", { name: "Ask why" }));
    expect(asked).toEqual(["Why is Revenue off target? Find the root cause and the contributing factors."]);
  });

  it("lists the rest once — a metric that could not be computed says so", async () => {
    mount();
    const list = await screen.findByTestId("health-list");
    const rows = within(list).getAllByTestId("health-row");
    expect(rows.map(r => r.textContent)).toEqual([
      expect.stringContaining("Gross margin"),
      expect.stringContaining("Units Sold"),
    ]);
    expect(rows[0]).toHaveTextContent("no value");
    expect(rows[0]).toHaveTextContent("not computed");
    expect(rows[1]).toHaveTextContent("4.48M");
    expect(rows[1]).toHaveTextContent("on target");
    expect(within(list).queryByText(/Revenue|Return rate/)).toBeNull();
  });

  it("reads the scorecard once — it runs each metric's query on the warehouse", async () => {
    mount();
    await screen.findByTestId("health-figures");
    expect(reads).toEqual(["/connections/8233e4fd/health-scorecard"]);
  });

  it("with no metric targeted, one line and the way to set a target", async () => {
    scorecard = [];
    mount();
    const empty = await screen.findByTestId("health-empty");
    expect(empty).toHaveTextContent("No metric has a target yet, so nothing is scored.");
    expect(empty).toHaveTextContent("Semantic Layer › a metric › Edit");
    expect(screen.queryByTestId("health-figures")).toBeNull();
    fireEvent.click(within(empty).getByRole("button", { name: "Set a target" }));
    expect(openedMetrics).toBe(1);
  });

  it("says a failed read and offers Retry — never 'no metrics'", async () => {
    scorecard = new Error("down");
    mount();
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not read the scorecard");
    expect(screen.queryByText(/No metric has a target/)).toBeNull();
  });
});

describe("a metric's value as a reader reads it", () => {
  it("by its unit", () => {
    expect(valueText(231_521.3, "$")).toBe("$231.5K");
    expect(valueText(76.5, "USD")).toBe("$76.50");
    expect(valueText(0.6, "%")).toBe("60.0%");
    expect(valueText(2.04, "days")).toBe("2.0 days");
    expect(valueText(4_476_728, null)).toBe("4.48M");
    expect(valueText(1904, null)).toBe("1,904");
  });
});
