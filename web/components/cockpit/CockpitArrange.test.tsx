// @vitest-environment jsdom

/**
 * CockpitArrange (Arc CT, CT-8): the outline a person arranges by hand. What is asserted is
 * the spec it hands back — the edits themselves are `lib/cockpit/edit.test.ts`'s.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CockpitArrange, type CardLine } from "@/components/cockpit/CockpitArrange";
import type { CockpitSpec } from "@/lib/cockpit/edit";

const premise = (): CockpitSpec =>
  JSON.parse(readFileSync(resolve(process.cwd(), "lib/cockpit/premise.fixture.json"), "utf8"));

const LINES = new Map<string, CardLine>([
  ["c7f3a001", { title: "Return rate" }],
  ["c91b2002", { title: "Net merchandise revenue", isNew: true, shows: "one figure for the whole connection" }],
]);

function arrange() {
  const onChange = vi.fn();
  render(<CockpitArrange spec={premise()} lines={LINES} onChange={onChange} />);
  return onChange;
}

describe("CockpitArrange", () => {
  it("lays the cockpit out as tabs, their sections, and the cards in each, by name", () => {
    arrange();
    expect(screen.getAllByTestId("arrange-tab-name").map(i => (i as HTMLInputElement).value)).toEqual(["Overview", "Watches"]);
    expect(screen.getAllByTestId("arrange-section-name").map(i => (i as HTMLInputElement).value)).toEqual(["Headline", "Limits"]);
    const cards = screen.getAllByTestId("arrange-card");
    expect(cards.map(c => c.getAttribute("data-card"))).toEqual(["c7f3a001", "c7f3a001", "c91b2002", "c7f3a001"]);
    expect(cards[0]).toHaveTextContent("shown on a condition");                // the alert is conditional
    expect(cards[2]).toHaveTextContent("Net merchandise revenue");
    expect(within(cards[2]).getByText("new")).toBeInTheDocument();             // a card a draft would make
    expect(cards[2]).toHaveTextContent("one figure for the whole connection");
  });

  it("takes a card off, and hands back the spec without it", () => {
    const onChange = arrange();
    const net = screen.getAllByTestId("arrange-card")[2];
    fireEvent.click(within(net).getByRole("button", { name: "Take off" }));
    const next = onChange.mock.calls.at(-1)![0] as CockpitSpec;
    expect(next.elements["card-net"]).toBeUndefined();
    expect(next.elements["sec-headline"].children).toEqual(["alert-rate", "card-rate"]);
  });

  it("moves a card earlier, and cannot move the first one further", () => {
    const onChange = arrange();
    const [alert, , net] = screen.getAllByTestId("arrange-card");
    expect(within(alert).getByRole("button", { name: "Move earlier" })).toBeDisabled();
    fireEvent.click(within(net).getByRole("button", { name: "Move earlier" }));
    expect((onChange.mock.calls.at(-1)![0] as CockpitSpec).elements["sec-headline"].children)
      .toEqual(["alert-rate", "card-net", "card-rate"]);
  });

  it("renames a section when the name is left, and not for an empty name", () => {
    const onChange = arrange();
    const [headline] = screen.getAllByTestId("arrange-section-name");
    fireEvent.change(headline, { target: { value: "At a glance" } });
    fireEvent.blur(headline);
    expect((onChange.mock.calls.at(-1)![0] as CockpitSpec).elements["sec-headline"].props.title).toBe("At a glance");

    onChange.mockClear();
    fireEvent.change(headline, { target: { value: "   " } });
    fireEvent.blur(headline);
    expect(onChange).not.toHaveBeenCalled();
    expect((headline as HTMLInputElement).value).toBe("Headline");            // put back, not blanked
  });
});
