// @vitest-environment jsdom

/**
 * The cockpit as a canvas (docs/COCKPIT_CANVAS_2026-10-08.md), drawn: a note and an image in a
 * section beside the cards, each with its stamp; every element at its size, as a span the
 * section's columns cut; the doors an owner has and a reader does not; and a bigger figure
 * that shows its metric's trend. Geometry is a browser question (jsdom is 0×0); what is pinned
 * is what the grid is told.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { change, fireEvent, render, screen, waitFor, within } from "@/lib/testing";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import type { CardState } from "@/components/brief/PinnedCardBody";
import { CockpitArrange } from "@/components/cockpit/CockpitArrange";
import { CockpitTile } from "@/components/cockpit/CockpitTile";
import { ComposedCockpit, type CockpitDoors } from "@/components/cockpit/ComposedCockpit";
import type { ImageStamp } from "@/components/cockpit/StaticTile";
import { readMetricTrend, type CardRunResult, type CockpitCard, type DashboardCard, type MetricTrend } from "@/lib/api";
import type { CockpitSpec } from "@/lib/cockpit/edit";
import type { CardStatus, CockpitHostState, RangeStatus } from "@/lib/cockpit/hostState";

vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  graduateCard: vi.fn(),
  updateDashboardCard: vi.fn(),
  readMetricTrend: vi.fn(),
}));
vi.mock("@/components/charts/vega/VegaChart", () => ({ VegaChart: () => <div data-testid="vega" /> }));

beforeAll(() => {
  globalThis.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} } as unknown as typeof ResizeObserver;
});
beforeEach(() => { vi.mocked(readMetricTrend).mockReset(); });

type Spec = CockpitSpec & { elements: Record<string, { type: string; props: Record<string, unknown>; children: string[]; visible?: unknown }> };
const premise = (): Spec => JSON.parse(readFileSync(resolve(process.cwd(), "lib/cockpit/premise.fixture.json"), "utf8"));

/** The premise with a note and an image in its headline section, and the revenue card made large. */
function canvas(): Spec {
  const s = premise();
  s.elements["note-1"] = { type: "Note", props: { text: "Check **ops** before the 15th.", size: "wide", author: "user:amit", written_at: "2026-10-08T09:00:00Z" }, children: [] };
  s.elements["image-1"] = { type: "Image", props: { object: "ab12cd34ef56", caption: "Promo calendar", size: "tall" }, children: [] };
  s.elements["sec-headline"].children.push("note-1", "image-1");
  s.elements["card-net"].props.size = "large";
  return s;
}

function card(id: string, title: string, value: number, extra: Partial<DashboardCard> = {}): CardState {
  const refresh = { cadence: "daily", last_run: "2026-09-28T06:00:00Z", last_value: value, prev_value: null, history: [value] };
  const c: DashboardCard = {
    id, connection_id: "thelook", scope: "user", scope_ref: "default", source: "authored", kind: "kpi",
    title, sql: "SELECT 1", query_ref: null, render: {}, refresh, thresholds: {},
    provenance: { origin_finding_id: "", receipt_ref: "", metric: "", metric_version: 0 } as DashboardCard["provenance"],
    links: [], body: "", author: "", created_at: "", updated_at: "", ...extra,
  };
  return { card: c, run: { columns: ["v"], rows: [[value]], row_count: 1, caveats: [], error: null, refresh } };
}

const CARDS = [card("c7f3a001", "Return rate", 0.1003), card("c91b2002", "Net merchandise revenue", 341000)];
const READER: CockpitDoors = { onRemove: vi.fn(), onRefresh: vi.fn() };
const PROMO: ImageStamp = { file_name: "promo.png", uploaded_by: "user:amit", uploaded_at: "2026-10-08T09:00:00Z", readable: true, why: "", url: "http://api/cockpits/images/ab12cd34ef56?connection_id=thelook" };

function host(range: RangeStatus, rate: CardStatus, net: CardStatus = "within"): CockpitHostState {
  return { range: { status: range }, cards: { c7f3a001: { status: rate }, c91b2002: { status: net } } };
}

const cellOf = (card: string) => screen.getAllByTestId("cockpit-card").find(c => c.dataset.card === card) as HTMLElement;

describe("a note and an image, drawn", () => {
  it("a note is the person's words with their stamp; an image its bytes with its stamp", () => {
    render(<ComposedCockpit spec={canvas()} cards={CARDS} host={host("final", "within")} doors={READER} images={{ ab12cd34ef56: PROMO }} />);
    const note = screen.getByTestId("cockpit-note");
    expect(within(note).getByText("ops").tagName).toBe("STRONG");
    expect(within(note).getByTestId("note-chip")).toHaveTextContent("Your words");
    expect(note).toHaveTextContent(/amit · written/);
    expect(note).toHaveTextContent("not measured, cited by nothing");
    // No status, no period, no comparison on either.
    expect(within(note).queryByTestId("tile-change")).toBeNull();

    const image = screen.getByTestId("cockpit-image");
    const bytes = within(image).getByTestId("cockpit-image-bytes");
    expect(bytes).toHaveAttribute("src", PROMO.url);
    expect(bytes).toHaveAttribute("alt", "Promo calendar");
    expect(image).toHaveTextContent("promo.png · uploaded by amit");
    expect(image).toHaveTextContent("no period, no comparison");
  });

  it("an image the reader may not see stands as its caption and says why", () => {
    render(<ComposedCockpit spec={canvas()} cards={CARDS} host={host("final", "within")} doors={READER}
      images={{ ab12cd34ef56: { ...PROMO, readable: false, why: "This image is not in this connection's cockpit volume, or it is gone." } }} />);
    const image = screen.getByTestId("cockpit-image");
    expect(within(image).queryByTestId("cockpit-image-bytes")).toBeNull();
    expect(within(image).getByTestId("cockpit-image-withheld")).toHaveTextContent("not in this connection's cockpit volume");
    expect(image).toHaveTextContent("Promo calendar");
  });

  it("an image the read said nothing of is not shown either, and says so", () => {
    render(<ComposedCockpit spec={canvas()} cards={CARDS} host={host("final", "within")} doors={READER} />);
    expect(screen.getByTestId("cockpit-image-withheld")).toHaveTextContent("the cockpit's read said nothing of it");
  });

  it("a note's link opens elsewhere and is kept to http and https", () => {
    const s = canvas();
    s.elements["note-1"].props.text = "See [the plan](https://example.com/plan) and [this](javascript:alert(1)).";
    render(<ComposedCockpit spec={s} cards={CARDS} host={host("final", "within")} doors={READER} />);
    const link = screen.getByRole("link", { name: "the plan" });
    expect(link).toHaveAttribute("href", "https://example.com/plan");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(screen.queryByRole("link", { name: "this" })).toBeNull();
    expect(screen.getByText("this")).toBeInTheDocument();
  });
});

describe("a size", () => {
  it("is a span the section's columns cut, and a card that says none takes what its shape asks", () => {
    render(<ComposedCockpit spec={canvas()} cards={CARDS} host={host("final", "within")} doors={READER} images={{ ab12cd34ef56: PROMO }} />);
    const note = screen.getByTestId("cockpit-note-cell");
    expect(note.dataset.size).toBe("wide");
    expect(note.style.gridColumn).toBe("span 2");
    expect(note.style.gridRow).toBe("");

    const image = screen.getByTestId("cockpit-image-cell");
    expect(image.dataset.size).toBe("tall");
    expect(image.style.gridColumn).toBe("");
    expect(image.style.gridRow).toBe("span 2");

    const net = cellOf("c91b2002");
    expect(net.dataset.size).toBe("large");
    expect(net.style.gridColumn).toBe("span 2");
    expect(net.style.gridRow).toBe("span 2");

    // A figure that says no size is small, as it was before sizes.
    const rate = cellOf("c7f3a001");
    expect(rate.dataset.size).toBe("small");
    expect(rate.style.gridColumn).toBe("");
  });

  it("never spans more columns than the section draws", () => {
    const s = canvas();
    s.elements["sec-headline"].props.columns = 1;
    render(<ComposedCockpit spec={s} cards={CARDS} host={host("final", "within")} doors={READER} />);
    expect(cellOf("c91b2002").style.gridColumn).toBe("");
    expect(cellOf("c91b2002").style.gridRow).toBe("span 2");
  });

  it("a bigger figure shows it larger, and — read for a range — its metric's trend", async () => {
    vi.mocked(readMetricTrend).mockResolvedValue({
      series: [
        { start: "2026-06-01", last_day: "2026-06-30", label: "Jun", value: 0.1, value_text: "10%", partial: null, current: false },
        { start: "2026-07-01", last_day: "2026-07-31", label: "Jul", value: 0.11, value_text: "11%", partial: null, current: true },
      ],
    } as unknown as MetricTrend);
    const metricCard = { ...CARDS[0].card, made_from: "metric", provenance: { ...CARDS[0].card.provenance, metric: "return_rate" } } as CockpitCard;
    const run = { ...CARDS[0].run, value: 0.1003, scoped: { covers: "July 2026", standing: false, why: "", grain: "orders.created_at" } } as CardRunResult;
    render(<CockpitTile cs={{ card: metricCard, run }} status="within" sym="$" doors={READER}
      place={{ elementKey: "card-rate", size: "wide", range: { preset: "previous_month" }, schema: "thelook" }} />);
    expect(screen.getByTestId("tile-figure").dataset.size).toBe("wide");
    expect(screen.getByTestId("tile-figure").style.fontSize).toBe("2.1em");
    await waitFor(() => expect(screen.getByTestId("tile-trend")).toBeInTheDocument());
    expect(readMetricTrend).toHaveBeenCalledWith("thelook", "return_rate", { preset: "previous_month" }, "thelook");
  });

  it("a small figure reads no trend", () => {
    const metricCard = { ...CARDS[0].card, made_from: "metric", provenance: { ...CARDS[0].card.provenance, metric: "return_rate" } } as CockpitCard;
    const run = { ...CARDS[0].run, value: 0.1003, scoped: { covers: "July 2026", standing: false, why: "", grain: "orders.created_at" } } as CardRunResult;
    render(<CockpitTile cs={{ card: metricCard, run }} status="within" sym="$" doors={READER}
      place={{ elementKey: "card-rate", size: "small", range: { preset: "previous_month" } }} />);
    expect(screen.getByTestId("tile-figure").style.fontSize).toBe("");
    expect(screen.queryByTestId("tile-trend")).toBeNull();
    expect(readMetricTrend).not.toHaveBeenCalled();
  });
});

describe("the doors", () => {
  const owner = (): CockpitDoors => ({ ...READER, onTakeOff: vi.fn(), onResize: vi.fn(), onEditNote: vi.fn(), onRecaption: vi.fn() });

  it("an owner takes a note off, resizes an element and edits a note, each by the element's key", () => {
    const doors = owner();
    render(<ComposedCockpit spec={canvas()} cards={CARDS} host={host("final", "within")} doors={doors} images={{ ab12cd34ef56: PROMO }} />);
    const note = screen.getByTestId("cockpit-note");
    fireEvent.click(within(note).getByRole("button", { name: "Take off this cockpit" }));
    expect(doors.onTakeOff).toHaveBeenCalledWith("note-1");

    change(within(cellOf("c91b2002")).getByTestId("size-pick"), { target: { value: "hero" } });
    expect(doors.onResize).toHaveBeenCalledWith("card-net", "hero");

    fireEvent.click(within(note).getByRole("button", { name: "Edit the note" }));
    fireEvent.change(within(note).getByRole("textbox", { name: "The note's words" }), { target: { value: "Check ops by the 12th." } });
    fireEvent.click(within(note).getByRole("button", { name: "Keep" }));
    expect(doors.onEditNote).toHaveBeenCalledWith("note-1", "Check ops by the 12th.");

    // The corner is there to drag on every element an owner may resize.
    expect(screen.getAllByTestId("resize-corner").length).toBeGreaterThanOrEqual(4);
  });

  it("a reader with no doors sees no corner, no size pick and no take-off on a note", () => {
    render(<ComposedCockpit spec={canvas()} cards={CARDS} host={host("final", "within")} doors={READER} images={{ ab12cd34ef56: PROMO }} />);
    expect(screen.queryAllByTestId("resize-corner")).toEqual([]);
    expect(screen.queryAllByTestId("size-pick")).toEqual([]);
    expect(within(screen.getByTestId("cockpit-note")).queryByRole("button", { name: "Take off this cockpit" })).toBeNull();
  });
});

describe("arranging a canvas", () => {
  it("names a note by its words and an image by its caption, and hands back a size", () => {
    const onChange = vi.fn();
    render(<CockpitArrange spec={canvas()} lines={new Map([["c7f3a001", { title: "Return rate" }], ["c91b2002", { title: "Net merchandise revenue" }]])} onChange={onChange} />);
    const rows = screen.getAllByTestId("arrange-card");
    expect(rows.map(r => r.dataset.kind)).toEqual(["card", "card", "card", "note", "image", "card"]);
    expect(rows[3]).toHaveTextContent("Note · Check **ops** before the 15th.");
    expect(rows[3]).toHaveTextContent("yours, not measured");
    expect(rows[4]).toHaveTextContent("Image · Promo calendar");

    change(within(rows[3]).getByTestId("size-pick"), { target: { value: "large" } });
    const next = onChange.mock.calls.at(-1)![0] as CockpitSpec;
    expect(next.elements["note-1"].props.size).toBe("large");

    change(within(rows[2]).getByTestId("size-pick"), { target: { value: "small" } });
    const back = onChange.mock.calls.at(-1)![0] as CockpitSpec;
    expect("size" in back.elements["card-net"].props).toBe(false);
  });
});
