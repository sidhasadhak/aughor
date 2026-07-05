#!/usr/bin/env node
/**
 * Design-token lint gate (REC-U1).
 *
 * Fails when component/app source reintroduces a raw radius or raw pixel font-size
 * instead of a design token — the enforcement half of the 3-tier design layer, the
 * same "baseline zero, blocking" discipline as the backend ruff gate.
 *
 *   Banned                              Use instead
 *   rounded-{lg,xl,2xl,3xl}[-side]      rounded-[var(--r3)]      (max 6px)
 *   rounded-full[-side]                 rounded-[var(--r-pill)]  (pills/avatars/dots)
 *   text-[Npx]                          aug-fs-{xs,sm,ui,h2,h1,display} or aug-text-*
 *
 * (Tailwind v4: the bracket must wrap var() — a bare `[--r3]` emits invalid CSS.)
 *
 * No dependencies — walks the tree and regex-scans className-bearing source. Run via
 * `npm run lint:tokens`; wired into CI as a blocking job.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const WEB = join(fileURLToPath(new URL(".", import.meta.url)), "..");
const ROOTS = ["components", "app"];
const EXTS = [".tsx", ".ts"];

const RULES = [
  {
    // rounded-lg / rounded-t-xl / rounded-full etc. (optional directional segment)
    re: /\brounded(?:-(?:t|b|l|r|tl|tr|bl|br))?-(?:lg|xl|2xl|3xl|full)\b/g,
    hint: "use rounded-[var(--r3)] (or rounded-[var(--r-pill)] for pills/avatars)",
  },
  {
    re: /\btext-\[\d+px\]/g,
    hint: "use an aug-fs-* size token (xs/sm/ui/h2/h1/display) — see styles/type.css",
  },
];

function* walk(dir) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (name === "node_modules") continue;
    const st = statSync(p);
    if (st.isDirectory()) yield* walk(p);
    else if (EXTS.some((e) => p.endsWith(e))) yield p;
  }
}

const violations = [];
for (const root of ROOTS) {
  for (const file of walk(join(WEB, root))) {
    const lines = readFileSync(file, "utf8").split("\n");
    lines.forEach((line, i) => {
      for (const { re, hint } of RULES) {
        for (const m of line.matchAll(re)) {
          violations.push({ file: relative(WEB, file), line: i + 1, token: m[0], hint });
        }
      }
    });
  }
}

if (violations.length === 0) {
  console.log("✓ design-token gate: no raw radius / pixel font-size in components/ or app/");
  process.exit(0);
}

console.error(`✗ design-token gate: ${violations.length} violation(s)\n`);
for (const v of violations) {
  console.error(`  ${v.file}:${v.line}  ${v.token}  →  ${v.hint}`);
}
console.error(
  "\nThe token scale is the single source of truth (REC-U1). " +
    "Fix the sites above or, for a genuinely new size, extend styles/type.css | tokens.css.",
);
process.exit(1);
