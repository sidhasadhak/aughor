// @vitest-environment jsdom
/** Arc BG — an edition's figures, drawn from what was measured: the range last, a thin segment grey. */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { EditionCell, EditionFigure } from "@/lib/api";
import { RangeBars, SegmentBars } from "./EditionFigure";

const FIG = { id: "aov", label: "Average order", better: "up", current: 645,
  usual: { mean: 590, low: 566, high: 614, n: 8, mean_text: "€590", low_text: "€566", high_text: "€614" },
  series: [{ label: "u1", start: "2026-10-05", value: 600 }, { label: "u2", start: "2026-10-12", value: null },
           { label: "current", start: "2026-10-19", value: 645 }] } as unknown as EditionFigure;

const cell = (group: string, delta: number, thin = false): EditionCell =>
  ({ group, current: 10 + delta, usual: 10, delta, rel: delta / 10, n: thin ? 7 : 80, thin, current_text: "", usual_text: "" });

describe("EditionFigure", () => {
  it("draws each range that has a value, the range itself last, over its usual range", () => {
    const { container } = render(<RangeBars figure={FIG} period="week" />);
    const bars = container.querySelectorAll("rect:not([data-testid])");
    expect(bars).toHaveLength(2);                                   // the range with no value is not drawn as zero
    expect(bars[1].getAttribute("data-current")).toBe("true");
    expect(screen.getByTestId("edition-usual-band")).toBeTruthy();
    expect(container.textContent).toContain("€614");
  });
  it("draws a segment under 30 rows grey and labels each change", () => {
    const { container } = render(<SegmentBars cells={[cell("Womenswear", 11), cell("Beauty", 4, true)]} better="down" />);
    expect(container.querySelector('[data-thin="true"]')?.textContent).toContain("Beauty");
    expect(container.textContent).toContain("+110%");
  });
});
