/**
 * The bot half of RC-1/RC-2: mention in, streamed governed answer out — then
 * the visual half of that answer as its own message.
 *
 * Built as a factory so the tests drive the REAL Chat pipeline (mention
 * detection, threading, post streaming) with a mock adapter and a fake ask —
 * the seam that fails if the handler is unplugged, not just if the transport
 * misparses. The Python API stays the only brain; nothing here retries,
 * rephrases, or interprets.
 *
 * RC-2 gives a turn two messages, not one, and the split is deliberate: the
 * answer streams live and must not be held back waiting on a chart render or a
 * file upload, and Slack cannot stream text and attach a file in the same
 * message anyway. So the prose (with its way back to the platform) posts as it
 * arrives, and the exhibits follow once the run has settled — and only when
 * there is something worth exhibiting.
 */
import { Chat, StreamingPlan, type Adapter, type FileUpload, type StateAdapter, type Thread } from "chat";

import { csvFilename, deepLink, renderGrid, worthShowing } from "./artifacts.js";
import type { ChartRenderer } from "./chart.js";
import type { AskChunk, AskStream, TurnArtifacts } from "./aughor.js";

export const BOT_USERNAME = "aughor";

const USAGE =
  "Ask me a data question — e.g. “@aughor why did revenue dip last month?” " +
  "I answer from the connected warehouse, with a Trust Receipt behind every number.";

/** The question, with the bot's own mention tokens stripped off. */
export function stripMention(text: string, userName: string = BOT_USERNAME): string {
  return text
    .replace(/<@[A-Z0-9]+>/g, " ")   // Slack raw mention tokens
    .replace(/@[UW][A-Z0-9]{7,}\b/g, " ") // the SDK's normalized form: @ + user id, no brackets
    .replace(new RegExp(`@${userName}\\b`, "gi"), " ")
    .replace(/\s+/g, " ")
    .trim();
}

/**
 * The answer, then the way back to it. Slack is the doorway — the interactive
 * chart, the whole result, the SQL and the Trust Receipt live in Aughor — so
 * every answered turn ends with the link that reaches them.
 */
async function* withDeepLink(
  stream: AsyncIterable<AskChunk>,
  link: string,
): AsyncIterable<AskChunk> {
  let sawText = false;
  for await (const chunk of stream) {
    if (typeof chunk === "string" || chunk.type === "markdown_text") sawText = true;
    yield chunk;
  }
  if (sawText) yield `\n\n<${link}|Open in Aughor →>`;
}

export function buildBot({
  ask,
  renderChart,
  adapters,
  state,
  webUrl,
}: {
  ask: AskStream;
  /** Absent in tests that only care about the text half. */
  renderChart?: ChartRenderer;
  adapters: Record<string, Adapter>;
  state: StateAdapter;
  webUrl?: string;
}): Chat {
  const bot = new Chat({
    userName: BOT_USERNAME,
    adapters,
    state,
    // debug shows every incoming envelope — the difference between "Slack never
    // sent the event" and "it arrived and nothing matched" is invisible at info.
    logger: (process.env.LOG_LEVEL as "debug" | "info" | undefined) ?? "info",
  });

  bot.onNewMention(async (thread, message) => {
    const question = stripMention(message.text ?? "");
    if (!question) {
      await thread.post(USAGE);
      return;
    }

    let turn: TurnArtifacts | null = null;
    // The thread IS the conversation: its id rides as session_id, so follow-up
    // mentions in the same thread compose on the same Aughor conversation.
    //
    // `thread.signal` is the platform's stop button. Passed here it does two
    // things: the SDK stops consuming the stream, and the transport cancels the
    // run server-side — which since FL-1 detached producers from viewers is the
    // only thing that actually stops the spend.
    const stream = ask(question, {
      sessionId: thread.id,
      signal: thread.signal,
      onTurn: (a) => { turn = a; },
    });

    const link = webUrl ? deepLink(webUrl, thread.id) : "";
    await thread.post(new StreamingPlan(
      link ? withDeepLink(stream, link) : stream,
      // One plan block beats a scatter of inline cards: a deep run's phases are
      // one piece of work with parts, and a thread reads better with a single
      // block that fills in than with eight cards interleaved through prose.
      { groupTasks: "plan" },
    ));

    await postExhibits(thread, turn, renderChart);
  });

  return bot;
}

/**
 * The turn's grid and chart, as a follow-up message.
 *
 * Silent by design when there is nothing to add: an answer whose result is one
 * number does not get a one-cell table under it, and a grid with no honest
 * chart does not get a picture of nothing (the renderer's own 204 says so).
 */
async function postExhibits(
  thread: Pick<Thread, "post">,
  turn: TurnArtifacts | null,
  renderChart?: ChartRenderer,
): Promise<void> {
  if (!turn || !worthShowing(turn)) return;

  const { markdown, csv } = renderGrid(turn);
  const files: FileUpload[] = [];

  const png = renderChart
    ? await renderChart({
        columns: turn.columns,
        rows: turn.rows,
        chart_type: turn.chartType || "auto",
        chart_config: turn.chartConfig,
        title: turn.question,
      })
    : null;
  if (png) files.push({ data: png, filename: "chart.png", mimeType: "image/png" });
  if (csv) {
    files.push({
      data: Buffer.from(csv, "utf8"),
      filename: csvFilename(turn.question),
      mimeType: "text/csv",
    });
  }

  if (!markdown && files.length === 0) return;
  await thread.post({ markdown, ...(files.length ? { files } : {}) });
}
