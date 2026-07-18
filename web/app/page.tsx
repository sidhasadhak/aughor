"use client";

import { useEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";

// Always-eager: on the critical path at first render
import { ChatPanel } from "@/components/ChatPanel";
import { InferencePanel } from "@/components/InferencePanel";
import { OrgSettingsPanel } from "@/components/OrgSettingsPanel";
import { setOrgSettingsCache, localizeCurrency } from "@/lib/orgSettings";
import { ExplorationBadge } from "@/components/ExplorationBadge";
import { SchemaProvider } from "@/lib/schema-context";
import { OpenInBuilderProvider } from "@/lib/openInBuilder";
import { getCanvases } from "@/lib/api";
import { CommandPalette } from "@/components/CommandPalette";
import { MiniStat, MiniStatRow } from "@/components/ui/MiniStat";
import { Button } from "@/components/ui/button";
import { UpgradeModal } from "@/components/UpgradeModal";
import { ApprovalModal } from "@/components/ApprovalModal";
import type { IntelLayer } from "@/components/IntelligenceWorkspace";
import type { OpsLayer } from "@/components/OperationsWorkspace";
import type { AgentLayer } from "@/components/AgentWorkspace";
import { Workspace as WorkspaceShell, type WorkspaceLayer } from "@/components/Workspace";
import { ErrorBoundary } from "@/components/ErrorBoundary";

function LoadingPanel() {
  return (
    <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", background: "var(--bg-0)" }}>
      <div style={{ width: 20, height: 20, border: "2px solid var(--bg-3)", borderTopColor: "var(--blue3)", borderRadius: "50%", animation: "aug-spin var(--dur-breath) linear infinite" }} />
    </div>
  );
}

// Lazy panels — only bundled & parsed when the user first navigates to them
const loading = () => <LoadingPanel />;
const ConfigurePanel    = dynamic(() => import("@/components/ConfigurePanel").then(m => ({ default: m.ConfigurePanel })),    { ssr: false, loading });
const HistoryPanel      = dynamic(() => import("@/components/HistoryPanel").then(m => ({ default: m.HistoryPanel })),        { ssr: false, loading });
const HistoryDetailPanel= dynamic(() => import("@/components/HistoryDetailPanel").then(m => ({ default: m.HistoryDetailPanel })), { ssr: false, loading });
// The four Intelligence perspectives (Ontology / Hub / Domain Intel / Org Intel)
// are now lazily loaded *inside* IntelligenceWorkspace, which fans them into
// layers of one unified workspace.
const IntelligenceWorkspace = dynamic(() => import("@/components/IntelligenceWorkspace").then(m => ({ default: m.IntelligenceWorkspace })), { ssr: false, loading });
const OperationsWorkspace = dynamic(() => import("@/components/OperationsWorkspace").then(m => ({ default: m.OperationsWorkspace })), { ssr: false, loading });
const SystemPanel       = dynamic(() => import("@/components/SystemPanel").then(m => ({ default: m.SystemPanel })),          { ssr: false, loading });
const RolesPanel        = dynamic(() => import("@/components/RolesPanel").then(m => ({ default: m.RolesPanel })),            { ssr: false, loading });
const ProcessHealthPanel= dynamic(() => import("@/components/ProcessHealthPanel").then(m => ({ default: m.ProcessHealthPanel })), { ssr: false, loading });
const PlaybookPanel     = dynamic(() => import("@/components/PlaybookPanel").then(m => ({ default: m.PlaybookPanel })),      { ssr: false, loading });
const RecommendationInbox= dynamic(() => import("@/components/RecommendationInbox").then(m => ({ default: m.RecommendationInbox })), { ssr: false, loading });
const DocumentUploader  = dynamic(() => import("@/components/DocumentUploader").then(m => ({ default: m.DocumentUploader })),{ ssr: false, loading });
const CatalogScreen     = dynamic(() => import("@/components/CatalogScreen").then(m => ({ default: m.CatalogScreen })),      { ssr: false, loading });
const CanvasBrowser     = dynamic(() => import("@/components/CanvasBrowser").then(m => ({ default: m.CanvasBrowser })),      { ssr: false, loading });
const CanvasCreator     = dynamic(() => import("@/components/CanvasCreator").then(m => ({ default: m.CanvasCreator })),      { ssr: false, loading });
const CanvasWorkspace   = dynamic(() => import("@/components/CanvasWorkspace").then(m => ({ default: m.CanvasWorkspace })),  { ssr: false, loading });
// Monitors / Action Hub / Security & Audit now render inside OperationsWorkspace (REC-U5).
const QueryBuilder      = dynamic(() => import("@/components/QueryBuilder").then(m => ({ default: m.QueryBuilder })),        { ssr: false, loading });
const MetricsPanel      = dynamic(() => import("@/components/MetricsPanel").then(m => ({ default: m.MetricsPanel })),        { ssr: false, loading });
const SemanticLayerPanel= dynamic(() => import("@/components/SemanticLayerPanel").then(m => ({ default: m.SemanticLayerPanel })), { ssr: false, loading });
const AgentWorkspace    = dynamic(() => import("@/components/AgentWorkspace").then(m => ({ default: m.AgentWorkspace })), { ssr: false, loading });
import { API_BASE } from "@/lib/config";
import {
  getConnections,
  getWorkspaces,
  createWorkspace as apiCreateWorkspace,
  type Workspace,
  addConnection as apiAddConnection,
  deleteConnection as apiDeleteConnection,
  getExplorationStatus,
  getOntology,
  getConnectionFreshness,
  getDomainInsights,
  getEffectiveSettings,
  getJobs,
  cancelJob,
  getAgents,
  patchAgent,
  getLlmConfig,
  type Connection,
  type ExplorationStatus,
  type OntologyGraph,
  type Canvas,
  type FleetJob,
  type AgentRosterEntry,
} from "@/lib/api";
import { costSummary, fmtCompact, fmtMs } from "@/lib/cost";
import { subscribeKernelEvents } from "@/lib/events";

// ── Types ──────────────────────────────────────────────────────────────────────

type NavTab =
  | "home"              // overview dashboard — stats, health, recents, quick input
  | "chat"              // active investigation / chat (hidden from nav)
  | "canvases"
  | "canvas-workspace"
  | "recents"
  | "fleet"              // the agent fleet — runs, status, cost
  | "agents"             // user-defined agents (domain personas, flag agents.user_defined)
  | "inbox"
  | "briefing"
  | "intelligence"      // unified multi-layered Intelligence workspace
  | "intel-hub"         // legacy deep-link → intelligence/hub layer
  | "intel"             // legacy deep-link → intelligence/domains layer
  | "org-intel"         // legacy deep-link → intelligence/org layer
  | "ontology"          // legacy deep-link → intelligence/ontology layer
  | "operations"        // unified Operations workspace (Monitors / Action Hub / Security)
  | "data"              // unified Data workspace (Catalog / Query Builder / Semantic Layer)
  | "health"
  | "playbook"
  | "catalog"
  | "builder"
  | "connections"
  | "metrics"
  | "monitors"
  | "actions"
  | "activity"
  | "security"
  | "semantic"
  | "settings";

type Theme = "dark" | "light";
type AskMode = "ask" | "investigate";

// ── Icon primitives ────────────────────────────────────────────────────────────

const ICON_PATHS: Record<string, string> = {
  home:     "M3 12L12 3l9 9M5 10v9a1 1 0 001 1h4v-5h4v5h4a1 1 0 001-1v-9",
  chat:     "M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z",
  clock:    "M12 22c5.52 0 10-4.48 10-10S17.52 2 12 2 2 6.48 2 12s4.48 10 10 10zm.5-14v5.25l4.5 2.67-.75 1.23L11 14.5V8h1.5z",
  db:       "M12 2C7.58 2 4 3.79 4 6v12c0 2.21 3.58 4 8 4s8-1.79 8-4V6c0-2.21-3.58-4-8-4zm0 2c3.87 0 6 1.5 6 2s-2.13 2-6 2-6-1.5-6-2 2.13-2 6-2zm6 12c0 .5-2.13 2-6 2s-6-1.5-6-2v-2.23C7.61 15.51 9.72 16 12 16s4.39-.49 6-1.23V16zm0-5c0 .5-2.13 2-6 2s-6-1.5-6-2V8.77C7.61 10.51 9.72 11 12 11s4.39-.49 6-1.23V11z",
  builder:  "M3 3h7v7H3V3zm11 0h7v7h-7V3zm0 11h7v7h-7v-7zM3 14h7v7H3v-7z",
  catalog:  "M4 6h16M4 10h16M4 14h16M4 18h16",
  node:     "M12 4a2 2 0 100 4 2 2 0 000-4zM6 18a2 2 0 100 4 2 2 0 000-4zm12 0a2 2 0 100 4 2 2 0 000-4zM12 6v4m0 4v4M8 19h8M14 7l4 10M10 7L6 17",
  settings: "M12 15a3 3 0 100-6 3 3 0 000 6zm7.94-3c0-.32-.03-.63-.07-.94l2.03-1.58a.49.49 0 00.12-.61l-1.92-3.32a.49.49 0 00-.6-.22l-2.39.96a7.07 7.07 0 00-1.62-.94l-.36-2.54a.484.484 0 00-.48-.41h-3.84c-.24 0-.43.17-.47.41l-.36 2.54c-.58.23-1.13.54-1.62.94l-2.39-.96a.48.48 0 00-.6.22L2.07 9.47a.48.48 0 00.12.61l2.03 1.58c-.05.31-.07.63-.07.94s.02.63.07.94l-2.03 1.58a.49.49 0 00-.12.61l1.92 3.32c.12.22.37.29.6.22l2.39-.96c.49.36 1.04.67 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.58-.27 1.13-.58 1.62-.94l2.39.96c.22.07.48 0 .6-.22l1.92-3.32a.48.48 0 00-.12-.61l-2.01-1.58c.05-.31.07-.63.07-.94z",
  search:   "M11 19a8 8 0 100-16 8 8 0 000 16zm10 2l-4.35-4.35",
  plus:     "M12 5v14M5 12h14",
  close:    "M18 6L6 18M6 6l12 12",
  chevd:    "M6 9l6 6 6-6",
  chevr:    "M9 6l6 6-6 6",
  send:     "M22 2L11 13M22 2L15 22l-4-9-9-4 20-7z",
  spark:    "M12 2l2.4 7.4H22l-6.2 4.5 2.4 7.4L12 17l-6.2 4.3 2.4-7.4L2 9.4h7.6L12 2z",
  activity: "M22 12h-4l-3 9L9 3l-3 9H2",
  process:  "M3 6h4v12H3V6zm7-3h4v18h-4V3zm7 6h4v9h-4V9z",
  playbook: "M9 12h6M9 16h4M5 3H3a2 2 0 00-2 2v16a2 2 0 002 2h16a2 2 0 002-2V5a2 2 0 00-2-2h-2M15 3H9a1 1 0 00-1 1v2a1 1 0 001 1h6a1 1 0 001-1V4a1 1 0 00-1-1z",
  check:    "M20 6L9 17l-5-5",
  info:     "M12 22c5.52 0 10-4.48 10-10S17.52 2 12 2 2 6.48 2 12s4.48 10 10 10zm0-14v4m0 4v.01",
  warning:  "M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0zM12 9v4m0 4v.01",
  sun:      "M12 8a4 4 0 100 8 4 4 0 000-8zM12 2v2m0 16v2M4.93 4.93l1.41 1.41m11.32 11.32l1.41 1.41M2 12h2m16 0h2M4.93 19.07l1.41-1.41m11.32-11.32l1.41-1.41",
  moon:     "M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z",
  refresh:  "M23 4v6h-6M1 20v-6h6M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15",
  trash:    "M4 6h16M6 6l1 14h10L18 6M9 6V4h6v2M10 11v6M14 11v6",
  canvas:   "M4 6h16M4 10h16M4 14h8M4 18h5M15 14l2 2 4-4",
  plug:     "M7 2v4M17 2v4M12 13v6M9 19h6M5 6h14l-1.5 7a2 2 0 01-2 1.73H8.5A2 2 0 016.5 13L5 6z",
  metric:   "M3 3v18h18M7 16l4-4 4 4 4-4M7 12l4-8 2 4 2-4 4 8",
  brief:    "M3 5h18M3 9h18M3 13h12M3 17h8",
  layers:   "M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5",
  inbox:    "M22 12h-6l-2 3h-4l-2-3H2M5.45 5.11L2 12v6a2 2 0 002 2h16a2 2 0 002-2v-6l-3.45-6.89A2 2 0 0016.76 4H7.24a2 2 0 00-1.79 1.11z",
  shield:   "M12 2l8 3v6c0 5-3.4 9.1-8 11-4.6-1.9-8-6-8-11V5l8-3zM9.5 12l1.8 1.8L15 9.8",
};

function NavIcon({ name, size = 14, color = "currentColor" }: { name: string; size?: number; color?: string }) {
  const d = ICON_PATHS[name] || ICON_PATHS.info;
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke={color} strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"
      style={{ flexShrink: 0 }}>
      <path d={d} />
    </svg>
  );
}

// ── Aughor logo ────────────────────────────────────────────────────────────────

function AughorLogo() {
  // Real mark — invert to white on the dark app shell, then tint to brand blue
  return (
    <img
      src="/aughor-logo.jpeg"
      width={26}
      height={26}
      alt="Aughor"
      style={{
        display: "block",
        borderRadius: 4,
        // Black mark on white → invert to white, then push toward brand blue via hue
        filter: "invert(1) sepia(1) saturate(2) hue-rotate(185deg) brightness(1.1)",
        opacity: 0.92,
      }}
    />
  );
}

// ── Helpers ────────────────────────────────────────────────────────────────────

/** A finding headline shown as a plain one-line list subtitle: strip markdown emphasis (no bold
 *  rendering here, so `**…**` would otherwise leak literal asterisks) and honour the currency. */
function plainSubtitle(text: string): string {
  return localizeCurrency(text).replace(/\*+/g, "");
}

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function freshnessLabel(ts: string | null): string | null {
  if (!ts) return null;
  const num = Number(ts);
  const d = !isNaN(num) ? new Date(num > 1e10 ? num : num * 1000) : new Date(ts);
  if (isNaN(d.getTime())) return null;
  const diffMs = Date.now() - d.getTime();
  const diffH = diffMs / 3_600_000;
  if (diffH < 1) return "< 1h ago";
  if (diffH < 24) return `${Math.round(diffH)}h ago`;
  const diffD = diffMs / 86_400_000;
  if (diffD < 7) return `${Math.round(diffD)}d ago`;
  return `${d.toLocaleDateString("en-US", { month: "short", day: "numeric" })}`;
}

// ── Workspace switcher ───────────────────────────────────────────────────────
// The top-level scope selector. A Workspace is a named grouping of DB
// connections; switching it re-scopes the whole app (connections, canvases,
// intelligence) — the Databricks model where everything lives in a workspace.
function WorkspaceSwitcher({
  workspaces,
  selectedWorkspace,
  connCount,
  onWorkspaceChange,
  onCreateWorkspace,
}: {
  workspaces: Workspace[];
  selectedWorkspace: string;
  connCount: number;
  onWorkspaceChange: (id: string) => void;
  onCreateWorkspace: (name: string) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const ref = useRef<HTMLDivElement>(null);
  const active = workspaces.find(w => w.id === selectedWorkspace);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) { setOpen(false); setCreating(false); }
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  const submitNew = async () => {
    const name = newName.trim();
    if (!name) return;
    await onCreateWorkspace(name);
    setNewName(""); setCreating(false); setOpen(false);
  };

  return (
    <div ref={ref} style={{ position: "relative", flexShrink: 0 }}>
      <button
        onClick={() => setOpen(v => !v)}
        title="Switch workspace"
        className="aug-btn"
        style={{
          display: "flex", alignItems: "center", gap: 8,
          padding: "5px 10px", borderRadius: "var(--r2)",
          background: open ? "var(--bg-sel)" : "var(--bg-2)",
          border: `1px solid ${open ? "var(--blue2)" : "var(--b1)"}`,
          color: "var(--t1)", maxWidth: 220,
        }}
      >
        <NavIcon name="layers" size={14} color="var(--blue4)" />
        <span style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", minWidth: 0 }}>
          <span style={{ fontSize: 9, color: "var(--t4)", textTransform: "uppercase", letterSpacing: ".06em", lineHeight: 1.1 }}>Workspace</span>
          <span style={{ fontSize: 12, fontWeight: 500, color: "var(--t1)", lineHeight: 1.3, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", maxWidth: 150 }}>
            {active?.name ?? "—"}
          </span>
        </span>
        <NavIcon name="chevd" size={13} color="var(--t3)" />
      </button>

      {open && (
        <div style={{
          position: "absolute", top: "calc(100% + 6px)", right: 0, zIndex: 100,
          minWidth: 260, background: "var(--bg-1)", border: "1px solid var(--b2)",
          borderRadius: "var(--r3)", boxShadow: "var(--shadow-lg, 0 8px 28px rgba(0,0,0,.4))",
          padding: 6,
        }}>
          <div style={{ fontSize: 9, color: "var(--t4)", textTransform: "uppercase", letterSpacing: ".06em", padding: "6px 8px 4px" }}>
            Workspaces
          </div>
          {workspaces.map(w => {
            const on = w.id === selectedWorkspace;
            return (
              <button
                key={w.id}
                onClick={() => { onWorkspaceChange(w.id); setOpen(false); }}
                className="aug-btn"
                style={{
                  display: "flex", alignItems: "center", gap: 9, width: "100%",
                  padding: "7px 8px", borderRadius: "var(--r2)",
                  background: on ? "var(--bg-sel)" : "transparent",
                  border: "1px solid transparent", textAlign: "left",
                }}
                onMouseEnter={e => { if (!on) e.currentTarget.style.background = "var(--bg-hover)"; }}
                onMouseLeave={e => { if (!on) e.currentTarget.style.background = "transparent"; }}
              >
                <NavIcon name="layers" size={14} color={on ? "var(--blue4)" : "var(--t3)"} />
                <span style={{ flex: 1, minWidth: 0 }}>
                  <span style={{ display: "block", fontSize: 12, fontWeight: on ? 500 : 400, color: "var(--t1)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                    {w.name}
                  </span>
                  <span style={{ display: "block", fontSize: 10, color: "var(--t4)" }}>
                    {w.connection_ids.length} connection{w.connection_ids.length === 1 ? "" : "s"}{w.is_default ? " · default" : ""}
                  </span>
                </span>
                {on && <NavIcon name="check" size={13} color="var(--blue4)" />}
              </button>
            );
          })}

          <div style={{ height: 1, background: "var(--b1)", margin: "6px 0" }} />

          {creating ? (
            <div style={{ display: "flex", gap: 6, padding: "2px 4px 4px" }}>
              <input
                autoFocus
                value={newName}
                onChange={e => setNewName(e.target.value)}
                onKeyDown={e => { if (e.key === "Enter") submitNew(); if (e.key === "Escape") { setCreating(false); setNewName(""); } }}
                placeholder="Workspace name…"
                style={{
                  flex: 1, padding: "6px 9px", fontSize: 12,
                  background: "var(--bg-2)", border: "1px solid var(--b2)",
                  borderRadius: "var(--r2)", color: "var(--t1)", outline: "none",
                }}
              />
              <button onClick={submitNew} className="aug-btn aug-btn-secondary" style={{ padding: "6px 12px", fontSize: 12 }}>
                Create
              </button>
            </div>
          ) : (
            <button
              onClick={() => setCreating(true)}
              className="aug-btn"
              style={{
                display: "flex", alignItems: "center", gap: 9, width: "100%",
                padding: "7px 8px", borderRadius: "var(--r2)",
                background: "transparent", border: "1px solid transparent",
                color: "var(--t2)", textAlign: "left",
              }}
              onMouseEnter={e => { e.currentTarget.style.background = "var(--bg-hover)"; }}
              onMouseLeave={e => { e.currentTarget.style.background = "transparent"; }}
            >
              <NavIcon name="plus" size={14} color="var(--t3)" />
              <span style={{ fontSize: 12 }}>New workspace</span>
            </button>
          )}
        </div>
      )}
    </div>
  );
}

// ── Topbar ─────────────────────────────────────────────────────────────────────

function Topbar({
  onSearchOpen,
  onNavigate,
  connections,
  selectedConn,
  workspaces,
  selectedWorkspace,
  onWorkspaceChange,
  onCreateWorkspace,
}: {
  onSearchOpen: () => void;
  onNavigate: (t: NavTab) => void;
  connections: Connection[];
  selectedConn: string;
  workspaces: Workspace[];
  selectedWorkspace: string;
  onWorkspaceChange: (id: string) => void;
  onCreateWorkspace: (name: string) => Promise<void>;
}) {
  return (
    <div className="aug-topbar">
      {/* Logo — same width as sidebar */}
      <div style={{ display: "flex", alignItems: "center", gap: 9, width: 224, flexShrink: 0 }}>
        <AughorLogo />
        <div>
          <div style={{ fontSize: 16, fontWeight: 600, color: "var(--t1)", letterSpacing: ".01em" }}>
            Aughor
          </div>
          {/* <div style={{ fontSize: 11, color: "var(--t4)", letterSpacing: ".06em", textTransform: "uppercase", marginTop: -1 }}>
            Intelligence Platform
          </div> */}
        </div>
      </div>

      {/* Search */}
      <button
        onClick={onSearchOpen}
        style={{
          flex: 1, maxWidth: 520, margin: "0 auto",
          display: "flex", alignItems: "center", gap: 10,
          padding: "6px 12px", borderRadius: "var(--r2)",
          background: "var(--bg-2)", border: "1px solid var(--b1)",
          color: "var(--t3)", fontSize: 12, transition: "all .12s", cursor: "text",
        }}
        onMouseEnter={e => { e.currentTarget.style.borderColor = "var(--b2)"; e.currentTarget.style.color = "var(--t2)"; }}
        onMouseLeave={e => { e.currentTarget.style.borderColor = "var(--b1)"; e.currentTarget.style.color = "var(--t3)"; }}
      >
        <NavIcon name="search" size={13} />
        <span style={{ flex: 1, textAlign: "left" }}>Search tables, analyses, metrics…</span>
        <span style={{ display: "flex", gap: 2, alignItems: "center" }}>
          <kbd style={{ fontSize: 9, padding: "1px 4px", background: "var(--bg-3)", border: "1px solid var(--b2)", borderRadius: 2, color: "var(--t3)", fontFamily: "var(--font-mono)" }}>⌘</kbd>
          <kbd style={{ fontSize: 9, padding: "1px 4px", background: "var(--bg-3)", border: "1px solid var(--b2)", borderRadius: 2, color: "var(--t3)", fontFamily: "var(--font-mono)" }}>K</kbd>
        </span>
      </button>

      {/* Right: workspace switcher (top-level scope) + settings + avatar */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "flex-end", gap: 8, flexShrink: 0, minWidth: 224 }}>
        <WorkspaceSwitcher
          workspaces={workspaces}
          selectedWorkspace={selectedWorkspace}
          connCount={connections.length}
          onWorkspaceChange={onWorkspaceChange}
          onCreateWorkspace={onCreateWorkspace}
        />
        <div style={{
          width: 28, height: 28, borderRadius: "var(--r2)",
          background: "var(--bg-3)", border: "1px solid var(--b2)",
          display: "flex", alignItems: "center", justifyContent: "center",
          color: "var(--t2)", fontSize: 11, fontWeight: 600,
        }}>
          AU
        </div>
      </div>
    </div>
  );
}

// ── Sidebar ────────────────────────────────────────────────────────────────────

// ── Two-tier nav (SOTA pattern: ≤5 primary rail + collapsible secondary) ────────
// Primary rail: the five destinations a user touches every session. Everything
// else is grouped into collapsible sections (collapsed by default), keeping the
// default sidebar to 5 prominent items without losing any feature. Settings lives
// in the topbar (gear). Each id maps 1:1 to an existing render block — no screen
// is removed, only the navigation hierarchy is flattened.
const NAV_PRIMARY = [
  { id: "home",         icon: "home",   label: "Home" },
  { id: "inbox",        icon: "inbox",  label: "Inbox" },
  { id: "canvases",     icon: "canvas", label: "Data Canvas" },
] as const;

const NAV_SECTIONS = [
  {
    label: "Intelligence", // what Aughor knows about your data
    items: [
      { id: "intelligence", icon: "brief",    label: "Briefing" },
      { id: "recents",      icon: "search",   label: "Investigations" },
      { id: "fleet",        icon: "node",     label: "Fleet" },
      { id: "agents",       icon: "spark",    label: "Agents" },
      { id: "health",       icon: "activity", label: "Health" },
      { id: "playbook",     icon: "playbook", label: "Playbook" },
    ],
  },
  {
    label: "Data", // explore and query data directly
    items: [
      { id: "catalog",  icon: "db",      label: "Catalog" },
      { id: "builder",  icon: "builder", label: "Query Builder" },
      { id: "semantic", icon: "layers",  label: "Semantic Layer" },
    ],
  },
  {
    label: "Operations", // monitor, act, govern
    items: [
      { id: "monitors", icon: "activity", label: "Monitors" },
      { id: "actions",  icon: "spark",    label: "Action Hub" },
      { id: "security", icon: "shield",   label: "Security & Audit" },
    ],
  },
] as const;

// The Data rail items render as layers of one Data workspace (REC-U5), mirroring
// Intelligence / Operations. The switcher labels/icons match the sidebar.
type DataLayer = "catalog" | "builder" | "semantic";
const DATA_LAYERS: WorkspaceLayer<DataLayer>[] = [
  { id: "catalog",  icon: "db",      label: "Catalog",       blurb: "Tables, schemas & profiles" },
  { id: "builder",  icon: "builder", label: "Query Builder", blurb: "Compose SQL visually" },
  { id: "semantic", icon: "layers",  label: "Semantic Layer", blurb: "Metrics, entities & glossary" },
];

function Sidebar({
  tab,
  onNavigate,
  selectedConn,
}: {
  tab: NavTab;
  onNavigate: (t: NavTab) => void;
  selectedConn: string;
}) {
  const renderItem = (item: { id: string; icon: string; label: string }) => (
    <button
      key={item.id}
      className={`aug-nav-item${tab === item.id ? " active" : ""}`}
      onClick={() => onNavigate(item.id as NavTab)}
      // WP-11 a11y (§1.7-7): the visible <span> label wasn't computing an accessible name,
      // so every nav button read as anonymous. An explicit aria-label guarantees the name;
      // aria-current marks the active destination for screen readers.
      aria-label={item.label}
      aria-current={tab === item.id ? "page" : undefined}
    >
      <NavIcon name={item.icon} size={14} color={tab === item.id ? "var(--blue4)" : "currentColor"} />
      <span>{item.label}</span>
      {/* Catalog is a catalog, not a monitor — no exploration badge here */}
    </button>
  );

  return (
    <nav className="aug-sidebar">
      <div style={{ flex: 1, overflowY: "auto", padding: "6px 8px 6px" }}>
        {/* Primary rail */}
        {NAV_PRIMARY.map(renderItem)}

        {/* Secondary sections — always expanded (static group headers) */}
        {NAV_SECTIONS.map(section => (
          <div key={section.label}>
            <div className="aug-nav-group">{section.label}</div>
            {section.items.map(renderItem)}
          </div>
        ))}
      </div>
      <div style={{ padding: "6px 8px 10px", borderTop: "1px solid var(--b0)" }}>
        {renderItem({ id: "settings", icon: "settings", label: "Settings" })}
        <div style={{ fontSize: 10, color: "var(--t4)", textAlign: "center", letterSpacing: ".04em", marginTop: 6 }}>
          v2 · Local
        </div>
      </div>
    </nav>
  );
}

// ── Search overlay ─────────────────────────────────────────────────────────────

function SearchOverlay({
  onClose,
  onNavigate,
  onGoToChat,
}: {
  onClose: () => void;
  onNavigate: (t: NavTab) => void;
  onGoToChat: (q?: string) => void;
}) {
  const [q, setQ] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => { inputRef.current?.focus(); }, []);
  useEffect(() => {
    const fn = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", fn);
    return () => window.removeEventListener("keydown", fn);
  }, [onClose]);

  const suggestions = [
    { label: "New Investigation", icon: "spark",    action: () => { onGoToChat(); onClose(); } },
    { label: "Browse Schema",     icon: "catalog",  action: () => { onNavigate("catalog"); onClose(); } },
    { label: "Ontology Graph",    icon: "node",     action: () => { onNavigate("ontology"); onClose(); } },
    { label: "Domain Intelligence", icon: "process", action: () => { onNavigate("intel"); onClose(); } },
    { label: "Activity Log",      icon: "activity", action: () => { onNavigate("activity"); onClose(); } },
    { label: "Playbook",          icon: "playbook", action: () => { onNavigate("playbook"); onClose(); } },
  ].filter(s => !q || s.label.toLowerCase().includes(q.toLowerCase()));

  const questions = [
    "Why did revenue drop 8% last month?",
    "Which customers have the highest payment failure rate?",
    "What is our MRR this month?",
    "Show top 10 products by revenue",
    "Is APAC churn a trend or one-time event?",
  ].filter(s => !q || s.toLowerCase().includes(q.toLowerCase()));

  return (
    <>
      <div onClick={onClose} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.65)", backdropFilter: "blur(3px)", zIndex: 200 }} />
      <div style={{
        position: "fixed", top: "16%", left: "50%", transform: "translateX(-50%)",
        zIndex: 201, width: "100%", maxWidth: 560,
        background: "var(--bg-3)", border: "1px solid var(--b2)",
        borderRadius: "var(--r3)", overflow: "hidden",
        boxShadow: "0 24px 48px rgba(0,0,0,.6)",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "12px 14px", borderBottom: "1px solid var(--b1)" }}>
          <NavIcon name="search" size={14} color="var(--t3)" />
          <input
            ref={inputRef}
            value={q}
            onChange={e => setQ(e.target.value)}
            placeholder="Search tables, analyses, metrics…"
            style={{ flex: 1, background: "transparent", border: "none", outline: "none", fontSize: 13, color: "var(--t1)", fontFamily: "var(--font-ui)" }}
          />
          <kbd
            onClick={onClose}
            style={{ fontSize: 9, padding: "2px 6px", background: "var(--bg-2)", border: "1px solid var(--b2)", borderRadius: 2, color: "var(--t3)", cursor: "pointer", fontFamily: "var(--font-mono)" }}
          >
            ESC
          </kbd>
        </div>
        <div style={{ maxHeight: 360, overflowY: "auto" }}>
          {suggestions.length > 0 && (
            <div style={{ padding: "6px 0" }}>
              <div className="aug-label" style={{ padding: "4px 14px 2px" }}>Navigation</div>
              {suggestions.map((s, i) => (
                <button key={i} onClick={s.action} style={{
                  width: "100%", display: "flex", alignItems: "center", gap: 10,
                  padding: "8px 14px", background: "none", border: "none",
                  color: "var(--t2)", fontSize: 12, cursor: "pointer", transition: "all .1s", textAlign: "left",
                }}
                  onMouseEnter={e => { e.currentTarget.style.background = "var(--bg-hover)"; e.currentTarget.style.color = "var(--t1)"; }}
                  onMouseLeave={e => { e.currentTarget.style.background = "none"; e.currentTarget.style.color = "var(--t2)"; }}
                >
                  <NavIcon name={s.icon} size={13} />{s.label}
                </button>
              ))}
            </div>
          )}
          {questions.length > 0 && (
            <div style={{ padding: "6px 0", borderTop: "1px solid var(--b0)" }}>
              <div className="aug-label" style={{ padding: "4px 14px 2px" }}>Ask a question</div>
              {questions.map((question, i) => (
                <button key={i} onClick={() => { onGoToChat(question); onClose(); }} style={{
                  width: "100%", display: "flex", alignItems: "center", gap: 10,
                  padding: "8px 14px", background: "none", border: "none",
                  color: "var(--t2)", fontSize: 12, cursor: "pointer", transition: "all .1s", textAlign: "left",
                }}
                  onMouseEnter={e => { e.currentTarget.style.background = "var(--bg-hover)"; e.currentTarget.style.color = "var(--t1)"; }}
                  onMouseLeave={e => { e.currentTarget.style.background = "none"; e.currentTarget.style.color = "var(--t2)"; }}
                >
                  <NavIcon name="spark" size={13} />{question}
                </button>
              ))}
            </div>
          )}
        </div>
        <div style={{ padding: "6px 14px", borderTop: "1px solid var(--b0)", display: "flex", gap: 12 }}>
          {[["↑↓", "Navigate"], ["↵", "Select"], ["ESC", "Close"]].map(([k, l]) => (
            <span key={k} style={{ display: "flex", alignItems: "center", gap: 4 }}>
              <kbd style={{ fontSize: 9, padding: "1px 5px", background: "var(--bg-2)", border: "1px solid var(--b2)", borderRadius: 2, color: "var(--t3)", fontFamily: "var(--font-mono)" }}>{k}</kbd>
              <span style={{ fontSize: 10, color: "var(--t4)" }}>{l}</span>
            </span>
          ))}
        </div>
      </div>
    </>
  );
}

// ── Stat card ──────────────────────────────────────────────────────────────────

function StatCard({ value, label, accent, sub, onClick }: {
  value: string | number;
  label: string;
  accent: string;
  sub?: string;
  onClick?: () => void;
}) {
  const [hov, setHov] = useState(false);
  return (
    <div
      onClick={onClick}
      onMouseEnter={() => setHov(true)}
      onMouseLeave={() => setHov(false)}
      style={{
        flex: 1, padding: "14px 16px",
        background: hov && onClick ? "var(--bg-3)" : "var(--bg-2)",
        border: `1px solid ${hov && onClick ? accent + "66" : "var(--b1)"}`,
        borderRadius: "var(--r3)", cursor: onClick ? "pointer" : "default",
        transition: "background .12s, border-color .12s", minWidth: 0,
      }}
    >
      <div style={{ fontSize: 24, fontWeight: 600, color: "var(--t1)", letterSpacing: "-.02em", lineHeight: 1, fontFamily: "var(--font-mono)" }}>{value}</div>
      <div style={{ fontSize: 11, color: "var(--t3)", marginTop: 5 }}>{label}</div>
      {sub && <div style={{ fontSize: 10, color: accent, marginTop: 3, fontFamily: "var(--font-mono)" }}>{sub}</div>}
      <div style={{ width: 20, height: 2, background: accent, borderRadius: 1, marginTop: 10 }} />
    </div>
  );
}

// ── Home screen ────────────────────────────────────────────────────────────────

type RecentInv = { id: string; question: string; started_at: string; status: string; headline: string | null; connection_id?: string; canvas_id?: string | null };

function HomeScreen({
  connections,
  selectedConn,
  workspaceId,
  onGoToChat,
  onNavigate,
  onOpenInvestigation,
  onAddConnection,
  onTryDemo,
}: {
  connections: Connection[];
  selectedConn: string;
  workspaceId: string;
  onGoToChat: (q?: string, mode?: AskMode) => void;
  onNavigate: (t: NavTab) => void;
  onOpenInvestigation: (id: string, kind?: "investigation" | "chat", connectionId?: string, canvasId?: string | null) => void;
  onAddConnection: () => void;
  onTryDemo: () => void;
}) {
  const [recentInvs, setRecentInvs] = useState<RecentInv[]>([]);
  const [exploration, setExploration] = useState<ExplorationStatus | null>(null);
  const [ontology, setOntology] = useState<OntologyGraph | null>(null);
  const [domainInsightCount, setDomainInsightCount] = useState<number | null>(null);
  // WP-11 — ask-on-Home: the composer as Home's hero. Submitting routes into the chat with
  // the question pre-filled + fired (goToChat), so Home is a launchpad, not a dead dashboard.
  const [homeQ, setHomeQ] = useState("");
  const [homeMode, setHomeMode] = useState<AskMode>("ask");
  const submitHome = () => {
    const q = homeQ.trim();
    if (q) { onGoToChat(q, homeMode); setHomeQ(""); }
  };

  useEffect(() => {
    fetch(`${API_BASE}/investigations${workspaceId ? `?workspace_id=${encodeURIComponent(workspaceId)}` : ""}`)
      .then(r => r.json())
      .then(d => setRecentInvs(Array.isArray(d) ? d.slice(0, 8) : []))
      .catch(() => {});
    getExplorationStatus(selectedConn).then(setExploration).catch(() => {});
    getOntology(selectedConn).then(setOntology).catch(() => {});
    getDomainInsights(selectedConn)
      .then(d => setDomainInsightCount(Object.values(d).reduce((sum, v) => sum + (v as { insights: unknown[] }).insights.length, 0)))
      .catch(() => {});
  }, [selectedConn, workspaceId]);

  const tables   = exploration?.tables_total    ?? "—";
  const insights = domainInsightCount ?? "—";
  const entities = ontology ? Object.keys(ontology.entities).length : "—";
  const queries  = exploration?.queries_executed ?? "—";

  return (
    <div className="aug-screen">
      <div className="aug-content-header">
        <NavIcon name="home" size={14} color="var(--t3)" />
        <span style={{ fontSize: 13, fontWeight: 500 }}>Home</span>
      </div>

      <div style={{ flex: 1, overflowY: "auto", padding: "24px 28px", display: "flex", flexDirection: "column", gap: 24 }}>

        {/* WP-11 — ask-on-Home hero: the composer, front and centre. Shown once a connection
            exists (before that, the first-run funnel guides connecting). Enter (or Ask) fires
            the question into the chat with the chosen depth. */}
        {connections.length > 0 && (
          <div style={{ background: "var(--bg-2)", border: "1px solid var(--b1)", borderRadius: "var(--r3)", padding: "18px 20px" }}>
            <div style={{ fontSize: 13.5, fontWeight: 650, color: "var(--t1)", marginBottom: 10 }}>Ask anything about your data</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <textarea
                value={homeQ}
                onChange={e => setHomeQ(e.target.value)}
                onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submitHome(); } }}
                placeholder="e.g. Where are we losing money? · Which segments churn most? · How did revenue trend last quarter?"
                rows={2}
                aria-label="Ask a question about your data"
                className="aug-input"
                style={{ width: "100%", resize: "vertical", fontSize: 13, lineHeight: 1.5, padding: "10px 12px" }}
              />
              <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                <div role="group" aria-label="Answer depth" style={{ display: "flex", gap: 4, padding: 3, background: "var(--bg-3)", borderRadius: "var(--r2)", border: "1px solid var(--b1)" }}>
                  <Button size="xs" variant={homeMode === "ask" ? "default" : "ghost"} aria-pressed={homeMode === "ask"} onClick={() => setHomeMode("ask")}>Insight</Button>
                  <Button size="xs" variant={homeMode === "investigate" ? "default" : "ghost"} aria-pressed={homeMode === "investigate"} onClick={() => setHomeMode("investigate")}>Deep</Button>
                </div>
                <span style={{ fontSize: 11, color: "var(--t4)" }}>
                  {homeMode === "ask" ? "a fast, grounded answer" : "a full multi-step investigation"}
                </span>
                <div style={{ flex: 1 }} />
                <Button size="sm" disabled={!homeQ.trim()} onClick={submitHome}>Ask →</Button>
              </div>
            </div>
          </div>
        )}

        {/* First-run funnel — shown until the user runs their first investigation */}
        {recentInvs.length === 0 && (
          <div style={{ background: "var(--bg-2)", border: "1px solid var(--b1)", borderRadius: "var(--r3)", padding: "22px 24px" }}>
            <div style={{ fontSize: 15, fontWeight: 650, color: "var(--t1)", marginBottom: 4 }}>Welcome to Aughor</div>
            <div style={{ fontSize: 12, color: "var(--t3)", marginBottom: 18, lineHeight: 1.5 }}>
              Autonomous analysis of your data — ask in plain English, get investigated answers. Get started in three steps:
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 10 }}>
              {[
                { n: 1, icon: "db",      title: "Connect your data", desc: "Add a database, or upload a CSV / Parquet / Excel file.",                 cta: "Add a connection", accent: "var(--cyn3)", action: onAddConnection },
                { n: 2, icon: "brief",   title: "Explore the demo",  desc: "No data handy? Browse the bundled BeautyCommerce sample workspace.",       cta: "Open the demo",    accent: "var(--vio3)", action: onTryDemo },
                { n: 3, icon: "home",    title: "Ask a question",    desc: "Ask anything — Aughor writes the SQL and runs the investigation for you.", cta: "Ask now",          accent: "var(--grn3)", action: () => onGoToChat() },
              ].map(s => (
                <div key={s.n} style={{ border: "1px solid var(--b1)", borderRadius: "var(--r2)", padding: 14, background: "var(--bg-3)", display: "flex", flexDirection: "column" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                    <div style={{ width: 22, height: 22, borderRadius: "50%", background: s.accent + "22", border: `1px solid ${s.accent}55`, color: s.accent, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 11, fontWeight: 700 }}>{s.n}</div>
                    <NavIcon name={s.icon} size={13} color={s.accent} />
                    <div style={{ fontSize: 12.5, fontWeight: 600, color: "var(--t1)" }}>{s.title}</div>
                  </div>
                  <div style={{ fontSize: 11, color: "var(--t3)", lineHeight: 1.5, flex: 1, marginBottom: 12 }}>{s.desc}</div>
                  <button onClick={s.action} style={{ alignSelf: "flex-start", fontSize: 11, fontWeight: 600, color: s.accent, background: s.accent + "14", border: `1px solid ${s.accent}44`, borderRadius: "var(--r2)", padding: "6px 12px", cursor: "pointer" }}>{s.cta} →</button>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Get Started — primary launcher (top of page) */}
        <div>
          <div className="aug-label" style={{ marginBottom: 12 }}>Get Started</div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 10 }}>
            {[
              { icon: "canvas",  name: "Data Canvas",      desc: "Curated schema + table spaces to explore and investigate.",      accent: "var(--vio3)", action: () => onNavigate("canvases") },
              { icon: "db",      name: "Catalog",       desc: "Browse connections, tables, columns, and data distributions.",   accent: "var(--cyn3)", action: () => onNavigate("catalog") },
              { icon: "brief",   name: "Briefing",      desc: "Your unified intelligence digest across the workspace.",          accent: "var(--grn3)", action: () => onNavigate("intelligence") },
              { icon: "builder", name: "Query Builder", desc: "Compose and run SQL against any connection, with results.",       accent: "var(--amb3)", action: () => onNavigate("builder") },
            ].map(a => (
              <button key={a.name} onClick={a.action} style={{
                textAlign: "left", padding: "14px 14px",
                background: "var(--bg-2)", border: "1px solid var(--b1)",
                borderRadius: "var(--r3)", cursor: "pointer", transition: "all .12s",
              }}
                onMouseEnter={e => { e.currentTarget.style.borderColor = a.accent + "66"; e.currentTarget.style.background = "var(--bg-3)"; }}
                onMouseLeave={e => { e.currentTarget.style.borderColor = "var(--b1)"; e.currentTarget.style.background = "var(--bg-2)"; }}
              >
                <div style={{ width: 30, height: 30, borderRadius: "var(--r2)", background: a.accent + "18", border: `1px solid ${a.accent}44`, display: "flex", alignItems: "center", justifyContent: "center", marginBottom: 10, color: a.accent }}>
                  <NavIcon name={a.icon} size={14} color={a.accent} />
                </div>
                <div style={{ fontSize: 12, fontWeight: 600, color: "var(--t1)", marginBottom: 4 }}>{a.name}</div>
                <div style={{ fontSize: 11, color: "var(--t3)", lineHeight: 1.5 }}>{a.desc}</div>
              </button>
            ))}
          </div>
        </div>

        {/* Stats */}
        <div style={{ display: "flex", gap: 10 }}>
          <StatCard value={tables}   label="Tables in schema"    accent="var(--blue3)"  sub={exploration ? `↑ ${exploration.tables_total} total` : undefined} onClick={() => onNavigate("catalog")} />
          <StatCard value={entities} label="Entities mapped"     accent="var(--vio3)"   sub="ontology layer"     onClick={() => onNavigate("ontology")} />
          <StatCard value={insights} label="Insights discovered" accent="var(--grn3)"   sub="domain intel"       onClick={() => onNavigate("intel")} />
          <StatCard value={queries}  label="Queries executed"    accent="var(--amb3)"   sub="last 7 days"        onClick={() => onNavigate("activity")} />
        </div>

        {/* Health scorecard — surfaced above the fold */}
        <ProcessHealthPanel connectionId={selectedConn} onInvestigate={q => onGoToChat(q, "investigate")} />

        {/* Recent activity */}
        <div>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
            <div className="aug-label">Recent Activity</div>
            <button onClick={() => onNavigate("recents")} style={{ fontSize: 11, color: "var(--blue4)", background: "none", border: "none", cursor: "pointer" }}>View all →</button>
          </div>
          {recentInvs.length === 0 ? (
            <div style={{ padding: "28px 0", textAlign: "center" }}>
              <p style={{ fontSize: 12, color: "var(--t3)" }}>No investigations yet — start by asking a question.</p>
            </div>
          ) : (
            <div style={{ background: "var(--bg-2)", border: "1px solid var(--b1)", borderRadius: "var(--r3)", overflow: "hidden" }}>
              <table className="aug-dt" style={{ width: "100%" }}>
                <thead>
                  <tr>
                    <th>Question</th>
                    <th>Time</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {recentInvs.slice(0, 5).map((inv) => (
                    <tr key={inv.id} style={{ cursor: "pointer" }} onClick={() => onOpenInvestigation(inv.id, "investigation", inv.connection_id, inv.canvas_id)}>
                      <td style={{ maxWidth: 400 }}>
                        <div style={{ fontSize: 12, color: "var(--t1)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontFamily: "var(--font-ui)" }}>{plainSubtitle(inv.question)}</div>
                        {inv.headline && <div style={{ fontSize: 10, color: "var(--t3)", marginTop: 2 }}>{plainSubtitle(inv.headline)}</div>}
                      </td>
                      <td style={{ color: "var(--t3)", fontSize: 11 }}>{timeAgo(inv.started_at)}</td>
                      <td>
                        {inv.status === "complete" && <span className="aug-tag aug-tag-green">Completed</span>}
                        {inv.status === "timed_out" && <span className="aug-tag aug-tag-amber">Timed out</span>}
                        {inv.status === "running"   && <span className="aug-tag aug-tag-blue">Running</span>}
                        {inv.status === "failed"    && <span className="aug-tag aug-tag-red">Failed</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

      </div>
    </div>
  );
}

// ── Recents screen ─────────────────────────────────────────────────────────────

function RecentsScreen({ onGoToChat, onOpenInvestigation, workspaceId }: { onGoToChat: (q?: string) => void; onOpenInvestigation: (id: string, kind: "investigation" | "chat", connectionId?: string, canvasId?: string | null) => void; workspaceId?: string }) {
  const [activities, setActivities] = useState<Array<{ id: string; question: string; started_at: string; status: string; headline: string | null; kind?: string; connection_id?: string; canvas_id?: string | null }>>([]);
  const [filter, setFilter] = useState<"all" | "investigation" | "chat">("all");

  useEffect(() => {
    let alive = true;
    const load = () => {
      const ctrl = new AbortController();
      const to = setTimeout(() => ctrl.abort(), 8_000);
      fetch(`${API_BASE}/investigations${workspaceId ? `?workspace_id=${encodeURIComponent(workspaceId)}` : ""}`, { signal: ctrl.signal })
        .then(r => r.json())
        .then(d => { if (alive) setActivities(Array.isArray(d) ? d : []); })
        .catch(() => {})
        .finally(() => clearTimeout(to));
    };
    load();
    // Live refresh on investigation lifecycle events — this screen previously
    // fetched ONCE on mount, so runs started elsewhere (another tab, the API)
    // never appeared until a full page reload. Mirrors HistoryPanel's wiring.
    const unsub = subscribeKernelEvents(() => load(), { kinds: ["investigation."] });
    return () => { alive = false; unsub(); };
  }, [workspaceId]);

  const shown = filter === "all" ? activities : activities.filter(a => (filter === "chat" ? a.kind === "chat" : a.kind !== "chat"));

  return (
    <div className="aug-screen">
      <div className="aug-content-header">
        <NavIcon name="clock" size={14} color="var(--t3)" />
        <span style={{ fontSize: 13, fontWeight: 500 }}>Recents</span>
        <div style={{ display: "flex", gap: 4, marginLeft: 12 }}>
          {(["all", "investigation", "chat"] as const).map(f => (
            <button key={f} onClick={() => setFilter(f)} style={{
              padding: "3px 10px", borderRadius: "var(--r2)", fontSize: 11, fontWeight: 500, cursor: "pointer",
              background: filter === f ? "var(--bg-sel)" : "transparent",
              border: `1px solid ${filter === f ? "var(--blue2)" : "var(--b1)"}`,
              color: filter === f ? "var(--blue5)" : "var(--t3)", transition: "all .1s",
            }}>
              {f === "all" ? "All" : f.charAt(0).toUpperCase() + f.slice(1)}
            </button>
          ))}
        </div>
      </div>
      <div style={{ flex: 1, overflowY: "auto", padding: "18px 20px" }}>
        {activities.length > 0 && (
          <MiniStatRow>
            <MiniStat value={activities.length} label="Total" />
            <MiniStat value={activities.filter(a => a.kind !== "chat").length} label="Investigations" tone="var(--blue4)" />
            <MiniStat value={activities.filter(a => a.status === "complete").length} label="Completed" tone="var(--grn4)" />
          </MiniStatRow>
        )}
        {shown.length === 0 ? (
          <div style={{ padding: "40px 0", textAlign: "center" }}>
            <p style={{ fontSize: 12, color: "var(--t3)" }}>No activity yet — start by asking a question.</p>
          </div>
        ) : (
          /* Card grid — each run reads as a tile: question + the answer headline + status */
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: 14 }}>
            {shown.map(a => {
              const isChat = a.kind === "chat";
              const st: [string, string] | null =
                a.status === "complete"  ? ["aug-tag-green", "Completed"] :
                a.status === "timed_out" ? ["aug-tag-amber", "Timed out"] :
                a.status === "running"   ? ["aug-tag-blue",  "Running"]   :
                a.status === "failed"    ? ["aug-tag-red",   "Failed"]    : null;
              const open = () => onOpenInvestigation(a.id, isChat ? "chat" : "investigation", a.connection_id, a.canvas_id);
              return (
                <div key={a.id} role="button" tabIndex={0} onClick={open}
                  onKeyDown={e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); } }}
                  style={{
                    display: "flex", flexDirection: "column", gap: 10, padding: 16, minHeight: 128, cursor: "pointer",
                    background: "var(--bg-2)", border: "1px solid var(--b1)", borderRadius: "var(--r3)",
                    transition: "border-color .12s, background .12s",
                  }}
                  onMouseEnter={e => { e.currentTarget.style.borderColor = "var(--b3)"; e.currentTarget.style.background = "var(--bg-3)"; }}
                  onMouseLeave={e => { e.currentTarget.style.borderColor = "var(--b1)"; e.currentTarget.style.background = "var(--bg-2)"; }}
                >
                  <div style={{ display: "flex", alignItems: "flex-start", gap: 11 }}>
                    <div style={{
                      width: 32, height: 32, borderRadius: "var(--r2)", flexShrink: 0,
                      background: isChat ? "color-mix(in srgb, var(--blue3) 15%, transparent)" : "color-mix(in srgb, var(--vio3) 18%, transparent)",
                      border: `1px solid ${isChat ? "color-mix(in srgb, var(--blue3) 30%, transparent)" : "color-mix(in srgb, var(--vio3) 32%, transparent)"}`,
                      display: "flex", alignItems: "center", justifyContent: "center",
                    }}>
                      <NavIcon name={isChat ? "chat" : "spark"} size={15} color={isChat ? "var(--blue4)" : "var(--vio4)"} />
                    </div>
                    <div style={{ minWidth: 0, flex: 1 }}>
                      <div style={{
                        fontSize: 13, fontWeight: 600, color: "var(--t1)", lineHeight: 1.35,
                        display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden",
                      }}>
                        {plainSubtitle(a.question)}
                      </div>
                      <div style={{ fontSize: 11, color: "var(--t3)", marginTop: 2 }}>
                        {isChat ? "Chat" : "Agentic"}{a.connection_id ? ` · ${a.connection_id}` : ""}
                      </div>
                    </div>
                  </div>
                  <div style={{
                    flex: 1, fontSize: 12, color: "var(--t3)", lineHeight: 1.5,
                    display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden",
                  }}>
                    {a.headline ? plainSubtitle(a.headline) : "—"}
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    {st && <span className={`aug-tag ${st[0]}`}>{st[1]}</span>}
                    <span style={{ marginLeft: "auto", fontSize: 11, color: "var(--t4)" }}>{timeAgo(a.started_at)}</span>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Fleet screen — the agents working your data (R2) ────────────────────────────

function StateTag({ state }: { state: string }) {
  const map: Record<string, [string, string]> = {
    RUNNING:   ["aug-tag-blue",  "Running"],
    PENDING:   ["aug-tag-blue",  "Pending"],
    SUCCEEDED: ["aug-tag-green", "Succeeded"],
    FAILED:    ["aug-tag-red",   "Failed"],
    CANCELLED: ["aug-tag-amber", "Cancelled"],
    PAUSED:    ["aug-tag-amber", "Paused"],
  };
  const [cls, label] = map[state] || ["aug-tag", state];
  return <span className={`aug-tag ${cls}`}>{label}</span>;
}

const AGENT_ICON: Record<string, string> = {
  scout: "search", analyst: "node", watcher: "activity", briefer: "brief", curator: "layers",
};

function fmtBudget(n: number | null): string {
  return n == null ? "∞" : fmtCompact(n);
}

// The Agents tab — the fleet roster + governance (enable/pause + budget + spend).
function AgentsPanel({ workspaceId, workspaceName }: { workspaceId?: string; workspaceName?: string }) {
  const [agents, setAgents] = useState<AgentRosterEntry[]>([]);
  const [tried, setTried] = useState(false);

  useEffect(() => {
    let alive = true;
    getAgents(workspaceId)
      .then(a => { if (alive) { setAgents(a); setTried(true); } })
      .catch(() => { if (alive) setTried(true); });
    return () => { alive = false; };
  }, [workspaceId]);   // re-resolve governance when the scope (Org vs workspace) changes
  const reload = () => getAgents(workspaceId).then(setAgents);
  const toggle = (id: string, enabled: boolean) => { patchAgent(id, { enabled, workspace_id: workspaceId }).then(() => reload()); };
  const setModel = (id: string, model: string) => { patchAgent(id, { model, workspace_id: workspaceId }).then(() => reload()); };

  // Available LLM models for the per-agent override (the distinct effective models).
  const [models, setModels] = useState<string[]>([]);
  useEffect(() => {
    getLlmConfig()
      .then(c => setModels([...new Set(Object.values(c.models || {}))].filter(Boolean) as string[]))
      .catch(() => setModels([]));
  }, []);

  if (!tried) {
    return <div style={{ padding: "40px 0", textAlign: "center" }}><p style={{ fontSize: 12, color: "var(--t3)" }}>Loading agents…</p></div>;
  }
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <p style={{ fontSize: 11, color: "var(--t3)", margin: 0 }}>
        Governing{" "}
        <strong style={{ color: "var(--t2)" }}>
          {workspaceName ? `workspace “${workspaceName}”` : "your Org (all workspaces)"}
        </strong>{" "}
        — pause an agent or cap its per-run budget. Budgets are <strong style={{ color: "var(--t2)" }}>enforced live</strong>:
        a run that exceeds its token or time budget is cancelled, because every run is metered.
        {workspaceName && " Unset values inherit the Org default."}
      </p>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(400px, 1fr))", gap: 12 }}>
      {agents.map(a => {
        const isBackground = a.lane === "background";
        const enabled = a.governance.enabled;
        return (
          <div key={a.id} style={{
            background: "var(--bg-2)", border: "1px solid var(--b1)", borderRadius: "var(--r3)",
            padding: "14px 16px", opacity: a.reserved ? 0.6 : 1,
            display: "flex", flexDirection: "column", gap: 8, transition: "border-color .12s",
          }}
            onMouseEnter={e => { e.currentTarget.style.borderColor = "var(--b3)"; }}
            onMouseLeave={e => { e.currentTarget.style.borderColor = "var(--b1)"; }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <div style={{ width: 30, height: 30, borderRadius: 8, background: "var(--bg-3)", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                <NavIcon name={AGENT_ICON[a.id] || "spark"} size={15} color="var(--t2)" />
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                  <span style={{ fontSize: 13, fontWeight: 600, color: "var(--t1)" }}>{a.name}</span>
                  <span className={`aug-tag ${isBackground ? "aug-tag-blue" : "aug-tag-violet"}`}>{isBackground ? "Background" : "Interactive"}</span>
                  {a.reserved && <span className="aug-tag">Reserved</span>}
                </div>
                <div style={{ fontSize: 11, color: "var(--t3)" }}>{a.role}</div>
              </div>
              {a.reserved ? (
                <span style={{ fontSize: 10, color: "var(--t4)" }}>wiring soon</span>
              ) : isBackground ? (
                <button onClick={() => toggle(a.id, !enabled)} style={{
                  padding: "4px 12px", borderRadius: "var(--r2)", fontSize: 11, fontWeight: 500, cursor: "pointer",
                  background: enabled ? "var(--grn1)" : "transparent",
                  border: `1px solid ${enabled ? "var(--grn2)" : "var(--b1)"}`,
                  color: enabled ? "var(--grn4)" : "var(--t3)",
                }}>{enabled ? "Enabled" : "Paused"}</button>
              ) : (
                <span style={{ fontSize: 10, color: "var(--t3)" }}>Always on</span>
              )}
            </div>
            <div style={{ fontSize: 11, color: "var(--t2)" }}>{a.goal}</div>
            <div style={{ display: "flex", gap: 5, flexWrap: "wrap" }}>
              {a.tools.map((t, i) => <span key={i} className="aug-tag">{t}</span>)}
            </div>
            {!a.reserved && (
              <div style={{ display: "flex", gap: 18, fontSize: 11, color: "var(--t3)", borderTop: "1px solid var(--b1)", paddingTop: 8, flexWrap: "wrap", alignItems: "center" }}>
                <span>Budget <span style={{ color: "var(--t2)" }}>{fmtBudget(a.governance.token_budget)} tokens/run</span></span>
                <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  Model
                  <select className="aug-input" value={a.governance.model ?? ""}
                    onChange={e => setModel(a.id, e.target.value)}
                    style={{ fontSize: 11, padding: "2px 6px", maxWidth: 220 }}>
                    <option value="">Role default</option>
                    {models.map(m => <option key={m} value={m}>{m}</option>)}
                    {a.governance.model && !models.includes(a.governance.model) && <option value={a.governance.model}>{a.governance.model}</option>}
                  </select>
                </span>
                <span>Recent <span style={{ color: "var(--t2)" }}>{a.spend.runs} runs · {fmtCompact(a.spend.total_tokens)} tokens · {a.spend.query_count} queries</span></span>
              </div>
            )}
          </div>
        );
      })}
      </div>
    </div>
  );
}

function FleetScreen({ onNavigate, workspaceId, workspaceName }: { onNavigate: (t: NavTab) => void; workspaceId?: string; workspaceName?: string }) {
  const [view, setView] = useState<"activity" | "agents">("activity");
  const [jobs, setJobs] = useState<FleetJob[]>([]);
  const [tried, setTried] = useState(false);

  useEffect(() => {
    let alive = true;
    const load = () => getJobs({ limit: 100 })
      .then(j => { if (alive) { setJobs(j); setTried(true); } })
      .catch(() => { if (alive) setTried(true); });
    load();
    // Live: refetch whenever a job changes state (reuses the shared kernel stream).
    const unsub = subscribeKernelEvents(() => load(), { kinds: ["job.state"] });
    const iv = setInterval(load, 15_000); // slow fallback if the stream is down
    return () => { alive = false; unsub(); clearInterval(iv); };
  }, []);

  const active = jobs.filter(j => j.state === "RUNNING" || j.state === "PENDING").length;
  const ok = jobs.filter(j => j.state === "SUCCEEDED").length;
  const bad = jobs.filter(j => j.state === "FAILED" || j.state === "CANCELLED").length;

  const cancel = (id: string) => {
    cancelJob(id)
      .catch(err => console.error("[Aughor] job cancel failed:", err))
      // Refetch either way — if the cancel did land server-side, show it.
      .then(() => getJobs({ limit: 100 }).then(setJobs).catch(() => {}));
  };

  return (
    <div className="aug-screen">
      <div className="aug-content-header">
        <NavIcon name="node" size={14} color="var(--t3)" />
        <span style={{ fontSize: 13, fontWeight: 500 }}>Fleet</span>
        <span style={{ fontSize: 11, color: "var(--t3)", marginLeft: 10 }}>
          the agents working your data — what they’re doing and what it cost
        </span>
        <div style={{ display: "flex", gap: 4, marginLeft: "auto" }}>
          {(["activity", "agents"] as const).map(v => (
            <button key={v} onClick={() => setView(v)} style={{
              padding: "3px 12px", borderRadius: "var(--r2)", fontSize: 11, fontWeight: 500, cursor: "pointer",
              background: view === v ? "var(--bg-sel)" : "transparent",
              border: `1px solid ${view === v ? "var(--blue2)" : "var(--b1)"}`,
              color: view === v ? "var(--blue5)" : "var(--t3)",
            }}>{v === "activity" ? "Activity" : "Agents"}</button>
          ))}
        </div>
      </div>
      <div style={{ flex: 1, overflowY: "auto", padding: "18px 20px" }}>
        {view === "agents" ? <AgentsPanel workspaceId={workspaceId} workspaceName={workspaceName} /> : (<>
        <MiniStatRow>
          <MiniStat value={active} label="Running" tone="var(--blue4)" />
          <MiniStat value={ok} label="Succeeded" tone="var(--grn4)" />
          <MiniStat value={bad} label="Failed / Cancelled" tone={bad ? "var(--red4)" : undefined} />
        </MiniStatRow>
        {!tried ? (
          <div style={{ padding: "40px 0", textAlign: "center" }}>
            <p style={{ fontSize: 12, color: "var(--t3)" }}>Loading the fleet…</p>
          </div>
        ) : jobs.length === 0 ? (
          <div style={{ padding: "40px 0", textAlign: "center" }}>
            <p style={{ fontSize: 12, color: "var(--t3)" }}>No agent runs yet — start an exploration or ask a deep-analysis question, and the fleet shows up here.</p>
          </div>
        ) : (
          <div style={{ background: "var(--bg-2)", border: "1px solid var(--b1)", borderRadius: "var(--r3)", overflow: "hidden" }}>
            <table className="aug-dt">
              <thead>
                <tr>
                  <th>Agent</th>
                  <th>Task</th>
                  <th>Status</th>
                  <th>Cost</th>
                  <th>When</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {jobs.map(j => {
                  const cost = costSummary(j.cost);
                  const isActive = j.state === "RUNNING" || j.state === "PENDING";
                  const when = j.started_at || j.created_at;
                  return (
                    <tr key={j.id}>
                      <td>
                        <div style={{ fontSize: 12, color: "var(--t1)", fontWeight: 500 }}>{j.agent.agent}</div>
                        <div style={{ fontSize: 10, color: "var(--t3)" }}>{j.agent.blurb}</div>
                      </td>
                      <td style={{ maxWidth: 360 }}>
                        <div style={{ fontSize: 12, color: "var(--t2)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{j.title}</div>
                        {j.error && <div style={{ fontSize: 10, color: "var(--red4)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{j.error}</div>}
                      </td>
                      <td><StateTag state={j.state} /></td>
                      <td style={{ fontSize: 11, color: cost ? "var(--t2)" : "var(--t4)" }}>{cost || "—"}</td>
                      <td style={{ fontSize: 11, color: "var(--t3)", whiteSpace: "nowrap" }}>
                        {when ? timeAgo(when) : ""}{j.duration_ms != null ? ` · ${fmtMs(j.duration_ms)}` : ""}
                      </td>
                      <td>
                        {isActive && (
                          <button onClick={() => cancel(j.id)} style={{
                            padding: "2px 9px", borderRadius: "var(--r2)", fontSize: 11, cursor: "pointer",
                            background: "transparent", border: "1px solid var(--b1)", color: "var(--t3)",
                          }}>Cancel</button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        <p style={{ fontSize: 10, color: "var(--t4)", marginTop: 14, lineHeight: 1.5 }}>
          Shows Scout (exploration) and Analyst (deep analysis) runs on the job kernel.
          Scheduled Monitors &amp; Briefings run on a separate scheduler and aren’t listed here yet —{" "}
          <button onClick={() => onNavigate("monitors")} style={{ background: "none", border: "none", padding: 0, color: "var(--blue4)", cursor: "pointer", fontSize: 10 }}>open Monitors</button>.
        </p>
        </>)}
      </div>
    </div>
  );
}

// ── Settings screen ────────────────────────────────────────────────────────────

function SettingsScreen({ theme, setTheme, workspaceId, workspaceName }: { theme: Theme; setTheme: (t: Theme) => void; workspaceId?: string; workspaceName?: string }) {
  const modes: Array<{ id: Theme; icon: string; label: string; desc: string }> = [
    { id: "dark",  icon: "moon", label: "Dark",  desc: "Navy backgrounds, light text" },
    { id: "light", icon: "sun",  label: "Light", desc: "White backgrounds, dark text" },
  ];

  type SettingsTab = "organization" | "access" | "appearance" | "models" | "system";
  const [sub, setSub] = useState<SettingsTab>("organization");
  const SUBS: Array<{ id: SettingsTab; label: string }> = [
    { id: "organization", label: "Organization" },
    { id: "access",       label: "Access" },
    { id: "appearance",   label: "Appearance" },
    { id: "models",       label: "Models" },
    { id: "system",       label: "System" },
  ];

  return (
    <div className="aug-screen">
      <div className="aug-content-header">
        <NavIcon name="settings" size={14} color="var(--t3)" />
        <span style={{ fontSize: 13, fontWeight: 500 }}>Settings</span>
      </div>

      {/* Sub-tab rail — grouped settings instead of one long scroll */}
      <div style={{ display: "flex", alignItems: "center", gap: 2, padding: "8px 20px 0", borderBottom: "1px solid var(--b1)", flexShrink: 0 }}>
        {SUBS.map(s => (
          <button key={s.id} onClick={() => setSub(s.id)} style={{
            padding: "7px 12px", fontSize: 12, fontWeight: 500, cursor: "pointer",
            background: "none", border: "none",
            color: sub === s.id ? "var(--t1)" : "var(--t3)",
            borderBottom: `2px solid ${sub === s.id ? "var(--blue4)" : "transparent"}`,
            marginBottom: -1,
          }}>{s.label}</button>
        ))}
      </div>

      <div style={{ flex: 1, overflowY: "auto", padding: "18px 20px", display: "flex", flexDirection: "column", gap: 20 }}>

        {sub === "organization" && (
          <OrgSettingsPanel workspaceId={workspaceId} workspaceName={workspaceName} />
        )}

        {sub === "appearance" && (
          <div>
            <div className="aug-label" style={{ marginBottom: 12 }}>Theme</div>
            <div style={{ display: "flex", gap: 10 }}>
              {modes.map(m => (
                <button key={m.id} onClick={() => setTheme(m.id)} style={{
                  flex: 1, display: "flex", alignItems: "center", gap: 12,
                  padding: "12px 14px", borderRadius: "var(--r3)", cursor: "pointer",
                  background: theme === m.id ? "var(--bg-sel)" : "var(--bg-2)",
                  border: `1px solid ${theme === m.id ? "var(--blue3)" : "var(--b1)"}`,
                  transition: "all .14s", textAlign: "left",
                }}>
                  <div style={{
                    width: 36, height: 28, borderRadius: "var(--r2)", flexShrink: 0,
                    background: m.id === "dark" ? "#111821" : "#FFFFFF",
                    border: `1px solid ${m.id === "dark" ? "#253552" : "#D2DCEB"}`,
                    display: "flex", alignItems: "center", justifyContent: "center",
                  }}>
                    <NavIcon name={m.icon} size={14} color={m.id === "dark" ? "#4C8EEE" : "#C08A00"} />
                  </div>
                  <div>
                    <div style={{ fontSize: 12, fontWeight: 600, color: theme === m.id ? "var(--blue5)" : "var(--t1)", marginBottom: 2 }}>{m.label}</div>
                    <div style={{ fontSize: 10, color: "var(--t3)" }}>{m.desc}</div>
                  </div>
                  {theme === m.id && (
                    <div style={{ marginLeft: "auto", flexShrink: 0 }}>
                      <NavIcon name="check" size={13} color="var(--blue3)" />
                    </div>
                  )}
                </button>
              ))}
            </div>
          </div>
        )}

        {sub === "models" && <InferencePanel />}

        {sub === "access" && <RolesPanel />}

        {sub === "system" && <SystemPanel />}

      </div>
    </div>
  );
}

// ── Add connection form ────────────────────────────────────────────────────────

// ── Connector type catalogue (static — mirrors backend registry) ──────────────

const CONNECTOR_TYPES = [
  { type: "postgres",     label: "PostgreSQL",    category: "built-in",  icon: "db" },
  { type: "duckdb",       label: "DuckDB",         category: "built-in",  icon: "db" },
  { type: "bigquery",     label: "BigQuery",       category: "warehouse", icon: "db" },
  { type: "snowflake",    label: "Snowflake",      category: "warehouse", icon: "db" },
  { type: "mysql",        label: "MySQL",          category: "warehouse", icon: "db" },
  { type: "local_upload", label: "Local Files",    category: "file",      icon: "catalog" },
  { type: "s3",           label: "S3 / R2",        category: "file",      icon: "catalog" },
  { type: "stripe",       label: "Stripe",         category: "api",       icon: "db" },
  { type: "hubspot",      label: "HubSpot",        category: "api",       icon: "db" },
  { type: "salesforce",   label: "Salesforce",     category: "api",       icon: "db" },
  { type: "federated",    label: "Federated",      category: "federated", icon: "canvas" },
  { type: "confluence",   label: "Confluence",     category: "knowledge", icon: "catalog" },
  { type: "notion",       label: "Notion",         category: "knowledge", icon: "catalog" },
] as const;

type ConnType = typeof CONNECTOR_TYPES[number]["type"];

// Per-type field definitions
const CONN_FIELDS: Record<ConnType, Array<{ key: string; label: string; placeholder: string; secret?: boolean; optional?: boolean }>> = {
  postgres: [
    { key: "dsn",         label: "Connection string",   placeholder: "postgresql://user:pass@host:5432/db", secret: true },
    { key: "schema_name", label: "Schema",               placeholder: "public", optional: true },
  ],
  duckdb: [
    { key: "dsn",         label: "File path",            placeholder: "/path/to/file.duckdb" },
    { key: "schema_name", label: "Schema",               placeholder: "main", optional: true },
  ],
  bigquery: [
    { key: "project_id",  label: "Project ID",           placeholder: "my-gcp-project" },
    { key: "dataset",     label: "Dataset",              placeholder: "analytics", optional: true },
    { key: "credentials", label: "Service account JSON path (blank = ADC)", placeholder: "/path/to/sa.json", secret: true, optional: true },
  ],
  snowflake: [
    { key: "account",     label: "Account identifier",   placeholder: "xy12345.us-east-1" },
    { key: "user",        label: "Username",             placeholder: "analyst" },
    { key: "password",    label: "Password",             placeholder: "", secret: true },
    { key: "database",    label: "Database",             placeholder: "PROD" },
    { key: "schema_name", label: "Schema",               placeholder: "PUBLIC", optional: true },
    { key: "warehouse",   label: "Warehouse",            placeholder: "COMPUTE_WH", optional: true },
  ],
  mysql: [
    { key: "dsn",         label: "Connection string",    placeholder: "mysql://user:pass@host:3306/mydb", secret: true },
  ],
  local_upload: [],
  federated:    [],  // member connections selected in a separate picker
  stripe: [
    { key: "secret_key",  label: "Secret key",      placeholder: "sk_live_…",    secret: true },
    { key: "objects",     label: "Objects to sync", placeholder: "charges,customers,subscriptions", optional: true },
  ],
  hubspot: [
    { key: "access_token",label: "Access token",    placeholder: "pat-na1-…",    secret: true },
    { key: "objects",     label: "Objects to sync", placeholder: "contacts,companies,deals,tickets", optional: true },
  ],
  salesforce: [
    { key: "username",       label: "Username",        placeholder: "user@org.com", secret: false as boolean },
    { key: "password",       label: "Password",        placeholder: "",             secret: true },
    { key: "security_token", label: "Security token",  placeholder: "token123…",    secret: true },
    { key: "domain",         label: "Domain",          placeholder: "login",        optional: true as boolean },
    { key: "objects",        label: "Objects to sync", placeholder: "Account,Contact,Opportunity", optional: true as boolean },
  ],
  s3: [
    { key: "bucket",  label: "Bucket",            placeholder: "my-data-bucket" },
    { key: "prefix",  label: "Key prefix",        placeholder: "data/sales/", optional: true },
    { key: "region",  label: "Region",            placeholder: "us-east-1" },
    { key: "key_id",  label: "Access Key ID",     placeholder: "AKIA…", secret: true },
    { key: "secret",  label: "Secret Access Key", placeholder: "", secret: true },
  ],
  confluence: [
    { key: "base_url",   label: "Base URL",    placeholder: "https://yourorg.atlassian.net" },
    { key: "username",   label: "Username",    placeholder: "user@example.com" },
    { key: "api_token",  label: "API token",   placeholder: "ATATT3…", secret: true },
    { key: "space_keys", label: "Space keys",  placeholder: "ENG,PROD (empty = all spaces)", optional: true },
  ],
  notion: [
    { key: "integration_token", label: "Integration token", placeholder: "secret_…", secret: true },
    { key: "database_ids",      label: "Database IDs",      placeholder: "id1,id2 (optional)", optional: true },
  ],
};

function AddConnectionForm({
  onSave,
  onCancel,
}: {
  onSave: (name: string, type: string, dsn: string, schema?: string, meta?: Record<string, string>) => Promise<void>;
  onCancel: () => void;
}) {
  const [name, setName] = useState("");
  const [type, setType] = useState<ConnType>("postgres");
  const [fields, setFields] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  // Reset field values when type changes
  const handleTypeChange = (newType: ConnType) => {
    setType(newType);
    setFields({});
  };

  const setField = (key: string, val: string) =>
    setFields(prev => ({ ...prev, [key]: val }));

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const dsn = fields["dsn"] || "";
      const schemaName = fields["schema_name"] || undefined;
      // All remaining fields (not dsn/schema_name) go into meta
      const meta: Record<string, string> = {};
      for (const [k, v] of Object.entries(fields)) {
        if (k !== "dsn" && k !== "schema_name" && v) meta[k] = v;
      }
      await onSave(name, type, dsn, schemaName, meta);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to add connection");
    } finally {
      setLoading(false);
    }
  };

  const typeInfo = CONNECTOR_TYPES.find(t => t.type === type);
  const fieldDefs = CONN_FIELDS[type] ?? [];
  const grouped = [
    { label: "Built-in",   items: CONNECTOR_TYPES.filter(t => t.category === "built-in") },
    { label: "Warehouse",  items: CONNECTOR_TYPES.filter(t => t.category === "warehouse") },
    { label: "File",       items: CONNECTOR_TYPES.filter(t => t.category === "file") },
    { label: "API / CRM",  items: CONNECTOR_TYPES.filter(t => t.category === "api") },
    { label: "Federation", items: CONNECTOR_TYPES.filter(t => t.category === "federated") },
    { label: "Knowledge",  items: CONNECTOR_TYPES.filter(t => t.category === "knowledge") },
  ];

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.65)", backdropFilter: "blur(3px)", zIndex: 200, display: "flex", alignItems: "center", justifyContent: "center", padding: 16 }}>
      <div style={{ width: "100%", maxWidth: 460, background: "var(--bg-3)", border: "1px solid var(--b2)", borderRadius: "var(--r3)", padding: 24, display: "flex", flexDirection: "column", gap: 16, maxHeight: "90vh", overflowY: "auto" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <span style={{ fontSize: 16, fontWeight: 600, color: "var(--t1)" }}>Add Connection</span>
          <button onClick={onCancel} style={{ background: "none", border: "none", cursor: "pointer", color: "var(--t3)" }}>
            <NavIcon name="close" size={14} />
          </button>
        </div>
        <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {/* Name */}
          <div>
            <div className="aug-label" style={{ marginBottom: 5 }}>Name</div>
            <input
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder="My Data Source"
              required
              className="aug-input"
            />
          </div>

          {/* Type selector */}
          <div>
            <div className="aug-label" style={{ marginBottom: 7 }}>Connector type</div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 5 }}>
              {grouped.map(group => (
                group.items.map(ct => (
                  <button
                    key={ct.type}
                    type="button"
                    onClick={() => handleTypeChange(ct.type)}
                    style={{
                      textAlign: "left", padding: "7px 10px",
                      borderRadius: "var(--r2)", cursor: "pointer",
                      background: type === ct.type ? "var(--bg-sel)" : "var(--bg-2)",
                      border: `1px solid ${type === ct.type ? "var(--blue2)" : "var(--b1)"}`,
                      fontSize: 11, color: type === ct.type ? "var(--blue5)" : "var(--t2)",
                      transition: "all .1s",
                    }}
                  >
                    <div style={{ fontWeight: 500 }}>{ct.label}</div>
                    <div style={{ fontSize: 9, color: "var(--t4)", textTransform: "uppercase", letterSpacing: ".04em", marginTop: 2 }}>{ct.category}</div>
                  </button>
                ))
              ))}
            </div>
          </div>

          {/* Dynamic fields */}
          {(type === "local_upload" || type === "federated") ? (
            <div style={{ padding: "12px", background: "var(--bg-2)", border: "1px solid var(--b1)", borderRadius: "var(--r2)", fontSize: 12, color: "var(--t3)", lineHeight: 1.5 }}>
              {type === "local_upload"
                ? <>Local Files: create the connection, then upload CSV/Parquet/Excel files to it via the Files tab.</>
                : <>Federated connections span multiple sources. Use <code style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--t2)" }}>POST /connections/federate</code> with a list of connection IDs.</>
              }
            </div>
          ) : (
            <>
              {(type === "confluence" || type === "notion") && (
                <div style={{ padding: "8px 10px", background: "var(--bg-2)", border: "1px solid var(--blue2)", borderRadius: "var(--r2)", fontSize: 11, color: "var(--blue4)", lineHeight: 1.5 }}>
                  {type === "confluence" ? "Pages are indexed into the AI context. After saving, trigger sync via the Catalog screen." : "Pages/databases are indexed into the AI context. After saving, trigger sync via the Catalog screen."}
                </div>
              )}
              {fieldDefs.map(f => (
                <div key={f.key}>
                  <div className="aug-label" style={{ marginBottom: 5 }}>
                    {f.label}
                    {f.optional && <span style={{ color: "var(--t4)", fontWeight: 400, marginLeft: 4 }}>(optional)</span>}
                  </div>
                  <input
                    value={fields[f.key] ?? ""}
                    onChange={e => setField(f.key, e.target.value)}
                    placeholder={f.placeholder}
                    type={f.secret ? "password" : "text"}
                    required={!f.optional}
                    className="aug-input"
                    style={{ fontFamily: "var(--font-mono)", fontSize: 11 }}
                  />
                </div>
              ))}
            </>
          )}

          {error && <div style={{ fontSize: 11, color: "var(--red4)", padding: "6px 10px", background: "var(--red1)", border: "1px solid var(--red2)", borderRadius: "var(--r2)" }}>{error}</div>}
          <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 4 }}>
            <button type="button" onClick={onCancel} className="aug-btn aug-btn-ghost">Cancel</button>
            <button type="submit" disabled={loading || !name.trim()} className="aug-btn aug-btn-primary">
              {loading ? "Connecting…" : "Save Connection"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ── Delete confirm modal ───────────────────────────────────────────────────────

function DeleteConnModal({
  conn,
  onConfirm,
  onCancel,
}: {
  conn: Connection;
  onConfirm: () => Promise<void>;
  onCancel: () => void;
}) {
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(false);

  const handleConfirm = async () => {
    setLoading(true);
    await onConfirm();
    setLoading(false);
  };

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.7)", backdropFilter: "blur(4px)", zIndex: 200, display: "flex", alignItems: "center", justifyContent: "center", padding: 16 }}
      onClick={e => { if (e.target === e.currentTarget) onCancel(); }}>
      <div style={{ width: "100%", maxWidth: 360, background: "var(--bg-3)", border: "1px solid var(--b2)", borderRadius: "var(--r3)", padding: 24, display: "flex", flexDirection: "column", gap: 16 }}>
        <div style={{ display: "flex", alignItems: "flex-start", gap: 12 }}>
          <div style={{ width: 36, height: 36, borderRadius: "var(--r2)", background: "var(--red1)", border: "1px solid var(--red2)", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
            <NavIcon name="trash" size={14} color="var(--red4)" />
          </div>
          <div>
            <div style={{ fontSize: 16, fontWeight: 600, color: "var(--t1)" }}>Remove connection</div>
            <div style={{ fontSize: 11, color: "var(--t3)", marginTop: 3, lineHeight: 1.5 }}>
              This removes <span style={{ color: "var(--t2)" }}>{conn.name}</span> from Aughor. The database is not affected.
            </div>
          </div>
        </div>
        <div style={{ fontSize: 10, color: "var(--t3)" }}>
          Type <span style={{ fontFamily: "var(--font-mono)", color: "var(--t2)" }}>{conn.name}</span> to confirm
        </div>
        <input
          autoFocus
          value={text}
          onChange={e => setText(e.target.value)}
          onKeyDown={e => { if (e.key === "Enter" && text === conn.name) handleConfirm(); }}
          placeholder={conn.name}
          className="aug-input"
          style={{ fontFamily: "var(--font-mono)", fontSize: 11 }}
        />
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button onClick={onCancel} className="aug-btn aug-btn-ghost">Cancel</button>
          <button
            onClick={handleConfirm}
            disabled={text !== conn.name || loading}
            style={{
              display: "inline-flex", alignItems: "center", gap: 6,
              padding: "5px 12px", borderRadius: "var(--r2)", fontSize: 12, fontWeight: 500,
              background: "var(--red1)", border: "1px solid var(--red2)", color: "var(--red4)",
              cursor: text === conn.name && !loading ? "pointer" : "not-allowed",
              opacity: text !== conn.name || loading ? 0.4 : 1, transition: "all .12s",
            }}
          >
            {loading ? "Removing…" : "Remove"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Main ───────────────────────────────────────────────────────────────────────

const LAST_CONN_KEY = "aughor_last_conn";
const LAST_WS_KEY = "aughor_last_workspace";
const THEME_KEY = "aughor_theme";

export default function Home() {
  // v2 nav IA: land on the Briefing (the intelligence digest), not the Home overview.
  const [tab, setTab] = useState<NavTab>("intelligence");
  const [theme, setThemeState] = useState<Theme>("dark");
  const [rawSelectedConn, setSelectedConn] = useState("");
  const [builderImport, setBuilderImport] = useState<{ connId: string; sql: string; nonce: number } | undefined>(undefined);
  const [activeCanvas, setActiveCanvas] = useState<Canvas | null>(null);
  const [initialCanvasInvId, setInitialCanvasInvId] = useState<string | null>(null);
  const [initialCanvasChatId, setInitialCanvasChatId] = useState<string | null>(null);
  const [showCanvasCreator, setShowCanvasCreator] = useState(false);
  const [selectedHistoryInvId, setSelectedHistoryInvId] = useState<string | null>(null);
  const [selectedChatSessionId, setSelectedChatSessionId] = useState<string | null>(null);
  const [chatKey, setChatKey] = useState(0);
  const [chatInitialQuestion, setChatInitialQuestion] = useState<string | undefined>(undefined);
  const [chatInitialMode, setChatInitialMode] = useState<"ask" | "investigate">("investigate");
  // Drill into a known finding: routes the first chat turn to the Tier-0 Finding Dossier.
  const [chatInitialInsightId, setChatInitialInsightId] = useState<string | undefined>(undefined);
  const [intelLayer, setIntelLayer] = useState<IntelLayer>("briefing");
  const [opsLayer, setOpsLayer] = useState<OpsLayer>("monitors");
  const [agentLayer, setAgentLayer] = useState<AgentLayer>("overview");
  const [dataLayer, setDataLayer] = useState<DataLayer>("catalog");
  const [secLens, setSecLens] = useState<"security" | "activity" | "approvals">("security");
  const [showHistory, setShowHistory] = useState(false);
  const [showSearch, setShowSearch] = useState(false);
  const [showAddConn, setShowAddConn] = useState(false);
  const [pendingDeleteConn, setPendingDeleteConn] = useState<Connection | null>(null);
  const [connections, setConnections] = useState<Connection[]>([]);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [selectedWorkspace, setSelectedWorkspace] = useState("");

  // ── Workspace-scoped connections (the tenancy boundary) ───────────────────
  // Everything below the topbar sees only the connections belonging to the
  // active workspace (Databricks-style). The Default workspace tracks every
  // connection, so for users who never create a custom workspace this is a no-op.
  const activeWs = workspaces.find(w => w.id === selectedWorkspace) ?? null;
  const wsConnections = activeWs
    ? connections.filter(c => activeWs.connection_ids.includes(c.id))
    : connections;
  // The ACTIVE connection, clamped to the workspace and *derived* (not stored) so
  // it can never lag the tenancy boundary. It reads "" until the workspace resolves,
  // or when the restored connection isn't a member — so an empty/foreign workspace
  // shows no data instead of briefly flashing the localStorage-restored default
  // connection's tables/queries/insights on first load (a fail-closed read).
  const selectedConn =
    activeWs && wsConnections.some(c => c.id === rawSelectedConn) ? rawSelectedConn : "";

  // Theme effect — apply data-theme to <html>
  useEffect(() => {
    const saved = typeof window !== "undefined" ? localStorage.getItem(THEME_KEY) as Theme | null : null;
    const initial: Theme = saved || "dark";
    setThemeState(initial);
    document.documentElement.setAttribute("data-theme", initial);
  }, []);

  const setTheme = (t: Theme) => {
    setThemeState(t);
    document.documentElement.setAttribute("data-theme", t);
    if (typeof window !== "undefined") localStorage.setItem(THEME_KEY, t);
  };

  useEffect(() => {
    getConnections()
      .then(conns => {
        setConnections(conns);
        const saved = typeof window !== "undefined" ? localStorage.getItem(LAST_CONN_KEY) : null;
        const valid = saved && conns.find(c => c.id === saved);
        setSelectedConn(valid ? saved : (conns[0]?.id ?? ""));
      })
      .catch(err => console.error("[Aughor] failed to load connections:", err));
  }, []);

  useEffect(() => {
    if (selectedConn && typeof window !== "undefined") {
      localStorage.setItem(LAST_CONN_KEY, selectedConn);
    }
  }, [selectedConn]);

  // Load workspaces (top-level scope). The backend always guarantees a "Default"
  // workspace containing every connection, so this never comes back empty.
  useEffect(() => {
    getWorkspaces()
      .then(ws => {
        setWorkspaces(ws);
        const saved = typeof window !== "undefined" ? localStorage.getItem(LAST_WS_KEY) : null;
        const valid = saved && ws.find(w => w.id === saved);
        setSelectedWorkspace(valid ? saved : (ws[0]?.id ?? ""));
      })
      .catch(err => console.error("[Aughor] failed to load workspaces:", err));
  }, []);

  useEffect(() => {
    if (selectedWorkspace && typeof window !== "undefined") {
      localStorage.setItem(LAST_WS_KEY, selectedWorkspace);
    }
  }, [selectedWorkspace]);

  // Populate the org-settings cache that the display formatters read (currency symbol,
  // date format) with the active workspace's effective settings; refresh on switch.
  useEffect(() => {
    getEffectiveSettings(selectedWorkspace || undefined).then(setOrgSettingsCache).catch(() => {});
  }, [selectedWorkspace]);

  const reloadWorkspaces = () => getWorkspaces().then(setWorkspaces).catch(() => {});

  // ⌘K global shortcut
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") { e.preventDefault(); setShowSearch(v => !v); }
      if (e.key === "Escape") setShowSearch(false);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  const reloadConnections = () => getConnections().then(setConnections).catch(() => {});

  // First-run funnel: select the best available demo connection and open the Catalog to browse it.
  const tryDemo = () => {
    const demo = connections.find(c => c.name === "BeautyCommerce")
      || connections.find(c => c.id === "workspace")
      || connections.find(c => c.builtin)
      || connections[0];
    if (demo) setSelectedConn(demo.id);
    handleNavigate("catalog");
  };

  const goToChat = (q?: string, mode?: "ask" | "investigate", insightId?: string) => {
    setSelectedChatSessionId(null);
    setSelectedHistoryInvId(null);
    setChatInitialQuestion(q);
    setChatInitialInsightId(insightId);
    if (mode) setChatInitialMode(mode);
    setChatKey(k => k + 1);
    setTab("chat");
  };

  /** Open an existing investigation (or chat session) by ID — goes straight to the report.
   *  Always clears chatInitialQuestion so no stale question fires if the user
   *  subsequently presses "New" while viewing history. */
  const openInvestigation = async (id: string, kind: "investigation" | "chat" = "investigation", connectionId?: string, canvasId?: string | null) => {
    setChatInitialQuestion(undefined);
    setChatInitialMode("investigate");
    setInitialCanvasInvId(null);
    setInitialCanvasChatId(null);

    // Try to resolve a canvas for this investigation
    let targetCanvas: Canvas | null = null;
    try {
      const allCanvases = await getCanvases();
      if (canvasId) {
        targetCanvas = allCanvases.find(c => c.id === canvasId) ?? null;
      }
      if (!targetCanvas && connectionId) {
        targetCanvas = allCanvases.find(c => c.scopes[0]?.connection_id === connectionId) ?? null;
      }
    } catch {
      // ignore canvas fetch errors
    }

    if (targetCanvas) {
      setActiveCanvas(targetCanvas);
      setTab("canvas-workspace");
      if (kind === "investigation") setInitialCanvasInvId(id);
      else setInitialCanvasChatId(id);
      return;
    }

    // Fallback: open the old chat module
    if (kind === "chat") {
      setSelectedHistoryInvId(null);
      setSelectedChatSessionId(id);
      setChatKey(k => k + 1);
    } else {
      setSelectedChatSessionId(null);
      setSelectedHistoryInvId(id);
    }
    setTab("chat");
  };

  // The four former Intelligence tabs are now layers of one unified workspace.
  // Translate any legacy navigation (StatCards, command palette, search) into
  // the `intelligence` tab opened at the matching layer.
  const LEGACY_INTEL_LAYER: Partial<Record<NavTab, IntelLayer>> = {
    briefing:    "briefing",
    ontology:    "ontology",
    "intel-hub": "hub",
    intel:       "hub",   // the former Domains layer folded into the Hub (Data Profile)
    "org-intel":  "org",
  };

  // The three Operations rail items are now layers of one Operations workspace (REC-U5).
  const LEGACY_OPS_LAYER: Partial<Record<NavTab, OpsLayer>> = {
    monitors: "monitors",
    actions:  "actions",
    security: "security",
  };

  // The three Data rail items are now layers of one Data workspace (REC-U5).
  const LEGACY_DATA_LAYER: Partial<Record<NavTab, DataLayer>> = {
    catalog:  "catalog",
    builder:  "builder",
    semantic: "semantic",
  };

  // Agents + Fleet are layers of one Agent workspace: the "Agents" rail item opens
  // the native Overview, "Fleet" opens the built-in fleet layer.
  const LEGACY_AGENT_LAYER: Partial<Record<NavTab, AgentLayer>> = {
    agents: "overview",
    fleet:  "fleet",
  };

  const handleNavigate = (t: NavTab) => {
    // Always dismiss any floating overlays when the user navigates.
    // The History backdrop is fixed inset-0 and will intercept sidebar clicks
    // if left open while switching tabs — this is the most common cause of
    // "can't open other tabs while a query is running".
    setShowHistory(false);

    // The "Briefing" rail item opens the unified Intelligence workspace at its
    // default Briefing lens.
    if (t === "intelligence") {
      setIntelLayer("briefing");
      setTab("intelligence");
      return;
    }

    // "Audit Log" was merged into the Security & Audit workspace (directive #6).
    // Legacy navigations to `activity` now open the Operations workspace at its Security
    // layer on the Activity lens.
    if (t === "activity") {
      setSecLens("activity");
      setOpsLayer("security");
      setTab("operations");
      return;
    }

    // Legacy Intelligence tabs are now layers of that workspace.
    const layer = LEGACY_INTEL_LAYER[t];
    if (layer) {
      setIntelLayer(layer);
      setTab("intelligence");
      return;
    }

    // The Monitors / Action Hub / Security rail items open the Operations workspace layer.
    const ops = LEGACY_OPS_LAYER[t];
    if (ops) {
      setOpsLayer(ops);
      setTab("operations");
      return;
    }

    // The Catalog / Query Builder / Semantic rail items open the Data workspace layer.
    const data = LEGACY_DATA_LAYER[t];
    if (data) {
      setDataLayer(data);
      setTab("data");
      return;
    }
    // Agents / Fleet rail items open the Agent workspace at the matching layer.
    const agentL = LEGACY_AGENT_LAYER[t];
    if (agentL) {
      setAgentLayer(agentL);
      setTab("agents");
      return;
    }
    setTab(t);
  };

  const handleCanvasSelect = (canvas: Canvas) => {
    setActiveCanvas(canvas);
    setInitialCanvasInvId(null);
    setInitialCanvasChatId(null);
    const primaryConn = canvas.scopes[0]?.connection_id;
    if (primaryConn) setSelectedConn(primaryConn);
    setSelectedHistoryInvId(null);
    setSelectedChatSessionId(null);
    setChatKey(k => k + 1);
    setChatInitialQuestion(undefined);
    setTab("canvas-workspace");
  };

  // Open in Query Builder — a query handed off from Insights / Deep Analysis.
  // Defaults the connection to the currently selected one (what the insight ran against).
  const handleOpenInBuilder = (sql: string, connId?: string) => {
    const c = connId || selectedConn;
    if (c && c !== selectedConn) setSelectedConn(c);
    setBuilderImport({ connId: c, sql, nonce: Date.now() });
    setDataLayer("builder");
    setTab("data");
  };

  const handleAddConn = async (name: string, type: string, dsn: string, schema?: string, meta?: Record<string, string>) => {
    await apiAddConnection(name, type, dsn, schema, meta);
    setShowAddConn(false);
    reloadConnections();
  };

  const handleDeleteConn = async () => {
    if (!pendingDeleteConn) return;
    await apiDeleteConnection(pendingDeleteConn.id);
    if (selectedConn === pendingDeleteConn.id) {
      const remaining = connections.filter(c => c.id !== pendingDeleteConn.id);
      setSelectedConn(remaining[0]?.id ?? "");
    }
    setPendingDeleteConn(null);
    reloadConnections();
  };

  // (Workspace-scoped connections + the clamped active connection are derived
  // near the top of the component, just after the useState block.)

  // Switching workspace must not leak the previous one's views — drop the active
  // canvas and any open chat/history session so only workspace-scoped data shows.
  const handleWorkspaceChange = (id: string) => {
    if (id === selectedWorkspace) return;
    setSelectedWorkspace(id);
    setActiveCanvas(null);
    setSelectedChatSessionId(null);
    setSelectedHistoryInvId(null);
  };

  // Keep the selected connection inside the active workspace. When the user
  // switches workspaces and the current connection isn't a member, jump to the
  // workspace's first connection — or clear it when the workspace is empty, so an
  // empty workspace shows no data instead of leaking the previously-selected one.
  useEffect(() => {
    if (!activeWs || connections.length === 0) return;
    if (wsConnections.length === 0) {
      if (selectedConn) setSelectedConn("");
      return;
    }
    if (!wsConnections.find(c => c.id === selectedConn)) {
      setSelectedConn(wsConnections[0].id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedWorkspace, connections]);

  return (
    <OpenInBuilderProvider value={handleOpenInBuilder}>
    <div className="aug-app">

      {/* Topbar */}
      <Topbar
        onSearchOpen={() => setShowSearch(true)}
        onNavigate={handleNavigate}
        connections={wsConnections}
        selectedConn={selectedConn}
        workspaces={workspaces}
        selectedWorkspace={selectedWorkspace}
        onWorkspaceChange={handleWorkspaceChange}
        onCreateWorkspace={async (name) => {
          const ws = await apiCreateWorkspace(name, []);
          await reloadWorkspaces();
          setSelectedWorkspace(ws.id);
        }}
      />

      {/* Body */}
      <div className="aug-body">

        {/* Sidebar */}
        <Sidebar tab={(tab === "operations" ? opsLayer : tab === "data" ? dataLayer : tab === "agents" ? (agentLayer === "fleet" ? "fleet" : "agents") : tab) as NavTab} onNavigate={handleNavigate} selectedConn={selectedConn} />

        {/* Content */}
        <SchemaProvider connId={selectedConn}>
          <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", minWidth: 0 }}>

            {/* ── ASK (hero screen) ── */}
            {tab === "home" && (
              <HomeScreen
                connections={wsConnections}
                selectedConn={selectedConn}
                workspaceId={selectedWorkspace}
                onGoToChat={goToChat}
                onNavigate={handleNavigate}
                onOpenInvestigation={openInvestigation}
                onAddConnection={() => setShowAddConn(true)}
                onTryDemo={tryDemo}
              />
            )}

            {/* ── CANVASES ── */}
            {tab === "canvases" && (
              <CanvasBrowser
                connections={wsConnections}
                workspaceId={selectedWorkspace}
                onSelect={handleCanvasSelect}
                onNew={() => setShowCanvasCreator(true)}
              />
            )}

            {/* ── CANVAS WORKSPACE ── */}
            {tab === "canvas-workspace" && activeCanvas && (
              <ErrorBoundary label="The Canvas workspace hit an error.">
                <CanvasWorkspace
                  canvas={activeCanvas}
                  connections={wsConnections}
                  onClose={() => { setActiveCanvas(null); setTab("canvases"); setInitialCanvasInvId(null); setInitialCanvasChatId(null); }}
                  onCanvasUpdate={updated => setActiveCanvas(updated)}
                  initialOpenInvId={initialCanvasInvId}
                  initialRestoreSessionId={initialCanvasChatId}
                />
              </ErrorBoundary>
            )}

            {/* ── CHAT (Investigate) ── always mounted so SSE streams survive tab switches */}
            <div style={{ flex: 1, flexDirection: "column", overflow: "hidden", background: "var(--bg-0)", display: tab === "chat" ? "flex" : "none" }}>
                {/* Chat header */}
                <div className="aug-content-header">
                  <NavIcon name="chat" size={14} color="var(--t3)" />
                  <span style={{ fontSize: 13, fontWeight: 500 }}>Investigate</span>
                  {activeCanvas ? (
                    <>
                      <span style={{
                        display: "inline-flex", alignItems: "center", gap: 5,
                        padding: "2px 8px", borderRadius: "var(--r2)", marginLeft: 4,
                        background: "color-mix(in srgb, var(--blue4) 12%, transparent)",
                        border: "1px solid color-mix(in srgb, var(--blue4) 30%, transparent)",
                        fontSize: 11, color: "var(--blue4)", fontWeight: 500,
                      }}>
                        <NavIcon name="canvas" size={11} color="var(--blue4)" />
                        {activeCanvas.name}
                      </span>
                      {activeCanvas.scopes[0]?.tables.length > 0 && (
                        <span className="aug-tag aug-tag-gray" style={{ fontSize: 10 }}>
                          {activeCanvas.scopes[0].tables.length} tables
                        </span>
                      )}
                      <button
                        onClick={() => setActiveCanvas(null)}
                        title="Clear canvas"
                        style={{
                          background: "none", border: "none", cursor: "pointer",
                          color: "var(--t4)", padding: "2px 4px",
                          display: "flex", alignItems: "center",
                        }}
                      >
                        <NavIcon name="close" size={11} />
                      </button>
                    </>
                  ) : selectedConn ? (
                    <span className="aug-tag aug-tag-gray" style={{ marginLeft: 4 }}>
                      {connections.find(c => c.id === selectedConn)?.name ?? selectedConn}
                    </span>
                  ) : null}
                  <div style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
                    {!activeCanvas && (
                      <button
                        onClick={() => setTab("canvases")}
                        className="aug-btn aug-btn-ghost aug-btn-sm"
                        title="Pick a Data Canvas"
                      >
                        <NavIcon name="canvas" size={11} /> Canvas
                      </button>
                    )}
                    <button onClick={() => { setSelectedChatSessionId(null); setSelectedHistoryInvId(null); setChatInitialQuestion(undefined); setChatInitialInsightId(undefined); setChatInitialMode("investigate"); setChatKey(k => k + 1); }} className="aug-btn aug-btn-ghost aug-btn-sm">
                      <NavIcon name="plus" size={11} /> New
                    </button>
                    <button onClick={() => setShowHistory(v => !v)} className={`aug-btn aug-btn-sm ${showHistory ? "aug-btn-primary" : "aug-btn-ghost"}`}>
                      <NavIcon name="clock" size={11} /> History
                    </button>
                  </div>
                </div>

                {selectedHistoryInvId
                  ? <HistoryDetailPanel
                      invId={selectedHistoryInvId}
                      onContinue={(q, m) => {
                        setSelectedHistoryInvId(null);
                        setSelectedChatSessionId(null);
                        setChatInitialQuestion(q);
                        setChatInitialInsightId(undefined);
                        setChatInitialMode(m);
                        setChatKey(k => k + 1);
                      }}
                    />
                  : <ChatPanel
                      key={chatKey}
                      connectionId={selectedConn}
                      canvasId={activeCanvas?.id}
                      restoreSessionId={selectedChatSessionId}
                      initialQuestion={chatInitialQuestion}
                      initialMode={chatInitialMode}
                      initialInsightId={chatInitialInsightId}
                    />
                }
            </div>

            {/* ── RECENTS ── */}
            {tab === "recents" && (
              <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", background: "var(--bg-0)" }}>
                <RecentsScreen onGoToChat={goToChat} onOpenInvestigation={openInvestigation} workspaceId={selectedWorkspace} />
              </div>
            )}

            {/* Fleet renders as the operations layer of the Agent workspace below. */}

            {/* ── INTELLIGENCE (unified, multi-layered) ── */}
            {tab === "intelligence" && (
              <ErrorBoundary label="The Intelligence workspace hit an error.">
                <IntelligenceWorkspace
                  connectionId={selectedConn}
                  onInvestigate={goToChat}
                  layer={intelLayer}
                  onLayerChange={setIntelLayer}
                  connections={wsConnections.filter(c => c.briefings_enabled !== false).map(c => ({ id: c.id, name: c.name }))}
                  onConnectionChange={setSelectedConn}
                  workspaceId={selectedWorkspace}
                />
              </ErrorBoundary>
            )}

            {/* Briefing now lives inside the unified Intelligence workspace as its
                default lens (see tab === "intelligence" above). */}

            {/* ── SECURITY & AUDIT (merged Security + Audit Log — directive #6) ── */}
            {/* ── OPERATIONS (Monitors / Action Hub / Security & Audit) ── */}
            {tab === "operations" && (
              <ErrorBoundary label="The Operations workspace hit an error.">
                <OperationsWorkspace
                  connId={selectedConn ?? undefined}
                  workspaceId={selectedWorkspace}
                  layer={opsLayer}
                  onLayerChange={setOpsLayer}
                  secLens={secLens}
                  onSecLensChange={setSecLens}
                />
              </ErrorBoundary>
            )}

            {/* ── PLAYBOOK ── */}
            {tab === "playbook" && (
              <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", background: "var(--bg-0)" }}>
                <div className="aug-content-header">
                  <NavIcon name="playbook" size={14} color="var(--t3)" />
                  <span style={{ fontSize: 13, fontWeight: 500 }}>Playbook</span>
                </div>
                <div style={{ flex: 1, overflowY: "auto", padding: "0 0 16px" }}>
                  <PlaybookPanel />
                </div>
              </div>
            )}

            {/* ── RECOMMENDATION INBOX ── */}
            {tab === "inbox" && (
              <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", background: "var(--bg-0)" }}>
                <div className="aug-content-header">
                  <NavIcon name="spark" size={14} color="var(--t3)" />
                  <span style={{ fontSize: 13, fontWeight: 500 }}>Recommendation Inbox</span>
                </div>
                <div style={{ flex: 1, overflowY: "auto", padding: "0 20px 16px" }}>
                  <RecommendationInbox onOpenInvestigation={invId => { setSelectedHistoryInvId(invId); setTab("chat"); }} workspaceId={selectedWorkspace} />
                </div>
              </div>
            )}

            {/* ── HEALTH SCORECARD ── */}
            {tab === "health" && (
              <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", background: "var(--bg-0)" }}>
                <div className="aug-content-header">
                  <NavIcon name="activity" size={14} color="var(--t3)" />
                  <span style={{ fontSize: 13, fontWeight: 500 }}>Health Scorecard</span>
                  <span style={{ fontSize: 11, color: "var(--t3)", marginLeft: 4 }}>
                    {connections.find(c => c.id === selectedConn)?.name ?? selectedConn}
                  </span>
                </div>
                <div style={{ flex: 1, overflowY: "auto", padding: "20px 28px" }}>
                  <ProcessHealthPanel connectionId={selectedConn} onInvestigate={goToChat} />
                </div>
              </div>
            )}

            {/* ── DATA (Catalog / Query Builder / Semantic Layer) ── */}
            {/* Monitors + Action Hub render as layers of the Operations workspace above. */}
            {tab === "data" && (
              <ErrorBoundary label="The Data workspace hit an error.">
              <WorkspaceShell
                layers={DATA_LAYERS}
                layer={dataLayer}
                onLayerChange={setDataLayer}
                ariaLabel="Data views"
                renderIcon={(name, size, color) => <NavIcon name={name} size={size} color={color} />}
                renderLayer={id => {
                  if (id === "builder") return (
                    <QueryBuilder initialConnId={selectedConn} onOpenCanvas={handleCanvasSelect} importRequest={builderImport} connections={wsConnections} />
                  );
                  if (id === "semantic") return (
                    <SemanticLayerPanel
                      connectionId={selectedConn ?? ""}
                      connName={wsConnections.find(c => c.id === selectedConn)?.name}
                      connections={wsConnections.map(c => ({ id: c.id, name: c.name }))}
                    />
                  );
                  return ( // "catalog"
                    <CatalogScreen
                      connections={wsConnections}
                      workspaceId={selectedWorkspace}
                      selectedConn={selectedConn}
                      onSelect={setSelectedConn}
                      onDeleteConn={conn => setPendingDeleteConn(conn)}
                      onChatWithTable={(table, connId) => {
                        if (connId !== selectedConn) setSelectedConn(connId);
                        goToChat(`Tell me about the ${table} table`);
                      }}
                    />
                  );
                }}
              />
              </ErrorBoundary>
            )}

            {/* ── METRICS ── */}
            {tab === "metrics" && (
              <div style={{ flex: 1, overflow: "hidden", display: "flex", flexDirection: "column", background: "var(--bg-0)" }}>
                <MetricsPanel connId={selectedConn ?? undefined} />
              </div>
            )}

            {/* ── AGENTS — Overview + Manage + Fleet layers ── */}
            {tab === "agents" && (
              <ErrorBoundary label="The Agents workspace hit an error.">
                <AgentWorkspace
                  layer={agentLayer}
                  onLayerChange={setAgentLayer}
                  fleetSlot={
                    <FleetScreen
                      onNavigate={handleNavigate}
                      workspaceId={activeWs && !activeWs.is_default ? activeWs.id : undefined}
                      workspaceName={activeWs && !activeWs.is_default ? activeWs.name : undefined}
                    />
                  }
                />
              </ErrorBoundary>
            )}

            {/* ── SETTINGS ── */}
            {tab === "settings" && (
              <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", background: "var(--bg-0)" }}>
                <SettingsScreen theme={theme} setTheme={setTheme} workspaceId={selectedWorkspace} workspaceName={activeWs?.name} />
              </div>
            )}

          </div>
        </SchemaProvider>
      </div>

      {/* ── History popup ── */}
      {showHistory && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setShowHistory(false)} />
          <div style={{
            position: "fixed", top: 104, right: 16, zIndex: 50,
            height: "72vh", width: "min(420px, 90vw)",
            background: "var(--bg-2)", border: "1px solid var(--b2)",
            borderRadius: "var(--r3)", display: "flex", flexDirection: "column",
            overflow: "hidden", boxShadow: "var(--shadow-md)",
          }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0 16px", borderBottom: "1px solid var(--b1)", height: 44, flexShrink: 0 }}>
              <span style={{ fontSize: 13, fontWeight: 500, color: "var(--t1)" }}>History</span>
              <button onClick={() => setShowHistory(false)} style={{ background: "none", border: "none", cursor: "pointer", color: "var(--t3)" }}>
                <NavIcon name="close" size={13} />
              </button>
            </div>
            <HistoryPanel
              selectedId={selectedHistoryInvId ?? selectedChatSessionId}
              onSelect={(id, kind) => {
                setShowHistory(false);
                if (kind === "chat") { setSelectedHistoryInvId(null); setSelectedChatSessionId(id); }
                else { setSelectedChatSessionId(null); setSelectedHistoryInvId(id); }
                setTab("chat");
              }}
            />
          </div>
        </>
      )}

      {/* ── Command palette (⌘K) ── */}
      <CommandPalette
        open={showSearch}
        onClose={() => setShowSearch(false)}
        selectedConn={selectedConn}
        onNavigate={t => { handleNavigate(t as NavTab); setShowSearch(false); }}
        onGoToChat={q => { goToChat(q); setShowSearch(false); }}
      />

      {/* ── Upgrade / upsell modal — fired by any HTTP-402 capability_locked response ── */}
      <UpgradeModal />

      {/* ── Approval modal — fired by any HTTP-428 approval_required response (P4) ── */}
      <ApprovalModal />

      {/* ── Add connection modal ── */}
      {showAddConn && (
        <AddConnectionForm
          onSave={handleAddConn}
          onCancel={() => setShowAddConn(false)}
        />
      )}

      {/* ── Delete confirm modal ── */}
      {pendingDeleteConn && (
        <DeleteConnModal
          conn={pendingDeleteConn}
          onConfirm={handleDeleteConn}
          onCancel={() => setPendingDeleteConn(null)}
        />
      )}

      {/* ── Canvas creator modal ── */}
      {showCanvasCreator && (
        <CanvasCreator
          connections={wsConnections}
          onCreated={canvas => {
            setShowCanvasCreator(false);
            handleCanvasSelect(canvas);
          }}
          onCancel={() => setShowCanvasCreator(false)}
        />
      )}

    </div>
    </OpenInBuilderProvider>
  );
}
