"use client";

import { useEffect, useState } from "react";
import { onApprovalRequired, approveAction, type ApprovalInfo } from "@/lib/approval";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";

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
 * Composed on ui/dialog + ui/button (the Wave-1 proof pattern for hand-rolled overlays);
 * Escape / backdrop-close come from the Dialog primitive.
 */
export function ApprovalModal() {
  const [info, setInfo] = useState<ApprovalInfo | null>(null);
  const [busy, setBusy] = useState(false);
  const [approved, setApproved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => onApprovalRequired((i) => { setInfo(i); setApproved(false); setError(null); }), []);

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
    <Dialog open onOpenChange={(open) => { if (!open) close(); }}>
      <DialogContent
        showCloseButton={false}
        className="sm:max-w-[400px] gap-3.5 p-6"
        style={{ background: "var(--bg-3)", border: "1px solid var(--b2)" }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{
            width: 34, height: 34, borderRadius: "var(--r2)", background: "var(--amb1)",
            border: "1px solid var(--amb2)", display: "flex", alignItems: "center",
            justifyContent: "center", flexShrink: 0, fontSize: 16,
          }}>🔒</div>
          <div>
            <DialogTitle style={{ fontSize: 14, fontWeight: 600, color: "var(--t1)" }}>Approval required</DialogTitle>
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
            {error && <p style={{ fontSize: 12, color: "var(--red4)", margin: 0 }}>{error}</p>}
            <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 2 }}>
              <Button variant="outline" onClick={close} className="text-[color:var(--t3)]">
                Cancel
              </Button>
              <Button
                onClick={approve}
                disabled={busy}
                className="bg-[var(--amb3)] text-white hover:bg-[var(--amb3)]/90 font-semibold"
              >
                {busy ? "Approving…" : "Approve for this scope"}
              </Button>
            </div>
          </>
        ) : (
          <>
            <p style={{ fontSize: 13, color: "var(--grn4)", margin: 0 }}>
              ✓ Approved. Retry the action — it will now proceed.
            </p>
            <div style={{ display: "flex", justifyContent: "flex-end" }}>
              <Button onClick={close} className="font-semibold">
                Done
              </Button>
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
