"use client";

/**
 * Render one `UIMessage` from its parts — CI-1d.
 *
 * THIS IS THE POINT OF THE WHOLE MIGRATION. The reducer it replaces is a
 * 107-case CLOSED switch: a frame it does not name reaches a `default:` that
 * only warns in dev, so a backend that grows a frame renders NOTHING and says
 * nothing in production. Here the same frame renders a labelled fallback. The
 * difference is not cosmetic — it is whether a new capability appears as
 * "unrecognised: forecast_band" or as silence.
 *
 * ── The migration is smaller than it looked ─────────────────────────────────
 *
 * Five of the reducer's nine importers take TYPES ONLY — `GuardReceipt`,
 * `ConverseStep`, `ContextManifest`, `ClarifyPending`, `PlanPending`. They are
 * payload shapes, not reducer state, so those renderers do not care where their
 * data came from and are reused here UNCHANGED. That is the migration's central
 * claim, tested by using them rather than by asserting it: only three modules
 * (`useChat`, `useInvestigationThread`, `aguiTransport`) actually consume the
 * reducer.
 *
 * ── Why parts are grouped before rendering ──────────────────────────────────
 *
 * `guard_receipt` and `converse_step` arrive as ONE PART EACH, while their
 * renderers take ARRAYS — `GuardReceiptChain` draws a chain and `ToolTrail`
 * draws a trail, and both are about the sequence. Rendering per part would
 * produce a row of one-item chains: technically every receipt on screen, and
 * none of the meaning. So same-typed parts are collected first and drawn once,
 * at the position where the first of them arrived.
 */

import { ContextRibbon } from "@/components/ContextRibbon";
import { GuardReceiptChain } from "@/components/GuardReceiptChain";
import { ToolTrail } from "@/components/ToolTrail";
import type {
  ContextManifest,
  ConverseStep,
  GuardReceipt,
} from "@/lib/investigationStream";
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

/** Part types whose renderer takes the whole sequence, not one item. */
const COLLECTED = new Set(["data-guard_receipt", "data-converse_step"]);

export function PartsMessage({
  message,
  connectionId = "",
  streaming = false,
}: {
  message: AughorUIMessage;
  connectionId?: string;
  streaming?: boolean;
}) {
  // Collect the sequence-valued parts up front, and remember where the FIRST of
  // each landed so the chain draws in the position it actually occupied.
  const receipts: GuardReceipt[] = [];
  const steps: ConverseStep[] = [];
  const firstAt = new Map<string, number>();
  message.parts.forEach((part, i) => {
    if (!COLLECTED.has(part.type)) return;
    if (!firstAt.has(part.type)) firstAt.set(part.type, i);
    const data = (part as { data: unknown }).data;
    if (part.type === "data-guard_receipt") receipts.push(data as GuardReceipt);
    else steps.push(data as ConverseStep);
  });

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

        // A collected type draws once, where its first part arrived.
        if (COLLECTED.has(part.type)) {
          if (firstAt.get(part.type) !== i) return null;
          return part.type === "data-guard_receipt"
            ? <GuardReceiptChain key={key} receipts={receipts} streaming={streaming} />
            : <ToolTrail key={key} steps={steps} streaming={streaming} />;
        }

        if (part.type === "data-context_assembled") {
          return (
            <ContextRibbon key={key}
                           manifest={(part as { data: unknown }).data as ContextManifest}
                           connectionId={connectionId} />
          );
        }

        // The escape hatch, rendered rather than swallowed. A frame the backend
        // grew that nothing here names still arrives — carrying its own name, so
        // the gap is legible instead of invisible.
        if (part.type === "data-unknown_frame") {
          const d = part.data as { event: string; payload: Record<string, unknown> };
          return <DataBlock key={key} label={`unrecognised: ${d.event}`} value={d.payload} />;
        }

        // The remaining declared parts — including `clarify_pending` and
        // `plan_pending`, whose renderers need `onChoose` / `onApprove`
        // callbacks. Those are a RESUME path back to the backend, not a
        // rendering problem, so they are shown as data rather than drawn
        // half-working: an approve button that cannot approve is worse than a
        // payload you can read.
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
