#!/usr/bin/env node
/**
 * Raw-element ratchet (REC-U2).
 *
 * The app has a token-based primitive layer (components/ui/*), but 204 raw
 * `<button>` elements were hand-styled before it existed. Retro-fitting all of them
 * to <Button> is a per-button design job (variant inference; a blind codemod would
 * add the default `bg-primary` and break custom styling — the review's own failure
 * mode), so instead this gate FREEZES the drift: it fails if the raw-`<button>` count
 * grows past the baseline. Convert buttons to <Button> opportunistically and lower
 * BASELINE — a one-way ratchet, exactly like the backend ruff/silent-swallow ratchets.
 *
 * Not a boolean gate (like the token/format gates) — a monotone-decreasing budget.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const WEB = join(fileURLToPath(new URL(".", import.meta.url)), "..");
const ROOTS = ["components", "app"];
const EXTS = [".tsx", ".ts"];

// One-way ratchet. LOWER this as raw <button>s become <Button>; never raise it.
const BASELINE = 183;

const RAW_BUTTON = /<button[ >]/g;

function* walk(dir) {
  for (const name of readdirSync(dir)) {
    if (name === "node_modules") continue;
    const p = join(dir, name);
    const st = statSync(p);
    if (st.isDirectory()) yield* walk(p);
    else if (EXTS.some((e) => p.endsWith(e))) yield p;
  }
}

let count = 0;
const perFile = [];
for (const root of ROOTS) {
  for (const file of walk(join(WEB, root))) {
    const n = (readFileSync(file, "utf8").match(RAW_BUTTON) || []).length;
    if (n) {
      count += n;
      perFile.push({ file: relative(WEB, file), n });
    }
  }
}

if (count <= BASELINE) {
  const slack = BASELINE - count;
  console.log(
    `✓ raw-element ratchet: ${count} raw <button> (baseline ${BASELINE}` +
      (slack ? `; ${slack} under — lower BASELINE to ${count}` : "") +
      "). Prefer <Button> from components/ui/button.",
  );
  process.exit(0);
}

console.error(
  `✗ raw-element ratchet: ${count} raw <button> exceeds baseline ${BASELINE} ` +
    `(+${count - BASELINE}). New buttons must use <Button> (components/ui/button), not a raw <button>.`,
);
perFile.sort((a, b) => b.n - a.n);
for (const { file, n } of perFile.slice(0, 15)) console.error(`  ${n.toString().padStart(3)}  ${file}`);
process.exit(1);
