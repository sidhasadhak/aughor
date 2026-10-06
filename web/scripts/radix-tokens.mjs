/**
 * radix-tokens.mjs — what Radix Themes' stylesheet declares, read from the installed package.
 *
 * Since 2026-10-06 the Instrument tokens are names for Radix steps (`--bg-1: var(--gray-2)`),
 * so two gates have to know Radix's variables: the undefined-variable gate (is `--gray-2` a
 * real name, or a typo that silently resolves to nothing?) and the chart-palette gate (what
 * hex does the chart's surface come to in each skin?). Both read the same file the browser
 * loads — `@radix-ui/themes/styles.css` — rather than a list kept by hand, so an upgrade
 * that renames a step fails the gate instead of drifting past it.
 *
 * Zero dependencies, like the gates that import it.
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const WEB = join(dirname(fileURLToPath(import.meta.url)), "..");
const SHEET = join(WEB, "node_modules/@radix-ui/themes/styles.css");

/** Every declaration block in the sheet: its selector, its text, and the at-rules around it. */
function blocksOf(css) {
  const out = [];
  const stack = [];          // the blocks we are inside, outermost first
  const text = css.replace(/\/\*[\s\S]*?\*\//g, "");
  let buf = "";              // the text since the last brace or semicolon: a block's prelude
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (ch === "{") {
      if (stack.length > 0) stack[stack.length - 1].hasChild = true;
      stack.push({ prelude: buf.trim(), start: i + 1, hasChild: false });
      buf = "";
    } else if (ch === "}") {
      const top = stack.pop();
      // A block with no block inside it holds declarations.
      if (top && !top.hasChild) {
        out.push({ selector: top.prelude, body: text.slice(top.start, i), within: stack.map(s => s.prelude) });
      }
      buf = "";
    } else if (ch === ";") {
      buf = "";
    } else {
      buf += ch;
    }
  }
  return out;
}

let cached = null;
function sheet() {
  if (cached) return cached;
  let css;
  try { css = readFileSync(SHEET, "utf8"); }
  catch { throw new Error(`Radix Themes' stylesheet is not installed at ${SHEET} — run npm install in web/`); }
  const blocks = blocksOf(css);
  const names = new Set();
  const values = new Map();   // --name → the last value declared for it, for the category gate
  const DECL = /(--[a-zA-Z0-9-]+)\s*:\s*([^;}]*)/g;
  for (const b of blocks) {
    for (const m of b.body.matchAll(DECL)) { names.add(m[1]); values.set(m[1], m[2].trim()); }
  }
  cached = { blocks, names, values };
  return cached;
}

/** Every custom property Radix Themes declares. */
export function radixNames() { return sheet().names; }

/** The last value Radix declares for a name — enough to tell a length from a colour. */
export function radixValues() { return sheet().values; }

/** Is this block one a wide-gamut screen reads INSTEAD of the sRGB one? Those repeat every
 *  colour as `color(display-p3 …)`; a gate that compares hexes reads the sRGB declaration. */
const wideGamut = (b) => b.within.some(p => /color-gamut|display-p3/.test(p));
const darkBlock = (b) => /\.dark\b/.test(b.selector);

/**
 * The value a Radix variable has at the Theme's root in one skin, with the grey the product
 * defaults to: a hex, or a keyword such as `white`. Follows `var()` the way the cascade does —
 * the skin's own declaration first, the light one (Radix's base) otherwise.
 */
export function radixValueAt(name, mode, seen = new Set()) {
  if (seen.has(name)) throw new Error(`${name} is a cyclic alias in Radix Themes' stylesheet`);
  seen.add(name);
  const { blocks } = sheet();
  const re = new RegExp(`(?:^|[\\s;{])${name}:\\s*([^;}]+)`);
  const pick = (wantDark) => {
    for (const b of blocks) {
      if (wideGamut(b) || darkBlock(b) !== wantDark) continue;
      // A scale re-declared for another grey (`[data-gray-color='slate']`) is not the default.
      if (/data-gray-color|data-accent-color/.test(b.selector)) continue;
      const m = b.body.match(re);
      if (m) return m[1].trim();
    }
    return null;
  };
  const value = (mode === "dark" ? pick(true) : null) ?? pick(false);
  if (!value) throw new Error(`${name} is not declared by Radix Themes (${mode})`);
  const alias = value.match(/^var\(\s*(--[a-zA-Z0-9-]+)\s*\)$/);
  return alias ? radixValueAt(alias[1], mode, seen) : value;
}
