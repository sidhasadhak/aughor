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
import { Chat, StreamingPlan, type Adapter, type FileUpload, type Message, type SentMessage, type StateAdapter, type Thread } from "chat";

import { csvFilename, renderGrid, worthShowing, type Grid } from "./artifacts.js";
import type { ChartRenderer } from "./chart.js";
import type { ArrivalPoster, AskChunk, AskStream, FactChecker, TurnArtifacts, VerdictPoster } from "./aughor.js";
import { createTurnMap } from "./turnmap.js";

export const BOT_USERNAME = "aughor";

const USAGE =
  "Ask me a data question — e.g. “@aughor why did revenue dip last month?” " +
  "I answer from the connected warehouse, with a Trust Receipt behind every number.";

/** HB-5 — the note verb: "@aughor note: carrier X was on strike last week" files the
 *  sentence as a NOTE on the object this thread is about (the thread→object link HB-3
 *  filed), instead of asking a question. The COLON is the verb — "note that revenue
 *  dipped?" is prose and still asks. Deterministic; never a guess. */
const NOTE_VERB = /^note:\s*/i;

/** Idea 7 — the check verb: "@aughor check: <memo>" checks every number in the memo
 *  against the data instead of asking a question. The COLON is the verb, as for `note:`. */
const CHECK_VERB = /^check:\s*/i;

/** A Slack thread id's (channel, root ts), for the arrivals door. The adapter's ids
 *  are colon-joined and prefixed ("slack:C123:1712.34"); the root ts is always the
 *  digits.digits tail. Null when the id does not carry one — the caller says so
 *  honestly instead of filing against a guess. */
export function parseSlackThreadRef(threadId: string): { channel: string; ts: string } | null {
  const parts = (threadId ?? "").split(":").filter(Boolean);
  const ts = parts[parts.length - 1] ?? "";
  if (!/^\d+\.\d+$/.test(ts) || parts.length < 2) return null;
  const channel = parts[parts.length - 2];
  return channel ? { channel, ts } : null;
}

/** The question, with the bot's own mention tokens stripped off. */
export function stripMention(text: string, userName: string = BOT_USERNAME): string {
  return text
    .replace(/<@[A-Z0-9]+>/g, " ")   // Slack raw mention tokens
    .replace(/@[UW][A-Z0-9]{7,}\b/g, " ") // the SDK's normalized form: @ + user id, no brackets
    .replace(new RegExp(`@${userName}\\b`, "gi"), " ")
    .replace(/\s+/g, " ")
    .trim();
}

export function buildBot({
  ask,
  renderChart,
  adapters,
  state,
  postArrival,
  factCheck,
  postVerdict,
  turnMapFile,
  rehearse = false,
}: {
  ask: AskStream;
  /** Absent in tests that only care about the text half. */
  renderChart?: ChartRenderer;
  adapters: Record<string, Adapter>;
  state: StateAdapter;
  /** HB-5 — absent in tests that only exercise the ask half. */
  postArrival?: ArrivalPoster;
  /** Idea 7 — absent in tests that only exercise the ask half. */
  factCheck?: FactChecker;
  /** TJ-4 — a reaction is a verdict; absent in tests that only exercise the ask half. */
  postVerdict?: VerdictPoster;
  /** AO-7b — where the message→turn map is persisted; absent (tests) keeps it in memory. */
  turnMapFile?: string;
  /** AO-6 — REHEARSE: a mention in a channel is answered in the asker's DM first and
   *  reaches the channel on their ✅ there. From the bot's record; off by default. */
  rehearse?: boolean;
}): Chat {
  const bot = new Chat({
    userName: BOT_USERNAME,
    adapters,
    state,
    // debug shows every incoming envelope — the difference between "Slack never
    // sent the event" and "it arrived and nothing matched" is invisible at info.
    logger: (process.env.LOG_LEVEL as "debug" | "info" | undefined) ?? "info",
  });

  // TJ-4 — which message carried which turn. The streamed answer and its exhibits by
  // message id, and the thread's latest answer as the fallback for a reaction on any
  // other message in the thread. Bounded, and since AO-7b PERSISTED (`turnmap.ts`): a
  // restart used to forget every answer, and a ✅ the next morning recorded nothing.
  // A reaction on an answer the map does not hold still records nothing rather than a guess.
  const byMessage = createTurnMap<TurnArtifacts>({
    file: turnMapFile ? turnMapFile.replace(/\.json$/, "") + ".messages.json" : "",
    log: (l) => console.log(l),
  });
  const byThread = createTurnMap<TurnArtifacts>({
    file: turnMapFile ? turnMapFile.replace(/\.json$/, "") + ".threads.json" : "",
    log: (l) => console.log(l),
  });
  const remember = (threadId: string, turn: TurnArtifacts | null, ...ids: (string | undefined)[]) => {
    if (!turn?.investigationId) return;
    for (const id of ids) if (id) byMessage.set(id, turn);
    byThread.set(threadId, turn);
  };
  // AO-6 — the rehearsals waiting on a click: the DM's messages (and the DM itself) → the
  // channel thread the mention came from, with the text and exhibits that answered it.
  // Persisted beside the turn maps for the same reason: a ✅ tomorrow must still promote.
  const rehearsals = createTurnMap<Rehearsal>({
    file: turnMapFile ? turnMapFile.replace(/\.json$/, "") + ".rehearsals.json" : "",
    limit: 100,
    log: (l) => console.log(l),
  });
  const ACCEPT = new Set(["white_check_mark", "heavy_check_mark", "✅", "✔️"]);
  const REJECT = new Set(["x", "negative_squared_cross_mark", "❌", "❎"]);
  bot.onReaction(async (event) => {
    // A verdict is not un-said by taking the emoji back; only an added ✅ / ❌ counts.
    if (!event.added) return;
    const raw = String(event.rawEmoji ?? "").replace(/^:|:$/g, "");
    const verdict = ACCEPT.has(raw) ? "accept" : REJECT.has(raw) ? "reject" : null;
    if (!verdict) return;
    const turn = byMessage.get(event.messageId) ?? byThread.get(event.threadId);
    const who = event.user?.userName || event.user?.userId || "someone";
    if (turn && postVerdict) {
      // Law 8: the message carries no receipt and the reaction needs none — nothing is posted back.
      // AO-7b: the headline is left to the verdict door, which reads the answer's own from the
      // turn's record — this process only ever knew the QUESTION, and sent it as the headline.
      await postVerdict({
        investigationId: turn.investigationId, verdict,
        note: `slack reaction :${raw}: by ${who} on "${turn.question.slice(0, 120)}"`,
      });
    }

    // AO-6 — on a rehearsed answer the same click is the promotion: ✅ posts the answer in
    // the thread it was asked in (and the verdict above has already said "accept"); ❌ drops
    // it. Once — the rehearsal's keys leave the map together, so a second ✅ posts nothing.
    const rehearsal = rehearsals.get(event.messageId) ?? rehearsals.get(event.threadId);
    if (!rehearsal) return;
    rehearsals.delete(...rehearsal.keys);
    const here = bot.thread(event.threadId);
    if (verdict === "reject") {
      await here.post("Dropped — nothing was posted in the channel.");
      return;
    }
    const origin = bot.thread(rehearsal.originThreadId);
    await origin.post(rehearsal.text || rehearsal.turn?.envelope?.headline || "(the answer had no text)");
    const exhibit = await postExhibits(origin, rehearsal.turn, renderChart);
    // The promoted copy is an answer in its own right: a ✅ on it in the channel is a verdict.
    remember(origin.id, rehearsal.turn, exhibit?.id);
    const ref = parseSlackThreadRef(rehearsal.originThreadId);
    await here.post(`Posted in ${ref ? `<#${ref.channel}>` : "the channel"}.`);
  });

  // AO-6 — REHEARSE: the mention's half of "a bot answers in a private thread first;
  // promotion to a channel is a click" (the automation half is the departure gate's
  // approval door). The answer streams into the ASKER's DM — the one place only they
  // read — with a line saying where it came from and what ✅ / ❌ do; the channel gets an
  // ephemeral note to the asker where the transport has one, and nothing public. The
  // session stays the channel thread's, so the promoted answer's follow-ups compose there.
  const rehearseMention = async (thread: Thread, message: Message, question: string) => {
    const author = message.author;
    if (!author?.userId) {
      await thread.post("Rehearsing — I answer privately first, but this message names no asker, so I can't.");
      return;
    }
    let dm: Thread;
    try {
      dm = await bot.openDM(author);
    } catch (err) {
      await thread.post("Rehearsing — I answer privately first, but I couldn't open a direct message with you "
        + `(${String((err as Error)?.message ?? err)}).`);
      return;
    }
    const ref = parseSlackThreadRef(thread.id);
    const where = ref ? `<#${ref.channel}>` : "that channel";
    const prelude = await dm.post(
      `You asked in ${where}: “${question}”\n\n`
      + "Rehearsal — only you see this. React ✅ here to post the answer in that thread, ❌ to drop it.");
    try {
      await thread.postEphemeral(author,
        "Rehearsing — I've answered you privately. A ✅ there posts it here.", { fallbackToDM: false });
    } catch { /* a transport with no ephemeral: the DM is the whole answer */ }

    let turn: TurnArtifacts | null = null;
    const stream = ask(question, {
      sessionId: thread.id,
      signal: dm.signal,
      principalRef: `slack:${author.userId}`,
      onTurn: (a) => { turn = a; },
    });
    const captured: string[] = [];
    await dm.post(new StreamingPlan(captureText(withoutTables(stream), captured), { groupTasks: "plan" }));
    const exhibit = await postExhibits(dm, turn, renderChart);
    remember(dm.id, turn, exhibit?.id, prelude?.id);
    const keys = [prelude?.id, exhibit?.id, dm.id].filter((k): k is string => Boolean(k));
    const held: Rehearsal = { originThreadId: thread.id, question, text: captured.join(""), turn, keys };
    for (const k of keys) rehearsals.set(k, held);
  };

  bot.onNewMention(async (thread, message) => {
    const question = stripMention(message.text ?? "");
    if (!question) {
      await thread.post(USAGE);
      return;
    }

    // HB-5 — the note verb takes the arrival path, never the ask path. The door does
    // customs and staging; this relays and repeats the door's own sentence, and an
    // unfiled thread gets the honest refusal rather than a silently redirected ask.
    if (postArrival && NOTE_VERB.test(question)) {
      const ref = parseSlackThreadRef(thread.id);
      if (!ref) {
        await thread.post("I can't tell which thread this is, so I can't file the note.");
        return;
      }
      const result = await postArrival({
        channel: ref.channel,
        threadTs: ref.ts,
        text: question.replace(NOTE_VERB, "").trim(),
        author: message.author?.fullName ?? "",
        authorRef: message.author?.userId ? `slack:${message.author.userId}` : "",
      });
      await thread.post(
        result.ok
          ? `Noted — staged for review. ${result.detail}`
          : `Not filed: ${result.detail}`,
      );
      return;
    }

    // Idea 7 — the check verb takes the fact-check door, never the ask path: the door
    // compiles each claim to grounded SQL and answers with an envelope, which this
    // thread renders like any answer — prose first, the verdict grid as the exhibit.
    if (factCheck && CHECK_VERB.test(question)) {
      const text = question.replace(CHECK_VERB, "").trim();
      if (!text) {
        await thread.post("Paste the memo after `check:` and I'll check every number in it against the data.");
        return;
      }
      const result = await factCheck(text);
      if (!result.ok || !result.envelope) {
        await thread.post(`Not checked: ${result.detail || "the door returned no result"}`);
        return;
      }
      const env = result.envelope;
      await thread.post([env.headline, env.body].filter(Boolean).join("\n\n"));
      await postExhibits(thread, {
        investigationId: String((env.provenance as { investigation_id?: unknown })?.investigation_id ?? ""),
        question: env.question, sessionId: thread.id,
        columns: env.grid?.columns ?? [], rows: env.grid?.rows ?? [],
        chartType: "auto", chartConfig: {}, envelope: env,
      });
      return;
    }

    // AO-6 — a rehearsing bot answers a CHANNEL mention privately first. A mention that
    // already sits in a DM has no channel to promote to and is answered where it was asked.
    if (rehearse && !thread.isDM) {
      await rehearseMention(thread, message, question);
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
      // RC-4 — the asker, so the turn is attributed to a person. `author.userId` is the
      // stable per-workspace Slack id and is always on the envelope; before this it was
      // read only to be STRIPPED from the question text, so every Slack turn filed under
      // nobody. Absent, the turn is honestly unattributed rather than falsely attributed.
      //
      // Not `message.userKey`: the SDK's cross-platform key needs a `ChatConfig.identity`
      // resolver, which would put identity resolution in the transport. Aughor resolves
      // `slack:<id>` server-side against its own link table — the Python API stays the
      // only brain, and one scheme serves every door rather than one per SDK.
      principalRef: message.author?.userId ? `slack:${message.author.userId}` : undefined,
      onTurn: (a) => { turn = a; },
    });

    await thread.post(new StreamingPlan(
      // CP-4 — the grid is ONE field of the answer, and this door renders it once, in
      // the exhibits. A table the model typed into its prose is the same rows again, so
      // it is held back as it streams: the platform's envelope carries the lifted copy.
      withoutTables(stream),
      // One plan block beats a scatter of inline cards: a deep run's phases are
      // one piece of work with parts, and a thread reads better with a single
      // block that fills in than with eight cards interleaved through prose.
      { groupTasks: "plan" },
    ));

    // The streamed answer's post hands back the plan, not a message id, so the exhibits'
    // message is the one remembered by id and the answer itself resolves by its thread.
    const exhibit = await postExhibits(thread, turn, renderChart);
    remember(thread.id, turn, exhibit?.id);
  });

  return bot;
}

/** AO-6 — a rehearsed answer waiting on the asker's click. */
interface Rehearsal {
  /** The channel thread the mention came from — where ✅ posts the answer. */
  originThreadId: string;
  question: string;
  /** The prose as it streamed into the DM (tables already held back), re-posted verbatim. */
  text: string;
  turn: TurnArtifacts | null;
  /** Every key this rehearsal sits under, so promotion or drop removes all of them at once. */
  keys: string[];
}

/** Pass the stream through unchanged while keeping its text, for the promoted copy. */
async function* captureText(src: AsyncIterable<AskChunk>, into: string[]): AsyncIterable<AskChunk> {
  for await (const c of src) {
    if (typeof c === "string") into.push(c);
    yield c;
  }
}

/** A GFM delimiter row: pipes, dashes, colons, spaces — and at least one dash. */
const isDelimiterRow = (line: string): boolean => {
  const s = line.trim();
  return s.includes("-") && s.includes("|") && /^\|?[\s:|-]+\|?$/.test(s);
};

/**
 * Drop every markdown table from the streamed prose, and nothing else — without
 * holding the prose back.
 *
 * The stream arrives in arbitrary chunks. A line whose first character is not a pipe is
 * prose, and it streams the moment that character is known — mid-line, so a paragraph
 * still types itself out. A line that opens with a pipe (or is a delimiter row, or sits
 * inside a run already being held) is held with its run until the run ends; the run is
 * then dropped if a delimiter row sat under its first line (a table) and released whole
 * otherwise. What remains at the stream's end is judged the same way.
 *
 * Content-blind: only the delimiter's SHAPE decides, as the platform's own `lift_tables`
 * decides, so what this door drops is what the envelope carries as the grid. A table the
 * model writes WITHOUT a leading pipe is the one shape this streaming filter lets through;
 * the envelope still lifts it for every door that reads the fields.
 */
export async function* withoutTables(
  stream: AsyncIterable<AskChunk>,
): AsyncIterable<AskChunk> {
  let held: string[] = [];    // the run of table-shaped lines being judged
  let line = "";              // the current unterminated line, while still unjudged
  let released = false;       // the current line was judged prose and is streaming

  const flushHeld = (): string => {
    if (held.length === 0) return "";
    const isTable = held.length >= 2 && isDelimiterRow(held[1]);
    const out = isTable ? "" : held.map((l) => `${l}\n`).join("");
    held = [];
    return out;
  };
  const joinsRun = (l: string): boolean =>
    l.trimStart().startsWith("|") || isDelimiterRow(l) || (held.length > 0 && l.includes("|"));

  for await (const chunk of stream) {
    if (typeof chunk !== "string") {
      yield chunk;
      continue;
    }
    let out = "";
    let rest = chunk;
    while (rest.length) {
      const nl = rest.indexOf("\n");
      const piece = nl === -1 ? rest : rest.slice(0, nl);
      rest = nl === -1 ? "" : rest.slice(nl + 1);
      if (released) {
        // Prose already streaming: straight through to the end of its line.
        out += nl === -1 ? piece : `${piece}\n`;
        if (nl !== -1) released = false;
        continue;
      }
      line += piece;
      if (nl === -1) {
        // Unterminated. Judge it as soon as its first character is known.
        const t = line.trimStart();
        if (t.length && !t.startsWith("|") && held.length === 0) {
          out += line;
          line = "";
          released = true;
        }
        continue;
      }
      if (joinsRun(line)) held.push(line);
      else out += `${flushHeld()}${line}\n`;
      line = "";
    }
    if (out) yield out;
  }
  if (line.length && joinsRun(line)) {
    held.push(line);
    line = "";
  }
  const tail = flushHeld() + line;
  if (tail) yield tail;
}

/**
 * The turn's grid, chart and caveats, as a follow-up message — selected from the
 * envelope when the platform sent one, from the grid frames when it did not.
 *
 * Silent by design when there is nothing to add: an answer whose result is one
 * number does not get a one-cell table under it, and a grid with no honest
 * chart does not get a picture of nothing (the renderer's own 204 says so).
 * Provenance is a field this door does not take (the user's 2026-09-22 rule:
 * no receipts on Slack messages).
 */
const MAX_CAVEATS = 2;

async function postExhibits(
  thread: Pick<Thread, "post">,
  turn: TurnArtifacts | null,
  renderChart?: ChartRenderer,
): Promise<SentMessage | null> {
  if (!turn) return null;
  const env = turn.envelope ?? null;
  const grid: Grid = env?.grid ?? { columns: turn.columns, rows: turn.rows };
  const chartType = env?.chart?.chart_type || turn.chartType || "auto";
  const chartConfig = env?.chart?.chart_config ?? turn.chartConfig;
  const caveats = (env?.caveats ?? []).slice(0, MAX_CAVEATS).map((c) => `⚠️ ${c}`);
  const showGrid = worthShowing(grid);

  const { markdown: table, csv } = showGrid ? renderGrid(grid) : { markdown: "", csv: null };
  const markdown = [table, caveats.join("\n")].filter(Boolean).join("\n\n");
  const files: FileUpload[] = [];

  const png = showGrid && renderChart
    ? await renderChart({
        columns: grid.columns,
        rows: grid.rows,
        chart_type: chartType,
        chart_config: chartConfig,
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

  if (!markdown && files.length === 0) return null;
  return await thread.post({ markdown, ...(files.length ? { files } : {}) });
}
