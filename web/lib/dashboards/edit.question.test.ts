import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import { placeQuestion, sectionsOf } from "@/lib/dashboards/edit";
import { checkDashboardSpec } from "@/lib/dashboards/rules";

/** The dashboard every rules test starts from. */
const SPEC = JSON.parse(readFileSync(resolve(process.cwd(), "lib/dashboards/premise.fixture.json"), "utf8"));
const FIRST = sectionsOf(SPEC)[0].key;

describe("placing a question (PENDING 54)", () => {
  it("places it in the first section by its automation — and with the answer it was kept from — and the rules accept it", () => {
    const s = placeQuestion(SPEC, "aut-1a2b3c4d", "d4039693");
    const key = s.elements[FIRST].children.at(-1)!;
    expect(s.elements[key]).toMatchObject({ type: "Question", props: { automation: "aut-1a2b3c4d", first: "d4039693" } });
    expect(checkDashboardSpec(s).valid).toBe(true);
  });

  it("places nothing without an automation, and the rules refuse a question whose automation is not an id", () => {
    expect(placeQuestion(SPEC, "")).toEqual(SPEC);
    const bad = placeQuestion(SPEC, "aut-1a2b3c4d");
    const key = bad.elements[FIRST].children.at(-1)!;
    (bad.elements[key].props as Record<string, unknown>).automation = "not an id!";
    expect(checkDashboardSpec(bad).valid).toBe(false);
  });
});
