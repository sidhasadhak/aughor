"use client";

import { useEffect, useRef, useState } from "react";

import { ConfigurePanel } from "@/components/ConfigurePanel";
import { ExplorationBadge } from "@/components/ExplorationBadge";
import { HistoryPanel } from "@/components/HistoryPanel";
import { HistoryDetailPanel } from "@/components/HistoryDetailPanel";
import { ChatPanel } from "@/components/ChatPanel";
import { OntologyPanel } from "@/components/OntologyPanel";
import { ExplorationPanel } from "@/components/ExplorationPanel";
import { SystemPanel } from "@/components/SystemPanel";
import { ActivityLog } from "@/components/ActivityLog";
import { SchemaProvider } from "@/lib/schema-context";
import { ProcessHealthPanel } from "@/components/ProcessHealthPanel";
import { PlaybookPanel } from "@/components/PlaybookPanel";
import { RecommendationInbox } from "@/components/RecommendationInbox";
import { DocumentUploader } from "@/components/DocumentUploader";
import { CatalogScreen } from "@/components/CatalogScreen";
import {
  getConnections,
  addConnection as apiAddConnection,
  deleteConnection as apiDeleteConnection,
  getExplorationStatus,
  getOntology,
  getConnectionFreshness,
  getDomainInsights,
  type Connection,
  type ExplorationStatus,
  type OntologyGraph,
} from "@/lib/api";

// ── Types ──────────────────────────────────────────────────────────────────────

type NavTab =
  | "home"
  | "chat"
  | "recents"
  | "ontology"
  | "intel"
  | "inbox"
  | "activity"
  | "playbook"
  | "connections"
  | "settings";

type Theme = "dark" | "light";

// ── Icon primitives ────────────────────────────────────────────────────────────

const ICON_PATHS: Record<string, string> = {
  home:     "M3 12L12 3l9 9M5 10v9a1 1 0 001 1h4v-5h4v5h4a1 1 0 001-1v-9",
  chat:     "M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z",
  clock:    "M12 22c5.52 0 10-4.48 10-10S17.52 2 12 2 2 6.48 2 12s4.48 10 10 10zm.5-14v5.25l4.5 2.67-.75 1.23L11 14.5V8h1.5z",
  db:       "M12 2C7.58 2 4 3.79 4 6v12c0 2.21 3.58 4 8 4s8-1.79 8-4V6c0-2.21-3.58-4-8-4zm0 2c3.87 0 6 1.5 6 2s-2.13 2-6 2-6-1.5-6-2 2.13-2 6-2zm6 12c0 .5-2.13 2-6 2s-6-1.5-6-2v-2.23C7.61 15.51 9.72 16 12 16s4.39-.49 6-1.23V16zm0-5c0 .5-2.13 2-6 2s-6-1.5-6-2V8.77C7.61 10.51 9.72 11 12 11s4.39-.49 6-1.23V11z",
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
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
      <polygon points="12,2 22,7 22,17 12,22 2,17 2,7" fill="var(--blue3)" opacity=".9" />
      <polygon points="12,6 18,9.5 18,15.5 12,19 6,15.5 6,9.5" fill="var(--bg-0)" />
      <circle cx="12" cy="12" r="2.5" fill="var(--blue4)" />
      <line x1="12" y1="9.5" x2="12" y2="6.5" stroke="var(--blue4)" strokeWidth="1.5" />
      <line x1="14.2" y1="13.5" x2="17" y2="15" stroke="var(--blue4)" strokeWidth="1.5" />
      <line x1="9.8" y1="13.5" x2="7" y2="15" stroke="var(--blue4)" strokeWidth="1.5" />
    </svg>
  );
}

// ── Helpers ────────────────────────────────────────────────────────────────────

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

// ── Topbar ─────────────────────────────────────────────────────────────────────

function Topbar({
  onSearchOpen,
  connections,
  selectedConn,
}: {
  onSearchOpen: () => void;
  connections: Connection[];
  selectedConn: string;
}) {
  const [freshness, setFreshness] = useState<string | null>(null);
  const conn = connections.find(c => c.id === selectedConn);

  useEffect(() => {
    if (!selectedConn) return;
    setFreshness(null);
    getConnectionFreshness(selectedConn)
      .then(r => setFreshness(freshnessLabel(r.freshness)))
      .catch(() => {});
  }, [selectedConn]);

  return (
    <div className="aug-topbar">
      {/* Logo — same width as sidebar */}
      <div style={{ display: "flex", alignItems: "center", gap: 9, width: 224, flexShrink: 0 }}>
        <AughorLogo />
        <div>
          <div style={{ fontSize: 13, fontWeight: 600, color: "var(--t1)", letterSpacing: ".01em" }}>
            Aughor
          </div>
          <div style={{ fontSize: 9, color: "var(--t3)", letterSpacing: ".08em", textTransform: "uppercase", marginTop: -1 }}>
            Intelligence Platform
          </div>
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

      {/* Right: connection pill + avatar */}
      <div style={{ width: 224, display: "flex", alignItems: "center", justifyContent: "flex-end", gap: 8, flexShrink: 0 }}>
        {conn && (
          <div style={{ display: "flex", alignItems: "center", gap: 6, padding: "4px 10px", background: "var(--bg-2)", border: "1px solid var(--b1)", borderRadius: "var(--r2)" }}>
            <span className="aug-dot aug-dot-grn aug-anim-blink" />
            <span style={{ fontSize: 11, fontFamily: "var(--font-mono)", color: "var(--t2)" }}>{conn.name}</span>
            <span style={{ fontSize: 9, color: "var(--t3)", textTransform: "uppercase", letterSpacing: ".06em" }}>
              {conn.conn_type === "duckdb" ? "DuckDB" : "PG"}
            </span>
            {freshness && (
              <span style={{ fontSize: 9, color: "var(--t4)" }}>{freshness}</span>
            )}
          </div>
        )}
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

const NAV_GROUPS = [
  { id: "home",        icon: "home",     label: "Overview",     group: null },
  { id: "chat",        icon: "chat",     label: "Investigate",  group: "Workspace" },
  { id: "recents",     icon: "clock",    label: "Recents",      group: null },
  { id: "ontology",    icon: "node",     label: "Ontology",     group: null },
  { id: "intel",       icon: "process",  label: "Domain Intel", group: null },
  { id: "inbox",       icon: "spark",    label: "Rec. Inbox",   group: null },
  { id: "activity",    icon: "activity", label: "Activity Log", group: null },
  { id: "playbook",    icon: "playbook", label: "Playbook",     group: "System" },
  { id: "connections", icon: "db",       label: "Catalog",      group: null },
  { id: "settings",    icon: "settings", label: "Settings",     group: null },
] as const;

function Sidebar({
  tab,
  onNavigate,
  selectedConn,
}: {
  tab: NavTab;
  onNavigate: (t: NavTab) => void;
  selectedConn: string;
}) {
  let lastGroup: string | null = null;

  return (
    <nav className="aug-sidebar">
      <div style={{ flex: 1, overflowY: "auto", padding: "6px 8px 6px" }}>
        {NAV_GROUPS.map(item => {
          const showGroup = item.group && item.group !== lastGroup;
          if (item.group) lastGroup = item.group;
          return (
            <div key={item.id}>
              {showGroup && <div className="aug-nav-group">{item.group}</div>}
              <button
                className={`aug-nav-item${tab === item.id ? " active" : ""}`}
                onClick={() => onNavigate(item.id as NavTab)}
              >
                <NavIcon
                  name={item.icon}
                  size={14}
                  color={tab === item.id ? "var(--blue4)" : "currentColor"}
                />
                <span>{item.label}</span>
                {item.id === "connections" && selectedConn && (
                  <ExplorationBadge connectionId={selectedConn} />
                )}
              </button>
            </div>
          );
        })}
      </div>
      <div style={{ padding: "10px 8px", borderTop: "1px solid var(--b0)" }}>
        <div style={{ fontSize: 10, color: "var(--t4)", textAlign: "center", letterSpacing: ".04em" }}>
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
    { label: "Browse Schema",     icon: "catalog",  action: () => { onNavigate("connections"); onClose(); } },
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

type RecentInv = { id: string; question: string; started_at: string; status: string; headline: string | null };

function HomeScreen({
  connections,
  selectedConn,
  onGoToChat,
  onNavigate,
}: {
  connections: Connection[];
  selectedConn: string;
  onGoToChat: (q?: string) => void;
  onNavigate: (t: NavTab) => void;
}) {
  const [recentInvs, setRecentInvs] = useState<RecentInv[]>([]);
  const [exploration, setExploration] = useState<ExplorationStatus | null>(null);
  const [ontology, setOntology] = useState<OntologyGraph | null>(null);
  const [domainInsightCount, setDomainInsightCount] = useState<number | null>(null);
  const conn = connections.find(c => c.id === selectedConn);

  useEffect(() => {
    fetch("http://localhost:8000/investigations")
      .then(r => r.json())
      .then(d => setRecentInvs(Array.isArray(d) ? d.slice(0, 8) : []))
      .catch(() => {});
    getExplorationStatus(selectedConn).then(setExploration).catch(() => {});
    getOntology(selectedConn).then(setOntology).catch(() => {});
    getDomainInsights(selectedConn)
      .then(d => setDomainInsightCount(Object.values(d).reduce((sum, v) => sum + (v as { insights: unknown[] }).insights.length, 0)))
      .catch(() => {});
  }, [selectedConn]);

  const tables   = exploration?.tables_total    ?? "—";
  const insights = domainInsightCount ?? "—";
  const entities = ontology ? Object.keys(ontology.entities).length : "—";
  const queries  = exploration?.queries_executed ?? "—";

  const starters = [
    "Why did revenue drop 8% last month?",
    "Which customers have the highest payment failure rate?",
    "What is our MRR this month?",
    "Show top 10 products by revenue",
    "Is APAC churn a trend or one-time event?",
  ];

  return (
    <div className="aug-screen">
      <div className="aug-content-header">
        <NavIcon name="home" size={14} color="var(--t3)" />
        <span style={{ fontSize: 13, fontWeight: 500 }}>Overview</span>
        <div style={{ marginLeft: "auto" }}>
          <span className="aug-tag aug-tag-gray">May 2026</span>
        </div>
      </div>

      <div style={{ flex: 1, overflowY: "auto", padding: "24px 28px", display: "flex", flexDirection: "column", gap: 24 }}>

        {/* Welcome */}
        <div>
          <h1 style={{ fontSize: 20, fontWeight: 600, color: "var(--t1)", letterSpacing: "-.02em", marginBottom: 4 }}>
            Intelligence Overview
          </h1>
          <p style={{ fontSize: 12, color: "var(--t3)", lineHeight: 1.6 }}>
            Aughor has explored your warehouse and built a live business ontology. All findings are evidence-backed.
          </p>
        </div>

        {/* Stats */}
        <div style={{ display: "flex", gap: 10 }}>
          <StatCard value={tables}   label="Tables in schema"    accent="var(--blue3)"  sub={exploration ? `↑ ${exploration.tables_total} total` : undefined} onClick={() => onNavigate("connections")} />
          <StatCard value={entities} label="Entities mapped"     accent="var(--vio3)"   sub="ontology layer"     onClick={() => onNavigate("ontology")} />
          <StatCard value={insights} label="Insights discovered" accent="var(--grn3)"   sub="domain intel"       onClick={() => onNavigate("intel")} />
          <StatCard value={queries}  label="Queries executed"    accent="var(--amb3)"   sub="last 7 days"        onClick={() => onNavigate("activity")} />
        </div>

        {/* Quick actions */}
        <div>
          <div className="aug-label" style={{ marginBottom: 12 }}>Get Started</div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 10 }}>
            {[
              { icon: "chat",    name: "Investigate", desc: "Ask a question and get an evidence-backed root-cause analysis.", accent: "var(--vio3)", action: () => onGoToChat() },
              { icon: "catalog", name: "Schema",      desc: "Browse tables, columns, row counts, and schema intelligence.",   accent: "var(--cyn3)", action: () => onNavigate("connections") },
              { icon: "node",    name: "Ontology",    desc: "Explore the auto-built entity graph and lifecycle states.",      accent: "var(--grn3)", action: () => onNavigate("ontology") },
              { icon: "process", name: "Domain Intel",desc: "Per-domain insights with query budgets and coverage angles.",    accent: "var(--amb3)", action: () => onNavigate("intel") },
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

        {/* Health scorecard */}
        <ProcessHealthPanel connectionId={selectedConn} onInvestigate={onGoToChat} />

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
                    <tr key={inv.id} style={{ cursor: "pointer" }} onClick={() => onGoToChat(inv.question)}>
                      <td style={{ maxWidth: 400 }}>
                        <div style={{ fontSize: 12, color: "var(--t1)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontFamily: "var(--font-ui)" }}>{inv.question}</div>
                        {inv.headline && <div style={{ fontSize: 10, color: "var(--t3)", marginTop: 2 }}>{inv.headline}</div>}
                      </td>
                      <td style={{ color: "var(--t3)", fontSize: 11 }}>{timeAgo(inv.started_at)}</td>
                      <td>
                        {inv.status === "completed" && <span className="aug-tag aug-tag-green">Completed</span>}
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

        {/* Try asking */}
        <div>
          <div className="aug-label" style={{ marginBottom: 12 }}>Try asking</div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
            {starters.map(qs => (
              <button key={qs} onClick={() => onGoToChat(qs)} style={{
                textAlign: "left", display: "flex", alignItems: "center", gap: 10,
                padding: "10px 14px", borderRadius: "var(--r2)",
                background: "var(--bg-2)", border: "1px solid var(--b1)",
                transition: "all .1s", cursor: "pointer",
              }}
                onMouseEnter={e => { e.currentTarget.style.borderColor = "var(--b2)"; e.currentTarget.style.background = "var(--bg-3)"; }}
                onMouseLeave={e => { e.currentTarget.style.borderColor = "var(--b1)"; e.currentTarget.style.background = "var(--bg-2)"; }}
              >
                <NavIcon name="spark" size={11} color="var(--t4)" />
                <span style={{ fontSize: 12, color: "var(--t3)" }}>{qs}</span>
              </button>
            ))}
          </div>
        </div>

      </div>
    </div>
  );
}

// ── Recents screen ─────────────────────────────────────────────────────────────

function RecentsScreen({ onGoToChat }: { onGoToChat: (q?: string) => void }) {
  const [activities, setActivities] = useState<Array<{ id: string; question: string; started_at: string; status: string; headline: string | null; mode?: string }>>([]);
  const [filter, setFilter] = useState<"all" | "investigation" | "chat">("all");

  useEffect(() => {
    const ctrl = new AbortController();
    const to = setTimeout(() => ctrl.abort(), 8_000);
    fetch("http://localhost:8000/investigations", { signal: ctrl.signal })
      .then(r => r.json())
      .then(d => setActivities(Array.isArray(d) ? d : []))
      .catch(() => {})
      .finally(() => clearTimeout(to));
  }, []);

  const shown = filter === "all" ? activities : activities.filter(a => (filter === "chat" ? a.mode === "chat" : a.mode !== "chat"));

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
        {shown.length === 0 ? (
          <div style={{ padding: "40px 0", textAlign: "center" }}>
            <p style={{ fontSize: 12, color: "var(--t3)" }}>No activity yet — start by asking a question.</p>
          </div>
        ) : (
          <div style={{ background: "var(--bg-2)", border: "1px solid var(--b1)", borderRadius: "var(--r3)", overflow: "hidden" }}>
            <table className="aug-dt">
              <thead>
                <tr>
                  <th>Question / Analysis</th>
                  <th>Type</th>
                  <th>Date</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {shown.map(a => (
                  <tr key={a.id} onClick={() => onGoToChat(a.question)} style={{ cursor: "pointer" }}>
                    <td style={{ maxWidth: 420 }}>
                      <div style={{ fontSize: 12, color: "var(--t1)", fontFamily: "var(--font-ui)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{a.question}</div>
                      {a.headline && <div style={{ fontSize: 10, color: "var(--t3)", marginTop: 2 }}>{a.headline}</div>}
                    </td>
                    <td>
                      <span className={`aug-tag ${a.mode === "chat" ? "aug-tag-blue" : "aug-tag-violet"}`}>
                        {a.mode === "chat" ? "chat" : "investigation"}
                      </span>
                    </td>
                    <td style={{ color: "var(--t3)", fontSize: 11 }}>{timeAgo(a.started_at)}</td>
                    <td>
                      {a.status === "completed" && <span className="aug-tag aug-tag-green">Completed</span>}
                      {a.status === "timed_out" && <span className="aug-tag aug-tag-amber">Timed out</span>}
                      {a.status === "running"   && <span className="aug-tag aug-tag-blue">Running</span>}
                      {a.status === "failed"    && <span className="aug-tag aug-tag-red">Failed</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Connections screen ─────────────────────────────────────────────────────────

function ConnectionsScreen({
  connections,
  selectedConn,
  onSelect,
  onAddConn,
  onDeleteConn,
}: {
  connections: Connection[];
  selectedConn: string;
  onSelect: (id: string) => void;
  onAddConn: () => void;
  onDeleteConn: (conn: Connection) => void;
}) {
  const [hov, setHov] = useState<string | null>(null);
  const sel = connections.find(c => c.id === selectedConn);

  return (
    <div className="aug-screen" style={{ flexDirection: "row" }}>
      {/* Left: connection list */}
      <div style={{ width: 260, borderRight: "1px solid var(--b1)", display: "flex", flexDirection: "column", flexShrink: 0 }}>
        <div className="aug-content-header" style={{ justifyContent: "space-between" }}>
          <span style={{ fontSize: 13, fontWeight: 500 }}>Connections</span>
          <button className="aug-btn aug-btn-primary aug-btn-sm" onClick={onAddConn}>
            <NavIcon name="plus" size={11} /> Add
          </button>
        </div>
        <div style={{ flex: 1, overflowY: "auto", padding: 8 }}>
          {connections.map(c => (
            <div key={c.id} onMouseEnter={() => setHov(c.id)} onMouseLeave={() => setHov(null)} style={{ position: "relative" }}>
              <button onClick={() => onSelect(c.id)} style={{
                display: "flex", alignItems: "flex-start", gap: 10, width: "100%",
                padding: "10px 10px", borderRadius: "var(--r2)",
                background: selectedConn === c.id ? "var(--bg-sel)" : "transparent",
                border: `1px solid ${selectedConn === c.id ? "var(--blue2)" : "transparent"}`,
                cursor: "pointer", transition: "all .1s", textAlign: "left", marginBottom: 2,
              }}
                onMouseEnter={e => { if (selectedConn !== c.id) e.currentTarget.style.background = "var(--bg-hover)"; }}
                onMouseLeave={e => { if (selectedConn !== c.id) e.currentTarget.style.background = "transparent"; }}
              >
                <NavIcon name="db" size={14} color={c.id === selectedConn ? "var(--grn4)" : "var(--t3)"} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 12, fontWeight: 500, color: "var(--t1)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.name}</div>
                  <div style={{ fontSize: 10, color: "var(--t3)", fontFamily: "var(--font-mono)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.dsn_preview}</div>
                  <div style={{ display: "flex", gap: 6, marginTop: 4, alignItems: "center" }}>
                    <span className={`aug-tag ${c.conn_type === "duckdb" ? "aug-tag-green" : "aug-tag-blue"}`}>{c.conn_type}</span>
                  </div>
                </div>
              </button>
              {hov === c.id && (
                <button onClick={e => { e.stopPropagation(); onDeleteConn(c); }} style={{
                  position: "absolute", top: 10, right: 6, padding: 4,
                  background: "none", border: "none", cursor: "pointer",
                  color: "var(--t3)",
                }}
                  onMouseEnter={e => e.currentTarget.style.color = "var(--red4)"}
                  onMouseLeave={e => e.currentTarget.style.color = "var(--t3)"}
                >
                  <NavIcon name="trash" size={11} />
                </button>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Right: connection detail */}
      {sel && (
        <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
          <div className="aug-content-header">
            <span className="aug-dot aug-dot-grn aug-anim-blink" />
            <span style={{ fontSize: 13, fontWeight: 500, fontFamily: "var(--font-mono)" }}>{sel.name}</span>
            <span className={`aug-tag ${sel.conn_type === "duckdb" ? "aug-tag-green" : "aug-tag-blue"}`}>{sel.conn_type}</span>
          </div>
          <div style={{ flex: 1, overflowY: "auto", padding: "16px 20px", display: "flex", flexDirection: "column", gap: 14 }}>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
              {[["DSN", sel.dsn_preview, true], ["Schema", sel.schema_name || "default", true], ["Type", sel.conn_type, false], ["Status", "active", false]].map(([k, v, mono]) => (
                <div key={String(k)} style={{ padding: "10px 12px", background: "var(--bg-2)", border: "1px solid var(--b1)", borderRadius: "var(--r2)" }}>
                  <div className="aug-label" style={{ marginBottom: 4 }}>{k}</div>
                  <div style={{ fontSize: 12, color: "var(--t1)", fontFamily: mono ? "var(--font-mono)" : "var(--font-ui)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{v}</div>
                </div>
              ))}
            </div>
            <ExplorationBadge connectionId={sel.id} />
          </div>
        </div>
      )}
    </div>
  );
}

// ── Settings screen ────────────────────────────────────────────────────────────

function SettingsScreen({ theme, setTheme }: { theme: Theme; setTheme: (t: Theme) => void }) {
  const modes: Array<{ id: Theme; icon: string; label: string; desc: string }> = [
    { id: "dark",  icon: "moon", label: "Dark",  desc: "Navy backgrounds, light text" },
    { id: "light", icon: "sun",  label: "Light", desc: "White backgrounds, dark text" },
  ];

  return (
    <div className="aug-screen">
      <div className="aug-content-header">
        <NavIcon name="settings" size={14} color="var(--t3)" />
        <span style={{ fontSize: 13, fontWeight: 500 }}>Settings</span>
      </div>
      <div style={{ flex: 1, overflowY: "auto", padding: "18px 20px", display: "flex", flexDirection: "column", gap: 20 }}>

        {/* Appearance */}
        <div>
          <div className="aug-label" style={{ marginBottom: 12 }}>Appearance</div>
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

        {/* System settings */}
        <div>
          <div className="aug-label" style={{ marginBottom: 12 }}>System</div>
          <SystemPanel />
        </div>

      </div>
    </div>
  );
}

// ── Add connection form ────────────────────────────────────────────────────────

function AddConnectionForm({
  onSave,
  onCancel,
}: {
  onSave: (name: string, type: string, dsn: string, schema?: string) => Promise<void>;
  onCancel: () => void;
}) {
  const [name, setName] = useState("");
  const [type, setType] = useState("postgres");
  const [dsn, setDsn] = useState("");
  const [schema, setSchema] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await onSave(name, type, dsn, schema || undefined);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to add connection");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.65)", backdropFilter: "blur(3px)", zIndex: 200, display: "flex", alignItems: "center", justifyContent: "center", padding: 16 }}>
      <div style={{ width: "100%", maxWidth: 400, background: "var(--bg-3)", border: "1px solid var(--b2)", borderRadius: "var(--r3)", padding: 24, display: "flex", flexDirection: "column", gap: 16 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: "var(--t1)" }}>Add Connection</span>
          <button onClick={onCancel} style={{ background: "none", border: "none", cursor: "pointer", color: "var(--t3)" }}>
            <NavIcon name="close" size={14} />
          </button>
        </div>
        <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {[
            { label: "Name", value: name, set: setName, placeholder: "My Database", type: "text", mono: false },
            { label: "Connection string", value: dsn, set: setDsn, placeholder: type === "postgres" ? "postgresql://…" : "/path/to/file.duckdb", type: "text", mono: true },
            { label: "Schema (optional)", value: schema, set: setSchema, placeholder: type === "postgres" ? "public" : "main", type: "text", mono: true },
          ].map(f => (
            <div key={f.label}>
              <div className="aug-label" style={{ marginBottom: 5 }}>{f.label}</div>
              <input
                value={f.value}
                onChange={e => f.set(e.target.value)}
                placeholder={f.placeholder}
                required={f.label === "Name" || f.label === "Connection string"}
                className="aug-input"
                style={f.mono ? { fontFamily: "var(--font-mono)", fontSize: 11 } : {}}
              />
            </div>
          ))}
          <div>
            <div className="aug-label" style={{ marginBottom: 5 }}>Type</div>
            <select value={type} onChange={e => setType(e.target.value)} className="aug-input">
              <option value="postgres">PostgreSQL</option>
              <option value="duckdb">DuckDB</option>
            </select>
          </div>
          {error && <div style={{ fontSize: 11, color: "var(--red4)" }}>{error}</div>}
          <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 4 }}>
            <button type="button" onClick={onCancel} className="aug-btn aug-btn-ghost">Cancel</button>
            <button type="submit" disabled={loading} className="aug-btn aug-btn-primary">{loading ? "Saving…" : "Save Connection"}</button>
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
            <div style={{ fontSize: 13, fontWeight: 600, color: "var(--t1)" }}>Remove connection</div>
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
const THEME_KEY = "aughor_theme";

export default function Home() {
  const [tab, setTab] = useState<NavTab>("home");
  const [theme, setThemeState] = useState<Theme>("dark");
  const [selectedConn, setSelectedConn] = useState("");
  const [selectedHistoryInvId, setSelectedHistoryInvId] = useState<string | null>(null);
  const [selectedChatSessionId, setSelectedChatSessionId] = useState<string | null>(null);
  const [chatKey, setChatKey] = useState(0);
  const [chatInitialQuestion, setChatInitialQuestion] = useState<string | undefined>(undefined);
  const [chatInitialMode, setChatInitialMode] = useState<"ask" | "investigate">("investigate");
  const [explorationSection, setExplorationSection] = useState<"nulls" | "joins" | "lifecycles" | "distributions" | "insights" | "intelligence" | undefined>(undefined);
  const [showHistory, setShowHistory] = useState(false);
  const [showSearch, setShowSearch] = useState(false);
  const [showAddConn, setShowAddConn] = useState(false);
  const [pendingDeleteConn, setPendingDeleteConn] = useState<Connection | null>(null);
  const [connections, setConnections] = useState<Connection[]>([]);

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

  const goToChat = (q?: string) => {
    setSelectedChatSessionId(null);
    setChatInitialQuestion(q);
    setChatKey(k => k + 1);
    setTab("chat");
  };

  const handleNavigate = (t: NavTab) => {
    setTab(t);
    if (t === "intel") setExplorationSection("intelligence");
  };

  const handleAddConn = async (name: string, type: string, dsn: string, schema?: string) => {
    await apiAddConnection(name, type, dsn, schema);
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

  return (
    <div className="aug-app">

      {/* Topbar */}
      <Topbar
        onSearchOpen={() => setShowSearch(true)}
        connections={connections}
        selectedConn={selectedConn}
      />

      {/* Body */}
      <div className="aug-body">

        {/* Sidebar */}
        <Sidebar tab={tab} onNavigate={handleNavigate} selectedConn={selectedConn} />

        {/* Content */}
        <SchemaProvider connId={selectedConn}>
          <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", minWidth: 0 }}>

            {/* ── HOME ── */}
            {tab === "home" && (
              <HomeScreen
                connections={connections}
                selectedConn={selectedConn}
                onGoToChat={goToChat}
                onNavigate={handleNavigate}
              />
            )}

            {/* ── CHAT (Investigate) ── */}
            {tab === "chat" && (
              <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", background: "var(--bg-0)" }}>
                {/* Chat header */}
                <div className="aug-content-header">
                  <NavIcon name="chat" size={14} color="var(--t3)" />
                  <span style={{ fontSize: 13, fontWeight: 500 }}>Investigate</span>
                  {selectedConn && (
                    <span className="aug-tag aug-tag-gray" style={{ marginLeft: 4 }}>{connections.find(c => c.id === selectedConn)?.name ?? selectedConn}</span>
                  )}
                  <div style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
                    <button onClick={() => { setSelectedChatSessionId(null); setSelectedHistoryInvId(null); setChatKey(k => k + 1); }} className="aug-btn aug-btn-ghost aug-btn-sm">
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
                        setChatInitialMode(m);
                        setChatKey(k => k + 1);
                      }}
                    />
                  : <ChatPanel
                      key={chatKey}
                      connectionId={selectedConn}
                      restoreSessionId={selectedChatSessionId}
                      initialQuestion={chatInitialQuestion}
                      initialMode={chatInitialMode}
                    />
                }
              </div>
            )}

            {/* ── RECENTS ── */}
            {tab === "recents" && <RecentsScreen onGoToChat={goToChat} />}

            {/* ── ONTOLOGY ── */}
            {tab === "ontology" && (
              <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", background: "var(--bg-0)" }}>
                <div className="aug-content-header">
                  <NavIcon name="node" size={14} color="var(--t3)" />
                  <span style={{ fontSize: 13, fontWeight: 500 }}>Business Ontology</span>
                </div>
                <OntologyPanel connectionId={selectedConn} onInvestigate={q => goToChat(q)} />
              </div>
            )}

            {/* ── DOMAIN INTEL ── */}
            {tab === "intel" && (
              <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", background: "var(--bg-0)" }}>
                <div className="aug-content-header">
                  <NavIcon name="process" size={14} color="var(--t3)" />
                  <span style={{ fontSize: 13, fontWeight: 500 }}>Domain Intelligence</span>
                </div>
                <ExplorationPanel connectionId={selectedConn} initialSection={explorationSection} />
              </div>
            )}

            {/* ── ACTIVITY LOG ── */}
            {tab === "activity" && (
              <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", background: "var(--bg-0)" }}>
                <div className="aug-content-header">
                  <NavIcon name="activity" size={14} color="var(--t3)" />
                  <span style={{ fontSize: 13, fontWeight: 500 }}>Activity Log</span>
                </div>
                <ActivityLog connectionId={selectedConn} isActive={tab === "activity"} />
              </div>
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
                  <RecommendationInbox onOpenInvestigation={invId => { setSelectedHistoryInvId(invId); setTab("chat"); }} />
                </div>
              </div>
            )}

            {/* ── CATALOG (was Connections) ── */}
            {tab === "connections" && (
              <CatalogScreen
                connections={connections}
                selectedConn={selectedConn}
                onSelect={setSelectedConn}
                onAddConn={() => setShowAddConn(true)}
                onDeleteConn={conn => setPendingDeleteConn(conn)}
                onChatWithTable={(table, connId) => {
                  if (connId !== selectedConn) setSelectedConn(connId);
                  goToChat(`Tell me about the ${table} table`);
                }}
              />
            )}

            {/* ── SETTINGS ── */}
            {tab === "settings" && (
              <SettingsScreen theme={theme} setTheme={setTheme} />
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

      {/* ── Search overlay ── */}
      {showSearch && (
        <SearchOverlay
          onClose={() => setShowSearch(false)}
          onNavigate={handleNavigate}
          onGoToChat={q => { goToChat(q); setShowSearch(false); }}
        />
      )}

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

    </div>
  );
}
