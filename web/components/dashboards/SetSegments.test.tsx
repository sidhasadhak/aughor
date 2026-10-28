// @vitest-environment jsdom

/**
 * Arc FA-4 in the builder — a set becomes a segment. A set's setup shows its chain step by step, a count at each (a set
 * it is combined with counted beside it), and keeps a set of fixed conditions as a segment: declared by the person as a
 * condition rule with the author's values in place, said to be in the draft. A set a segment cannot hold says why; one
 * already kept says under which name. Every read is mocked: no test here reaches an API.
 */
import { fireEvent, render, screen, waitFor } from "@/lib/testing";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SetSetup } from "@/components/dashboards/WiringSetup";
import type { DashboardSpec } from "@/lib/dashboards/edit";

const objects = vi.hoisted(() => ({ queryObjects: vi.fn(), cachedObjectCatalog: vi.fn() }));
vi.mock("@/lib/objects", async (original) => ({ ...(await original<typeof import("@/lib/objects")>()), ...objects }));
const types = vi.hoisted(() => ({ getObjectType: vi.fn(), getProcesses: vi.fn(), declareRule: vi.fn() }));
vi.mock("@/lib/objectTypes", async (original) => ({ ...(await original<typeof import("@/lib/objectTypes")>()), ...types }));
const api = vi.hoisted(() => ({ getSystemFlags: vi.fn(async () => ({})) }));
vi.mock("@/lib/api", async (original) => ({ ...(await original<typeof import("@/lib/api")>()), ...api }));

const ORDER = { id: "order", object_type: "order", segments: [], links: [], derived: { segments: [], properties: [], metrics: [] },
  properties: [{ name: "status", display_name: "Status", role: "dimension", data_type: "STRING", unit: "", is_key: false, null_rate: 0, description: "", source: {} }] };

function desk(): DashboardSpec {
  return {
    root: "desk",
    values: { window: { label: "Window", kind: "days", value: 14 }, mine: { label: "Status", kind: "text", value: "Shipped", from: { by: "reader" } } },
    sets: {
      placed: { label: "Placed", entity: "order", where: [{ path: "created_at", op: "in_last", value_from: "window" }] },
      waiting: { label: "Waiting", from: "placed", where: [{ path: "status", op: "=", value: "Processing" }] },
      returned: { label: "Returned", entity: "order", where: [{ path: "status", op: "=", value: "Returned" }] },
      both: { label: "Waiting and returned", from: "placed", combine: { op: "both", set: "returned" } },
      chosen: { label: "By status", entity: "order", where: [{ path: "status", op: "=", value_from: "mine" }] },
    },
    elements: { desk: { type: "Section", props: { title: "Desk" }, children: [] } },
  } as unknown as DashboardSpec;
}
// what each set holds, by the conditions it is read with — the door's count
function held(filters: { op: string; value?: unknown }[] = []): string {
  if (filters.some(f => f.value === "Returned")) return "88";
  if (filters.some(f => f.op === "in_set")) return "41";
  if (filters.some(f => f.value === "Processing")) return "1327";
  return filters.some(f => f.op === "in_last") ? "6619" : "125080";
}

let conn = 0;
const draw = (name: string) => render(<SetSetup spec={desk()} name={name} onChange={vi.fn()} onGone={vi.fn()} connectionId={`c${++conn}`} />);

beforeEach(() => {
  vi.clearAllMocks();
  objects.queryObjects.mockImplementation(async (b: { filters?: { op: string; value?: unknown }[] }) =>
    ({ path: "compiled", rows: [[held(b.filters)]], caveats: [], error: null }));
  objects.cachedObjectCatalog.mockResolvedValue({ object_types: [{ object_type: "order", id: "Order", display_name: "Order" }] });
  types.getObjectType.mockResolvedValue(ORDER);
  types.getProcesses.mockResolvedValue({ processes: [], rules: [] });
  types.declareRule.mockImplementation(async (_c: string, spec: { id: string }) => ({ id: spec.id, admitted: 1327 }));
});

describe("a set's chain, a count at each step", () => {
  it("counts each set it starts from, from the first to this one", async () => {
    draw("waiting");
    await waitFor(() => expect(screen.getAllByTestId("set-chain-step").map(s => s.textContent)).toEqual(["Placed6,619", "Waiting1,327"]));
  });

  it("counts a set it is combined with beside its step", async () => {
    draw("both");
    await waitFor(() => expect(screen.getByTestId("set-chain-combined")).toHaveTextContent("both this and Returned88"));
    expect(screen.getAllByTestId("set-chain-step").map(s => s.dataset.name)).toEqual(["placed", "both"]);
  });
});

describe("keeping a set as a segment", () => {
  it("declares its conditions as the person's rule, the author's values in place, and says it is in the draft", async () => {
    draw("waiting");
    fireEvent.click(await screen.findByTestId("set-segment-keep"));
    await waitFor(() => expect(screen.getByTestId("set-segment-kept")).toHaveTextContent("Kept as segment waiting · 1,327"));
    expect(types.declareRule).toHaveBeenCalledWith(expect.stringMatching(/^c\d+$/), {
      id: "waiting", display_name: "Waiting", entity: "order", kind: "condition",
      conditions: [{ path: "status", op: "=", value: "Processing" }, { path: "created_at", op: "in_last", value: 14 }],
    }, undefined);
    expect(screen.getByTestId("set-segment")).toHaveTextContent("In the draft: readers get it when the ontology is published.");
  });

  it("says why the door refused it", async () => {
    types.declareRule.mockRejectedValue(new Error("a rule 'waiting' already exists"));
    draw("waiting");
    fireEvent.click(await screen.findByTestId("set-segment-keep"));
    await waitFor(() => expect(screen.getByTestId("set-segment-problem")).toHaveTextContent("a rule 'waiting' already exists"));
  });

  it("says a set already kept as a rule of the same definition, under its name", async () => {
    types.getProcesses.mockResolvedValue({ processes: [], rules: [{ id: "waiting_orders", kind: "condition", entity: "order", entity_id: "Order", admitted: 1327,
      conditions: [{ path: "status", op: "=", value: "Processing" }, { path: "created_at", op: "in_last", value: 14 }] }] });
    draw("waiting");
    await waitFor(() => expect(screen.getByTestId("set-segment-kept")).toHaveTextContent("Kept as segment waiting_orders"));
    expect(screen.queryByTestId("set-segment-keep")).toBeNull();
  });

  it("refuses, in a sentence, a set a segment cannot hold", async () => {
    draw("chosen");
    expect(await screen.findByTestId("set-segment-refused")).toHaveTextContent(
      "The set \"By status\" reads \"Status\", a value the reader sets on the page, and a segment's conditions are fixed.");
    expect(screen.queryByTestId("set-segment-keep")).toBeNull();
  });
});
