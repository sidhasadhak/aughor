/**
 * React list keys are identities, not kinds (the rule: web/AGENTS.md).
 *
 * Two halves here. `withUniqueKeys` itself, and a ratchet over the source: a bare key read off
 * a field that names a KIND or a DISPLAY TEXT (`key={phase.phase_id}`, `key={m.name}`) collides
 * the moment the data repeats one — a report with two `decomposition` phases, an aggregate with
 * one metric name twice. That count may fall, never rise; new code keys such a list with
 * `withUniqueKeys`. The runtime half lives in vitest.setup.ts: a component test that renders a
 * duplicate key fails.
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative, resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { withUniqueKeys } from "./listKeys";

describe("withUniqueKeys", () => {
  const keysOf = (xs: string[]) => withUniqueKeys(xs, x => x).map(([k]) => k);

  it("keeps the natural key when nothing repeats", () => {
    expect(keysOf(["baseline", "decomposition"])).toEqual(["baseline", "decomposition"]);
  });

  it("gives a repeat its own key, and every key stays unique", () => {
    expect(keysOf(["decomposition", "baseline", "decomposition", "decomposition"]))
      .toEqual(["decomposition", "baseline", "decomposition#2", "decomposition#3"]);
  });

  it("never reuses a suffix the list already carries", () => {
    const keys = keysOf(["a#2", "a", "a"]);
    expect(new Set(keys).size).toBe(3);
  });

  it("pairs each item with its key, in order", () => {
    const phases = [{ phase_id: "decomposition", n: 1 }, { phase_id: "decomposition", n: 2 }];
    expect(withUniqueKeys(phases, p => p.phase_id).map(([key, p]) => `${key}:${p.n}`))
      .toEqual(["decomposition:1", "decomposition#2:2"]);
  });
});

/** Fields that name a kind, a category or a display text. Keying a data list by one of these,
 *  bare, is how the duplicate-key errors in this repo started. */
const NOT_AN_IDENTITY = [
  "phase_id", "phase", "kind", "type", "domain", "category", "status", "role", "level",
  "severity", "mode", "stage", "format", "source", "group", "section", "tier", "verdict",
  "state", "angle", "name", "label", "title",
];
const BARE_KIND_KEY = new RegExp(`key=\\{[A-Za-z_$][\\w$]*\\.(?:${NOT_AN_IDENTITY.join("|")})\\}`, "g");

/** Measured 2026-09-26, after the three `phase_id` lists were keyed with `withUniqueKeys`.
 *  One-way: when you convert one, lower this; never raise it. */
const BASELINE = 60;

function bareKindKeys(text: string): string[] {
  return text.match(BARE_KIND_KEY) ?? [];
}

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap(name => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return name === "node_modules" || name.startsWith(".") ? [] : sourceFiles(path);
    return path.endsWith(".tsx") && !path.endsWith(".test.tsx") ? [path] : [];
  });
}

describe("React list keys are identities, not kinds", () => {
  it("the scan finds the pattern it guards, so it can fail", () => {
    expect(bareKindKeys("{phases.map(phase => <PhaseSection key={phase.phase_id} />)}")).toHaveLength(1);
    expect(bareKindKeys("{metrics.map(m => <Row key={m.name} />)}")).toHaveLength(1);
    expect(bareKindKeys("{rows.map(r => <Row key={r.id} />)}")).toHaveLength(0);
    expect(bareKindKeys("{withUniqueKeys(ps, p => p.phase_id).map(([key, p]) => <Row key={key} />)}"))
      .toHaveLength(0);
  });

  it(`no list is newly keyed by a kind or a display text (baseline ${BASELINE})`, () => {
    // From the vitest root (`web/`), not `__dirname` — that is undefined under ESM.
    const root = resolve(".");
    const hits = ["app", "components", "lib"].flatMap(dir => sourceFiles(resolve(dir))).flatMap(file =>
      readFileSync(file, "utf8").split("\n").flatMap((line, i) =>
        bareKindKeys(line).map(hit => `${relative(root, file)}:${i + 1}: ${hit}`)));
    expect(hits.length, hits.length > BASELINE
      ? "A kind or a display text is not an identity — key these lists with withUniqueKeys() "
        + `(lib/listKeys.ts), or by a real id:\n${hits.join("\n")}`
      : `The count fell to ${hits.length} — lower BASELINE to match, so it cannot rise back.`,
    ).toBe(BASELINE);
  });
});
