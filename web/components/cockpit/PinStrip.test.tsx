// @vitest-environment jsdom

/**
 * Arc OC-4 — the release a cockpit holding pieces was composed against, said above it. In force: one quiet line.
 * Changed since: each change that touches what a piece reads, with the class it was published as and the piece that
 * reads it, and a re-pin for the person who keeps the cockpit — none for a reader of a published one.
 */
import { fireEvent, render, screen } from "@/lib/testing";
import { describe, expect, it, vi } from "vitest";

import { PinStrip } from "@/components/cockpit/PinStrip";
import type { CockpitPin } from "@/lib/api";

const SPEC = { elements: { board: { type: "ProcessBoard" }, flag: { type: "ActionButton" } } };
const pin = (over: Partial<CockpitPin> = {}): CockpitPin =>
  ({ pinned: "c/thelook@2", current: "c/thelook@2", changes: [], ...over });

describe("the pin strip", () => {
  it("says the release in force quietly when it is the one the cockpit was composed against", () => {
    render(<PinStrip pin={pin()} spec={SPEC} onRepin={vi.fn()} />);
    expect(screen.getByTestId("cockpit-pin").textContent).toContain("read release 2 of the ontology, the one it was composed against");
    expect(screen.queryByTestId("cockpit-repin")).toBeNull();
  });

  it("names each change since that touches a piece, and re-pins on the keeper's word", () => {
    const onRepin = vi.fn();
    render(<PinStrip spec={SPEC} onRepin={onRepin} pin={pin({ current: "c/thelook@4", changes: [
      { release: "c/thelook@3", number: 3, kind: "process", target_id: "order_fulfilment", change: "changed", class: "MEANING", pieces: ["board"] },
      { release: "c/thelook@4", number: 4, kind: "action", target_id: "flag_for_review", change: "changed", class: "WARN", pieces: ["flag"] },
    ] })} />);
    expect(screen.getByTestId("cockpit-pin").textContent).toContain("Composed against release 2; its pieces read release 4. 2 changes since");
    expect(screen.getAllByTestId("cockpit-pin-change").map(li => li.textContent)).toEqual([
      "changes a meaningprocess order_fulfilment changed in release 3 · read by the process board",
      "worth a lookaction flag_for_review changed in release 4 · read by the action button"]);
    fireEvent.click(screen.getByTestId("cockpit-repin"));
    expect(onRepin).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("cockpit-repin").textContent).toBe("Re-pin to release 4");
  });

  it("offers a reader of a published cockpit no re-pin, and says when one was never pinned", () => {
    render(<PinStrip spec={SPEC} pin={pin({ pinned: "", current: "c/thelook@4" })} />);
    expect(screen.getByTestId("cockpit-pin").textContent).toContain("Not pinned to a release; its pieces read release 4.");
    expect(screen.queryByTestId("cockpit-repin")).toBeNull();
  });
});
