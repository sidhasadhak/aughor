#!/usr/bin/env node
/**
 * check-chart-palette.mjs — the CA-4 palette gate. Two jobs:
 *
 *  1. SYNC — the chart palette lives twice by necessity (CSS tokens for the
 *     browser, TS literals for headless renderers). Parse both and fail on any
 *     drift between web/aughor-v2/theme/tokens-v2.css (--chart-1..6,
 *     --chart-deemph, --bg-2) and components/charts/echarts/palette.ts
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
const ts = readFileSync(join(root, "components/charts/echarts/palette.ts"), "utf8");

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
const tsDeemph = tsRecord("CHART_DEEMPH");
const tsSurface = tsRecord("CHART_SURFACE");

let failed = false;
const fail = (msg) => { console.error(`  ✗ ${msg}`); failed = true; };
const okay = (msg) => console.log(`  ✓ ${msg}`);

console.log("chart palette · sync (CSS tokens ↔ palette.ts)");
for (const mode of ["light", "dark"]) {
  const a = cssPal[mode].series.join(","), b = tsSeries[mode].join(",");
  a === b ? okay(`${mode} series match (${a})`) : fail(`${mode} series drift: css ${a} vs ts ${b}`);
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

if (failed) {
  console.error("\nchart palette gate FAILED — fix the tokens (both files) and re-run");
  process.exit(1);
}
console.log("\nchart palette gate passed");
