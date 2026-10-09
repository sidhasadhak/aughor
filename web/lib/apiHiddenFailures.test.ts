/**
 * A helper in `lib/api.ts` says when the API refused it — it throws with the server's own reason
 * (`refused`) — and never turns a refused response into an empty answer.
 *
 * Measured 2026-10-04: 57 helpers returned `[]`, `null`, `{}` or `false` on a non-OK response, so
 * their screens read a failed read as "nothing here" — the Documents tab's "No documents yet",
 * the feature flags vanishing from Settings, the Agent Ops roster's "no custom agents" (whose
 * "could not read" branch the helper made unreachable) — and a refused write as nothing at all.
 * 25 now throw and their screens say so; the rest are held at this count, which may only fall:
 * lower BASELINE in the change that converts one.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const HIDES = /if \(!res\.ok\) return (?:\[\]|null|\{\}|false);/g;
const BASELINE = 31;   // 32 → 31, Arc OC-4 (2026-10-09): the roster reads through getDeclaredActions, which says a refusal

function hidden(text: string): number {
  return (text.match(HIDES) ?? []).length;
}

describe("api helpers say a refusal", () => {
  it("the scan finds the pattern it guards, so it can fail", () => {
    expect(hidden("  if (!res.ok) return [];\n  if (!res.ok) return null;")).toBe(2);
    expect(hidden('  if (!res.ok) throw await refused(res, "Reading the jobs");')).toBe(0);
  });

  it("no helper hides more refused responses than it did", () => {
    const n = hidden(readFileSync(resolve("lib/api.ts"), "utf8"));
    expect(n, `${n} helpers turn a refused response into an empty answer (baseline ${BASELINE}) — `
      + "throw `refused(res, what)` instead and let the screen say it could not read").toBeLessThanOrEqual(BASELINE);
    expect(n, `the count fell to ${n} — lower BASELINE to ${n} in this file`).toBe(BASELINE);
  });
});
