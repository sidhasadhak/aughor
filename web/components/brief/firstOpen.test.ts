import { beforeEach, describe, expect, it } from "vitest";

import { claimBriefingEntrance, forgetPageClaimForTests } from "@/components/brief/firstOpen";

function memorySession() {
  const m = new Map<string, string>();
  return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v) };
}

describe("claimBriefingEntrance", () => {
  beforeEach(() => forgetPageClaimForTests());

  it("is granted to the first open of a session and to no later one", () => {
    const session = memorySession();
    expect(claimBriefingEntrance(session)).toBe(true);
    expect(claimBriefingEntrance(session)).toBe(false);
  });

  it("is not granted again after a page refresh in the same session", () => {
    const session = memorySession();
    expect(claimBriefingEntrance(session)).toBe(true);
    forgetPageClaimForTests();
    expect(claimBriefingEntrance(session)).toBe(false);
  });

  it("is still granted once when storage refuses", () => {
    const refusing = {
      getItem: (): string | null => { throw new Error("denied"); },
      setItem: (): void => { throw new Error("denied"); },
    };
    expect(claimBriefingEntrance(refusing)).toBe(true);
    expect(claimBriefingEntrance(refusing)).toBe(false);
  });
});
