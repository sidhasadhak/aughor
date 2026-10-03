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

export type SlackBotChanges = Partial<Pick<SlackBotPatch, "name" | "enabled" | "agent_id" | "connection_id" | "channel_id" | "rehearse">>;

export function patchBodyFor(bot: SlackBotSummary, changes: SlackBotChanges): SlackBotPatch {
  return {
    name: bot.name,
    enabled: bot.enabled,
    agent_id: bot.agent_id,
    connection_id: bot.connection_id,
    // Carried, never edited here: it must agree with the manifest the app was created
    // from, and the create door is the one place that sets both in one act.
    agent_view: bot.agent_view ?? false,
    // AO-2f — the home channel is a plain field like the rest: a whole-record write.
    channel_id: bot.channel_id ?? "",
    // AO-6 — likewise rehearse: an edit that omitted it would switch it off.
    rehearse: bot.rehearse ?? false,
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

/** What a "Post to Slack" step should say about the bot it names, or "" when the bot is
 *  there and running.
 *
 *  The step stores a bot ID. Delete or pause that bot and the picker used to show
 *  "Post as…" — the stored id matched no option — while the step kept the dead id and
 *  saved it back on the next edit. A person changed the channel, saw nothing wrong, and
 *  the post failed later as "unknown Slack bot". A bound value (`{"$from": …}`) is not an
 *  id and is left alone. */
export function slackStepBotNote(botId: unknown, bots: SlackBotSummary[]): string {
  if (typeof botId !== "string" || !botId) return "";
  const bot = bots.find(b => b.id === botId);
  if (!bot) {
    return "This step posts as a bot that is no longer in the registry, so its post will fail. "
      + "Pick one of the bots above.";
  }
  if (!bot.enabled) {
    return `${bot.name} is paused, so this step's post will fail until it is resumed or another bot is picked.`;
  }
  return "";
}
