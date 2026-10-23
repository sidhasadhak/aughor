/**
 * Keeping a query of one's own (Arc AP-7): a refusal comes back as the server says it — each reason in its own words, so
 * the setup can list them — and anything else that fails says what failed.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { QueryRefused, keepDashboardQuery } from "@/lib/api";

afterEach(() => { vi.unstubAllGlobals(); });

describe("keeping a query of one's own", () => {
  it("hands back each reason the server refused it with", async () => {
    const reasons = ["Along the bottom names “nowhere”, which this query does not return.", "Sum reads a number, and “country” is text."];
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail: { refused: reasons } }), { status: 422 })));
    const refused = await keepDashboardQuery("thelook", { sql: "SELECT 1", shown: { as: "bar" } }).catch(e => e);
    expect(refused).toBeInstanceOf(QueryRefused);
    expect((refused as QueryRefused).reasons).toEqual(reasons);
  });

  it("says what failed when the server failed, never a refusal", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail: "Connection not found" }), { status: 404 })));
    const failed = await keepDashboardQuery("thelook", { sql: "SELECT 1", shown: {} }).catch(e => e);
    expect(failed).not.toBeInstanceOf(QueryRefused);
    expect((failed as Error).message).toContain("Connection not found");
  });
});
