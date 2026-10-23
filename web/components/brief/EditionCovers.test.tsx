// @vitest-environment jsdom
/**
 * What each edition covers, on data that ENDED (the Olist run; design-mockups/briefing-data-ended.html).
 * Six rows, in the range control's order; the edition on screen marked; a comparison the data only
 * partly covers says "not compared" and why; an edition with no figure says why it has none.
 */
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { EditionCovers as Covers } from "@/lib/api";

const api = vi.hoisted(() => ({ readEditionCovers: vi.fn() }));
vi.mock("@/lib/api", async (importOriginal) => ({ ...(await importOriginal<typeof import("@/lib/api")>()), ...api }));

import { besideWords, EditionCovers } from "./EditionCovers";

const row = (preset: string, label: string, extra: Record<string, unknown> = {}) =>
  ({ preset, label, why: "", covers: `${label} covers`, compared_with: `${label} before`, compare_withheld: "",
     current_text: "BRL 100", previous_text: "BRL 90", rel: 0.111, ...extra });

const OLIST: Covers = {
  data_ended: true, data_through: "2018-10-17", data_from: "2016-09-04",
  metric: { name: "gmv", label: "Gross Merchandise Value" },
  editions: [
    row("yesterday", "Day", { current_text: null, previous_text: null, rel: null, why: "its data has no rows in this range",
                              start: "2018-10-17", last_day: "2018-10-17", previous_start: "2018-10-10", previous_last_day: "2018-10-10" }),
    row("last_week", "Week"),
    row("last_month", "Month", { covers: "September 2018", rel: -0.9998, start: "2018-09-01", last_day: "2018-09-30",
                                 previous_start: "2018-08-01", previous_last_day: "2018-08-31" }),
    row("last_year", "Year", { compare_withheld: "the data starts on 2016-09-04, so 2016 holds only part of its days", rel: null,
                               start: "2017-01-01", last_day: "2017-12-31", previous_start: "2016-01-01", previous_last_day: "2016-12-31" }),
    row("month_to_date", "Month to date"),
    row("year_to_date", "Year to date"),
  ] as Covers["editions"],
};

describe("EditionCovers", () => {
  it("lists the six editions with the lead metric's figure and says why one is not compared", async () => {
    api.readEditionCovers.mockResolvedValue(OLIST);
    render(<EditionCovers connectionId="workspace" schema="olist" workspaceId="w1" current="last_month" />);
    const table = await screen.findByTestId("edition-covers");
    expect(api.readEditionCovers).toHaveBeenCalledWith("workspace", "olist", "w1");
    expect(within(table).getByText(/Each figure is Gross Merchandise Value, the lead approved metric/)).toBeInTheDocument();
    for (const label of ["Day", "Week", "Month", "Year", "Month to date", "Year to date"]) {
      expect(within(table).getByText(label)).toBeInTheDocument();
    }
    expect(within(table).getByText("September 2018")).toBeInTheDocument();           // compact cells, the sentence as title
    expect(within(table).getByText("August 2018")).toBeInTheDocument();
    expect(within(table).getByText("Wed 17 Oct 2018")).toBeInTheDocument();
    expect(within(table).getByText("2017")).toBeInTheDocument();
    expect(within(table).queryByText("2016")).toBeNull();                             // withheld: no dates for it
    expect(within(table).getByText("-100.0%")).toBeInTheDocument();
    expect(within(table).getByText("not compared")).toBeInTheDocument();
    expect(within(table).getByText(/Not compared: the data starts on 2016-09-04/)).toBeInTheDocument();
    expect(within(table).getByText("Its data has no rows in this range.")).toBeInTheDocument();
  });

  it("says when nothing is approved, and when the table could not be read", async () => {
    api.readEditionCovers.mockResolvedValueOnce({ ...OLIST, metric: null });
    const { unmount } = render(<EditionCovers connectionId="workspace" />);
    expect(await screen.findByText("No metric is approved yet, so no edition has a figure.")).toBeInTheDocument();
    unmount();
    api.readEditionCovers.mockRejectedValueOnce(new Error("What each edition covers could not be read"));
    render(<EditionCovers connectionId="workspace" />);
    expect(await screen.findByText("What each edition covers could not be read")).toBeInTheDocument();
  });
});

describe("besideWords", () => {
  it("says the withheld reason first, then why a figure is missing, else nothing", () => {
    expect(besideWords(OLIST.editions[3])).toBe("Not compared: the data starts on 2016-09-04, so 2016 holds only part of its days.");
    expect(besideWords(OLIST.editions[0])).toBe("Its data has no rows in this range.");
    expect(besideWords(OLIST.editions[1])).toBe("");
  });
});
