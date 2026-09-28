// @vitest-environment jsdom

/**
 * How a cockpit draws one card (the user's mock, 2026-09-28). What is pinned is what a reader
 * reads off a tile: the figure at the scale its metric's unit states, how it moved against the
 * period it is compared with — and when that comparison is not at equal age, or has no figure,
 * that it says so — its limit, and what stands behind it.
 *
 * The trend's chart is a browser question (jsdom draws nothing); what is pinned for it is the
 * spec it is handed: the line, the newest point labelled, and the limit drawn across it.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";

import type { CardState } from "@/components/brief/PinnedCardBody";
import { CockpitTile, WithheldTile, changeWords, figureText, tileShape, trendSpec } from "@/components/cockpit/CockpitTile";
import { seriesTrend } from "@/components/brief/Sparkline";
import type { CardRunResult, CockpitCard } from "@/lib/api";

vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  graduateCard: vi.fn(),
  updateDashboardCard: vi.fn(),
}));
vi.mock("@/components/charts/vega/VegaChart", () => ({ VegaChart: () => <div data-testid="vega" /> }));

beforeAll(() => {
  globalThis.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} } as unknown as typeof ResizeObserver;
});

const RATIO = { kind: "ratio01" as const, lo: 0, hi: 1 };

function card(extra: Partial<CockpitCard> = {}): CockpitCard {
  return {
    id: "c1", connection_id: "thelook", scope: "user", scope_ref: "default", source: "authored", kind: "kpi",
    title: "Return rate", sql: "SELECT 1", query_ref: null, render: {},
    refresh: { cadence: "daily", last_run: "", last_value: null, prev_value: null, history: [] },
    thresholds: {}, provenance: { insight_id: "", origin_finding_id: "", receipt_ref: "", metric: "return_rate", metric_version: 1 },
    links: [], body: "", author: "", created_at: "", updated_at: "",
    own: true, made_from: "metric", unit: "ratio 0-1", stated_range: RATIO, ...extra,
  } as CockpitCard;
}

function ranged(value: number, previous: CardRunResult["previous"] = null): CardRunResult {
  return {
    columns: ["v"], rows: [[String(value)]], row_count: 1, caveats: [], error: null, value,
    refresh: { cadence: "daily", last_run: "", last_value: null, prev_value: null, history: [] },
    scoped: { covers: "July 2026", standing: false, why: "", grain: "orders.created_at" }, previous,
  } as CardRunResult;
}

const JUNE = { covers: "June 2026", word: "June", equal_age: true, value: 0.104, why: "" };
const DOORS = { onRemove: vi.fn(), onRefresh: vi.fn() };
const tile = (c: CockpitCard, run: CardRunResult, status: "within" | "over" | "unmeasured" = "unmeasured", sym = "$") =>
  render(<CockpitTile cs={{ card: c, run } as CardState & { card: CockpitCard }} status={status} sym={sym} doors={DOORS} />);

describe("a figure", () => {
  it("is drawn at the scale its unit states, with how it moved against the period before", () => {
    tile(card(), ranged(0.1003, JUNE));
    expect(screen.getByTestId("tile-figure")).toHaveTextContent("10.0%");
    expect(screen.getByTestId("tile-change")).toHaveTextContent("0.4 pts lower than June");
    expect(screen.getByTestId("tile-change")).toHaveAttribute("title", "Against June 2026");
    expect(screen.getByText("Approved metric")).toBeInTheDocument();
    expect(screen.queryByTestId("tile-not-equal-age")).toBeNull();
  });

  it("writes money with the business's symbol, and a relative move in percent", () => {
    tile(card({ title: "Net merchandise revenue", unit: "USD", stated_range: { kind: "open", lo: null, hi: null } }),
      ranged(341000, { ...JUNE, value: 330426 }), "unmeasured", "€");
    expect(screen.getByTestId("tile-figure")).toHaveTextContent("€341.0K");
    expect(screen.getByTestId("tile-change")).toHaveTextContent("3.2% higher than June");
  });

  it("says a comparison is not at equal age before the range settles", () => {
    tile(card(), ranged(0.1003, { ...JUNE, equal_age: false }));
    expect(screen.getByTestId("tile-not-equal-age")).toBeInTheDocument();
  });

  it("says when the period before has no figure — never a move from zero", () => {
    tile(card(), ranged(0.1003, { ...JUNE, value: null, why: "it has no figure there" }));
    expect(screen.getByTestId("tile-change")).toHaveTextContent("No figure for June to compare with");
  });

  it("colours a move only where its limit says which way is bad", () => {
    tile(card(), ranged(0.1003, JUNE));
    expect(screen.getByTestId("tile-change").style.color).toBe("var(--t2)");
  });

  it("with a limit, a move away from it reads good, and a figure past it reads as past it", () => {
    const limited = card({ thresholds: { warning: 0.12, direction: "above" } });
    const { unmount } = tile(limited, ranged(0.1003, JUNE), "within");
    expect(screen.getByTestId("tile-change").style.color).toBe("var(--grn4)");
    expect(screen.getByTestId("card-limit")).toHaveTextContent("Limit: at or above 12.0%");
    unmount();
    tile(limited, ranged(0.13, JUNE), "over");
    expect(screen.getByTestId("card-limit")).toHaveTextContent("Past its limit: at or above 12.0%");
    expect(screen.getByTestId("tile-figure").style.color).toBe("var(--red4)");
  });

  it("names the record behind it; a card with none is a query", () => {
    tile(card({ made_from: "trusted_query", unit: "", stated_range: null }), ranged(697));
    expect(screen.getByText("Trusted query")).toBeInTheDocument();
    expect(screen.getByTestId("tile-figure")).toHaveTextContent("697");
  });

  it("a card whose tables have no date says it is all history", () => {
    // Run standing, the server keeps the figure as the card's standing value, as any standing run.
    const run = { ...ranged(5), refresh: { ...ranged(5).refresh, last_value: 5 },
      scoped: { covers: "July 2026", standing: true, why: "no date on products", grain: null } };
    tile(card({ made_from: "", unit: "", stated_range: null }), run as CardRunResult);
    expect(screen.getByTestId("card-scoped")).toHaveTextContent("All history, not July 2026 — no date on products");
    expect(screen.getByText("Query")).toBeInTheDocument();
  });

  it("its doors are the card's: refresh and take off", () => {
    tile(card(), ranged(0.1003, JUNE));
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    fireEvent.click(screen.getByRole("button", { name: "Take off this cockpit" }));
    expect(DOORS.onRefresh).toHaveBeenCalledWith("c1");
    expect(DOORS.onRemove).toHaveBeenCalledWith("c1");
  });
});

describe("an empty figure", () => {
  it("is a figure that says the period has none — never a one-cell table reading NULL", () => {
    const empty = { ...ranged(0), rows: [[null]], value: null } as unknown as CardRunResult;
    expect(tileShape({ card: card(), run: empty })).toBe("figure");
    tile(card(), empty);
    expect(screen.getByTestId("tile-no-figure")).toHaveTextContent("No figure for July 2026");
  });
});

describe("the words", () => {
  it("say a figure its unit rules out plainly, and flag it", () => {
    expect(figureText(1.4, card(), "$")).toEqual({ text: "1.4", outside: true });
    expect(figureText(0, card(), "$")).toEqual({ text: "0", outside: false });
  });

  it("say no relative move from a base of zero", () => {
    const plain = card({ unit: "", stated_range: null });
    expect(changeWords(5, 0, plain, "June")).toBeNull();
    expect(changeWords(5, 5, plain, "June")).toEqual({ text: "the same as June", sign: 0 });
  });
});

describe("a series", () => {
  const rows = [["2026-05-01", "0.101"], ["2026-06-01", "0.104"], ["2026-07-01", "0.1003"]];
  const series = { ...ranged(0), columns: ["month", "rate"], rows, value: null, scoped: null } as unknown as CardRunResult;

  it("is drawn as a trend, its newest point named with its figure", () => {
    expect(tileShape({ card: card(), run: series })).toBe("trend");
    tile(card(), series);
    expect(screen.getByTestId("tile-newest")).toHaveTextContent(/2026 · 10\.0%$/);
    expect(screen.getByTestId("vega")).toBeInTheDocument();
    expect(screen.getByText("Approved metric, by month")).toBeInTheDocument();
  });

  it("carries its limit across the chart, labelled", () => {
    const trend = seriesTrend(series.columns, series.rows)!;
    const spec = trendSpec(trend, card({ thresholds: { warning: 0.12 } }), "$") as { layer: Record<string, unknown>[] };
    const marks = spec.layer.map(l => (l.mark as { type: string }).type);
    expect(marks).toEqual(["line", "point", "text", "rule", "text"]);
    expect(spec.layer[3].data).toEqual({ values: [{ y: 0.12 }] });
    expect((spec.layer[4].encoding as { text: { value: string } }).text.value).toBe("Limit");
    expect((spec.layer[2].encoding as { text: { value: string } }).text.value).toBe("10.0%");
    expect(trendSpec(trend, card(), "$")).toMatchObject({ layer: expect.any(Array) });
    expect((trendSpec(trend, card(), "$") as { layer: unknown[] }).layer).toHaveLength(3);
  });
});

describe("a withheld card", () => {
  it("is a tile that says it is here and not shown", () => {
    render(<WithheldTile />);
    expect(screen.getByText("Withheld")).toBeInTheDocument();
    expect(screen.getByText("Not shown")).toBeInTheDocument();
    expect(screen.getByText("You may not see this card.")).toBeInTheDocument();
  });
});
