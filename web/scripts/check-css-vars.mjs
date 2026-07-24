#!/usr/bin/env node
/**
 * Undefined-CSS-variable gate (UI Elevation Wave 1, move 1).
 *
 * A `var(--panel)` referencing a token that no sheet defines silently falls through
 * to the fallback (or to nothing) — the component quietly drifts off the design
 * system. This gate cross-checks every `var(--name)` reference in components/, app/,
 * lib/ and aughor-v2/ against the tokens actually DEFINED in the CSS sheets
 * (styles/*.css, app/globals.css, aughor-v2/theme/*.css), `@theme` blocks, and
 * inline `--name:` declarations in TSX style objects.
 *
 * Tailwind v4's own theme namespace (--color-*, --radius-*, --spacing*, --text-*,
 * --font-*, …) and runtime-injected vars (--i, --len, ECharts/antd internals) are
 * allowlisted below.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const WEB = join(fileURLToPath(new URL(".", import.meta.url)), "..");
const SRC_ROOTS = ["components", "app", "lib", "aughor-v2"];
const CSS_ROOTS = ["styles", "app", "aughor-v2"];

// Vars provided by Tailwind v4's default @theme or set at runtime, not by our sheets.
const ALLOW_PREFIXES = [
  "--color-", "--radius-", "--spacing", "--text-", "--font-", "--tw-",
  "--breakpoint-", "--container-", "--leading-", "--tracking-", "--shadow-2xs",
  "--animate-", "--ease-", "--blur-", "--aspect-", "--default-",
];
const ALLOW_EXACT = new Set([
  "--i", "--len", // stagger index / SVG draw length, set via inline style at use sites
  "--radius",      // shadcn bridge alias (defined in styles/tokens.css)
]);

function* walk(dir, exts) {
  let names;
  try { names = readdirSync(dir); } catch { return; }
  for (const name of names) {
    if (name === "node_modules" || name === ".next") continue;
    const p = join(dir, name);
    const st = statSync(p);
    if (st.isDirectory()) yield* walk(p, exts);
    else if (exts.some((e) => p.endsWith(e))) yield p;
  }
}

// 1) Collect defined custom properties: `--name:` in CSS sheets and TSX inline styles.
const defined = new Set();
const declaredValue = new Map(); // --name → its literal value, for the category gate below
const DEF_RE = /(--[a-zA-Z0-9-]+)\s*:\s*([^;}]*)/g;
for (const root of CSS_ROOTS) {
  for (const file of walk(join(WEB, root), [".css"])) {
    for (const m of readFileSync(file, "utf8").matchAll(DEF_RE)) {
      defined.add(m[1]);
      // Themes redeclare a token per scheme; the CATEGORY is stable across them, so last wins.
      declaredValue.set(m[1], m[2].trim());
    }
  }
}
for (const root of SRC_ROOTS) {
  for (const file of walk(join(WEB, root), [".tsx", ".ts"])) {
    // Inline style-object definitions: ["--x"]: … or "--x": …
    for (const m of readFileSync(file, "utf8").matchAll(/["'](--[a-zA-Z0-9-]+)["']\s*[:\]]/g)) {
      defined.add(m[1]);
    }
  }
}

// 2) Collect every var(--name) reference in source + CSS.
const REF_RE = /var\(\s*(--[a-zA-Z0-9-]+)/g;
const orphans = [];
for (const root of [...new Set([...SRC_ROOTS, ...CSS_ROOTS])]) {
  for (const file of walk(join(WEB, root), [".tsx", ".ts", ".css"])) {
    const lines = readFileSync(file, "utf8").split("\n");
    lines.forEach((line, i) => {
      for (const m of line.matchAll(REF_RE)) {
        const name = m[1];
        if (name.endsWith("-")) continue; // template literal (`var(--chart-${i})`) — dynamic index
        if (defined.has(name)) continue;
        if (ALLOW_EXACT.has(name)) continue;
        if (ALLOW_PREFIXES.some((p) => name.startsWith(p))) continue;
        orphans.push({ file: relative(WEB, file), line: i + 1, name });
      }
    });
  }
}

// 3) Category gate. Section 2 only catches a token that is UNDEFINED — where the fallback
// (or nothing) still renders. The silent case it structurally cannot see is a token that IS
// defined, but as the wrong KIND of value: `--r1..3` are radii, so `background: var(--r1)`
// substitutes to `background: 2px` — invalid, and a `var()` fallback never applies when the
// token exists. Nothing errors; the colour just vanishes.
//
// The check is deliberately one-directional and narrow, because a gate that cries wolf gets
// ignored: LENGTH tokens are few and their legitimate positions are a short closed list, so we
// assert only that a length token stays in a length position (and, symmetrically, that a colour
// never lands in one). Anything we cannot classify with certainty is left alone.
const LENGTH_VALUE = /^-?\d*\.?\d+(px|rem|em|vh|vw|ch|%)$/;
const COLOR_VALUE = /^(#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(|oklch\(|color-mix\()/;

function categoryOf(name, seen = new Set()) {
  if (seen.has(name)) return "unknown"; // alias cycle
  seen.add(name);
  const raw = declaredValue.get(name);
  if (!raw) return "unknown";
  if (LENGTH_VALUE.test(raw)) return "length";
  if (COLOR_VALUE.test(raw)) return "color";
  const alias = raw.match(/^var\(\s*(--[a-zA-Z0-9-]+)/);
  return alias ? categoryOf(alias[1], seen) : "unknown";
}

// Properties whose value is unambiguously a length, and unambiguously a colour. Both
// camelCase (TSX style objects) and kebab-case (CSS) spellings, lowercased so one entry covers
// both. Mixed shorthands (box-shadow, transform, background shorthand with an image) are in
// NEITHER list on purpose — they are handled by the border-style probe below or skipped.
const LENGTH_PROPS = new Set([
  "borderradius", "border-radius", "padding", "margin", "gap", "rowgap", "row-gap",
  "columngap", "column-gap", "width", "height", "minwidth", "min-width", "maxwidth",
  "max-width", "minheight", "min-height", "maxheight", "max-height", "fontsize",
  "font-size", "top", "left", "right", "bottom", "inset", "borderwidth", "border-width",
  "outlineoffset", "outline-offset", "letterspacing", "letter-spacing", "strokewidth",
  "stroke-width", "flexbasis", "flex-basis", "textindent", "text-indent",
]);
const COLOR_PROPS = new Set([
  "color", "background", "backgroundcolor", "background-color", "bordercolor",
  "border-color", "outlinecolor", "outline-color", "fill", "stroke", "caretcolor",
  "caret-color", "textdecorationcolor", "text-decoration-color", "accentcolor",
  "accent-color", "columnrulecolor", "column-rule-color",
  // Props this codebase passes colours through by convention.
  "accent", "tone",
]);
// Shorthands that hold a length AND a colour. A `solid|dashed|…` keyword between the property
// and the reference means the reference is in the COLOUR slot — that much is certain.
const MIXED_SHORTHANDS = new Set(["border", "outline", "borderbottom", "border-bottom",
  "bordertop", "border-top", "borderleft", "border-left", "borderright", "border-right"]);
const BORDER_STYLE = /\b(solid|dashed|dotted|double|groove|ridge|inset|outset)\b/;

// The nearest property key to the LEFT of the reference. Walking backwards (rather than
// anchoring at the start of the line) is what makes a ternary work —
// `background: cond ? "var(--a)" : "var(--b)"` must attribute BOTH arms to `background`.
// The `=` branch accepts a JSX prop (`tone="var(--x)"`) while rejecting `===`, `!==`, `=>`.
const PROP_BEFORE = /([a-zA-Z-]+)\s*(?::|(?<![=!<>])=(?![=>]))/g;
function propBefore(line, idx) {
  let last = null;
  for (const m of line.slice(0, idx).matchAll(PROP_BEFORE)) last = m[1];
  return last;
}

// A `const OUTCOME_COLOR = { error: "var(--r2)" }` map is a colour position too, but its keys
// are outcome names, not CSS properties. The enclosing declaration's name is what says so.
const COLORISH_NAME = /colou?r|tone|accent|palette|swatch/i;

const miscategorized = [];
for (const root of [...new Set([...SRC_ROOTS, ...CSS_ROOTS])]) {
  for (const file of walk(join(WEB, root), [".tsx", ".ts", ".css"])) {
    const lines = readFileSync(file, "utf8").split("\n");
    let enclosing = null;
    let inComment = false; // /* … */ spans lines, so a line-local test would miss the tail
    lines.forEach((line, i) => {
      const decl = line.match(/(?:const|let|var)\s+([A-Za-z_$][\w$]*)/);
      if (decl) enclosing = decl[1];
      const opened = line.lastIndexOf("/*");
      const closed = line.lastIndexOf("*/");
      const wasInComment = inComment;
      if (opened > closed) inComment = true;
      else if (closed > opened) inComment = false;
      if (wasInComment && inComment) return;
      for (const m of line.matchAll(REF_RE)) {
        const cat = categoryOf(m[1]);
        if (cat === "unknown") continue;
        const head = line.slice(0, m.index);
        // Tailwind arbitrary values (`rounded-[var(--r3)]`, `rounded-[min(var(--radius-md),8px)]`)
        // carry their property INSIDE the utility, not in a key we can read — unclassifiable, so
        // left alone. The tell is an UNCLOSED `-[`; testing for `className` on the line instead
        // would swallow a real `style={{ color: … }}` sitting after a className on the same line.
        if (/-\[[^\]]*$/.test(head)) continue;
        if (/\/\/|\/\*/.test(head)) continue;
        const prop = propBefore(line, m.index);
        if (!prop) continue;
        // A token aliasing another token is always legitimate — skip declarations.
        if (prop.startsWith("--") || head.includes(`--${prop}`)) continue;
        const key = prop.toLowerCase();
        const isLengthPos = LENGTH_PROPS.has(key);
        const isColorPos = COLOR_PROPS.has(key)
          || (MIXED_SHORTHANDS.has(key) && BORDER_STYLE.test(head))
          || (!isLengthPos && !!enclosing && COLORISH_NAME.test(enclosing));
        if ((cat === "length" && isColorPos) || (cat === "color" && isLengthPos)) {
          miscategorized.push({ file: relative(WEB, file), line: i + 1, name: m[1], prop, cat });
        }
      }
    });
  }
}

if (orphans.length === 0 && miscategorized.length === 0) {
  console.log(`✓ css-var gate: every var(--…) reference resolves to a defined token of the right kind (${defined.size} tokens known)`);
  process.exit(0);
}
if (orphans.length > 0) {
  console.error(`✗ css-var gate: ${orphans.length} reference(s) to undefined custom properties\n`);
  for (const o of orphans) console.error(`  ${o.file}:${o.line}  var(${o.name})`);
  console.error("\nDefine the token in styles/tokens.css | aughor-v2/theme/tokens-v2.css, or re-point the reference at an existing token.");
}
if (miscategorized.length > 0) {
  console.error(`${orphans.length > 0 ? "\n" : ""}✗ css-var gate: ${miscategorized.length} reference(s) use a token of the wrong KIND\n`);
  for (const o of miscategorized) {
    console.error(`  ${o.file}:${o.line}  ${o.prop}: var(${o.name})  — ${o.name} is a ${o.cat} token`);
  }
  console.error("\nThese resolve to a valid-but-nonsense value (e.g. `background: 2px`), so the declaration is");
  console.error("dropped and no var() fallback applies. Colours live on the intent palette (--grn* --red*");
  console.error("--amb* --blue*); --r1/--r2/--r3 are RADII. Re-point the reference at a token of the right kind.");
}
process.exit(1);
