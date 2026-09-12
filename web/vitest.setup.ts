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
