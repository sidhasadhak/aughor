/**
 * SP-2's latency receipt — "palette latency for plain commands unchanged,
 * measured" — over the REAL search pipeline (lib/paletteSearch is the module the
 * overlay runs; benchmarking a copy would measure nothing).
 *
 * The bound is deliberately generous (a regression tripwire, not a stopwatch —
 * CI machines vary): typical per-keystroke cost on a laptop is well under a
 * millisecond at this population. The measured numbers print with the run so a
 * drift is visible before the bound trips. The second test pins the SHAPE that
 * keeps Spotlight free: the fallthrough row is appended after the search, never
 * indexed, so its existence costs zero per keystroke.
 */
import { describe, expect, it } from "vitest";

import { buildPaletteIndex } from "./paletteSearch";

function population(n: number) {
  const words = ["monitor", "canvas", "catalog", "builder", "agent", "metric",
                 "health", "inbox", "orders", "returns", "revenue", "settings"];
  return Array.from({ length: n }, (_, i) => ({
    label: `${words[i % words.length]} ${i}`,
    sublabel: `${words[(i + 3) % words.length]} row ${i}`,
    keywords: `${words[(i + 5) % words.length]} extra terms`,
  }));
}

describe("palette search latency", () => {
  it("filters a busy deployment's item list well inside a keystroke", () => {
    const fuse = buildPaletteIndex(population(800));
    const queries = ["mon", "agents", "set", "rev", "cata", "he", "build", "ret"];

    // Warm once (Fuse lazily finishes its index on first search).
    fuse.search("warm");

    const t0 = performance.now();
    let hits = 0;
    for (let round = 0; round < 5; round++) {
      for (const q of queries) hits += fuse.search(q).slice(0, 20).length;
    }
    const perSearchMs = (performance.now() - t0) / (5 * queries.length);

    // eslint-disable-next-line no-console
    console.log(`palette search: ${perSearchMs.toFixed(2)} ms/keystroke over 800 items (${hits} hits total)`);
    expect(hits).toBeGreaterThan(0);           // the measurement measured something
    expect(perSearchMs).toBeLessThan(50);      // tripwire, ~50× typical headroom
  });

  it("keeps the Spotlight fallthrough out of the index — appending is O(1)", () => {
    const items = population(400);
    const fuse = buildPaletteIndex(items);
    const results = fuse.search("monitor").slice(0, 20);
    // The overlay appends its Spotlight row AFTER this array; nothing in the
    // index knows the row exists. Appending one element to twenty is not a
    // per-keystroke cost worth a number — the pinned fact is structural: the
    // searchable population is exactly the items given, nothing more.
    expect(results.every(r => items.includes(r.item))).toBe(true);
  });
});
