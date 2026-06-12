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
import { getAnswerReceipt, type InsightReceipt } from "@/lib/api";

const REL_LABEL: Record<string, string> = {
  metric_available: "metric",
  validated_by: "guard",
  trusted: "trusted",
};

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
  const used = rec.lineage.filter(l => l.relation === "metric_used");      // B-7: governed formula used
  const drift = rec.lineage.filter(l => l.relation === "metric_drift");    // B-7: improvised
  const guards = rec.lineage.filter(l => l.relation === "validated_by");
  const inputs = rec.lineage.filter(l => l.relation === "input");
  const sqlEdge = rec.lineage.find(l => l.relation === "source_sql");

  const Badge = ({ tone, title, children }: { tone: "governed" | "drift" | "guard" | "muted"; title?: string; children: React.ReactNode }) => {
    const c = {
      governed: ["var(--blue1)", "var(--blue2)", "var(--blue4)"],
      drift: ["var(--amb1)", "var(--amb2)", "var(--amb4)"],
      guard: ["var(--grn1)", "var(--grn2)", "var(--grn4)"],
      muted: ["var(--bg-3)", "var(--b1)", "var(--t3)"],
    }[tone];
    return (
      <span title={title} style={{
        fontSize: 10, padding: "1px 6px", borderRadius: "var(--r1)", whiteSpace: "nowrap",
        background: c[0], border: `1px solid ${c[1]}`, color: c[2],
      }}>{children}</span>
    );
  };

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
        {guards.map((g, i) => <Badge key={`guard:${i}:${g.ref}`} tone="guard">✓ {g.ref.replace("guard:", "").replace(/_/g, " ")}</Badge>)}
        {used.length === 0 && drift.length === 0 && guards.length === 0 && <Badge tone="muted">{inputs.length} source{inputs.length !== 1 ? "s" : ""} · executed SQL</Badge>}
        <span style={{ fontSize: 10, color: "var(--t4)" }}>{open ? "▾" : "▸"}</span>
      </button>

      {open && (
        <div style={{
          padding: "8px 10px", borderRadius: "var(--r2)", background: "var(--bg-2)",
          border: "1px solid var(--b1)", display: "flex", flexDirection: "column", gap: 7,
        }}>
          {rec.job && (
            <div style={{ fontSize: 11, color: "var(--t3)" }}>
              Recorded {new Date(rec.artifact.created_at).toLocaleString()} · version {rec.artifact.version}
            </div>
          )}
          {metrics.length > 0 && (
            <div style={{ fontSize: 11, color: "var(--t2)" }}>
              Governed metrics available: {metrics.map((m, i) => (
                <span key={`avail:${i}:${m.ref}`} title={m.detail || ""} style={{ color: "var(--blue4)" }}>{m.ref.replace("metric:", "")} </span>
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
