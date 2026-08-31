// @vitest-environment jsdom
/**
 * DS-1 — the palette tells the truth about THIS deployment, and adds through one gate.
 *
 * The property worth guarding is the one the panel exists for: a row whose object does
 * not exist here must look different from one whose object does, and must say why. Before
 * this, every deployment was offered every kind and found out at save — which is the
 * shape of failure §3.4's alt-door rule was written against.
 *
 * The other is the gate. A click and a drop are two affordances over one code path; if
 * they ever become two, one of them will keep adding steps a refusal no longer sees.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  AutomationPalette, readPaletteDrag,
} from "@/components/automations/AutomationPalette";
import type { AutomationPaletteEntry } from "@/lib/api";

const ENTRY = (over: Partial<AutomationPaletteEntry> = {}): AutomationPaletteEntry => ({
  kind: "notify", group: "action", label: "Notify",
  description: "Send through a Notifications trigger", icon: "bell", priority: 10,
  publishes: ["sent_at"], bindable: ["message"],
  availability: "ready", reason: "", ...over,
});

const ROWS: AutomationPaletteEntry[] = [
  ENTRY(),
  ENTRY({
    kind: "slack_post", label: "Post to Slack", icon: "send", priority: 20,
    description: "Post into a channel as one of your bots",
    publishes: ["ts", "channel"], bindable: ["message"],
    availability: "needs_setup",
    reason: "No Slack bots configured — create one first, then this step can post as it.",
  }),
  ENTRY({ kind: "schedule", group: "trigger", label: "Schedule", icon: "clock",
          priority: 10, publishes: [], bindable: [] }),
];

const getAutomationPalette = vi.fn(async () => ROWS);

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  getAutomationPalette: (...args: unknown[]) => getAutomationPalette(...(args as [])),
}));

beforeEach(() => {
  getAutomationPalette.mockClear();
  getAutomationPalette.mockImplementation(async () => ROWS);
});

function mount(props: Partial<React.ComponentProps<typeof AutomationPalette>> = {}) {
  const onAdd = vi.fn();
  render(<AutomationPalette onAdd={onAdd} onClose={() => {}} {...props} />);
  return onAdd;
}

describe("what the deployment can actually do", () => {
  it("dims a row whose object does not exist here, and says why in place", async () => {
    mount();
    const reason = await screen.findByTestId("palette-reason-slack_post");
    expect(reason.textContent).toContain("No Slack bots configured");
  });

  it("offers no add control on a row that cannot be used", async () => {
    mount();
    await screen.findByTestId("palette-row-slack_post");
    // An affordance that fails is worse than an absent one — the same law the rail
    // enforces by ABSENCE for the last remaining step.
    expect(screen.queryByLabelText("Add Post to Slack to the canvas")).toBeNull();
    expect(screen.getByLabelText("Add Notify to the canvas")).toBeTruthy();
  });

  it("does not let an unusable row be dragged either", async () => {
    mount();
    const row = await screen.findByTestId("palette-row-slack_post");
    expect(row.getAttribute("draggable")).toBe("false");
  });

  it("says what a step gives, so the next binding is visible before it is placed", async () => {
    mount();
    const row = await screen.findByTestId("palette-row-notify");
    expect(row.textContent).toContain("sent_at");
  });

  it("scopes the request to the automation's connection", async () => {
    mount({ connId: "conn-7" });
    await waitFor(() => expect(getAutomationPalette).toHaveBeenCalledWith("conn-7"));
  });
});

describe("the one add gate", () => {
  it("adds on click with no position — 'wherever I am looking'", async () => {
    const onAdd = mount();
    fireEvent.click(await screen.findByLabelText("Add Notify to the canvas"));
    expect(onAdd).toHaveBeenCalledWith({ kind: "notify", group: "action" });
  });

  it("hands a drag the same two facts a click does", async () => {
    mount();
    const row = await screen.findByTestId("palette-row-notify");
    const data: Record<string, string> = {};
    fireEvent.dragStart(row, {
      dataTransfer: { setData: (t: string, v: string) => { data[t] = v; }, effectAllowed: "" },
    });
    // Whatever the canvas reads back must be exactly what the click path sends, or the
    // two affordances are two gates wearing one name.
    expect(readPaletteDrag(Object.values(data)[0]))
      .toEqual({ kind: "notify", group: "action" });
  });
});

describe("readPaletteDrag", () => {
  it("refuses a drop that is not ours rather than guessing", () => {
    expect(readPaletteDrag(null)).toBeNull();
    expect(readPaletteDrag("")).toBeNull();
    expect(readPaletteDrag("a file from the desktop")).toBeNull();
    expect(readPaletteDrag('{"kind":"notify"}')).toBeNull();      // no group
    expect(readPaletteDrag('{"kind":"x","group":"nope"}')).toBeNull(); // not a group
  });
});

describe("finding a step", () => {
  it("searches the description, not only the name", async () => {
    mount();
    await screen.findByTestId("palette-row-notify");
    fireEvent.change(screen.getByLabelText("Search the palette"), {
      target: { value: "notifications" },  // only Notify's DESCRIPTION says this
    });
    expect(screen.getByTestId("palette-row-notify")).toBeTruthy();
    expect(screen.queryByTestId("palette-row-slack_post")).toBeNull();
  });

  it("says so when nothing matches", async () => {
    mount();
    await screen.findByTestId("palette-row-notify");
    fireEvent.change(screen.getByLabelText("Search the palette"),
                     { target: { value: "zzzz" } });
    expect(screen.getByText(/Nothing matches/)).toBeTruthy();
  });

  it("narrows to one half when opened from Add Trigger", async () => {
    mount({ only: "trigger" });
    await screen.findByTestId("palette-row-schedule");
    expect(screen.queryByTestId("palette-row-notify")).toBeNull();
  });

  it("says nothing matches when the hit is in the OTHER half", async () => {
    // Found by driving it: the empty state was computed over every entry, so a query
    // that matched only an Action while Triggers were shown rendered no rows, no
    // heading and no message — a panel that looks broken rather than empty.
    mount({ only: "trigger" });
    await screen.findByTestId("palette-row-schedule");
    fireEvent.change(screen.getByLabelText("Search the palette"),
                     { target: { value: "channel" } });  // matches Post to Slack only
    expect(screen.queryByTestId("palette-row-slack_post")).toBeNull();
    expect(screen.getByText(/Nothing matches/)).toBeTruthy();
  });

  it("clears a stale search when the canvas swaps which half is shown", async () => {
    const { rerender } = render(
      <AutomationPalette only="action" onAdd={vi.fn()} onClose={() => {}} />);
    await screen.findByTestId("palette-row-notify");
    fireEvent.change(screen.getByLabelText("Search the palette"),
                     { target: { value: "channel" } });
    rerender(<AutomationPalette only="trigger" onAdd={vi.fn()} onClose={() => {}} />);
    await waitFor(() => expect(screen.getByTestId("palette-row-schedule")).toBeTruthy());
  });
});

describe("when the palette itself cannot load", () => {
  it("does not read as a platform with nothing in it", async () => {
    getAutomationPalette.mockImplementation(async () => { throw new Error("offline"); });
    mount();
    // The failure mode this replaces: an empty column, indistinguishable from a
    // deployment that genuinely offers no steps.
    expect(await screen.findByText(/Could not load the palette/)).toBeTruthy();
  });
});
