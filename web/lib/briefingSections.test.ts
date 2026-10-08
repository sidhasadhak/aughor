/**
 * The Briefing's switches (B1): what the stored preference comes to, and what a person's words
 * come to — a proposal, kept whole or not, never a write.
 */
import { describe, expect, it } from "vitest";

import {
  BRIEFING_SECTIONS, DEFAULT_SECTIONS, moved, normalizeSections, proposeFromWords, toggled, type BriefingSectionsPref,
} from "@/lib/briefingSections";

const COCKPITS = [{ id: "growth-review-1a2b", title: "Growth review" }, { id: "returns-9f", title: "Returns" }];
const order = (p: BriefingSectionsPref) => p.sections.map(s => `${s.id}${s.on ? "" : ":off"}`);

describe("the preference", () => {
  it("lists every section once, in the kept order, and appends one the store left out, shown", () => {
    const p = normalizeSections({ sections: [{ id: "synthesis", on: true }, { id: "findings", on: false }, { id: "nope" }, { id: "synthesis" }], strip: "returns-9f" });
    expect(order(p)).toEqual(["synthesis", "findings:off", "verdict", "key_metrics", "cockpit", "patterns"]);
    expect(p.strip).toBe("returns-9f");
    expect(normalizeSections(undefined)).toEqual(DEFAULT_SECTIONS);
    expect(normalizeSections({ strip: 7 }).strip).toBe("");
    expect(BRIEFING_SECTIONS.map(s => s.id)).toEqual(["verdict", "key_metrics", "findings", "synthesis", "cockpit", "patterns"]);
  });

  it("toggles and moves without touching the rest", () => {
    expect(order(toggled(DEFAULT_SECTIONS, "findings", false))).toEqual(["verdict", "key_metrics", "findings:off", "synthesis", "cockpit", "patterns"]);
    expect(order(moved(DEFAULT_SECTIONS, "synthesis", 0))).toEqual(["synthesis", "verdict", "key_metrics", "findings", "cockpit", "patterns"]);
    expect(order(moved(DEFAULT_SECTIONS, "verdict", 99))).toEqual(["key_metrics", "findings", "synthesis", "cockpit", "patterns", "verdict"]);
  });
});

describe("the words", () => {
  it("hide the findings, put the synthesis first — two switches, one proposal", () => {
    const out = proposeFromWords("hide the findings, put the synthesis first", DEFAULT_SECTIONS, COCKPITS);
    expect(out.kind).toBe("proposal");
    if (out.kind !== "proposal") return;
    expect(out.lines).toEqual(["Hide “Findings” — one line stays saying it is hidden", "Put “Full synthesis” first"]);
    expect(order(out.next)).toEqual(["synthesis", "verdict", "key_metrics", "findings:off", "cockpit", "patterns"]);
    expect(out.next.strip).toBe("");
  });

  it("names the cockpit that rides with the Briefing, and shows the section it rides in", () => {
    const hidden = toggled(DEFAULT_SECTIONS, "cockpit", false);
    const out = proposeFromWords("show the Growth review strip with it", hidden, COCKPITS);
    expect(out.kind).toBe("proposal");
    if (out.kind !== "proposal") return;
    expect(out.lines).toEqual(["Let “Growth review” ride with your Briefing"]);
    expect(out.next.strip).toBe("growth-review-1a2b");
    expect(out.next.sections.find(s => s.id === "cockpit")?.on).toBe(true);
    const none = proposeFromWords("no cockpit strip", out.next, COCKPITS);
    expect(none.kind === "proposal" && none.next.strip).toBe("");
  });

  it("reads before and after, show, and the key metrics before the bare word", () => {
    const out = proposeFromWords("put the key metrics after the synthesis and show patterns", DEFAULT_SECTIONS, COCKPITS);
    expect(out.kind).toBe("proposal");
    if (out.kind !== "proposal") return;
    expect(out.lines).toEqual(["Put “Key Metrics” after “Full synthesis”", "Show “Top patterns”"]);
    expect(order(out.next)).toEqual(["verdict", "findings", "synthesis", "key_metrics", "cockpit", "patterns"]);
  });

  it("refuses what it does not read, and says what can be said; a switch already so is said so", () => {
    const out = proposeFromWords("write me a note saying returns are too high", DEFAULT_SECTIONS, COCKPITS);
    expect(out.kind).toBe("refused");
    expect(out.kind === "refused" && out.why).toContain("hide or show a section");
    const same = proposeFromWords("show the findings", DEFAULT_SECTIONS, COCKPITS);
    expect(same.kind === "refused" && same.why).toContain("already reads that way");
  });
});
