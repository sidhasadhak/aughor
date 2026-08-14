"use client";

/**
 * Render one `UIMessage` from its parts — CI-1d.
 *
 * THIS IS THE POINT OF THE WHOLE MIGRATION. The reducer it replaces is a
 * 107-case closed switch: a frame it does not name reaches a `default:` that can
 * only warn in dev, so a backend that grows a frame renders NOTHING and says
 * nothing in production. Here the same frame renders a labelled fallback. The
 * difference is not cosmetic — it is whether a new capability appears as
 * "unrecognised: forecast_band" or as silence.
 *
 * The renderer is therefore deliberately OPEN: known part types get real
 * treatment, and everything else falls through to a fallback that names itself.
 * Adding a part type is additive; forgetting one is visible rather than silent.
 */

import type { AughorUIMessage } from "@/lib/useAughorChat";

/** A titled block of monospace payload — the honest default for a typed part. */
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

export function PartsMessage({ message }: { message: AughorUIMessage }) {
  return (
    <div style={{ marginBlock: 10 }}>
      <span className="aug-label" style={{ color: "var(--t3)" }}>{message.role}</span>
      {message.parts.map((part, i) => {
        const key = `${message.id}:${i}`;

        // Text is the answer itself — the one part that renders as prose.
        if (part.type === "text") {
          return (
            <p key={key} className="aug-fs-ui"
               style={{ margin: "4px 0", color: "var(--t1)", whiteSpace: "pre-wrap" }}>
              {part.text}
            </p>
          );
        }

        if (part.type === "reasoning") {
          return <DataBlock key={key} label="reasoning" value={part.text} />;
        }

        // The escape hatch, rendered rather than swallowed. A frame the backend
        // grew that nothing here names still arrives — carrying its own name, so
        // the gap is legible instead of invisible.
        if (part.type === "data-unknown_frame") {
          const d = part.data as { event: string; payload: Record<string, unknown> };
          return <DataBlock key={key} label={`unrecognised: ${d.event}`} value={d.payload} />;
        }

        // Every declared data part. Named generically on purpose: this proves the
        // TRANSPORT, and giving each of ~35 parts a bespoke component here would
        // duplicate renderers the reducer's consumers already own. The migration
        // moves those across; it does not rewrite them.
        if (part.type.startsWith("data-")) {
          return (
            <DataBlock key={key}
                       label={part.type.slice("data-".length)}
                       value={(part as { data: unknown }).data} />
          );
        }

        // An SDK part type this renderer does not handle yet (files, sources,
        // tool calls). Same rule as an unknown frame: name it, never drop it.
        return <DataBlock key={key} label={part.type} value={part} />;
      })}
    </div>
  );
}
