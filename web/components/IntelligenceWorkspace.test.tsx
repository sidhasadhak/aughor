// @vitest-environment jsdom

/**
 * The Briefing READS its edition when it MOUNTS — it opens on the Week and reads the edition last written
 * for the person's reader (`GET /exploration/{conn}/briefing/edition`) — and writes one only on a click
 * (Arc BG, §6 item 58: opening never spends). Until 2026-10-29 a mount with nothing built POSTed a build,
 * a model call nobody asked for; these tests count the read, and that no write follows it.
 *
 * Measured on a stub API before the fix, for a connection that declares no schema: every re-render
 * of the shell posted the brief again — opening ⌘K, a nav count landing, switching to Profile — with
 * the Briefing on screen or kept alive behind another layer. The shell builds `connections` afresh on
 * every render, the schema effect was keyed on that array, and each re-run re-gated the scope: the
 * Briefing swapped out for its "Reading this connection's schemas…" state and back in, and a Briefing
 * that mounts again asks again.
 */
import { act, render, screen, waitFor, change } from "@/lib/testing";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { IntelligenceWorkspace, type IntelLayer } from "@/components/IntelligenceWorkspace";
import { buildRangeBriefing, getCatalogTree, readBriefingEdition, readBriefingGuide, readRangeBriefing, writeBriefingEdition } from "@/lib/api";

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
  await import("@/components/brief/BriefingEdition");
  // The Profile layer imports pieces of the earlier Briefing panel (its evidence drawer); pay that graph too.
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
  // The Day's Briefing is not built yet, so the panel asks for one: the request that can spend.
  vi.mocked(readRangeBriefing).mockReset().mockResolvedValue({
    narrative: "", headline_theme: "", citations: [], generated_at: null, available: false, built: false,
  });
  vi.mocked(buildRangeBriefing).mockReset().mockResolvedValue({
    narrative: "", headline_theme: "", citations: [], generated_at: null, available: false,
  });
  // The Week's edition is not written yet: the page says so and waits for a click.
  vi.mocked(readBriefingEdition).mockReset().mockResolvedValue({ built: false, scope_key: CONN, period: {} as never, reader: "" });
  vi.mocked(readBriefingGuide).mockReset().mockResolvedValue({
    available: false, guide: null, version: null, editions_read: null, published_version: null, versions: [] });
  vi.mocked(writeBriefingEdition).mockReset();
});

const WEEK = { preset: "last_week" };

describe("IntelligenceWorkspace — the Briefing asks for its brief only when it is opened", () => {
  it("never mounts the Briefing when the workspace opens on Profile, however often the shell re-renders", async () => {
    const { rerender } = render(shell("hub"));
    await screen.findByText("Profile layer");
    for (let i = 0; i < 3; i++) {
      rerender(shell("hub"));
      await settle();
    }
    expect(readRangeBriefing).not.toHaveBeenCalled();
    expect(buildRangeBriefing).not.toHaveBeenCalled();
  });

  it("reads once for an opened Briefing, through shell re-renders and a switch to Profile, and never writes", async () => {
    const { rerender } = render(shell("briefing"));
    await waitFor(() => expect(readBriefingEdition).toHaveBeenCalledTimes(1), { timeout: 5_000 });
    expect(readBriefingEdition).toHaveBeenLastCalledWith(CONN, WEEK, undefined, "sales", "default", undefined);

    rerender(shell("briefing"));   // the shell re-renders: ⌘K opens, a nav count lands
    await settle();
    rerender(shell("hub"));        // the user switches to Profile; the Briefing stays mounted behind it
    await screen.findByText("Profile layer");
    await settle();
    rerender(shell("hub"));        // and the shell re-renders again
    await settle();

    expect(readBriefingEdition).toHaveBeenCalledTimes(1);
    expect(writeBriefingEdition).not.toHaveBeenCalled();
    expect(buildRangeBriefing).not.toHaveBeenCalled();
    // The scope was resolved once. A re-render is no reason to re-read the catalog tree, which
    // opens every connection.
    expect(getCatalogTree).toHaveBeenCalledTimes(1);
  });

  it("briefs a connection that declares its schema on that schema, without reading the catalog", async () => {
    const { rerender } = render(shell("briefing", "sales"));
    await waitFor(() => expect(readBriefingEdition).toHaveBeenCalledTimes(1), { timeout: 5_000 });
    rerender(shell("briefing", "sales"));
    await settle();

    expect(readBriefingEdition).toHaveBeenCalledTimes(1);
    expect(readBriefingEdition).toHaveBeenLastCalledWith(CONN, WEEK, undefined, "sales", "default", undefined);
    expect(writeBriefingEdition).not.toHaveBeenCalled();
    expect(getCatalogTree).not.toHaveBeenCalled();
  });
});


describe("IntelligenceWorkspace — the Dashboards tab, beside the Briefing (Arc CT-7)", () => {
  // By the name a person hears: a Radix tab holds its label twice (one hidden, for its width).
  const tabs = () => screen.getAllByRole("tab").map(t => t.querySelector(".rt-TabsTriggerInner")?.textContent?.trim());
  it("is there right after the Briefing, and opening it asks for no brief", async () => {
    render(shell("dashboards"));
    await waitFor(() => expect(tabs()).toContain("Dashboards"));
    expect(tabs().slice(0, 2)).toEqual(["Briefing", "Dashboards"]);
    await settle();
    expect(readRangeBriefing).not.toHaveBeenCalled();
    expect(buildRangeBriefing).not.toHaveBeenCalled();
  });

  it("a canvas's Briefing is the edition page, reading the canvas's own edition and never writing", async () => {
    render(<IntelligenceWorkspace connectionId={CONN} layer="briefing" onLayerChange={noop} onInvestigate={noop}
      canvasId="cv1" workspaceId="default" />);
    await waitFor(() => expect(readBriefingEdition).toHaveBeenCalledTimes(1), { timeout: 5_000 });
    expect(vi.mocked(readBriefingEdition).mock.calls[0].at(-1)).toBe("cv1");
    expect(await screen.findByTestId("briefing-edition")).toBeTruthy();
    expect(writeBriefingEdition).not.toHaveBeenCalled();
    expect(readRangeBriefing).not.toHaveBeenCalled();
  });

  it("is not there for a canvas, which is for questions and deep analysis, and a link to it opens the Briefing", async () => {
    const onLayerChange = vi.fn();
    render(<IntelligenceWorkspace connectionId={CONN} layer="dashboards" onLayerChange={onLayerChange} onInvestigate={noop}
      canvasId="cv1" workspaceId="default" />);
    await waitFor(() => expect(onLayerChange).toHaveBeenCalledWith("briefing"));
    expect(tabs()).not.toContain("Dashboards");
  });
});
