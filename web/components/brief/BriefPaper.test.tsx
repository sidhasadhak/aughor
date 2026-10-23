// @vitest-environment jsdom
/**
 * The Briefing as a morning paper (2026-10-12). The pieces say what they hold and what they could not
 * read: a desk column that failed says so, an empty one says why, a figure never measured is hatched,
 * and the sources number on from the lead's own citations.
 */
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";

import { DeskColumns, InBrief, PaperDateline, PaperEdgeNotice, PaperNumbers, PaperSources, numberDesk, paperDate, rangeNumbers } from "@/components/brief/BriefPaper";
import { firstSentence } from "@/components/BriefingPanel";
import type { BriefingDesk, BriefingRangeBlock, BriefingRangeMeasure, DeskItem } from "@/lib/api";

vi.mock("@/lib/navigate", () => ({ requestTab: vi.fn() }));

const item = (kind: string, title: string, extra: Partial<DeskItem> = {}): DeskItem =>
  ({ kind, title, text: `${title} — why`, source: { kind: "claim", ref: title, label: `Source of ${title}` }, ...extra });

const DESK: BriefingDesk = {
  connection_id: "c1", schema: null, as_of: "2026-10-12", unread: {},
  trends: { items: [item("answer", "August revenue rose 13.2%", { status: "Provisional" }), item("trend", "Sell-through has risen since 2020", { status: "Provisional" })], more: 0 },
  gaps: { items: [item("disagree", "2025 revenue has three answers", { action: { verb: "Settle it", kind: "inquiry", ref: "q1" } })], more: 2 },
  decide: { items: [], more: 0 },
};

describe("the paper on data that ended (design-mockups/briefing-data-ended.html)", () => {
  it("marks the edition final, names the day the data ended, and says no settling lag", () => {
    render(<PaperDateline today="Friday 23 October 2026" covers="covering September 2018" lagDays={9} records={0}
      endedOn="2018-10-17" />);
    expect(screen.getByTestId("paper-final")).toHaveTextContent("final");
    expect(screen.getByTestId("paper-ended")).toHaveTextContent("data ended Wed 17 Oct 2018");
    expect(screen.queryByText(/settles/)).toBeNull();
  });

  it("keeps the settling chip on live data", () => {
    render(<PaperDateline today="Friday 23 October 2026" covers="covering 20 October" lagDays={29} records={0} />);
    expect(screen.getByText("data settles 29 days late")).toBeInTheDocument();
    expect(screen.queryByTestId("paper-final")).toBeNull();
  });

  it("says where the data ended in one line, with a door to the editions table", () => {
    const onCovers = vi.fn();
    render(<PaperEdgeNotice note="The data ended on 2018-10-17 (Wednesday)." onCovers={onCovers} />);
    expect(screen.getByTestId("paper-edge-notice")).toHaveTextContent("The data ended on 2018-10-17 (Wednesday).");
    fireEvent.click(screen.getByText("What each edition covers ↓"));
    expect(onCovers).toHaveBeenCalledOnce();
  });
});

describe("numberDesk", () => {
  it("numbers the desk's stories on from the lead's citations, in reading order", () => {
    const refs = numberDesk(DESK, 4);
    expect([...refs.values()]).toEqual([4, 5, 6]);
    expect(numberDesk(null, 1).size).toBe(0);
  });
});

describe("firstSentence", () => {
  it("keeps a decimal inside the sentence and stops at the sentence's end", () => {
    expect(firstSentence("The return rate is 9.9%, based on items. A second sentence.")).toBe("The return rate is 9.9%, based on items.");
    expect(firstSentence("x".repeat(300), 50)).toHaveLength(50);
  });
});

describe("paperDate", () => {
  it("names the day in words", () => {
    expect(paperDate(new Date(2026, 9, 12))).toBe("Monday 12 October 2026");
  });
});

describe("DeskColumns", () => {
  it("prints each column, its story's number and its button; an empty column says why; a remainder is counted", () => {
    render(<DeskColumns desk={DESK} refs={numberDesk(DESK, 1)} connectionId="c1" />);
    const trends = screen.getByTestId("paper-col-trends");
    expect(within(trends).getAllByText("provisional")).toHaveLength(1);       // an investigation's reading, not every finding
    const gaps = screen.getByTestId("paper-col-gaps");
    expect(within(gaps).getByRole("button", { name: "Settle it" })).toBeInTheDocument();
    expect(within(gaps).getByText("2 more in the Record →")).toBeInTheDocument();
    expect(within(screen.getByTestId("paper-col-decide")).getByText("Nothing is waiting on you.")).toBeInTheDocument();
    expect(within(gaps).getByText("3", { selector: "sup" })).toBeInTheDocument();
  });

  it("a column whose store could not be read says so, and a failed read says it in every column", () => {
    const { rerender } = render(<DeskColumns desk={{ ...DESK, trends: null, unread: { claims: "claims could not be read just now" } }}
      refs={new Map()} connectionId="c1" />);
    expect(within(screen.getByTestId("paper-col-trends")).getByText("claims could not be read just now")).toBeInTheDocument();
    rerender(<DeskColumns desk={null} error="The Briefing's desk could not be read" refs={new Map()} connectionId="c1" />);
    for (const k of ["trends", "gaps", "decide"])
      expect(within(screen.getByTestId(`paper-col-${k}`)).getByText("The Briefing's desk could not be read")).toBeInTheDocument();
  });

  it("while the desk is read the columns say so, never 'nothing'", () => {
    render(<DeskColumns desk={undefined} refs={new Map()} connectionId="c1" />);
    expect(screen.getAllByText("Reading…")).toHaveLength(3);
  });
});

describe("PaperNumbers", () => {
  it("a figure never measured is hatched as such, never a zero; a change carries its sign", () => {
    render(<PaperNumbers title="The day in numbers" rows={[
      { key: "r", label: "Revenue", value: "$14.7K", change: { text: "+3.1%", sign: 1 } },
      { key: "c", label: "Cart → order", value: "", unknown: "not measured" }]} />);
    expect(screen.getByText("not measured")).toBeInTheDocument();
    expect(screen.getByText("+3.1%")).toBeInTheDocument();
    expect(screen.queryByText("0")).toBeNull();
  });
});

describe("InBrief", () => {
  it("leads to every finding, and an empty range edition says why with the way back", () => {
    const onAll = vi.fn(); const standing = vi.fn();
    const { rerender } = render(<InBrief title="In brief" items={[{ id: "a", node: "One line." }]} total={44} onAll={onAll} allOpen={false} />);
    fireEvent.click(screen.getByRole("button", { name: "All 44 findings →" }));
    expect(onAll).toHaveBeenCalled();
    rerender(<InBrief title="In brief" items={[]} total={0} onAll={onAll} allOpen={false}
      empty="No finding could be measured for the week." standing={standing} />);
    expect(screen.getByTestId("paper-brief-empty")).toHaveTextContent("No finding could be measured for the week.");
    fireEvent.click(screen.getByRole("button", { name: "What we know →" }));
    expect(standing).toHaveBeenCalled();
  });

  it("says the findings it left out because they read a table turned off, and nothing when none were", () => {
    const said = "2 findings read luxexperience.orders_archive, turned off for analysis, and are left out.";
    const { rerender } = render(<InBrief title="In brief" items={[{ id: "a", node: "One line." }]} total={5}
      onAll={() => {}} allOpen={false} leftOut={said} />);
    expect(screen.getByTestId("paper-left-out")).toHaveTextContent(said);
    rerender(<InBrief title="In brief" items={[{ id: "a", node: "One line." }]} total={5} onAll={() => {}} allOpen={false} />);
    expect(screen.queryByTestId("paper-left-out")).toBeNull();
  });
});

describe("PaperSources", () => {
  it("lists every numbered source and opens the one that has a door", () => {
    const open = vi.fn();
    render(<PaperSources refs={[{ n: 1, label: "Day Briefing", onOpen: open }, { n: 2, label: "Inquiry · revenue" }]} />);
    fireEvent.click(screen.getByRole("button", { name: "Day Briefing" }));   // a span with the button role
    expect(open).toHaveBeenCalled();
    expect(screen.getByTestId("paper-sources")).toHaveTextContent("2Inquiry · revenue");
  });
});

describe("rangeNumbers — every figure is the edition's own (LuxExperience's week, 2026-10-23)", () => {
  const m = (over: Partial<BriefingRangeMeasure>): BriefingRangeMeasure => ({
    name: "Average Order Value (AOV)", metric: "aov", unit: "EUR", time_kind: "flow", confirmed: false,
    current: 581.12, previous: 590.72, last_year: 454.19, rel: -0.0162, rel_last_year: 0.279, status: "final",
    current_text: "€581", previous_text: "€591", ...over });
  // Clienteling ended June 2025: the server has no figure for it this week.
  const block = {
    compared_with: "the week before, 2026-10-05 to 2026-10-11", covers: "the week 2026-10-12 to 2026-10-18",
    measured: [
      m({}),
      m({ name: "Session Conversion Rate", metric: "scr", current: 0.021, rel: null, current_text: "2.1%",
          current_partial: "2026-10-12 to 2026-10-14" }),
    ],
    unmeasured: [
      { name: "Clienteling-Influenced GMV per Interaction", metric: "gmv_int", data_ends: "2025-06-29",
        reason: "its data ends 2025-06-29, before this range" },
      { name: "Marketing ROAS", reason: "its data has no rows in this range" },
    ],
  } as unknown as BriefingRangeBlock;

  it("prints the edition's figures plain, and an ended metric as when its data ended — never another week's figure", () => {
    const rows = rangeNumbers(block);
    expect(rows[0]).toMatchObject({ label: "Average Order Value (AOV)", value: "€581", note: undefined });
    expect(rows[0].change?.sign).toBe(-1);
    expect(rows[1].note).toBe("only 2026-10-12 to 2026-10-14");          // part of the edition's own week
    expect(rows[2]).toMatchObject({ label: "Clienteling-Influenced GMV per Interaction", value: "",
                                    unknown: "data ended Jun 2025", why: "Its data ends 2025-06-29, before this range" });
    expect(rows[3]).toMatchObject({ label: "Marketing ROAS", unknown: "not measured" });
    expect(rows.map(r => r.value)).not.toContain("13,809");
  });

  it("prints an edition stored before the rule by the same rule", () => {
    // stored with Clienteling's own last week among the edition's figures
    const lastWeek = m({ name: "Clienteling-Influenced GMV per Interaction", metric: "gmv_int", current: 13809, current_text: "13,809",
      anchored: { start: "2025-06-23", end: "2025-06-30", data_ends: "2025-06-29", covers: "the week 2025-06-23 to 2025-06-29",
                  compared_with: "the week before", why: "x" } });
    const stored = { ...block, unmeasured: [block.unmeasured[1]], measured: [...block.measured, lastWeek] } as BriefingRangeBlock;
    const rows = rangeNumbers(stored);
    expect(rows.map(r => r.label)).toEqual(["Average Order Value (AOV)", "Session Conversion Rate",
      "Clienteling-Influenced GMV per Interaction", "Marketing ROAS"]);
    expect(rows[2]).toMatchObject({ value: "", unknown: "data ended Jun 2025" });
  });

  it("prints no other week's dates under any name", () => {
    render(<PaperNumbers title="The week in numbers" rows={rangeNumbers(block)} />);
    expect(screen.getAllByTestId("paper-number-note").map(n => n.textContent)).toEqual(["only 2026-10-12 to 2026-10-14"]);
    expect(screen.getByTestId("paper-numbers")).not.toHaveTextContent("2025-06");
    expect(screen.getByText("data ended Jun 2025")).toHaveAttribute("title", "Its data ends 2025-06-29, before this range");
  });
});
