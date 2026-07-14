"use client";

/**
 * B-9 — the Trust Receipt, default-visible.
 *
 * Every chat answer's number self-justifies: a compact badge row (the metric it
 * used, the guards that fired) shown inline, expandable to the executed SQL and
 * full provenance. The CFO's "can I put this in a board deck?" answered in one
 * glance. Fetches lazily; renders nothing if the answer has no receipt (older
 * turns, or answers with no SQL).
 */
import { useEffect, useState } from "react";
import CheckMarkIcon      from "@atlaskit/icon/core/check-mark";
import WarningIcon        from "@atlaskit/icon/core/warning";
import EditIcon           from "@atlaskit/icon/core/edit";
import StatusVerifiedIcon from "@atlaskit/icon/core/status-verified";
import AiSparkleIcon      from "@atlaskit/icon/core/ai-sparkle";
import AutomationIcon     from "@atlaskit/icon/core/automation";
import ChevronDownIcon    from "@atlaskit/icon/core/chevron-down";
import ChevronRightIcon   from "@atlaskit/icon/core/chevron-right";
import { getAnswerReceipt, type InsightReceipt, type LearningReceiptPayload } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { StatusChip, type ChipHue } from "@/components/brief/StatusChip";
import { costSummary } from "@/lib/cost";
import { formatTimestamp } from "@/lib/format";

// The NEW-this-run learning signals (readings reused is already shown as the resolved-reading badge from lineage).
const learnedNewCount = (l?: LearningReceiptPayload) =>
  (l?.resolutions_crystallized ?? 0) + (l?.trusted_program_replayed ?? 0);

function learningPhrases(l: LearningReceiptPayload): string[] {
  const p: string[] = [];
  if (l.readings_reused)
    p.push(`reused ${l.readings_reused} resolved reading${l.readings_reused !== 1 ? "s" : ""}` +
      (l.corrections_applied ? ` (${l.corrections_applied} correction${l.corrections_applied !== 1 ? "s" : ""})` : ""));
  if (l.resolutions_crystallized)
    p.push(`crystallized ${l.resolutions_crystallized} new resolution${l.resolutions_crystallized !== 1 ? "s" : ""}`);
  if (l.trusted_program_replayed) p.push("replayed a trusted plan");
  return p;
}

// "ada.premise_check" → "premise check"
const capLabel = (c: string) => c.replace(/^[a-z]+\./, "").replace(/[._]/g, " ");

// Receipt tone → the ONE chip vocabulary (StatusChip, REC-U3). The old private Badge
// carried its own style map and a sub-floor 10px font; StatusChip renders the same
// semantics at the 11px legibility floor.
const TONE_HUE: Record<"governed" | "drift" | "guard" | "propose" | "muted", ChipHue> = {
  governed: "info",
  drift: "caution",
  guard: "positive",
  propose: "accent",
  muted: "muted",
};

function Badge({ tone, title, icon, children }: { tone: keyof typeof TONE_HUE; title?: string; icon?: React.ReactNode; children: React.ReactNode }) {
  return (
    <StatusChip hue={TONE_HUE[tone]} strength="soft" title={title} icon={icon} className="whitespace-nowrap font-normal">
      {children}
    </StatusChip>
  );
}

export function TrustReceipt({ connectionId, receiptId, kind = "chat" }: { connectionId: string; receiptId: string; kind?: "chat" | "ada" }) {
  const [rec, setRec] = useState<InsightReceipt | null>(null);
  const [open, setOpen] = useState(false);
  const [tried, setTried] = useState(false);

  useEffect(() => {
    let alive = true;
    getAnswerReceipt(kind, connectionId, receiptId)
      .then(r => { if (alive) { setRec(r); setTried(true); } })
      .catch(() => { if (alive) setTried(true); });
    return () => { alive = false; };
  }, [connectionId, receiptId, kind]);

  if (!tried || !rec) return null;

  const metrics = rec.lineage.filter(l => l.relation === "metric_available");
  const used = rec.lineage.filter(l => l.relation === "metric_used");        // B-7: governed formula used
  const drift = rec.lineage.filter(l => l.relation === "metric_drift");      // B-7: improvised
  const proposed = rec.lineage.filter(l => l.relation === "metric_proposed"); // B-7: ungoverned KPI to define
  const guards = rec.lineage.filter(l => l.relation === "validated_by");
  const inputs = rec.lineage.filter(l => l.relation === "input");
  const sqlEdge = rec.lineage.find(l => l.relation === "source_sql");
  // I6 — a reading this connection settled earlier (Ambiguity Ledger) that this answer applied.
  const resolved = rec.lineage.filter(l => l.relation === "resolved_ambiguity");
  // Wave 1 receipts family: per-run Learning Receipt (E4) + Activation Receipt (E3), stamped on the payload.
  const learning = rec.artifact.payload.learning;
  const activations = rec.artifact.payload.activations ?? [];
  const learnedNew = learnedNewCount(learning);

  return (
    <div style={{ marginTop: 6, display: "flex", flexDirection: "column" }}>
      <Button
        variant="ghost"
        onClick={() => setOpen(o => !o)}
        className="h-auto w-full flex-wrap justify-start gap-1.5 p-0 whitespace-normal text-left font-normal hover:bg-transparent dark:hover:bg-transparent"
        aria-label="Trust receipt"
        aria-expanded={open}
      >
        <span className="aug-fs-xs" style={{ color: "var(--t4)", textTransform: "uppercase", letterSpacing: ".06em" }}>receipt</span>
        {used.map((m, i) => <Badge key={`used:${i}:${m.ref}`} tone="governed" title={m.detail || ""} icon={<CheckMarkIcon label="" size="small" />}>{m.ref.replace("metric:", "")} · governed</Badge>)}
        {drift.map((m, i) => <Badge key={`drift:${i}:${m.ref}`} tone="drift" title={m.detail || ""} icon={<WarningIcon label="" size="small" />}>{m.ref.replace("metric:", "")} · non-governed</Badge>)}
        {proposed.map((m, i) => <Badge key={`prop:${i}:${m.ref}`} tone="propose" title={m.detail || "Define this metric in the Semantic Layer to enforce it"} icon={<EditIcon label="" size="small" />}>define {m.ref.replace("metric:", "")}</Badge>)}
        {guards.map((g, i) => <Badge key={`guard:${i}:${g.ref}`} tone="guard" icon={<CheckMarkIcon label="" size="small" />}>{g.ref.replace("guard:", "").replace(/_/g, " ")}</Badge>)}
        {resolved.length > 0 && <Badge tone="governed" title="This answer applied an ambiguity this connection resolved earlier" icon={<StatusVerifiedIcon label="" size="small" />}>{resolved.length === 1 ? "resolved reading" : `${resolved.length} resolved readings`}</Badge>}
        {learnedNew > 0 && learning && <Badge tone="governed" title="What the closed loop learned on this answer" icon={<AiSparkleIcon label="" size="small" />}>{[learning.resolutions_crystallized && `crystallized ${learning.resolutions_crystallized}`, learning.trusted_program_replayed && "trusted plan replayed"].filter(Boolean).join(" · ")}</Badge>}
        {activations.length > 0 && <Badge tone="guard" title="Self-gating capabilities whose trigger fired this run" icon={<AutomationIcon label="" size="small" />}>{activations.length} capabilit{activations.length !== 1 ? "ies" : "y"}</Badge>}
        {used.length === 0 && drift.length === 0 && proposed.length === 0 && guards.length === 0 && resolved.length === 0 && learnedNew === 0 && activations.length === 0 && <Badge tone="muted">{inputs.length} source{inputs.length !== 1 ? "s" : ""} · executed SQL</Badge>}
        <span className="aug-fs-xs" style={{ color: "var(--t4)" }} aria-hidden>
          {open ? <ChevronDownIcon label="" size="small" /> : <ChevronRightIcon label="" size="small" />}
        </span>
      </Button>

      {/* Expanded provenance panel — stays mounted so .aug-disclose can animate the
          open/close height (grid-rows 0fr→1fr). Mounts closed; only the user's toggle
          transitions it, so restored turns never animate on mount. */}
      <div className="aug-disclose" data-open={open}>
        <div>
        <div style={{
          marginTop: 5, padding: "8px 10px", borderRadius: "var(--r2)", background: "var(--bg-2)",
          border: "1px solid var(--b1)", display: "flex", flexDirection: "column", gap: 7,
        }}>
          {rec.job && (
            <div style={{ fontSize: 11, color: "var(--t3)" }}>
              Recorded {formatTimestamp(rec.artifact.created_at)} · version {rec.artifact.version}
            </div>
          )}
          {costSummary(rec.cost) && (
            <div style={{ fontSize: 11, color: "var(--t3)", display: "flex", gap: 6, alignItems: "center" }}>
              <span style={{ color: "var(--t4)", display: "inline-flex", alignItems: "center", gap: 4 }} title="What this answer cost to produce">
                <AutomationIcon label="" size="small" /> cost
              </span>
              <span>{costSummary(rec.cost)}</span>
            </div>
          )}
          {metrics.length > 0 && (
            <div style={{ fontSize: 11, color: "var(--t2)" }}>
              Governed metrics available: {metrics.map((m, i) => (
                <span key={`avail:${i}:${m.ref}`} title={m.detail || ""} style={{ color: "var(--blue4)" }}>{m.ref.replace("metric:", "")} </span>
              ))}
            </div>
          )}
          {resolved.length > 0 && (
            <div style={{ fontSize: 11, color: "var(--t2)" }}>
              <span style={{ color: "var(--t3)" }}>Applied a previously-resolved reading (so this question doesn’t re-ask):</span>
              {resolved.map((r, i) => (
                <div key={`resolved:${i}:${r.ref}`} style={{ marginTop: 2 }}>
                  <span style={{ color: "var(--blue4)", display: "inline-flex", alignItems: "center", gap: 4, verticalAlign: "text-bottom" }}>
                    <StatusVerifiedIcon label="" size="small" /> {r.ref.replace("reading:", "")}
                  </span>
                  {r.detail ? ` — ${r.detail}` : ""}
                </div>
              ))}
            </div>
          )}
          {learning && (learning.readings_reused > 0 || learnedNew > 0) && (
            <div style={{ fontSize: 11, color: "var(--t2)" }}>
              <span style={{ color: "var(--t3)" }}>What the loop learned this run:</span>{" "}
              {learningPhrases(learning).join(" · ")}.
            </div>
          )}
          {activations.length > 0 && (
            <div style={{ fontSize: 11, color: "var(--t2)" }}>
              <span style={{ color: "var(--t3)" }}>Guards that fired (their trigger held):</span>
              {activations.map((a, i) => (
                <div key={`act:${i}:${a.capability}`} style={{ marginTop: 2 }}>
                  <span style={{ color: "var(--grn4)", display: "inline-flex", alignItems: "center", gap: 4, verticalAlign: "text-bottom" }}>
                    <AutomationIcon label="" size="small" /> {capLabel(a.capability)}
                  </span>
                  {a.reason ? ` — activated because ${a.reason}` : ""}{a.count > 1 ? ` (×${a.count})` : ""}
                </div>
              ))}
            </div>
          )}
          {inputs.length > 0 && (
            <div style={{ display: "flex", gap: 4, flexWrap: "wrap", alignItems: "center" }}>
              <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>inputs:</span>
              {inputs.map((inp, idx) => <Badge key={`input:${idx}:${inp.ref}`} tone="muted">{inp.ref.replace("table:", "")}</Badge>)}
            </div>
          )}
          {sqlEdge?.detail && (
            <pre style={{
              margin: 0, padding: "8px 10px", borderRadius: "var(--r2)", background: "var(--code-bg)",
              border: "1px solid var(--b1)", fontSize: 11, fontFamily: "var(--font-code)",
              color: "var(--t2)", whiteSpace: "pre-wrap", wordBreak: "break-word", lineHeight: 1.5,
            }}>{sqlEdge.detail}</pre>
          )}
        </div>
        </div>
      </div>
    </div>
  );
}
