#!/usr/bin/env node
/**
 * Icon-system gate.
 *
 * ── WHY ──────────────────────────────────────────────────────────────────────
 * The app drew its glyphs three ways at once: `lucide-react` in 4 files,
 * `@atlaskit/icon` in 10, and 97 hand-written `<svg>` elements across 34 more —
 * including FIVE separate path maps that had each re-drawn "database", "table" and
 * "settings" a little differently. The same concept arrived at the eye as a different
 * shape depending on which screen you were on, and nothing anywhere answered "which
 * glyph means catalog".
 *
 * One set now (Tabler), imported in exactly one file. This gate keeps it that way.
 *
 * ── THE TWO RULES ────────────────────────────────────────────────────────────
 *   THIRD-PARTY SETS   Baseline zero, hard fail. A second icon package is not a
 *                      gradual problem — it is one import, and the fix is one import.
 *   INLINE <svg>       Baseline zero in scope, hard fail. Anything that is a GLYPH
 *                      goes through <Icon>; anything that is a DRAWING is listed
 *                      below by name, with the reason it is not an icon.
 *
 * A drawing is not an icon: chart marks, graph edges, a sparkline's path and a
 * vendor's logo are content, geometry or a trademark, and no icon set supplies them.
 * They are enumerated rather than pattern-matched so that adding one is a decision
 * somebody makes on purpose, in this file, with a reason beside it.
 *
 * No dependencies. Run via `npm run lint:icons`; wired into CI as a blocking job.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const WEB = join(fileURLToPath(new URL(".", import.meta.url)), "..");
const ROOTS = ["components", "app"];
const EXTS = [".tsx", ".ts"];

/** The one file allowed to name an icon package. */
const ICON_MODULE = "components/ui/icon.tsx";

/** Files whose `<svg>` is a drawing, not a glyph — each with why. */
const DRAWINGS = {
  "components/BrandLogos.tsx":      "vendor trademarks — Snowflake, Stripe, Postgres et al",
  "components/OntologyCanvas.tsx":  "graph edges and node geometry, computed per layout",
  "components/ERDiagram.tsx":       "relationship edges between table cards",
  "components/ProcessMapper.tsx":   "the process map itself — nodes, edges, hit areas",
  "components/brief/Sparkline.tsx": "the sparkline path, area fill and end dot",
  "components/DomainIntelPanel.tsx":"an empty-state illustration of a linked network",
};

/** Icon packages that must not reappear. */
const BANNED = [/from\s+["']lucide-react["']/, /from\s+["']@atlaskit\/icon/];

function* walk(dir) {
  for (const name of readdirSync(dir)) {
    if (name === "node_modules") continue;
    const p = join(dir, name);
    const st = statSync(p);
    if (st.isDirectory()) yield* walk(p);
    else if (EXTS.some((e) => p.endsWith(e))) yield p;
  }
}

const thirdParty = [];
const inlineSvg = [];

for (const root of ROOTS) {
  for (const file of walk(join(WEB, root))) {
    const rel = relative(WEB, file);
    if (rel === ICON_MODULE) continue;
    const lines = readFileSync(file, "utf8").split("\n");
    lines.forEach((line, i) => {
      for (const re of BANNED) {
        if (re.test(line)) thirdParty.push({ file: rel, line: i + 1, text: line.trim() });
      }
      if (line.includes("<svg") && !DRAWINGS[rel]) {
        inlineSvg.push({ file: rel, line: i + 1 });
      }
    });
  }
}

let failed = false;

if (thirdParty.length) {
  failed = true;
  console.error(`✗ icon gate: ${thirdParty.length} import(s) from a second icon set\n`);
  for (const v of thirdParty.slice(0, 20)) {
    console.error(`  ${v.file}:${v.line}  ${v.text}`);
  }
  console.error(`\n      → import { Icon } from "@/components/ui/icon" and add a role there.`);
}

if (inlineSvg.length) {
  failed = true;
  console.error(`\n✗ icon gate: ${inlineSvg.length} hand-drawn <svg> glyph(s)\n`);
  for (const v of inlineSvg.slice(0, 30)) console.error(`  ${v.file}:${v.line}`);
  if (inlineSvg.length > 30) console.error(`  … and ${inlineSvg.length - 30} more`);
  console.error(
    `\n      → a GLYPH becomes <Icon name="…" /> (add the role to ${ICON_MODULE}).\n` +
    `        a DRAWING — chart marks, graph edges, a logo — goes in this gate's\n` +
    `        DRAWINGS list with the reason it is not an icon.`);
}

if (failed) process.exit(1);

console.log(
  `✓ icon gate: one icon set (Tabler, via ${ICON_MODULE}); ` +
  `no third-party imports, no hand-drawn glyphs ` +
  `(${Object.keys(DRAWINGS).length} files hold drawings, listed by name).`);
