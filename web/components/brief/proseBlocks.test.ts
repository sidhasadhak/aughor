/**
 * Answer prose with block structure — the markdown table that rendered as pipes.
 *
 * Live: a quick turn tabulated its result into the answer text and every pipe and dash
 * of it reached the screen, because the answer surface had an INLINE-only renderer:
 *
 *   The number of flights per route is as follows (showing the top 10 routes by
 *   volume): | Route ID | Number of Flights | | :--- | :--- | | ZRH-LHR | 108 | …
 *
 * The tests assert on the parse, not on React output: what broke was the reading of the
 * text, and that is what has to stay fixed.
 */
import { describe, expect, it } from "vitest";

import { hasProseBlocks, renderProseBlocks } from "./BriefProse";

const LIVE_ANSWER = [
  "The number of flights per route is as follows (showing the top 10 routes by volume):",
  "",
  "| Route ID | Number of Flights |",
  "| :--- | :--- |",
  "| ZRH-LHR | 108 |",
  "| GVA-LHR | 96 |",
  "",
  "(There are 84 unique routes in total.)",
].join("\n");

describe("hasProseBlocks", () => {
  it("recognises a markdown table", () => {
    expect(hasProseBlocks(LIVE_ANSWER)).toBe(true);
  });

  it("leaves ordinary prose alone", () => {
    expect(hasProseBlocks("GVA-LHR leads with 42 flights, then ZRH-CDG at 35.")).toBe(false);
  });

  it("does not mistake a sentence containing a pipe for a table", () => {
    expect(hasProseBlocks("Filter is a | b, which matched nothing.")).toBe(false);
  });

  it("needs the rule row — a header alone is not a table", () => {
    expect(hasProseBlocks("| Route | Flights |\n| ZRH-LHR | 28 |")).toBe(false);
  });

  it("is safe on empty input", () => {
    expect(hasProseBlocks("")).toBe(false);
  });
});

describe("renderProseBlocks", () => {
  it("splits the live answer into prose, table, prose", () => {
    const blocks = renderProseBlocks(LIVE_ANSWER);
    expect(blocks).toHaveLength(3);
  });

  it("keeps a table with no body rows as prose rather than inventing an empty one", () => {
    const blocks = renderProseBlocks("| Route | Flights |\n| :--- | :--- |");
    // header + rule and nothing else: not a table anyone can read
    expect(blocks).toHaveLength(1);
  });

  it("splits paragraphs on blank lines", () => {
    expect(renderProseBlocks("First point.\n\nSecond point.")).toHaveLength(2);
  });

  it("returns nothing for empty text", () => {
    expect(renderProseBlocks("")).toHaveLength(0);
  });
});
