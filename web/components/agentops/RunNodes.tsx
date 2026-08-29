"use client";

/**
 * VA-4e · the node vocabulary of a run canvas.
 *
 * The canvas drew ONE card for every node: name, duration, model, usage, a Details
 * toggle. Correct, and flat — a guardrail, a model call, the request that started the run
 * and the response that ended it all arrived at the eye as the same rectangle. The user
 * put our canvas beside VoltAgent's and the difference was not capability but reading:
 * theirs types its nodes, so the shape of a run is legible before a single word is read.
 *
 * So: one face per KIND OF WORK, each showing the fields that kind actually has.
 *
 * **Every face is fed by rows we already store.** Nothing here is invented and nothing
 * new is recorded — the request payload, the guardrail verdict, the model role, the row
 * count, the wall clock were all in `session_events` and were all being rendered as
 * "name · duration". This file is presentation; the substrate did not move.
 *
 * **The trigger is a real node or it is absent.** Measured across 14 live runs: only the
 * `/ask` and `/chat` doors write a `user_request` row. A canvas exploration opens on a
 * guardrail, a monitor on a tool call, an automation on its first step. So the trigger
 * face renders the request row WHEN THERE IS ONE, and when there is not, the canvas says
 * where the run came from in its rail rather than drawing a head node nothing recorded.
 * A synthesised trigger would be indistinguishable from a real one, which is how a
 * debugging surface starts lying.
 */
import type { SessionEvent, TimelineNode } from "@/lib/api";

import { Icon, type IconName } from "@/components/ui/icon";
import { formatCount } from "@/lib/format";

/** What a node is drawn AS. Derived, never stored — the store keeps rows, not faces. */
export type RunFace =
  | "trigger" | "response" | "model" | "guardrail" | "tool" | "delegation" | "event";

/** Card geometry. One width for every face, so a run reads as a column of peers. */
export const CARD_W = 218;

export const FACE_META: Record<RunFace, { label: string; icon: IconName; color: string }> = {
  trigger:    { label: "Trigger",   icon: "bolt",    color: "var(--chart-3)" },
  response:   { label: "Response",  icon: "send",    color: "var(--chart-2)" },
  model:      { label: "Model",     icon: "spark",   color: "var(--chart-1)" },
  guardrail:  { label: "Guardrail", icon: "shield",  color: "var(--chart-4)" },
  tool:       { label: "Tool",      icon: "process", color: "var(--chart-5)" },
  delegation: { label: "Delegate",  icon: "robot",   color: "var(--chart-4)" },
  event:      { label: "Event",     icon: "dot",     color: "var(--chart-6)" },
};

/**
 * The face a node wears.
 *
 * Ordered by SPECIFICITY, not by the store's own kind: `event_kind` is the row's real
 * identity and `kind` is the timeline's coarse bucket, so a guardrail (which the timeline
 * files under the catch-all "event" because it carries no span) has to be recognised
 * before that bucket is consulted, or it renders as an anonymous dot.
 */
export function faceOf(node: TimelineNode): RunFace {
  if (node.event_kind === "user_request") return "trigger";
  if (node.event_kind === "final_response") return "response";
  if (node.event_kind === "guardrail") return "guardrail";
  if (node.delegation) return "delegation";
  if (node.kind === "model") return "model";
  if (node.kind === "tool" || node.kind === "node") return "tool";
  if (node.kind === "error") return "event";
  return "event";
}

/** Doors we can name from a session id's provider prefix. Anything else stays "Web". */
const DOOR_LABEL: Record<string, string> = {
  slack: "Slack", teams: "Teams", mcp: "MCP", api: "API", cli: "CLI",
};

/**
 * Which door a run came in through, read off the session id's `provider:…` prefix.
 *
 * The Slack bot files a conversation as `slack:<channel>:<thread_ts>`, so the prefix is
 * a fact the door wrote, not a guess. A session id with no recognised prefix is the web
 * app, and NO session id at all is a run that started inside the platform — which is a
 * different answer from "the web", and is returned as such.
 */
export function doorOf(sessionId: string | null | undefined):
  { service: string; where: string } | null {
  if (!sessionId) return null;
  const [head, ...rest] = String(sessionId).split(":");
  const service = DOOR_LABEL[head.toLowerCase()];
  if (!service) return { service: "Web", where: String(sessionId).slice(0, 32) };
  return { service, where: rest.join(":").slice(0, 32) };
}

/**
 * Where a run came from, assembled from whatever it recorded.
 *
 * Every field is optional because every field genuinely can be missing, and the rail
 * that renders this prints only what came back. A run with no request row still has a
 * charter, a connection and a start time, and naming those is a better answer than an
 * empty panel or an invented trigger.
 */
export interface RunOrigin {
  service: string | null;
  where: string | null;
  /** The agent charter that did the work — `analyst`, `scout`, `worker`, `coder`. */
  charter: string | null;
  agentId: string | null;
  connId: string | null;
  jobId: string | null;
  /** True when a `user_request` row exists, i.e. a person asked through a door. */
  requested: boolean;
}

export function originOf(events: SessionEvent[]): RunOrigin {
  const first = <K extends keyof SessionEvent>(key: K): SessionEvent[K] | null => {
    for (const e of events) if (e[key]) return e[key];
    return null;
  };
  const sessionId = first("session_id") as string | null;
  const door = doorOf(sessionId);
  return {
    service: door?.service ?? null,
    where: door?.where || null,
    charter: first("charter_id") as string | null,
    agentId: first("agent_id") as string | null,
    connId: first("conn_id") as string | null,
    jobId: first("job_id") as string | null,
    requested: events.some(e => e.kind === "user_request"),
  };
}

/** Durations read as durations. */
export function ms(n: number | null | undefined): string {
  if (n == null) return "—";
  return n >= 1000 ? `${(n / 1000).toFixed(2)}s` : `${Math.round(n)}ms`;
}

/** A guardrail row's verdict, from the payload the guard itself wrote. */
export function guardVerdict(event: SessionEvent | null):
  { blocked: boolean; action: string; found: number } {
  const p = (event?.payload ?? {}) as Record<string, unknown>;
  return {
    blocked: p.blocked === true,
    action: typeof p.detail === "string" ? p.detail : "",
    found: typeof p.found === "number" ? p.found : 0,
  };
}

/* ── the pieces every face is built from ─────────────────────────────────────── */

export function FieldRow({ label, value, tone = "var(--t2)" }:
  { label: string; value: string; tone?: string }) {
  return (
    <div className="aug-fs-xs" style={{ display: "flex", justifyContent: "space-between",
      gap: 8, padding: "2px 9px" }}>
      <span style={{ color: "var(--t4)", flexShrink: 0 }}>{label}</span>
      <span style={{ color: tone, textAlign: "right", overflow: "hidden",
        textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{value}</span>
    </div>
  );
}

/** The strip every card wears: what kind of work this was, and how long it took. */
export function FaceHeader({ face, title, duration, failed }:
  { face: RunFace; title: string; duration: number | null; failed: boolean }) {
  const meta = FACE_META[face];
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 5, padding: "5px 9px" }}>
      <span style={{ color: failed ? "var(--red4)" : meta.color, display: "flex" }}>
        <Icon name={meta.icon} size={12} />
      </span>
      <span className="aug-fs-xs" style={{ color: "var(--t1)", fontWeight: 500,
        overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {title}
      </span>
      {duration != null && (
        <span className="aug-fs-xs" style={{ color: "var(--t3)", marginLeft: "auto",
          flexShrink: 0, fontVariantNumeric: "tabular-nums" }}>
          {ms(duration)}
        </span>
      )}
    </div>
  );
}

/** Prompt / completion / total, as three rows. The split names WHICH half to go fix. */
export function UsageBlock({ usage }: {
  usage: { prompt_tokens: number | null; completion_tokens: number | null;
           total_tokens: number | null };
}) {
  const rows = [
    ["Prompt", usage.prompt_tokens],
    ["Completion", usage.completion_tokens],
    ["Total", usage.total_tokens],
  ] as const;
  return (
    <div style={{ borderTop: "1px solid var(--border)", padding: "2px 0" }}>
      {rows.map(([label, v]) => (
        <div key={label} className="aug-fs-xs"
          style={{ display: "flex", justifyContent: "space-between", padding: "1px 9px" }}>
          <span style={{ color: "var(--t4)" }}>{label}</span>
          <span style={{ color: label === "Total" ? "var(--t1)" : "var(--t3)",
            fontVariantNumeric: "tabular-nums" }}>
            {v == null ? "—" : formatCount(v)}
          </span>
        </div>
      ))}
    </div>
  );
}

/**
 * A block of prose a card carries — the question asked, the answer given.
 *
 * Clamped rather than truncated with an ellipsis in the string: the full text is in the
 * DOM, so it is selectable and searchable, and the card stays a card.
 */
export function ProseBlock({ text, tone = "var(--t2)" }: { text: string; tone?: string }) {
  return (
    <div className="aug-fs-xs nowheel" style={{
      borderTop: "1px solid var(--border)", padding: "5px 9px", color: tone,
      maxHeight: 76, overflowY: "auto", lineHeight: 1.4, overflowWrap: "anywhere",
    }}>
      {text}
    </div>
  );
}
