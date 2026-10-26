// @vitest-environment jsdom
/**
 * The Briefing's figures past its front (2026-10-26): "Every figure, by area" under the desk — area cards, stopped
 * figures one line per day, a blank figure with its reason — the front box's footer, and the reader's choice, which
 * offers no seventh place on a full front.
 */
import { fireEvent, render, screen, within } from "@/lib/testing";
import { describe, expect, it, vi } from "vitest";

import type { PaperNumber } from "@/components/brief/BriefPaper";
import { arrange } from "@/lib/briefingFigures";

import { ChooseFigures, EveryFigure, FrontFooter } from "./BriefFigures";

const fig = (metric: string, area: string, extra: Partial<PaperNumber> = {}): PaperNumber =>
  ({ key: metric, metric, label: metric.replace(/_/g, " "), value: "1", area, change: { text: "+1%", sign: 1 }, ...extra });
const ROWS: PaperNumber[] = [
  ...["gmv", "net_revenue", "aov", "gross_margin", "item_return_rate", "session_conversion"].map(m => fig(m, "Orders & sales")),
  fig("contribution_margin", "Margin & pricing", { moved: true }), fig("delivery_days", "Fulfilment"),
  { key: "unmeasured:consent", metric: "consent", label: "Marketing consent rate", value: "", unknown: "data ended", ended: true,
    ends: "2025-05-19", why: "its data ends 2025-05-19" },
  { key: "unmeasured:roas", metric: "roas", label: "Marketing ROAS", value: "", unknown: "not measured",
    why: "its date is a fiscal year, so no week of it exists." },
];

describe("EveryFigure", () => {
  it("lays the rest out by area under the desk, stopped figures by day, a blank with its reason", () => {
    render(<EveryFigure arranged={arrange(ROWS, { front: [], hidden: [] })} connectionId="dcc63d83" comparedWith="the week before" onChoose={() => {}} />);
    const cards = screen.getAllByTestId("paper-area-card");
    expect(cards.map(c => c.textContent?.split(/\d/)[0])).toEqual(["Margin & pricing", "Fulfilment"]);
    expect(cards[0]).toHaveTextContent("1 · 1 moved 10%+");
    expect(screen.getByTestId("paper-every-stopped")).toHaveTextContent("1 stopped");
    expect(screen.getByTestId("paper-every-stopped")).toHaveTextContent("Marketing consent rate");
    expect(screen.getByTestId("paper-every-blanks")).toHaveTextContent("Marketing ROAS — its date is a fiscal year");
    expect(within(screen.getByTestId("paper-every-blanks")).getByText("Fix its definition")).toBeInTheDocument();
  });

  it("says only how many are hidden when nothing else is left below", () => {
    render(<EveryFigure arranged={arrange(ROWS.slice(0, 7), { front: [], hidden: ["contribution_margin"] })} onChoose={() => {}} />);
    expect(screen.getByTestId("paper-every-figure")).toHaveTextContent("1 figure hidden by you");
  });
});

describe("FrontFooter", () => {
  it("counts what reads below and opens the choice", () => {
    const onChoose = vi.fn();
    render(<FrontFooter arranged={arrange(ROWS, { front: [], hidden: ["delivery_days"] })} onChoose={onChoose} />);
    expect(screen.getByTestId("paper-front-footer")).toHaveTextContent("2 more below, by area · 1 stopped · 1 hidden by you");
    fireEvent.click(screen.getByText("Choose figures"));
    expect(onChoose).toHaveBeenCalledOnce();
  });
});

describe("ChooseFigures", () => {
  it("offers Front only while the front has room, and says a full one is full", () => {
    render(<ChooseFigures rows={ROWS} choice={{ front: [], hidden: [] }} onChange={() => {}} onClose={() => {}} />);
    expect(screen.getByTestId("paper-choose")).toHaveTextContent("6 of 6 on the front");
    const rows = screen.getAllByTestId("paper-choose-row");
    // Radix prints each label twice (one copy sizes the segment): read each radio's own word once
    const offered = (row: HTMLElement) => within(row).getAllByRole("radio").map(r => (r.textContent ?? "").slice(0, (r.textContent ?? "").length / 2));
    expect(offered(rows[0])).toEqual(["Front", "Below", "Hidden"]);
    const below = rows.find(r => r.textContent?.startsWith("contribution margin"))!;
    expect(offered(below)).toEqual(["Below", "Hidden"]);
    expect(screen.getByText("The front is full — move one below to put another there.")).toBeInTheDocument();
  });

  it("goes back to the default in one step once a choice was made", () => {
    const onChange = vi.fn();
    const { rerender } = render(<ChooseFigures rows={ROWS} choice={{ front: [], hidden: [] }} onChange={onChange} onClose={() => {}} />);
    expect(screen.queryByTestId("paper-choose-default")).toBeNull();
    rerender(<ChooseFigures rows={ROWS} choice={{ front: [], hidden: ["gmv"] }} onChange={onChange} onClose={() => {}} />);
    fireEvent.click(screen.getByTestId("paper-choose-default"));
    expect(onChange).toHaveBeenCalledWith({ front: [], hidden: [] }, "Back to the default: the first six on the front, nothing hidden.");
  });
});
