"use client";
import { SkeletonRows } from "@/components/ui/motion";

import { useCallback, useEffect, useState } from "react";

import { useVisiblePoll } from "@/lib/useVisiblePoll";
import dynamic from "next/dynamic";

import { RangePicker } from "@/components/agentops/RangePicker";
import { Button } from "@/components/ui/button";
import { useTimeRange } from "@/components/agentops/useTimeRange";
import { Workspace, type WorkspaceLayer } from "@/components/Workspace";
import { getConnections, getDepartureSummary, getNeedsHuman, type Connection } from "@/lib/api";
import { askSpotlight } from "@/lib/commandRegistry";
import { Icon as Glyph, type IconName } from "@/components/ui/icon";

// ── Lazy panels — load on first open, then keep mounted (Workspace keep-alive),
// so the activity tail, a selected trace and an agent detail survive switches.
const loading = () => (
  <div style={{ flex: 1, background: "var(--bg-0)", padding: 16 }}>
    <SkeletonRows rows={6} />
  </div>
);

const FleetOverviewPanel = dynamic(() => import("@/components/FleetOverviewPanel").then(m => ({ default: m.FleetOverviewPanel })), { ssr: false, loading });
const AgenticAgentsPanel = dynamic(() => import("@/components/AgenticAgentsPanel").then(m => ({ default: m.AgenticAgentsPanel })), { ssr: false, loading });
const NeedsHumanPanel    = dynamic(() => import("@/components/NeedsHumanPanel").then(m => ({ default: m.NeedsHumanPanel })),       { ssr: false, loading });
const AgenticActivityPanel = dynamic(() => import("@/components/AgenticActivityPanel").then(m => ({ default: m.AgenticActivityPanel })), { ssr: false, loading });
const AutomationsPanel   = dynamic(() => import("@/components/AutomationsPanel").then(m => ({ default: m.AutomationsPanel })),     { ssr: false, loading });
const HubMapPanel        = dynamic(() => import("@/components/agentops/HubMapPanel").then(m => ({ default: m.HubMapPanel })),      { ssr: false, loading });
const ActionCentrePanel  = dynamic(() => import("@/components/operations/ActionCentrePanel").then(m => ({ default: m.ActionCentrePanel })), { ssr: false, loading });
const DeveloperPanel     = dynamic(() => import("@/components/operations/DeveloperPanel").then(m => ({ default: m.DeveloperPanel })),       { ssr: false, loading });
const WorkPanel          = dynamic(() => import("@/components/operations/WorkPanel").then(m => ({ default: m.WorkPanel })),         { ssr: false, loading });
const DeparturesPanel    = dynamic(() => import("@/components/agentops/DeparturesPanel").then(m => ({ default: m.DeparturesPanel })), { ssr: false, loading });

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
  send: "send",
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
  "fleet" | "agents" | "attention" | "activity" | "automations" | "hub" | "departures"
  | "duties" | "action-centre" | "developer";

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
  // HB-6 — the hub-wide map. The Roster's Map answers "what does THIS agent touch";
  // this layer answers the hub-wide question the roadmap words exactly: every
  // automation on one screen — trigger, destinations, grant, owner, last run, cost,
  // probation state.
  { id: "hub",       icon: "flow",     label: "Hub",       blurb: "Every automation on one screen — where it sends, what it earned" },
  // HB-2 — the departures ledger: what left the platform, what the departure gate held
  // and why, and the two things a person owes it (a probation mark, an owner's answer).
  { id: "departures", icon: "send",    label: "Departures", blurb: "What left, what was held and why — and what needs a person" },
  // The 2027 study's screen 8 — the same estate read by DUTY rather than by agent: what each of
  // the seven duties booked this week, how its runs ended by type, and every principal with what
  // became of its entries. Last in the row, so every layer that was here keeps its place.
  { id: "duties",    icon: "gauge",    label: "By duty",   blurb: "The week by duty: what was booked, what failed and how, what it cost" },
  // Screens 11 and 13: what an action may do on its record, and what an outside agent or a pack
  // author works with. Here rather than as rail rows of their own — the rail keeps every row it
  // had above the fold, and this row scrolls rather than clips.
  { id: "action-centre", icon: "hand", label: "Action centre", blurb: "Every declared action, the level it may run at, and its record" },
  { id: "developer", icon: "gear",     label: "Developer", blurb: "Packs, doors, service principals, kits and the agent contract" },
];

type Props = {
  layer: AgenticOpsLayer;
  /** The connection the Automations layer scopes to — that panel filters by it. */
  connId?: string;
  /** AO-4 — lets the workspace change that connection itself (a picker in its context
   *  bar) instead of sending the reader to the rail. Optional: without it, no picker. */
  onSelectConnection?: (connectionId: string) => void;
  onLayerChange: (l: AgenticOpsLayer) => void;
  workspaceId?: string;
  workspaceName?: string;
  onOpenInvestigation?: (invId: string) => void;
  onOpenAutomations?: () => void;
  /** DS-5 — destinations an agent's Map can send a reader to, when the shell has them. */
  onOpenIntegrations?: () => void;
  onOpenConnection?: (connectionId: string) => void;
  /** PX-5 — open the chat already talking to this agent (the agent surface's Chat door). */
  onChatWithAgent?: (agentId: string) => void;
  /** Doors out of this workspace for its newer layers, when the shell has them: every run; the
   *  declared actions (Intelligence ▸ Actions); the approval trail (Security & Audit ▸ Approvals);
   *  Settings, where packs are managed. */
  onOpenRuns?: () => void;
  onOpenDeclaredActions?: () => void;
  onOpenApprovals?: () => void;
  onOpenSettings?: () => void;
};

/**
 * Agentic Ops — ONE surface for the agent estate, merging the former Control
 * Room, Agents and Fleet tabs: what is running, what it did, what it cost,
 * what needs a human, and who the agents are — rendered from stores that
 * already exist and saying plainly what it cannot measure.
 */
export function AgenticOpsWorkspace({
  layer, onLayerChange, workspaceId, workspaceName,
  connId, onSelectConnection, onOpenInvestigation, onOpenAutomations,
  onOpenIntegrations, onOpenConnection, onChatWithAgent,
  onOpenRuns, onOpenDeclaredActions, onOpenApprovals, onOpenSettings,
}: Props) {
  // Cross-layer focus: a trace opened from Fleet/Agents/Attention lands in the
  // Activity layer's runs mode; an agent opened from Fleet lands in Agents.
  const [traceFocus, setTraceFocus] = useState<{ traceId?: string; investigationId?: string } | null>(null);
  const [agentFocus, setAgentFocus] = useState<{ id: string; kind: "charter" | "persona" } | null>(null);
  // AO-4 — "Open automation" carries its id from every layer; the Automations layer
  // opens that one on arrival rather than the list it is somewhere in.
  const [automationFocus, setAutomationFocus] = useState<string | null>(null);
  const openAutomation = useCallback((automationId?: string) => {
    setAutomationFocus(automationId ?? null);
    onLayerChange("automations");
    onOpenAutomations?.();
  }, [onLayerChange, onOpenAutomations]);
  const openAgent = useCallback((id: string, kind: NonNullable<typeof agentFocus>["kind"] = "persona") => {
    setAgentFocus({ id, kind });
    onLayerChange("agents");
  }, [onLayerChange]);
  // The connection picker's options — read once; a failure leaves the picker absent
  // rather than empty, and the rail still works.
  const [connections, setConnections] = useState<Connection[] | null>(null);
  useEffect(() => {
    if (!onSelectConnection) return;
    let alive = true;
    getConnections().then(c => { if (alive) setConnections(c); }).catch(() => {});
    return () => { alive = false; };
  }, [onSelectConnection]);
  const [attention, setAttention] = useState(0);
  const [departuresOwed, setDeparturesOwed] = useState(0);
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
  const pollBadges = useCallback(() => {
    getNeedsHuman(1).then(d => setAttention(d.count)).catch(() => {});
    // HB-2 — what the departures ledger still needs from a person, on its layer's badge.
    getDepartureSummary().then(d => setDeparturesOwed(d?.awaiting ?? 0)).catch(() => {});
  }, []);
  useEffect(() => { pollBadges(); }, [pollBadges]);
  // Not while the browser tab is in the background (useVisiblePoll); refreshed on return.
  useVisiblePoll(pollBadges, 20_000);

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

  const openAnalysisTrace = useCallback((invId: string) => {
    setTraceFocus({ investigationId: invId });
    onLayerChange("activity");
  }, [onLayerChange]);

  return (
    <Workspace
      layers={LAYERS}
      layer={layer}
      onLayerChange={onLayerChange}
      ariaLabel="Agent Ops views"
      badges={{ attention, departures: departuresOwed }}
      // AO-4 — the "?" opens Spotlight on the arc's own help topic: what the layers are,
      // what each number means, what to do here. Deterministic platform help, not a model call.
      help={() => askSpotlight("help ao")}
      headerControls={onSelectConnection && connections && connections.length > 0 ? (
        <label className="aug-fs-xs" style={{ display: "inline-flex", alignItems: "center", gap: 6,
          color: "var(--t2)" }}>
          Connection
          <select className="aug-input" value={connId ?? ""} aria-label="Connection"
            onChange={e => onSelectConnection(e.target.value)}
            style={{ height: 24, padding: "0 6px" }}>
            {!connId && <option value="">choose…</option>}
            {connections.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
          <span style={{ color: "var(--t3)" }}>scopes Automations and the Action centre; the Hub and Departures stay hub-wide</span>
        </label>
      ) : undefined}
      toolbar={<>
        <RangePicker range={range} onKey={setKey} onClearBrush={clearBrush} />
        {/* The one action, at the right end of the filter row. `default`, not a hand-rolled
            blue: `--primary` IS `--blue3`, so the design system's own CTA variant is the blue
            this asks for — and it brings the hover and focus states an inline `background`
            would silently drop. */}
        <Button variant="default" size="xs"
          title="Create a custom agent — a scope and a stance"
          onClick={() => { onLayerChange("agents"); setCreateSignal(n => n + 1); }}
          style={{ whiteSpace: "nowrap", marginLeft: "auto" }}>
          + Create agent
        </Button>
      </>}
      renderIcon={(name, size, color) => <Icon name={name} size={size} color={color} />}
      renderLayer={id => {
        if (id === "agents") return (
          <AgenticAgentsPanel workspaceId={workspaceId} workspaceName={workspaceName}
            focusAgent={agentFocus} onOpenTrace={openAnalysisTrace} range={range}
            createSignal={createSignal}
            // DS-5 — a node on an agent's Map opens the surface that owns it. The chains
            // live one layer over, so that one is a layer switch; the rest belong to the
            // app and are only offered when the shell passes them down.
            onOpenAutomations={openAutomation}
            onOpenIntegrations={onOpenIntegrations}
            onOpenConnection={onOpenConnection}
            onChatWithAgent={onChatWithAgent} />
        );
        if (id === "attention") return (
          <NeedsHumanPanel onOpenInvestigation={onOpenInvestigation}
            // Automations live HERE now, so "Open automation" switches a layer rather
            // than navigating out to Operations — and lands on the one that was clicked.
            onOpenAutomations={openAutomation} />
        );
        if (id === "activity") return (
          <AgenticActivityPanel
            focusInvestigationId={traceFocus?.investigationId}
            focusTraceId={traceFocus?.traceId} range={range} />
        );
        if (id === "automations") return (
          <AutomationsPanel connId={connId} workspaceId={workspaceId} focusId={automationFocus} />
        );
        if (id === "duties") return (
          <WorkPanel
            onOpenRuns={() => onOpenRuns?.()}
            onOpenDepartures={() => onLayerChange("departures")}
            onOpenActivity={() => onLayerChange("activity")}
            onOpenAgents={() => onLayerChange("agents")}
            onOpenActionCentre={() => onLayerChange("action-centre")}
            onOpenDeveloper={() => onLayerChange("developer")} />
        );
        if (id === "action-centre") return (
          <ActionCentrePanel connections={connections ?? []} selectedConn={connId ?? ""}
            onOpenDeclared={() => onOpenDeclaredActions?.()} onOpenApprovals={() => onOpenApprovals?.()} />
        );
        if (id === "developer") return (
          <DeveloperPanel onOpenPacks={() => onOpenSettings?.()} onOpenIntegrations={() => onOpenIntegrations?.()}
            onOpenDeclared={() => onOpenDeclaredActions?.()} />
        );
        if (id === "departures") return (
          // Hub-wide, like the map: every departure the platform recorded, any connection.
          <DeparturesPanel onOpenAutomation={openAutomation}
            onOpenTrace={openAnalysisTrace} />
        );
        if (id === "hub") return (
          // No connId on purpose: this layer IS the hub-wide answer ("every automation
          // on one screen"). Scoping it to the page's selected connection would rebuild
          // the per-connection Automations layer one tab over. The door still takes
          // ?conn_id for callers that want the narrow read.
          <HubMapPanel onOpenAgent={id => openAgent(id)} onOpenAutomation={openAutomation} />
        );
        return (
          <FleetOverviewPanel
            range={range} onBrush={setBrush} onClearBrush={clearBrush}
            onOpenAttention={() => onLayerChange("attention")}
            onOpenInvestigation={onOpenInvestigation}
            onOpenAgent={(id, kind) => openAgent(id, kind)} /> // "fleet"
        );
      }}
    />
  );
}
