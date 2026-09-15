import { describe, expect, it, vi, afterEach } from "vitest";

import { listOntologySchemas, withSchemas } from "@/lib/objectTypes";

describe("the schemas an ontology is built on", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("join a picker after what it offers, each once, and never displace it", () => {
    expect(withSchemas(["main"], ["main", "ecommerce"])).toEqual(["main", "ecommerce"]);
    expect(withSchemas(["main"], ["ecommerce", "ecommerce", ""])).toEqual(["main", "ecommerce"]);
    expect(withSchemas([], ["ecommerce"])).toEqual(["ecommerce"]);
    expect(withSchemas(["main"], [])).toEqual(["main"]);
  });

  it("are read from the store for one connection, and a refusal says why", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ schemas: ["main", "ecommerce"] }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(listOntologySchemas("baef6c3e")).resolves.toEqual(["main", "ecommerce"]);
    expect(String((fetchMock.mock.calls[0] as unknown[])[0])).toContain("/ontology/schemas?connection_id=baef6c3e");
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail: "no such connection" }), { status: 404 })));
    await expect(listOntologySchemas("nope")).rejects.toThrow("no such connection");
  });
});
