"use client";

import { useEffect, useState } from "react";
import { onApprovalRequired, approveAction, type ApprovalInfo } from "@/lib/approval";

// Friendly labels for the high-risk actions the backend gates.
const ACTION_LABELS: Record<string, string> = {
  "connection.delete": "Delete connection (and all its data)",
  "connection.schema.delete": "Delete schema",
  "connection.table.delete": "Delete table",
  "ontology.override": "Edit the ontology / semantic layer",
  "ontology.delete_override": "Remove an ontology override",
  "ontology.import": "Import an ontology",
  "metric.approve": "Publish a governed metric",
};

function prettify(action: string): string {
  return ACTION_LABELS[action]
    ?? action.split(/[._]/).map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(" ");
}

/**
 * App-wide approval modal (P4). Listens for HTTP-428 `approval_required` events surfaced
 * by the fetch interceptor (lib/approval.ts). Approving allowlists the action for its
 * scope; the user then retries and it proceeds. Mounted once at the app root.
 */
export function ApprovalModal() {
  const [info, setInfo] = useState<ApprovalInfo | null>(null);
  const [busy, setBusy] = useState(false);
  const [approved, setApproved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => onApprovalRequired((i) => { setInfo(i); setApproved(false); setError(null); }), []);

  useEffect(() => {
    if (!info) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setInfo(null); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [info]);

  if (!info) return null;
  const close = () => setInfo(null);

  async function approve() {
    if (!info) return;
    setBusy(true); setError(null);
    try {
      await approveAction(info.action, info.scope);
      setApproved(true);
    } catch (e) {
      setError((e as Error)?.message ?? "Approval failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      onClick={e => { if (e.target === e.currentTarget) close(); }}
      style={{
        position: "fixed", inset: 0, background: "rgba(0,0,0,.7)", backdropFilter: "blur(4px)",
        zIndex: 300, display: "flex", alignItems: "center", justifyContent: "center", padding: 16,
      }}
    >
      <div style={{
        width: "100%", maxWidth: 400, background: "var(--bg-3)", border: "1px solid var(--b2)",
        borderRadius: "var(--r3)", padding: 24, display: "flex", flexDirection: "column", gap: 14,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{
            width: 34, height: 34, borderRadius: "var(--r2)", background: "var(--amber1, #3a2a12)",
            border: "1px solid var(--amber2, #6b4a1e)", display: "flex", alignItems: "center",
            justifyContent: "center", flexShrink: 0, fontSize: 16,
          }}>🔒</div>
          <div>
            <div style={{ fontSize: 14, fontWeight: 600, color: "var(--t1)" }}>Approval required</div>
            <div style={{ fontSize: 11, color: "var(--t4)", textTransform: "uppercase", letterSpacing: ".05em" }}>
              {info.risk}-risk action
            </div>
          </div>
        </div>

        <div style={{ fontSize: 13, color: "var(--t2)", lineHeight: 1.5 }}>
          <strong style={{ color: "var(--t1)" }}>{prettify(info.action)}</strong>
          {info.scope ? <> on <code style={{ color: "var(--t3)" }}>{info.scope}</code></> : null} needs approval before it can run.
        </div>

        {!approved ? (
          <>
            <p style={{ fontSize: 12, color: "var(--t4)", lineHeight: 1.5, margin: 0 }}>
              Approving allowlists this action for this scope; every attempt is recorded in
              Security &amp; Audit.
            </p>
            {error && <p style={{ fontSize: 12, color: "#f87171", margin: 0 }}>{error}</p>}
            <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 2 }}>
              <button onClick={close}
                style={{ padding: "7px 12px", fontSize: 13, color: "var(--t3)", background: "transparent",
                         border: "1px solid var(--b2)", borderRadius: "var(--r2)", cursor: "pointer" }}>
                Cancel
              </button>
              <button onClick={approve} disabled={busy}
                style={{ padding: "7px 12px", fontSize: 13, fontWeight: 600, color: "#fff",
                         background: "var(--amber-btn, #b45309)", border: "none",
                         borderRadius: "var(--r2)", cursor: busy ? "default" : "pointer", opacity: busy ? .6 : 1 }}>
                {busy ? "Approving…" : "Approve for this scope"}
              </button>
            </div>
          </>
        ) : (
          <>
            <p style={{ fontSize: 13, color: "#4ade80", margin: 0 }}>
              ✓ Approved. Retry the action — it will now proceed.
            </p>
            <div style={{ display: "flex", justifyContent: "flex-end" }}>
              <button onClick={close}
                style={{ padding: "7px 12px", fontSize: 13, fontWeight: 600, color: "#fff",
                         background: "var(--blue-btn, #1d4ed8)", border: "none",
                         borderRadius: "var(--r2)", cursor: "pointer" }}>
                Done
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
