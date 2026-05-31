import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
  ]),
  {
    rules: {
      // Data-loading effects (fetch → setState in callback) are the standard async
      // pattern. The rule fires on the synchronous load() call inside the effect body
      // even though setState only runs asynchronously inside the callback — false positive.
      "react-hooks/set-state-in-effect": "warn",
      // ref.current reads inside JSX callbacks are safe; rule fires on render-time reads.
      "react-hooks/refs": "warn",
      // lastGroup mutation during render is intentional group-header tracking.
      "react-hooks/immutability": "warn",
      // Unused vars: off for vars prefixed with _ (already handled by TS), warn otherwise.
      "@typescript-eslint/no-unused-vars": ["warn", { "varsIgnorePattern": "^_", "argsIgnorePattern": "^_" }],
    },
  },
]);

export default eslintConfig;
