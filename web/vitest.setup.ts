import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

/**
 * React Testing Library keeps every rendered tree in the document until it is told
 * otherwise. Without this, a component that reads `document` — a portal, a focus trap,
 * anything counting siblings — sees the previous test's DOM and the failure lands in
 * whichever test happens to run second.
 */
afterEach(() => {
  cleanup();
});

/**
 * A list keyed by something that repeats only WARNS in React ("Encountered two children with
 * the same key"): the page still renders, a row may be dropped or doubled, and the dev overlay
 * shows the error to whoever opens that screen with that data. This repo shipped that bug at
 * least seven times, fixed one field at a time. So a component test that renders a duplicate
 * key fails, whatever else it asserts. The rule and the helper: web/AGENTS.md, lib/listKeys.ts.
 */
const duplicateKeys: string[] = [];
const consoleError = console.error.bind(console);
console.error = (...args: unknown[]) => {
  if (typeof args[0] === "string" && args[0].includes("Encountered two children with the same key")) {
    duplicateKeys.push(args.map(String).join(" ").slice(0, 240));
  }
  consoleError(...args);
};
afterEach(() => {
  if (!duplicateKeys.length) return;
  const found = duplicateKeys.splice(0);
  throw new Error(
    "This test rendered a list with duplicate React keys — key it with withUniqueKeys() "
    + `(lib/listKeys.ts), or by a real id:\n${found.join("\n")}`,
  );
});

/**
 * A jsdom test that forgets to mock a fetching module does NOT fail: `getApiBase()` answers
 * `http://localhost:8000`, so the call reaches whatever platform the developer happens to be running and reads —
 * or WRITES — their live data. Measured, not theorised: a component test of the ontology map wrote a card layout
 * into the running platform's preference store before its mock existed.
 *
 * So the component project has no network. An unmocked call rejects with a sentence naming the URL and what to
 * do about it, which a component's own `.catch` handles exactly as it handles a server being down — the state
 * these tests should be asserting anyway. A test that wants a response mocks `fetch` or the module, as they do.
 */
globalThis.fetch = (async (input: RequestInfo | URL) => {
  const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
  throw new Error(
    `fetch(${url}) in a component test: this project has no network — mock the module you are calling `
    + "(vi.mock(\"@/lib/api\", …)) or `globalThis.fetch` itself. Without this, the call would reach the API "
    + "base for real.",
  );
}) as typeof fetch;
