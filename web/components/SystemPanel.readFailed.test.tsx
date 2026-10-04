// @vitest-environment jsdom
/**
 * A failed stats read kept the whole System tab on "Loading stats…" for good — hiding the
 * Backend section, the one place a person points this browser at a reachable API, and the
 * feature flags (which, read on their own and failing, vanished: `{}` returned null). Both
 * failures are said, with a Retry, and the sections that need no stats still draw.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// Every read the tab makes is stubbed: an unmocked one would reach the live API from jsdom.
vi.mock("@/lib/api", async importOriginal => {
  const actual = await importOriginal<Record<string, unknown>>();
  return {
    ...actual,
    getDevStats: () => Promise.reject(new Error("Failed to fetch")),
    getSystemFlags: () => Promise.reject(new Error("Failed to fetch")),
    getEvalGraduations: () => Promise.resolve([]),
    getPacks: () => Promise.resolve({ enabled: false, packs: [] }),
    getPackDeltas: () => Promise.resolve([]),
    getConnections: () => Promise.resolve([]),
    getCatalogTree: () => Promise.resolve({ sections: [] }),
  };
});
vi.mock("@/lib/events", () => ({ subscribeKernelEvents: () => () => {} }));

import { SystemPanel } from "./SystemPanel";

describe("SystemPanel — a backend it cannot reach", () => {
  it("says the stats and the flags could not be read, and keeps the backend section", async () => {
    render(<SystemPanel />);

    expect(await screen.findByText(/Could not read the system stats — Failed to fetch/)).toBeInTheDocument();
    expect(await screen.findByText(/Could not read the feature flags — Failed to fetch/)).toBeInTheDocument();
    expect(screen.getByText("Backend")).toBeInTheDocument();
    expect(screen.queryByText(/Loading stats/)).not.toBeInTheDocument();
  });
});
