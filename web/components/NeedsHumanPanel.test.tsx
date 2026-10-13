// @vitest-environment jsdom
/**
 * Agent Ops · Attention — what needs a person, and never "Nothing needs a human" when that is not what the read said.
 *
 * The panel said a failed read only before its first answer: once it had one, a refresh that failed was kept off the
 * page and the last answer stayed, so an empty first read printed "Nothing needs a human. Every source is empty right
 * now." for as long as every read after it failed. And reads overlap — the poll fires every 10 s and the route runs its
 * sweeps before it answers — so a slow empty answer could land after a newer one and put "nothing" back.
 *
 * Every API function the panel calls is stubbed, and the poll is driven by hand: nothing reaches the live API.
 */
import { act, render, screen } from "@/lib/testing";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { NeedsHuman, NeedsHumanRow } from "@/lib/api";

const stubs: { getNeedsHuman: () => Promise<NeedsHuman> } = { getNeedsHuman: () => Promise.resolve(answer([])) };
let poll: () => void = () => {};

vi.mock("@/lib/api", async importOriginal => ({
  ...(await importOriginal<Record<string, unknown>>()),
  getNeedsHuman: () => stubs.getNeedsHuman(),
  getConnections: () => Promise.resolve([]),
  acknowledgeAgentAlert: () => Promise.resolve(),
}));
vi.mock("@/lib/useVisiblePoll", () => ({
  useVisiblePoll: (fn: () => void) => { poll = fn; return true; },
}));
// The rules editor and the approval card read their own endpoints; neither is what this suite is about.
vi.mock("@/components/agentops/AgentAlertRulesPanel", () => ({ AgentAlertRulesPanel: () => null }));
vi.mock("@/components/ProposalCard", () => ({ ProposalCardById: () => null }));

const { NeedsHumanPanel } = await import("@/components/NeedsHumanPanel");

const alert = (id: string): NeedsHumanRow => ({
  source: "agent_alert", id, title: "Error rate: crossed 40% of runs", connection_id: "", severity: "warning",
  since: "2026-10-13T08:00:00Z", waiting_ms: 60_000, resolve: {},
});

function answer(rows: NeedsHumanRow[]): NeedsHuman {
  return { count: rows.length, rows,
    sources: { paused_runs: 0, automation_approvals: 0, agent_alerts: rows.length, broken_automations: 0 } as NeedsHuman["sources"] };
}

function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>(r => { resolve = r; });
  return { promise, resolve };
}

const NOTHING = /Nothing needs a human/;

beforeEach(() => {
  stubs.getNeedsHuman = () => Promise.resolve(answer([]));
});

describe("Attention", () => {
  it("says a refresh that failed, never 'Nothing needs a human' from the answer before it", async () => {
    const answers = [Promise.resolve(answer([])), Promise.reject(new Error("502 from the API"))];
    answers[1].catch(() => {});
    stubs.getNeedsHuman = () => answers.shift()!;
    render(<NeedsHumanPanel />);
    expect(await screen.findByText(NOTHING)).toBeInTheDocument();

    await act(async () => { poll(); });
    expect(await screen.findByText(/Could not read what needs a person/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
    expect(screen.queryByText(NOTHING)).toBeNull();
  });

  it("lists what waits even when an older, empty answer arrives after a newer one", async () => {
    const first = deferred<NeedsHuman>();
    const second = deferred<NeedsHuman>();
    const answers = [first.promise, second.promise];
    stubs.getNeedsHuman = () => answers.shift()!;
    render(<NeedsHumanPanel />);
    await act(async () => { poll(); });

    await act(async () => { second.resolve(answer([alert("a1")])); });
    expect(await screen.findByRole("button", { name: "Acknowledge" })).toBeInTheDocument();

    await act(async () => { first.resolve(answer([])); });
    expect(screen.getByRole("button", { name: "Acknowledge" })).toBeInTheDocument();
    expect(screen.queryByText(NOTHING)).toBeNull();
  });

  it("names a source the route could not read, its count a dash — never 'every source is empty'", async () => {
    stubs.getNeedsHuman = () => Promise.resolve({ ...answer([]), unread: ["agent_alerts", "paused_runs"] });
    render(<NeedsHumanPanel />);
    expect(await screen.findByTestId("needs-unread"))
      .toHaveTextContent("Could not read agent alerts, paused deep runs — anything waiting there is not shown.");
    expect(screen.queryByText(NOTHING)).toBeNull();
    expect(screen.getByText("Nothing waits in the sources that could be read.")).toBeInTheDocument();
  });
});
