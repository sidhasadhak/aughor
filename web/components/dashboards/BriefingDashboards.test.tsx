// @vitest-environment jsdom

/**
 * BriefingDashboards (Arc CT, CT-7 to CT-10): a person's dashboards, the Dashboards tab beside the Briefing.
 *
 * The API is stood in for, and the dashboard's own drawing (`ComposedDashboard`, tested on its own)
 * is a stub that records what it was handed. What is asserted is what this component asks the
 * server to do, and what it hands on.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { act, choose, fireEvent, optionsOf, render, screen, waitFor, within } from "@/lib/testing";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BriefingDashboards } from "@/components/dashboards/BriefingDashboards";
import type { BriefingRangeBlock, DashboardList, PersonDashboard } from "@/lib/api";

const api = vi.hoisted(() => ({
  listDashboards: vi.fn(), getDashboard: vi.fn(), runCard: vi.fn(), keepDashboard: vi.fn(),
  startMyDashboard: vi.fn(), draftDashboard: vi.fn(), getProposalById: vi.fn(), acceptProposal: vi.fn(), uploadDashboardImage: vi.fn(),
  listSharedDashboards: vi.fn(), getSharedDashboard: vi.fn(), copySharedDashboard: vi.fn(), dashboardAudiences: vi.fn(),
  publishDashboard: vi.fn(), unpublishDashboard: vi.fn(), askDashboard: vi.fn(), listFindingsByDomain: vi.fn(), pinFinding: vi.fn(),
  rejectProposal: vi.fn(), moveCanvasDashboard: vi.fn(), restoreDashboard: vi.fn(), retireDashboard: vi.fn(),
  getSystemFlags: vi.fn(), measureRange: vi.fn(), readExpectedNext: vi.fn(), getDeclaredActions: vi.fn(),
  getSuggestedShapes: vi.fn(), getDashboardFromObject: vi.fn(), getGroups: vi.fn(),
  keepDashboardQuery: vi.fn(), previewDashboardQuery: vi.fn(), getCatalogTree: vi.fn(),
  listPackTemplates: vi.fn(), draftFromPackTemplate: vi.fn(),
}));
const drawn = vi.hoisted(() => ({ props: [] as Record<string, unknown>[] }));
const ontology = vi.hoisted(() => ({ getProcesses: vi.fn() }));
vi.mock("@/lib/objectTypes", async (original) => ({ ...(await original<typeof import("@/lib/objectTypes")>()), ...ontology }));
// the builder names entities from the object catalog: never read from a live API in a test
vi.mock("@/lib/objects", async (original) => ({ ...(await original<typeof import("@/lib/objects")>()), cachedObjectCatalog: vi.fn(async () => null) }));
const toasts = vi.hoisted(() => ({ error: vi.fn(), success: vi.fn() }));
vi.mock("@/components/ui/toast", async (original) => ({ ...(await original<typeof import("@/components/ui/toast")>()), toast: toasts }));
const composer = vi.hoisted(() => ({ onCreated: null as null | (() => void) }));

vi.mock("@/lib/api", async (original) => ({ ...(await original<typeof import("@/lib/api")>()), ...api }));
vi.mock("@/components/dashboards/ComposedDashboard", () => ({
  ComposedDashboard: (props: Record<string, unknown>) => { drawn.props.push(props); return <div data-testid="composed-stub" />; },
}));
vi.mock("@/components/brief/NewCardComposer", () => ({
  NewCardComposer: ({ onCreated }: { onCreated: () => void }) => { composer.onCreated = onCreated; return <div data-testid="composer-stub" />; },
}));

const SPEC = JSON.parse(readFileSync(resolve(process.cwd(), "lib/dashboards/premise.fixture.json"), "utf8"));
const card = (id: string, title: string, own = true) => ({
  id, title, kind: "kpi", own, connection_id: "thelook", scope: own ? "user" : "connection", scope_ref: "default",
  source: "authored", sql: "SELECT 1", thresholds: {}, provenance: {}, links: [], render: {},
}) as unknown as PersonDashboard["cards"][number];

const version = (n: number, extra: Record<string, unknown> = {}) => ({
  version: n, artifact_id: `a${n}`, kept_at: "2026-09-28T15:14:39Z", current: true, retired: false,
  approved_by: "person", source: "a person's own hand", note: "", vocabulary_version: 1,
  written_by_model: false, cards: [], changes: { added: [], removed: [], changed: [] }, ...extra,
});

const LIST: DashboardList = {
  person: "default", shared_cards: 1, own_cards: 2, from_canvases: [],
  cockpits: [
    { ...version(3), cockpit_id: "returns-1", title: "Returns", started_at: "2026-09-28T10:00:00Z" },
    { ...version(1), cockpit_id: "pricing-1", title: "Pricing", started_at: "2026-09-28T11:00:00Z" },
  ],
};

const READ: PersonDashboard = {
  connection_id: "thelook", owner: "default", cockpit_id: "returns-1",
  cockpit: { ...version(3), spec: SPEC },
  cards: [card("c7f3a001", "Return rate"), card("c91b2002", "Net merchandise revenue"), card("cafe0003", "Pinned for everyone", false)],
  range: { status: "standing", preset: null, start: null, last_day: null, covers: "", as_of: null, lag_days: null, still_moving: [] },
  history: [version(3), { ...version(2), current: false }, { ...version(1), current: false }],
};

const MEASURED = {
  period: "month", key: "range:previous_month:2026-08-01..2026-08-31", preset: "previous_month", label: "Last month",
  start: "2026-08-01", end: "2026-09-01", last_day: "2026-08-31", previous_start: "2026-07-01", previous_end: "2026-08-01",
  last_year_start: null, last_year_end: null, as_of: "2026-10-05", lag_days: 1, lag_source: "default", still_moving: [],
  covers: "August 2026", compared_with: "July 2026", last_year_label: null, unmeasured: [],
  measured: [{
    name: "Revenue", metric: "revenue", unit: "USD", time_kind: "flow", confirmed: true, current: 110, previous: 100,
    last_year: null, rel: 0.1, rel_last_year: null, status: "final", current_text: "$110", previous_text: "$100",
  }],
} as unknown as BriefingRangeBlock;

const show = () => render(<BriefingDashboards connectionId="thelook" schema="thelook" />);
/** Arc AP-1 — the dashboard opened in the builder. */
const openBuilder = async () => {
  show();
  fireEvent.click(await screen.findByTestId("dashboard-edit"));
  await screen.findByTestId("dashboard-builder");
};
/** The strip's tabs by name — a Themes tab carries its label twice (one copy hidden), so read the visible one. */
const stripTabs = () => screen.getAllByRole("tab").map(t => t.querySelector(".rt-TabsTriggerInner")?.textContent);

beforeEach(() => {
  for (const f of Object.values(api)) f.mockReset();
  toasts.error.mockReset();
  drawn.props.length = 0;
  composer.onCreated = null;
  try { localStorage.clear(); } catch { /* jsdom */ }
  // A person who left off on a dashboard of their own. Nothing remembered opens the metrics —
  // the last block below.
  localStorage.setItem("aughor:cockpit:thelook", "returns-1");
  api.getSystemFlags.mockResolvedValue({});
  api.getGroups.mockResolvedValue({ ladder: [], builtin_groups: [], groups: [] });
  api.listDashboards.mockResolvedValue(LIST);
  api.listSharedDashboards.mockResolvedValue([]);
  api.getDashboard.mockResolvedValue(READ);
  api.runCard.mockResolvedValue({ columns: ["_v"], rows: [["10.03"]], row_count: 1 });
  api.keepDashboard.mockResolvedValue({ status: "kept", kept: true, version: 4, artifact_id: "a4", sentences: [] });
  api.measureRange.mockResolvedValue({ period: MEASURED, from_briefing: false, measured_at: "2026-10-05T09:00:00Z", scope_key: "thelook:thelook" });
  api.readExpectedNext.mockResolvedValue({ why: "", target: { start: "2026-09-01", last_day: "2026-09-30", label: "2026-09-01 to 2026-09-30", settles_on: "2026-10-01" },
    items: [{ metric: "revenue", name: "Revenue", why: "", expected: { claim_id: "p1", low: 100, mid: 108, high: 116, text: "$100 to $116", state: "open", scored_against: null, must_say: ["6 earlier ranges"], n: 6 } }] });
});

describe("a person's dashboards", () => {
  it("lists them in a strip and draws the one the person left off on, each card it places run for the month", async () => {
    show();
    await waitFor(() => expect(drawn.props.length).toBeGreaterThan(0));
    expect(stripTabs()).toEqual(["Metrics", "Returns", "Pricing"]);
    expect(api.getDashboard).toHaveBeenCalledWith("thelook", "returns-1", { preset: "previous_month" });
    // Only the cards the spec places are run — the pinned card it does not place is not.
    expect(api.runCard.mock.calls.map(c => c[0]).sort()).toEqual(["c7f3a001", "c91b2002"]);
    expect(api.runCard.mock.calls[0][1]).toEqual({ preset: "previous_month" });
    const last = drawn.props.at(-1)!;
    expect(last.spec).toEqual(SPEC);
    expect(last.sym).toBe("$");
    // The version is said in the history, not above the cards.
    expect(screen.queryByTestId("dashboard-version")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /History/ }));
    expect(screen.getByTestId("dashboard-version")).toHaveTextContent("Version 3 · kept by person");
  });

  it("opens on last month and asks each card how it moved against the one before", async () => {
    api.getDashboard.mockResolvedValue({ ...READ, currency_symbol: "€",
      range: { ...READ.range, status: "final", preset: "last_month", covers: "July 2026" } });
    show();
    await waitFor(() => expect(api.getDashboard).toHaveBeenCalledWith("thelook", "returns-1", { preset: "previous_month" }));
    await waitFor(() => expect(api.runCard).toHaveBeenCalledWith("c7f3a001", { preset: "previous_month" }, { compare: true }));
    // Never first read as written: that run would roll every card's standing value.
    expect(api.getDashboard).not.toHaveBeenCalledWith("thelook", "returns-1", null);
    expect(await screen.findByTestId("dashboard-range")).toHaveTextContent("July 2026 · final");
    await waitFor(() => expect(drawn.props.at(-1)!.sym).toBe("€"));
  });

  it("opens the one the person chose last time", async () => {
    localStorage.setItem("aughor:cockpit:thelook", "pricing-1");
    show();
    await waitFor(() => expect(api.getDashboard).toHaveBeenCalledWith("thelook", "pricing-1", { preset: "previous_month" }));
  });

  it("'Remove' on a card takes it off THIS dashboard and keeps the card", async () => {
    await openBuilder();
    await waitFor(() => expect((drawn.props.at(-1)?.doors as { onRemove?: unknown } | undefined)?.onRemove).toBeTypeOf("function"));
    const doors = drawn.props.at(-1)!.doors as { onRemove: (id: string) => void };
    act(() => { doors.onRemove("c91b2002"); });
    await waitFor(() => expect(api.keepDashboard).toHaveBeenCalled(), { timeout: 3000 });
    const [conn, id, spec, note] = api.keepDashboard.mock.calls[0];
    expect([conn, id, note]).toEqual(["thelook", "returns-1", "a card taken off"]);
    expect(JSON.stringify(spec)).not.toContain("c91b2002");
  });

  it("a card pinned from here lands on the dashboard in view", async () => {
    await openBuilder();
    expect(screen.queryByTestId("composer-stub")).toBeNull();
    fireEvent.click(screen.getByTestId("dashboard-card-new"));
    await waitFor(() => expect(composer.onCreated).not.toBeNull());
    api.getDashboard.mockResolvedValue({ ...READ, cards: [...READ.cards, card("fresh0001", "Just pinned", false)] });
    composer.onCreated!();
    await waitFor(() => expect(api.keepDashboard).toHaveBeenCalled());
    const [, , spec, note] = api.keepDashboard.mock.calls[0];
    expect(note).toBe("a card pinned from the Briefing");
    expect(JSON.stringify(spec)).toContain("fresh0001");
    expect(JSON.stringify(spec)).not.toContain("cafe0003");                  // the one already there is not
  });
});

describe("a retired dashboard", () => {
  it("is retired from the toolbar, after one confirmation — not from inside History, where it read as absent", async () => {
    api.retireDashboard.mockResolvedValue({ status: "kept", kept: true, version: 4, artifact_id: "a4", sentences: [] });
    await openBuilder();
    fireEvent.click(screen.getByTestId("dashboard-retire-open"));
    expect(screen.getByTestId("dashboard-retire-confirm").textContent).toContain("its history stays");
    fireEvent.click(screen.getByRole("button", { name: "Keep it" }));
    expect(screen.queryByTestId("dashboard-retire-confirm")).toBeNull();
    expect(api.retireDashboard).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId("dashboard-retire-open"));
    fireEvent.click(screen.getByRole("button", { name: "Retire it" }));
    await waitFor(() => expect(api.retireDashboard).toHaveBeenCalledWith("thelook", "returns-1"));
    fireEvent.click(screen.getByRole("button", { name: /History/ }));
    expect(screen.queryByRole("button", { name: "Retire this dashboard" })).toBeNull();
  });

  it("leaves the strip for good: nothing offers to bring a retired dashboard back (the user, 2026-10-11 — once it's gone it's gone)", async () => {
    api.listDashboards.mockResolvedValue({ ...LIST, cockpits: [LIST.cockpits[0], { ...LIST.cockpits[1], retired: true, version: 4, title: "Pricing" }] });
    show();
    await waitFor(() => expect(stripTabs()).toEqual(["Metrics", "Returns"]));
    expect(screen.queryByText(/Retired:|Pricing/)).toBeNull();
    expect(screen.queryByRole("button", { name: /Bring back/ })).toBeNull();
    fireEvent.click(await screen.findByTestId("dashboard-edit"));
    fireEvent.click(await screen.findByTestId("dashboard-retire-open"));
    expect(screen.getByTestId("dashboard-retire-confirm")).toHaveTextContent("It leaves your strip for good and cannot be brought back");
    expect(api.restoreDashboard).not.toHaveBeenCalled();
  });
});

describe("with no dashboards yet", () => {
  it("offers to start 'My dashboard' from the cards already pinned, with no model", async () => {
    api.listDashboards.mockResolvedValue({ ...LIST, cockpits: [] });
    api.startMyDashboard.mockResolvedValue({ status: "kept", kept: true, version: 1, artifact_id: "a1", sentences: [], cockpit_id: "my-cockpit" });
    show();
    fireEvent.click(await screen.findByRole("button", { name: "Start “My dashboard” from 3 pinned cards" }));
    await waitFor(() => expect(api.startMyDashboard).toHaveBeenCalledWith("thelook"));
    expect(api.draftDashboard).not.toHaveBeenCalled();
  });

  it("offers to move a dashboard that lived in a Data Canvas", async () => {
    api.listDashboards.mockResolvedValue({ ...LIST, cockpits: [], from_canvases: [{ ...version(3), canvas_id: "d617964b", title: "Executive Dashboard" }] });
    api.moveCanvasDashboard.mockResolvedValue({ moved: true, cockpit_id: "executive-cockpit-1", title: "Executive Dashboard", version: 1, sentences: [] });
    show();
    const offer = await screen.findByTestId("dashboard-move-offer");
    expect(offer).toHaveTextContent("“Executive Dashboard” was kept in a Data Canvas");
    fireEvent.click(within(offer).getByRole("button", { name: "Move it here" }));
    await waitFor(() => expect(api.moveCanvasDashboard).toHaveBeenCalledWith("thelook", "d617964b"));
  });
});

describe("a new dashboard started without a model", () => {
  // The walk-through (2026-10-09): + New dashboard offered only a model's draft, and a dashboard for a process only inside
  // the designer's own session.
  const kept = () => api.keepDashboard.mock.calls.at(-1) as [string, string, { elements: Record<string, { type: string; props: Record<string, unknown>; children: string[] }> }, string];

  it("starts empty — its name and a first note in the person's words — and opens on it", async () => {
    show();
    fireEvent.click(await screen.findByTestId("dashboard-new-open"));
    const startIt = screen.getByTestId("dashboard-start-empty");
    expect(startIt).toBeDisabled();
    expect(screen.getByTestId("dashboard-new")).toHaveTextContent("Name it.");                 // never a silent dead end
    fireEvent.change(screen.getByLabelText("The dashboard's name"), { target: { value: "Carrier performance" } });
    fireEvent.change(screen.getByLabelText("What this dashboard is for — its first note"), { target: { value: "Which carriers miss pickups." } });
    fireEvent.click(startIt);
    await waitFor(() => expect(api.keepDashboard).toHaveBeenCalled());
    const [conn, id, spec, note] = kept();
    expect([conn, note]).toEqual(["thelook", "Started empty"]);
    expect(id).toMatch(/^carrier-performance-[0-9a-f]{6}$/);
    expect(Object.values(spec.elements).map(e => [e.type, e.props])).toEqual([
      ["Cockpit", { title: "Carrier performance" }], ["Section", { title: "Carrier performance", columns: 3 }],
      ["Note", { text: "Which carriers miss pickups." }]]);
    expect(api.draftDashboard).not.toHaveBeenCalled();
  });

  it("starts for a declared process — its board, its overdue objects and one beside them", async () => {
    ontology.getProcesses.mockResolvedValue({ processes: [
      { id: "order_fulfilment", display_name: "Order fulfilment", entity: "order", entity_id: "Order",
        stages: [{ name: "placed", promise: null }, { name: "shipped", promise: { overdue_segment: "overdue_dispatch" } }] },
    ], rules: [] });
    show();
    fireEvent.click(await screen.findByTestId("dashboard-new-open"));
    fireEvent.click(screen.getByTestId("dashboard-new-process"));
    await choose(await screen.findByLabelText("The process"), "order_fulfilment");
    fireEvent.click(screen.getByTestId("dashboard-start-process"));
    await waitFor(() => expect(api.keepDashboard).toHaveBeenCalled());
    const [, id, spec, note] = kept();
    expect(id).toMatch(/^order-fulfilment-[0-9a-f]{6}$/);
    expect(note).toBe("Started from the process Order fulfilment");
    const els = Object.values(spec.elements);
    expect(els.map(e => e.type)).toEqual(["Cockpit", "Section", "ProcessBoard", "ObjectTable", "ObjectDetail"]);
    expect(els[3].props).toEqual({ entity: "Order", segment: "overdue_dispatch", size: "wide" });
  });

  it("says there is no process to start from, and where to design one", async () => {
    ontology.getProcesses.mockResolvedValue({ processes: [], rules: [] });
    show();
    fireEvent.click(await screen.findByTestId("dashboard-new-open"));
    fireEvent.click(screen.getByTestId("dashboard-new-process"));
    expect(await screen.findByTestId("dashboard-new-no-process")).toHaveTextContent("Design one in the Ontology, with New process.");
  });
});

describe("a new dashboard from an area", () => {
  const PROPOSAL = {
    id: "p1", kind: "cockpit_draft", status: "pending", reasoning: "Returns first, then what they cost.",
    params: { home: { connection_id: "thelook", owner: "default", cockpit_id: "returns-9" }, spec: SPEC,
              cards: [{ id: "c91b2002", title: "Net merchandise revenue", kind: "kpi", from: "metric" }] },
    detail: { outline: [
      { tab: "Overview", sections: [{ title: "Headline", cards: [{ title: "Return rate" }, { title: "Return rate" }, { title: "Net merchandise revenue" }] }] },
      { tab: "Watches", sections: [{ title: "Limits", cards: [{ title: "Return rate" }] }] },
    ] },
  };

  async function draftReturns() {
    show();
    fireEvent.click(await screen.findByTestId("dashboard-new-open"));
    fireEvent.click(screen.getByTestId("dashboard-new-draft"));                 // the one way here that asks a model
    fireEvent.change(screen.getByLabelText("What this dashboard is for"), { target: { value: "Returns" } });
    fireEvent.click(screen.getByRole("button", { name: "Draft it" }));
  }

  it("drafts it, shows it to be arranged, and keeps it as drafted", async () => {
    api.draftDashboard.mockResolvedValue({ staged: true, proposal_id: "p1", cockpit_id: "returns-9", summary: "Drafted the dashboard \"Returns\".", rounds: 1, stop_reason: "answered", sentences: [] });
    api.getProposalById.mockResolvedValue(PROPOSAL);
    api.acceptProposal.mockResolvedValue({ status: "executed" });
    await draftReturns();

    const draft = await screen.findByTestId("dashboard-draft");
    expect(api.draftDashboard).toHaveBeenCalledWith("thelook", "Returns", "thelook");
    expect(draft).toHaveTextContent("Drafted the dashboard \"Returns\".");
    expect(draft).toHaveTextContent("Why it is arranged this way: Returns first, then what they cost.");
    const lines = within(draft).getAllByTestId("arrange-card");
    expect(lines[0]).toHaveTextContent("Return rate");                       // a card the person has, by name
    expect(lines[2]).toHaveTextContent("Net merchandise revenue");
    expect(lines[2]).toHaveTextContent("one figure for the whole connection");

    fireEvent.click(within(draft).getByRole("button", { name: "Keep it" }));
    await waitFor(() => expect(api.acceptProposal).toHaveBeenCalledWith("p1", "briefing"));
    expect(api.keepDashboard).not.toHaveBeenCalled();                          // kept as drafted: one version
  });

  it("changes made before keeping are kept as the next version, in the same act", async () => {
    api.draftDashboard.mockResolvedValue({ staged: true, proposal_id: "p1", cockpit_id: "returns-9", summary: "", rounds: 1, stop_reason: "answered", sentences: [] });
    api.getProposalById.mockResolvedValue(PROPOSAL);
    api.acceptProposal.mockResolvedValue({ status: "executed" });
    await draftReturns();
    const draft = await screen.findByTestId("dashboard-draft");
    fireEvent.click(within(within(draft).getAllByTestId("arrange-card")[2]).getByRole("button", { name: "Take off" }));
    fireEvent.click(within(draft).getByRole("button", { name: "Keep, with my changes" }));

    await waitFor(() => expect(api.keepDashboard).toHaveBeenCalled());
    expect(api.acceptProposal).toHaveBeenCalledWith("p1", "briefing");
    const [conn, id, spec, note] = api.keepDashboard.mock.calls[0];
    expect([conn, id, note]).toEqual(["thelook", "returns-9", "adjusted before keeping"]);
    expect(JSON.stringify(spec)).not.toContain("c91b2002");
  });

  it("when nothing is drafted, says why in the platform's words and keeps nothing", async () => {
    api.draftDashboard.mockResolvedValue({ staged: false, proposal_id: "", cockpit_id: "", summary: "", rounds: 0, stop_reason: "answered",
      sentences: ["Nothing this connection measures bears on marketing."] });
    await draftReturns();
    expect(await screen.findByTestId("dashboard-not-drafted")).toHaveTextContent("Nothing this connection measures bears on marketing.");
    expect(api.getProposalById).not.toHaveBeenCalled();
  });

  it("discarding rejects the draft", async () => {
    api.draftDashboard.mockResolvedValue({ staged: true, proposal_id: "p1", cockpit_id: "returns-9", summary: "", rounds: 1, stop_reason: "answered", sentences: [] });
    api.getProposalById.mockResolvedValue(PROPOSAL);
    api.rejectProposal.mockResolvedValue(true);
    await draftReturns();
    fireEvent.click(within(await screen.findByTestId("dashboard-draft")).getByRole("button", { name: "Discard" }));
    await waitFor(() => expect(api.rejectProposal).toHaveBeenCalledWith("p1", "briefing"));
    expect(api.acceptProposal).not.toHaveBeenCalled();
  });
});

describe("the metrics, the dashboard a person opens on", () => {
  beforeEach(() => { localStorage.clear(); });

  it("is first in the strip and open when nothing was chosen; no dashboard of the person's is read", async () => {
    show();
    const metrics = await screen.findByRole("tab", { name: "Metrics" });
    expect(metrics).toHaveAttribute("aria-selected", "true");
    // measured for the latest month, as a dashboard is read — and the Briefing's own table shows it
    await waitFor(() => expect(api.measureRange).toHaveBeenCalledWith("thelook", { preset: "previous_month" }, "thelook"));
    expect(await screen.findByText("Measured for August 2026 · against July 2026")).toBeInTheDocument();
    // the figure on its card — the table behind Details holds it too
    expect(within(screen.getByTestId("metrics-figures")).getAllByText("$110").length).toBeGreaterThan(0);
    // and what the metric's own past expects of the range after it
    expect(await screen.findByText("$100 to $116")).toBeInTheDocument();
    expect(api.readExpectedNext).toHaveBeenCalledWith("thelook", { preset: "previous_month" }, "thelook", undefined);
    expect(screen.getByTestId("dashboard-range")).toHaveTextContent("August 2026 · final");
    expect(api.getDashboard).not.toHaveBeenCalled();
    // the person's own dashboards are still there, one click away, and that choice is remembered
    fireEvent.mouseDown(screen.getByRole("tab", { name: "Returns" }));   // a Radix tab opens on mouseDown
    await waitFor(() => expect(api.getDashboard).toHaveBeenCalledWith("thelook", "returns-1", { preset: "previous_month" }));
    expect(localStorage.getItem("aughor:cockpit:thelook")).toBe("returns-1");
  });

  it("still explains what a dashboard of your own is when you have none", async () => {
    api.listDashboards.mockResolvedValue({ ...LIST, cockpits: [] });
    show();
    expect(await screen.findByTestId("metrics-dashboard")).toBeInTheDocument();
    // one muted line and its door, under the metrics; what a dashboard of your own is, on its hover
    const none = screen.getByTestId("dashboard-none-yet");
    expect(none).toHaveTextContent("No dashboard of your own yet");
    expect(none.getAttribute("title")).toMatch(/the set of cards you keep watching for one area/);
    expect(within(none).getByRole("button", { name: /New dashboard|Start “My dashboard”/ })).toBeInTheDocument();
  });
});

describe("the canvas: a note, an image and a size, by hand (2026-10-08)", () => {
  it("a note typed here is placed in the first section and kept as the next version, its stamps the server's", async () => {
    await openBuilder();
    fireEvent.click(screen.getByTestId("dashboard-note-new"));
    fireEvent.change(screen.getByRole("textbox", { name: "The note's words" }), { target: { value: "Check **ops** before the 15th." } });
    fireEvent.click(screen.getByRole("button", { name: "Place the note" }));
    await waitFor(() => expect(api.keepDashboard).toHaveBeenCalled());
    const [conn, id, spec, note] = api.keepDashboard.mock.calls[0] as [string, string, { elements: Record<string, { type: string; props: Record<string, unknown> }> }, string];
    expect([conn, id, note]).toEqual(["thelook", "returns-1", "a note written by hand"]);
    const placed = Object.values(spec.elements).find(e => e.type === "Note")!;
    expect(placed.props).toEqual({ text: "Check **ops** before the 15th." });     // no author: the server stamps it
    expect(spec.elements["sec-headline"]).toBeDefined();
    expect(screen.queryByTestId("dashboard-note-composer")).toBeNull();
  });

  it("an image is uploaded first, then placed by the object id the upload answered with", async () => {
    api.uploadDashboardImage.mockResolvedValue({ object: "ab12cd34ef56", file_name: "promo.png", uploaded_by: "user:default",
      uploaded_at: "2026-10-08T09:00:00Z", content_type: "image/png", bytes: 72, readable: true, why: "" });
    await openBuilder();
    fireEvent.click(screen.getByTestId("dashboard-image-new"));
    const file = new File([new Uint8Array([137, 80, 78, 71])], "promo.png", { type: "image/png" });
    fireEvent.change(screen.getByLabelText("The image file"), { target: { files: [file] } });
    fireEvent.change(screen.getByRole("textbox", { name: "Caption" }), { target: { value: "Promo calendar" } });
    fireEvent.click(screen.getByRole("button", { name: "Upload and place" }));
    await waitFor(() => expect(api.keepDashboard).toHaveBeenCalled());
    expect(api.uploadDashboardImage).toHaveBeenCalledWith("thelook", file);
    const spec = api.keepDashboard.mock.calls[0][2] as { elements: Record<string, { type: string; props: Record<string, unknown> }> };
    const placed = Object.values(spec.elements).find(e => e.type === "Image")!;
    expect(placed.props).toEqual({ object: "ab12cd34ef56", caption: "Promo calendar" });
    expect(api.keepDashboard.mock.calls[0][3]).toBe("an image uploaded by hand");
  });

  it("an upload the server refuses is said where the file was chosen, and nothing is kept", async () => {
    api.uploadDashboardImage.mockRejectedValue(new Error("The file is not a PNG, JPEG, GIF, WebP or SVG image (it was sent as text/html)."));
    await openBuilder();
    fireEvent.click(screen.getByTestId("dashboard-image-new"));
    fireEvent.change(screen.getByLabelText("The image file"), { target: { files: [new File(["<html>"], "page.html", { type: "text/html" })] } });
    fireEvent.click(screen.getByRole("button", { name: "Upload and place" }));
    expect(await screen.findByTestId("dashboard-image-refused")).toHaveTextContent("sent as text/html");
    expect(api.keepDashboard).not.toHaveBeenCalled();
  });

  it("a tile taken off in the builder is kept as the next version", async () => {
    await openBuilder();
    await waitFor(() => expect((drawn.props.at(-1)?.doors as { onTakeOff?: unknown } | undefined)?.onTakeOff).toBeTypeOf("function"));
    const doors = drawn.props.at(-1)!.doors as { onTakeOff: (k: string) => void };
    act(() => { doors.onTakeOff("card-net"); });
    await waitFor(() => expect(api.keepDashboard).toHaveBeenCalledTimes(1), { timeout: 3000 });
    const without = api.keepDashboard.mock.calls[0][2] as { elements: Record<string, unknown> };
    expect(without.elements["card-net"]).toBeUndefined();
    expect(api.keepDashboard.mock.calls[0][3]).toBe("taken off by hand");

    // The images the read answered with reach the drawing with where to read each from.
    expect(drawn.props.at(-1)!.images).toEqual({});
  });

  it("sizes one grade at a time: each step is drawn at once, a burst is kept as ONE version, and nothing is read again (Arc AP-1)", async () => {
    await openBuilder();
    await waitFor(() => expect(drawn.props.length).toBeGreaterThan(0));
    const reads = api.getDashboard.mock.calls.length;
    const runs = api.runCard.mock.calls.length;
    type Doors = { onRegrid: (k: string, b: { w: number; h: number }, m: Record<string, { w: number; h: number }>) => void };
    const step = (w: number, h: number) => act(() => { (drawn.props.at(-1)!.doors as Doors).onRegrid("card-net", { w, h }, {}); });
    step(4, 4);
    step(5, 4);
    step(6, 5);
    // drawn at once, on the grid, before anything is kept
    const shown = drawn.props.at(-1)!.spec as { elements: Record<string, { props: Record<string, unknown> }> };
    expect(shown.elements["card-net"].props).toMatchObject({ w: 6, h: 5 });
    expect(shown.elements["sec-headline"].props.grid).toBe(12);
    expect(api.keepDashboard).not.toHaveBeenCalled();
    await waitFor(() => expect(api.keepDashboard).toHaveBeenCalledTimes(1), { timeout: 3000 });
    const kept = api.keepDashboard.mock.calls[0][2] as { elements: Record<string, { props: Record<string, unknown> }> };
    expect(kept.elements["card-net"].props).toMatchObject({ w: 6, h: 5 });
    expect(api.keepDashboard.mock.calls[0][3]).toBe("resized by hand");
    // the room changed and nothing measured did: the dashboard is not read again, nor any card run again
    await new Promise(r => setTimeout(r, 50));
    expect(api.getDashboard.mock.calls.length).toBe(reads);
    expect(api.runCard.mock.calls.length).toBe(runs);
    expect((drawn.props.at(-1)!.spec as typeof kept).elements["card-net"].props).toMatchObject({ w: 6, h: 5 });
  });

  it("a newer burst is never undone by an older one landing after it", async () => {
    let land: (v: unknown) => void = () => {};
    api.keepDashboard.mockImplementationOnce(() => new Promise(r => { land = r; }));
    await openBuilder();
    await waitFor(() => expect(drawn.props.length).toBeGreaterThan(0));
    type Doors = { onRegrid: (k: string, b: { w: number; h: number }, m: object) => void };
    const step = (w: number) => act(() => { (drawn.props.at(-1)!.doors as Doors).onRegrid("card-net", { w, h: 5 }, {}); });
    step(6);
    await waitFor(() => expect(api.keepDashboard).toHaveBeenCalledTimes(1), { timeout: 3000 });   // the first is on its way
    step(9);                                                                                   // a second burst begins
    await act(async () => { land({ status: "kept", kept: true, version: 4, artifact_id: "a4", sentences: [] }); });
    const shown = () => (drawn.props.at(-1)!.spec as { elements: Record<string, { props: Record<string, unknown> }> }).elements["card-net"].props;
    expect(shown()).toMatchObject({ w: 9 });                                                   // still the newer size
    await waitFor(() => expect(api.keepDashboard).toHaveBeenCalledTimes(2), { timeout: 3000 });
    expect((api.keepDashboard.mock.calls[1][2] as { elements: Record<string, { props: Record<string, unknown> }> }).elements["card-net"].props).toMatchObject({ w: 9 });
  });

  it("a burst the server refuses is drawn back as it was kept, and the refusal is said", async () => {
    api.keepDashboard.mockRejectedValue(new (await import("@/lib/api")).DashboardRefused(
      { status: "refused", kept: false, version: null, artifact_id: "", sentences: ["Refused for a reason."] }));
    await openBuilder();
    await waitFor(() => expect(drawn.props.length).toBeGreaterThan(0));
    act(() => { (drawn.props.at(-1)!.doors as { onRegrid: (k: string, b: { w: number; h: number }, m: object) => void }).onRegrid("card-net", { w: 6, h: 5 }, {}); });
    await waitFor(() => expect(api.keepDashboard).toHaveBeenCalledTimes(1), { timeout: 3000 });
    await waitFor(() => expect(drawn.props.at(-1)!.spec).toEqual(SPEC));
    expect(await screen.findByText(/Refused for a reason/)).toBeInTheDocument();
  });
});

describe("the canvas: a finding from the ledger, a change in words, publishing (2026-10-08)", () => {
  it("places any recorded finding through the pin door, and says which has no query", async () => {
    api.listFindingsByDomain.mockResolvedValue([
      { domain: "returns", findings: [
        { id: "returns__cat__1", domain: "returns", angle: "by category", finding: "Jeans return at twice the rate of Tops", sql: "SELECT 1" },
        { id: "supply__stock__2", domain: "returns", angle: "stock", finding: "Stockouts in Outerwear", sql: "" },
      ] },
    ]);
    api.pinFinding.mockResolvedValue({ card: { id: "newcard" }, preview: { columns: [], rows: [], row_count: 0 }, caveats: [] });
    await openBuilder();
    fireEvent.click(screen.getByTestId("dashboard-finding-new"));
    const rows = await screen.findAllByTestId("finding-row");
    expect(rows).toHaveLength(2);
    expect(rows[1]).toHaveTextContent("no query — nothing to measure");
    expect(within(rows[1]).getByRole("button", { name: "Place" })).toBeDisabled();
    fireEvent.click(within(rows[0]).getByRole("button", { name: "Place" }));
    await waitFor(() => expect(api.pinFinding).toHaveBeenCalledWith("thelook", "returns__cat__1", { scope: "connection", scopeRef: "thelook", schema: "thelook" }));
    // The card pinned lands on the dashboard in view, as a pin from the Briefing does.
    await waitFor(() => expect(api.getDashboard).toHaveBeenCalledTimes(2));
  });

  it("a change asked for in words is a proposal, read as its outline, kept whole on Keep", async () => {
    const edited = JSON.parse(JSON.stringify(SPEC));
    edited.elements["card-net"].props.size = "large";
    api.askDashboard.mockResolvedValue({ staged: true, proposal_id: "p9", cockpit_id: "returns-1", summary: "Drafted an edit: Net merchandise revenue made large.", rounds: 1, stop_reason: "stop", sentences: [] });
    api.getProposalById.mockResolvedValue({ id: "p9", kind: "cockpit_draft", reasoning: "", params: { spec: edited, cards: [], mode: "edit" },
      detail: { mode: "edit", title: "Returns", replaces_version: 3, outline: [], taken_off: [], changes: { added: [], removed: [], changed: ["card-net"] } } });
    api.acceptProposal.mockResolvedValue({});
    await openBuilder();
    fireEvent.change(screen.getByRole("textbox", { name: "Ask for a change in words" }), { target: { value: "make the net sales card bigger" } });
    fireEvent.click(screen.getByRole("button", { name: "Propose" }));
    await waitFor(() => expect(api.askDashboard).toHaveBeenCalledWith("thelook", "returns-1", "make the net sales card bigger", "thelook"));
    const review = await screen.findByTestId("dashboard-draft");
    expect(review).toHaveTextContent("Net merchandise revenue made large");
    expect(api.acceptProposal).not.toHaveBeenCalled();
    fireEvent.click(within(review).getByRole("button", { name: "Keep it" }));
    await waitFor(() => expect(api.acceptProposal).toHaveBeenCalledWith("p9", "briefing"));
    expect(api.keepDashboard).not.toHaveBeenCalled();                 // kept as proposed: no second version
  });

  it("words that come to nothing are said in the platform's sentences", async () => {
    api.askDashboard.mockResolvedValue({ staged: false, proposal_id: "", cockpit_id: "", summary: "", rounds: 1, stop_reason: "stop",
      sentences: ["The edit adds the note \"note-2\". A note is the person's words and an image is the person's choice: you may move one they placed, resize it or take it off, never add one."] });
    await openBuilder();
    fireEvent.change(screen.getByRole("textbox", { name: "Ask for a change in words" }), { target: { value: "write me a note saying returns are too high" } });
    fireEvent.click(screen.getByRole("button", { name: "Propose" }));
    expect(await screen.findByTestId("dashboard-not-proposed")).toHaveTextContent("never add one");
    expect(api.acceptProposal).not.toHaveBeenCalled();
  });

  it("publishes to a group the person belongs to, and the strip lists what others published", async () => {
    api.dashboardAudiences.mockResolvedValue({ groups: [{ kind: "group", id: "sales", name: "Sales team" }], roles: [{ kind: "role", id: "analyst", name: "Editor" }] });
    api.publishDashboard.mockResolvedValue({ status: "kept", kept: true, version: 4, artifact_id: "a4", sentences: [] });
    api.listSharedDashboards.mockResolvedValue([{ owner: "priya@example.com", cockpit_id: "sales-weekly-1", title: "Sales weekly", version: 3, kept_at: "2026-10-06T10:00:00Z",
      published_by: "user:priya@example.com", published_to: [{ kind: "group", id: "sales", name: "Sales team" }] }]);
    api.getSharedDashboard.mockResolvedValue({ ...READ, owner: "priya@example.com", cockpit_id: "sales-weekly-1", published_by: "user:priya@example.com",
      published_to: [{ kind: "group", id: "sales", name: "Sales team" }], images: {} });
    api.copySharedDashboard.mockResolvedValue({ status: "kept", kept: true, version: 1, artifact_id: "b1", sentences: [], cockpit_id: "sales-weekly-9f", title: "Sales weekly" });
    show();
    await waitFor(() => expect(drawn.props.length).toBeGreaterThan(0));
    expect(stripTabs()).toEqual(["Metrics", "Returns", "Pricing", "Sales weekly · priya@example.com"]);

    fireEvent.click(screen.getByTestId("dashboard-edit"));
    fireEvent.click(await screen.findByTestId("dashboard-publish-open"));
    const panel = await screen.findByTestId("dashboard-publish");
    await within(panel).findByText("Sales team");
    fireEvent.click(within(panel).getByRole("checkbox", { name: "Publish to Sales team" }));
    fireEvent.click(within(panel).getByTestId("dashboard-publish-go"));
    await waitFor(() => expect(api.publishDashboard).toHaveBeenCalledWith("thelook", "returns-1", [{ kind: "group", id: "sales", name: "Sales team" }]));
    fireEvent.click(screen.getByTestId("builder-done"));
    await waitFor(() => expect(screen.queryByTestId("dashboard-builder")).toBeNull());

    // What Priya published reads as hers, read-only, with the door to start one's own from it.
    fireEvent.mouseDown(screen.getByRole("tab", { name: "Sales weekly · priya@example.com" }));
    const sharedView = await screen.findByTestId("dashboard-shared");
    expect(within(sharedView).getByTestId("dashboard-shared-by")).toHaveTextContent("An App by priya@example.com, for Sales team · version 3 · read-only");
    const doors = drawn.props.at(-1)!.doors as Record<string, unknown>;
    expect(doors.onRemove).toBeUndefined();
    expect(doors.onResize).toBeUndefined();
    fireEvent.click(within(sharedView).getByRole("button", { name: "Start my dashboard from this" }));
    await waitFor(() => expect(api.copySharedDashboard).toHaveBeenCalledWith("thelook", "priya@example.com", "sales-weekly-1"));
  });
});

describe("building a dashboard in place (Arc AP-1)", () => {
  type Doors = Record<string, unknown> & { onRegrid?: (k: string, b: { w: number; h: number }, m: object) => void };
  const doors = () => drawn.props.at(-1)!.doors as Doors;
  const shown = () => (drawn.props.at(-1)!.spec as { elements: Record<string, { props: Record<string, unknown> }> }).elements;

  it("a dashboard opens to be read: one bar — its history and Edit — and the reader's own doors only", async () => {
    show();
    expect(await screen.findByTestId("dashboard-edit")).toBeInTheDocument();
    for (const id of ["dashboard-card-new", "dashboard-note-new", "dashboard-arrange-open", "dashboard-publish-open", "dashboard-retire-open", "dashboard-ask"]) {
      expect(screen.queryByTestId(id)).toBeNull();
    }
    expect(screen.getByRole("button", { name: /History/ })).toBeInTheDocument();
    await waitFor(() => expect(Object.entries(doors()).filter(([, v]) => v !== undefined).map(([k]) => k)).toEqual(["onRefresh"]));
  });

  it("Edit opens the builder: the strip folds into the name, the rail into its icons — never into the person's preference — and Done gives both back", async () => {
    document.documentElement.removeAttribute("data-nav");
    await openBuilder();
    expect(screen.queryAllByRole("tab")).toHaveLength(0);
    expect(screen.getByLabelText("The dashboard being edited")).toBeInTheDocument();
    expect(document.documentElement.getAttribute("data-nav")).toBe("collapsed");
    expect(localStorage.getItem("aughor_nav_collapsed")).toBeNull();
    expect(screen.getByTestId("builder-saved")).toHaveTextContent("version 3");
    for (const id of ["dashboard-card-new", "dashboard-note-new", "dashboard-publish-open", "dashboard-retire-open", "dashboard-ask"]) {
      expect(screen.getByTestId(id)).toBeInTheDocument();
    }
    expect(doors().onSelect).toBeTypeOf("function");
    fireEvent.click(screen.getByTestId("builder-done"));
    await waitFor(() => expect(screen.queryByTestId("dashboard-builder")).toBeNull());
    expect(document.documentElement.hasAttribute("data-nav")).toBe(false);
    expect(localStorage.getItem("aughor_nav_collapsed")).toBeNull();
    expect(stripTabs()).toContain("Returns");
  });

  it("undo keeps the version before as the next one, and redo the one after", async () => {
    await openBuilder();
    await waitFor(() => expect(doors().onRegrid).toBeTypeOf("function"));
    act(() => { doors().onRegrid!("card-net", { w: 6, h: 5 }, {}); });
    await waitFor(() => expect(api.keepDashboard).toHaveBeenCalledTimes(1), { timeout: 3000 });
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(shown()["card-net"].props.w).toBeUndefined();                                       // drawn back at once
    await waitFor(() => expect(api.keepDashboard).toHaveBeenCalledTimes(2), { timeout: 3000 });
    expect(api.keepDashboard.mock.calls[1][2]).toEqual(SPEC);
    expect(api.keepDashboard.mock.calls[1][3]).toBe("undone by hand");
    expect(screen.getByRole("button", { name: "Undo" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Redo" }));
    await waitFor(() => expect(api.keepDashboard).toHaveBeenCalledTimes(3), { timeout: 3000 });
    expect((api.keepDashboard.mock.calls[2][2] as { elements: Record<string, { props: Record<string, unknown> }> }).elements["card-net"].props)
      .toMatchObject({ w: 6, h: 5 });
    expect(api.keepDashboard.mock.calls[2][3]).toBe("redone by hand");
  });

  it("a note placed while a resize waits to be kept is kept with it — the resize never lands after it and takes it back", async () => {
    await openBuilder();
    await waitFor(() => expect(doors().onRegrid).toBeTypeOf("function"));
    act(() => { doors().onRegrid!("card-net", { w: 6, h: 5 }, {}); });
    fireEvent.click(screen.getByTestId("dashboard-note-new"));
    fireEvent.change(await screen.findByLabelText("The note's words"), { target: { value: "Watch returns in Q4" } });
    fireEvent.click(screen.getByRole("button", { name: "Place the note" }));
    await waitFor(() => expect(api.keepDashboard).toHaveBeenCalledTimes(1));
    const kept = api.keepDashboard.mock.calls[0][2] as { elements: Record<string, { type: string; props: Record<string, unknown> }> };
    expect(kept.elements["card-net"].props).toMatchObject({ w: 6, h: 5 });
    expect(Object.values(kept.elements).some(el => el.type === "Note" && el.props.text === "Watch returns in Q4")).toBe(true);
    await new Promise(r => setTimeout(r, 1200));                                                // past the burst's moment
    expect(api.keepDashboard).toHaveBeenCalledTimes(1);
  });

  it("a note placed while a keep is on its way is kept after it lands, never before it", async () => {
    let land: (v: unknown) => void = () => {};
    api.keepDashboard.mockImplementationOnce(() => new Promise(r => { land = r; }));
    await openBuilder();
    await waitFor(() => expect(doors().onRegrid).toBeTypeOf("function"));
    act(() => { doors().onRegrid!("card-net", { w: 6, h: 5 }, {}); });
    await waitFor(() => expect(api.keepDashboard).toHaveBeenCalledTimes(1), { timeout: 3000 });   // the resize, on its way
    fireEvent.click(screen.getByTestId("dashboard-note-new"));
    fireEvent.change(await screen.findByLabelText("The note's words"), { target: { value: "After the resize" } });
    fireEvent.click(screen.getByRole("button", { name: "Place the note" }));
    await new Promise(r => setTimeout(r, 50));
    expect(api.keepDashboard).toHaveBeenCalledTimes(1);                                          // it waits for the first
    await act(async () => { land({ status: "kept", kept: true, version: 4, artifact_id: "a4", sentences: [] }); });
    await waitFor(() => expect(api.keepDashboard).toHaveBeenCalledTimes(2));
    const second = api.keepDashboard.mock.calls[1][2] as { elements: Record<string, { type: string; props: Record<string, unknown> }> };
    expect(second.elements["card-net"].props).toMatchObject({ w: 6, h: 5 });
    expect(Object.values(second.elements).some(el => el.type === "Note" && el.props.text === "After the resize")).toBe(true);
  });

  it("what a refused keep said is gone once a later change is kept", async () => {
    api.keepDashboard.mockRejectedValueOnce(new (await import("@/lib/api")).DashboardRefused(
      { status: "refused", kept: false, version: null, artifact_id: "", sentences: ["Refused for a reason."] }));
    await openBuilder();
    await waitFor(() => expect(doors().onRegrid).toBeTypeOf("function"));
    act(() => { doors().onRegrid!("card-net", { w: 6, h: 5 }, {}); });
    expect(await screen.findByText(/Refused for a reason/, {}, { timeout: 3000 })).toBeInTheDocument();
    act(() => { doors().onRegrid!("card-net", { w: 7, h: 5 }, {}); });
    await waitFor(() => expect(api.keepDashboard).toHaveBeenCalledTimes(2), { timeout: 3000 });
    await waitFor(() => expect(screen.queryByText(/Refused for a reason/)).toBeNull());
  });
});

describe("action buttons, placed by hand (Arc AP-3)", () => {
  const OPEN_CASE = { id: "open_case", display_name: "Open a case", description: "", entity: "order", object_type: "order", kind: "annotate",
    risk: "low", edits: [], params: [] };

  it("are placed with the first action declared here, and kept as a version said in words", async () => {
    api.getDeclaredActions.mockResolvedValue({ open_case: OPEN_CASE, flag_for_review: { ...OPEN_CASE, id: "flag_for_review" } });
    await openBuilder();
    fireEvent.click(await screen.findByTestId("dashboard-buttons-new"));
    await waitFor(() => expect(api.keepDashboard).toHaveBeenCalledTimes(1));
    const kept = api.keepDashboard.mock.calls[0][2] as { elements: Record<string, { type: string; props: Record<string, unknown> }> };
    const placed = Object.values(kept.elements).filter(el => el.type === "ActionButtons");
    expect(placed).toHaveLength(1);
    expect(placed[0].props.buttons).toEqual([{ action: "open_case" }]);
    expect(api.keepDashboard.mock.calls[0][3]).toBe("action buttons placed by hand");
  });

  it("say that no action is declared, and place nothing", async () => {
    api.getDeclaredActions.mockResolvedValue({});
    await openBuilder();
    fireEvent.click(await screen.findByTestId("dashboard-buttons-new"));
    await waitFor(() => expect(toasts.error).toHaveBeenCalledWith("No action is declared here", expect.objectContaining({
      description: expect.stringContaining("Ontology ▸ Actions") })));
    await new Promise(r => setTimeout(r, 50));
    expect(api.keepDashboard).not.toHaveBeenCalled();
  });
});

describe("a new dashboard from a pack template (Arc FA, FA-6)", () => {
  const TEMPLATE = {
    pack: "retail", pack_name: "Retail and e-commerce", version: 1, id: "checkout-and-returns", title: "Checkout and returns",
    description: "How many carts become an order.", sections: ["Checkout", "Returns"], ready: 1, source: "pack:retail@1 template",
    cards: [
      { key: "cart-conversion", metric: "cart_to_order_conversion_rate", title: "Cart-to-order conversion rate", ready: false,
        why: "not registered on this connection" },
      { key: "return-rate", metric: "return_rate", title: "Return rate", ready: true, why: "" },
    ],
  };

  it("lists the bound packs' templates, says what is left out, and drafts one with no model", async () => {
    api.listPackTemplates.mockResolvedValue({ templates: [TEMPLATE], waiting: { banking: "the pack is draft: its templates are offered once a person activates it" } });
    api.draftFromPackTemplate.mockResolvedValue({
      staged: true, proposal_id: "p2", rounds: 0, stop_reason: "", sentences: [], dashboard_id: "checkout-and-returns-a1b2c3",
      summary: "Drafted \"Checkout and returns\" from the Retail and e-commerce pack's template (v1): 1 card. Left out: Cart-to-order conversion rate — not registered on this connection.",
      skipped: [{ key: "cart-conversion", metric: "cart_to_order_conversion_rate", title: "Cart-to-order conversion rate", why: "not registered on this connection" }],
      source: "pack:retail@1 template",
    });
    api.getProposalById.mockResolvedValue({ id: "p2", status: "pending", reasoning: "", params: { spec: SPEC, cards: [] }, detail: { outline: [] } });
    show();
    fireEvent.click(await screen.findByTestId("dashboard-new-open"));
    fireEvent.click(await screen.findByTestId("dashboard-new-pack"));
    const t = await screen.findByTestId("dashboard-pack-template");
    expect(api.listPackTemplates).toHaveBeenCalledWith("thelook", "thelook");
    expect(t).toHaveTextContent("Checkout and returns");
    expect(t).toHaveTextContent("Retail and e-commerce pack · v1");
    expect(t).toHaveTextContent("1 card this connection can make · left out: Cart-to-order conversion rate (not registered on this connection)");
    expect(screen.getByTestId("dashboard-new-pack-templates")).toHaveTextContent("banking: the pack is draft");
    fireEvent.click(within(t).getByTestId("dashboard-pack-template-draft"));
    await waitFor(() => expect(api.draftFromPackTemplate).toHaveBeenCalledWith("retail", "checkout-and-returns", "thelook", "thelook"));
    const draft = await screen.findByTestId("dashboard-draft");
    expect(draft).toHaveTextContent("Left out: Cart-to-order conversion rate — not registered on this connection.");
    expect(api.draftDashboard).not.toHaveBeenCalled();
  });
});

describe("what each object suggests (Arc AP-5)", () => {
  it("lists each object with the shape it fits, and a click opens the starter on it", async () => {
    // answered after the object catalog, as the live API answers: the catalog's arrival must not drop them
    api.getSuggestedShapes.mockImplementation(() => new Promise(resolve => setTimeout(() => resolve([
      { entity: "order", type_id: "Order", name: "Customer Order", shape: "queue", short: "a dispatch promise · 2 actions" },
      { entity: "distribution_center", type_id: "DistributionCenter", name: "Distribution Center", shape: "map", short: "a latitude and a longitude" }]), 60)));
    api.getDashboardFromObject.mockReturnValue(new Promise(() => {}));
    show();
    fireEvent.click(await screen.findByTestId("dashboard-new-open"));
    fireEvent.click(await screen.findByTestId("dashboard-new-object"));
    const rows = await screen.findAllByTestId("dashboard-new-suggestion");
    expect(rows.map(r => [r.dataset.shape, r.textContent])).toEqual([
      ["queue", "Customer OrderQueuea dispatch promise · 2 actions"], ["map", "Distribution CenterMapa latitude and a longitude"]]);
    fireEvent.click(rows[1]);
    await waitFor(() => expect(api.getDashboardFromObject).toHaveBeenCalledWith("thelook", "distribution_center", "thelook"));
    expect(screen.queryByTestId("dashboard-new-suggested")).toBeNull();
  });
});

describe("History, in words (Arc AP-6)", () => {
  it("says what each version changed, and counts as before where a server says no words", async () => {
    api.getSystemFlags.mockResolvedValue({});
    api.getDashboard.mockResolvedValue({ ...READ, history: [
      { ...version(3), said: ["Added the map · distribution center", "Moved a note to the section Waiting"] },
      { ...version(2), current: false, said: [] , source: "published to Operations" },
      { ...version(1), current: false, changes: { added: ["a", "b"], removed: [], changed: ["c"] } },
    ] });
    show();
    fireEvent.click(await screen.findByRole("button", { name: /History/ }));
    const rows = within(await screen.findByTestId("dashboard-history")).getAllByRole("listitem");
    expect(within(rows[0]).getByTestId("dashboard-history-said")).toHaveTextContent("Added the map · distribution center · Moved a note to the section Waiting");
    expect(within(rows[1]).queryByTestId("dashboard-history-said")).toBeNull();          // published: its source says it
    expect(rows[1]).toHaveTextContent("published to Operations");
    expect(rows[2]).toHaveTextContent("2 added · 1 changed");
  });
});

describe("an App publishes one version (Arc ED, ED-4)", () => {
  const sales = { kind: "group" as const, id: "sales", name: "Sales team" };
  /** The person's dashboard read with ``newest`` as its newest version, under the field name the API carries. */
  const withNewest = (newest: PersonDashboard["cockpit"], more: Partial<PersonDashboard> = {}): PersonDashboard =>
    ({ ...READ, ...more, cockpit: newest });

  it("a change kept since the version its readers read is said, publishes to the same audience, and History marks what they read", async () => {
    api.dashboardAudiences.mockResolvedValue({ groups: [sales], roles: [] });
    api.publishDashboard.mockResolvedValue({ status: "kept", kept: true, version: 4, artifact_id: "a4", sentences: [] });
    api.getDashboard.mockResolvedValue(withNewest({ ...version(3), spec: SPEC, published_to: [sales], state: "draft", published_version: 2 }, {
      history: [{ ...version(3), state: "draft", published_to: [sales] },
                { ...version(2), current: false, state: "published", published_to: [sales], source: "published to Sales team" },
                { ...version(1), current: false, state: "draft" }] }));
    await openBuilder();
    const door = await screen.findByTestId("dashboard-publish-open");
    expect(door).toHaveTextContent("An App for Sales team · readers see version 2");
    expect(door).toHaveAttribute("title", "What you kept since version 2 is a draft. Its readers read version 2 until you publish.");

    fireEvent.click(door);
    const panel = await screen.findByTestId("dashboard-publish");
    await within(panel).findByText("Sales team");
    expect(within(panel).getByTestId("dashboard-publish-draft")).toHaveTextContent("Its readers read version 2. What you kept since is a draft until you publish it.");
    const go = within(panel).getByTestId("dashboard-publish-go");
    expect(go).toHaveTextContent("Publish your changes");
    expect(go).toBeEnabled();                                   // the same audience: before ED-4 this door was shut
    fireEvent.click(go);
    await waitFor(() => expect(api.publishDashboard).toHaveBeenCalledWith("thelook", "returns-1", [sales]));

    fireEvent.click(screen.getByRole("button", { name: /History/ }));
    const rows = within(await screen.findByTestId("dashboard-history")).getAllByRole("listitem");
    expect(within(rows[1]).getByTestId("dashboard-history-read")).toHaveTextContent("what its readers read");
    expect(within(rows[0]).queryByTestId("dashboard-history-read")).toBeNull();
  });

  it("a server with App versions off says no state: the door reads as before, and the same audience is not offered again", async () => {
    api.dashboardAudiences.mockResolvedValue({ groups: [sales], roles: [] });
    api.getDashboard.mockResolvedValue(withNewest({ ...version(3), spec: SPEC, published_to: [sales] }));
    await openBuilder();
    const door = await screen.findByTestId("dashboard-publish-open");
    expect(door).toHaveTextContent(/^An App for Sales team$/);
    fireEvent.click(door);
    const panel = await screen.findByTestId("dashboard-publish");
    await within(panel).findByText("Sales team");
    expect(within(panel).queryByTestId("dashboard-publish-draft")).toBeNull();
    expect(within(panel).getByTestId("dashboard-publish-go")).toHaveTextContent("Publish the App");
    expect(within(panel).getByTestId("dashboard-publish-go")).toBeDisabled();
  });
});

describe("previewing as a group (Arc AP-6)", () => {
  it("reads the dashboard as the person and a member of the group, with no door that changes it, and says what is withheld", async () => {
    api.getSystemFlags.mockResolvedValue({ "ontology.security": { value: true } });
    api.getGroups.mockResolvedValue({ ladder: [], builtin_groups: [], groups: [{ id: "support", name: "Support" }, { id: "fulfilment", name: "Fulfilment" }] });
    show();
    fireEvent.click(await screen.findByTestId("dashboard-edit"));
    await screen.findByTestId("dashboard-builder");
    await waitFor(() => expect(optionsOf(screen.getByLabelText("Preview as")).map(o => o.value)).toEqual(["", "support", "fulfilment"]));
    await choose(screen.getByLabelText("Preview as"), "support");
    const banner = await screen.findByTestId("dashboard-preview-banner");
    expect(banner).toHaveTextContent("Previewing as Support.");
    expect(within(banner).getByTestId("dashboard-preview-nothing")).toHaveTextContent("No row policy or mask holds back what these pieces read from this group.");
    const props = drawn.props.at(-1)! as { asGroup?: string; doors: Record<string, unknown>; onSaid: (line: string) => void };
    expect(props.asGroup).toBe("support");
    expect(Object.keys(props.doors).sort()).toEqual(["onReadState", "onRefresh"]);           // nothing that changes the dashboard
    const WITHHELD = [
      "only the Order objects user:amit previewing as support may see are shown — support: status in cancelled",
      "counted over only the Order objects user:amit previewing as support may see — support: status in cancelled",
      "Order.revenue is restricted — masked for group:support; finance may read it",
      "Order is shown by group, and marketing is none of its groups (fulfilment, support) — a member of marketing sees no Order object",
    ];
    act(() => {
      for (const line of WITHHELD) props.onSaid(line);
      props.onSaid("the compiler read status through its own column");                         // not a withholding: not said here
      props.onSaid(WITHHELD[0]);                                                                   // said again: once
    });
    expect(within(banner).getAllByTestId("dashboard-preview-withheld").map(w => w.textContent)).toEqual(WITHHELD.map(w => `Withheld — ${w}.`));
    // another group: what the last one was told withheld goes with it
    await choose(screen.getByLabelText("Preview as"), "fulfilment");
    await waitFor(() => expect(screen.getByTestId("dashboard-preview-banner")).toHaveTextContent("Previewing as Fulfilment."));
    expect(screen.queryByTestId("dashboard-preview-withheld")).toBeNull();
    fireEvent.click(within(screen.getByTestId("dashboard-preview-banner")).getByRole("button", { name: "Stop previewing" }));
    await waitFor(() => expect(screen.queryByTestId("dashboard-preview-banner")).toBeNull());
    expect((drawn.props.at(-1) as { asGroup?: string }).asGroup).toBeUndefined();
  });

  it("ends when the builder closes or another dashboard opens in it: the dashboard is read as the person again", async () => {
    api.getGroups.mockResolvedValue({ ladder: [], builtin_groups: [], groups: [{ id: "support", name: "Support" }] });
    await openBuilder();
    await waitFor(() => expect(optionsOf(screen.getByLabelText("Preview as")).map(o => o.value)).toEqual(["", "support"]));
    await choose(screen.getByLabelText("Preview as"), "support");
    // where limiting who sees which objects is off, a member of the group reads what the person reads — said so
    expect(await screen.findByTestId("dashboard-preview-nothing")).toHaveTextContent(
      "Limiting who sees which objects is off here, so a member of Support reads what you read.");
    fireEvent.click(screen.getByTestId("builder-done"));
    await waitFor(() => expect(screen.queryByTestId("dashboard-builder")).toBeNull());
    fireEvent.click(await screen.findByTestId("dashboard-edit"));
    await screen.findByTestId("dashboard-builder");
    expect(screen.queryByTestId("dashboard-preview-banner")).toBeNull();
    expect(screen.getByLabelText("Preview as")).toHaveValue("");
    await choose(screen.getByLabelText("Preview as"), "support");
    await screen.findByTestId("dashboard-preview-banner");
    await choose(screen.getByLabelText("The dashboard being edited"), "pricing-1");
    await waitFor(() => expect(screen.queryByTestId("dashboard-preview-banner")).toBeNull());
    expect(screen.getByTestId("dashboard-builder")).toBeInTheDocument();
  });
});

describe("the checks chip, as the dashboard's cells say what they read (Arc AP-6)", () => {
  const doors = () => drawn.props.at(-1)!.doors as { onReadState?: (key: string, state: { status: "ok" | "refused" | "reading"; reason: string } | null) => void };

  it("counts what each cell said, lists what to fix, and lets go of a cell once it is gone", async () => {
    await openBuilder();
    await waitFor(() => expect(doors().onReadState).toBeTypeOf("function"));
    act(() => {
      doors().onReadState!("card-rate", { status: "ok", reason: "" });
      doors().onReadState!("card-net", { status: "refused", reason: "Not one of your cards" });
    });
    await waitFor(() => expect(screen.getByTestId("builder-checks")).toHaveTextContent("1 read cleanly · 1 to fix"));
    act(() => { doors().onReadState!("card-net", null); });
    await waitFor(() => expect(screen.getByTestId("builder-checks")).toHaveTextContent(/^1 read cleanly$/));
  });
});

describe("your own query on the dashboard (Arc AP-7)", () => {
  const SHOWN = { as: "bar", summed: true, x: "day", bucket: "day", series: [{ column: "sales", agg: "sum" }], split: "", top: 5,
    segments: "stacked", running: false, labels: false, columns: [], sort: "", descending: true, label: "" };
  const queryCard = (id: string) => ({ ...card(id, "Sales by day"), sql: "SELECT day, sales FROM thelook.orders",
    render: { shown: SHOWN, columns: [{ name: "day", type: "DATE" }, { name: "sales", type: "DOUBLE" }] } });
  beforeEach(() => {
    // the piece picker reads the declared actions and the processes when it opens
    api.getDeclaredActions.mockResolvedValue({});
    ontology.getProcesses.mockResolvedValue({ processes: [] });
  });

  it("writes a new one for the section the picker was opened for, and places the kept card there", async () => {
    api.keepDashboardQuery.mockResolvedValue({ card: queryCard("qnew"), preview: { connection_id: "thelook", refused: [] } });
    show();
    fireEvent.click(await screen.findByTestId("dashboard-edit"));
    await screen.findByTestId("dashboard-builder");
    fireEvent.click(await screen.findByTestId("builder-add-piece"));
    const entry = (await screen.findAllByTestId("piece-picker-entry")).find(e => e.dataset.kind === "query")!;
    fireEvent.click(entry);
    const setup = await screen.findByTestId("query-setup");
    fireEvent.change(within(setup).getByLabelText("SQL"), { target: { value: "SELECT day, sales FROM thelook.orders" } });
    api.getDashboard.mockResolvedValue({ ...READ, cards: [...READ.cards, queryCard("qnew")] });
    fireEvent.click(within(setup).getByTestId("query-keep"));
    await waitFor(() => expect(api.keepDashboard).toHaveBeenCalled());
    const [, , spec, note] = api.keepDashboard.mock.calls.at(-1)!;
    expect(note).toBe("a query of your own placed by hand");                    // never "a card pinned from the Briefing"
    const placed = Object.entries((spec as { elements: Record<string, { type: string; props: { card?: string } }> }).elements)
      .filter(([, el]) => el.type === "Card" && el.props.card === "qnew");
    expect(placed).toHaveLength(1);
    expect(screen.queryByTestId("query-setup")).toBeNull();
  });

  it("sets up a card of the person's own query where it is chosen, and keeps a change by swapping the new card in", async () => {
    api.getDashboard.mockResolvedValue({ ...READ, cards: [READ.cards[0], queryCard("c91b2002"), READ.cards[2]] });
    api.keepDashboardQuery.mockResolvedValue({ card: queryCard("q2"), preview: { connection_id: "thelook", refused: [] } });
    show();
    fireEvent.click(await screen.findByTestId("dashboard-edit"));
    await screen.findByTestId("dashboard-builder");
    fireEvent.click((await screen.findAllByTestId("builder-line")).find(l => l.dataset.key === "card-net")!);
    const setup = await screen.findByTestId("query-setup");
    fireEvent.click(within(setup).getByRole("radio", { name: /Line/ }));
    fireEvent.click(within(setup).getByTestId("query-keep"));
    await waitFor(() => expect(api.keepDashboard).toHaveBeenCalled(), { timeout: 3000 });
    const [, , spec, note] = api.keepDashboard.mock.calls.at(-1)!;
    expect(note).toBe("a query of your own changed by hand");
    const els = (spec as { elements: Record<string, { props: { card?: string } }> }).elements;
    expect(els["card-net"].props.card).toBe("q2");
    expect(api.keepDashboardQuery).toHaveBeenCalledWith("thelook", expect.objectContaining({ replaces: "c91b2002" }));
  });

  it("leaves a query that reads the dashboard's values to its own cell, and runs every other card as written (Arc AP-8)", async () => {
    api.getDashboard.mockResolvedValue({ ...READ, cards: [READ.cards[0],
      { ...queryCard("c91b2002"), sql: "SELECT day, sales FROM thelook.orders WHERE country = {{country}}" }, READ.cards[2]] });
    show();
    await waitFor(() => expect(drawn.props.length).toBeGreaterThan(0));
    expect(api.runCard.mock.calls.map(c => c[0])).toEqual(["c7f3a001"]);
    const held = (drawn.props.at(-1)!.cards as { card: { id: string }; run?: unknown }[]).find(c => c.card.id === "c91b2002")!;
    expect(held.run).toBeUndefined();
  });

  it("offers the dashboard's values to a query's setup, and the Variables pane", async () => {
    const valued = { ...SPEC, values: { country: { label: "Country", kind: "text", value: "China", from: { by: "reader" } } } };
    api.getDashboard.mockResolvedValue({ ...READ, cockpit: { ...READ.cockpit, spec: valued }, cards: [READ.cards[0], queryCard("c91b2002"), READ.cards[2]] });
    await openBuilder();
    fireEvent.click((await screen.findAllByTestId("builder-line")).find(l => l.dataset.key === "card-net")!);
    const setup = await screen.findByTestId("query-setup");
    expect(within(setup).getByTestId("query-values-open")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Variables" })).toBeInTheDocument();
  });
});
