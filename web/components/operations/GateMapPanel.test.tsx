// @vitest-environment jsdom
/**
 * The gate map and the policies, redone to CLARITY.md. The gate map is a map, so it opens on the picture — the places
 * in the code, the doors they go through, the warehouse; and what leaves, through the departure gate's laws in the
 * order they run — then the dialect bars and the places nothing guards. Policies read like a page of rules: each a
 * sentence, its facts as chips, its button on its row. A failed or absent read says so.
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { Theme } from "@radix-ui/themes";
import { afterEach, describe, expect, it, vi } from "vitest";

import { GateMapView, PoliciesView } from "./GateMapPanel";

const GATE_MAP = {
  statements: {
    present: true, sites: 206,
    note: "every place a statement reaches a warehouse, from the code itself; a call the census does not list fails the build",
    by_dialect: [
      { dialect: "declared", sites: 204, means: "the call declares sql_dialect='duckdb'" },
      { dialect: "none", sites: 2, means: "DuckDB's spelling sent undeclared: the bug class" },
    ],
    by_door: [
      { door: "execute", sites: 160, uses: 40660, last_used: "2026-10-13T19:14:56+00:00" },
      { door: "bulk_read", sites: 1, uses: 0, last_used: "" },
    ],
    counted_since: "2026-10-05", uses_note: "Uses are counted from 2026-10-05; nothing earlier was recorded",
    unguarded: [{
      key: "aughor/tools/data_catalog.py::_fetch_sample::execute::_catalog", path: "aughor/tools/data_catalog.py",
      function: "_fetch_sample", door: "execute", label: "_catalog", dialect: "none", author: "platform",
      note: "kept DuckDB-only on purpose: translated, BigQuery rows would reach the model's prompt unredacted",
    }],
  },
  departures: {
    over: 77, note: "counted over the newest 77 departures; a law with 0 held none of them",
    laws: [
      { guard: "trust", label: "trust", law: "", sentence: "a brief whose headline figure … `TRUST_BANNER` …",
        meaning: "The analysis flagged its own headline figure as a computation error.", passed: 67, held: 7, asked: 0,
        last_held: "2026-09-27T13:37:18Z" },
      { guard: "remeasure", label: "re-measure", law: "law 1", sentence: "every magnitude … ``REMEASURE_WITHIN_SECONDS`` …",
        meaning: "The message states numbers the analysis never measured.", passed: 49, held: 16, asked: 0,
        last_held: "2026-10-12T09:05:49Z" },
      { guard: "probation", label: "probation", law: "", sentence: "a NEW automation's departures …",
        meaning: "A new automation reaches only the person who declared it.", passed: 0, held: 0, asked: 0, last_held: "" },
    ],
  },
};

function serve(routes: Record<string, unknown>, status: Record<string, number> = {}) {
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(typeof input === "string" ? input : input instanceof URL ? input.href : input.url);
    const code = status[url.pathname] ?? 200;
    return new Response(JSON.stringify(routes[url.pathname] ?? {}), { status: code, headers: { "Content-Type": "application/json" } });
  }) as typeof fetch;
}

const realFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = realFetch; });

describe("GateMapView", () => {
  it("opens on the picture: places → doors → the warehouse, and what leaves through each law in order", async () => {
    serve({ "/governance/gate-map": GATE_MAP });
    render(<Theme><GateMapView /></Theme>);
    const inFlow = await screen.findByTestId("gate-in-flow");
    expect(within(inFlow).getByTestId("gate-in-places")).toHaveTextContent("206 places in the code");
    expect(within(inFlow).getByTestId("gate-in-places")).toHaveTextContent("1 with no guard");
    const doors = within(inFlow).getAllByTestId("gate-door");
    expect(doors.map(d => d.textContent)).toEqual([
      "execute160 places · 40.7K uses · last 13 Oct",
      "bulk read1 place · not used since 5 Oct",
    ]);
    expect(within(inFlow).getByText("The warehouse")).toBeInTheDocument();

    const laws = within(screen.getByTestId("gate-out-flow")).getAllByTestId("gate-law");
    expect(laws.map(l => l.textContent)).toEqual([
      "trust7 held · 67 passed · last 27 Sep",
      "re-measure · law 116 held · 49 passed · last 12 Oct",
      "probationmet none",
    ]);
    // the law's long sentence is kept, behind its name
    expect(laws[1].getAttribute("title")).toContain("REMEASURE_WITHIN_SECONDS");
    expect(screen.getByText("newest 77 checked")).toBeInTheDocument();
    expect(screen.getByText("uses since 5 Oct")).toBeInTheDocument();
  });

  it("then the dialect bars and the places nothing guards, with the reason each is still there", async () => {
    serve({ "/governance/gate-map": GATE_MAP });
    render(<Theme><GateMapView /></Theme>);
    const dialects = await screen.findByTestId("gate-dialects");
    expect(within(dialects).getByText("none — undeclared")).toBeInTheDocument();
    const site = within(screen.getByTestId("gate-unguarded")).getByTestId("gate-unguarded-site");
    expect(site).toHaveTextContent("kept DuckDB-only on purpose");
    expect(site).toHaveTextContent("aughor/tools/data_catalog.py · in _fetch_sample · written by the platform");
  });

  it("an install without the census says so instead of drawing an empty map", async () => {
    serve({ "/governance/gate-map": { ...GATE_MAP, statements: { present: false, sites: 0, by_dialect: [], by_door: [], unguarded: [],
      note: "the census of statement doors ships with the source tree and is not on this install" } } });
    render(<Theme><GateMapView /></Theme>);
    expect(await screen.findByText(/the census of statement doors ships with the source tree/)).toBeInTheDocument();
    expect(screen.queryByTestId("gate-in-flow")).toBeNull();
    expect(screen.queryByTestId("gate-dialects")).toBeNull();
  });

  it("says a failed read and offers to read again", async () => {
    serve({}, { "/governance/gate-map": 500 });
    render(<Theme><GateMapView /></Theme>);
    expect(await screen.findByRole("alert")).toHaveTextContent(/gate map/);
    expect(screen.getByRole("button", { name: /Retry/ })).toBeInTheDocument();
  });
});

const POLICY = {
  effective: { level: "run", connections: null, tools: null, set_by: "", updated_at: "", source: "default", narrowed_by: [] },
  levels: ["read", "run", "act"],
};
const ROLES = [
  { name: "viewer", label: "Viewer", description: "Read-only access to answers and analyses.", permissions: ["resource.read"] },
  { name: "owner", label: "Owner", description: "Full control, including role administration and billing.", permissions: ["admin.manage_org", "resource.read"] },
];

describe("PoliciesView", () => {
  it("reads each rule back as a sentence, its facts as chips, its button on its row", async () => {
    serve({
      "/org-settings/agent-policy": POLICY, "/governance/caps": { caps: [] }, "/rbac/roles": ROLES,
      "/rbac/assignments": [{ user_id: "mallory", role: "owner" }], "/rbac/me": { user_id: null, org_id: "default", roles: ["owner"] },
    });
    const onOpenSettings = vi.fn();
    const onOpenSpend = vi.fn();
    render(<Theme><PoliciesView onOpenSettings={onOpenSettings} onOpenSpend={onOpenSpend} /></Theme>);
    const agents = await screen.findByRole("group", { name: "Agents" });
    expect(await within(agents).findByText(/It may not change anything outside the conversation/)).toBeInTheDocument();
    expect(within(agents).getByText("the default · nobody has set it")).toBeInTheDocument();
    fireEvent.click(within(agents).getByRole("button", { name: "Change it" }));
    expect(onOpenSettings).toHaveBeenCalled();

    const spending = screen.getByRole("group", { name: "Spending" });
    expect(await within(spending).findByTestId("policy-no-cap")).toHaveTextContent("no cap");
    expect(spending).toHaveTextContent("Nothing alerts or blocks on usage.");
    fireEvent.click(within(spending).getByRole("button", { name: "Spend" }));
    expect(onOpenSpend).toHaveBeenCalled();

    const groups = screen.getByRole("group", { name: "Groups" });
    expect(await within(groups).findAllByTestId("policy-group")).toHaveLength(2);
    expect(groups).toHaveTextContent("mallory · 2 permissions");
    expect(within(groups).getByTestId("policy-groups-wait")).toHaveTextContent("narrow nothing while identity is off");

    const identity = screen.getByRole("group", { name: "Identity" });
    expect(await within(identity).findByText(/every caller is treated as the owner/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Download" })).toHaveAttribute("download", "aughor-ledger.jsonl");
  });

  it("a cap reads back as a sentence; a failed read says so on its own row", async () => {
    serve({
      "/org-settings/agent-policy": POLICY,
      "/governance/caps": { caps: [{ scope: "org", subject: "*", metric: "calls", limit: 1000, window_hours: 24, action: "block" }] },
      "/rbac/roles": ROLES, "/rbac/assignments": [], "/rbac/me": { user_id: "user:amit", org_id: "default", roles: ["owner"] },
    }, { "/rbac/roles": 500 });
    render(<Theme><PoliciesView onOpenSettings={() => {}} onOpenSpend={() => {}} /></Theme>);
    expect(await screen.findByText(/Block when any organisation uses more than 1,000 model calls in 24 hours\./)).toBeInTheDocument();
    expect(await within(screen.getByRole("group", { name: "Groups" })).findByRole("alert")).toHaveTextContent(/groups/);
    expect(await screen.findByText(/You are amit, holding owner\./)).toBeInTheDocument();
    expect(screen.queryByTestId("policy-groups-wait")).toBeNull();
  });
});
