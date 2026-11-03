// @vitest-environment jsdom
/**
 * New dashboard ▸ From a file. The model is the server's, so what is checked here is what a person is shown and what is sent back:
 * nothing is drafted without a file and words, each card's definition is the server's, and what they keep is what they ticked.
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { Theme } from "@radix-ui/themes";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  stageFile: vi.fn(), createFromFile: vi.fn(), draftSheetDashboard: vi.fn(), keepSheetDashboard: vi.fn(),
}));
vi.mock("@/lib/sheets", async importOriginal => ({ ...(await importOriginal<typeof import("@/lib/sheets")>()), ...api }));

import { FromFile } from "./FromFile";

const staged = { token: "t", file: "orders.csv", size: 1782579, tabs: [{ tab: "Sheet1", rows: 7, columns: [
  { name: "status", suggested: "choice", offered: [], filled: 7, empty: 0, integer: false, first: "Complete", values: [["Complete", 3], ["Returned", 1]], distinct: 5, misfits: {} },
  { name: "sale_price", suggested: "money", offered: [], filled: 7, empty: 0, integer: false, first: "10.00", values: [], distinct: 7, misfits: {} },
] }] };
const figure = (key: string, title: string, value: number, definition: string, reads: string[] = []) => ({
  key, title, sql: `SELECT ${key}`, definition, reads, size: "small", shown: { as: "figure", series: [{ column: key, agg: "sum" }], format: "money" },
  preview: { as: "figure", value, label: title, said: [], format: "money" },
});
const draft = {
  drafted: true, sentences: [], sheet: "s1", connection_id: "sheets", title: "Orders so far", words: "What we kept", table: "orders",
  cards: [figure("kept", "Kept", 120, "Sum of Sale price where Status is Complete"), figure("back", "Came back", 20, ""), figure("kept-if", "If returns fell", 120, "words", ["cut"])],
  filters: [{ column: "channel", label: "Channel", grain: "", values: [["Search", 4], ["Email", 3]] }],
  scenario: { inputs: [{ name: "cut", label: "Returns fall by", start: 0, min: 0, max: 1, step: 0.01, unit: "percent" }], presets: [], scenario_card: "kept-if", file_card: "kept" },
  questions: [{ says: "Kept counts Complete.", instead: { label: "Also Shipped", cards: { kept: figure("kept", "Kept", 150, "Sum of Sale price where Status is Complete or Shipped") } } }],
  not_made: [{ asked: "Margin", why: "This file has no cost column." }],
};
const keptAs = { connection_id: "sheets", dashboard_id: "d1", title: "Orders so far", version: 1, cards: 3 };

async function drafted(onKept = vi.fn()) {
  render(<Theme><FromFile onKept={onKept} /></Theme>);
  fireEvent.change(screen.getByTestId("from-file-input"), { target: { files: [new File(["a"], "orders.csv")] } });
  await screen.findByTestId("from-file-columns");
  fireEvent.change(screen.getByTestId("from-file-words"), { target: { value: "What we kept" } });
  fireEvent.click(screen.getByTestId("from-file-draft"));
  await screen.findByTestId("from-file-check");
  return onKept;
}
const row = (id: string) => document.querySelector(`[data-row="${id}"]`) as HTMLElement;

beforeEach(() => {
  api.stageFile.mockResolvedValue(staged);
  api.createFromFile.mockResolvedValue({ sheets: [{ id: "s1" }] });
  api.draftSheetDashboard.mockResolvedValue(draft);
  api.keepSheetDashboard.mockResolvedValue(keptAs);
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("From a file", () => {
  it("asks for a file and words before it spends anything, and says a draft asks a model", async () => {
    render(<Theme><FromFile onKept={vi.fn()} /></Theme>);
    expect(screen.getByTestId("from-file-draft")).toBeDisabled();
    expect(screen.getByText(/Drafting asks a model once/)).toBeInTheDocument();
    fireEvent.change(screen.getByTestId("from-file-input"), { target: { files: [new File(["a"], "orders.csv")] } });
    await screen.findByTestId("from-file-columns");
    expect(screen.getByTestId("from-file-draft")).toBeDisabled();
    expect(api.draftSheetDashboard).not.toHaveBeenCalled();
  });

  it("shows how each column reads, and makes the sheet once however many times it drafts", async () => {
    await drafted();
    expect(api.createFromFile).toHaveBeenCalledTimes(1);
    expect(api.createFromFile.mock.calls[0][1][0].kinds).toEqual({ status: "choice", sale_price: "money" });
    fireEvent.change(screen.getByLabelText("Ask for a change"), { target: { value: "Drop Channel" } });
    fireEvent.click(screen.getByTestId("from-file-change"));
    await waitFor(() => expect(api.draftSheetDashboard).toHaveBeenCalledTimes(2));
    expect(api.createFromFile).toHaveBeenCalledTimes(1);
    expect(api.draftSheetDashboard.mock.calls[1][1]).toContain("Drop Channel");
  });

  it("says what a card means in the server's words, and says so when there are none", async () => {
    await drafted();
    expect(within(row("kept")).getByTestId("from-file-definition")).toHaveTextContent("Sum of Sale price where Status is Complete");
    expect(within(row("kept")).getByTestId("from-file-preview-figure")).toHaveTextContent("$120");
    expect(within(row("back")).getByTestId("from-file-definition")).toHaveTextContent("too involved to say in words");
  });

  it("asks what the model chose, and says what could not be made", async () => {
    await drafted();
    expect(screen.getByTestId("from-file-question")).toHaveTextContent("Kept counts Complete. Is that what you mean?");
    expect(screen.getByTestId("from-file-not-made")).toHaveTextContent("Margin is not here. This file has no cost column. No card was made.");
  });

  it("takes the other reading when asked, and sends that statement", async () => {
    await drafted();
    fireEvent.click(screen.getByRole("button", { name: "Also Shipped" }));
    expect(within(row("kept")).getByTestId("from-file-preview-figure")).toHaveTextContent("$150");
    expect(within(row("kept")).getByTestId("from-file-definition")).toHaveTextContent("Complete or Shipped");
  });

  it("keeps what was ticked and nothing else, and opens it", async () => {
    const onKept = await drafted();
    fireEvent.click(within(row("back")).getByRole("checkbox"));
    fireEvent.click(within(row("filter:channel")).getByRole("checkbox"));
    fireEvent.click(screen.getByTestId("from-file-keep"));
    await waitFor(() => expect(onKept).toHaveBeenCalledWith("d1", "sheets"));
    const [sheet, body] = api.keepSheetDashboard.mock.calls[0];
    expect(sheet).toBe("s1");
    expect(body.cards.map((c: { key: string }) => c.key)).toEqual(["kept", "kept-if"]);
    expect(body.filters).toEqual([]);
    expect(body.scenario.scenario_card).toBe("kept-if");
    expect(body.add_row).toBe(true);
  });

  it("a scenario holds on to the figure it is measured against, even when that figure leaves the overview", async () => {
    await drafted();
    fireEvent.click(within(row("kept")).getByRole("checkbox"));
    fireEvent.click(screen.getByTestId("from-file-keep"));
    await waitFor(() => expect(api.keepSheetDashboard).toHaveBeenCalled());
    const kept = api.keepSheetDashboard.mock.calls[0][1].cards.find((c: { key: string }) => c.key === "kept");
    expect(kept.scenario_only).toBe(true);
  });

  it("taking the scenario off takes its cards with it", async () => {
    await drafted();
    fireEvent.click(within(row("__scenario")).getByRole("checkbox"));
    fireEvent.click(screen.getByTestId("from-file-keep"));
    await waitFor(() => expect(api.keepSheetDashboard).toHaveBeenCalled());
    const body = api.keepSheetDashboard.mock.calls[0][1];
    expect(body.scenario).toBeNull();
    expect(body.cards.map((c: { key: string }) => c.key)).toEqual(["kept", "back"]);
  });

  it("says why when no draft came back, and offers to try again", async () => {
    api.draftSheetDashboard.mockResolvedValueOnce({ ...draft, drafted: false, sentences: ["The model drafted no dashboard for this, and gave no reason."] });
    render(<Theme><FromFile onKept={vi.fn()} /></Theme>);
    fireEvent.change(screen.getByTestId("from-file-input"), { target: { files: [new File(["a"], "orders.csv")] } });
    await screen.findByTestId("from-file-columns");
    fireEvent.change(screen.getByTestId("from-file-words"), { target: { value: "Show it" } });
    fireEvent.click(screen.getByTestId("from-file-draft"));
    expect(await screen.findByTestId("from-file-said")).toHaveTextContent("gave no reason");
    expect(screen.getByTestId("from-file-draft")).toBeEnabled();
  });
});
