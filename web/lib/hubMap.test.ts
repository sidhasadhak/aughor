import { describe, expect, it } from "vitest";

import type { HubCost, HubProbation } from "@/lib/api";
import {
  costCaveat, costText, destinationText, probationText, stateColor, tokensText,
} from "@/lib/hubMap";

const COST: HubCost = {
  window_days: 7, runs: 2, deep_runs: 1, total_tokens: 1244, cost_usd: 0.05,
  unpriced_calls: 0, calls_without_usage: 0, floor: true,
};

describe("destinationText", () => {
  it("names a routed notify by what it routes about and how many it reached", () => {
    expect(destinationText({
      kind: "notify", target: "promise:p.d", routed_about: "promise:p.d",
      resolved: [{ principal: "group:supply-chain", channel_trigger_id: "", group_id: "supply-chain", why: [] }],
    })).toBe("routed(promise:p.d) → 1 destination");
  });
  it("names a slack post by its channel and a trigger by its label", () => {
    expect(destinationText({ kind: "slack_post", target: "", channel: "#ops" })).toBe("slack #ops");
    expect(destinationText({ kind: "notify", target: "t1", label: "Ops webhook", type: "webhook" }))
      .toBe("Ops webhook (webhook)");
  });
});

describe("cost", () => {
  it("renders dollars and tokens, and dashes an empty window", () => {
    expect(costText(COST)).toBe("$0.0500 · 1.2k tok");
    expect(costText({ ...COST, runs: 0, total_tokens: 0 })).toBe("—");
    expect(tokensText(999)).toBe("999 tok");
  });
  it("says why it is a floor only when something was unpriced", () => {
    expect(costCaveat(COST)).toBe("");
    expect(costCaveat({ ...COST, unpriced_calls: 2, calls_without_usage: 1 }))
      .toBe("2 calls with no published rate, 1 calls that reported no usage — a floor, not a total");
  });
});

describe("probationText", () => {
  const P: HubProbation = {
    on: true, marked: 0, counts: {}, unlanded: 0, precision: null,
    graduates_at: { min_marked: 5, precision: 0.8 },
  };
  it("renders unmeasured as not measured, never 0%", () => {
    expect(probationText(P)).toBe("probation · not measured");
  });
  it("counts unlanded pushes in the denominator", () => {
    expect(probationText({ ...P, marked: 4, unlanded: 1, precision: 0.8 }))
      .toBe("probation · 80% of 5");
  });
  it("says graduated once probation lifts with marks behind it", () => {
    expect(probationText({ ...P, on: false, marked: 6, precision: 1 })).toBe("graduated");
    expect(probationText({ ...P, on: false })).toBe("—");
  });
});

describe("stateColor", () => {
  it("keeps live green, muted amber, the rest quiet", () => {
    expect(stateColor("live")).toBe("var(--grn3)");
    expect(stateColor("muted")).toBe("var(--amb3)");
    expect(stateColor("disabled")).toBe("var(--t3)");
  });
});
