// @vitest-environment jsdom

/**
 * The process designer (2026-10-09, approved as drawn after the usability walk-through). A person names a process in
 * words, picks what moves through it and when each stage is reached from what the data carries, and sees it counted as
 * declaring would count it — with the checks to read before publishing, the stuck stage asked about as a question, and
 * what the process creates. Declaring, publishing the release and starting a cockpit for it follow from the same page.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";

import { choose, render, screen, waitFor, within } from "@/lib/testing";
import type { ProcessCandidates, ProcessPreview, TypeMapRow } from "@/lib/objectTypes";

const calls = vi.hoisted(() => ({
  candidates: vi.fn(), preview: vi.fn(), declare: vi.fn(), release: vi.fn(), publish: vi.fn(),
  keep: vi.fn(), tab: vi.fn(), list: vi.fn(),
}));

vi.mock("@/lib/objectTypes", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/objectTypes")>()),
  getProcessCandidates: calls.candidates, previewProcess: calls.preview, declareProcess: calls.declare,
  getRelease: calls.release, publishRelease: calls.publish,
}));
vi.mock("@/lib/api", async (importOriginal) => ({ ...(await importOriginal<typeof import("@/lib/api")>()), keepCockpit: calls.keep }));
vi.mock("@/lib/navigate", () => ({ requestTab: calls.tab }));
vi.mock("@/lib/objects", async (importOriginal) => ({ ...(await importOriginal<typeof import("@/lib/objects")>()), listObjects: calls.list }));

import { ProcessDesigner } from "@/components/ontology/ProcessDesigner";

// The designer reads a type's id, its name and its row count — nothing else of the row.
const TYPES = [{ id: "Order", display_name: "Order", rows: 5000 },
               { id: "Customer", display_name: "Customer", rows: 900 }] as unknown as TypeMapRow[];

const moment = (path: string, set: number) =>
  ({ path, property: path, label: path, via: "", on: "Order", on_label: "Order", set, earliest: "2023-01-01", latest: "2024-12-30" });
const CANDIDATES: ProcessCandidates = {
  entity: "Order", label: "Order", api_name: "order", objects: 5000, table: "orders", key: "order_id",
  moments: [moment("order_date", 5000), moment("shipped_at", 4600), moment("delivered_at", 2500)],
  states: [{ property: "status", label: "status", values: [{ value: "delivered", objects: 2500 }, { value: "shipped", objects: 800 },
    { value: "cancelled", objects: 600 }, { value: "refunded", objects: 500 }] }],
  unread: [],
};
const stage = (name: string, reached: number, extra = {}) => ({ name, display_name: name, timestamp: "", state: [], property: "",
  reached, verified: true, note: "", skipped: 0, out_of_order: 0, p50_days: null, promise: null, ...extra });
const STUCK = {
  id: "stuck:delivered", level: "ask" as const, stage: "delivered",
  says: "1,100 orders reached Shipped and never Delivered, 576 of them more than a year ago. With a 5-day promise, 1,100 would be called late today.",
  numbers: { open: 1100, stale: 576, overdue: 1100 },
  show: { entity: "order", columns: ["shipped_at", "status"], filters: [{ path: "shipped_at", op: "not_null" }] },
  exit: { property: "status", label: "status", values: ["cancelled", "refunded"], explains: 576, of: 576, holding: 1100, recent: 524 },
};
const PREVIEW: ProcessPreview = {
  process: { id: "order_delivery", entity: "Order", objects: 5000, stages: [
    stage("placed", 5000), stage("shipped", 4600, { p50_days: 1 }),
    stage("delivered", 2500, { p50_days: 3, promise: { name: "delivery", within_days: 5, within_hours: null, deadline: "",
      reached: 2500, breached: 1428, open: 1100, open_overdue: 1100, breach_rate: 0.5712, as_of: "2024-12-30", flags: [] } })] },
  checks: [STUCK, { id: "order", level: "ok", says: "Every stage's moment follows the one before it." }],
  creates: [{ kind: "segment", name: "overdue_delivery", noun: "delivery", value: 1100, says: "open and past the delivery promise" },
            { kind: "metric", name: "delivery_breach_rate", noun: "delivery", value: 0.5712, says: "share past the promise" },
            { kind: "property", name: "delivery_lag_days", noun: "delivery", value: 3, says: "days, median" }],
};

function designer() {
  const onDeclared = vi.fn();
  const { rerender } = render(<ProcessDesigner connectionId="c1" schema="s" types={TYPES} takenIds={["order_fulfilment"]}
    onClose={() => {}} onDeclared={onDeclared} />);
  return { onDeclared, rerender };
}

/** Name it, choose Order, two stages by hand and the third from a suggestion, with a 5-day promise named delivery. */
async function designDelivery(user: ReturnType<typeof userEvent.setup>) {
  const status = screen.getByTestId("designer-status");
  expect(status.textContent).toBe("Name the process.");                       // never a silent disabled button
  await user.type(screen.getByLabelText("Process name"), "Order delivery");
  await choose(screen.getByLabelText("What moves through the process"), "Order");
  await waitFor(() => expect(calls.candidates).toHaveBeenCalledWith("c1", "Order", "s"));
  expect(screen.getByTestId("designer-status").textContent).toBe("Name stage 1.");
  await user.type(screen.getByLabelText("Stage 1 name"), "Placed");
  await choose(screen.getByLabelText("When an object reaches stage 1"), "m:order_date");
  await user.type(screen.getByLabelText("Stage 2 name"), "Shipped");
  await choose(screen.getByLabelText("When an object reaches stage 2"), "m:shipped_at");
  await user.click(within(screen.getByTestId("designer-suggestions")).getByRole("button", { name: /delivered_at · 2,500/ }));
  await choose(screen.getByLabelText("Promise on stage 3"), "days");
  await user.type(screen.getByLabelText("Promise on stage 3, days"), "5");
  await user.type(screen.getByLabelText("Promise on stage 3, name"), "delivery");
}

const lastSpec = () => calls.preview.mock.calls.at(-1)?.[1];

describe("the process designer", () => {
  beforeEach(() => {
    Object.values(calls).forEach(f => f.mockReset());
    calls.candidates.mockResolvedValue(CANDIDATES);
    calls.preview.mockResolvedValue(PREVIEW);
    try { localStorage.clear(); } catch { /* jsdom keeps one */ }
  });
  afterEach(() => { try { localStorage.clear(); } catch { /* nothing kept */ } });

  it("counts a draft written in words as declaring would, and shows each stage's count and the checks", async () => {
    const user = userEvent.setup();
    designer();
    await designDelivery(user);
    await waitFor(() => expect(lastSpec()?.stages?.[2]?.promise).toEqual({ name: "delivery", within_days: 5 }), { timeout: 4000 });
    expect(lastSpec()).toEqual({ id: "order_delivery", display_name: "Order delivery", entity: "Order", stages: [
      { name: "placed", display_name: "Placed", timestamp: "order_date" },
      { name: "shipped", display_name: "Shipped", timestamp: "shipped_at" },
      { name: "delivered", display_name: "delivered", timestamp: "delivered_at", promise: { name: "delivery", within_days: 5 } }] });
    expect(calls.preview.mock.calls.at(-1)?.[0]).toBe("c1");
    await waitFor(() => expect(screen.getAllByTestId("designer-reached").map(n => n.textContent)).toEqual(["5,000", "4,600", "2,500"]));
    expect(screen.getByTestId("designer-breach").textContent).toBe("57.1% of those that reached it late");
    // a count stands only beside the draft it counted: a stage renamed reads "—" until it is counted again
    await user.type(screen.getByLabelText("Stage 1 name"), " date");
    expect(screen.getAllByTestId("designer-reached").map(n => n.textContent)).toEqual(["—", "—", "—"]);
    await waitFor(() => expect(screen.getAllByTestId("designer-reached")[0].textContent).toBe("5,000"), { timeout: 4000 });
    const ask = screen.getAllByTestId("designer-check").find(n => n.getAttribute("data-level") === "ask")!;
    expect(ask.textContent).toContain("576 of them more than a year ago");
    expect(ask.textContent).toContain("status is cancelled or refunded for 576 of the 576");
    expect(screen.getAllByTestId("designer-create").map(n => n.textContent)).toEqual([
      expect.stringContaining("Late delivery1,100"), expect.stringContaining("Delivery promise broken57.1%"),
      expect.stringContaining("Delivery duration3 d")]);
  });

  it("answers the stuck stage: they left — the exit is declared from the states that explain them — or they are late", async () => {
    const user = userEvent.setup();
    designer();
    await designDelivery(user);
    await screen.findByRole("button", { name: "They left the process" }, { timeout: 4000 });
    await user.click(screen.getByRole("button", { name: "They left the process" }));
    expect(screen.getByTestId("designer-exits").textContent).toContain("status is cancelled or refunded");
    await waitFor(() => expect(lastSpec()?.leaves).toEqual({ property: "status", values: ["cancelled", "refunded"] }), { timeout: 4000 });

    await user.click(screen.getByRole("button", { name: "Review and publish" }));
    expect(await screen.findByRole("button", { name: "Declare it anyway" })).toBeInTheDocument();   // an answer still open
    await user.click(await screen.findByRole("button", { name: "They really are late" }));
    expect(screen.getByRole("button", { name: "Declare the process" })).toBeInTheDocument();
    expect(screen.getByText(/You said these are really late/)).toBeInTheDocument();
  });

  it("lists twenty of the objects a check is about, through the object door", async () => {
    const user = userEvent.setup();
    calls.list.mockResolvedValue({ path: "listed", names: ["order_id", "shipped_at", "status"], rows: [["O1", "2023-02-01", "cancelled"]],
      total: 576, error: null });
    designer();
    await designDelivery(user);
    await user.click(await screen.findByRole("button", { name: "Show me 20 of them" }, { timeout: 4000 }));
    await waitFor(() => expect(calls.list).toHaveBeenCalledWith(
      { entity: "order", filters: STUCK.show.filters, columns: STUCK.show.columns, limit: 20 }, "c1", "s"));
    expect((await screen.findByTestId("designer-sample")).textContent).toContain("576 in all");
  });

  it("declares, publishes the release, and starts a cockpit holding the board, the late list and one object", async () => {
    const user = userEvent.setup();
    const { onDeclared, rerender } = designer();
    calls.declare.mockResolvedValue({ id: "order_delivery" });
    calls.release.mockResolvedValue({ published: { number: 4 }, draft: [{}, {}] });
    calls.publish.mockResolvedValue({ number: 5, id: "c1/s@5", restated_claims: [] });
    calls.keep.mockResolvedValue({ version: 1 });
    await designDelivery(user);
    await screen.findByRole("button", { name: "They really are late" }, { timeout: 4000 });
    expect(screen.getByTestId("designer-cockpit")).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "They really are late" }));
    await user.click(screen.getByRole("button", { name: "Review and publish" }));
    expect(screen.getByTestId("designer-review-panel").textContent).toContain("Declaring Order delivery counts it once more");
    await user.click(screen.getByRole("button", { name: "Declare the process" }));
    await waitFor(() => expect(calls.declare).toHaveBeenCalledWith("c1", lastSpec(), "s"));
    expect(onDeclared).toHaveBeenCalledWith("order_delivery");
    // the map re-reads and the declared id is taken now: what was counted and declared still stands beside it
    rerender(<ProcessDesigner connectionId="c1" schema="s" types={TYPES} takenIds={["order_fulfilment", "order_delivery"]}
      onClose={() => {}} onDeclared={onDeclared} />);
    expect(screen.getAllByTestId("designer-reached").map(n => n.textContent)).toEqual(["5,000", "4,600", "2,500"]);
    expect((await screen.findByTestId("designer-release")).textContent).toContain("release 5, which holds 2 changes waiting");
    await user.click(screen.getByRole("button", { name: "Publish release 5" }));
    await waitFor(() => expect(screen.getByTestId("designer-state").textContent).toBe("Published in release 5"));
    await user.click(screen.getByTestId("designer-cockpit"));
    await waitFor(() => expect(calls.keep).toHaveBeenCalled());
    const [conn, id, spec] = calls.keep.mock.calls[0];
    // the server's own id law (`cockpit.home._ID`) and a suffix of its own — never one of the person's cockpits
    expect(conn).toBe("c1");
    expect(id).toMatch(/^order-delivery-[0-9a-f]{6}$/);
    expect(id).toMatch(/^[a-z0-9][a-z0-9-]{0,47}$/);
    const els = (spec as { elements: Record<string, { type: string; props: Record<string, unknown> }> }).elements;
    const of = (type: string) => Object.entries(els).find(([, e]) => e.type === type);
    expect(of("ProcessBoard")?.[1].props.process).toBe("order_delivery");
    expect(of("ObjectTable")?.[1].props).toMatchObject({ entity: "Order", segment: "overdue_delivery" });
    expect(of("ObjectDetail")?.[1].props.follows).toBe(of("ObjectTable")?.[0]);
    expect(calls.tab).toHaveBeenCalledWith("cockpit", { conn: "c1" });
  });

  it("keeps a draft in this browser and brings it back", async () => {
    const user = userEvent.setup();
    const first = render(<ProcessDesigner connectionId="c1" schema="s" types={TYPES} takenIds={[]} onClose={() => {}} onDeclared={() => {}} />);
    await user.type(screen.getByLabelText("Process name"), "Returns handling");
    await user.click(screen.getByRole("button", { name: "Save draft" }));
    first.unmount();
    render(<ProcessDesigner connectionId="c1" schema="s" types={TYPES} takenIds={[]} onClose={() => {}} onDeclared={() => {}} />);
    expect(screen.getByLabelText("Process name")).toHaveValue("Returns handling");
    expect(screen.getByText(/Your draft, as this browser kept it/)).toBeInTheDocument();
  });
});
