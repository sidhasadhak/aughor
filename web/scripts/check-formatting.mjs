#!/usr/bin/env node
/**
 * Formatting-adoption gate (REC-U8).
 *
 * `lib/format.ts` is the single source of truth for number / percent / date
 * rendering. When components re-implement it (a local `toLocaleString`, a hand-rolled
 * `Intl.NumberFormat`), the same value renders "45.3K" in one surface and "45,300" in
 * another — the review's "most likely silently wrong in the UI today". This gate keeps
 * the primitives in one place, the same baseline-zero/blocking discipline as the
 * design-token gate and the backend ruff gate.
 *
 *   Banned in components/ and app/     Use instead (from @/lib/format)
 *   x.toLocaleString()                 formatCount(x)              (thousands)
 *   new Date(x).toLocaleString()       formatTimestamp(x)         (date+time)
 *   Intl.NumberFormat                  compactNumber / formatMetricValue / pct
 *   Intl.DateTimeFormat                fmtDate / formatTimestamp
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const WEB = join(fileURLToPath(new URL(".", import.meta.url)), "..");
const ROOTS = ["components", "app"];
const EXTS = [".tsx", ".ts"];

const RULES = [
  { re: /\.toLocaleString\s*\(/g, hint: "use formatCount(x) / formatTimestamp(x) from @/lib/format" },
  { re: /\bIntl\.NumberFormat\b/g, hint: "use compactNumber / formatMetricValue / pct from @/lib/format" },
  { re: /\bIntl\.DateTimeFormat\b/g, hint: "use fmtDate / formatTimestamp from @/lib/format" },
];

function* walk(dir) {
  for (const name of readdirSync(dir)) {
    if (name === "node_modules") continue;
    const p = join(dir, name);
    const st = statSync(p);
    if (st.isDirectory()) yield* walk(p);
    else if (EXTS.some((e) => p.endsWith(e))) yield p;
  }
}

const violations = [];
for (const root of ROOTS) {
  for (const file of walk(join(WEB, root))) {
    readFileSync(file, "utf8").split("\n").forEach((line, i) => {
      for (const { re, hint } of RULES) {
        for (const m of line.matchAll(re)) {
          violations.push({ file: relative(WEB, file), line: i + 1, token: m[0], hint });
        }
      }
    });
  }
}

if (violations.length === 0) {
  console.log("✓ formatting gate: all number/date rendering routes through lib/format.ts");
  process.exit(0);
}

console.error(`✗ formatting gate: ${violations.length} violation(s)\n`);
for (const v of violations) {
  console.error(`  ${v.file}:${v.line}  ${v.token.trim()}  →  ${v.hint}`);
}
console.error("\nlib/format.ts is the one home for these primitives (REC-U8).");
process.exit(1);
