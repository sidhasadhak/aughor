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
  /** DS-17b — the gated rows now sit behind a counted fold, so a test about how a gated
   *  row LOOKS has to open it first. What these three guard is unchanged: a row whose
   *  object is missing must look different, say why, and offer no affordance that fails. */
  async function openGated() {
    fireEvent.click(await screen.findByTestId("palette-gated-toggle-action"));
  }

  it("dims a row whose object does not exist here, and says why in place", async () => {
    mount();
    await openGated();
    const reason = await screen.findByTestId("palette-reason-slack_post");
    expect(reason.textContent).toContain("No Slack bots configured");
  });

  it("offers no add control on a row that cannot be used", async () => {
    mount();
    await openGated();
    await screen.findByTestId("palette-row-slack_post");
    // An affordance that fails is worse than an absent one — the same law the rail
    // enforces by ABSENCE for the last remaining step.
    expect(screen.queryByLabelText("Add Post to Slack to the canvas")).toBeNull();
    expect(screen.getByLabelText("Add Notify to the canvas")).toBeTruthy();
  });

  it("does not let an unusable row be dragged either", async () => {
    mount();
    await openGated();
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

/* ── DS-1 P1 · the binding filter ───────────────────────────────────────────── */

describe("the binding filter", () => {
  const CONSUMERLESS = ENTRY({
    kind: "metric_value", label: "Governed metric", icon: "gauge", priority: 30,
    publishes: ["value", "unit", "label"], bindable: [],
  });

  it("shows only steps with an input port, and names the value on a banner", async () => {
    getAutomationPalette.mockImplementation(async () => [...ROWS, CONSUMERLESS]);
    mount({ bindFilter: { ref: "numbers.answer" } });
    expect(await screen.findByTestId("palette-bind-banner")).toHaveTextContent("numbers.answer");
    expect(screen.getByTestId("palette-row-notify")).toBeInTheDocument();
    // No input port ⇒ not offered: an edge onto it is one the engine will not follow.
    expect(screen.queryByTestId("palette-row-metric_value")).not.toBeInTheDocument();
    // A trigger cannot consume anything — the whole group is out by construction.
    expect(screen.queryByTestId("palette-row-schedule")).not.toBeInTheDocument();
  });

  it("the banner's × clears the filter and keeps the palette", async () => {
    const onClear = vi.fn();
    mount({ bindFilter: { ref: "numbers.answer" }, onClearBindFilter: onClear });
    fireEvent.click(await screen.findByLabelText("Clear the binding filter"));
    expect(onClear).toHaveBeenCalled();
  });

  it("no filter, no banner — a narrowed list must never be silent about it", async () => {
    mount();
    await screen.findByTestId("palette-row-notify");
    expect(screen.queryByTestId("palette-bind-banner")).not.toBeInTheDocument();
  });
});

describe("the three-key sort", () => {
  it("a label hit outranks a description hit at equal priority", async () => {
    const { searchScore } = await import("@/components/automations/AutomationPalette");
    const labelHit = ENTRY({ label: "Post to Slack" });
    const descHit = ENTRY({ label: "Notify", description: "post through a trigger" });
    expect(searchScore(labelHit, "post")).toBeLessThan(searchScore(descHit, "post"));
    // And a prefix beats a mere substring.
    expect(searchScore(labelHit, "post")).toBeLessThan(
      searchScore(ENTRY({ label: "Repost" }), "post"));
  });
});

/**
 * DS-17b — the defect that produced §3.7's second movement: a step that SHIPS, gated on
 * this connection, read as a missing feature because it sat below the fold.
 *
 * 🔑 The first draft of this suite ranked availability and called it fixed. The mutation
 * run said otherwise: the FALSIFIER stayed green against the pre-fix sort, because the
 * fixture happened to give every gated kind the highest priority, so both orders agreed.
 * The real palette does not look like that — `notify` (30), `brief` (40) and
 * `integration_call` (70) are gated and sit ABOVE four runnable kinds. The fixture below
 * is the measured live shape, and the arithmetic it exposed is why this wave needed a
 * second half: `trusted_query` is the 9th of 10 rows under BOTH orders, so ranking alone
 * moved it exactly nowhere.
 */
const ACTIONS: AutomationPaletteEntry[] = [
  ENTRY({ kind: "investigate", label: "Investigate", priority: 10 }),
  ENTRY({ kind: "slack_post", label: "Post to Slack", priority: 20 }),
  ENTRY({ kind: "notify", label: "Notify", priority: 30, availability: "needs_setup",
          reason: "No notification triggers configured — create one first." }),
  ENTRY({ kind: "brief", label: "Deliver briefing", priority: 40,
          availability: "needs_setup",
          reason: "No briefing subscriptions on this connection — create one first." }),
  ENTRY({ kind: "kinetic_action", label: "Declared action", priority: 50 }),
  ENTRY({ kind: "subchain", label: "Run a chain", priority: 60 }),
  ENTRY({ kind: "integration_call", label: "Use an integration", priority: 70,
          availability: "needs_setup",
          reason: "No connected accounts — connect one under Integrations." }),
  ENTRY({ kind: "metric_value", label: "Governed metric", priority: 80 }),
  ENTRY({ kind: "trusted_query", label: "Trusted query", priority: 90,
          availability: "needs_setup",
          reason: "No trusted queries on this connection — promote a verified answer first." }),
  ENTRY({ kind: "mcp_call", label: "Call an MCP tool", priority: 95,
          availability: "needs_setup",
          reason: "No MCP servers on this deployment — add one under MCP servers." }),
];

describe("a gated row ranks below what this deployment can run", () => {
  it("THE FALSIFIER, on the measured live shape: no gated row precedes a runnable one",
    async () => {
      const { ordered } = await import("@/components/automations/AutomationPalette");
      const kinds = ordered(ACTIONS, "").map(e => e.kind);
      expect(kinds).toEqual([
        // the five this connection can run, in the server's curated order…
        "investigate", "slack_post", "kinetic_action", "subchain", "metric_value",
        // …then the five it cannot, keeping theirs.
        "notify", "brief", "integration_call", "trusted_query", "mcp_call",
      ]);
      // Stated as the property, so a future fixture cannot satisfy it by accident.
      const ranks = ordered(ACTIONS, "").map(e => e.availability === "ready" ? 0 : 1);
      expect(ranks).toEqual([...ranks].sort((a, b) => a - b));
    });

  it("the curated order still decides WITHIN each group", async () => {
    const { ordered } = await import("@/components/automations/AutomationPalette");
    const kinds = ordered(ACTIONS, "").map(e => e.kind);
    expect(kinds.indexOf("slack_post")).toBeLessThan(kinds.indexOf("metric_value"));
    expect(kinds.indexOf("notify")).toBeLessThan(kinds.indexOf("trusted_query"));
  });

  it("a TYPED query outranks availability — the person named the thing", async () => {
    const { ordered } = await import("@/components/automations/AutomationPalette");
    // "trusted" hits Trusted query's LABEL and nothing else's, so it must lead despite
    // being gated and despite carrying the second-lowest curated weight on the panel.
    expect(ordered(ACTIONS, "trusted").map(e => e.kind)[0]).toBe("trusted_query");
  });

  it("relevance outranks the curated weight — the second defect this wave found",
    async () => {
      const { ordered } = await import("@/components/automations/AutomationPalette");
      // Both READY, so availability is not what is measured here: a low-priority
      // description hit must not outrank the label the person actually typed.
      const rows = [
        ENTRY({ kind: "notify", label: "Notify", priority: 10,
                description: "send a trusted message" }),
        ENTRY({ kind: "trusted_query", label: "Trusted query", priority: 90,
                description: "run a vetted query" }),
      ];
      expect(ordered(rows, "trusted").map(e => e.kind)).toEqual(["trusted_query", "notify"]);
      expect(ordered(rows, "").map(e => e.kind)).toEqual(["notify", "trusted_query"]);
    });
});

/**
 * The half the ranking could not do. Ranking made the gated rows contiguous; it did not
 * make them cost less vertical space, and space was the actual mechanism — three
 * multi-line prereq sentences between the top of the list and the row being looked for.
 */
describe("the gated rows collapse behind one counted line", () => {
  const mountWith = (rows: AutomationPaletteEntry[]) => {
    getAutomationPalette.mockImplementation(async () => rows);
    return mount();
  };

  it("a gated row is not rendered until the fold is opened, and its count is stated",
    async () => {
      mountWith(ACTIONS);
      await screen.findByTestId("palette-row-subchain");
      // The five runnable ones are there…
      expect(screen.getByTestId("palette-row-metric_value")).toBeInTheDocument();
      // …the five gated ones are not, and the panel SAYS so rather than going quiet.
      expect(screen.queryByTestId("palette-row-trusted_query")).not.toBeInTheDocument();
      const toggle = screen.getByTestId("palette-gated-toggle-action");
      expect(toggle).toHaveTextContent("5 steps need setup");
      expect(toggle).toHaveAttribute("aria-expanded", "false");

      fireEvent.click(toggle);
      expect(await screen.findByTestId("palette-row-trusted_query")).toBeInTheDocument();
      expect(screen.getByTestId("palette-gated-toggle-action"))
        .toHaveAttribute("aria-expanded", "true");
    });

  it("an opened row keeps the sentence that is its only door", async () => {
    mountWith(ACTIONS);
    fireEvent.click(await screen.findByTestId("palette-gated-toggle-action"));
    expect(await screen.findByTestId("palette-reason-trusted_query"))
      .toHaveTextContent("promote a verified answer first");
  });

  it("SEARCHING never hides a match behind the fold", async () => {
    mountWith(ACTIONS);
    await screen.findByTestId("palette-row-subchain");
    fireEvent.change(screen.getByPlaceholderText("Search steps…"),
      { target: { value: "trusted" } });
    // Typed the name, got the row — no fold, no toggle, no second click.
    expect(await screen.findByTestId("palette-row-trusted_query")).toBeInTheDocument();
    expect(screen.queryByTestId("palette-gated-toggle-action")).not.toBeInTheDocument();
  });

  it("no gated rows, no fold — the panel never invents an empty one", async () => {
    mountWith(ACTIONS.filter(e => e.availability === "ready"));
    await screen.findByTestId("palette-row-subchain");
    expect(screen.queryByTestId("palette-gated-toggle-action")).not.toBeInTheDocument();
  });
});
