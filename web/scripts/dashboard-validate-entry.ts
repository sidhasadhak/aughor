/**
 * dashboard-validate-entry.ts — the cockpit's rules, run on the server (Arc CT, CT-2).
 *
 * Bundled by `npm run build:dashboard-validate` into `aughor/cockpit/validate.bundle.mjs` and
 * run by `aughor/cockpit/validate.py` as a node subprocess — the arrangement the chart
 * renderer already uses, for the same reason: the server checks a spec with the SAME
 * function the browser draws it with, so the two cannot come to disagree.
 *
 * Reads one JSON payload from stdin and writes one to stdout:
 *   { "op": "check", "spec": … }   → { valid, issues: [{ code, message, elementKey? }],
 *                                       cards, stateCards, texts }
 *   { "op": "vocabulary" }         → { version, components, tones, range_statuses,
 *                                       card_statuses, limits }
 *   { "op": "patch", "spec": …,    → { ok, spec, issues: [{ index, message }] } — the edit
 *     "patches": [ … ] }              applied strictly, all or nothing (CT-5). The result is
 *                                     NOT checked here; the caller sends it back as a "check".
 *   { "op": "wiring", "spec": … }  → { sets, buttons } — each set as the object door would read it, each
 *                                     button's parameters with their source's kind and entity (Arc AP-2/3)
 *   { "op": "grammar",             → { text } — what the writer of a cockpit is told (CT-5); the
 *     "grid": bool }                   grid only while cockpits are built in place (Arc AP-1)
 *
 * It exits non-zero on anything it does not understand, and the server treats that as
 * "could not check", never as "accepted".
 */
import { grammar } from "@/lib/dashboards/grammar";
import { applyDashboardPatches } from "@/lib/dashboards/patch";
import { checkDashboardSpec, vocabulary } from "@/lib/dashboards/rules";
import { wiring, type WireSpec } from "@/lib/dashboards/sets";

async function main(): Promise<void> {
  const chunks: Buffer[] = [];
  for await (const c of process.stdin) chunks.push(c as Buffer);
  const payload = JSON.parse(Buffer.concat(chunks).toString("utf8")) as
    { op?: string; spec?: unknown; patches?: unknown; grid?: boolean; structure?: boolean };
  if (payload.op === "vocabulary") {
    process.stdout.write(JSON.stringify(vocabulary()));
    return;
  }
  if (payload.op === "check") {
    process.stdout.write(JSON.stringify(checkDashboardSpec(payload.spec)));
    return;
  }
  if (payload.op === "patch") {
    process.stdout.write(JSON.stringify(applyDashboardPatches(payload.spec, payload.patches)));
    return;
  }
  if (payload.op === "wiring") {
    process.stdout.write(JSON.stringify(wiring(payload.spec as WireSpec)));
    return;
  }
  if (payload.op === "grammar") {
    process.stdout.write(JSON.stringify({ text: grammar({ grid: payload.grid === true, structure: payload.structure === true }) }));
    return;
  }
  throw new Error(`unknown op ${JSON.stringify(payload.op)}`);
}

main().catch((e) => {
  process.stderr.write(`dashboard-validate: ${String(e)}\n`);
  process.exit(1);
});
