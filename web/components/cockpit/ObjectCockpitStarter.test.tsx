// @vitest-environment jsdom

/**
 * The starter's shapes (Arc AP-5; design-mockups/cockpit-builder.html screen 7): what an object fits is offered as one to
 * three shapes, the best first and chosen, with one sentence of why and what the shape holds; Make it keeps the shape's
 * cockpit as the person's first version, saying which shape it started from. An overview is today's checklist; with
 * shapes off the starter is the one before. Every read is mocked.
 */
import { fireEvent, render, screen, waitFor, within } from "@/lib/testing";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ObjectCockpitStarter } from "@/components/cockpit/ObjectCockpitStarter";
import type { CockpitFromObject } from "@/lib/api";

const api = vi.hoisted(() => ({ getCockpitFromObject: vi.fn() }));
vi.mock("@/lib/api", async (original) => ({ ...(await original<typeof import("@/lib/api")>()), ...api }));
const start = vi.hoisted(() => ({ startCockpit: vi.fn(async () => "kept-1") }));
vi.mock("@/lib/cockpit/start", async (original) => ({ ...(await original<typeof import("@/lib/cockpit/start")>()), ...start }));

const ORDER: CockpitFromObject = {
  connection_id: "thelook", schema_name: "thelook", entity: "order", type_id: "Order", name: "Customer Order", title: "Customer Orders",
  total: 125080, filters: [{ path: "status", label: "Status", via: "", values: [["Shipped", 37838]] }],
  figures: [{ label: "Customer Orders", agg: "count", path: "", format: "number", value: 125080 }],
  chart: null, table: { columns: ["status", "created_at"], labels: ["Status", "Created at"] },
  actions: [{ id: "flag_for_review", label: "Flag for review" }], caveats: [],
  shapes: [
    { shape: "queue", short: "a dispatch promise · 1 action", why: "Customer Order has a dispatch promise of 2 days; 1,275 customer orders placed in the last 14 days are past it, and 1 action is declared on it." },
    { shape: "overview", short: "customer orders: figures and what they break into", why: "Figures over customer orders, how they move and what they break into." },
    { shape: "timeline", short: "created at → shipped at", why: "Each customer order holds two moments, created at and shipped at." },
  ],
  signals: {
    entity: "order", type_id: "Order", name: "Customer Order", label: "", window: 14, measured: { waiting: 1275 },
    queue: { kind: "promise", process: "order_fulfilment", noun: "dispatch", placed: "created_at", reached: "shipped_at", stage: "shipped",
      overdue: "overdue_dispatch", late: "late_dispatch", promise: "2 days" },
    actions: [{ id: "flag_for_review", label: "Flag for review", params: [{ name: "order", source: "chosen" }] }],
    places: null, moments: { start: "created_at", end: "shipped_at" }, one: null, lines: null,
  },
};

beforeEach(() => {
  vi.clearAllMocks();
  api.getCockpitFromObject.mockResolvedValue(ORDER);
});

const draw = () => {
  const onKept = vi.fn();
  render(<ObjectCockpitStarter connectionId="thelook" entity="order" onKept={onKept} onCancel={vi.fn()} />);
  return onKept;
};
const cards = () => screen.getAllByTestId("object-starter-shape");

describe("the starter's shapes", () => {
  it("offers the shapes the object fits, the best first and chosen, with its why and what it holds", async () => {
    draw();
    await waitFor(() => expect(cards()).toHaveLength(3));
    expect(cards().map(c => c.dataset.shape)).toEqual(["queue", "overview", "timeline"]);
    expect(cards()[0]).toHaveAttribute("aria-checked", "true");
    expect(cards()[0]).toHaveTextContent("fits best");
    expect(screen.getByTestId("object-starter-why")).toHaveTextContent("Why queue: Customer Order has a dispatch promise of 2 days; 1,275");
    const holds = within(screen.getByTestId("object-starter-holds")).getAllByRole("listitem").map(li => li.textContent);
    expect(holds).toContain("The list, oldest first — a click chooses, a tick collects");
    expect(screen.queryByTestId("object-starter-filter")).toBeNull();          // the checklist is the overview's
    expect(screen.getByTestId("object-starter-create")).toHaveTextContent("Make it");
  });

  it("keeps the queue over the days picked, saying it started as a queue", async () => {
    const onKept = draw();
    await waitFor(() => expect(cards()).toHaveLength(3));
    fireEvent.click(within(screen.getByRole("radiogroup", { name: "Days" })).getByRole("radio", { name: "7 days" }));
    fireEvent.click(screen.getByTestId("object-starter-create"));
    await waitFor(() => expect(onKept).toHaveBeenCalledWith("kept-1"));
    const [conn, title, spec, note] = start.startCockpit.mock.calls[0] as unknown as [string, string, { values: { window: { value: number } }; sets: Record<string, unknown> }, string];
    expect([conn, title, note]).toEqual(["thelook", "Dispatch desk", "Started from the object Customer Order as a queue"]);
    expect(spec.values.window.value).toBe(7);
    expect(Object.keys(spec.sets)).toEqual(["placed", "waiting", "done", "late"]);
  });

  it("is today's checklist as an overview, and a timeline when that is picked", async () => {
    draw();
    await waitFor(() => expect(cards()).toHaveLength(3));
    fireEvent.click(cards()[1]);
    expect(screen.getAllByTestId("object-starter-filter")).toHaveLength(1);
    expect(screen.queryByTestId("object-starter-holds")).toBeNull();
    fireEvent.click(screen.getByTestId("object-starter-create"));
    await waitFor(() => expect(start.startCockpit).toHaveBeenCalledTimes(1));
    expect((start.startCockpit.mock.calls[0] as unknown as string[])[3]).toBe("Started from the object Customer Order as an overview");
    start.startCockpit.mockClear();
    fireEvent.click(cards()[2]);
    expect(screen.getByTestId("object-starter-why")).toHaveTextContent("Why timeline: Each customer order holds two moments");
    fireEvent.click(screen.getByTestId("object-starter-create"));
    await waitFor(() => expect(start.startCockpit).toHaveBeenCalled());
    expect((start.startCockpit.mock.calls[0] as unknown as string[])[1]).toBe("Customer Orders over time");
  });

  it("is the starter before shapes while they are off", async () => {
    api.getCockpitFromObject.mockResolvedValue({ ...ORDER, shapes: undefined, signals: undefined });
    draw();
    await waitFor(() => expect(screen.getAllByTestId("object-starter-filter")).toHaveLength(1));
    expect(screen.queryByTestId("object-starter-shapes")).toBeNull();
    expect(screen.getByTestId("object-starter-create")).toHaveTextContent("Create cockpit");
  });
});

describe("an object that declares no key", () => {
  it("is counted and charted, its table not offered as if it could be listed — and none is kept", async () => {
    api.getCockpitFromObject.mockResolvedValue({ ...ORDER, name: "Event Log", title: "Event Logs", listable: false, shapes: undefined, signals: undefined });
    draw();
    await waitFor(() => expect(screen.getByTestId("object-starter-unlisted")).toHaveTextContent("Event Log declares no key"));
    expect(screen.queryByTestId("object-starter-table")).toBeNull();
    expect(screen.queryByTestId("object-starter-action")).toBeNull();
    fireEvent.click(screen.getByTestId("object-starter-create"));
    await waitFor(() => expect(start.startCockpit).toHaveBeenCalled());
    const spec = (start.startCockpit.mock.calls[0] as unknown as [string, string, { elements: Record<string, { type: string }> }])[2];
    expect(Object.values(spec.elements).map(e => e.type)).not.toContain("ObjectTable");
  });
});
