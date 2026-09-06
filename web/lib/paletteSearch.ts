/**
 * paletteSearch — the ⌘K palette's fuzzy-search configuration, as a pure module.
 *
 * Extracted (SP-2) so the palette and its latency receipt measure the SAME
 * pipeline: the receipt that says "plain commands stay fast" is worthless if it
 * benchmarks a copy of the options that can drift from the ones the overlay
 * actually runs. The Spotlight row is deliberately OUTSIDE this index — it is
 * appended after the search returns, so its existence costs zero per keystroke;
 * that shape is load-bearing and pinned by the latency test.
 */

import Fuse, { type IFuseOptions } from "fuse.js";

export interface PaletteSearchable {
  label: string;
  sublabel?: string;
  keywords?: string;
}

export function paletteFuseOptions<T extends PaletteSearchable>(): IFuseOptions<T> {
  return {
    keys: [
      { name: "label", weight: 2 },
      { name: "sublabel", weight: 1 },
      { name: "keywords", weight: 1 },
    ],
    threshold: 0.35,
    includeMatches: true,
    minMatchCharLength: 1,
  };
}

export function buildPaletteIndex<T extends PaletteSearchable>(items: T[]): Fuse<T> {
  return new Fuse(items, paletteFuseOptions<T>());
}
