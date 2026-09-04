/**
 * The anti-drift guard for a rule that lives on two sides.
 *
 * `automationFlow.ts` warns that "a rule mirrored on one side only is a rule that
 * disagrees with itself" — it was written after the client's binding check rejected a
 * server-valid binding. The cast vocabulary is the same shape of rule, so it gets a test
 * that reads BOTH files rather than a comment asking people to remember.
 *
 * Parsing the Python source rather than importing it: this is a vitest suite with no
 * Python runtime, and the alternative — duplicating the list into a fixture — would be a
 * third copy of the thing whose duplication is the risk.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { CASTS } from "./automationFlow";

function serverCasts(): string[] {
  // From the vitest root (`web/`), not `__dirname` — that is undefined under ESM, and the
  // vacuity guard below is what caught it rather than a silently empty comparison.
  const src = readFileSync(
    resolve(process.cwd(), "..", "aughor", "automations", "dataflow.py"), "utf8");
  // Anchored on the closing paren at LINE START, not the first ")" — the block's own
  // comments contain parentheses ("post only if > 0"), and splitting on those truncated
  // the parse after a single entry. The vacuity guard below is what surfaced that.
  const block = src.split("CASTS: tuple[str, ...] = (")[1]?.split("\n)")[0] ?? "";
  // Only quoted entries, and only outside comment lines: a comment quoting a value (the
  // boolean note quotes "false") would otherwise be read as part of the vocabulary.
  return block.split("\n")
    .filter(line => !line.trim().startsWith("#"))
    .flatMap(line => [...line.matchAll(/"([a-z]+)"/g)].map(m => m[1]));
}

describe("$as cast vocabulary", () => {
  it("finds the server's list at all", () => {
    // Vacuity guard: an empty parse would make the equality below trivially satisfiable
    // by an empty client list, which is the failure this whole file exists to catch.
    expect(serverCasts().length).toBeGreaterThan(4);
  });

  it("matches the server's CASTS exactly", () => {
    expect([...CASTS].sort()).toEqual(serverCasts().sort());
  });
});
