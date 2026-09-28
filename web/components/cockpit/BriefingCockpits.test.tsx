// @vitest-environment jsdom

/**
 * BriefingCockpits (Arc CT, CT-7 to CT-10): a person's cockpits in the Briefing.
 *
 * The API is stood in for, and the cockpit's own drawing (`ComposedCockpit`, tested on its own)
 * is a stub that records what it was handed. What is asserted is what this component asks the
 * server to do, and what it hands on.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BriefingCockpits } from "@/components/cockpit/BriefingCockpits";
import type { CockpitList, PersonCockpit } from "@/lib/api";

const api = vi.hoisted(() => ({
  listCockpits: vi.fn(), getCockpit: vi.fn(), runDashboardCard: vi.fn(), keepCockpit: vi.fn(),
  startMyCockpit: vi.fn(), draftCockpit: vi.fn(), getProposalById: vi.fn(), acceptProposal: vi.fn(),
  rejectProposal: vi.fn(), moveCanvasCockpit: vi.fn(), restoreCockpit: vi.fn(), retireCockpit: vi.fn(),
}));
const drawn = vi.hoisted(() => ({ props: [] as Record<string, unknown>[] }));
const composer = vi.hoisted(() => ({ onCreated: null as null | (() => void) }));

vi.mock("@/lib/api", async (original) => ({ ...(await original<typeof import("@/lib/api")>()), ...api }));
vi.mock("@/components/cockpit/ComposedCockpit", () => ({
  ComposedCockpit: (props: Record<string, unknown>) => { drawn.props.push(props); return <div data-testid="composed-stub" />; },
}));
vi.mock("@/components/brief/NewCardComposer", () => ({
  NewCardComposer: ({ onCreated }: { onCreated: () => void }) => { composer.onCreated = onCreated; return <div data-testid="composer-stub" />; },
}));

const SPEC = JSON.parse(readFileSync(resolve(process.cwd(), "lib/cockpit/premise.fixture.json"), "utf8"));
const card = (id: string, title: string, own = true) => ({
  id, title, kind: "kpi", own, connection_id: "thelook", scope: own ? "user" : "connection", scope_ref: "default",
  source: "authored", sql: "SELECT 1", thresholds: {}, provenance: {}, links: [], render: {},
}) as unknown as PersonCockpit["cards"][number];

const version = (n: number, extra: Record<string, unknown> = {}) => ({
  version: n, artifact_id: `a${n}`, kept_at: "2026-09-28T15:14:39Z", current: true, retired: false,
  approved_by: "person", source: "a person's own hand", note: "", vocabulary_version: 1,
  written_by_model: false, cards: [], changes: { added: [], removed: [], changed: [] }, ...extra,
});

const LIST: CockpitList = {
  person: "default", shared_cards: 1, own_cards: 2, from_canvases: [],
  cockpits: [
    { ...version(3), cockpit_id: "returns-1", title: "Returns", started_at: "2026-09-28T10:00:00Z" },
    { ...version(1), cockpit_id: "pricing-1", title: "Pricing", started_at: "2026-09-28T11:00:00Z" },
  ],
};

const READ: PersonCockpit = {
  connection_id: "thelook", owner: "default", cockpit_id: "returns-1",
  cockpit: { ...version(3), spec: SPEC },
  cards: [card("c7f3a001", "Return rate"), card("c91b2002", "Net merchandise revenue"), card("cafe0003", "Pinned for everyone", false)],
  range: { status: "standing", preset: null, start: null, last_day: null, covers: "", as_of: null, lag_days: null, still_moving: [] },
  ranges_on: true,
  history: [version(3), { ...version(2), current: false }, { ...version(1), current: false }],
};

const show = (range = null as null | { preset: "last_month" }) => render(
  <BriefingCockpits connectionId="thelook" schema="thelook" range={range} fallback={<div data-testid="the-old-cockpit" />} />);

beforeEach(() => {
  for (const f of Object.values(api)) f.mockReset();
  drawn.props.length = 0;
  composer.onCreated = null;
  try { localStorage.clear(); } catch { /* jsdom */ }
  api.listCockpits.mockResolvedValue(LIST);
  api.getCockpit.mockResolvedValue(READ);
  api.runDashboardCard.mockResolvedValue({ columns: ["_v"], rows: [["10.03"]], row_count: 1 });
  api.keepCockpit.mockResolvedValue({ status: "kept", kept: true, version: 4, artifact_id: "a4", sentences: [] });
});

describe("with the flag off", () => {
  it("draws exactly what the Briefing drew before, and nothing of its own", async () => {
    api.listCockpits.mockResolvedValue(null);
    show();
    expect(await screen.findByTestId("the-old-cockpit")).toBeInTheDocument();
    expect(screen.queryByTestId("briefing-cockpits")).toBeNull();
    expect(api.getCockpit).not.toHaveBeenCalled();
  });
});

describe("a person's cockpits", () => {
  it("lists them in a strip and draws the first, each card it places run for the page's range", async () => {
    show({ preset: "last_month" });
    await waitFor(() => expect(drawn.props.length).toBeGreaterThan(0));
    expect(screen.getAllByTestId("cockpit-strip-item").map(b => b.textContent)).toEqual(["Returns", "Pricing"]);
    expect(api.getCockpit).toHaveBeenCalledWith("thelook", "returns-1", { preset: "last_month" });
    // Only the cards the spec places are run — the pinned card it does not place is not.
    expect(api.runDashboardCard.mock.calls.map(c => c[0]).sort()).toEqual(["c7f3a001", "c91b2002"]);
    expect(api.runDashboardCard.mock.calls[0][1]).toEqual({ preset: "last_month" });
    const last = drawn.props.at(-1)!;
    expect(last.spec).toEqual(SPEC);
    expect(screen.getByTestId("cockpit-version")).toHaveTextContent("Version 3 · kept by person");
  });

  it("opens the one the person chose last time", async () => {
    localStorage.setItem("aughor:cockpit:thelook", "pricing-1");
    show();
    await waitFor(() => expect(api.getCockpit).toHaveBeenCalledWith("thelook", "pricing-1", null));
  });

  it("'Remove' on a card takes it off THIS cockpit and keeps the card", async () => {
    show();
    await waitFor(() => expect(drawn.props.length).toBeGreaterThan(0));
    const doors = drawn.props.at(-1)!.doors as { onRemove: (id: string) => void };
    doors.onRemove("c91b2002");
    await waitFor(() => expect(api.keepCockpit).toHaveBeenCalled());
    const [conn, id, spec, note] = api.keepCockpit.mock.calls[0];
    expect([conn, id, note]).toEqual(["thelook", "returns-1", "a card taken off"]);
    expect(JSON.stringify(spec)).not.toContain("c91b2002");
  });

  it("a card pinned from here lands on the cockpit in view", async () => {
    show();
    await waitFor(() => expect(composer.onCreated).not.toBeNull());
    api.getCockpit.mockResolvedValue({ ...READ, cards: [...READ.cards, card("fresh0001", "Just pinned", false)] });
    composer.onCreated!();
    await waitFor(() => expect(api.keepCockpit).toHaveBeenCalled());
    const [, , spec, note] = api.keepCockpit.mock.calls[0];
    expect(note).toBe("a card pinned from the Briefing");
    expect(JSON.stringify(spec)).toContain("fresh0001");
    expect(JSON.stringify(spec)).not.toContain("cafe0003");                  // the one already there is not
  });
});

describe("a retired cockpit", () => {
  it("leaves the strip, is said to be retired, and is brought back as it was before", async () => {
    api.listCockpits.mockResolvedValue({ ...LIST, cockpits: [LIST.cockpits[0], { ...LIST.cockpits[1], retired: true, version: 4, title: "Pricing" }] });
    api.restoreCockpit.mockResolvedValue({ status: "kept", kept: true, version: 5, artifact_id: "a5", sentences: [] });
    show();
    const retired = await screen.findByTestId("cockpit-retired");
    expect(screen.getAllByTestId("cockpit-strip-item").map(b => b.textContent)).toEqual(["Returns"]);
    expect(retired).toHaveTextContent("Retired:Pricing");
    fireEvent.click(within(retired).getByRole("button", { name: "Bring back" }));
    await waitFor(() => expect(api.restoreCockpit).toHaveBeenCalledWith("thelook", "pricing-1", 3));
  });
});

describe("arranging by hand", () => {
  it("saves what was arranged as the next version, and offers the cards not on it", async () => {
    show();
    fireEvent.click(await screen.findByTestId("cockpit-arrange-open"));
    const save = screen.getByRole("button", { name: "Save" });
    expect(save).toBeDisabled();                                            // nothing changed yet

    const tray = screen.getByTestId("cockpit-tray");
    expect(within(tray).getAllByRole("button").map(b => b.textContent)).toEqual(["+ Pinned for everyone"]);
    fireEvent.click(within(tray).getByRole("button", { name: "+ Pinned for everyone" }));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.keepCockpit).toHaveBeenCalled());
    const [, id, spec, note] = api.keepCockpit.mock.calls[0];
    expect([id, note]).toEqual(["returns-1", "arranged by hand"]);
    expect(JSON.stringify(spec)).toContain("cafe0003");
  });
});

describe("with no cockpits yet", () => {
  it("offers to start 'My cockpit' from the cards already pinned, with no model", async () => {
    api.listCockpits.mockResolvedValue({ ...LIST, cockpits: [] });
    api.startMyCockpit.mockResolvedValue({ status: "kept", kept: true, version: 1, artifact_id: "a1", sentences: [], cockpit_id: "my-cockpit" });
    show();
    fireEvent.click(await screen.findByRole("button", { name: "Start “My cockpit” from 3 pinned cards" }));
    await waitFor(() => expect(api.startMyCockpit).toHaveBeenCalledWith("thelook"));
    expect(api.draftCockpit).not.toHaveBeenCalled();
  });

  it("offers to move a cockpit that lived in a Data Canvas", async () => {
    api.listCockpits.mockResolvedValue({ ...LIST, cockpits: [], from_canvases: [{ ...version(3), canvas_id: "d617964b", title: "Executive Cockpit" }] });
    api.moveCanvasCockpit.mockResolvedValue({ moved: true, cockpit_id: "executive-cockpit-1", title: "Executive Cockpit", version: 1, sentences: [] });
    show();
    const offer = await screen.findByTestId("cockpit-move-offer");
    expect(offer).toHaveTextContent("“Executive Cockpit” was kept in a Data Canvas");
    fireEvent.click(within(offer).getByRole("button", { name: "Move it here" }));
    await waitFor(() => expect(api.moveCanvasCockpit).toHaveBeenCalledWith("thelook", "d617964b"));
  });
});

describe("a new cockpit from an area", () => {
  const PROPOSAL = {
    id: "p1", kind: "cockpit_draft", status: "pending", reasoning: "Returns first, then what they cost.",
    params: { home: { connection_id: "thelook", owner: "default", cockpit_id: "returns-9" }, spec: SPEC,
              cards: [{ id: "c91b2002", title: "Net merchandise revenue", kind: "kpi", from: "metric" }] },
    detail: { outline: [
      { tab: "Overview", sections: [{ title: "Headline", cards: [{ title: "Return rate" }, { title: "Return rate" }, { title: "Net merchandise revenue" }] }] },
      { tab: "Watches", sections: [{ title: "Limits", cards: [{ title: "Return rate" }] }] },
    ] },
  };

  async function draftReturns() {
    show();
    fireEvent.click(await screen.findByTestId("cockpit-new-open"));
    fireEvent.change(screen.getByLabelText("What this cockpit is for"), { target: { value: "Returns" } });
    fireEvent.click(screen.getByRole("button", { name: "Draft it" }));
  }

  it("drafts it, shows it to be arranged, and keeps it as drafted", async () => {
    api.draftCockpit.mockResolvedValue({ staged: true, proposal_id: "p1", cockpit_id: "returns-9", summary: "Drafted the cockpit \"Returns\".", rounds: 1, stop_reason: "answered", sentences: [] });
    api.getProposalById.mockResolvedValue(PROPOSAL);
    api.acceptProposal.mockResolvedValue({ status: "executed" });
    await draftReturns();

    const draft = await screen.findByTestId("cockpit-draft");
    expect(api.draftCockpit).toHaveBeenCalledWith("thelook", "Returns", "thelook");
    expect(draft).toHaveTextContent("Drafted the cockpit \"Returns\".");
    expect(draft).toHaveTextContent("Why it is arranged this way: Returns first, then what they cost.");
    const lines = within(draft).getAllByTestId("arrange-card");
    expect(lines[0]).toHaveTextContent("Return rate");                       // a card the person has, by name
    expect(lines[2]).toHaveTextContent("Net merchandise revenue");
    expect(lines[2]).toHaveTextContent("one figure for the whole connection");

    fireEvent.click(within(draft).getByRole("button", { name: "Keep it" }));
    await waitFor(() => expect(api.acceptProposal).toHaveBeenCalledWith("p1", "briefing"));
    expect(api.keepCockpit).not.toHaveBeenCalled();                          // kept as drafted: one version
  });

  it("changes made before keeping are kept as the next version, in the same act", async () => {
    api.draftCockpit.mockResolvedValue({ staged: true, proposal_id: "p1", cockpit_id: "returns-9", summary: "", rounds: 1, stop_reason: "answered", sentences: [] });
    api.getProposalById.mockResolvedValue(PROPOSAL);
    api.acceptProposal.mockResolvedValue({ status: "executed" });
    await draftReturns();
    const draft = await screen.findByTestId("cockpit-draft");
    fireEvent.click(within(within(draft).getAllByTestId("arrange-card")[2]).getByRole("button", { name: "Take off" }));
    fireEvent.click(within(draft).getByRole("button", { name: "Keep, with my changes" }));

    await waitFor(() => expect(api.keepCockpit).toHaveBeenCalled());
    expect(api.acceptProposal).toHaveBeenCalledWith("p1", "briefing");
    const [conn, id, spec, note] = api.keepCockpit.mock.calls[0];
    expect([conn, id, note]).toEqual(["thelook", "returns-9", "adjusted before keeping"]);
    expect(JSON.stringify(spec)).not.toContain("c91b2002");
  });

  it("when nothing is drafted, says why in the platform's words and keeps nothing", async () => {
    api.draftCockpit.mockResolvedValue({ staged: false, proposal_id: "", cockpit_id: "", summary: "", rounds: 0, stop_reason: "answered",
      sentences: ["Nothing this connection measures bears on marketing."] });
    await draftReturns();
    expect(await screen.findByTestId("cockpit-not-drafted")).toHaveTextContent("Nothing this connection measures bears on marketing.");
    expect(api.getProposalById).not.toHaveBeenCalled();
  });

  it("discarding rejects the draft", async () => {
    api.draftCockpit.mockResolvedValue({ staged: true, proposal_id: "p1", cockpit_id: "returns-9", summary: "", rounds: 1, stop_reason: "answered", sentences: [] });
    api.getProposalById.mockResolvedValue(PROPOSAL);
    api.rejectProposal.mockResolvedValue(true);
    await draftReturns();
    fireEvent.click(within(await screen.findByTestId("cockpit-draft")).getByRole("button", { name: "Discard" }));
    await waitFor(() => expect(api.rejectProposal).toHaveBeenCalledWith("p1", "briefing"));
    expect(api.acceptProposal).not.toHaveBeenCalled();
  });
});
