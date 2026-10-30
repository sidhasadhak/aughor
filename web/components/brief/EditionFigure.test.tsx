// @vitest-environment jsdom
/** Arc BG/BC — an edition's shapes, drawn from what was measured: the range last, a step coloured by its sign. */
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { EditionFigure } from "@/lib/api";
import { Bridge, LineMark, Multiples, PairRows, RangeBars } from "./EditionFigure";

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

  describe("drawn at the width it is shown", () => {
    // jsdom lays nothing out: give every box the width a full block has on the page, and a ResizeObserver that reads it
    afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });
    const shownAt = (px: number) => {
      vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(px);
      vi.stubGlobal("ResizeObserver", class { constructor(private cb: () => void) {} observe() { this.cb(); } disconnect() {} });
    };
    const POINTS = [{ x: "2026-10-05", v: 0.33 }, { x: "2026-10-12", v: 0.15 }, { x: "2026-10-19", v: 0.04 }];

    it("draws a full-width line at its shown width, so its labels keep their size", () => {
      shownAt(770);
      render(<LineMark points={POINTS} fmt={v => `${(v * 100).toFixed(1)}%`} mark={{ at: "2026-10-12", text: "returns still arriving" }} />);
      expect(screen.getByTestId("edition-line").getAttribute("viewBox")).toBe("0 0 770 160");
    });

    it("draws a bridge and a figure's bars at their shown widths too", () => {
      shownAt(640);
      render(<Bridge steps={[{ label: "Usual", value: 100, kind: "base" }, { label: "A", value: 20, kind: "delta" },
                             { label: "This week", value: 120, kind: "total" }]} fmt={v => String(v)} />);
      expect(screen.getByTestId("edition-bridge").getAttribute("viewBox")).toBe("0 0 640 210");
      render(<RangeBars figure={FIG} period="week" />);
      expect(screen.getByTestId("edition-range-bars").getAttribute("viewBox")).toBe("0 0 640 118");
    });

    it("draws at its own width until the box is measured", () => {
      render(<LineMark points={POINTS} fmt={String} />);
      expect(screen.getByTestId("edition-line").getAttribute("viewBox")).toBe("0 0 360 160");
    });
  });
});
