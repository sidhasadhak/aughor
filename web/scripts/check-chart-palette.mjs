#!/usr/bin/env node
/**
 * check-chart-palette.mjs — the CA-4 palette gate. Two jobs:
 *
 *  1. SYNC — the chart palette lives twice by necessity (CSS tokens for the
 *     browser, TS literals for headless renderers). Parse both and fail on any
 *     drift between web/aughor-v2/theme/tokens-v2.css (--chart-1..6,
 *     --chart-deemph, --bg-2) and components/charts/palette.ts
 *     (CHART_SERIES / CHART_DEEMPH / CHART_SURFACE).
 *
 *  2. VALIDATE — run the six-check palette validator (validate_palette.mjs,
 *     vendored) on each mode against the app's real card surface. Any hard
 *     FAIL (lightness band, chroma floor, CVD < 6, normal-vision floor < 15)
 *     fails the gate. Contrast "relief" is reported, not failed: the finding
 *     cards ship direct labels and a table view — the documented relief rule.
 *
 * Zero dependencies, same contract as the other check-*.mjs gates.
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { validate } from "./validate_palette.mjs";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const css = readFileSync(join(root, "aughor-v2/theme/tokens-v2.css"), "utf8");
const ts = readFileSync(join(root, "components/charts/palette.ts"), "utf8");

// ── parse the CSS tokens: dark = :root block, light = [data-theme="light"] block ──
function cssBlock(afterMarker) {
  const at = css.indexOf(afterMarker);
  if (at < 0) throw new Error(`marker not found in tokens-v2.css: ${afterMarker}`);
  return css.slice(at);
}
function cssVarIn(block, name) {
  const m = block.match(new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{6})`));
  if (!m) throw new Error(`--${name} not found`);
  return m[1].toUpperCase();
}
const darkBlock = cssBlock("── DARK");
const lightBlock = cssBlock('[data-theme="light"]');
const fromCss = (block) => ({
  series: [1, 2, 3, 4, 5, 6].map((k) => cssVarIn(block, `chart-${k}`)),
  // --chart-7 is the KIND accent, not a seventh series: it stays out of `series`
  // so the chart's fold-to-Other still happens at six. Parsed and checked here
  // because a token no gate reads is a token that drifts.
  kindAccent: cssVarIn(block, "chart-7"),
  deemph: cssVarIn(block, "chart-deemph"),
  surface: cssVarIn(block, "bg-2"),
});
const cssPal = { dark: fromCss(darkBlock), light: fromCss(lightBlock) };

// ── parse the TS literals ──
function tsRecord(name) {
  const m = ts.match(new RegExp(`${name}[^=]*=\\s*{([\\s\\S]*?)};`));
  if (!m) throw new Error(`${name} not found in palette.ts`);
  const body = m[1];
  const get = (mode) => {
    const mm = body.match(new RegExp(`${mode}:\\s*(\\[[^\\]]*\\]|"#[0-9a-fA-F]{6}")`));
    if (!mm) throw new Error(`${name}.${mode} not found`);
    return (mm[1].match(/#[0-9a-fA-F]{6}/g) || []).map((h) => h.toUpperCase());
  };
  return { light: get("light"), dark: get("dark") };
}
const tsSeries = tsRecord("CHART_SERIES");
const tsKindAccent = tsRecord("CHART_KIND_ACCENT");
const tsDeemph = tsRecord("CHART_DEEMPH");
const tsSurface = tsRecord("CHART_SURFACE");

/**
 * The separation of one colour from every colour in `others`, worst case.
 *
 * Read off the validator's own two-colour report rather than by importing its
 * internals: `validate` is vendored, and a gate that reaches past a vendored
 * module's exports is a gate that breaks on its next update.
 */
function worstAgainst(colour, others, mode, surface) {
  const num = (s) => { const m = String(s).match(/(\d+\.\d+)/); return m ? +m[1] : 0; };
  let cvd = Infinity, normal = Infinity;
  for (const other of others) {
    const { report } = validate([colour, other], { mode, surface, pairs: "adjacent" });
    cvd = Math.min(cvd, num(report.find((r) => String(r[0]).includes("CVD"))?.[2]));
    normal = Math.min(normal, num(report.find((r) => String(r[0]).includes("Normal"))?.[2]));
  }
  return { cvd, normal };
}

let failed = false;
const fail = (msg) => { console.error(`  ✗ ${msg}`); failed = true; };
const okay = (msg) => console.log(`  ✓ ${msg}`);

console.log("chart palette · sync (CSS tokens ↔ palette.ts)");
for (const mode of ["light", "dark"]) {
  const a = cssPal[mode].series.join(","), b = tsSeries[mode].join(",");
  a === b ? okay(`${mode} series match (${a})`) : fail(`${mode} series drift: css ${a} vs ts ${b}`);
  const [ck, tk] = [cssPal[mode].kindAccent, tsKindAccent[mode][0]];
  ck === tk ? okay(`${mode} kind accent match (${ck})`) : fail(`${mode} kind-accent drift: css ${ck} vs ts ${tk}`);
  const [cd, td] = [cssPal[mode].deemph, tsDeemph[mode][0]];
  cd === td ? okay(`${mode} deemph match (${cd})`) : fail(`${mode} deemph drift: css ${cd} vs ts ${td}`);
  const [cs, tsf] = [cssPal[mode].surface, tsSurface[mode][0]];
  cs === tsf ? okay(`${mode} surface match (${cs})`) : fail(`${mode} surface drift: css ${cs} vs ts ${tsf}`);
}

console.log("chart palette · six checks (validate_palette.mjs)");
for (const mode of ["light", "dark"]) {
  const { report, ok } = validate(cssPal[mode].series, { mode, surface: cssPal[mode].surface });
  for (const [name, state, detail] of report) {
    const label = state === true || state === "pass" ? "PASS"
      : state === "relief" || state === "floor" ? "WARN" : "FAIL";
    console.log(`  [${label}] ${mode} · ${name} — ${detail}`);
  }
  if (!ok) fail(`${mode} palette fails the hard gates`);
}

/* The kind accent's own bar, and it is STRICTER than the one the six carry.
 *
 * The six are only required to separate ADJACENTLY — they are slots in an ordered
 * series, and a stacked bar puts neighbours together. Measured under all-pairs they
 * do not clear 6 CVD (0.7 light / 1.7 dark), and that is precisely why six is the
 * documented ceiling. A KIND accent has no such excuse: on the automation canvas
 * every kind is on screen at once, so it must stand apart from all six, not from
 * one neighbour. Grandfathering it in under the series' bar would have let a
 * seventh hue land that a reader with protanopia could not tell from the third. */
console.log("chart palette · kind accent (--chart-7) vs all six");
for (const mode of ["light", "dark"]) {
  const { series, kindAccent, surface } = cssPal[mode];
  const { cvd, normal } = worstAgainst(kindAccent, series, mode, surface);
  const band = validate([...series, kindAccent], { mode, surface, pairs: "adjacent" });
  cvd >= 6
    ? okay(`${mode} kind accent CVD vs all six: ${cvd.toFixed(1)} (>= 6)`)
    : fail(`${mode} kind accent is ${cvd.toFixed(1)} from a series colour under CVD (needs >= 6)`);
  normal >= 15
    ? okay(`${mode} kind accent normal-vision vs all six: ${normal.toFixed(1)} (>= 15)`)
    : fail(`${mode} kind accent is ${normal.toFixed(1)} from a series colour (needs >= 15)`);
  band.ok
    ? okay(`${mode} kind accent holds the band, chroma floor and surface contrast`)
    : fail(`${mode} kind accent fails a hard palette check`);
}

if (failed) {
  console.error("\nchart palette gate FAILED — fix the tokens (both files) and re-run");
  process.exit(1);
}
console.log("\nchart palette gate passed");
