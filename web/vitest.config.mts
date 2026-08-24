import { fileURLToPath } from "node:url";

import { defineConfig } from "vitest/config";

/**
 * Two projects, because the suite has two costs.
 *
 * Until now `web/` had vitest and nothing else — no jsdom, no
 * `@testing-library/react` — so 255 tests could pass while a canvas rendered ZERO
 * edges, and VA-6's whole UI had to be verified by driving a browser by hand. Every
 * UI wave paid that.
 *
 * The 255 logic tests stay in `node` and stay fast (826ms for the lot). Rendering
 * tests pay for a DOM, so they are their own project and only they load it — a single
 * jsdom environment for everything would tax every pure function in the repo for the
 * benefit of a handful of components.
 *
 * The `@` alias is declared explicitly rather than inherited. Vitest resolves
 * `tsconfig` paths on its own TODAY, with no config file present at all; the moment a
 * config exists that behaviour is worth pinning rather than relying on.
 */
const root = fileURLToPath(new URL(".", import.meta.url));
const alias = { "@": root.replace(/\/$/, "") };

export default defineConfig({
  test: {
    projects: [
      {
        resolve: { alias },
        test: {
          name: "logic",
          environment: "node",
          include: ["**/*.test.ts"],
          exclude: ["**/node_modules/**", "**/.next/**"],
        },
      },
      {
        resolve: { alias },
        test: {
          name: "components",
          environment: "jsdom",
          include: ["**/*.test.tsx"],
          exclude: ["**/node_modules/**", "**/.next/**"],
          setupFiles: ["./vitest.setup.ts"],
        },
      },
    ],
  },
});
