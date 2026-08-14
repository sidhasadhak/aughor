/**
 * Vitest config — CI-1d.
 *
 * `web/` had no test runner, which is how the C1 adapter sat untested for two
 * weeks. Node 24 strips TS types natively but will not resolve the extensionless
 * imports the app is written with, so a runner with bundler-style resolution is
 * the smallest thing that works.
 *
 * `.mts`, not `.ts`: this package is CommonJS (no `"type": "module"`, and adding
 * one would change resolution for the whole app), so Vite's native config loader
 * warns that ESM syntax is being loaded as CJS — a warning that becomes an error
 * in a future major. The explicit module extension settles it locally.
 *
 * The `@/*` alias is duplicated from `tsconfig.json` rather than read from it:
 * vitest does not consult tsconfig paths on its own, and a test that cannot
 * resolve an import fails as "Cannot find package", which reads like a missing
 * dependency rather than a missing alias.
 */

import { fileURLToPath } from "node:url";

import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: {
    alias: { "@": fileURLToPath(new URL("./", import.meta.url)) },
  },
  test: {
    // Co-located with the code they test — the repo has no __tests__ convention.
    include: ["**/*.test.ts", "**/*.test.tsx"],
    exclude: ["node_modules/**", ".next/**"],
  },
});
