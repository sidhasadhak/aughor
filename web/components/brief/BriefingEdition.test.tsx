// @vitest-environment jsdom
/**
 * Arc BC — the Briefing as an edition the model composed (ROADMAP §3.67, §6 item 59).
 *
 * Opening never spends: the page READS the edition and writes one only on a click. A written edition is drawn from
 * its blocks — each from the sources the server ran: a cited number opens its source beside the page, a control fades
 * the rows of every other value in the blocks that listen to it, a drill writes one level deeper under its block, a
 * block of a type the page does not know is said, and "Not now" puts a decision away.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { BriefingEdition as Edition, BriefingGuideResponse, EditionSource } from "@/lib/api";

const api = vi.hoisted(() => ({
  readBriefingEdition: vi.fn(), writeBriefingEdition: vi.fn(), readBriefingGuide: vi.fn(), draftBriefingGuide: vi.fn(),
  getGroups: vi.fn(), putMyPreference: vi.fn(), drillBriefingEdition: vi.fn(),
}));
vi.mock("@/lib/api", async (importOriginal) => ({ ...(await importOriginal<typeof import("@/lib/api")>()), ...api }));
vi.mock("@/components/brief/BriefSchedule", () => ({ BriefSchedule: () => null }));
vi.mock("@/lib/useAughorChat", () => ({ useAughorChat: () => ({ messages: [], sendMessage: vi.fn(), status: "ready" }) }));
vi.mock("@/lib/objects", () => ({ getObjectCatalog: vi.fn(async () => ({ types: [] })) }));
vi.mock("@/components/charts/vega/VegaChart", () => ({
  VegaChart: ({ spec }: { spec: unknown }) => <div data-testid="vega" data-spec={JSON.stringify(spec)} />,
}));

import { BriefingEdition } from "./BriefingEdition";

const PERIOD = { period: "week", key: "range:last_week:2026-10-19..2026-10-25", preset: "last_week", label: "Weekly",
  start: "2026-10-19", end: "2026-10-26", last_day: "2026-10-25", previous_start: "2026-10-12", previous_end: "2026-10-19",
  last_year_start: null, last_year_end: null, as_of: "2026-10-29", lag_days: 3, lag_source: "learned", still_moving: [],
  covers: "the week 2026-10-19 to 2026-10-25", compared_with: "the week before", last_year_label: null } as unknown as Edition["period"];

const S = (over: Partial<EditionSource>): EditionSource => ({ id: "s", label: "S", kind: "query", columns: [], rows: [], sql: "SELECT 1",
  status: "final", facts: {}, receipts: [], caveats: [], note: "", error: "", unit: "", better: "up", ...over });

const SOURCES: Record<string, EditionSource> = {
  sales: S({ id: "sales", label: "Sales", kind: "check", columns: ["start", "value", "this_range"], unit: "EUR",
             rows: [["2026-10-12", 158815, false], ["2026-10-19", 166988, true]], facts: { current: 166988 },
             sql: "SELECT SUM(gmv_eur) FROM orders" }),
  by_top: S({ id: "by_top", label: "Sales by top client", kind: "breakdown", unit: "EUR",
              columns: ["segment", "this_range", "usual", "change", "change_pct", "rows", "too_few"],
              rows: [[true, 85349, 75932, 9417, 0.124, 70, false], [false, 81640, 85028, -3388, -0.04, 189, false]],
              facts: { check: "sales", by: "is_top", within: {} } }),
  stores: S({ id: "stores", label: "Top clients by storefront", columns: ["platform", "this_week", "usual"],
              rows: [["Mytheresa", 38840, 29849], ["YOOX", 9845, 11051]] }),
  orders: S({ id: "orders", label: "Largest orders", columns: ["order_id", "platform", "gmv_eur"],
              rows: [["MYT-1", "Mytheresa", 3459], ["NET-1", "NET-A-PORTER", 2505]] }),
  countries: S({ id: "countries", label: "By ship country", columns: ["country", "this_week", "usual"],
                 rows: [["Japan", 4935, 2317], ["United States", 20364, 23639]] }),
};

const WRITTEN: Edition = { built: true, composed: true, scope_key: "c", period: { ...PERIOD, measured: [] },
  reader: { group_id: "leadership", name: "Leadership" }, sources: SOURCES, drill_columns: { sales: ["platform", "is_top"] },
  blocks: [
    { id: "lead", type: "lead", text: "Sales were an ordinary {€167.0k|sales}, but top clients spent {€9.4k more|by_top}." },
    { id: "where", type: "bridge", source: "by_top", title: "Where the week's sales came from" },
    { id: "store", type: "control", source: "stores", column: "platform", title: "Look at one storefront" },
    { id: "cmp", type: "compare", source: "stores", label: "platform", value: "this_week", compare: "usual", listens: "store",
      title: "Top clients by storefront" },
    { id: "tbl", type: "table", source: "orders", title: "The largest orders", link: "order_id" },
    { id: "map", type: "map", source: "countries", label: "country", value: "this_week", compare: "usual", title: "Where orders went" },
    { id: "odd", type: "sankey", source: "sales" },
    { id: "dec", type: "decision", text: "Look into app conversion before Singles Day?", actions: ["investigate", "not_now"] },
  ],
  withheld: [{ block: "lead", sentence: "Promotions lifted sales.", why: "it claims a cause (“lifted”)" }],
  guide: { version: 5, state: "draft" }, model_steps: 5, queries: 2, generated_at: "2026-10-29T09:00:00Z", currency_code: "EUR" };

const GUIDE: BriefingGuideResponse = {
  available: true, published_version: null, editions_read: { version: 5, state: "draft" },
  version: { version: 5, state: "draft", by: "explorer", note: "", created_at: "", published_at: "" }, versions: [],
  guide: { business: "A luxury group.", ranges: { week: "", month: "", year: "", custom: "", day: "" }, news: {},
           comparisons: [], calendar: [], care: [], checks: [], dropped: [], readers: [], proposed_readers: [] },
};

beforeEach(() => {
  Object.values(api).forEach(f => f.mockReset());
  api.getGroups.mockResolvedValue({ ladder: [], builtin_groups: [], groups: [
    { id: "leadership", name: "Leadership", kind: "function", description: "", channel_trigger_id: "" }] });
  api.readBriefingGuide.mockResolvedValue(GUIDE);
  api.putMyPreference.mockResolvedValue(undefined);
});

describe("BriefingEdition", () => {
  it("reads on opening and never writes", async () => {
    api.readBriefingEdition.mockResolvedValue({ built: false, scope_key: "c", period: PERIOD, reader: "leadership" });
    render(<BriefingEdition connectionId="dcc63d83" schema="luxexperience" />);
    expect(await screen.findByText(/Not written yet for Leadership/)).toBeTruthy();
    expect(api.readBriefingEdition).toHaveBeenCalledTimes(1);
    expect(api.writeBriefingEdition).not.toHaveBeenCalled();
  });

  it("writes only when asked, for the reader on screen", async () => {
    api.readBriefingEdition.mockResolvedValue({ built: false, scope_key: "c", period: PERIOD, reader: "leadership" });
    api.writeBriefingEdition.mockResolvedValue(WRITTEN);
    render(<BriefingEdition connectionId="dcc63d83" schema="luxexperience" />);
    fireEvent.click(await screen.findByRole("button", { name: "Write this week's edition" }));
    await screen.findByTestId("edition-lead");
    expect(api.writeBriefingEdition).toHaveBeenCalledWith("dcc63d83", { preset: "last_week" }, "leadership", "luxexperience", undefined);
  });

  it("draws the blocks it was given, in their order, and says the one it cannot draw", async () => {
    api.readBriefingEdition.mockResolvedValue(WRITTEN);
    render(<BriefingEdition connectionId="dcc63d83" schema="luxexperience" />);
    await screen.findByTestId("edition-lead");
    const types = screen.getAllByTestId("edition-block").map(b => b.getAttribute("data-type"));
    expect(types).toEqual(["lead", "bridge", "control", "compare", "table", "map", "sankey", "decision"]);
    expect(screen.getByTestId("edition-bridge")).toBeTruthy();
    expect(screen.getByText(/which this page cannot draw/)).toBeTruthy();
    const odd = screen.getAllByTestId("edition-block")[6];
    expect(within(odd).getByRole("heading").textContent).toBe("Sales");        // untitled: its source's own label
    expect(screen.getByTestId("edition-withheld").textContent).toContain("Promotions lifted sales.");
    const spec = JSON.parse(screen.getByTestId("vega").getAttribute("data-spec") ?? "{}");
    expect(spec.transform[0].lookup).toBe("properties.name");                   // countries looked up by name
    expect(spec.transform[0].from.data.values.map((v: { place: string }) => v.place)).toEqual(["Japan", "United States"]);
  });

  it("opens a cited number's source beside the page", async () => {
    api.readBriefingEdition.mockResolvedValue(WRITTEN);
    render(<BriefingEdition connectionId="dcc63d83" schema="luxexperience" />);
    fireEvent.click(await screen.findByText("€167.0k"));
    const panel = await screen.findByTestId("edition-evidence");
    expect(within(panel).getByText("Sales")).toBeTruthy();
    expect(panel.textContent).toContain("SELECT SUM(gmv_eur) FROM orders");
  });

  it("fades every other storefront in the blocks that listen to the control", async () => {
    api.readBriefingEdition.mockResolvedValue(WRITTEN);
    render(<BriefingEdition connectionId="dcc63d83" schema="luxexperience" />);
    await screen.findByTestId("edition-lead");
    fireEvent.click(screen.getByRole("radio", { name: "Mytheresa" }));
    const rows = within(screen.getAllByTestId("edition-pair-rows")[0]).getAllByRole("row");   // the comparison, not the map's list
    expect(rows[0].getAttribute("data-faded")).toBeNull();                    // Mytheresa
    expect(rows[1].getAttribute("data-faded")).toBe("true");                  // YOOX
  });

  it("writes a drill under the block it came from, and puts a decision away on Not now", async () => {
    api.readBriefingEdition.mockResolvedValue(WRITTEN);
    api.drillBriefingEdition.mockResolvedValue({ at: 2, block: { id: "drill_x", type: "compare", source: "drill_src", kicker: "Drill",
      title: "Sales by platform, within is top True, against usual", by_code: true },
      source: S({ id: "drill_src", label: "Sales by platform", kind: "drill", columns: ["segment", "this_range", "usual", "change", "change_pct", "rows", "too_few"],
                  rows: [["Mytheresa", 38840, 29849, 8991, 0.3, 24, true]], facts: { check: "sales", by: "platform", within: { is_top: true } } }) });
    render(<BriefingEdition connectionId="dcc63d83" schema="luxexperience" />);
    await screen.findByTestId("edition-lead");
    fireEvent.click(screen.getByRole("button", { name: /By platform, within Yes/ }));
    await waitFor(() => expect(screen.getAllByTestId("edition-block")[2].getAttribute("data-type")).toBe("compare"));
    expect(api.drillBriefingEdition).toHaveBeenCalledWith("dcc63d83", { preset: "last_week" }, "leadership",
      { source_id: "by_top", column: "platform", segment: true, after: "where" }, "luxexperience", undefined);
    fireEvent.click(screen.getByRole("button", { name: "Not now" }));
    expect(screen.queryByText(/Look into app conversion/)).toBeNull();
  });

  it("with no guide, says so and drafts one only on a click", async () => {
    api.readBriefingGuide.mockResolvedValue({ ...GUIDE, available: false, guide: null, version: null, editions_read: null });
    api.readBriefingEdition.mockResolvedValue({ built: false, scope_key: "c", period: PERIOD, reader: "" });
    api.draftBriefingGuide.mockResolvedValue(GUIDE);
    render(<BriefingEdition connectionId="dcc63d83" schema="luxexperience" />);
    const empty = await screen.findByTestId("edition-no-guide");
    expect(api.draftBriefingGuide).not.toHaveBeenCalled();
    fireEvent.click(within(empty).getByRole("button", { name: "Draft the guide" }));
    await waitFor(() => expect(api.draftBriefingGuide).toHaveBeenCalledWith("dcc63d83", "luxexperience"));
  });
});
