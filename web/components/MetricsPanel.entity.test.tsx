// @vitest-environment jsdom
/**
 * Arc OC-3 — the metric editor's Measures block: the proposal and why, Confirm sending the proposed entity, a confirmed
 * key with Clear, and a house metric (every connection) showing nothing.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Metric } from "@/lib/api";

vi.mock("@/lib/useMe", () => ({ useMe: () => ({ actor: "ana" }) }));

import { EntitySection } from "./MetricsPanel";

type Call = { url: string; method: string; body?: string };

function serve() {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url: String(url), method: init?.method ?? "GET", body: init?.body as string | undefined });
    if (String(url).includes("/ontology/keys")) {
      return new Response(JSON.stringify({
        connection_id: "c", schema_name: "thelook",
        entities: [{ id: "Order", label: "Order" }, { id: "OrderItem", label: "Order item" }],
        metrics: [{ name: "revenue", label: "Revenue", status: "approved", entity: "", confirmed_by: "", agrees: false,
                    proposal: { entity: "OrderItem", property: "created_at", candidates: ["OrderItem"],
                                why: "its grain, order_items.created_at, is a date of OrderItem's table order_items" } }],
      }));
    }
    return new Response(JSON.stringify({ name: "revenue" }));
  }));
  return calls;
}

const REVENUE: Metric = { name: "revenue", label: "Revenue", sql: "SELECT 1", connection: "c", schema_name: "thelook" } as Metric;

afterEach(() => vi.unstubAllGlobals());

describe("EntitySection", () => {
  it("shows the proposal with why, and Confirm sends the proposed entity", async () => {
    const calls = serve();
    const changed = vi.fn();
    render(<EntitySection metric={REVENUE} onChanged={changed} />);
    expect(await screen.findByText(/OrderItem, on its created_at — its grain/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(changed).toHaveBeenCalled());
    const put = calls.find((c) => c.method === "PUT");
    expect(put?.url).toContain("/metrics/revenue/entity?connection_id=c&schema=thelook");
    expect(JSON.parse(put?.body ?? "{}")).toEqual({ entity: "OrderItem" });
  });

  it("a confirmed key says who, and Clear sends an empty entity", async () => {
    const calls = serve();
    render(<EntitySection metric={{ ...REVENUE, entity: "OrderItem", entity_confirmed_by: "ana" }} onChanged={() => {}} />);
    expect(await screen.findByText("confirmed by ana")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Clear" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    expect(JSON.parse(calls.find((c) => c.method === "PUT")?.body ?? "{}")).toEqual({ entity: "" });
  });

  it("a house metric is keyed per connection, so it shows nothing", () => {
    serve();
    const { container } = render(<EntitySection metric={{ ...REVENUE, connection: "*" }} onChanged={() => {}} />);
    expect(container.firstChild).toBeNull();
  });
});
