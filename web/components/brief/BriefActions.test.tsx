// @vitest-environment jsdom
// CB-6 / CB-7 — the line under a cited finding: the goal it bears on and the one action beside it.
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { BriefActions } from "./BriefActions";

const base = { insight_id: "i", domain: "ops", angle: "returns", finding: "f" };

describe("BriefActions", () => {
  it("names the goal and the play with its learned rate, and nothing for a bare citation", () => {
    render(<BriefActions citations={[
      { ...base, ref: "1", priority: "return rate", action: { kind: "play", text: "Pause the two lowest-margin carriers", why: "the playbook's best play", executable: false, success_rate: 0.8 } },
      { ...base, ref: "2" },
    ]} />);
    const list = screen.getByTestId("brief-actions");
    expect(list.textContent).toContain("bears on the goal: return rate");
    expect(list.textContent).toContain("Pause the two lowest-margin carriers");
    expect(list.textContent).toContain("worked 80% of the time");
    expect(list.querySelectorAll("li")).toHaveLength(1);
  });

  it("an executable recommendation is taken in place, through the gate, and says only what happened", async () => {
    const calls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      calls.push(`${init?.method ?? "GET"} ${url}`);
      if (url.endsWith("/actions/triggers")) return new Response(JSON.stringify({ triggers: [
        { id: "t1", name: "Ops Slack", enabled: true }, { id: "t2", name: "Off", enabled: false }] }));
      return new Response(JSON.stringify({ status: "failed", error: "webhook 500" }));
    }));
    render(<BriefActions citations={[
      { ...base, ref: "1", action: { kind: "recommendation", text: "Move the cut-off", why: "the first recommendation of the deep analysis it came from", executable: true, inv_id: "inv9", rec_index: 2 } },
    ]} />);
    fireEvent.click(screen.getByText("Take this action →"));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Ops Slack" }));
    // A delivery the trigger reports as failed is NOT "sent" — the inbox's copy said ✓ for it.
    expect(await screen.findByText(/Not sent — Ops Slack: failed — webhook 500/)).toBeInTheDocument();
    expect(calls.at(-1)).toMatch(/^POST .*\/investigations\/inv9\/recommendations\/2\/execute$/);
    expect(screen.queryByRole("menuitem", { name: "Off" })).toBeNull();
    vi.unstubAllGlobals();
  });

  it("renders nothing when no citation carries a goal or an action", () => {
    const { container } = render(<BriefActions citations={[{ ...base, ref: "1" }]} />);
    expect(container.textContent).toBe("");
  });
});
