"use client";

import { useCallback, useEffect, useState } from "react";
import dynamic from "next/dynamic";

import { RangePicker } from "@/components/agentops/RangePicker";
import { Button } from "@/components/ui/button";
import { useTimeRange } from "@/components/agentops/useTimeRange";
import { Workspace, type WorkspaceLayer } from "@/components/Workspace";
import { getNeedsHuman } from "@/lib/api";
import { Icon as Glyph, type IconName } from "@/components/ui/icon";

// ── Lazy panels — load on first open, then keep mounted (Workspace keep-alive),
// so the activity tail, a selected trace and an agent detail survive switches.
const loading = () => (
  <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", background: "var(--bg-0)" }}>
    <div style={{ width: 20, height: 20, border: "2px solid var(--bg-3)", borderTopColor: "var(--blue3)", borderRadius: "50%", animation: "aug-spin 0.7s linear infinite" }} />
  </div>
);

const FleetOverviewPanel = dynamic(() => import("@/components/FleetOverviewPanel").then(m => ({ default: m.FleetOverviewPanel })), { ssr: false, loading });
const AgenticAgentsPanel = dynamic(() => import("@/components/AgenticAgentsPanel").then(m => ({ default: m.AgenticAgentsPanel })), { ssr: false, loading });
const NeedsHumanPanel    = dynamic(() => import("@/components/NeedsHumanPanel").then(m => ({ default: m.NeedsHumanPanel })),       { ssr: false, loading });
const AgenticActivityPanel = dynamic(() => import("@/components/AgenticActivityPanel").then(m => ({ default: m.AgenticActivityPanel })), { ssr: false, loading });
const AutomationsPanel   = dynamic(() => import("@/components/AutomationsPanel").then(m => ({ default: m.AutomationsPanel })),     { ssr: false, loading });

/**
 * This screen's glyphs, by role. The drawings come from the platform icon set
 * (`components/ui/icon.tsx`); this map only says which role each local name means,
 * so the existing call sites and `LAYERS` entries keep working unchanged.
 */
const ROLE: Record<string, IconName> = {
  gauge: "gauge",
  spark: "spark",
  hand: "hand",
  activity: "activity",
  flow: "flow",
};

function Icon({ name, size = 14, color = "currentColor" }: { name: string; size?: number; color?: string }) {
  return (
    <span style={{ color, display: "inline-flex", flexShrink: 0 }}>
      <Glyph name={ROLE[name] ?? "info"} size={size} />
    </span>
  );
}

// `runs` retired 2026-08-30 (B1). Checked before removal, the same audit the
// automations-tab removal ran: no LEGACY_AGENTIC_LAYER entry maps to it, no URL
// parameter persists this layer, and the command palette routes to the workspace,
// not the tab. Its automation strip was the third surface for automation runs
// (Automations → History and Activity → Traces are the others); its phase view —
// the half with no second home — moved to Activity → Phases.
export type AgenticOpsLayer =
  "fleet" | "agents" | "attention" | "activity" | "automations";

// Labels follow docs/GLOSSARY.md — Overview · Roster · Attention · Activity · Runs. The
// inner layer stops being "Agents" now that the workspace is called Agent Ops (a workspace
// containing a tab of the same name is the collision the glossary row exists to prevent),
// and "Run graphs" becomes "Runs". The layer IDS are unchanged, so every deep link holds.
const LAYERS: WorkspaceLayer<AgenticOpsLayer>[] = [
  { id: "fleet",     icon: "gauge",    label: "Overview",  blurb: "What's wrong · what's running · what it cost" },
  { id: "agents",    icon: "spark",    label: "Roster",    blurb: "One agent, fully: health, runs, spend, config" },
  { id: "attention", icon: "hand",     label: "Attention", blurb: "What needs a human, and for how long" },
  { id: "activity",  icon: "activity", label: "Activity",  blurb: "Usage · the live tail · traces · deep-run phases" },
  // Moved here from Operations 2026-08-29 (user-decided). An automation IS an agent
  // operating on a schedule — since VA-9b it names the agent it runs as, every step
  // inherits that agent, and its governed writes are attributed to `agent:<id>` rather
  // than to a cron. Filing it under Monitors said the opposite: that it was a metric
  // watch with side effects, next to the agent plane instead of part of it.
  { id: "automations", icon: "gear",   label: "Automations", blurb: "Scheduled agent work · the proposal queue" },
];

type Props = {
  layer: AgenticOpsLayer;
  /** The connection the Automations layer scopes to — that panel filters by it. */
  connId?: string;
  onLayerChange: (l: AgenticOpsLayer) => void;
  workspaceId?: string;
  workspaceName?: string;
  onOpenInvestigation?: (invId: string) => void;
  onOpenAutomations?: () => void;
  /** DS-5 — destinations an agent's Map can send a reader to, when the shell has them. */
  onOpenIntegrations?: () => void;
  onOpenConnection?: (connectionId: string) => void;
};

/**
 * Agentic Ops — ONE surface for the agent estate, merging the former Control
 * Room, Agents and Fleet tabs: what is running, what it did, what it cost,
 * what needs a human, and who the agents are — rendered from stores that
 * already exist and saying plainly what it cannot measure.
 */
export function AgenticOpsWorkspace({
  layer, onLayerChange, workspaceId, workspaceName,
  connId, onOpenInvestigation, onOpenAutomations,
  onOpenIntegrations, onOpenConnection,
}: Props) {
  // Cross-layer focus: a trace opened from Fleet/Agents/Attention lands in the
  // Activity layer's runs mode; an agent opened from Fleet lands in Agents.
  const [traceFocus, setTraceFocus] = useState<{ traceId?: string; investigationId?: string } | null>(null);
  const [agentFocus, setAgentFocus] = useState<{ id: string; kind: "charter" | "persona" } | null>(null);
  const [attention, setAttention] = useState(0);
  // Creating an agent is reachable from EVERY layer, not just the one whose sidebar happens
  // to hold the roster. A counter rather than a boolean: clicking Create while already on
  // the Roster must re-open the flow, and a bool that is already true fires no change.
  const [createSignal, setCreateSignal] = useState(0);
  // ONE window for the whole surface, held here so every layer reads the same one and a
  // brush drawn on the Overview still applies when the reader switches to Activity. Two
  // independent windows on one page is how two tiles disagree with no visible reason.
  const { range, setKey, setBrush, clearBrush } = useTimeRange();

  // The Attention badge — polled at workspace level so the count is visible
  // from every layer, not only when the Attention panel is open.
  useEffect(() => {
    let alive = true;
    const poll = () => getNeedsHuman(1).then(d => { if (alive) setAttention(d.count); }).catch(() => {});
    poll();
    const iv = setInterval(poll, 20_000);
    return () => { alive = false; clearInterval(iv); };
  }, []);

  // `?create=agent` opens the creation flow on arrival — the command palette's deep link,
  // and a URL anyone can paste. The param is consumed so a refresh does not reopen it.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    if (params.get("create") !== "agent") return;
    params.delete("create");
    const qs = params.toString();
    window.history.replaceState(null, "", `${window.location.pathname}${qs ? `?${qs}` : ""}`);
    onLayerChange("agents");
    setCreateSignal(n => n + 1);
  }, [onLayerChange]);

  const openTraceForInvestigation = useCallback((invId: string) => {
    setTraceFocus({ investigationId: invId });
    onLayerChange("activity");
  }, [onLayerChange]);

  return (
    <Workspace
      layers={LAYERS}
      layer={layer}
      onLayerChange={onLayerChange}
      ariaLabel="Agent Ops views"
      badges={{ attention }}
      headerControls={
        <div style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0 }}>
          <RangePicker range={range} onKey={setKey} onClearBrush={clearBrush} />
        </div>
      }
      headerTrailing={
        // `default`, not a hand-rolled blue: `--primary` IS `--blue3`, so the design
        // system's own CTA variant is the blue this asks for — and it brings the hover
        // and focus states an inline `background` would silently drop.
        <Button variant="default" size="xs"
          title="Create a custom agent — a scope and a stance"
          onClick={() => { onLayerChange("agents"); setCreateSignal(n => n + 1); }}
          style={{ whiteSpace: "nowrap" }}>
          + Create agent
        </Button>
      }
      renderIcon={(name, size, color) => <Icon name={name} size={size} color={color} />}
      renderLayer={id => {
        if (id === "agents") return (
          <AgenticAgentsPanel workspaceId={workspaceId} workspaceName={workspaceName}
            focusAgent={agentFocus} onOpenTrace={openTraceForInvestigation} range={range}
            createSignal={createSignal}
            // DS-5 — a node on an agent's Map opens the surface that owns it. The chains
            // live one layer over, so that one is a layer switch; the rest belong to the
            // app and are only offered when the shell passes them down.
            onOpenAutomations={() => onLayerChange("automations")}
            onOpenIntegrations={onOpenIntegrations}
            onOpenConnection={onOpenConnection} />
        );
        if (id === "attention") return (
          <NeedsHumanPanel onOpenInvestigation={onOpenInvestigation}
            // Automations live HERE now, so "Open automation" switches a layer rather
            // than navigating out to Operations. The prop stays optional for any caller
            // that still wants to hand its own handler in.
            onOpenAutomations={onOpenAutomations ?? (() => onLayerChange("automations"))} />
        );
        if (id === "activity") return (
          <AgenticActivityPanel
            focusInvestigationId={traceFocus?.investigationId}
            focusTraceId={traceFocus?.traceId} range={range} />
        );
        if (id === "automations") return (
          <AutomationsPanel connId={connId} workspaceId={workspaceId} />
        );
        return (
          <FleetOverviewPanel
            range={range} onBrush={setBrush} onClearBrush={clearBrush}
            onOpenAttention={() => onLayerChange("attention")}
            onOpenInvestigation={onOpenInvestigation}
            onOpenAgent={(id, kind) => {
              setAgentFocus({ id, kind });
              onLayerChange("agents");
            }} /> // "fleet"
        );
      }}
    />
  );
}
