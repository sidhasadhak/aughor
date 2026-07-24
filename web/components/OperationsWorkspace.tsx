"use client";

import dynamic from "next/dynamic";
import { Workspace, type WorkspaceLayer } from "@/components/Workspace";

// ── Lazy panels ──────────────────────────────────────────────────────────────
// Each operational surface is a heavy data view — load on first open, then keep
// mounted (the Workspace's keep-alive), mirroring IntelligenceWorkspace.
const loading = () => (
  <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", background: "var(--bg-0)" }}>
    <div style={{ width: 20, height: 20, border: "2px solid var(--bg-3)", borderTopColor: "var(--blue3)", borderRadius: "50%", animation: "aug-spin 0.7s linear infinite" }} />
  </div>
);

const MonitorsPanel      = dynamic(() => import("@/components/MonitorsPanel").then(m => ({ default: m.MonitorsPanel })),           { ssr: false, loading });
const AutomationsPanel   = dynamic(() => import("@/components/AutomationsPanel").then(m => ({ default: m.AutomationsPanel })),     { ssr: false, loading });
const ActionHubPanel     = dynamic(() => import("@/components/ActionHubPanel").then(m => ({ default: m.ActionHubPanel })),         { ssr: false, loading });
const SecurityAuditPanel = dynamic(() => import("@/components/SecurityAuditPanel").then(m => ({ default: m.SecurityAuditPanel })), { ssr: false, loading });

// Icon paths mirror the sidebar's NavIcon set (activity / gear / spark / shield).
const ICONS: Record<string, string> = {
  activity: "M22 12h-4l-3 9L9 3l-3 9H2",
  gear:     "M12 15a3 3 0 100-6 3 3 0 000 6zM19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 11-2.83 2.83l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 11-4 0v-.09A1.65 1.65 0 008 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 11-2.83-2.83l.06-.06a1.65 1.65 0 00.33-1.82 1.65 1.65 0 00-1.51-1H2a2 2 0 110-4h.09A1.65 1.65 0 003.6 8a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 112.83-2.83l.06.06a1.65 1.65 0 001.82.33H8a1.65 1.65 0 001-1.51V2a2 2 0 114 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 112.83 2.83l-.06.06a1.65 1.65 0 00-.33 1.82V8a1.65 1.65 0 001.51 1H22a2 2 0 110 4h-.09a1.65 1.65 0 00-1.51 1z",
  spark:    "M12 2l2.4 7.4H22l-6.2 4.5 2.4 7.4L12 17l-6.2 4.3 2.4-7.4L2 9.4h7.6L12 2z",
  shield:   "M12 2l8 3v6c0 5-3.4 9.1-8 11-4.6-1.9-8-6-8-11V5l8-3zM9.5 12l1.8 1.8L15 9.8",
};

function Icon({ name, size = 14, color = "currentColor" }: { name: string; size?: number; color?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke={color} strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
      <path d={ICONS[name]} />
    </svg>
  );
}

export type OpsLayer = "monitors" | "automations" | "actions" | "security";

const LAYERS: WorkspaceLayer<OpsLayer>[] = [
  { id: "monitors",    icon: "activity", label: "Monitors",         blurb: "Metric watches & alerts" },
  { id: "automations", icon: "gear",     label: "Automations",      blurb: "Condition → effect, & the proposal queue" },
  { id: "actions",     icon: "spark",    label: "Action Hub",       blurb: "Governed actions & approvals" },
  { id: "security",    icon: "shield",   label: "Security & Audit", blurb: "Access, PII & the audit trail" },
];

type SecLens = "security" | "activity" | "approvals";

type Props = {
  connId?: string;
  workspaceId?: string;
  /** Active layer — controlled by the shell so external nav can deep-link. */
  layer: OpsLayer;
  onLayerChange: (l: OpsLayer) => void;
  /** Security & Audit's own lens (security ↔ activity), owned by the shell so a legacy
   *  `activity` deep-link can open the security layer already on the activity lens. */
  secLens: SecLens;
  onSecLensChange: (l: SecLens) => void;
};

/**
 * The Operations workspace — folds the three formerly-separate Operations tabs
 * (Monitors / Action Hub / Security & Audit) into one perspective-switched surface,
 * an *instance* of the generic `<Workspace>` shell (Part 2 REC-U5). The panels bring
 * their own bodies; the shell owns the header + switcher + keep-alive.
 */
export function OperationsWorkspace({ connId, workspaceId, layer, onLayerChange, secLens, onSecLensChange }: Props) {
  return (
    <Workspace
      layers={LAYERS}
      layer={layer}
      onLayerChange={onLayerChange}
      ariaLabel="Operations views"
      renderIcon={(name, size, color) => <Icon name={name} size={size} color={color} />}
      renderLayer={id => {
        if (id === "monitors")    return <MonitorsPanel connId={connId} workspaceId={workspaceId} />;
        if (id === "automations") return <AutomationsPanel connId={connId} workspaceId={workspaceId} />;
        if (id === "actions")     return <ActionHubPanel />;
        return <SecurityAuditPanel connId={connId} lens={secLens} onLensChange={onSecLensChange} />; // "security"
      }}
    />
  );
}
