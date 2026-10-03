// @vitest-environment jsdom
/**
 * Arc AO-4 — the agent's Doors tab says every way in, with its state, and says which
 * doors are not built yet rather than leaving them off the list.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { Automation, SlackBotSummary, UserAgent } from "@/lib/api";

const stubs = {
  bots: [] as SlackBotSummary[],
  automations: [] as Automation[],
  reject: false,
};

vi.mock("@/lib/api", async importOriginal => {
  const actual = await importOriginal<Record<string, unknown>>();
  return {
    ...actual,
    getSlackBots: () => stubs.reject ? Promise.reject(new Error("502")) : Promise.resolve(stubs.bots),
    getAutomations: () => Promise.resolve(stubs.automations),
  };
});

const { AgentDoors } = await import("@/components/agentops/AgentDoors");
const { TERMS } = await import("@/components/agentops/Term");

const agent: UserAgent = {
  id: "ua_1", name: "The Look Analyst", instructions: "", connection_id: "c1",
  schema_scope: "", doc_ids: [], pack_ids: [], tool_grants: [], owner: "", enabled: true,
  last_eval: null, config_rev: "", eval_basis: "current" as UserAgent["eval_basis"],
  created_at: "", updated_at: "",
};

const bot = (over: Partial<SlackBotSummary>): SlackBotSummary => ({
  id: "sb_1", name: "salesbot", enabled: true, disabled_reason: "", listening: null,
  liveness_hint: "not listening — no supervisor has reported; start the supervisor: cd bots/slack && npm run dev",
  team_id: "T1", bot_user_id: "U1", agent_id: "ua_1", connection_id: "c1", agent_view: false,
  ...over,
});

describe("the Doors tab", () => {
  it("lists chat, the bot with its liveness, the automation, and the doors not built yet", async () => {
    stubs.bots = [bot({ listening: { supervisor_id: "h:1", since: "2026-10-03T00:00:00Z", last_seen_at: "2026-10-03T00:00:30Z" } }),
                  bot({ id: "sb_other", agent_id: "ua_other" })];
    stubs.automations = [{ id: "au_1", name: "Daily as the agent", enabled: true, agent_id: "ua_1",
                           effects: [] } as unknown as Automation];
    const openAutomation = vi.fn();
    render(<AgentDoors agent={agent} onOpenAutomation={openAutomation} onChat={() => {}} />);
    await screen.findByText("salesbot");
    expect(screen.queryByText("sb_other")).toBeNull();
    expect(screen.getByText("listening")).toBeInTheDocument();
    expect(screen.getByText("Daily as the agent")).toBeInTheDocument();
    expect(screen.getAllByText("not built yet")).toHaveLength(2);
    await userEvent.click(screen.getByRole("button", { name: "Open automation" }));
    expect(openAutomation).toHaveBeenCalledWith("au_1");
  });

  it("a bot nobody listens for says so, with the command", async () => {
    stubs.bots = [bot({})];
    stubs.automations = [];
    render(<AgentDoors agent={agent} />);
    await screen.findByText("salesbot");
    expect(screen.getByText("not listening")).toBeInTheDocument();
    expect(screen.getByText(/npm run dev/)).toBeInTheDocument();
    expect(screen.getByText("No automation runs as this agent")).toBeInTheDocument();
  });

  it("a rejected read is said, never rendered as 'no doors'", async () => {
    stubs.reject = true;
    render(<AgentDoors agent={agent} />);
    await screen.findByText(/Could not read this agent's doors/);
    expect(screen.queryByText("No Slack bot fronts this agent")).toBeNull();
    stubs.reject = false;
  });

  it("the six words each carry one sentence", () => {
    for (const word of ["built-in", "runner", "goldens", "probation", "grant", "door"] as const) {
      expect(TERMS[word].length).toBeGreaterThan(40);
    }
  });
});
