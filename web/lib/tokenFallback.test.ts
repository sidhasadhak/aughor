import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { DEFAULT_LOOK } from "./look";
import { TOKEN_FALLBACK, type TokenName } from "./tokenFallback";
// The gates' own reader of Radix Themes' stylesheet: the file the browser loads.
import { radixValueAt } from "../scripts/radix-tokens.mjs";

const SHEET = readFileSync(join(__dirname, "../aughor-v2/theme/tokens-v2.css"), "utf8");
const ROOT = SHEET.slice(SHEET.indexOf(":root {"), SHEET.indexOf('[data-theme="light"] {'));
// The light skin re-declares the surfaces that differ from dark's (2026-10-25): its block is read first
// for light, as the cascade reads it on <html data-theme="light">, then the root for the rest.
const LIGHT = SHEET.slice(SHEET.indexOf('[data-theme="light"] {'));
const LIGHT_BLOCK = LIGHT.slice(0, LIGHT.indexOf("\n}") + 2);

function declaredIn(block: string, name: string): string | null {
  const m = block.match(new RegExp(`(?:^|[\\s;{])${name}:\\s*([^;]+);`, "m"));
  return m ? m[1].trim() : null;
}
function declared(name: string, mode: "light" | "dark"): string | null {
  return (mode === "light" ? declaredIn(LIGHT_BLOCK, name) : null) ?? declaredIn(ROOT, name);
}

/** A token's value in one skin at the default look: through our sheet's aliases, then into Radix's. */
function resolve(name: string, mode: "light" | "dark", depth = 0): string {
  if (depth > 8) throw new Error(`${name} does not resolve`);
  const ours = declared(name, mode);
  if (ours) {
    const alias = ours.match(/^var\(\s*(--[a-zA-Z0-9-]+)\s*\)$/);
    return alias ? resolve(alias[1], mode, depth + 1) : ours;
  }
  // The accent is the Theme's prop, not a declaration at the root: the default look names it.
  const radixName = name.replace(/^--accent-/, `--${DEFAULT_LOOK.accent}-`);
  const value = radixValueAt(radixName, mode);
  return value === "white" ? "#FFFFFF" : value;
}

describe("the token fallback table", () => {
  for (const mode of ["dark", "light"] as const) {
    it(`holds what each token resolves to at the default look (${mode})`, () => {
      const live = Object.fromEntries(
        (Object.keys(TOKEN_FALLBACK[mode]) as TokenName[]).map(name => [name, resolve(name, mode).toUpperCase()]),
      );
      expect(TOKEN_FALLBACK[mode]).toEqual(live);
    });
  }

  it("names the same tokens in both skins", () => {
    expect(Object.keys(TOKEN_FALLBACK.light)).toEqual(Object.keys(TOKEN_FALLBACK.dark));
  });
});
