/**
 * RC-2 — a deep run's stages, as Slack task cards.
 *
 * A deep or wide question is a multi-minute wait. On the web FL-5 turned that
 * wait into a run card; in Slack the platform-native equivalent is the
 * `task_update` chunk, which Slack renders as a live progress card and updates
 * in place when the same `id` comes back with a new status.
 *
 * So this maps Aughor's own progress vocabulary onto that id space, and the
 * mapping is the whole file. The rules that matter:
 *
 * - `phase_progress` and `phase_complete` SHARE a key space (`phase_id`), which
 *   is what lets one phase be one card that fills in rather than two cards that
 *   look like duplicate work. `phase_complete` carries the phase object, so the
 *   card can finally be titled with the phase's real name.
 * - A `task_update` must repeat its `title` on every update, so titles are
 *   remembered per id — otherwise a completing card renames itself back to its
 *   raw id.
 * - Nothing here invents an outcome. A phase that came back `skipped` or
 *   `partial` says so in its own output; Slack has only four statuses and
 *   silently promoting either one to "complete" would report work that did not
 *   happen.
 *
 * Frames with no honest card (sql, guard receipts, grid frames) map to nothing.
 * The card trail is about the work, not the machinery.
 */
import type { StreamChunk } from "chat";

const str = (v: unknown): string => (typeof v === "string" ? v : "");
const num = (v: unknown): number => (typeof v === "number" ? v : 0);

/** Slack cards are small; long prose belongs in the answer, not the trail. */
function cap(s: string, n: number): string {
  const t = s.trim().replace(/\s+/g, " ");
  return t.length > n ? `${t.slice(0, n - 1)}…` : t;
}

/** `root_cause` → `Root cause` — a last resort when no human name arrived. */
function humanize(id: string): string {
  const s = id.replace(/[_-]+/g, " ").trim();
  return s ? s[0].toUpperCase() + s.slice(1) : "Step";
}

/**
 * The phase's own status, mapped onto the four Slack allows. `partial` and
 * `skipped` have no Slack equivalent, so they land as `complete` with the word
 * kept in the output — a card that reads "complete" over a phase that skipped
 * is the kind of quiet overstatement this whole surface exists to avoid.
 */
function phaseStatus(status: string): { status: TaskStatus; prefix: string } {
  switch (status) {
    case "error":   return { status: "error", prefix: "" };
    case "running": return { status: "in_progress", prefix: "" };
    case "partial": return { status: "complete", prefix: "Partial — " };
    case "skipped": return { status: "complete", prefix: "Skipped — " };
    default:        return { status: "complete", prefix: "" };
  }
}

type TaskStatus = "pending" | "in_progress" | "complete" | "error";

export type ProgressMapper = (frame: Record<string, unknown>) => StreamChunk[];

export function createProgressCards(): ProgressMapper {
  // id → title. A card's title must be re-sent with every update, and the good
  // title usually arrives LATER than the card does (a phase is named when it
  // completes; a sub-question is named by the plan, then answered).
  const titles = new Map<string, string>();
  let hops = 0;

  const task = (
    id: string, title: string, status: TaskStatus,
    extra: { details?: string; output?: string } = {},
  ): StreamChunk => {
    const t = cap(title || titles.get(id) || humanize(id), 120);
    titles.set(id, t);
    return {
      type: "task_update", id, title: t, status,
      ...(extra.details ? { details: cap(extra.details, 200) } : {}),
      ...(extra.output ? { output: cap(extra.output, 300) } : {}),
    };
  };

  return (frame) => {
    switch (frame.type) {
      // The deep path's per-dimension scan, inside a phase that has not landed
      // yet. Same words the web uses for the same frame, so the two surfaces
      // narrate one run identically.
      case "phase_progress": {
        const id = str(frame.phase_id);
        if (!id) return [];
        const current = str(frame.current);
        const done = num(frame.done), total = num(frame.total);
        return [task(`phase-${id}`, titles.get(`phase-${id}`) ?? humanize(id), "in_progress", {
          details: current
            ? `Scanning ${current} · ${done}/${total}`
            : `Scanning dimensions · ${done}/${total}`,
        })];
      }

      case "phase_complete": {
        const phase = (frame.phase ?? {}) as Record<string, unknown>;
        const id = str(phase.phase_id);
        if (!id) return [];
        const { status, prefix } = phaseStatus(str(phase.status) || "complete");
        const summary = str(phase.summary) || str(phase.skipped_reason);
        return [task(`phase-${id}`, str(phase.phase_name) || humanize(id), status, {
          output: prefix || summary ? `${prefix}${summary}`.trim() : "",
        })];
      }

      // The wave's plan names every sub-question up front — the wait's real
      // denominator, and the reason a five-minute exploration reads as five
      // pieces of work rather than one silence.
      case "explore_plan": {
        const subs = (frame.sub_questions ?? []) as Record<string, unknown>[];
        if (!Array.isArray(subs) || subs.length === 0) return [];
        const plan: StreamChunk = {
          type: "plan_update",
          title: `Exploration · ${subs.length} sub-question${subs.length === 1 ? "" : "s"}`,
        };
        return [plan, ...subs.flatMap((s) => {
          const id = str(s.id);
          return id ? [task(`subq-${id}`, str(s.question) || humanize(id), "pending")] : [];
        })];
      }

      case "subq_answer": {
        const id = str(frame.subq_id);
        if (!id) return [];
        const failed = Boolean(str(frame.error));
        return [task(`subq-${id}`, str(frame.question), failed ? "error" : "complete", {
          output: failed ? str(frame.error) : (str(frame.insight) || str(frame.answer)),
        })];
      }

      // The conversational body's tool calls. The frame arrives once the step
      // has already settled, so there is no in-progress half to show — the card
      // appears as the step lands, carrying its own verdict.
      case "converse_step": {
        const i = num(frame.index);
        if (!i) return [];
        return [task(`step-${i}`, humanize(str(frame.tool)), frame.ok === false ? "error" : "complete", {
          output: str(frame.detail),
        })];
      }

      // FL-2's provider-chain transition. The failover's whole failure mode is
      // that it works silently, so the hop gets a card of its own: it is a
      // completed event, not a step still running.
      case "chain_state": {
        const to = str(frame.to);
        if (!to) return [];
        hops += 1;
        const from = str(frame.from);
        const title = str(frame.event) === "link_failed" ? "Model unavailable" : "Switched model";
        return [task(`chain-${hops}`, title, "complete", {
          details: from ? `${from} → ${to}` : `now on ${to}`,
          output: str(frame.detail),
        })];
      }

      default:
        return [];
    }
  };
}
