/**
 * The transport half of RC-1/RC-2: one Aughor `/ask` turn, folded into an
 * `AsyncIterable` that `thread.post` can stream into Slack.
 *
 * Deliberately thin. The question goes to the `/ask` door at `depth: "auto"` —
 * the same deterministic router the web chat's auto path uses, so a quick
 * question answers in seconds and a deep or wide one runs the full governed
 * path — and the Slack thread id rides as `session_id`, so the turn files under
 * a conversation (FL-6) exactly as a web turn does.
 *
 * Frame → text mapping is REPLACE-aware: Aughor's `*_delta` partials carry the
 * FULL text-so-far per frame (the resume hub's snapshot contract), while a
 * `thread.post` iterable APPENDS every yield. So this tracks what it already
 * yielded per channel and emits only suffixes — the one non-obvious piece of
 * the whole file.
 *
 * RC-2 adds three things that do not change that shape:
 *   - progress frames become `task_update` chunks (see `progress.ts`), yielded
 *     into the same stream the text rides;
 *   - the turn's grid and chart ride out through `onTurn` once the run settles,
 *     for the caller to post as a table, a CSV and a picture;
 *   - an abandoned run is CANCELLED, not merely disconnected. Since FL-1
 *     detached the producer from its viewer, dropping the SSE connection no
 *     longer stops the work — it just stops anyone watching it burn budget.
 */
import type { StreamChunk } from "chat";

import { createProgressCards } from "./progress.js";

/** What the turn produced besides prose — the visual half of the answer. */
export interface TurnArtifacts {
  investigationId: string;
  question: string;
  sessionId: string;
  columns: string[];
  rows: unknown[][];
  chartType: string;
  chartConfig: Record<string, unknown>;
}

export interface AskOptions {
  sessionId: string;
  /** The platform's cancellation signal — Slack's stop button aborts it. */
  signal?: AbortSignal;
  /** Called once, when a turn settles with a grid worth showing. */
  onTurn?: (artifacts: TurnArtifacts) => void;
  /**
   * RC-4 — who is asking, as `slack:<user id>`. The bot authenticates as itself and
   * reports the human on whose behalf it asks, so a turn is attributed to a person
   * rather than to nobody. Aughor honours it only when no authenticated identity is
   * already in scope, so this can never be used to claim to BE someone else.
   */
  principalRef?: string;
}

export type AskChunk = string | StreamChunk;
export type AskStream = (question: string, opts: AskOptions) => AsyncIterable<AskChunk>;

interface Env {
  AUGHOR_API_URL?: string;
  AUGHOR_API_KEY?: string;
  AUGHOR_CONNECTION_ID?: string;
}

const asText = (v: unknown): string => (typeof v === "string" ? v : "");

/** Yield only what `full` adds beyond `seen` (REPLACE partial → APPEND stream). */
function suffix(seen: string, full: string): string {
  if (!full || full.length <= seen.length) return "";
  return full.startsWith(seen) ? full.slice(seen.length) : "";
}

export function createAskStream(
  env: Env = process.env,
  fetchImpl: typeof fetch = fetch,
): AskStream {
  const base = (env.AUGHOR_API_URL ?? "http://127.0.0.1:8000").replace(/\/+$/, "");
  const connection = env.AUGHOR_CONNECTION_ID ?? "workspace";
  const authHeaders: Record<string, string> =
    env.AUGHOR_API_KEY ? { "x-api-key": env.AUGHOR_API_KEY } : {};

  /**
   * Stop the run itself, not just our view of it.
   *
   * FL-1 detached the producer from its SSE consumers so a refresh would stop
   * killing a deep run. The cost of that win is this: after detachment, walking
   * away leaves a supervised kernel job running to completion against a budget
   * nobody is watching. Cancelling the job is the only legitimate kill, and
   * `/investigations/{id}/cancel` is the door to it.
   *
   * Sent WITHOUT the aborted signal — the whole point is that this request must
   * outlive the one that was just abandoned.
   */
  async function cancel(investigationId: string): Promise<void> {
    try {
      await fetchImpl(`${base}/investigations/${encodeURIComponent(investigationId)}/cancel`, {
        method: "POST",
        headers: { "content-type": "application/json", ...authHeaders },
      });
    } catch {
      // Best-effort: the run's own budget still bounds it, and there is no
      // longer a thread to report this into.
    }
  }

  return async function* ask(question, { sessionId, signal, onTurn, principalRef }) {
    const res = await fetchImpl(`${base}/ask`, {
      method: "POST",
      signal,
      headers: {
        "content-type": "application/json",
        accept: "text/event-stream",
        ...authHeaders,
      },
      body: JSON.stringify({
        question,
        connection_id: connection,
        depth: "auto",
        session_id: sessionId,
        ...(principalRef ? { principal_ref: principalRef } : {}),
      }),
    });
    if (!res.ok || !res.body) {
      yield `⚠️ Aughor did not answer (HTTP ${res.status}) — is the API running at ${base}?`;
      return;
    }

    let headline = "";
    let narrative = "";
    let sawText = false;
    let settled = false;
    const cards = createProgressCards();
    const artifacts: TurnArtifacts = {
      investigationId: "", question, sessionId,
      columns: [], rows: [], chartType: "", chartConfig: {},
    };
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    try {
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        // SSE frames are `data: {json}` blocks separated by a blank line.
        for (;;) {
          const cut = buffer.indexOf("\n\n");
          if (cut < 0) break;
          const block = buffer.slice(0, cut);
          buffer = buffer.slice(cut + 2);
          const line = block.split("\n").find((l) => l.startsWith("data: "));
          if (!line) continue;
          let frame: Record<string, unknown>;
          try {
            frame = JSON.parse(line.slice(6));
          } catch {
            continue; // a malformed frame must not kill the whole answer
          }

          // Progress frames become task cards; every other frame maps to none.
          for (const card of cards(frame)) yield card;

          switch (frame.type) {
            case "start":
              // The run's identity, and the only handle a cancel has.
              artifacts.investigationId = asText(frame.investigation_id);
              break;

            // The grid and its chart, kept for the artifacts post. Last-wins: a
            // conversational turn may run several queries, and the one the
            // closing prose is about is the one it finished on.
            case "columns":
              artifacts.columns = (frame.columns as string[]) ?? [];
              break;
            case "rows":
              artifacts.rows = (frame.rows as unknown[][]) ?? [];
              break;
            case "chart_type":
              artifacts.chartType = asText(frame.chart_type);
              break;
            case "chart_config":
              artifacts.chartConfig = (frame.chart_config as Record<string, unknown>) ?? {};
              break;

            case "headline_delta": {
              const add = suffix(headline, asText(frame.headline));
              if (add) {
                headline += add;
                sawText = true;
                yield add;
              }
              break;
            }
            case "narrative_delta": {
              const full = asText(frame.narrative);
              const add = suffix(narrative, full);
              if (add) {
                if (!narrative && sawText) yield "\n\n";
                narrative += add;
                sawText = true;
                yield add;
              }
              break;
            }
            case "headline":
            case "answer": {
              // Settled text wins over its stream — yield whatever the partial missed.
              const full = asText(frame.headline) || asText(frame.text) || asText(frame.answer);
              const add = suffix(headline, full);
              if (add) {
                headline = full;
                sawText = true;
                yield add;
              }
              break;
            }
            case "answer_report":
            case "report":
            case "explore_report": {
              // A deep or wide turn lands as a report. The full artifact lives in
              // Aughor; the thread gets the report's own words, never a summary
              // this transport invented.
              const rep = (frame.answer_report ?? frame.report ?? frame.explore_report ?? {}) as Record<string, unknown>;
              const head = asText(rep.headline) || asText(rep.answer) || asText(rep.summary);
              const body = asText(rep.summary) !== head ? asText(rep.summary) : "";
              const text = [head, body].filter(Boolean).join("\n\n")
                || "Deep analysis complete — open Aughor for the full report.";
              yield (sawText ? "\n\n" : "") + text;
              sawText = true;
              break;
            }
            case "error": {
              // The error frame carries R4's typed tail (reason/hint) AND the raw
              // provider text — which for a rate-limited chain is a wall of repeated
              // 429 JSON (seen live in a thread). A Slack surface gets ONE honest
              // sentence: the hint if the backend classified the error, else the
              // first attempt's text, bounded.
              const hint = asText(frame.hint);
              const first = (asText(frame.message) || asText(frame.error) || "the run failed")
                .split(" · ")[0]
                .trim();
              const short = first.length > 240 ? `${first.slice(0, 240)}…` : first;
              yield (sawText ? "\n\n" : "") + `⚠️ ${hint || short}`;
              // No artifacts: a failed turn has no result to exhibit, and half a
              // grid posted under a failure reads as a partial answer.
              return;
            }
            case "done":
              settled = true;
              onTurn?.(artifacts);
              return;
            default:
              break; // receipt/telemetry frames are web-surface concerns, not Slack text
          }
        }
      }
      // The stream ended without a `done` — a settled answer that never got its
      // terminal frame still earned its exhibits.
      if (!settled && sawText) onTurn?.(artifacts);
    } finally {
      reader.releaseLock();
      // Abandoned, not finished: the platform's stop button (or any abort)
      // reached us mid-run, so kill the work rather than merely stop watching.
      if (!settled && signal?.aborted && artifacts.investigationId) {
        await cancel(artifacts.investigationId);
      }
    }
  };
}
