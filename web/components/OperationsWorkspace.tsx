"use client";

import dynamic from "next/dynamic";
import { Workspace, type WorkspaceLayer } from "@/components/Workspace";
import { Icon as Glyph, type IconName } from "@/components/ui/icon";

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
/**
 * This screen's glyphs, by role. The drawings come from the platform icon set
 * (`components/ui/icon.tsx`); this map only says which role each local name means,
 * so the existing call sites and `LAYERS` entries keep working unchanged.
 */
const ROLE: Record<string, IconName> = {
  activity: "activity",
  gear: "settings",
  spark: "spark",
  shield: "shield",
};

function Icon({ name, size = 14, color = "currentColor" }: { name: string; size?: number; color?: string }) {
  return (
    <span style={{ color, display: "inline-flex", flexShrink: 0 }}>
      <Glyph name={ROLE[name] ?? "info"} size={size} />
    </span>
  );
}

export type OpsLayer = "monitors" | "automations" | "actions" | "security";

const LAYERS: WorkspaceLayer<OpsLayer>[] = [
  { id: "monitors",    icon: "activity", label: "Monitors",         blurb: "Metric watches & alerts" },
  { id: "automations", icon: "gear",     label: "Automations",      blurb: "Condition → effect, & the proposal queue" },
  { id: "actions",     icon: "spark",    label: "Notifications",    blurb: "Webhook, Slack & Jira triggers" },
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
