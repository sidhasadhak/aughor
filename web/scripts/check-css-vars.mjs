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
const DEF_RE = /(--[a-zA-Z0-9-]+)\s*:/g;
for (const root of CSS_ROOTS) {
  for (const file of walk(join(WEB, root), [".css"])) {
    for (const m of readFileSync(file, "utf8").matchAll(DEF_RE)) defined.add(m[1]);
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

if (orphans.length === 0) {
  console.log(`✓ css-var gate: every var(--…) reference resolves to a defined token (${defined.size} tokens known)`);
  process.exit(0);
}
console.error(`✗ css-var gate: ${orphans.length} reference(s) to undefined custom properties\n`);
for (const o of orphans) console.error(`  ${o.file}:${o.line}  var(${o.name})`);
console.error("\nDefine the token in styles/tokens.css | aughor-v2/theme/tokens-v2.css, or re-point the reference at an existing token.");
process.exit(1);
