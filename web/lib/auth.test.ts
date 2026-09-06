/**
 * The pure attach decision (VA-10). The wrapper patches window.fetch, but WHAT
 * it attaches is this function — testable with no window at all.
 */
import { describe, expect, it } from "vitest";
import { authHeaderFor, claimsOf } from "@/lib/auth";

const API = "http://localhost:8000";

describe("authHeaderFor", () => {
  it("attaches the bearer to API-base URLs only", () => {
    expect(authHeaderFor(`${API}/ask`, API, "tok")).toEqual({ Authorization: "Bearer tok" });
    expect(authHeaderFor("https://accounts.google.com/gsi/client", API, "tok")).toBeNull();
  });

  it("attaches nothing without a token", () => {
    expect(authHeaderFor(`${API}/ask`, API, null)).toBeNull();
  });

  it("never overrides a caller's own Authorization header", () => {
    // /cron-style callers and the webhook door carry their OWN credential.
    expect(authHeaderFor(`${API}/cron/tick`, API, "tok",
                         { Authorization: "Bearer cron-secret" })).toBeNull();
  });

  it("attaches when other, unrelated headers exist", () => {
    expect(authHeaderFor(`${API}/ask`, API, "tok", { "Content-Type": "application/json" }))
      .toEqual({ Authorization: "Bearer tok" });
  });
});

describe("claimsOf", () => {
  it("decodes a JWT payload for display", () => {
    const payload = Buffer.from(JSON.stringify({ email: "ada@example.test" }))
      .toString("base64url");
    expect(claimsOf(`h.${payload}.s`)?.email).toBe("ada@example.test");
  });

  it("is null on garbage", () => {
    expect(claimsOf(null)).toBeNull();
    expect(claimsOf("not-a-jwt")).toBeNull();
    expect(claimsOf("a.!!!.c")).toBeNull();
  });
});
