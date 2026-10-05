import { describe, expect, it } from "vitest";

import { DESTINATIONS, locate, movedNotice, pagesOf, resolveLegacy } from "./destinations";

/**
 * Every place the 2026 rail and its workspaces could open, as the shell's state names it: the tab
 * that renders it and the layer inside. A rearrangement of the six destinations may move any of
 * them, and may not lose one — a saved link must still open (the 2027 study §U, rule 5).
 */
const PLACES_OF_2026: [string, string | undefined][] = [
  ["inbox", undefined], ["canvases", undefined], ["recents", undefined], ["health", undefined], ["documents", undefined],
  ["intelligence", "briefing"], ["intelligence", "hub"], ["intelligence", "ontology"], ["intelligence", "graph"],
  ["intelligence", "evidence"], ["intelligence", "memory"], ["intelligence", "org"], ["intelligence", "brain"],
  ["intelligence", "cockpit"],
  ["data", "catalog"], ["data", "query"], ["data", "semantic"],
  ["operations", "monitors"], ["operations", "actions"], ["operations", "integrations"], ["operations", "spend"],
  ["operations", "security"],
  ["agentic-ops", "fleet"], ["agentic-ops", "agents"], ["agentic-ops", "attention"], ["agentic-ops", "activity"],
  ["agentic-ops", "automations"], ["agentic-ops", "hub"], ["agentic-ops", "departures"],
  ["evals", "suites"], ["evals", "runs"], ["evals", "experiments"],
];

describe("the six destinations", () => {
  it("are six, each a question, each page named once", () => {
    expect(DESTINATIONS.map(d => d.id)).toEqual(["now", "inquiries", "decisions", "missions", "record", "operations"]);
    expect(DESTINATIONS.every(d => d.question.endsWith("?"))).toBe(true);
    const ids = DESTINATIONS.flatMap(d => d.pages.map(p => p.id));
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("open every page where its own address says it lives", () => {
    for (const d of DESTINATIONS) {
      for (const page of d.pages) {
        const here = locate(page.at.tab, page.at.layer);
        expect(here.destination?.id, `${d.id} ▸ ${page.id}`).toBe(d.id);
        expect(here.page?.id, `${d.id} ▸ ${page.id}`).toBe(page.id);
      }
    }
  });

  it("still hold every place the 2026 rail could open", () => {
    for (const [tab, layer] of PLACES_OF_2026) {
      const here = locate(tab, layer);
      expect(here.destination, `${tab}${layer ? ` ▸ ${layer}` : ""} resolves to no destination`).not.toBeNull();
      expect(here.page, `${tab}${layer ? ` ▸ ${layer}` : ""} resolves to no page`).not.toBeNull();
    }
  });

  it("resolve the two ids that no longer name a screen, and nothing else", () => {
    expect(resolveLegacy("home")).toEqual({ tab: "now", layer: undefined });
    expect(resolveLegacy("settings")).toEqual({ tab: "admin", layer: undefined });
    expect(resolveLegacy("inbox")).toBeNull();
    expect(locate("now").page?.id).toBe("now");
    expect(locate("admin").destination?.id).toBe("operations");
  });

  it("say once where a moved screen went, and nothing for one that did not move", () => {
    expect(movedNotice("inbox", locate("inbox"))).toBe("The Inbox is now Decisions ▸ Proposed.");
    expect(movedNotice("home", locate("now"))).toBe("Home is now Now ▸ This week.");
    expect(movedNotice("settings", locate("admin"))).toBe("Settings is now Operations ▸ Admin.");
    expect(movedNotice("now", locate("now"))).toBeNull();
    expect(movedNotice("missions", locate("missions"))).toBeNull();
  });

  it("show a flagged page only while its flag is on", () => {
    const missions = DESTINATIONS.find(d => d.id === "missions")!;
    expect(pagesOf(missions).map(p => p.id)).toEqual(["missions", "monitors"]);
    expect(pagesOf(missions, { "cockpit.composed": true }).map(p => p.id)).toEqual(["missions", "monitors", "cockpits"]);
  });

  it("place a working surface in a destination without a page of its own", () => {
    expect(locate("canvas-workspace").destination?.id).toBe("record");
    expect(locate("canvas-workspace").page).toBeNull();
    expect(locate("chat").destination).toBeNull();
  });
});
