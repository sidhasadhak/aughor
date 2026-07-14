"use client";

import { useEffect, useState } from "react";
import { onUpgradeRequired, type UpgradeInfo } from "@/lib/upsell";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";

// What each plan adds — shown so the upsell explains the value, not just the lock.
const PLAN_HIGHLIGHTS: Record<string, string[]> = {
  Pro: [
    "Autonomous exploration & deep investigations",
    "Monitors, scheduled briefs & the Action Hub",
    "Ontology + semantic-layer editing and saved fixes",
  ],
  Enterprise: [
    "Everything in Pro",
    "Adaptive Temporal Tier-3 & the semantic compiler",
    "RBAC / SSO, audit export & the security suite",
  ],
};

/**
 * App-wide upsell modal. Listens for HTTP-402 `capability_locked` events surfaced by
 * the fetch interceptor (see lib/upsell.ts) and explains how to unlock the feature.
 * Mounted once at the app root; renders nothing until a gated call is attempted.
 */
export function UpgradeModal() {
  const [info, setInfo] = useState<UpgradeInfo | null>(null);

  useEffect(() => onUpgradeRequired(setInfo), []);

  if (!info) return null;

  const highlights = PLAN_HIGHLIGHTS[info.requiredTier] ?? PLAN_HIGHLIGHTS.Pro;
  const close = () => setInfo(null);

  return (
    <Dialog open onOpenChange={(open) => { if (!open) close(); }}>
      <DialogContent
        showCloseButton={false}
        className="sm:max-w-[380px] gap-4 p-6"
        style={{ background: "var(--bg-3)", border: "1px solid var(--b2)" }}
      >
        <div style={{ display: "flex", alignItems: "flex-start", gap: 12 }}>
          <div style={{
            width: 36, height: 36, borderRadius: "var(--r2)", background: "var(--blue1)",
            border: "1px solid var(--blue2)", display: "flex", alignItems: "center",
            justifyContent: "center", flexShrink: 0,
          }}>
            {/* spark / premium glyph */}
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path d="M13 2 4 14h7l-1 8 9-12h-7l1-8Z" fill="var(--blue4)" />
            </svg>
          </div>
          <div>
            <DialogTitle style={{ fontSize: 16, fontWeight: 600, color: "var(--t1)" }}>
              Unlock {info.feature}
            </DialogTitle>
            <div style={{ fontSize: 11, color: "var(--t3)", marginTop: 3, lineHeight: 1.5 }}>
              {info.feature} isn&apos;t included in your{" "}
              <span style={{ color: "var(--t2)", textTransform: "capitalize" }}>{info.currentTier}</span>{" "}
              plan. Upgrade to <span style={{ color: "var(--blue4)" }}>{info.requiredTier}</span> to use it.
            </div>
          </div>
        </div>

        <div style={{
          background: "var(--bg-2)", border: "1px solid var(--b1)", borderRadius: "var(--r2)",
          padding: "12px 14px", display: "flex", flexDirection: "column", gap: 8,
        }}>
          <div style={{ fontSize: 11, fontWeight: 600, color: "var(--t3)", letterSpacing: ".04em" }}>
            {info.requiredTier.toUpperCase()} PLAN INCLUDES
          </div>
          {highlights.map((h, i) => (
            <div key={i} style={{ display: "flex", alignItems: "flex-start", gap: 8, fontSize: 12, color: "var(--t2)" }}>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" style={{ marginTop: 2, flexShrink: 0 }} aria-hidden="true">
                <path d="M20 6 9 17l-5-5" stroke="var(--grn4)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              <span style={{ lineHeight: 1.4 }}>{h}</span>
            </div>
          ))}
        </div>

        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", alignItems: "center" }}>
          <Button variant="ghost" onClick={close} className="text-[color:var(--t2)]">Maybe later</Button>
          <Button
            variant="outline"
            onClick={close}
            className="gap-1.5 font-semibold bg-[var(--blue1)] border-[var(--blue2)] text-[color:var(--blue4)] hover:bg-[var(--blue1)] hover:text-[color:var(--blue4)] dark:bg-[var(--blue1)] dark:hover:bg-[var(--blue1)]"
          >
            See plans →
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
