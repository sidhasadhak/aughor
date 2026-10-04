/**
 * Arc UI — a loading state is the design system's `<Loading what=…>`, never a hand-rolled line.
 *
 * Measured 2026-10-04 before the sweep: 37 "Loading…" lines across 26 components, in five font
 * sizes and two greys (three in a hard-coded Tailwind zinc), none announced to assistive tech and
 * most not saying WHAT was loading. They are now `<Loading>` (components/ui/states.tsx), and this
 * scan keeps a new one from being written. The one shape allowed is an `<option>` label, which
 * can hold only text.
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";

const BARE_LOADING = />\s*Loading(?: [a-z][^<{]*)?(?:…|\.\.\.)?\s*</;
const ALLOWED = /<option\b[^>]*>\s*Loading/;

function bareLoading(text: string): string[] {
  return text.split("\n").filter(line => BARE_LOADING.test(line) && !ALLOWED.test(line));
}

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap(name => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return name === "node_modules" || name.startsWith(".") ? [] : sourceFiles(path);
    return path.endsWith(".tsx") && !path.endsWith(".test.tsx") ? [path] : [];
  });
}

describe("loading states are the design system's", () => {
  it("the scan finds the pattern it guards, so it can fail", () => {
    expect(bareLoading('{loading && <p style={{ color: "var(--t3)" }}>Loading…</p>}')).toHaveLength(1);
    expect(bareLoading('<div className="aug-fs-sm">Loading agents…</div>')).toHaveLength(1);
    expect(bareLoading('{loading && <Loading what="agents" />}')).toHaveLength(0);
    expect(bareLoading('<option disabled>Loading…</option>')).toHaveLength(0);
  });

  it("no component draws its own loading line", () => {
    const root = resolve(".");
    const hits = ["app", "components", "lib"].flatMap(dir => sourceFiles(resolve(dir)))
      .filter(file => !file.endsWith(join("components", "ui", "states.tsx")))
      .flatMap(file => bareLoading(readFileSync(file, "utf8")).map(l => `${file.slice(root.length + 1)}: ${l.trim()}`));
    expect(hits, `use <Loading what="…"> from components/ui/states:\n${hits.join("\n")}`).toEqual([]);
  });
});
