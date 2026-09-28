/**
 * cockpit-validate-entry.ts — the cockpit's rules, run on the server (Arc CT, CT-2).
 *
 * Bundled by `npm run build:cockpit-validate` into `aughor/cockpit/validate.bundle.mjs` and
 * run by `aughor/cockpit/validate.py` as a node subprocess — the arrangement the chart
 * renderer already uses, for the same reason: the server checks a spec with the SAME
 * function the browser draws it with, so the two cannot come to disagree.
 *
 * Reads one JSON payload from stdin and writes one to stdout:
 *   { "op": "check", "spec": … }   → { valid, issues: [{ code, message, elementKey? }],
 *                                       cards, stateCards, texts }
 *   { "op": "vocabulary" }         → { version, components, tones, range_statuses,
 *                                       card_statuses, limits }
 *
 * It exits non-zero on anything it does not understand, and the server treats that as
 * "could not check", never as "accepted".
 */
import { checkCockpitSpec, vocabulary } from "@/lib/cockpit/rules";

async function main(): Promise<void> {
  const chunks: Buffer[] = [];
  for await (const c of process.stdin) chunks.push(c as Buffer);
  const payload = JSON.parse(Buffer.concat(chunks).toString("utf8")) as { op?: string; spec?: unknown };
  if (payload.op === "vocabulary") {
    process.stdout.write(JSON.stringify(vocabulary()));
    return;
  }
  if (payload.op === "check") {
    process.stdout.write(JSON.stringify(checkCockpitSpec(payload.spec)));
    return;
  }
  throw new Error(`unknown op ${JSON.stringify(payload.op)}`);
}

main().catch((e) => {
  process.stderr.write(`cockpit-validate: ${String(e)}\n`);
  process.exit(1);
});
