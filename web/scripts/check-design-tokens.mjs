#!/usr/bin/env node
/**
 * Design-token lint gate (REC-U1).
 *
 * Fails when component/app source reintroduces a raw radius or an off-scale font size
 * instead of a design token — the enforcement half of the 3-tier design layer, the
 * same "baseline zero, blocking" discipline as the backend ruff gate.
 *
 *   Banned                              Use instead
 *   rounded-{lg,xl,2xl,3xl}[-side]      rounded-[var(--r3)]      (max 6px)
 *   rounded-full[-side]                 rounded-[var(--r-pill)]  (avatars/status dots)
 *                                       rounded-[var(--r-chip)]  (tags/badges/filters)
 *   text-[Npx] / fontSize: N            aug-fs-{xs,sm,ui,h2,h1,display,glyph}
 *
 * (Tailwind v4: the bracket must wrap var() — a bare `[--r3]` emits invalid CSS.)
 *
 * ── WHY THIS FILE GREW A SECOND RULE SHAPE ──────────────────────────────────
 * It used to match ONLY Tailwind's `text-[Npx]` bracket form, and reported "no raw
 * pixel font-size" while it was true of 12 declarations and blind to 1,261. This app
 * writes its sizes as `fontSize: 13` inside inline style objects, which the old regex
 * could not see, so 21 distinct sizes accumulated — including 9px and 10px, below the
 * 11px legibility floor type.css states, and half-pixel values (9.5, 10.5, 11.5, 12.5,
 * 13.5) that sit on no scale at all. A gate that can only see one of the two ways to
 * write the thing it forbids is worse than no gate: it reports green and is believed.
 *
 * Two rules now, because the two problems are different:
 *
 *   OFF-SCALE   is a hard failure, baseline zero. A size that is not a step cannot be
 *               argued for — the scale is the argument.
 *   RAW COUNT   is a one-way ratchet. Every remaining literal is on-scale and legible,
 *               so converting them to `aug-fs-*` classes is tidying rather than
 *               repair; it happens as files are touched, and this number only falls.
 *
 * `components/charts/echarts/` is out of scope: those numbers are ECharts spec values
 * rendered to canvas by the chart theme, not DOM type on the page.
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

/** Chart specs are chart-engine text governed by the engine's own theme/config, not DOM
 *  type on the page: ECharts renders them to canvas, Vega renders them inside its SVG.
 *  Both are sized by the chart theme the engine registers, so the page type scale does
 *  not apply. Anything in these dirs that IS page DOM must still wear an aug-fs-* class. */
const OUT_OF_SCOPE = ["components/charts/echarts", "components/charts/vega"];

/** The steps in styles/type.css. Keep the two in lockstep. */
const SCALE = new Set([11, 12, 13, 15, 18, 22, 28]);

/** One-way ratchet: raw on-scale font-size literals still awaiting an aug-fs-* class.
 *  LOWER this as they are converted; never raise it. */
const FONT_SIZE_BASELINE = 1245;

const RADIUS_RULES = [
  {
    // rounded-lg / rounded-t-xl / rounded-full etc. (optional directional segment)
    re: /\brounded(?:-(?:t|b|l|r|tl|tr|bl|br))?-(?:lg|xl|2xl|3xl|full)\b/g,
    hint: "use rounded-[var(--r3)] (or --r-pill for avatars/dots, --r-chip for tags)",
  },
];

/** Both spellings of a raw font size: the Tailwind bracket and the style object. */
const FONT_SIZE = /\btext-\[(\d+(?:\.\d+)?)px\]|\bfontSize:\s*"?(\d+(?:\.\d+)?)(?:px)?"?/g;

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
const offScale = [];
let rawFontSizes = 0;

for (const root of ROOTS) {
  for (const file of walk(join(WEB, root))) {
    const rel = relative(WEB, file);
    if (OUT_OF_SCOPE.some((d) => rel.startsWith(d))) continue;
    const lines = readFileSync(file, "utf8").split("\n");
    lines.forEach((line, i) => {
      for (const { re, hint } of RADIUS_RULES) {
        for (const m of line.matchAll(re)) {
          violations.push({ file: rel, line: i + 1, token: m[0], hint });
        }
      }
      for (const m of line.matchAll(FONT_SIZE)) {
        rawFontSizes++;
        const px = Number(m[1] ?? m[2]);
        if (!SCALE.has(px)) {
          offScale.push({ file: rel, line: i + 1, token: m[0], px });
        }
      }
    });
  }
}

let failed = false;

if (violations.length) {
  failed = true;
  console.error(`✗ design-token gate: ${violations.length} raw radius value(s)\n`);
  for (const v of violations.slice(0, 40)) {
    console.error(`  ${v.file}:${v.line}  ${v.token}\n      → ${v.hint}`);
  }
  if (violations.length > 40) console.error(`  … and ${violations.length - 40} more`);
}

if (offScale.length) {
  failed = true;
  console.error(
    `\n✗ design-token gate: ${offScale.length} off-scale font size(s). ` +
    `The scale is ${[...SCALE].join(" / ")}px — see styles/type.css.\n`);
  for (const v of offScale.slice(0, 40)) {
    console.error(`  ${v.file}:${v.line}  ${v.token}  (${v.px}px is not a step)`);
  }
  if (offScale.length > 40) console.error(`  … and ${offScale.length - 40} more`);
}

if (rawFontSizes > FONT_SIZE_BASELINE) {
  failed = true;
  console.error(
    `\n✗ design-token gate: raw font-size literals rose ${FONT_SIZE_BASELINE} → ` +
    `${rawFontSizes}. Use an aug-fs-* class (styles/type.css) rather than adding one.`);
}

if (failed) process.exit(1);

const slack = FONT_SIZE_BASELINE - rawFontSizes;
console.log(
  "✓ design-token gate: no raw radius, every font size on the " +
  `${[...SCALE].join("/")}px scale; ${rawFontSizes} raw literals ` +
  `(baseline ${FONT_SIZE_BASELINE}${slack > 0 ? `, ${slack} under — lower it` : ""}).`);
