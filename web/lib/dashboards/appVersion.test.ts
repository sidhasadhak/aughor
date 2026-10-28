import { describe, expect, it } from "vitest";

import { appWords } from "./appVersion";

const sales = { kind: "group" as const, id: "g1", name: "Sales team" };

describe("appWords — what an App's owner is told about the version its readers read (ED-4)", () => {
  it("a dashboard published to nobody offers to publish", () => {
    expect(appWords({ version: 3, published_to: [] })).toEqual({ label: "Publish as an App", title: "", draft: false, readersSee: null });
  });

  it("a server from before App versions says no state, and the words read as before", () => {
    expect(appWords({ version: 3, published_to: [sales] }).label).toBe("An App for Sales team");
    expect(appWords({ version: 3, published_to: [sales] }).draft).toBe(false);
  });

  it("a change kept since the published version is a draft, and says which version the readers read", () => {
    const w = appWords({ version: 4, published_to: [sales], state: "draft", published_version: 2 });
    expect(w.draft).toBe(true);
    expect(w.label).toBe("An App for Sales team · readers see version 2");
    expect(w.title).toContain("Its readers read version 2 until you publish.");
  });

  it("the version just published is not a draft", () => {
    expect(appWords({ version: 5, published_to: [sales], state: "published", published_version: 5 }).draft).toBe(false);
  });
});
