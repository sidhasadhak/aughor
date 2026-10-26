// @vitest-environment jsdom

/**
 * Arc FA, FA-3 — an object whose entity is marked retiring still reads, and its page says what replaces it and when:
 * "retiring on <date> — use <successor> instead", and after the day "past its retiring date" (the user's word,
 * 2026-10-26). The page draws the chip only when the object's answer carries a mark; while marking is off it carries
 * none, and the header is what it was.
 */
import React from "react";
import { describe, expect, it } from "vitest";
import { render, screen } from "@/lib/testing";

import { RetiringChip } from "@/components/objects/ObjectView";

describe("RetiringChip — an object page says its entity is retiring", () => {
  it("names the successor and the day, and keeps the person's note on hover", () => {
    render(<RetiringChip typeName="Product" mark={{ successor: "Brand", successor_name: "Brand", on: "2026-12-01",
                                                    past: false, note: "merged into brands",
                                                    said: "retiring on 2026-12-01 — use Brand instead" }} />);
    const chip = screen.getByTestId("object-retiring");
    expect(chip).toHaveTextContent("retiringProduct is retiring on Tue 1 Dec 2026 — use Brand instead");
    expect(chip.getAttribute("title")).toBe("Product is retiring on Tue 1 Dec 2026 — use Brand instead. merged into brands");
  });

  it("after the day it says the object's entity is past its retiring date", () => {
    render(<RetiringChip typeName="Product" mark={{ successor: "Brand", successor_name: "Brand", on: "2026-10-01",
                                                    past: true, said: "past its retiring date, 2026-10-01 — use Brand instead" }} />);
    expect(screen.getByTestId("object-retiring"))
      .toHaveTextContent("past its retiring dateProduct is past its retiring date, Thu 1 Oct 2026 — use Brand instead");
  });
});
