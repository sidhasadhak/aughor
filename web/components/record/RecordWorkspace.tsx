"use client";

/**
 * Intelligence ▸ Record — the organisation's ledger as five views of one workspace: Inquiries,
 * Decisions, Missions, Claims and Corrections (the 2027 study §V, screens 4 to 7 and 9).
 *
 * One rail item, not five: an instance of the same `<Workspace>` shell Agent Ops and Evals are,
 * so the rail that was here keeps every row above the fold. A Ledger row opens its Reader in
 * place, addressed as `?id=`; a citation that points at another view (an inquiry's decision, a
 * decision's claim) switches the view and opens that record.
 */
import dynamic from "next/dynamic";

import type { Connection } from "@/lib/api";
import { listInquiries } from "@/lib/record";
import { Workspace, type WorkspaceLayer } from "@/components/Workspace";
import { Icon as Glyph, type IconName } from "@/components/ui/icon";
import { SkeletonRows } from "@/components/ui/motion";

const loading = () => (
  <div style={{ flex: 1, background: "var(--bg-0)", padding: 16 }}>
    <SkeletonRows rows={6} />
  </div>
);

const InquiriesPanel   = dynamic(() => import("@/components/inquiries/InquiriesPanel").then(m => ({ default: m.InquiriesPanel })), { ssr: false, loading });
const DecisionsPanel   = dynamic(() => import("@/components/decisions/DecisionsPanel").then(m => ({ default: m.DecisionsPanel })), { ssr: false, loading });
const MissionsPanel    = dynamic(() => import("@/components/missions/MissionsPanel").then(m => ({ default: m.MissionsPanel })),   { ssr: false, loading });
const RecordPanel      = dynamic(() => import("@/components/record/RecordPanel").then(m => ({ default: m.RecordPanel })),         { ssr: false, loading });
const CorrectionsPanel = dynamic(() => import("@/components/record/CorrectionsPanel").then(m => ({ default: m.CorrectionsPanel })), { ssr: false, loading });

export type RecordLayer = "inquiries" | "decisions" | "missions" | "claims" | "corrections";

const LAYERS: WorkspaceLayer<RecordLayer>[] = [
  { id: "inquiries",   icon: "idea",     label: "Inquiries",   blurb: "What is established, what is open and what would settle it" },
  { id: "decisions",   icon: "bookmark", label: "Decisions",   blurb: "What was chosen, what was expected and what became of it" },
  { id: "missions",    icon: "target",   label: "Missions",    blurb: "Each objective against its baseline, and what it cost" },
  { id: "claims",      icon: "list",     label: "Claims",      blurb: "What is held true about a thing, as of any date" },
  { id: "corrections", icon: "history",  label: "Corrections", blurb: "What the platform was wrong about, and what replaced it" },
];

export function RecordWorkspace({
  layer, onLayerChange, openId, onOpenRecord, connections, selectedConn,
  onOpenRun, onAsk, onOpenReceipt, onOpenDefinitions, onOpenMap, onOpenMonitors,
}: {
  /** Active view — controlled by the shell so a link can open one. */
  layer: RecordLayer;
  onLayerChange: (l: RecordLayer) => void;
  /** The record the active view's Reader has open; null for its Ledger. */
  openId: string | null;
  /** Open one record on its view — or, with a null id, that view's Ledger. */
  onOpenRecord: (layer: RecordLayer, id: string | null) => void;
  connections: Connection[];
  selectedConn: string;
  onOpenRun: (runId: string) => void;
  onAsk: () => void;
  onOpenReceipt: (ref: string) => void;
  onOpenDefinitions: () => void;
  onOpenMap: () => void;
  onOpenMonitors: () => void;
}) {
  // Every view stays mounted once visited; only the one on screen holds the open record.
  const idFor = (l: RecordLayer) => (layer === l ? openId : null);
  return (
    <Workspace
      layers={LAYERS}
      layer={layer}
      onLayerChange={onLayerChange}
      ariaLabel="Record views"
      renderIcon={(name, size, color) => (
        <span style={{ color, display: "inline-flex", flexShrink: 0 }}><Glyph name={name as IconName} size={size} /></span>
      )}
      renderLayer={id => {
        if (id === "inquiries") return (
          <InquiriesPanel connections={connections} openId={idFor("inquiries")}
            onOpen={x => onOpenRecord("inquiries", x)} onOpenRun={onOpenRun} onAsk={onAsk}
            onOpenDecision={x => onOpenRecord("decisions", x)} onOpenClaim={x => onOpenRecord("claims", x)} />
        );
        if (id === "decisions") return (
          <DecisionsPanel connections={connections} selectedConn={selectedConn} openId={idFor("decisions")}
            onOpen={x => onOpenRecord("decisions", x)} onOpenClaim={x => onOpenRecord("claims", x)} />
        );
        if (id === "missions") return (
          <MissionsPanel connections={connections} selectedConn={selectedConn} openId={idFor("missions")}
            onOpen={x => onOpenRecord("missions", x)} onOpenMonitors={onOpenMonitors}
            onOpenInquiry={x => onOpenRecord("inquiries", x)} onOpenDecision={x => onOpenRecord("decisions", x)}
            onOpenClaim={x => onOpenRecord("claims", x)} />
        );
        if (id === "claims") return (
          <RecordPanel connections={connections} selectedConn={selectedConn} openId={idFor("claims")}
            onOpen={x => onOpenRecord("claims", x)} onOpenDecision={x => onOpenRecord("decisions", x)}
            onOpenRun={onOpenRun} onOpenReceipt={onOpenReceipt}
            onOpenDefinitions={onOpenDefinitions} onOpenMap={onOpenMap} />
        );
        return ( // "corrections"
          <CorrectionsPanel connections={connections}
            onOpenClaim={x => onOpenRecord("claims", x)} onOpenDecision={x => onOpenRecord("decisions", x)}
            onOpenInquiryKey={key => {
              // A refuted cause names its inquiry by key; the view it opens is addressed by id.
              listInquiries({ limit: 500 })
                .then(rows => onOpenRecord("inquiries", rows.find(q => q.key === key)?.id ?? null))
                .catch(() => onOpenRecord("inquiries", null));
            }} />
        );
      }}
    />
  );
}
