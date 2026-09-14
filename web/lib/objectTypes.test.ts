/**
 * ON-8 — the organisation's ontology travels where a connection id goes. What is pinned: a domain scope reaches every
 * door as `?domain=` and never with a schema, and the scope itself stays in `connection_id`, so a door that does not
 * read domains answers for a connection nobody registered — nothing — instead of for another connection.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { domainScope, getTypeMap, measureOntology, scopeDomain } from "@/lib/objectTypes";

const calls: string[] = [];

afterEach(() => {
  calls.length = 0;
  vi.unstubAllGlobals();
});

function stubFetch(): void {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    calls.push(String(url));
    return new Response(JSON.stringify({ object_types: [], links: [] }), { status: 200 });
  }));
}

function query(at: number): URLSearchParams {
  return new URL(calls[at], "http://api.test").searchParams;
}

describe("the organisation's ontology as a scope", () => {
  it("names a domain where a connection id goes, and tells the two apart", () => {
    expect(domainScope()).toBe("domain:default");
    expect(scopeDomain(domainScope("finance"))).toBe("finance");
    expect(scopeDomain("domain:")).toBe("default");
    expect(scopeDomain("914df862")).toBeNull();
  });

  it("sends a domain to the doors, never a schema, and keeps the scope where no door can mistake it for a connection", async () => {
    stubFetch();
    await getTypeMap(domainScope("finance"), "ignored");
    await measureOntology(domainScope());
    await getTypeMap("914df862", "luxexperience");
    expect(query(0).get("domain")).toBe("finance");
    expect(query(0).get("schema_name")).toBeNull();
    expect(query(0).get("connection_id")).toBe("domain:finance");
    expect(query(1).get("domain")).toBe("default");
    expect(query(2).get("domain")).toBeNull();
    expect(query(2).get("schema_name")).toBe("luxexperience");
  });
});
