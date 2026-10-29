// @vitest-environment jsdom
/** Arc BG/BC — an edition's shapes, drawn from what was measured: the range last, a step coloured by its sign. */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { EditionFigure } from "@/lib/api";
import { Bridge, Multiples, PairRows, RangeBars } from "./EditionFigure";

const FIG = { id: "aov", label: "Average order", better: "up", current: 645,
  usual: { mean: 590, low: 566, high: 614, n: 8, mean_text: "€590", low_text: "€566", high_text: "€614" },
  series: [{ label: "u1", start: "2026-10-05", value: 600 }, { label: "u2", start: "2026-10-12", value: null },
           { label: "current", start: "2026-10-19", value: 645 }] } as unknown as EditionFigure;

describe("EditionFigure", () => {
  it("draws each range that has a value, the range itself last, over its usual range", () => {
    const { container } = render(<RangeBars figure={FIG} period="week" />);
    const bars = container.querySelectorAll("rect:not([data-testid])");
    expect(bars).toHaveLength(2);                                   // the range with no value is not drawn as zero
    expect(bars[1].getAttribute("data-current")).toBe("true");
    expect(screen.getByTestId("edition-usual-band")).toBeTruthy();
  });

  it("bridges a usual range to this one, each step coloured by its sign", () => {
    const { container } = render(<Bridge fmt={v => `€${Math.round(v / 100) / 10}k`} steps={[
      { label: "A usual range", value: 160960, kind: "base" }, { label: "Top clients", value: 9417, kind: "delta" },
      { label: "Everyone else", value: -3388, kind: "delta" }, { label: "This range", value: 166989, kind: "total" }]} />);
    const fills = [...container.querySelectorAll("rect")].map(r => r.getAttribute("fill"));
    expect(fills).toEqual(["var(--chart-deemph)", "var(--grn4)", "var(--amb4)", "var(--blue4)"]);
    expect(container.textContent).toContain("+€9.4k");
    expect(container.textContent).toContain("−€3.4k");
  });

  it("fades the rows a control has not chosen, and calls a segment of a few rows too few", () => {
    render(<PairRows better="up" fmt={v => String(v)} change={() => ""} dim={l => l !== "Mytheresa"}
      rows={[{ label: "Mytheresa", now: 38840, base: 29849 }, { label: "YOOX", now: 9845, base: 11051, thin: true }]} />);
    const rows = screen.getAllByRole("row");
    expect(rows[0].getAttribute("data-faded")).toBeNull();
    expect(rows[1].getAttribute("data-faded")).toBe("true");
    expect(rows[1].textContent).toContain("too few");
  });

  it("draws one small chart per series, each against its own usual", () => {
    const pts = (vals: number[]) => vals.map((v, i) => ({ x: `2026-10-${10 + i}`, v }));
    render(<Multiples fmt={v => `${v.toFixed(2)}%`} series={[{ name: "App", points: pts([6.8, 6.6, 6.7, 5.2]) },
                                                              { name: "Desktop", points: pts([2.0, 1.9, 2.1, 2.6]) }]} />);
    expect(screen.getByTestId("edition-multiples").textContent).toContain("App");
    expect(screen.getByTestId("edition-multiples").textContent).toContain("5.20%");
  });
});
