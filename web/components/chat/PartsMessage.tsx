"use client";

/**
 * Render one assistant turn from its `UIMessage` parts — CI-1d, finished in CA-1.
 *
 * THIS IS THE POINT OF THE WHOLE MIGRATION. The reducer it replaces was a
 * 107-case CLOSED switch: a frame it did not name reached a `default:` that only
 * warned in dev, so a backend that grew a frame rendered NOTHING and said
 * nothing in production. Here the same frame renders a labelled fallback. The
 * difference is not cosmetic — it is whether a new capability appears as
 * "unrecognised: forecast_band" or as silence.
 *
 * HOW EVERY DECLARED PART REACHES AN ORGAN. The parts are projected into the
 * turn view-model (`projectTurn`, `lib/chatTurn.ts` — the reducer's accumulation
 * as a pure function) and the projected turn drives `ChatMessage`: the same
 * organ suite the reducer path drove — the report registry, the gates, the
 * trace, the guard chain, the tool trail, the figure. The organs took typed
 * props all along; only the accumulation moved. Coverage is a TESTED contract:
 * every key of `AughorUIDataTypes` is consumed by a projector or named in
 * `FALLBACK_PARTS`, and `chatTurn.test.ts` fails on any key that is neither.
 *
 * WHAT RENDERS AS A FALLBACK, DELIBERATELY:
 *   • `data-unknown_frame` — the escape hatch, labelled with the frame's own
 *     name, so a gap is legible instead of invisible;
 *   • any SDK part type this shell has no organ for yet (files, sources, tool
 *     invocations) — same rule: name it, never drop it.
 */

import { ChatMessage } from "@/components/ChatMessage";
import type { ChatMessageProps } from "@/components/ChatMessage";
import type { AughorUIMessage } from "@/lib/chatTurn";
import { PROJECTED_PARTS } from "@/lib/chatTurn";

/** A titled block of monospace payload — the honest default for an unclaimed part. */
function DataBlock({ label, value }: { label: string; value: unknown }) {
  const text = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  return (
    <div style={{ marginBlock: 6 }}>
      <span className="aug-label" style={{ color: "var(--t3)" }}>{label}</span>
      <pre
        style={{
          margin: "3px 0 0", padding: "6px 8px", overflowX: "auto",
          background: "var(--bg-2)", border: "1px solid var(--b1)",
          borderRadius: 4, color: "var(--t1)",
        }}
        className="aug-fs-ui"
      >
        {text.length > 1200 ? `${text.slice(0, 1200)}…` : text}
      </pre>
    </div>
  );
}

export interface PartsMessageProps extends ChatMessageProps {
  /** The raw message the turn was projected from — the fallback sweep reads it. */
  message?: AughorUIMessage;
}

export function PartsMessage({ message, ...chatMessageProps }: PartsMessageProps) {
  return (
    <>
      <ChatMessage {...chatMessageProps} />
      {(message?.parts ?? []).map((part, i) => {
        const key = `${message?.id ?? "m"}:${i}`;
        // The escape hatch, rendered rather than swallowed. A frame the backend
        // grew that nothing here names still arrives — carrying its own name.
        if (part.type === "data-unknown_frame") {
          const d = part.data as { event: string; payload: Record<string, unknown> };
          return <DataBlock key={key} label={`unrecognised: ${d.event}`} value={d.payload} />;
        }
        // Text and every projected data part already rendered through the organs.
        if (part.type === "text" || part.type === "step-start") return null;
        if (part.type.startsWith("data-") && PROJECTED_PARTS.has(part.type.slice(5))) {
          return null;
        }
        // An SDK part type this shell has no organ for yet (reasoning, files,
        // sources, tool calls) — or a data part that slipped every net. Same
        // rule as an unknown frame: name it, never drop it.
        return <DataBlock key={key} label={part.type} value={part} />;
      })}
    </>
  );
}
