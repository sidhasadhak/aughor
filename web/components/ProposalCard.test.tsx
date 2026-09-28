// @vitest-environment jsdom
/**
 * SP-9 — the approval card says WHAT either click creates, never raw params.
 *
 * The measured break it exists for (§3.11, second movement): approval rows printed
 * `JSON.stringify(p.params)`, and Attention offered Accept/Reject beside a bare title.
 * Locked here: labeled facts per kind, the whole-object JSON dump absent, open choices
 * as fields that gate Accept and travel as `fills`, and the bundle reading as ONE
 * decision.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { StagedProposal } from "@/lib/api";

const acceptProposal = vi.fn();
const rejectProposal = vi.fn();
const getProposalById = vi.fn();

vi.mock("@/lib/api", async importOriginal => {
  const actual = await importOriginal<Record<string, unknown>>();
  return {
    ...actual,
    acceptProposal: (...a: unknown[]) => acceptProposal(...a),
    rejectProposal: (...a: unknown[]) => rejectProposal(...a),
    getProposalById: (...a: unknown[]) => getProposalById(...a),
  };
});

const { ProposalCard, utcWords } = await import("@/components/ProposalCard");

const chainParams = (channel: string) => ({
  conn_id: "conn-x", name: "morning anomalies", description: "",
  conditions: [{ kind: "schedule", config: { cron: "0 9 * * *" } }],
  effects: [{ kind: "slack_post", config: { bot_id: "bot-1", channel, message: "hi" } }],
});

const proposal = (over: Partial<StagedProposal> = {}): StagedProposal => ({
  id: "prop-1", connection_id: "conn-x", schema_name: "", kind: "automation_draft",
  grant_id: "", action_id: "automation:morning anomalies",
  params: chainParams("#ops"), detail: {}, reasoning: "asked in conversation",
  proposer: "spotlight", source: "agent", status: "pending", status_message: "",
  outcome: {}, created_at: "2026-09-15T09:00:00Z", resolved_at: null, resolved_by: "",
  ...over,
} as StagedProposal);

beforeEach(() => {
  acceptProposal.mockReset().mockResolvedValue({ status: "executed", outcome: {}, minted_grant: "" });
  rejectProposal.mockReset().mockResolvedValue(true);
});

describe("ProposalCard", () => {
  it("renders an automation draft as labeled facts, never the params object as JSON", () => {
    const { container } = render(
      <ProposalCard proposal={proposal({
        detail: { first_run: "2026-09-16T09:00:00Z", dry_run_ok: true, runs_as: "" },
      })} actor="tester" />);
    expect(screen.getByText("morning anomalies")).toBeInTheDocument();
    expect(screen.getByText(/schedule · 0 9 \* \* \* \(UTC\)/)).toBeInTheDocument();
    expect(screen.getByText(/channel #ops/)).toBeInTheDocument();
    expect(screen.getByText(/16 Sep 2026 09:00 UTC/)).toBeInTheDocument();
    // the ratchet's claim, held at component level: no whole-object dump
    expect(container.textContent).not.toContain('{"conn_id"');
  });

  it("gates Accept on the open choices and sends the answers as fills", async () => {
    render(
      <ProposalCard proposal={proposal({
        params: chainParams(""),
        detail: { open_choices: [{ action: 1, key: "channel" }], to_fill: [] },
      })} actor="tester" />);
    const accept = screen.getByRole("button", { name: "Accept" });
    expect(accept).toBeDisabled();               // arming a placeholder is not offered

    await userEvent.type(screen.getByPlaceholderText("#channel"), "#ops");
    expect(accept).toBeEnabled();
    await userEvent.click(accept);
    expect(acceptProposal).toHaveBeenCalledWith("prop-1", "tester", false, { "1.channel": "#ops" });
  });

  it("renders the bundle as ONE decision holding both records", () => {
    render(
      <ProposalCard proposal={proposal({
        kind: "agent_bundle",
        action_id: "agent:watcher+automation:morning anomalies",
        params: {
          agent: { name: "watcher", instructions: "Deliver anomalies.", schema_scope: "", doc_ids: [] },
          automation: chainParams("#ops"),
        },
        detail: { first_run: "2026-09-16T09:00:00Z", runs_as: "watcher" },
      })} actor="tester" />);
    // "watcher" appears as the agent's name AND as the chain's runs-as — both on purpose
    expect(screen.getAllByText("watcher").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("morning anomalies")).toBeInTheDocument();
    expect(screen.getByText(/all\s*or\s*nothing/)).toBeInTheDocument();
    // the empty-documents trap, still disclosed on the card
    expect(screen.getByText(/less context than plain chat/)).toBeInTheDocument();
  });

  it("rejects with no side effect and reads back the resolution", async () => {
    render(<ProposalCard proposal={proposal()} actor="tester" />);
    await userEvent.click(screen.getByRole("button", { name: "Reject" }));
    expect(rejectProposal).toHaveBeenCalledWith("prop-1", "tester");
    expect(await screen.findByText(/rejected/)).toBeInTheDocument();
  });

  it("shows an agent draft's scope and the empty-documents disclosure", () => {
    render(
      <ProposalCard proposal={proposal({
        kind: "agent_draft", action_id: "agent:watcher",
        params: { name: "watcher", instructions: "A scope and a stance.", schema_scope: "thelook", doc_ids: [] },
      })} actor="tester" />);
    expect(screen.getByText(/schema thelook/)).toBeInTheDocument();
    expect(screen.getByText("A scope and a stance.")).toBeInTheDocument();
    expect(screen.getByText(/less context than plain chat/)).toBeInTheDocument();
  });
});

describe("utcWords", () => {
  it("names the clock", () => {
    expect(utcWords("2026-09-16T09:00:00Z")).toBe("Wed, 16 Sep 2026 09:00 UTC");
    expect(utcWords("not a date")).toBe("not a date");
  });
});

describe("SP-12 kinds", () => {
  it("an edit renders as a before-and-after diff, never raw params", () => {
    const { container } = render(
      <ProposalCard proposal={proposal({
        kind: "automation_edit", action_id: "automation-edit:The Monday brief",
        params: { automation_id: "a1", changes: { cron: "0 8 * * 1" } },
        detail: { automation_name: "The Monday brief",
          diff: [{ field: "cron", before: "0 9 * * 1", after: "0 8 * * 1" }] },
      })} actor="tester" />);
    expect(screen.getByText("The Monday brief")).toBeInTheDocument();
    expect(screen.getByText("0 9 * * 1")).toBeInTheDocument();
    expect(screen.getByText("0 8 * * 1")).toBeInTheDocument();
    expect(container.textContent).not.toContain('{"automation_id"');
  });

  it("a monitor bundle says what it watches and reads as one decision", () => {
    render(
      <ProposalCard proposal={proposal({
        kind: "monitor_bundle", action_id: "monitor:refund watch+automation:refund watch",
        params: { monitor: { name: "refund watch" }, automation: chainParams("#ops") },
        detail: { watches: "refund_rate", sigma: 3, check_cadence: "hourly",
          to_fill: [], open_choices: [] },
      })} actor="tester" />);
    expect(screen.getByText("refund watch")).toBeInTheDocument();
    expect(screen.getByText(/refund_rate · breach at 3σ/)).toBeInTheDocument();
    expect(screen.getByText(/all or nothing/)).toBeInTheDocument();
  });

  it("a brief draft says when and through what it delivers", () => {
    render(
      <ProposalCard proposal={proposal({
        kind: "brief_draft", action_id: "brief:Morning brief",
        params: { name: "Morning brief", period: "day", trigger_id: "trig-slack" },
        detail: { send_words: "every day at 08:00 UTC", delivers_via: "trig-slack (Ops Slack)" },
      })} actor="tester" />);
    expect(screen.getByText("Morning brief")).toBeInTheDocument();
    expect(screen.getByText("every day at 08:00 UTC")).toBeInTheDocument();
    expect(screen.getByText(/Ops Slack/)).toBeInTheDocument();
  });
});

describe("cockpit_draft (Arc CT-5)", () => {
  const spec = {
    root: "cockpit", elements: {
      cockpit: { type: "Cockpit", props: { title: "Returns" }, children: ["sec"] },
      sec: { type: "Section", props: { title: "Headline" }, children: ["c"] },
      c: { type: "Card", props: { card: "a1b2c3d4" }, children: [] },
    },
  };
  const draft = (over: Partial<StagedProposal> = {}) => proposal({
    kind: "cockpit_draft", action_id: "cockpit:canvas-1", proposer: "cockpit",
    reasoning: "Alerts first, detail behind a tab.",
    params: {
      canvas_id: "canvas-1", mode: "new", base_version: null, spec, patches: [],
      cards: [
        { id: "a1b2c3d4", key: "return-rate", from: "metric", name: "return_rate", version: 3,
          label: "Return rate", kind: "kpi", title: "Return rate", sql: "SELECT secret_sql FROM t",
          limit: { critical: 12, direction: "above" } },
        { id: "e5f6a7b8", key: "by-category", from: "trusted_query", name: "tq-7", version: 2,
          label: "Items returned by category", kind: "chart", title: "Returned, by category",
          sql: "SELECT other_sql", limit: {} },
      ],
    },
    detail: {
      canvas_name: "Returns desk", title: "Returns", mode: "new", replaces_version: null,
      counts: { tabs: 2, sections: 2, cards: 3, new: 2 },
      changes: { added: ["cockpit", "sec", "c"], removed: [], changed: [] },
      outline: [
        { tab: "Overview", sections: [
          { title: "Needs a look", shown: "\"Return rate\" is over its limit", cards: [
            { title: "Return rate", new: true, tone: "bad", shown: "" }] }] },
        { tab: "Detail", sections: [
          { title: "Where and when", shown: "", cards: [
            { title: "Returned, by category", new: true, tone: "", shown: "" },
            { title: "Net merchandise revenue", new: false, tone: "", shown: "the range is not to date" }] }] },
      ],
    },
    ...over,
  });

  it("says what is arranged, in words — tabs, sections, cards and each condition", () => {
    render(<ProposalCard proposal={draft()} actor="tester" />);
    expect(screen.getByText("cockpit")).toBeInTheDocument();                     // the chip
    expect(screen.getByText("Returns")).toBeInTheDocument();
    expect(screen.getByText("Returns desk")).toBeInTheDocument();
    const outline = screen.getByTestId("cockpit-outline");
    expect(outline).toHaveTextContent("Tab · Overview");
    expect(outline).toHaveTextContent("Needs a look · shown when \"Return rate\" is over its limit");
    expect(outline).toHaveTextContent("Return rate · new");
    expect(outline).toHaveTextContent("Tab · Detail");
    expect(outline).toHaveTextContent("Net merchandise revenue · shown when the range is not to date");
    // A card the canvas already holds is not called new.
    expect(outline).not.toHaveTextContent("Net merchandise revenue · new");
  });

  it("says what each new card is made from, and never shows a query or the spec", () => {
    const { container } = render(<ProposalCard proposal={draft()} actor="tester" />);
    const made = screen.getByTestId("cockpit-new-cards");
    expect(made).toHaveTextContent("2 cards are made");
    expect(made).toHaveTextContent(
      "Return rate — from the approved metric return_rate, version 3 · limit: critical at or above 12");
    expect(made).toHaveTextContent("Returned, by category — from the trusted query tq-7, version 2");
    expect(container.textContent).not.toContain("secret_sql");
    expect(container.textContent).not.toContain("other_sql");
    expect(container.textContent).not.toContain('"elements"');
    expect(container.textContent).not.toContain("$state");
    expect(screen.getByText(/all or nothing/)).toBeInTheDocument();
    expect(screen.getByText("Alerts first, detail behind a tab.")).toBeInTheDocument();
  });

  it("a limit crossed going down, and a warning beside a critical", () => {
    const p = draft();
    (p.params.cards as Record<string, unknown>[])[0].limit = { warning: 95, critical: 90, direction: "below" };
    render(<ProposalCard proposal={p} actor="tester" />);
    expect(screen.getByTestId("cockpit-new-cards"))
      .toHaveTextContent("limit: at or below 95, critical at or below 90");
  });

  it("an edit says which version it edits and how much of it moves", () => {
    render(<ProposalCard proposal={draft({
      params: { canvas_id: "canvas-1", mode: "edit", base_version: 4, spec, cards: [], patches: [] },
      detail: { canvas_name: "Returns desk", title: "Returns", mode: "edit", replaces_version: 4,
        counts: { tabs: 0, sections: 1, cards: 1, new: 0 },
        changes: { added: [], removed: ["c-week"], changed: ["sec-detail", "sec-headline"] },
        outline: [{ tab: "", sections: [{ title: "Headline", shown: "", cards: [
          { title: "Return rate", new: false, tone: "", shown: "" }] }] }] },
    })} actor="tester" />);
    expect(screen.getByText(/version 4 · of its elements, 1 removed · 2 changed/)).toBeInTheDocument();
    expect(screen.queryByTestId("cockpit-moved")).toBeNull();          // this outline marks nothing
    expect(screen.queryByTestId("cockpit-taken-off")).toBeNull();      // and its record names nothing taken off
    // No card is made, so the card does not speak of cards that were run.
    expect(screen.queryByText(/was run once/)).toBeNull();
    expect(screen.queryByTestId("cockpit-new-cards")).toBeNull();
    expect(screen.queryByText(/Tab ·/)).toBeNull();
    expect(screen.getByText(/accepting keeps this arrangement/)).toBeInTheDocument();
  });

  it("an edit marks each line it adds or changes, and no line it leaves alone", () => {
    render(<ProposalCard proposal={draft({
      params: { canvas_id: "canvas-1", mode: "edit", base_version: 4, spec, patches: [],
        cards: [{ id: "a1b2c3d4", key: "units", from: "metric", name: "units_returned", version: 1,
          label: "Units returned", kind: "kpi", title: "Units returned", sql: "SELECT x", limit: {} }] },
      detail: { canvas_name: "Returns desk", title: "Returns", mode: "edit", replaces_version: 4,
        counts: { tabs: 2, sections: 3, cards: 4, new: 1 },
        changes: { added: ["tab-asked", "sec-asked", "c-units", "c-net-2"], removed: [], changed: ["sec-headline", "tabs"] },
        outline: [
          { tab: "Overview", change: "", sections: [
            { title: "At a glance", change: "changed", shown: "", cards: [
              { title: "Return rate", new: false, change: "", tone: "", shown: "" }] },
            { title: "Trend", change: "", shown: "", cards: [
              { title: "Revenue by month", new: false, change: "", tone: "", shown: "" }] }] },
          { tab: "Asked for", change: "added", sections: [
            { title: "From approved records", change: "added", shown: "", cards: [
              { title: "Units returned", new: true, change: "added", tone: "", shown: "" },
              { title: "Net merchandise revenue", new: false, change: "added", tone: "", shown: "" }] }] },
        ] },
    })} actor="tester" />);
    const outline = screen.getByTestId("cockpit-outline");
    expect(outline).toHaveTextContent("Tab · Asked for · added");
    expect(outline).toHaveTextContent("At a glance · changed");
    expect(outline).toHaveTextContent("From approved records · added");
    expect(outline).toHaveTextContent("Net merchandise revenue · added");      // a card the canvas holds, placed here
    expect(outline).toHaveTextContent("Units returned · new");                 // a card the draft makes says new…
    expect(outline).not.toHaveTextContent("Units returned · new · added");     // …and not both
    expect(outline).not.toHaveTextContent("Tab · Overview ·");
    expect(outline).not.toHaveTextContent("Trend ·");
    expect(outline).not.toHaveTextContent("Return rate ·");
    expect(screen.getAllByTestId("cockpit-moved")).toHaveLength(4);
  });

  it("an edit names what it takes off, and where each was", () => {
    render(<ProposalCard proposal={draft({
      params: { canvas_id: "canvas-1", mode: "edit", base_version: 4, spec, cards: [], patches: [] },
      detail: { canvas_name: "Returns desk", title: "Returns", mode: "edit", replaces_version: 4,
        counts: { tabs: 0, sections: 1, cards: 1, new: 0 },
        changes: { added: [], removed: ["c-week", "sec-detail", "tab-detail"], changed: ["tabs"] },
        taken_off: [
          { what: "card", title: "Returns by week", from: "Where and when" },
          { what: "section", title: "Where and when", from: "Detail" },
          { what: "tab", title: "Detail", from: "" },
        ],
        outline: [{ tab: "", change: "", sections: [{ title: "Headline", change: "", shown: "", cards: [
          { title: "Return rate", new: false, change: "", tone: "", shown: "" }] }] }] },
    })} actor="tester" />);
    const gone = screen.getByTestId("cockpit-taken-off");
    expect(gone).toHaveTextContent("Taken off the cockpit. A card taken off is kept, and other cockpits may place it:");
    expect(gone).toHaveTextContent("CardReturns by week — it was in Where and when");
    expect(gone).toHaveTextContent("SectionWhere and when — it was in Detail");
    expect(gone).toHaveTextContent(/TabDetail$/);
  });

  it("a new cockpit names nothing taken off", () => {
    render(<ProposalCard proposal={draft()} actor="tester" />);
    expect(screen.queryByTestId("cockpit-taken-off")).toBeNull();
    expect(screen.getByText(/Every new card was run once and passed the guards/)).toBeInTheDocument();
  });

  it("accepted, it says which version it became and where to find it", async () => {
    acceptProposal.mockResolvedValue({
      status: "executed", minted_grant: "",
      outcome: { canvas_id: "canvas-1", version: 5, cards_created: ["a1b2c3d4", "e5f6a7b8"] },
    });
    render(<ProposalCard proposal={draft()} actor="approver@example.com" />);
    await userEvent.click(screen.getByRole("button", { name: "Accept" }));
    expect(acceptProposal).toHaveBeenCalledWith("prop-1", "approver@example.com", false, {});
    expect(await screen.findByText("executed — kept as version 5 — it is among your cockpits in the Briefing"))
      .toBeInTheDocument();
  });

  it("refused on accept, it says why in the server's own sentence and stays pending", async () => {
    acceptProposal.mockRejectedValue(new Error(
      "draft no longer valid: The cockpit has changed since this was drafted: it was version 1, and it is now version 2."));
    render(<ProposalCard proposal={draft()} actor="tester" />);
    await userEvent.click(screen.getByRole("button", { name: "Accept" }));
    expect(await screen.findByText(/The cockpit has changed since this was drafted/)).toBeInTheDocument();
  });

  it("read after it settled, it still says where it went, or why it did not", () => {
    const { unmount } = render(<ProposalCard actor="tester" proposal={draft({
      status: "executed", outcome: { version: 2, cards_created: [] } })} />);
    expect(screen.getByText("executed — kept as version 2 — it is among your cockpits in the Briefing")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Accept" })).toBeNull();
    unmount();
    render(<ProposalCard actor="tester" proposal={draft({
      status: "superseded", status_message: "superseded by prop-9" })} />);
    expect(screen.getByText("superseded — superseded by prop-9")).toBeInTheDocument();
  });
});

describe("outbound_send (SP-7 widened)", () => {
  it("shows the drafted post's destination and offers always-allow", async () => {
    const accept = vi.fn().mockResolvedValue({ status: "executed", outcome: {}, minted_grant: "g1" });
    (await import("@/lib/api")).acceptProposal = accept as never;
    render(
      <ProposalCard proposal={proposal({
        kind: "outbound_send", action_id: "slack_post:auto-1",
        params: { bot_id: "sb_1", channel: "#ops", message: "anomalies today", automation_id: "auto-1" },
      })} actor="tester" />);
    expect(screen.getByText("#ops")).toBeInTheDocument();
    expect(screen.getByText("anomalies today")).toBeInTheDocument();
    const box = screen.getByRole("checkbox");
    await userEvent.click(box);
    await userEvent.click(screen.getByRole("button", { name: "Accept" }));
    expect(accept).toHaveBeenCalledWith("prop-1", "tester", true, {});
  });
});
