/**
 * The process designer's draft (2026-10-09): a person names things in words and the ids are made for them; a draft
 * that cannot be counted yet always says why. The walk-through typed "Delivery time", "Shipped" and "Delivered" and the
 * old form's button stayed disabled with nothing beside it.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  cockpitIdFor, dropDraft, emptyDraft, freshId, idFrom, keepDraft, keptDraft, notReady, toSpec, type ProcessDraft,
} from "@/lib/processDraft";

const ready: ProcessDraft = {
  ...emptyDraft("Order"),
  name: "Order delivery",
  stages: [
    { label: "Placed", anchor: { kind: "moment", path: "order_date" }, promise: null },
    { label: "Shipped", anchor: { kind: "moment", path: "shipped_at" }, promise: null },
    { label: "Delivered", anchor: { kind: "moment", path: "delivered_at" },
      promise: { kind: "days", amount: "5", name: "Delivery", target: "95" } },
  ],
};

describe("ids made from a person's words", () => {
  it("lower-cases, joins words with underscores, and starts with a letter", () => {
    expect(idFrom("Delivery time")).toBe("delivery_time");
    expect(idFrom("  Order → Delivery!  ")).toBe("order_delivery");
    expect(idFrom("2-day dispatch")).toBe("p_2_day_dispatch");
    expect(idFrom("Ça déménage")).toBe("ca_demenage");
    expect(idFrom("—")).toBe("");
  });

  it("never takes an id already held", () => {
    expect(freshId("order_delivery", ["order_fulfilment"])).toBe("order_delivery");
    expect(freshId("order_delivery", ["order_delivery", "order_delivery_2"])).toBe("order_delivery_3");
  });
});

describe("a new cockpit's id", () => {
  it("is the server's shape — lower-case words joined by hyphens, then a random suffix", () => {
    expect(cockpitIdFor("Order delivery", () => "a1b2c3")).toBe("order-delivery-a1b2c3");
    expect(cockpitIdFor("Délai d'expédition — 2 jours", () => "000000")).toBe("delai-d-expedition-2-jours-000000");
    expect(cockpitIdFor("—", () => "ffffff")).toBe("cockpit-ffffff");
    expect(cockpitIdFor("x".repeat(80))).toMatch(/^x{32}-[0-9a-f]{6}$/);
    expect(cockpitIdFor("Order delivery")).not.toBe(cockpitIdFor("Order delivery"));   // never counted, never the same
  });
});

describe("a draft that cannot be counted yet says why", () => {
  const stage = (i: number, change: object): ProcessDraft =>
    ({ ...ready, stages: ready.stages.map((s, j) => (j === i ? { ...s, ...change } : s)) });

  it.each([
    [{ ...ready, name: " " }, "Name the process."],
    [{ ...ready, entity: "" }, "Choose what moves through the process."],
    [{ ...ready, stages: ready.stages.slice(0, 1) }, "A process has at least two stages."],
    [stage(1, { label: "" }), "Name stage 2."],
    [stage(1, { anchor: null }), "Choose when an object reaches Shipped."],
    [stage(1, { anchor: { kind: "state", property: "status", values: [] } }), "Choose the status values that place an object in Shipped."],
    [stage(0, { promise: { kind: "days", amount: "2", name: "", target: "" } }), "Placed is the first stage — there is no stage before it to count a promise from."],
    [stage(1, { anchor: { kind: "state", property: "status", values: ["shipped"] } }),
      "Delivered's promise counts from the stage before it, which is reached by a status and has no moment to count from."],
    [stage(2, { promise: { kind: "days", amount: "five", name: "", target: "" } }), "Say how many days the promise on Delivered allows."],
    [stage(2, { promise: { kind: "deadline", deadline: "", name: "", target: "" } }), "Choose the deadline the promise on Delivered is kept by."],
    [stage(2, { promise: { kind: "days", amount: "5", name: "", target: "120" } }), "The target on Delivered is a percentage above 0, at most 100."],
    [stage(2, { label: "shipped" }), "Two stages are named alike (shipped) — name each stage differently."],
  ])("%#", (draft, why) => {
    expect(notReady(draft as ProcessDraft)).toBe(why);
  });

  it("is ready when every stage is named, reached and its promise complete", () => {
    expect(notReady(ready)).toBe("");
  });
});

describe("the declaration a draft becomes", () => {
  it("keeps the words as the names a reader sees and makes the ids from them", () => {
    expect(toSpec({ ...ready, owner: " Logistics ", leaves: { property: "status", values: ["cancelled", "refunded"] } },
      ["order_fulfilment"])).toEqual({
      id: "order_delivery", display_name: "Order delivery", entity: "Order", owner: "Logistics",
      stages: [
        { name: "placed", display_name: "Placed", timestamp: "order_date" },
        { name: "shipped", display_name: "Shipped", timestamp: "shipped_at" },
        { name: "delivered", display_name: "Delivered", timestamp: "delivered_at",
          promise: { name: "delivery", within_days: 5, target: 0.95 } },
      ],
      leaves: { property: "status", values: ["cancelled", "refunded"] },
    });
  });

  it("reads a status stage, an hours promise and a deadline promise in the door's own shape", () => {
    const spec = toSpec({ ...ready, stages: [
      { label: "Placed", anchor: { kind: "moment", path: "order_date" }, promise: null },
      { label: "Packed", anchor: { kind: "state", property: "status", values: ["packed"] }, promise: null },
      { label: "Shipped", anchor: { kind: "moment", path: "shipped_at" }, promise: { kind: "deadline", deadline: "ship_by", name: "", target: "" } },
      { label: "Delivered", anchor: { kind: "moment", path: "delivered_at" }, promise: { kind: "hours", amount: "72", name: "", target: "" } },
    ] }, ["order_delivery"]);
    expect(spec.id).toBe("order_delivery_2");
    expect(spec.stages.slice(1)).toEqual([
      { name: "packed", display_name: "Packed", property: "status", state: ["packed"] },
      { name: "shipped", display_name: "Shipped", timestamp: "shipped_at", promise: { deadline: "ship_by" } },
      { name: "delivered", display_name: "Delivered", timestamp: "delivered_at", promise: { within_hours: 72 } },
    ]);
  });
});

describe("a draft kept in this browser", () => {
  afterEach(() => { vi.unstubAllGlobals(); });

  it("is kept, read back and dropped — and a browser that keeps nothing says so", () => {
    const store = new Map<string, string>();
    vi.stubGlobal("localStorage", {
      getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => void store.set(k, v),
      removeItem: (k: string) => void store.delete(k),
    });
    expect(keepDraft("c1", "s", ready)).toBe(true);
    expect(keptDraft("c1", "s")).toEqual(ready);
    expect(keptDraft("c1", "other")).toBeNull();
    dropDraft("c1", "s");
    expect(keptDraft("c1", "s")).toBeNull();
    vi.stubGlobal("localStorage", { setItem: () => { throw new Error("private mode"); }, getItem: () => null, removeItem: () => {} });
    expect(keepDraft("c1", "s", ready)).toBe(false);
  });
});
