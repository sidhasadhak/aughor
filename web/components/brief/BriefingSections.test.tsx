// @vitest-environment jsdom

/**
 * The Briefing's switches (B1): a section shown or hidden, moved, the cockpit that rides with
 * the Briefing, and a change asked for in words — each lands as the next preference, through
 * `onChange`, and words land only once kept.
 */
import { change, fireEvent, render, screen, within } from "@/lib/testing";
import { describe, expect, it, vi } from "vitest";

import { BriefingSections, HiddenSection } from "@/components/brief/BriefingSections";
import { DEFAULT_SECTIONS, type BriefingSectionsPref } from "@/lib/briefingSections";

const COCKPITS = [{ id: "growth-1", title: "Growth review" }, { id: "returns-2", title: "Returns" }];
const order = (p: BriefingSectionsPref) => p.sections.map(s => `${s.id}${s.on ? "" : ":off"}`);

function show(pref = DEFAULT_SECTIONS, cockpitsOn = true) {
  const onChange = vi.fn();
  render(<BriefingSections pref={pref} onChange={onChange} cockpits={COCKPITS} cockpitsOn={cockpitsOn} />);
  return onChange;
}

describe("the switches", () => {
  it("lists the six sections in order, each with its switch, and hides one on a click", () => {
    const onChange = show();
    const rows = screen.getAllByTestId("briefing-section-switch");
    expect(rows.map(r => r.dataset.section)).toEqual(["verdict", "key_metrics", "findings", "synthesis", "cockpit", "patterns"]);
    fireEvent.click(within(rows[2]).getByRole("checkbox", { name: "Show Findings" }));
    const [next, said] = onChange.mock.calls[0] as [BriefingSectionsPref, string];
    expect(order(next)).toEqual(["verdict", "key_metrics", "findings:off", "synthesis", "cockpit", "patterns"]);
    expect(said).toBe("Hidden: Findings.");
  });

  it("moves a section, and the first cannot go up", () => {
    const onChange = show();
    const rows = screen.getAllByTestId("briefing-section-switch");
    expect(within(rows[0]).getByRole("button", { name: "Move Verdict and largest moves up" })).toBeDisabled();
    fireEvent.click(within(rows[3]).getByRole("button", { name: "Move Full synthesis up" }));
    expect(order(onChange.mock.calls[0][0] as BriefingSectionsPref)).toEqual(["verdict", "key_metrics", "synthesis", "findings", "cockpit", "patterns"]);
  });

  it("names the cockpit that rides with the Briefing, only where cockpits are on", () => {
    const onChange = show();
    change(screen.getByTestId("briefing-strip-pick"), { target: { value: "growth-1" } });
    expect(onChange.mock.calls[0][0]).toEqual({ ...DEFAULT_SECTIONS, strip: "growth-1" });
    expect(onChange.mock.calls[0][1]).toBe("“Growth review” rides with your Briefing.");
  });

  it("with cockpits off there is no cockpit to choose", () => {
    show(DEFAULT_SECTIONS, false);
    expect(screen.queryByTestId("briefing-strip-pick")).toBeNull();
  });
});

describe("in words", () => {
  it("proposes what the words come to, and keeps it only on Keep", () => {
    const onChange = show();
    fireEvent.change(screen.getByRole("textbox", { name: "Ask for a change in words" }), { target: { value: "hide the findings, put the synthesis first" } });
    fireEvent.click(screen.getByRole("button", { name: "Propose" }));
    const proposal = screen.getByTestId("briefing-switch-proposal");
    expect(proposal).toHaveTextContent("Hide “Findings”");
    expect(proposal).toHaveTextContent("Put “Full synthesis” first");
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.click(within(proposal).getByRole("button", { name: "Keep it" }));
    expect(order(onChange.mock.calls[0][0] as BriefingSectionsPref)).toEqual(["synthesis", "verdict", "key_metrics", "findings:off", "cockpit", "patterns"]);
    expect(screen.queryByTestId("briefing-switch-proposal")).toBeNull();
  });

  it("says what it could not read, and writes nothing", () => {
    const onChange = show();
    fireEvent.change(screen.getByRole("textbox", { name: "Ask for a change in words" }), { target: { value: "write me a note" } });
    fireEvent.keyDown(screen.getByRole("textbox", { name: "Ask for a change in words" }), { key: "Enter" });
    expect(screen.getByTestId("briefing-switch-refused")).toHaveTextContent("Not read as a Briefing switch");
    expect(onChange).not.toHaveBeenCalled();
  });
});

describe("a hidden section", () => {
  it("leaves one line saying so, and the way back", () => {
    const onShow = vi.fn();
    render(<HiddenSection id="findings" onShow={onShow} />);
    expect(screen.getByTestId("briefing-section-hidden")).toHaveTextContent("Findings is hidden.");
    fireEvent.click(screen.getByRole("button", { name: "Show it" }));
    expect(onShow).toHaveBeenCalled();
  });
});
