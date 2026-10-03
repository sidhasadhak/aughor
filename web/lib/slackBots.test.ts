import { describe, expect, it } from "vitest";
import type { SlackBotSummary, UserAgent } from "@/lib/api";
import { bindingProblem, patchBodyFor, slackStepBotNote } from "./slackBots";

const bot: SlackBotSummary = {
  id: "sb_1", name: "Aughor", enabled: true, disabled_reason: "", listening: null,
  liveness_hint: "", team_id: "T1", bot_user_id: "U1", agent_id: "ua_1", connection_id: "",
  agent_view: false,
};
const agent = (over: Partial<UserAgent> = {}): UserAgent => ({
  id: "ua_1", name: "The Look Analyst", instructions: "", connection_id: "8233e4fd",
  schema_scope: "thelook", doc_ids: [], pack_ids: [], tool_grants: [], owner: "",
  enabled: true, last_eval: null, config_rev: "", eval_basis: "current" as UserAgent["eval_basis"],
  created_at: "", updated_at: "", ...over,
});

describe("patchBodyFor", () => {
  it("carries every plain field, because the server replaces what it is not sent", () => {
    const body = patchBodyFor(bot, { connection_id: "8233e4fd" });
    expect(body).toEqual({
      name: "Aughor", enabled: true, agent_id: "ua_1", connection_id: "8233e4fd", agent_view: false,
      channel_id: "",   // AO-2f — a plain field like the rest, carried even when unset
    });
  });
  it("applies the change over the record", () => {
    expect(patchBodyFor(bot, { enabled: false }).enabled).toBe(false);
    expect(patchBodyFor(bot, { name: "TheLook" }).name).toBe("TheLook");
  });
  it("carries agent_view even when an older record never had the field", () => {
    const legacy = { ...bot, agent_view: undefined as unknown as boolean };
    expect(patchBodyFor(legacy, {}).agent_view).toBe(false);
  });
});

describe("bindingProblem", () => {
  it("is silent for a bot with no agent", () => {
    expect(bindingProblem({ ...bot, agent_id: "" }, [agent()])).toBeNull();
  });
  it("is silent when the bot asks on the agent's bound connection", () => {
    expect(bindingProblem({ ...bot, connection_id: "8233e4fd" }, [agent()])).toBeNull();
  });
  it("is silent when the agent is bound to nothing", () => {
    expect(bindingProblem(bot, [agent({ connection_id: "" })])).toBeNull();
  });
  it("names the mismatch, with the reader's names for both connections", () => {
    const names: Record<string, string> = { "8233e4fd": "theLook", other: "Superstore" };
    const msg = bindingProblem({ ...bot, connection_id: "other" }, [agent()], id => names[id] ?? id);
    expect(msg).toContain("bound to theLook");
    expect(msg).toContain("asks on Superstore");
    expect(msg).toContain("409");
  });
  it("treats an empty connection as a mismatch — the supervisor's default is not the agent's", () => {
    expect(bindingProblem(bot, [agent()])).toContain("asks on no connection");
  });
  it("says when the agent is disabled or gone", () => {
    expect(bindingProblem(bot, [agent({ enabled: false })])).toContain("disabled");
    expect(bindingProblem(bot, [])).toContain("no longer exists");
  });
});

describe("slackStepBotNote", () => {
  const live = { ...bot, id: "sb_live", name: "Aughor", enabled: true };
  it("is silent for a bot that is there and running, and for an unset step", () => {
    expect(slackStepBotNote("sb_live", [live])).toBe("");
    expect(slackStepBotNote("", [live])).toBe("");
    expect(slackStepBotNote(undefined, [live])).toBe("");
  });
  it("says so when the step names a bot that was deleted", () => {
    expect(slackStepBotNote("sb_gone", [live])).toContain("no longer in the registry");
  });
  it("says so when the step names a paused bot, by name", () => {
    expect(slackStepBotNote("sb_live", [{ ...live, enabled: false }])).toContain("Aughor is paused");
  });
  it("leaves a bound value alone — a binding is not an id", () => {
    expect(slackStepBotNote({ $from: "item.bot" }, [live])).toBe("");
  });
});
