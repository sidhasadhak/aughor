// @vitest-environment jsdom

/**
 * The component project has no network (`vitest.setup.ts`). This pins that, because the alternative is silent:
 * with a real `fetch`, `getApiBase()` answers `http://localhost:8000` and an unmocked call in a jsdom test reads
 * — and writes — whatever platform the developer is running. That happened here before this existed.
 */
import { describe, expect, it } from "vitest";

import { getApiBase } from "@/lib/config";

describe("the component project's network", () => {
  it("rejects an unmocked call, and says what to do instead", async () => {
    await expect(fetch(`${getApiBase()}/me/preferences`)).rejects.toThrow(/no network — mock the module/);
  });

  it("names the URL it stopped, so the mock that is missing is obvious", async () => {
    await expect(fetch("http://localhost:8000/objects/query", { method: "POST" }))
      .rejects.toThrow("http://localhost:8000/objects/query");
  });
});
