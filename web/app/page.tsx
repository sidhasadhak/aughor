"use client";

import { useEffect, useRef, useState } from "react";
import HomeIcon        from "@atlaskit/icon/core/home";
import CommentIcon     from "@atlaskit/icon/core/comment";
import ChartBarIcon    from "@atlaskit/icon/core/chart-bar";
import SettingsIcon    from "@atlaskit/icon/core/settings";
import ChevronDownIcon from "@atlaskit/icon/core/chevron-down";
import ArchiveBoxIcon  from "@atlaskit/icon/core/archive-box";
import ClockIcon       from "@atlaskit/icon/core/clock";
import SearchIcon      from "@atlaskit/icon/core/search";
import AddIcon         from "@atlaskit/icon/core/add";
import CloseIcon       from "@atlaskit/icon/core/close";
import NodeIcon        from "@atlaskit/icon/core/node";

import { ConfigurePanel } from "@/components/ConfigurePanel";
import { ConnectionsPanel } from "@/components/ConnectionsPanel";
import { ExplorationBadge } from "@/components/ExplorationBadge";
import { HistoryPanel } from "@/components/HistoryPanel";
import { HistoryDetailPanel } from "@/components/HistoryDetailPanel";
import { SchemaPanel } from "@/components/SchemaPanel";
import { CatalogPanel } from "@/components/CatalogPanel";
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
import { getConnections, addConnection as apiAddConnection, deleteConnection as apiDeleteConnection, getExplorationStatus, getOntology, getConnectionFreshness, getDomainInsights, type Connection, type ExplorationStatus, type OntologyGraph } from "@/lib/api";

// ── Types ─────────────────────────────────────────────────────────────────────

type NavTab = "home" | "chat" | "recents" | "catalog" | "data";

// ── Example questions ─────────────────────────────────────────────────────────

const EXAMPLE_QUESTIONS = [
  "Why did revenue drop 8% last week?",
  "What is our MRR this month?",
  "Which customer segment has the highest payment failure rate?",
  "Is the APAC revenue decline a trend or a one-time event?",
  "Show me the top 10 customers by revenue",
];

// ── Helpers ───────────────────────────────────────────────────────────────────

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

// ── Nav sidebar item ──────────────────────────────────────────────────────────

function NavItem({
  icon,
  label,
  active,
  onClick,
}: {
  icon: React.ReactNode;
  label: string;
  active?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`
        relative w-full flex items-center gap-2.5 px-3 py-[7px] text-sm font-medium transition-all rounded-md
        ${active
          ? "bg-zinc-700/70 text-zinc-100"
          : "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-700/30"}
      `}
    >
      {active && (
        <span className="absolute left-0 top-1/2 -translate-y-1/2 w-[2.5px] h-4 bg-violet-500 rounded-r-full" />
      )}
      <span className={`shrink-0 ${active ? "text-violet-400" : "text-zinc-500"}`}>{icon}</span>
      <span className="truncate text-[12px] font-medium">{label}</span>
    </button>
  );
}

// ── Connection selector (topbar) ──────────────────────────────────────────────

function freshnessLabel(ts: string | null): string | null {
  if (!ts) return null;
  // Handle numeric Unix timestamps returned as strings (seconds or ms)
  const num = Number(ts);
  const d = !isNaN(num) ? new Date(num > 1e10 ? num : num * 1000) : new Date(ts);
  if (isNaN(d.getTime())) return null;
  const diffMs = Date.now() - d.getTime();
  const diffH = diffMs / 3_600_000;
  if (diffH < 1) return "data < 1h ago";
  if (diffH < 24) return `data ${Math.round(diffH)}h ago`;
  const diffD = diffMs / 86_400_000;
  if (diffD < 7) return `data ${Math.round(diffD)}d ago`;
  return `data ${d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: diffD > 365 ? "numeric" : undefined })}`;
}

function ConnectionSelector({
  connections,
  selectedId,
  onSelect,
  onManage,
}: {
  connections: Connection[];
  selectedId: string;
  onSelect: (id: string) => void;
  onManage: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [freshness, setFreshness] = useState<string | null>(null);
  const current = connections.find((c) => c.id === selectedId);

  useEffect(() => {
    if (!selectedId) return;
    setFreshness(null);
    getConnectionFreshness(selectedId)
      .then(r => setFreshness(freshnessLabel(r.freshness)))
      .catch(() => {});
  }, [selectedId]);

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 px-3 py-1.5 rounded-lg border border-zinc-600/70 bg-zinc-800 hover:bg-zinc-700/60 transition text-xs text-zinc-300 font-mono"
      >
        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 shrink-0" />
        <span className="max-w-[160px] truncate">{current?.name ?? selectedId}</span>
        {freshness && (
          <span className="text-[10px] text-zinc-500 shrink-0 font-sans">{freshness}</span>
        )}
        <span className="text-zinc-500 shrink-0"><ChevronDownIcon label="" size="small" /></span>
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} />
          <div className="absolute top-full left-1/2 -translate-x-1/2 mt-1.5 w-64 bg-zinc-900 border border-zinc-600 rounded-xl shadow-2xl z-40 overflow-hidden">
            <div className="px-3 pt-3 pb-1.5">
              <p className="text-[10px] text-zinc-500 uppercase tracking-widest font-medium mb-1.5">
                Connections
              </p>
            </div>
            <div className="pb-1.5">
              {connections.map((c) => (
                <button
                  key={c.id}
                  onClick={() => { onSelect(c.id); setOpen(false); }}
                  className={`w-full flex items-center gap-2.5 px-3 py-2.5 text-xs transition hover:bg-zinc-700/60 ${
                    c.id === selectedId ? "text-zinc-100" : "text-zinc-400"
                  }`}
                >
                  <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                    c.id === selectedId ? "bg-emerald-400" : "bg-zinc-600"
                  }`} />
                  <span className="font-mono truncate flex-1">{c.name}</span>
                  {c.id === selectedId && (
                    <span className="ml-auto text-violet-400 text-[10px] font-medium">active</span>
                  )}
                </button>
              ))}
            </div>
            <div className="border-t border-zinc-700 px-3 py-2.5">
              <button
                onClick={() => { onManage(); setOpen(false); }}
                className="text-xs text-zinc-500 hover:text-zinc-300 transition"
              >
                Manage connections →
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

// ── Global search palette ─────────────────────────────────────────────────────

function SearchPalette({
  onClose,
  onGoToChat,
}: {
  onClose: () => void;
  onGoToChat: (q?: string) => void;
}) {
  const [query, setQuery] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const suggestions = [
    { label: "New Chat",  icon: <CommentIcon label="" size="small" />, action: () => { onGoToChat(); onClose(); } },
    ...EXAMPLE_QUESTIONS.map(q => ({
      label: q,
      icon: <SearchIcon label="" size="small" />,
      action: () => { onGoToChat(q); onClose(); },
    })),
  ].filter(s => !query || s.label.toLowerCase().includes(query.toLowerCase()));

  return (
    <>
      <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm" onClick={onClose} />
      <div className="fixed top-[18%] left-1/2 -translate-x-1/2 z-50 w-full max-w-xl bg-zinc-900 border border-zinc-600 rounded-2xl shadow-2xl overflow-hidden">
        {/* Input row */}
        <div className="flex items-center gap-3 px-4 py-3.5 border-b border-zinc-700/80">
          <span className="text-zinc-500 shrink-0"><SearchIcon label="Search" size="small" /></span>
          <input
            ref={inputRef}
            value={query}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={e => { if (e.key === "Escape") onClose(); }}
            placeholder="Search data, analyses, and more…"
            className="flex-1 bg-transparent text-sm text-zinc-100 placeholder:text-zinc-500 focus:outline-none"
          />
          <kbd
            onClick={onClose}
            className="text-[10px] text-zinc-500 border border-zinc-600 rounded px-1.5 py-0.5 cursor-pointer hover:text-zinc-400 transition"
          >
            esc
          </kbd>
        </div>
        {/* Results */}
        <div className="py-2 max-h-80 overflow-y-auto">
          {suggestions.length === 0 ? (
            <p className="px-4 py-3 text-xs text-zinc-500">No results for "{query}"</p>
          ) : (
            suggestions.map((s, i) => (
              <button
                key={i}
                onClick={s.action}
                className="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-zinc-300 hover:bg-zinc-700/60 hover:text-zinc-100 transition text-left"
              >
                <span className="text-zinc-500 shrink-0">{s.icon}</span>
                {s.label}
              </button>
            ))
          )}
        </div>
        <div className="px-4 py-2 border-t border-zinc-700/80 flex items-center gap-3">
          <span className="text-[10px] text-zinc-600">Navigate with ↑↓ · Enter to select · Esc to close</span>
        </div>
      </div>
    </>
  );
}

// ── Recents panel ─────────────────────────────────────────────────────────────

type ActivityType = "investigation" | "chat" | "ontology";

const TYPE_META: Record<ActivityType, { label: string; color: string; bg: string; border: string }> = {
  investigation: { label: "Investigation", color: "#fb923c", bg: "rgba(251,146,60,0.08)", border: "rgba(251,146,60,0.25)" },
  chat:          { label: "Chat",          color: "#7ba8f7", bg: "rgba(123,168,247,0.08)", border: "rgba(123,168,247,0.25)" },
  ontology:      { label: "Ontology",      color: "#4ade80", bg: "rgba(74,222,128,0.08)",  border: "rgba(74,222,128,0.25)" },
};

type Activity = { id: string; question: string; started_at: string; status: string; headline: string | null; type: ActivityType };

function RecentsPanel({ onGoToChat, onGoToData }: { onGoToChat: (q?: string) => void; onGoToData: () => void }) {
  const [activities, setActivities] = useState<Activity[]>([]);
  const [filter, setFilter] = useState<ActivityType | "all">("all");

  useEffect(() => {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 8_000);
    fetch("http://localhost:8000/investigations", { signal: controller.signal })
      .then(r => r.json())
      .then((data: Array<{ id: string; question: string; started_at: string; status: string; headline: string | null; mode?: string }>) => {
        const mapped: Activity[] = (Array.isArray(data) ? data : []).map(inv => ({
          id: inv.id,
          question: inv.question,
          started_at: inv.started_at,
          status: inv.status,
          headline: inv.headline,
          type: (inv.mode === "chat" ? "chat" : "investigation") as ActivityType,
        }));
        setActivities(mapped);
      })
      .catch(() => {})
      .finally(() => clearTimeout(timeout));
  }, []);

  const shown = filter === "all" ? activities : activities.filter(a => a.type === filter);
  const filters: Array<ActivityType | "all"> = ["all", "investigation", "chat", "ontology"];

  return (
    <div className="flex-1 overflow-y-auto min-h-0" style={{ background: "#0d0e11" }}>
      <div style={{ padding: "36px 48px" }}>

        {/* Header */}
        <div style={{ marginBottom: "28px" }}>
          <h1 style={{ fontSize: "22px", fontWeight: 500, color: "#e8e6e1", letterSpacing: "-0.02em", marginBottom: "5px" }}>Recents</h1>
          <p style={{ fontSize: "12.5px", color: "#3e3f47" }}>Your recent investigations, chats, and data explorations.</p>
        </div>

        {/* Filter pills */}
        <div style={{ display: "flex", gap: "6px", marginBottom: "20px" }}>
          {filters.map(f => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              style={{
                fontSize: "11px", padding: "4px 12px", borderRadius: "20px", cursor: "pointer",
                background: filter === f ? "#1e2040" : "transparent",
                border: `0.5px solid ${filter === f ? "#3d6bff55" : "#2a2b30"}`,
                color: filter === f ? "#7ba8f7" : "#5a5b62",
                transition: "all 0.1s", textTransform: "capitalize",
              }}
            >
              {f === "all" ? "All activity" : TYPE_META[f].label}
            </button>
          ))}
        </div>

        {/* Table header */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 120px 140px 100px", gap: "0 16px", padding: "6px 12px", marginBottom: "4px" }}>
          <span style={{ fontSize: "10px", color: "#3e3f47", textTransform: "uppercase", letterSpacing: "0.08em" }}>Name</span>
          <span style={{ fontSize: "10px", color: "#3e3f47", textTransform: "uppercase", letterSpacing: "0.08em" }}>Type</span>
          <span style={{ fontSize: "10px", color: "#3e3f47", textTransform: "uppercase", letterSpacing: "0.08em" }}>Date</span>
          <span style={{ fontSize: "10px", color: "#3e3f47", textTransform: "uppercase", letterSpacing: "0.08em" }}>Status</span>
        </div>

        {/* Rows */}
        {shown.length === 0 ? (
          <div style={{ padding: "40px 0", textAlign: "center" }}>
            <p style={{ fontSize: "12.5px", color: "#3e3f47" }}>No activity yet — start by asking a question in Chat.</p>
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: "2px" }}>
            {shown.map(a => {
              const meta = TYPE_META[a.type];
              return (
                <button
                  key={a.id}
                  onClick={() => a.type === "ontology" ? onGoToData() : onGoToChat(a.question)}
                  className="group text-left w-full"
                  style={{
                    display: "grid", gridTemplateColumns: "1fr 120px 140px 100px", gap: "0 16px",
                    padding: "10px 12px", borderRadius: "7px", alignItems: "center",
                    background: "transparent", border: "none", cursor: "pointer",
                    transition: "background 0.1s",
                  }}
                  onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = "#13141a"; }}
                  onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = "transparent"; }}
                >
                  {/* Name + headline */}
                  <div style={{ minWidth: 0 }}>
                    <p style={{ fontSize: "12.5px", color: "#c0bfbc", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{a.question}</p>
                    {a.headline && (
                      <p style={{ fontSize: "11px", color: "#3e3f47", marginTop: "2px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{a.headline}</p>
                    )}
                  </div>
                  {/* Type badge */}
                  <span style={{
                    fontSize: "10px", padding: "3px 8px", borderRadius: "4px", fontWeight: 500, display: "inline-block",
                    color: meta.color, background: meta.bg, border: `0.5px solid ${meta.border}`,
                    whiteSpace: "nowrap",
                  }}>
                    {meta.label}
                  </span>
                  {/* Date */}
                  <span style={{ fontSize: "11px", color: "#5a5b62" }}>{timeAgo(a.started_at)}</span>
                  {/* Status */}
                  {a.status === "completed" && <span style={{ fontSize: "10px", color: "#4ade80" }}>Completed</span>}
                  {a.status === "running"   && <span style={{ fontSize: "10px", color: "#7ba8f7" }}>Running</span>}
                  {a.status === "failed"    && <span style={{ fontSize: "10px", color: "#f87171" }}>Failed</span>}
                  {a.status === "timed_out" && <span style={{ fontSize: "10px", color: "#fbbf24" }}>Timed out</span>}
                  {!["completed","running","failed","timed_out"].includes(a.status) && (
                    <span style={{ fontSize: "10px", color: "#5a5b62" }}>{a.status}</span>
                  )}
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Home page ──────────────────────────────────────────────────────────────────

type RecentInv = { id: string; question: string; started_at: string; status: string; headline: string | null };
type RecentTab = "recents" | "investigations";

function StatCard({ value, label, accent, onClick }: { value: string | number; label: string; accent: string; onClick?: () => void }) {
  const [hov, setHov] = useState(false);
  return (
    <div
      onClick={onClick}
      onMouseEnter={() => setHov(true)}
      onMouseLeave={() => setHov(false)}
      style={{
        flex: 1, padding: "16px 18px",
        background: hov && onClick ? "#161720" : "#13141a",
        border: `0.5px solid ${hov && onClick ? accent + "40" : "#1e1f24"}`,
        borderRadius: "8px", minWidth: 0,
        cursor: onClick ? "pointer" : "default",
        transition: "all 0.12s",
      }}
    >
      <p style={{ fontSize: "22px", fontWeight: 600, color: "#e8e6e1", letterSpacing: "-0.02em", lineHeight: 1 }}>{value}</p>
      <p style={{ fontSize: "11px", color: "#5a5b62", marginTop: "5px", lineHeight: 1.3 }}>{label}</p>
      <div style={{ width: "18px", height: "2px", background: accent, borderRadius: "2px", marginTop: "10px" }} />
    </div>
  );
}

function QuickActionCard({ icon, name, desc, accent, action }: { icon: React.ReactNode; name: string; desc: string; accent: string; action: () => void }) {
  const [hov, setHov] = useState(false);
  return (
    <button
      onClick={action}
      onMouseEnter={() => setHov(true)}
      onMouseLeave={() => setHov(false)}
      className="text-left"
      style={{
        padding: "16px 18px",
        background: hov ? "#161720" : "#13141a",
        border: `0.5px solid ${hov ? accent + "55" : "#1e1f24"}`,
        borderRadius: "8px",
        transition: "all 0.12s",
        cursor: "pointer",
      }}
    >
      <div style={{
        width: "32px", height: "32px", borderRadius: "7px",
        background: accent + "18", border: `0.5px solid ${accent}40`,
        display: "flex", alignItems: "center", justifyContent: "center",
        marginBottom: "12px", color: accent,
      }}>
        {icon}
      </div>
      <p style={{ fontSize: "13px", fontWeight: 500, color: "#c8c7c3", marginBottom: "4px" }}>{name}</p>
      <p style={{ fontSize: "11.5px", color: "#3e3f47", lineHeight: 1.5 }}>{desc}</p>
    </button>
  );
}

function HomePage({
  connections,
  selectedConn,
  onGoToChat,
  onGoToCatalog,
  onGoToData,
}: {
  connections: Connection[];
  selectedConn: string;
  onGoToChat: (q?: string) => void;
  onGoToCatalog: () => void;
  onGoToData: (subTab?: "ontology" | "schema" | "exploration" | "activity" | "playbook" | "inbox" | "documents", section?: "nulls" | "joins" | "lifecycles" | "distributions" | "insights" | "intelligence") => void;
}) {
  const [recentInvs, setRecentInvs] = useState<RecentInv[]>([]);
  const [exploration, setExploration] = useState<ExplorationStatus | null>(null);
  const [ontology, setOntology] = useState<OntologyGraph | null>(null);
  const [domainInsightCount, setDomainInsightCount] = useState<number | null>(null);
  const [recentTab, setRecentTab] = useState<RecentTab>("recents");
  const conn = connections.find(c => c.id === selectedConn);

  useEffect(() => {
    fetch("http://localhost:8000/investigations")
      .then(r => r.json())
      .then(d => setRecentInvs(Array.isArray(d) ? d.slice(0, 8) : []))
      .catch(() => {});
    getExplorationStatus(selectedConn).then(setExploration).catch(() => {});
    getOntology(selectedConn).then(setOntology).catch(() => {});
    getDomainInsights(selectedConn)
      .then(d => setDomainInsightCount(Object.values(d).reduce((sum, v) => sum + v.insights.length, 0)))
      .catch(() => {});
  }, [selectedConn]);

  const tables   = exploration?.tables_total    ?? "—";
  const insights = domainInsightCount ?? "—";
  const entities = ontology ? Object.keys(ontology.entities).length : "—";
  const queries  = exploration?.queries_executed ?? "—";

  const starters = [
    "What are the top-selling products this month?",
    "Which marketing channels drive the most revenue?",
    "Why did order count drop last month?",
    "What is our average order value?",
    "Which customers have the highest lifetime value?",
  ];

  const shownInvs = recentTab === "recents"
    ? recentInvs.slice(0, 5)
    : recentInvs;

  return (
    <div className="flex-1 overflow-y-auto min-h-0" style={{ background: "#0d0e11" }}>
      <div style={{ padding: "36px 48px", display: "flex", flexDirection: "column", gap: "32px" }}>

        {/* ── Welcome + connection ── */}
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: "16px" }}>
          <div>
            <h1 style={{ fontSize: "24px", fontWeight: 500, color: "#e8e6e1", letterSpacing: "-0.02em", marginBottom: "5px" }}>
              Welcome to Aughor
            </h1>
            <p style={{ fontSize: "12.5px", color: "#3e3f47", lineHeight: 1.6 }}>
              Your autonomous data analyst — ask questions, investigate root causes, explore your data.
            </p>
          </div>
          {/* Active DB pill */}
          <div style={{ display: "flex", alignItems: "center", gap: "8px", padding: "7px 12px", background: "#13141a", border: "0.5px solid #1e1f24", borderRadius: "20px", flexShrink: 0, marginTop: "2px" }}>
            <span style={{ width: "6px", height: "6px", borderRadius: "50%", background: "#4ade80", flexShrink: 0 }} />
            <span style={{ fontSize: "12px", fontWeight: 500, color: "#c8c7c3", fontFamily: "JetBrains Mono, monospace" }}>{conn?.name ?? selectedConn}</span>
            <span style={{ fontSize: "9.5px", color: "#3e3f47", fontFamily: "JetBrains Mono, monospace", letterSpacing: "0.06em" }}>{(conn?.conn_type ?? "db").toUpperCase()}</span>
          </div>
        </div>

        {/* ── Stats row ── */}
        <div style={{ display: "flex", gap: "8px" }}>
          <StatCard value={tables}   label="Tables in schema"    accent="#3d6bff" onClick={() => onGoToData("schema")} />
          <StatCard value={entities} label="Entities mapped"     accent="#a78bfa" onClick={() => onGoToData("ontology")} />
          <StatCard value={insights} label="Insights discovered" accent="#4ade80" onClick={() => onGoToData("exploration", "intelligence")} />
          <StatCard value={queries}  label="Queries executed"    accent="#f97316" onClick={() => onGoToData("activity")} />
        </div>

        {/* ── Quick actions ── */}
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: "6px", marginBottom: "12px" }}>
            <p style={{ fontSize: "14px", fontWeight: 500, color: "#c8c7c3" }}>Get started</p>
            <span style={{ fontSize: "13px", color: "#3e3f47" }}>›</span>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr", gap: "8px" }}>
            <QuickActionCard
              icon={<CommentIcon label="Chat" size="small" />}
              name="Chat"
              desc="Ask questions and investigate root causes."
              accent="#a78bfa"
              action={() => onGoToChat()}
            />
            <QuickActionCard
              icon={<ArchiveBoxIcon label="Catalog" size="small" />}
              name="Catalog"
              desc="Browse tables, columns, and row counts."
              accent="#38bdf8"
              action={onGoToCatalog}
            />
            <QuickActionCard
              icon={
                <svg viewBox="0 0 24 24" fill="currentColor" width="18" height="18">
                  <circle cx="8" cy="12" r="3.2" fill="none" stroke="currentColor" strokeWidth="2"/>
                  <circle cx="18" cy="5" r="3.2" fill="none" stroke="currentColor" strokeWidth="2"/>
                  <circle cx="18" cy="19" r="3.2" fill="none" stroke="currentColor" strokeWidth="2"/>
                  <circle cx="12" cy="12" r="2.4"/>
                  <line x1="10.9" y1="10.9" x2="15.2" y2="6.6" stroke="currentColor" strokeWidth="2"/>
                  <line x1="10.9" y1="13.1" x2="15.2" y2="17.4" stroke="currentColor" strokeWidth="2"/>
                  <line x1="9.6" y1="12" x2="14.8" y2="12" stroke="currentColor" strokeWidth="2"/>
                </svg>
              }
              name="Ontology"
              desc="Explore your business entity graph."
              accent="#4ade80"
              action={onGoToData}
            />
            <QuickActionCard
              icon={<SearchIcon label="Investigate" size="small" />}
              name="Investigate"
              desc="Start a new root-cause investigation."
              accent="#fb923c"
              action={() => onGoToChat("Investigate the most significant trend in the data.")}
            />
          </div>
        </div>

        {/* ── Business Health scorecard ── */}
        <ProcessHealthPanel connectionId={selectedConn} onInvestigate={onGoToChat} />

        {/* ── Recent activity ── */}
        <div>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "12px" }}>
            <p style={{ fontSize: "14px", fontWeight: 500, color: "#c8c7c3" }}>Your activity</p>
            <div style={{ display: "flex", gap: "4px" }}>
              {(["recents", "investigations"] as RecentTab[]).map(t => (
                <button
                  key={t}
                  onClick={() => setRecentTab(t)}
                  style={{
                    fontSize: "11px", padding: "4px 10px", borderRadius: "20px", cursor: "pointer",
                    background: recentTab === t ? "#1e2040" : "transparent",
                    border: `0.5px solid ${recentTab === t ? "#3d6bff55" : "#2a2b30"}`,
                    color: recentTab === t ? "#7ba8f7" : "#5a5b62",
                    transition: "all 0.1s",
                  }}
                >
                  {t === "recents" ? "Recents" : "All investigations"}
                </button>
              ))}
            </div>
          </div>

          {recentInvs.length === 0 ? (
            <div style={{ padding: "28px 0", textAlign: "center" }}>
              <p style={{ fontSize: "12.5px", color: "#3e3f47" }}>No investigations yet — start by asking a question in Chat.</p>
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: "1px" }}>
              {shownInvs.map((inv, i) => (
                <div
                  key={inv.id}
                  style={{
                    display: "flex", alignItems: "center", gap: "12px",
                    padding: "10px 12px", borderRadius: "7px",
                    borderBottom: i < shownInvs.length - 1 ? "0.5px solid #1a1b20" : "none",
                  }}
                >
                  <div style={{ width: "28px", height: "28px", borderRadius: "6px", background: "#1a1b22", border: "0.5px solid #2a2b30", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0, color: "#5a5b62" }}>
                    <ClockIcon label="" size="small" />
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <p style={{ fontSize: "12.5px", color: "#c0bfbc", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{inv.question}</p>
                    {inv.headline && (
                      <p style={{ fontSize: "11px", color: "#3e3f47", marginTop: "2px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{inv.headline}</p>
                    )}
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: "8px", flexShrink: 0 }}>
                    <span style={{ fontSize: "11px", color: "#3e3f47" }}>{timeAgo(inv.started_at)}</span>
                    {inv.status === "timed_out" && <span style={{ fontSize: "9px", color: "#fbbf24", border: "0.5px solid rgba(251,191,36,0.25)", background: "rgba(251,191,36,0.08)", borderRadius: "4px", padding: "2px 7px" }}>timed out</span>}
                    {inv.status === "failed"    && <span style={{ fontSize: "9px", color: "#f87171", border: "0.5px solid rgba(248,113,113,0.25)", background: "rgba(248,113,113,0.08)", borderRadius: "4px", padding: "2px 7px" }}>failed</span>}
                    {inv.status === "running"   && <span style={{ fontSize: "9px", color: "#4ade80", border: "0.5px solid rgba(74,222,128,0.25)", background: "rgba(74,222,128,0.08)", borderRadius: "4px", padding: "2px 7px" }}>running</span>}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* ── Try asking ── */}
        <div>
          <p style={{ fontSize: "14px", fontWeight: 500, color: "#c8c7c3", marginBottom: "12px" }}>Try asking</p>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "6px" }}>
            {starters.map(q => (
              <button
                key={q}
                onClick={() => onGoToChat(q)}
                className="group text-left flex items-center"
                style={{ gap: "10px", padding: "10px 14px", borderRadius: "7px", background: "#13141a", border: "0.5px solid #1e1f24", transition: "border-color 0.1s" }}
                onMouseEnter={e => { (e.currentTarget as HTMLButtonElement).style.borderColor = "#2a2b30"; (e.currentTarget as HTMLButtonElement).style.background = "#161720"; }}
                onMouseLeave={e => { (e.currentTarget as HTMLButtonElement).style.borderColor = "#1e1f24"; (e.currentTarget as HTMLButtonElement).style.background = "#13141a"; }}
              >
                <span style={{ width: "4px", height: "4px", borderRadius: "50%", background: "#2a3050", flexShrink: 0 }} />
                <span style={{ fontSize: "12px", color: "#6e6f78", flex: 1 }} className="group-hover:text-[#c0bfbc]">{q}</span>
                <span style={{ fontSize: "12px", color: "#3d6bff", opacity: 0, transition: "opacity 0.1s" }} className="group-hover:opacity-100">→</span>
              </button>
            ))}
          </div>
        </div>

      </div>
    </div>
  );
}

// ── Main ──────────────────────────────────────────────────────────────────────

const LAST_CONN_KEY = "aughor_last_conn";

export default function Home() {
  const [tab, setTab] = useState<NavTab>("home");
  const [selectedConn, setSelectedConn] = useState("");
  const [selectedHistoryInvId, setSelectedHistoryInvId] = useState<string | null>(null); // modal
  const [selectedChatSessionId, setSelectedChatSessionId] = useState<string | null>(null);
  const [chatKey, setChatKey] = useState(0);
  const [chatInitialQuestion, setChatInitialQuestion] = useState<string | undefined>(undefined);
  const [connRightTab, setConnRightTab] = useState<"ontology" | "schema" | "exploration" | "activity" | "system" | "playbook" | "inbox" | "documents">("ontology");
  const [explorationSection, setExplorationSection] = useState<"nulls" | "joins" | "lifecycles" | "distributions" | "insights" | "intelligence" | undefined>(undefined);
  const [showHistory, setShowHistory] = useState(false);
  const [showConfigure, setShowConfigure] = useState(false);
  const [showSearch, setShowSearch] = useState(false);
  const [connections, setConnections] = useState<Connection[]>([]);
  const [sidebarAddingConn, setSidebarAddingConn] = useState(false);
  const [pendingDeleteConn, setPendingDeleteConn] = useState<Connection | null>(null);
  const [deleteConfirmText, setDeleteConfirmText] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [hoveredConn, setHoveredConn] = useState<string | null>(null);
  const [addFormName, setAddFormName] = useState("");
  const [addFormType, setAddFormType] = useState("postgres");
  const [addFormDsn, setAddFormDsn] = useState("");
  const [addFormSchema, setAddFormSchema] = useState("");
  const [addFormError, setAddFormError] = useState("");
  const [addFormLoading, setAddFormLoading] = useState(false);

  useEffect(() => {
    getConnections()
      .then((conns) => {
        setConnections(conns);
        const saved = typeof window !== "undefined" ? localStorage.getItem(LAST_CONN_KEY) : null;
        const valid = saved && conns.find(c => c.id === saved);
        setSelectedConn(valid ? saved : (conns[0]?.id ?? ""));
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (selectedConn && typeof window !== "undefined") {
      localStorage.setItem(LAST_CONN_KEY, selectedConn);
    }
  }, [selectedConn]);

  // Global ⌘K / Ctrl+K shortcut
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setShowSearch(v => !v);
      }
      if (e.key === "Escape") setShowSearch(false);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  const reloadConnections = () => {
    getConnections().then(setConnections).catch(() => {});
  };

  const handleSidebarAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    setAddFormError("");
    setAddFormLoading(true);
    try {
      await apiAddConnection(addFormName, addFormType, addFormDsn, addFormSchema || undefined);
      setAddFormName(""); setAddFormDsn(""); setAddFormSchema(""); setSidebarAddingConn(false);
      reloadConnections();
    } catch (err: unknown) {
      setAddFormError(err instanceof Error ? err.message : "Failed to add connection");
    } finally {
      setAddFormLoading(false);
    }
  };

  const handleDeleteConfirm = async () => {
    if (!pendingDeleteConn) return;
    setDeleting(true);
    try {
      await apiDeleteConnection(pendingDeleteConn.id);
      setPendingDeleteConn(null);
      setDeleteConfirmText("");
      if (selectedConn === pendingDeleteConn.id) {
        const remaining = connections.filter(c => c.id !== pendingDeleteConn.id);
        setSelectedConn(remaining[0]?.id ?? "");
      }
      reloadConnections();
    } finally {
      setDeleting(false);
    }
  };

  const goToChat = (q?: string) => {
    setSelectedChatSessionId(null);
    setChatInitialQuestion(q);
    setChatKey(k => k + 1); // remount ChatPanel so initialQuestion fires fresh
    setTab("chat");
  };

  return (
    <div className="h-screen overflow-hidden bg-zinc-900 text-zinc-100 flex flex-col">

      {/* ══════════════════════════════════════════════════════════════
          GLOBAL TOP BAR — full width, above sidebar and content
      ══════════════════════════════════════════════════════════════ */}
      <div className="h-12 bg-zinc-950 border-b border-zinc-700/80 flex items-center px-4 gap-4 shrink-0 z-20">

        {/* Brand — same width as sidebar */}
        <div className="w-56 shrink-0 flex items-center gap-2.5">
          <div className="w-6 h-6 rounded-md bg-violet-600 flex items-center justify-center shrink-0">
            <ChartBarIcon label="Aughor" size="small" color="var(--ds-icon-inverse)" />
          </div>
          <div className="leading-tight">
            <span className="text-sm font-semibold tracking-tight text-zinc-100">Aughor</span>
            <span className="text-[9px] text-zinc-500 block -mt-0.5">Autonomous Analyst</span>
          </div>
        </div>

        {/* Search bar — centred, takes up available space */}
        <button
          onClick={() => setShowSearch(true)}
          className="flex-1 max-w-2xl mx-auto flex items-center gap-3 px-4 py-2 rounded-lg bg-zinc-800/80 border border-zinc-700/60 text-zinc-500 text-sm hover:bg-zinc-800 hover:border-zinc-600 hover:text-zinc-400 transition group"
        >
          <span className="shrink-0"><SearchIcon label="Search" size="small" /></span>
          <span className="flex-1 text-left text-[13px]">Search data, tables, analyses, and more…</span>
          <span className="hidden sm:flex items-center gap-0.5 text-[10px] text-zinc-600 group-hover:text-zinc-500 transition">
            <kbd className="px-1.5 py-0.5 rounded border border-zinc-700 bg-zinc-800/60 font-mono">⌘</kbd>
            <kbd className="px-1.5 py-0.5 rounded border border-zinc-700 bg-zinc-800/60 font-mono">K</kbd>
          </span>
        </button>

        {/* Right: spacer matching sidebar content side */}
        <div className="w-56 shrink-0" />
      </div>

      {/* Search palette overlay */}
      {showSearch && (
        <SearchPalette
          onClose={() => setShowSearch(false)}
          onGoToChat={goToChat}
        />
      )}

      {/* ══════════════════════════════════════════════════════════════
          BELOW TOP BAR: sidebar + content
      ══════════════════════════════════════════════════════════════ */}
      <div className="flex-1 flex overflow-hidden min-w-0">

        {/* ── Left navigation sidebar ── */}
        <nav className="w-56 shrink-0 bg-zinc-900 border-r border-zinc-700/80 flex flex-col overflow-hidden">

          {/* Primary nav */}
          <div className="flex flex-col py-2 gap-0.5 px-1.5 shrink-0">
            <NavItem icon={<HomeIcon label="Home" size="small" />} label="Home" active={tab === "home"} onClick={() => setTab("home")} />

            <p className="px-2 pt-4 pb-1 text-[10px] text-zinc-600 uppercase tracking-widest font-semibold">
              Workspace
            </p>
            <NavItem
              icon={<CommentIcon label="Chat" size="small" />}
              label="Chat"
              active={tab === "chat"}
              onClick={() => { setSelectedChatSessionId(null); setChatKey(k => k + 1); setTab("chat"); }}
            />
            <NavItem
              icon={<ClockIcon label="Recents" size="small" />}
              label="Recents"
              active={tab === "recents"}
              onClick={() => setTab("recents")}
            />

            <p className="px-2 pt-4 pb-1 text-[10px] text-zinc-600 uppercase tracking-widest font-semibold">
              Data
            </p>
            <NavItem icon={<ArchiveBoxIcon label="Catalog" size="small" />}  label="Catalog"      active={tab === "catalog"} onClick={() => setTab("catalog")} />
            <NavItem icon={<NodeIcon label="Data Sources" size="small" />}   label="Data Sources" active={tab === "data"}    onClick={() => setTab("data")} />
          </div>

          {/* Connection list — shown inline when on Data Sources tab */}
          {tab === "data" && (
            <div className="flex-1 overflow-y-auto min-h-0 border-t border-zinc-700/80">
              <div className="px-2 pt-2 pb-1">
                <div className="flex items-center justify-between px-1 pb-1.5">
                  <span className="text-[10px] uppercase tracking-widest font-semibold text-zinc-600">Connections</span>
                  <button
                    onClick={() => setSidebarAddingConn(v => !v)}
                    className="text-[11px] transition"
                    style={{ color: sidebarAddingConn ? "#9a9ba4" : "#3d6bff" }}
                  >
                    {sidebarAddingConn ? "Cancel" : "+ Add"}
                  </button>
                </div>

                {sidebarAddingConn && (
                  <form onSubmit={handleSidebarAdd} className="mb-2 space-y-2 p-2 rounded-lg" style={{ background: "#13141a", border: "0.5px solid #1e1f24" }}>
                    <div>
                      <label className="text-[10px] text-zinc-500 block mb-0.5">Name</label>
                      <input className="w-full rounded text-[11px] bg-zinc-800 border border-zinc-700 text-zinc-100 px-2 py-1 focus:outline-none focus:ring-1 focus:ring-zinc-600" placeholder="My Database" value={addFormName} onChange={e => setAddFormName(e.target.value)} required />
                    </div>
                    <div>
                      <label className="text-[10px] text-zinc-500 block mb-0.5">Type</label>
                      <select className="w-full rounded text-[11px] bg-zinc-800 border border-zinc-700 text-zinc-100 px-2 py-1 focus:outline-none" value={addFormType} onChange={e => setAddFormType(e.target.value)}>
                        <option value="postgres">PostgreSQL</option>
                        <option value="duckdb">DuckDB file</option>
                      </select>
                    </div>
                    <div>
                      <label className="text-[10px] text-zinc-500 block mb-0.5">{addFormType === "postgres" ? "Connection string" : "File path"}</label>
                      <input className="w-full rounded text-[11px] bg-zinc-800 border border-zinc-700 text-zinc-300 font-mono px-2 py-1 focus:outline-none" placeholder={addFormType === "postgres" ? "postgresql://..." : "/path/to/file.duckdb"} value={addFormDsn} onChange={e => setAddFormDsn(e.target.value)} required />
                    </div>
                    <div>
                      <label className="text-[10px] text-zinc-500 block mb-0.5">Schema <span className="text-zinc-600">(optional)</span></label>
                      <input className="w-full rounded text-[11px] bg-zinc-800 border border-zinc-700 text-zinc-300 font-mono px-2 py-1 focus:outline-none" placeholder={addFormType === "postgres" ? "public" : "main"} value={addFormSchema} onChange={e => setAddFormSchema(e.target.value)} />
                    </div>
                    {addFormError && <p className="text-[10px] text-red-400">{addFormError}</p>}
                    <button type="submit" disabled={addFormLoading} className="w-full rounded text-[11px] bg-zinc-100 text-zinc-900 font-medium py-1 hover:bg-white disabled:opacity-40 transition">
                      {addFormLoading ? "Saving…" : "Save connection"}
                    </button>
                  </form>
                )}

                {connections.map(conn => (
                  <div
                    key={conn.id}
                    className="relative"
                    onMouseEnter={() => setHoveredConn(conn.id)}
                    onMouseLeave={() => setHoveredConn(null)}
                  >
                    <button
                      onClick={() => setSelectedConn(conn.id)}
                      className="w-full text-left px-2 py-2 rounded-sm border-l-2 transition-all block"
                      style={{
                        borderLeftColor: conn.id === selectedConn ? "#3d6bff" : "transparent",
                        background: conn.id === selectedConn ? "#13141a" : "transparent",
                      }}
                      onMouseEnter={e => { if (conn.id !== selectedConn) (e.currentTarget as HTMLButtonElement).style.background = "rgba(19,20,26,0.5)"; }}
                      onMouseLeave={e => { if (conn.id !== selectedConn) (e.currentTarget as HTMLButtonElement).style.background = "transparent"; }}
                    >
                      <div className="flex items-center gap-1.5 justify-between pr-5">
                        <span className="text-[12px] font-medium truncate" style={{ color: conn.id === selectedConn ? "#e8e6e1" : "#c0bfbc" }}>
                          {conn.name}
                        </span>
                        <span className="text-[9px] px-1.5 py-0.5 rounded border font-medium shrink-0" style={
                          conn.conn_type === "duckdb"
                            ? { background: "#1a2a1a", color: "#4ade80", border: "0.5px solid #2a4a2a" }
                            : { background: "#1a1e2e", color: "#7ba8f7", border: "0.5px solid #2a3050" }
                        }>
                          {conn.conn_type === "duckdb" ? "DuckDB" : "Postgres"}
                        </span>
                      </div>
                      <p className="text-[10px] font-mono mt-0.5 truncate" style={{ color: "#3e3f47" }}>
                        {conn.dsn_preview}{conn.schema_name ? ` · ${conn.schema_name}` : ""}
                      </p>
                      <div className="flex items-center gap-1.5 mt-1">
                        <span className="w-[5px] h-[5px] rounded-full bg-emerald-400 shrink-0" />
                        <ExplorationBadge connectionId={conn.id} />
                      </div>
                    </button>
                    {/* Delete button — appears on hover for all connections */}
                    <button
                      onClick={e => { e.stopPropagation(); setPendingDeleteConn(conn); setDeleteConfirmText(""); }}
                      className="absolute top-2 right-1.5 p-1 rounded transition-opacity"
                      style={{ opacity: hoveredConn === conn.id ? 1 : 0, color: "#4a4b57" }}
                      onMouseEnter={e => (e.currentTarget.style.color = "#f87171")}
                      onMouseLeave={e => (e.currentTarget.style.color = "#4a4b57")}
                      title="Remove connection"
                    >
                      <svg width="11" height="11" viewBox="0 0 12 12" fill="none">
                        <path d="M4.5 1.5h3M1.5 3h9M3 3l.5 6.5M6 3v6.5M9 3l-.5 6.5" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" strokeLinejoin="round"/>
                      </svg>
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Fill remaining space when not on data tab */}
          {tab !== "data" && <div className="flex-1" />}

        </nav>

        {/* ── Right: topbar + content ── */}
        <SchemaProvider connId={selectedConn}>
        <div className="flex-1 flex flex-col overflow-hidden min-w-0">

          {/* ── Section topbar ── */}
          <header className="h-13 border-b border-zinc-700/80 flex items-center justify-between px-5 shrink-0 gap-4 bg-zinc-900/60" style={{ height: "52px" }}>

            {/* Section breadcrumb */}
            <div className="flex items-center gap-2 shrink-0">
              {tab === "data" ? (
                <div>
                  <span className="text-sm font-semibold text-zinc-200">
                    {connections.find(c => c.id === selectedConn)?.name ?? selectedConn}
                  </span>
                  <p className="text-[11px] mt-0.5" style={{ color: "#3e3f47" }}>
                    Data Sources <span style={{ color: "#5a5b62" }}>/ {connections.find(c => c.id === selectedConn)?.name ?? selectedConn}</span>
                  </p>
                </div>
              ) : (
                <span className="text-sm font-semibold text-zinc-200">
                  {tab === "home" ? "Home" : tab === "chat" ? "Chat" : tab === "recents" ? "Recents" : tab === "catalog" ? "Catalog" : "Home"}
                </span>
              )}
            </div>

            {/* Connection selector — shown on chat */}
            {tab === "chat" && (
              <ConnectionSelector
                connections={connections.length > 0 ? connections : [{ id: selectedConn, name: selectedConn, conn_type: "duckdb", dsn_preview: "", schema_name: null, builtin: false }]}
                selectedId={selectedConn}
                onSelect={setSelectedConn}
                onManage={() => setTab("data")}
              />
            )}

            {/* Right: New Chat + History + Configure */}
            <div className="flex items-center gap-2.5 shrink-0">

              {/* New Chat button */}
              <button
                onClick={() => {
                  setSelectedChatSessionId(null);
                  setSelectedHistoryInvId(null);
                  setChatKey(k => k + 1);   // remounts ChatPanel → clears conversation
                  setTab("chat");
                }}
                title="New Chat"
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-zinc-800 border border-zinc-700 text-zinc-400 hover:text-zinc-200 hover:border-zinc-600 hover:bg-zinc-700/60 text-xs font-medium transition"
              >
                <AddIcon label="New" size="small" />
                <span>New</span>
              </button>

              {/* History button */}
              <button
                onClick={() => { setShowHistory((v) => !v); setShowConfigure(false); }}
                title="History"
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs font-medium transition ${
                  showHistory
                    ? "border-violet-500/50 bg-violet-500/10 text-violet-400"
                    : "border-zinc-700 bg-zinc-800 text-zinc-400 hover:text-zinc-200 hover:border-zinc-600 hover:bg-zinc-700/60"
                }`}
              >
                <ClockIcon label="History" size="small" />
                <span>History</span>
              </button>

              {/* Configure button */}
              <button
                onClick={() => { setShowConfigure((v) => !v); setShowHistory(false); }}
                title="Configure"
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs font-medium transition ${
                  showConfigure
                    ? "border-blue-500 bg-blue-600 text-white shadow-sm shadow-blue-500/20"
                    : "border-zinc-700 bg-zinc-800 text-zinc-400 hover:text-zinc-200 hover:border-zinc-600 hover:bg-zinc-700/60"
                }`}
              >
                <SettingsIcon label="Configure" size="small" />
                <span>Configure</span>
              </button>
            </div>
          </header>

          {/* ── History popup ── */}
          {showHistory && (
            <>
              <div className="fixed inset-0 z-40" onClick={() => setShowHistory(false)} />
              <div className="fixed top-[104px] right-4 z-50 h-[72vh] bg-zinc-900 border border-zinc-700 rounded-2xl shadow-2xl flex flex-col overflow-hidden" style={{ width: "min(420px, 90vw)" }}>
                <div className="flex items-center justify-between px-4 py-3 border-b border-zinc-700 shrink-0">
                  <span className="text-sm font-semibold text-zinc-200">History</span>
                  <button onClick={() => setShowHistory(false)} className="text-zinc-500 hover:text-zinc-300 transition">
                    <CloseIcon label="Close" size="small" />
                  </button>
                </div>
                <HistoryPanel
                  selectedId={selectedHistoryInvId ?? selectedChatSessionId}
                  onSelect={(id, kind) => {
                    setShowHistory(false);
                    if (kind === "chat") {
                      setSelectedHistoryInvId(null);
                      setSelectedChatSessionId(id);
                      setTab("chat");
                    } else {
                      setSelectedChatSessionId(null);
                      setSelectedHistoryInvId(id);
                      setTab("chat");
                    }
                  }}
                />
              </div>
            </>
          )}

          {/* ── Configure panel ── */}
          {showConfigure && (
            <ConfigurePanel
              connectionId={selectedConn}
              connections={connections.length > 0 ? connections : [{ id: selectedConn, name: selectedConn, conn_type: "duckdb", dsn_preview: "", schema_name: null, builtin: false }]}
              onSelectConn={(id) => { setSelectedConn(id); }}
              onClose={() => setShowConfigure(false)}
            />
          )}

          {/* ── Main content area ── */}
          <div className="flex-1 flex overflow-hidden min-w-0" style={{ background: "#0d0e11" }}>

            {/* ════ HOME TAB ════ */}
            {tab === "home" && (
              <HomePage
                connections={connections}
                selectedConn={selectedConn}
                onGoToChat={goToChat}
                onGoToCatalog={() => setTab("catalog")}
                onGoToData={(subTab, section) => { setTab("data"); if (subTab) setConnRightTab(subTab); setExplorationSection(section); }}
              />
            )}

            {/* ════ RECENTS TAB ════ */}
            {tab === "recents" && (
              <RecentsPanel
                onGoToChat={goToChat}
                onGoToData={() => setTab("data")}
              />
            )}

            {/* ════ CHAT TAB ════ */}
            {tab === "chat" && (
              selectedHistoryInvId
                ? <HistoryDetailPanel invId={selectedHistoryInvId} />
                : <ChatPanel
                    key={chatKey}
                    connectionId={selectedConn}
                    restoreSessionId={selectedChatSessionId}
                    initialQuestion={chatInitialQuestion}
                    initialMode="investigate"
                  />
            )}

            {/* ════ CATALOG TAB ════ */}
            {tab === "catalog" && (
              <CatalogPanel
                connectionId={selectedConn}
                onChatWithTable={(table, connId) => {
                  setSelectedConn(connId);
                  setTab("chat");
                }}
              />
            )}

            {/* ════ DATA SOURCES TAB (connections in sidebar + detail panel) ════ */}
            {tab === "data" && (
              <div className="flex-1 flex overflow-hidden">
                {/* Right: ontology-first panel with sub-tabs */}
                <div className="flex-1 flex flex-col overflow-hidden">
                  <div className="flex items-center border-b border-zinc-700/80 px-4 shrink-0 bg-zinc-900/40">
                    {(["ontology", "schema", "exploration", "activity", "playbook", "inbox", "documents", "system"] as const).map((t) => (
                      <button
                        key={t}
                        onClick={() => setConnRightTab(t)}
                        className={`px-4 py-3.5 text-xs font-medium capitalize transition-colors border-b-2 -mb-px ${
                          connRightTab === t
                            ? "border-violet-500 text-violet-400"
                            : "border-transparent text-zinc-500 hover:text-zinc-300"
                        }`}
                      >
                        {t === "ontology"    ? "Ontology"
                         : t === "schema"    ? "Schema"
                         : t === "exploration" ? "Exploration"
                         : t === "activity"  ? "Activity"
                         : t === "playbook"  ? "Playbook"
                         : t === "inbox"     ? "Inbox"
                         : t === "documents" ? "Documents"
                         : "System Stats"}
                      </button>
                    ))}
                  </div>
                  {connRightTab === "ontology" ? (
                    <OntologyPanel
                      connectionId={selectedConn}
                      onInvestigate={(q) => goToChat(q)}
                    />
                  ) : connRightTab === "schema" ? (
                    <SchemaPanel connId={selectedConn} connName={selectedConn} />
                  ) : connRightTab === "exploration" ? (
                    <ExplorationPanel connectionId={selectedConn} initialSection={explorationSection} />
                  ) : connRightTab === "activity" ? (
                    <ActivityLog connectionId={selectedConn} isActive={connRightTab === "activity"} />
                  ) : connRightTab === "playbook" ? (
                    <PlaybookPanel />
                  ) : connRightTab === "inbox" ? (
                    <div className="flex-1 overflow-y-auto p-4">
                      <RecommendationInbox
                        onOpenInvestigation={(invId) => {
                          setSelectedHistoryInvId(invId);
                          setTab("chat");
                        }}
                      />
                    </div>
                  ) : connRightTab === "documents" ? (
                    <div className="flex-1 overflow-y-auto p-4">
                      <DocumentUploader />
                    </div>
                  ) : (
                    <SystemPanel />
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
        </SchemaProvider>
      </div>

      {/* ── Delete connection modal ─────────────────────────────────────────── */}
      {pendingDeleteConn && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4"
          style={{ background: "rgba(0,0,0,0.7)", backdropFilter: "blur(4px)" }}
          onClick={e => { if (e.target === e.currentTarget) { setPendingDeleteConn(null); setDeleteConfirmText(""); } }}
        >
          <div
            className="w-full max-w-sm rounded-xl p-6 flex flex-col gap-5"
            style={{ background: "#0f1014", border: "0.5px solid #2a2b35" }}
          >
            {/* Header */}
            <div className="flex items-start gap-3">
              <div className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0" style={{ background: "#2a1414", border: "0.5px solid #3e2020" }}>
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                  <path d="M6 2h4M2 4h12M5 4l.5 8M8 4v8M11 4l-.5 8" stroke="#f87171" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
              </div>
              <div>
                <p className="text-[13px] font-medium" style={{ color: "#e8e6e1" }}>Remove connection</p>
                <p className="text-[11px] mt-0.5" style={{ color: "#5a5b62" }}>
                  This removes <span style={{ color: "#c8c7c3" }}>{pendingDeleteConn.name}</span> from Aughor. The underlying database is not affected.
                </p>
              </div>
            </div>

            {/* What gets removed */}
            <div className="rounded-lg p-3 space-y-1.5" style={{ background: "#13141a", border: "0.5px solid #1e1f24" }}>
              {[
                "Connection credentials and settings",
                "Exploration history and findings",
                "Saved ontology and entity graph",
              ].map(item => (
                <div key={item} className="flex items-center gap-2">
                  <span className="w-1 h-1 rounded-full shrink-0" style={{ background: "#f87171" }} />
                  <span className="text-[11px]" style={{ color: "#6e6f78" }}>{item}</span>
                </div>
              ))}
            </div>

            {/* Confirm by typing name */}
            <div>
              <p className="text-[10px] mb-1.5" style={{ color: "#5a5b62" }}>
                Type <span className="font-mono" style={{ color: "#9a9ba4" }}>{pendingDeleteConn.name}</span> to confirm
              </p>
              <input
                autoFocus
                type="text"
                value={deleteConfirmText}
                onChange={e => setDeleteConfirmText(e.target.value)}
                onKeyDown={e => { if (e.key === "Enter" && deleteConfirmText === pendingDeleteConn.name) handleDeleteConfirm(); }}
                placeholder={pendingDeleteConn.name}
                className="w-full text-[12px] rounded-lg px-3 py-2 focus:outline-none font-mono"
                style={{ background: "#13141a", border: `0.5px solid ${deleteConfirmText === pendingDeleteConn.name ? "#3e2020" : "#1e1f24"}`, color: "#c8c7c3" }}
              />
            </div>

            {/* Actions */}
            <div className="flex gap-2 justify-end">
              <button
                onClick={() => { setPendingDeleteConn(null); setDeleteConfirmText(""); }}
                className="text-[12px] px-4 py-2 rounded-lg transition-colors"
                style={{ background: "#1a1a22", color: "#6e6f78", border: "0.5px solid #2a2b35" }}
              >
                Cancel
              </button>
              <button
                onClick={handleDeleteConfirm}
                disabled={deleteConfirmText !== pendingDeleteConn.name || deleting}
                className="text-[12px] px-4 py-2 rounded-lg transition-all disabled:opacity-30"
                style={{ background: "#2a1414", color: "#f87171", border: "0.5px solid #3e2020" }}
              >
                {deleting ? "Removing…" : "Remove connection"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
