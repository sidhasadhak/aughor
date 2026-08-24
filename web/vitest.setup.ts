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
