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
import { getAnswerReceipt, type InsightReceipt, type LearningReceiptPayload } from "@/lib/api";
import { costSummary } from "@/lib/cost";
import { formatTimestamp } from "@/lib/format";

// The NEW-this-run learning signals (readings reused is already shown as the ◆ badge from lineage).
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

function Badge({ tone, title, children }: { tone: "governed" | "drift" | "guard" | "propose" | "muted"; title?: string; children: React.ReactNode }) {
  const c = {
    governed: ["var(--blue1)", "var(--blue2)", "var(--blue4)"],
    drift: ["var(--amb1)", "var(--amb2)", "var(--amb4)"],
    guard: ["var(--grn1)", "var(--grn2)", "var(--grn4)"],
    propose: ["var(--vio1)", "var(--vio2)", "var(--vio4)"],
    muted: ["var(--bg-3)", "var(--b1)", "var(--t3)"],
  }[tone];
  return (
    <span title={title} style={{
      fontSize: 10, padding: "1px 6px", borderRadius: "var(--r1)", whiteSpace: "nowrap",
      background: c[0], border: `1px solid ${c[1]}`, color: c[2],
    }}>{children}</span>
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
    <div style={{ marginTop: 6, display: "flex", flexDirection: "column", gap: 5 }}>
      <button
        onClick={() => setOpen(o => !o)}
        style={{
          display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap",
          background: "none", border: "none", cursor: "pointer", padding: 0, textAlign: "left",
        }}
        aria-label="Trust receipt"
      >
        <span style={{ fontSize: 10, color: "var(--t4)", textTransform: "uppercase", letterSpacing: ".06em" }}>receipt</span>
        {used.map((m, i) => <Badge key={`used:${i}:${m.ref}`} tone="governed" title={m.detail || ""}>{m.ref.replace("metric:", "")} · governed ✓</Badge>)}
        {drift.map((m, i) => <Badge key={`drift:${i}:${m.ref}`} tone="drift" title={m.detail || ""}>⚠ {m.ref.replace("metric:", "")} · non-governed</Badge>)}
        {proposed.map((m, i) => <Badge key={`prop:${i}:${m.ref}`} tone="propose" title={m.detail || "Define this metric in the Semantic Layer to enforce it"}>✎ define {m.ref.replace("metric:", "")}</Badge>)}
        {guards.map((g, i) => <Badge key={`guard:${i}:${g.ref}`} tone="guard">✓ {g.ref.replace("guard:", "").replace(/_/g, " ")}</Badge>)}
        {resolved.length > 0 && <Badge tone="governed" title="This answer applied an ambiguity this connection resolved earlier">◆ {resolved.length === 1 ? "resolved reading" : `${resolved.length} resolved readings`}</Badge>}
        {learnedNew > 0 && learning && <Badge tone="governed" title="What the closed loop learned on this answer">✦ {[learning.resolutions_crystallized && `crystallized ${learning.resolutions_crystallized}`, learning.trusted_program_replayed && "trusted plan replayed"].filter(Boolean).join(" · ")}</Badge>}
        {activations.length > 0 && <Badge tone="guard" title="Self-gating capabilities whose trigger fired this run">⚡ {activations.length} capabilit{activations.length !== 1 ? "ies" : "y"}</Badge>}
        {used.length === 0 && drift.length === 0 && proposed.length === 0 && guards.length === 0 && resolved.length === 0 && learnedNew === 0 && activations.length === 0 && <Badge tone="muted">{inputs.length} source{inputs.length !== 1 ? "s" : ""} · executed SQL</Badge>}
        <span style={{ fontSize: 10, color: "var(--t4)" }}>{open ? "▾" : "▸"}</span>
      </button>

      {open && (
        <div style={{
          padding: "8px 10px", borderRadius: "var(--r2)", background: "var(--bg-2)",
          border: "1px solid var(--b1)", display: "flex", flexDirection: "column", gap: 7,
        }}>
          {rec.job && (
            <div style={{ fontSize: 11, color: "var(--t3)" }}>
              Recorded {formatTimestamp(rec.artifact.created_at)} · version {rec.artifact.version}
            </div>
          )}
          {costSummary(rec.cost) && (
            <div style={{ fontSize: 11, color: "var(--t3)", display: "flex", gap: 6, alignItems: "center" }}>
              <span style={{ color: "var(--t4)" }} title="What this answer cost to produce">⚡ cost</span>
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
                  <span style={{ color: "var(--blue4)" }}>◆ {r.ref.replace("reading:", "")}</span>
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
                  <span style={{ color: "var(--grn4)" }}>⚡ {capLabel(a.capability)}</span>
                  {a.reason ? ` — activated because ${a.reason}` : ""}{a.count > 1 ? ` (×${a.count})` : ""}
                </div>
              ))}
            </div>
          )}
          {inputs.length > 0 && (
            <div style={{ display: "flex", gap: 4, flexWrap: "wrap", alignItems: "center" }}>
              <span style={{ fontSize: 10, color: "var(--t3)" }}>inputs:</span>
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
      )}
    </div>
  );
}
