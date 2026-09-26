/**
 * Slack bot records — the two rules the Integrations page must not get wrong.
 *
 * 1. An update REPLACES every plain field. The server keeps the stored secrets when the
 *    payload omits them (`merge_secrets`), but name, enabled, agent and connection are
 *    taken as sent — a partial body blanks the rest. `patchBodyFor` is the only way a
 *    body gets built here, so a one-field change on screen is a whole-record write on
 *    the wire.
 *
 * 2. A bot answers AS an agent, and an agent may be BOUND to a connection. The ask door
 *    refuses (409) when the two disagree — including when the bot names no connection at
 *    all, because the supervisor then asks on its own default, which is not the agent's.
 *    `bindingProblem` says so on the record itself, where the person who can fix it is
 *    looking, instead of in a Slack thread as "did not answer (HTTP 409)".
 */
import type { SlackBotPatch, SlackBotSummary, UserAgent } from "@/lib/api";

export type SlackBotChanges = Partial<Pick<SlackBotPatch, "name" | "enabled" | "agent_id" | "connection_id">>;

export function patchBodyFor(bot: SlackBotSummary, changes: SlackBotChanges): SlackBotPatch {
  return {
    name: bot.name,
    enabled: bot.enabled,
    agent_id: bot.agent_id,
    connection_id: bot.connection_id,
    // Carried, never edited here: it must agree with the manifest the app was created
    // from, and the create door is the one place that sets both in one act.
    agent_view: bot.agent_view ?? false,
    ...changes,
  };
}

/** Why @mentions of this bot would be refused, or null when they would be answered.
 *  `nameOf` renders a connection id for the reader (the id itself when unknown). */
export function bindingProblem(
  bot: SlackBotSummary,
  agents: UserAgent[],
  nameOf: (connectionId: string) => string = id => id,
): string | null {
  if (!bot.agent_id) return null;
  const agent = agents.find(a => a.id === bot.agent_id);
  if (!agent) {
    return `Answers as an agent that no longer exists (${bot.agent_id}) — @mentions are refused until another is chosen.`;
  }
  if (agent.enabled === false) {
    return `${agent.name} is disabled — @mentions are refused until the agent is enabled.`;
  }
  if (agent.connection_id && bot.connection_id !== agent.connection_id) {
    const asks = bot.connection_id ? nameOf(bot.connection_id) : "no connection";
    return `${agent.name} is bound to ${nameOf(agent.connection_id)} but this bot asks on ${asks} — `
      + "@mentions are refused (409) until the two match.";
  }
  return null;
}
