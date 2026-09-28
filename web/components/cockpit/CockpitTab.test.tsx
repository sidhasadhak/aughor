// @vitest-environment jsdom

/**
 * The Cockpit tab (Arc CT-4). The server is mocked at `@/lib/api`; everything between it and
 * the screen is real — the status each card is given from its run, the rules, the renderer.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { CockpitTab } from "@/components/cockpit/CockpitTab";
import type { CanvasCockpit, CardRunResult, CockpitVersion, DashboardCard } from "@/lib/api";

const api = vi.hoisted(() => ({
  getCanvasCockpit: vi.fn(),
  runDashboardCard: vi.fn(),
  startCanvasCockpit: vi.fn(),
  restoreCanvasCockpit: vi.fn(),
  retireCanvasCockpit: vi.fn(),
  deleteDashboardCard: vi.fn(),
}));
const composer = vi.hoisted(() => ({ props: [] as Record<string, unknown>[] }));

vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  ...api,
  graduateCard: vi.fn(),
  updateDashboardCard: vi.fn(),
}));
vi.mock("@/components/brief/NewCardComposer", () => ({
  NewCardComposer: (props: Record<string, unknown>) => { composer.props.push(props); return <div data-testid="composer" />; },
}));

beforeAll(() => {
  globalThis.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} } as unknown as typeof ResizeObserver;
});

const premise = () => JSON.parse(readFileSync(resolve(process.cwd(), "lib/cockpit/premise.fixture.json"), "utf8"));

function card(id: string, title: string, limits: Record<string, unknown> = {}): DashboardCard {
  return {
    id, connection_id: "thelook", scope: "canvas", scope_ref: "cv1", source: "authored", kind: "kpi",
    title, sql: "SELECT 1", query_ref: null, render: {},
    refresh: { cadence: "daily", last_run: "", last_value: null, prev_value: null, history: [] },
    thresholds: limits,
    provenance: {} as DashboardCard["provenance"],          // no test here reads it
    links: [], body: "", author: "", created_at: "", updated_at: "",
  };
}

/** A run as the server answers it. Cut to a range, `rows` hold the RANGE's figure while
 *  `refresh` stays the card's standing one — a range's figure never rolls into it. */
function ran(value: number, scoped: CardRunResult["scoped"] = null, standing = value): CardRunResult {
  return {
    columns: ["v"], rows: [[String(value)]], row_count: 1, caveats: [], error: null, scoped, value,
    refresh: { cadence: "daily", last_run: "", last_value: standing, prev_value: null, history: [standing] },
  };
}

function version(n: number, more: Partial<CockpitVersion> = {}): CockpitVersion {
  return {
    version: n, artifact_id: `a${n}`, kept_at: "2026-09-28T09:00:00Z", current: true, retired: false,
    approved_by: "user:u_42", source: "a person's own hand", note: "", vocabulary_version: 1,
    written_by_model: false,
    cards: ["c7f3a001", "c91b2002"], changes: { added: [], removed: [], changed: ["sec-headline"] }, ...more,
  };
}

const RATE = card("c7f3a001", "Return rate", { warning: 0.12, critical: null, direction: "above" });
const NET = card("c91b2002", "Net merchandise revenue");

function read(more: Partial<CanvasCockpit> = {}): CanvasCockpit {
  return {
    canvas_id: "cv1", connection_id: "thelook",
    cockpit: { ...version(2), spec: premise() },
    cards: [RATE, NET],
    range: { status: "standing", preset: null, start: null, last_day: null, covers: "", as_of: null, lag_days: null, still_moving: [] },
    ranges_on: true,
    history: [version(2), version(1, { current: false, approved_by: "user:u_7" })],
    ...more,
  };
}

const placed = () => screen.queryAllByTestId("cockpit-card").map(el => `${el.dataset.card}${el.dataset.tone ? `:${el.dataset.tone}` : ""}`);
const show = (active = true) => render(<CockpitTab canvasId="cv1" connectionId="thelook" schema="thelook" active={active} />);

beforeEach(() => {
  Object.values(api).forEach(f => f.mockReset());
  composer.props.length = 0;
  api.getCanvasCockpit.mockResolvedValue(read());
  api.runDashboardCard.mockImplementation(async (id: string) => ran(id === "c7f3a001" ? 0.1003 : 341000));
});

describe("with the flag off", () => {
  it("draws nothing and runs no card", async () => {
    api.getCanvasCockpit.mockResolvedValue(null);          // the route answered 404
    const { container } = show();
    await waitFor(() => expect(api.getCanvasCockpit).toHaveBeenCalled());
    await waitFor(() => expect(container).toBeEmptyDOMElement());
    expect(api.runDashboardCard).not.toHaveBeenCalled();
  });
});

describe("while another tab is showing", () => {
  it("asks the server for nothing", async () => {
    show(false);
    await new Promise(r => setTimeout(r, 20));
    expect(api.getCanvasCockpit).not.toHaveBeenCalled();
    expect(api.runDashboardCard).not.toHaveBeenCalled();
  });
});

describe("a kept cockpit", () => {
  it("is drawn from its spec, each card run once and drawn by the card's own component", async () => {
    show();
    await screen.findByTestId("cockpit");

    expect(api.getCanvasCockpit).toHaveBeenCalledWith("cv1", null);
    expect(api.runDashboardCard.mock.calls.map(c => c[0]).sort()).toEqual(["c7f3a001", "c91b2002"]);
    expect(placed()).toEqual(["c7f3a001", "c91b2002"]);
    expect(within(screen.getAllByTestId("cockpit-card")[0]).getByText("Return rate")).toBeInTheDocument();
    expect(screen.getByTestId("cockpit-version")).toHaveTextContent("Version 2 · approved by u_42");
    expect(screen.getByTestId("cockpit-waiting")).toHaveTextContent("1 card waits on a condition");
  });

  it("shows the conditional card when the card's own run is past its limit", async () => {
    api.runDashboardCard.mockImplementation(async (id: string) => ran(id === "c7f3a001" ? 0.126 : 341000));
    show();
    await screen.findByTestId("cockpit");
    expect(placed()).toEqual(["c7f3a001:bad", "c7f3a001", "c91b2002"]);
    expect(screen.queryByTestId("cockpit-waiting")).toBeNull();
  });

  it("a card whose run failed is unmeasured, so its condition waits", async () => {
    api.runDashboardCard.mockImplementation(async (id: string) => {
      if (id === "c7f3a001") throw new Error("the guards refused it");
      return ran(341000);
    });
    show();
    await screen.findByTestId("cockpit");
    expect(placed()).toEqual(["c7f3a001", "c91b2002"]);
  });

  it("keeps new cards for this canvas, not for the connection", async () => {
    show();
    await screen.findByTestId("cockpit");
    expect(composer.props.at(-1)).toMatchObject({
      connectionId: "thelook", schema: "thelook", keptFor: { scope: "canvas", scopeRef: "cv1" },
    });
  });
});

describe("the range", () => {
  it("is asked of the server and of every card, and its status is said", async () => {
    show();
    await screen.findByTestId("cockpit");
    expect(screen.getByRole("group", { name: "Cockpit range" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "As written" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByTestId("cockpit-range")).toBeNull();

    api.getCanvasCockpit.mockResolvedValue(read({
      range: { status: "to_date", preset: "month_to_date", start: "2026-09-01", last_day: "2026-09-20", covers: "September 2026 to date, 2026-09-01 to 2026-09-20", as_of: "2026-09-28", lag_days: 8, still_moving: [] },
    }));
    api.runDashboardCard.mockImplementation(async (id: string) =>
      ran(id === "c7f3a001" ? 0.13 : 298000,
        { covers: "September 2026 to date", standing: false, why: "", grain: "order_items.created_at" },
        id === "c7f3a001" ? 0.1003 : 341000));
    fireEvent.click(screen.getByRole("button", { name: "Month to date" }));

    await screen.findByTestId("cockpit-range");
    expect(screen.getByTestId("cockpit-range")).toHaveTextContent("To date · September 2026 to date, 2026-09-01 to 2026-09-20");
    expect(api.getCanvasCockpit).toHaveBeenLastCalledWith("cv1", { preset: "month_to_date" });
    expect(api.runDashboardCard).toHaveBeenLastCalledWith(expect.any(String), { preset: "month_to_date" });
    // Standing, the rate is within its limit; the RANGE's own figure is past it. The status
    // follows the range asked for, so the alert card shows — and each card shows the range's
    // figure, not its standing one.
    await waitFor(() => expect(placed()).toEqual(["c7f3a001:bad", "c7f3a001", "c91b2002"]));
    const net = screen.getAllByTestId("cockpit-card")[2];
    expect(within(net).getByText("298,000")).toBeInTheDocument();
    expect(within(net).queryByText("341,000")).toBeNull();
    expect(within(net).getByTestId("card-scoped")).toHaveTextContent("for September 2026 to date");
  });

  it("has no control when the Briefing's ranges are off", async () => {
    api.getCanvasCockpit.mockResolvedValue(read({ ranges_on: false }));
    show();
    await screen.findByTestId("cockpit");
    expect(screen.queryByRole("group", { name: "Cockpit range" })).toBeNull();
  });
});

describe("a canvas with no cockpit", () => {
  it("offers to start one from its cards, and starts it without a model", async () => {
    api.getCanvasCockpit.mockResolvedValueOnce(read({ cockpit: null, history: [] }));
    api.startCanvasCockpit.mockResolvedValue({ status: "kept", kept: true, version: 1, artifact_id: "a1", sentences: [] });
    show();

    await screen.findByText("This canvas has no cockpit yet");
    expect(screen.getByText(/This canvas holds 2 cards/)).toBeInTheDocument();
    expect(screen.queryByTestId("cockpit")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Start one from this canvas's cards" }));
    await screen.findByTestId("cockpit");                     // read again, and now there is one
    expect(api.startCanvasCockpit).toHaveBeenCalledWith("cv1");
    expect(api.getCanvasCockpit).toHaveBeenCalledTimes(2);
  });

  it("with no cards, says what a cockpit is made of and offers nothing it cannot do", async () => {
    api.getCanvasCockpit.mockResolvedValue(read({ cockpit: null, history: [], cards: [] }));
    show();
    await screen.findByText("This canvas has no cockpit yet");
    expect(screen.getByText(/A cockpit is made of cards/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Start/ })).toBeNull();
    expect(screen.getByTestId("composer")).toBeInTheDocument();
  });

  it("shows a refusal in the validator's own sentences, and keeps nothing on screen", async () => {
    const { CockpitRefused } = await import("@/lib/api");
    api.getCanvasCockpit.mockResolvedValue(read({ cockpit: null, history: [] }));
    api.startCanvasCockpit.mockRejectedValue(new CockpitRefused({
      status: "not_checked", kept: false, version: null, artifact_id: "",
      sentences: ["The cockpit's rules could not run: node was not found on this machine. Nothing is accepted unchecked."],
    }));
    show();
    fireEvent.click(await screen.findByRole("button", { name: "Start one from this canvas's cards" }));

    const refusal = await screen.findByTestId("cockpit-write-refusal");
    expect(refusal).toHaveTextContent("Nothing is accepted unchecked");
    expect(screen.getByText("Not checked · nothing was kept")).toBeInTheDocument();
    expect(screen.queryByTestId("cockpit")).toBeNull();
  });
});

describe("the history", () => {
  it("lists every version and goes back by keeping the earlier one again", async () => {
    api.restoreCanvasCockpit.mockResolvedValue({ status: "kept", kept: true, version: 3, artifact_id: "a3", sentences: [] });
    show();
    await screen.findByTestId("cockpit");
    expect(screen.queryByTestId("cockpit-history")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "History" }));
    const rows = within(screen.getByTestId("cockpit-history")).getAllByRole("listitem");
    expect(rows.map(r => r.textContent)).toEqual([
      expect.stringMatching(/^Version 21 changed · u_42 · .* · a person's own handcurrent$/),
      expect.stringMatching(/^Version 11 changed · u_7 · .* · a person's own handGo back to this$/),
    ]);

    fireEvent.click(within(rows[1]).getByRole("button", { name: "Go back to this" }));
    await waitFor(() => expect(api.restoreCanvasCockpit).toHaveBeenCalledWith("cv1", 1));
    await waitFor(() => expect(api.getCanvasCockpit).toHaveBeenCalledTimes(2));
  });

  it("a retired cockpit says who retired it, keeps its history, and can be started again", async () => {
    api.getCanvasCockpit.mockResolvedValue(read({
      cockpit: { ...version(3, { retired: true, approved_by: "user:u_7", source: "retired" }), spec: null },
      history: [version(3, { retired: true, approved_by: "user:u_7", source: "retired" }), version(2, { current: false })],
    }));
    show();
    await screen.findByText("This cockpit was retired");
    expect(screen.getByText(/Retired by u_7 on/)).toBeInTheDocument();
    expect(screen.queryByTestId("cockpit")).toBeNull();
    expect(screen.queryByRole("button", { name: "Retire" })).toBeNull();
    expect(screen.getByRole("button", { name: "Start a new one from this canvas's cards" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "History" }));
    const rows = within(screen.getByTestId("cockpit-history")).getAllByRole("listitem");
    expect(rows[0]).toHaveTextContent("Version 3Retired");
    expect(within(rows[0]).queryByRole("button")).toBeNull();
  });
});

describe("when the server cannot be read", () => {
  it("says so and offers to try again", async () => {
    api.getCanvasCockpit.mockRejectedValueOnce(new Error("Failed to read the cockpit"));
    show();
    await screen.findByText("The cockpit could not be read.");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await screen.findByTestId("cockpit");
  });
});
