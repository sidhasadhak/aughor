// @vitest-environment jsdom
/**
 * New dashboard ▸ From a file. The model is the server's, so what is checked here is what a person is shown and what is sent back:
 * nothing is drafted without a file and words, each card's definition is the server's, and what they keep is what they ticked.
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { Theme } from "@radix-ui/themes";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  stageFile: vi.fn(), createFromFile: vi.fn(), draftSheetDashboard: vi.fn(), keepSheetDashboard: vi.fn(), exploreSheetDashboard: vi.fn(), checkDraftedCard: vi.fn(),
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

  // ── a model explores the file ──────────────────────────────────────────────
  const looked = { why: "Which statuses exist", sql: "SELECT status, COUNT(*) FROM orders GROUP BY 1", rows: 5, more: false, refused: "" };
  const explored = { type: "explored", words: "What we sold and what came back, by month.", noticed: ["Cancelled orders still carry a price."], looks: [looked] };
  const hears = (...frames: unknown[]) => api.exploreSheetDashboard.mockImplementation(async (_id: string, _body: unknown, hear: (f: unknown) => void) => { for (const f of frames) hear(f); });
  async function ready() {
    render(<Theme><FromFile onKept={vi.fn()} /></Theme>);
    fireEvent.change(screen.getByTestId("from-file-input"), { target: { files: [new File(["a"], "orders.csv")] } });
    await screen.findByTestId("from-file-columns");
  }

  it("says what exploring reads, and spends nothing until someone asks", async () => {
    render(<Theme><FromFile onKept={vi.fn()} /></Theme>);
    expect(screen.getByTestId("from-file-write")).toBeDisabled();
    expect(screen.getByTestId("from-file-draw")).toBeDisabled();
    fireEvent.change(screen.getByTestId("from-file-input"), { target: { files: [new File(["a"], "orders.csv")] } });
    await screen.findByTestId("from-file-columns");
    expect(screen.getByTestId("from-file-write")).toBeEnabled();
    expect(screen.getByTestId("from-file-explore")).toHaveTextContent("up to 16 queries");
    expect(screen.getByTestId("from-file-explore")).toHaveTextContent("up to 30 rows");
    expect(api.exploreSheetDashboard).not.toHaveBeenCalled();
    expect(api.createFromFile).not.toHaveBeenCalled();
  });

  it("writes the words in the box for the person to change, and drafts what they left there", async () => {
    await ready();
    hears({ type: "look", ...looked }, explored, { type: "end" });
    fireEvent.click(screen.getByTestId("from-file-write"));
    await waitFor(() => expect(screen.getByTestId("from-file-words")).toHaveValue("What we sold and what came back, by month."));
    expect(api.exploreSheetDashboard.mock.calls[0][1]).toEqual({ focus: "", draw: false });
    expect(screen.getByTestId("from-file-wrote")).toHaveTextContent("Written by a model after 1 query");
    expect(screen.getByTestId("from-file-noticed")).toHaveTextContent("Cancelled orders still carry a price.");
    expect(screen.getByText(/a few of their values, and what was noticed below, and nothing else/)).toBeInTheDocument();
    expect(api.draftSheetDashboard).not.toHaveBeenCalled();

    fireEvent.change(screen.getByTestId("from-file-words"), { target: { value: "Only what came back, by month." } });
    expect(screen.getByTestId("from-file-wrote")).toHaveTextContent("changed by you");
    fireEvent.click(screen.getByTestId("from-file-draft"));
    await screen.findByTestId("from-file-check");
    expect(api.draftSheetDashboard).toHaveBeenCalledWith("s1", "Only what came back, by month.", ["Cancelled orders still carry a price."]);
    expect(screen.getByText(/Drafted from your words/)).toBeInTheDocument();
    expect(api.createFromFile).toHaveBeenCalledTimes(1);
  });

  it("starts from what the person typed, and can put it back", async () => {
    await ready();
    fireEvent.change(screen.getByTestId("from-file-words"), { target: { value: "Late deliveries" } });
    expect(screen.getByTestId("from-file-explore")).toHaveTextContent("It starts from what is in the box.");
    hears(explored, { type: "end" });
    fireEvent.click(screen.getByTestId("from-file-write"));
    await waitFor(() => expect(screen.getByTestId("from-file-words")).toHaveValue(explored.words));
    expect(api.exploreSheetDashboard.mock.calls[0][1].focus).toBe("Late deliveries");
    fireEvent.click(screen.getByTestId("from-file-put-back"));
    expect(screen.getByTestId("from-file-words")).toHaveValue("Late deliveries");
    expect(screen.queryByTestId("from-file-noticed")).not.toBeInTheDocument();
  });

  it("explores and draws it right away, and says the draft came from what a model found", async () => {
    await ready();
    hears({ type: "look", ...looked }, explored, { type: "drafting" }, { type: "drafted", draft: { ...draft, words: explored.words } }, { type: "end" });
    fireEvent.click(screen.getByTestId("from-file-draw"));
    await screen.findByTestId("from-file-check");
    expect(api.exploreSheetDashboard.mock.calls[0][1]).toEqual({ focus: "", draw: true });
    expect(screen.getByText(/Drafted from what a model found/)).toBeInTheDocument();
    expect(screen.getByText(explored.words)).toBeInTheDocument();
    expect(screen.getByTestId("from-file-noticed")).toHaveTextContent("Cancelled orders");
    fireEvent.click(screen.getByRole("button", { name: "Back to the words" }));
    expect(screen.getByTestId("from-file-words")).toHaveValue(explored.words);
  });

  it("shows each query as it happens, and locks the box while it works", async () => {
    await ready();
    let hear: (f: unknown) => void = () => {};
    let finish: () => void = () => {};
    api.exploreSheetDashboard.mockImplementation((_id: string, _body: unknown, h: (f: unknown) => void) => { hear = h; return new Promise<void>(r => { finish = r; }); });
    fireEvent.click(screen.getByTestId("from-file-write"));
    await screen.findByTestId("from-file-exploring");
    expect(screen.getByTestId("from-file-words")).toBeDisabled();
    expect(screen.getByTestId("from-file-draft")).toBeDisabled();
    expect(screen.getByTestId("from-file-exploring")).toHaveTextContent("0 queries so far");
    await waitFor(() => expect(api.exploreSheetDashboard).toHaveBeenCalled());
    hear({ type: "look", ...looked });
    await screen.findByText("Which statuses exist");
    expect(screen.getByTestId("from-file-exploring")).toHaveTextContent("1 query so far");
    fireEvent.click(within(screen.getByTestId("from-file-look")).getByRole("button", { name: "Query" }));
    expect(screen.getByText(looked.sql)).toBeInTheDocument();
    hear({ type: "failed", sentences: ["The model is away."] });
    finish();
    await screen.findByText("The model is away.");
    expect(screen.queryByTestId("from-file-exploring")).not.toBeInTheDocument();
    expect(screen.getByTestId("from-file-words")).toBeEnabled();
  });

  it("stops when asked, says how far it got, and stops when the person leaves", async () => {
    await ready();
    let signal: AbortSignal | undefined;
    api.exploreSheetDashboard.mockImplementation((_id: string, _body: unknown, hear: (f: unknown) => void, s: AbortSignal) => {
      signal = s;
      hear({ type: "look", ...looked });
      return new Promise<void>((_, reject) => s.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError"))));
    });
    fireEvent.click(screen.getByTestId("from-file-write"));
    fireEvent.click(await screen.findByTestId("from-file-stop"));
    await screen.findByText("Stopped after 1 query. Nothing was written.");
    expect(signal?.aborted).toBe(true);
    expect(screen.getByTestId("from-file-words")).toHaveValue("");

    fireEvent.click(screen.getByTestId("from-file-write"));
    await screen.findByTestId("from-file-stop");
    const running = signal;
    cleanup();
    expect(running?.aborted).toBe(true);
  });

  it("says so when a stream is cut short", async () => {
    await ready();
    api.exploreSheetDashboard.mockRejectedValue(new Error("The exploring stopped before it finished."));
    fireEvent.click(screen.getByTestId("from-file-draw"));
    await screen.findByText("The exploring stopped before it finished.");
  });

  it("forgets what a model wrote when the file changes, but not what a person wrote", async () => {
    await ready();
    hears(explored, { type: "end" });
    fireEvent.click(screen.getByTestId("from-file-write"));
    await waitFor(() => expect(screen.getByTestId("from-file-words")).toHaveValue(explored.words));
    fireEvent.change(screen.getByTestId("from-file-input"), { target: { files: [new File(["b"], "other.csv")] } });
    await waitFor(() => expect(screen.getByTestId("from-file-words")).toHaveValue(""));
    expect(screen.queryByTestId("from-file-noticed")).not.toBeInTheDocument();
    fireEvent.change(screen.getByTestId("from-file-words"), { target: { value: "Mine" } });
    fireEvent.change(screen.getByTestId("from-file-input"), { target: { files: [new File(["c"], "third.csv")] } });
    await waitFor(() => expect(api.stageFile).toHaveBeenCalledTimes(3));
    expect(screen.getByTestId("from-file-words")).toHaveValue("Mine");
  });

  it("opens the box wide enough to read what a model wrote", async () => {
    await ready();
    const box = screen.getByTestId("from-file-words");
    expect(box).toHaveAttribute("rows", "6");
    hears({ ...explored, words: "x".repeat(460) }, { type: "end" });
    fireEvent.click(screen.getByTestId("from-file-write"));
    await waitFor(() => expect(Number(screen.getByTestId("from-file-words").getAttribute("rows"))).toBeGreaterThan(7));
  });

  it("says how many cards and how many filters it keeps, each by its own name", async () => {
    await drafted();
    const keep = screen.getByTestId("from-file-keep");
    expect(keep).toHaveTextContent("Keep 3 cards and 1 filter");
    fireEvent.click(within(row("filter:channel")).getByRole("checkbox"));
    expect(keep).toHaveTextContent("Keep 3 cards");
    expect(keep).not.toHaveTextContent("filter");
  });

  // ── a person changes a card ────────────────────────────────────────────────
  const openEditor = (id: string) => fireEvent.click(within(row(id)).getByTestId("from-file-edit"));

  it("runs a changed card with no model, and shows what it now says", async () => {
    await drafted();
    const asked = api.draftSheetDashboard.mock.calls.length;
    api.checkDraftedCard.mockResolvedValue({ sentences: [], card: figure("kept", "Kept or shipped", 150, "Sum of Sale price where Status is Complete or Shipped") });
    openEditor("kept");
    expect(screen.getByTestId("from-file-card-query")).toHaveValue("SELECT kept");
    fireEvent.change(screen.getByTestId("from-file-card-title"), { target: { value: "Kept or shipped" } });
    fireEvent.change(screen.getByTestId("from-file-card-query"), { target: { value: "SELECT 150 AS kept" } });
    fireEvent.click(screen.getByTestId("from-file-card-run"));
    await waitFor(() => expect(within(row("kept")).getByText("Kept or shipped")).toBeInTheDocument());
    const sent = api.checkDraftedCard.mock.calls[0][1];
    expect(sent.card).toMatchObject({ key: "kept", title: "Kept or shipped", sql: "SELECT 150 AS kept" });
    expect(within(row("kept")).getByTestId("from-file-definition")).toHaveTextContent("Complete or Shipped");
    expect(within(row("kept")).getByTestId("from-file-changed")).toHaveTextContent("Changed by you");
    expect(screen.queryByTestId("from-file-card-editor")).not.toBeInTheDocument();
    expect(api.draftSheetDashboard.mock.calls.length).toBe(asked);
  });

  it("says why a change was refused and keeps what was typed", async () => {
    await drafted();
    api.checkDraftedCard.mockResolvedValue({ sentences: ["Kept reads elsewhere. A card reads orders and nothing else."], card: null });
    openEditor("kept");
    fireEvent.change(screen.getByTestId("from-file-card-query"), { target: { value: "SELECT 1 FROM elsewhere" } });
    fireEvent.click(screen.getByTestId("from-file-card-run"));
    expect((await screen.findByTestId("from-file-card-said")).textContent).toContain("nothing else");
    expect(screen.getByTestId("from-file-card-query")).toHaveValue("SELECT 1 FROM elsewhere");
    expect(within(row("kept")).getByTestId("from-file-definition")).toHaveTextContent("Status is Complete");
    expect(within(row("kept")).queryByTestId("from-file-changed")).not.toBeInTheDocument();
  });

  it("cancels without running, and keeps what a card was", async () => {
    await drafted();
    openEditor("kept");
    fireEvent.change(screen.getByTestId("from-file-card-query"), { target: { value: "SELECT 2" } });
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(api.checkDraftedCard).not.toHaveBeenCalled();
    openEditor("kept");
    expect(screen.getByTestId("from-file-card-query")).toHaveValue("SELECT kept");
  });

  it("sends a scenario's other card, so a change that breaks it is said at once", async () => {
    await drafted();
    api.checkDraftedCard.mockResolvedValue({ sentences: ["At its starting values the scenario must equal the file."], card: null });
    openEditor("kept");
    fireEvent.click(screen.getByTestId("from-file-card-run"));
    await screen.findByTestId("from-file-card-said");
    const sent = api.checkDraftedCard.mock.calls[0][1];
    expect(sent.twin.key).toBe("kept-if");
    expect(sent.scenario.file_card).toBe("kept");
  });

  it("keeps a changed card as changed, and a 'Yes' to a question does not undo it", async () => {
    const onKept = await drafted();
    api.checkDraftedCard.mockResolvedValue({ sentences: [], card: figure("kept", "Kept by us", 120, "Sum of Sale price") });
    openEditor("kept");
    fireEvent.click(screen.getByTestId("from-file-card-run"));
    await waitFor(() => expect(within(row("kept")).getByText("Kept by us")).toBeInTheDocument());
    fireEvent.click(within(screen.getByTestId("from-file-question")).getByRole("button", { name: "Yes" }));
    expect(within(row("kept")).getByText("Kept by us")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("from-file-keep"));
    await waitFor(() => expect(onKept).toHaveBeenCalled());
    const cards = api.keepSheetDashboard.mock.calls[0][1].cards;
    expect(cards.find((c: { key: string }) => c.key === "kept")).toMatchObject({ title: "Kept by us", edited: true });
    expect(cards.find((c: { key: string }) => c.key === "back").edited).toBeUndefined();
  });

  it("warns that asking a model for a change redraws what the person changed", async () => {
    await drafted();
    expect(screen.getByText("Asks a model once more.")).toBeInTheDocument();
    api.checkDraftedCard.mockResolvedValue({ sentences: [], card: figure("kept", "Kept by us", 120, "Sum of Sale price") });
    openEditor("kept");
    fireEvent.click(screen.getByTestId("from-file-card-run"));
    await screen.findByText(/so what you changed goes/);
  });

  it("carries a first change into the second, and says when a change could not be made", async () => {
    await drafted();
    api.draftSheetDashboard.mockResolvedValueOnce({ ...draft, words: "What we kept Then this change: Drop Channel" });
    fireEvent.change(screen.getByLabelText("Ask for a change"), { target: { value: "Drop Channel" } });
    fireEvent.click(screen.getByTestId("from-file-change"));
    await screen.findByText("What we kept Then this change: Drop Channel");
    api.draftSheetDashboard.mockResolvedValueOnce({ ...draft, drafted: false, sentences: ["That is more than 1,200 characters."] });
    fireEvent.change(screen.getByLabelText("Ask for a change"), { target: { value: "Add Margin" } });
    fireEvent.click(screen.getByTestId("from-file-change"));
    await waitFor(() => expect(api.draftSheetDashboard.mock.calls.at(-1)?.[1]).toBe("What we kept Then this change: Drop Channel Then this change: Add Margin"));
    expect((await screen.findByTestId("from-file-said")).textContent).toContain("1,200");
  });
});
