// @vitest-environment jsdom

/**
 * The Briefing asks for its brief when it MOUNTS — `POST /exploration/{conn}/briefing`, which the
 * server answers from its cache or by writing a narrative (a model call on a miss or a stale entry).
 * A mount nobody asked for is spend nobody asked for, so these tests count that request.
 *
 * Measured on a stub API before the fix, for a connection that declares no schema: every re-render
 * of the shell posted the brief again — opening ⌘K, a nav count landing, switching to Profile — with
 * the Briefing on screen or kept alive behind another layer. The shell builds `connections` afresh on
 * every render, the schema effect was keyed on that array, and each re-run re-gated the scope: the
 * Briefing swapped out for its "Reading this connection's schemas…" state and back in, and a Briefing
 * that mounts again asks again.
 */
import { act, render, screen, waitFor } from "@testing-library/react";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { IntelligenceWorkspace, type IntelLayer } from "@/components/IntelligenceWorkspace";
import { generateBriefingNarrative, getCatalogTree } from "@/lib/api";

// Every async call in the API module stays pending unless a test answers it, so the real
// BriefingPanel renders its loading state and nothing reaches the no-network guard. Synchronous
// helpers keep their real implementations.
vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return Object.fromEntries(Object.entries(actual).map(([name, value]) => [
    name,
    typeof value === "function" && value.constructor.name === "AsyncFunction"
      ? vi.fn(() => new Promise(() => {}))
      : value,
  ]));
});
// jsdom has no EventSource.
vi.mock("@/lib/events", () => ({ subscribeKernelEvents: () => () => {} }));
// Profile is the layer being looked at, not the subject: a stand-in that fetches nothing.
vi.mock("@/components/ProfilePanel", () => ({ ProfilePanel: () => <p>Profile layer</p> }));

const CONN = "c1";
const noop = () => {};

/** The workspace as the shell renders it — with a NEW `connections` array each time, the way
 *  `app/page.tsx` builds it (`wsConnections.filter(…).map(…)`) on every one of its renders. */
function shell(layer: IntelLayer, schemaName: string | null = null) {
  return (
    <IntelligenceWorkspace
      connectionId={CONN}
      layer={layer}
      onLayerChange={noop}
      onInvestigate={noop}
      connections={[{ id: CONN, name: "Warehouse", schema_name: schemaName }]}
      workspaceId="default"
    />
  );
}

/** Let every answered request land, and whatever it renders mount, before counting. */
async function settle() {
  for (let i = 0; i < 5; i++) {
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)); });
  }
}

// The Briefing is a large module graph behind a lazy layer. Pay its first import here: inside the
// first test it outlasted the wait for the brief, and that test failed on loading, not on behaviour.
beforeAll(async () => {
  await import("@/components/BriefingPanel");
}, 60_000);

beforeEach(() => {
  vi.mocked(getCatalogTree).mockReset().mockResolvedValue({
    sections: [{
      id: "connections", label: "Connections",
      entries: [{
        conn_id: CONN, name: "Warehouse", conn_type: "bigquery", builtin: false,
        schemas: [{ name: "sales", tables: [] }, { name: "ops", tables: [] }],
      }],
    }],
  });
  vi.mocked(generateBriefingNarrative).mockReset().mockResolvedValue({
    narrative: "", headline_theme: "", citations: [], generated_at: null, available: false,
  });
});

describe("IntelligenceWorkspace — the Briefing asks for its brief only when it is opened", () => {
  it("never mounts the Briefing when the workspace opens on Profile, however often the shell re-renders", async () => {
    const { rerender } = render(shell("hub"));
    await screen.findByText("Profile layer");
    for (let i = 0; i < 3; i++) {
      rerender(shell("hub"));
      await settle();
    }
    expect(generateBriefingNarrative).not.toHaveBeenCalled();
  });

  it("asks once for an opened Briefing, through shell re-renders and a switch to Profile", async () => {
    const { rerender } = render(shell("briefing"));
    await waitFor(() => expect(generateBriefingNarrative).toHaveBeenCalledTimes(1), { timeout: 5_000 });
    expect(generateBriefingNarrative).toHaveBeenLastCalledWith(CONN, false, "sales", "default");

    rerender(shell("briefing"));   // the shell re-renders: ⌘K opens, a nav count lands
    await settle();
    rerender(shell("hub"));        // the user switches to Profile; the Briefing stays mounted behind it
    await screen.findByText("Profile layer");
    await settle();
    rerender(shell("hub"));        // and the shell re-renders again
    await settle();

    expect(generateBriefingNarrative).toHaveBeenCalledTimes(1);
    // The scope was resolved once. A re-render is no reason to re-read the catalog tree, which
    // opens every connection.
    expect(getCatalogTree).toHaveBeenCalledTimes(1);
  });

  it("briefs a connection that declares its schema on that schema, without reading the catalog", async () => {
    const { rerender } = render(shell("briefing", "sales"));
    await waitFor(() => expect(generateBriefingNarrative).toHaveBeenCalledTimes(1), { timeout: 5_000 });
    rerender(shell("briefing", "sales"));
    await settle();

    expect(generateBriefingNarrative).toHaveBeenCalledTimes(1);
    expect(generateBriefingNarrative).toHaveBeenLastCalledWith(CONN, false, "sales", "default");
    expect(getCatalogTree).not.toHaveBeenCalled();
  });
});
