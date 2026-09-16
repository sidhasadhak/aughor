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
