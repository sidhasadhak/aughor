"use client";

/**
 * ExportButton — download a stored analysis as a polished PDF or PowerPoint.
 *
 * Hits GET /investigations/{id}/export?format=… (server-side serializer that
 * renders the report's prose, KPIs, charts and tables). The optional "AI
 * executive summary" toggle sets ?narrate=true (best-effort LLM detailing).
 */
import { useEffect, useRef, useState } from "react";
import { downloadInvestigationExport } from "@/lib/api";

export function ExportButton({ invId }: { invId: string }) {
  const [open, setOpen] = useState(false);
  const [narrate, setNarrate] = useState(false);
  const [busy, setBusy] = useState<null | "pdf" | "pptx">(null);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  const go = (fmt: "pdf" | "pptx") => {
    setBusy(fmt);
    downloadInvestigationExport(invId, fmt, narrate);
    // The browser handles the actual file transfer; clear the spinner shortly after.
    setTimeout(() => { setBusy(null); setOpen(false); }, narrate ? 1400 : 700);
  };

  const item: React.CSSProperties = {
    display: "flex", alignItems: "center", gap: 8, width: "100%",
    padding: "7px 10px", borderRadius: "var(--r1)", fontSize: 12,
    color: "var(--t2)", background: "transparent", border: "none",
    cursor: "pointer", textAlign: "left",
  };

  return (
    <div ref={ref} style={{ position: "relative" }}>
      <button
        onClick={() => setOpen(v => !v)}
        title="Download this analysis as PDF or PowerPoint"
        style={{
          display: "inline-flex", alignItems: "center", gap: 6,
          padding: "4px 10px", borderRadius: "var(--r2)", fontSize: 11.5,
          background: "var(--bg-2)", border: "1px solid var(--b1)",
          color: "var(--t2)", cursor: "pointer", transition: "all .1s",
        }}
        onMouseEnter={e => { e.currentTarget.style.color = "var(--t1)"; e.currentTarget.style.borderColor = "var(--b2)"; }}
        onMouseLeave={e => { e.currentTarget.style.color = "var(--t2)"; e.currentTarget.style.borderColor = "var(--b1)"; }}
      >
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
          <polyline points="7 10 12 15 17 10" />
          <line x1="12" y1="15" x2="12" y2="3" />
        </svg>
        Export
        <span style={{ fontSize: 9, opacity: 0.6 }}>▾</span>
      </button>

      {open && (
        <div style={{
          position: "absolute", right: 0, top: "calc(100% + 6px)", zIndex: 50,
          width: 210, padding: 6, borderRadius: "var(--r2)",
          background: "var(--bg-1)", border: "1px solid var(--b2)",
          boxShadow: "0 8px 28px rgba(0,0,0,.24)",
        }}>
          <button style={item} disabled={!!busy} onClick={() => go("pdf")}
            onMouseEnter={e => (e.currentTarget.style.background = "var(--bg-3)")}
            onMouseLeave={e => (e.currentTarget.style.background = "transparent")}>
            <span style={{ fontSize: 14 }}>📄</span>
            <span style={{ flex: 1 }}>PDF document</span>
            {busy === "pdf" && <Spin />}
          </button>
          <button style={item} disabled={!!busy} onClick={() => go("pptx")}
            onMouseEnter={e => (e.currentTarget.style.background = "var(--bg-3)")}
            onMouseLeave={e => (e.currentTarget.style.background = "transparent")}>
            <span style={{ fontSize: 14 }}>📊</span>
            <span style={{ flex: 1 }}>PowerPoint (.pptx)</span>
            {busy === "pptx" && <Spin />}
          </button>
          <label style={{
            display: "flex", alignItems: "center", gap: 8, padding: "8px 10px 4px",
            marginTop: 4, borderTop: "1px solid var(--b1)", fontSize: 11,
            color: "var(--t3)", cursor: "pointer",
          }}>
            <input type="checkbox" checked={narrate} onChange={e => setNarrate(e.target.checked)} />
            Add AI executive summary
          </label>
        </div>
      )}
    </div>
  );
}

function Spin() {
  return (
    <span style={{
      width: 11, height: 11, border: "1.5px solid var(--b2)",
      borderTop: "1.5px solid var(--blue4)", borderRadius: "50%",
      animation: "aug-spin var(--dur-breath) linear infinite", flexShrink: 0,
    }} />
  );
}
