// @vitest-environment jsdom
/**
 * The Briefing as a morning paper (2026-10-12). The pieces say what they hold and what they could not
 * read: a desk column that failed says so, an empty one says why, a figure never measured is hatched,
 * and the sources number on from the lead's own citations.
 */
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";

import { DeskColumns, InBrief, PaperNumbers, PaperSources, numberDesk, paperDate } from "@/components/brief/BriefPaper";
import { firstSentence } from "@/components/BriefingPanel";
import type { BriefingDesk, DeskItem } from "@/lib/api";

vi.mock("@/lib/navigate", () => ({ requestTab: vi.fn() }));

const item = (kind: string, title: string, extra: Partial<DeskItem> = {}): DeskItem =>
  ({ kind, title, text: `${title} — why`, source: { kind: "claim", ref: title, label: `Source of ${title}` }, ...extra });

const DESK: BriefingDesk = {
  connection_id: "c1", schema: null, as_of: "2026-10-12", unread: {},
  trends: { items: [item("answer", "August revenue rose 13.2%", { status: "Provisional" }), item("trend", "Sell-through has risen since 2020", { status: "Provisional" })], more: 0 },
  gaps: { items: [item("disagree", "2025 revenue has three answers", { action: { verb: "Settle it", kind: "inquiry", ref: "q1" } })], more: 2 },
  decide: { items: [], more: 0 },
};

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
