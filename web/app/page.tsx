"use client";

import { useEffect, useRef, useState } from "react";
import {
  MessageSquare,
  BarChart2,
  Database,
  Settings,
  ChevronDown,
  Home as HomeIcon,
  BookOpen,
  Clock,
  Search,
  Plus,
  X,
  ArrowLeft,
} from "lucide-react";

import { ConfigurePanel } from "@/components/ConfigurePanel";
import { ConnectionsPanel } from "@/components/ConnectionsPanel";
import { HistoryPanel } from "@/components/HistoryPanel";
import { HistoryDetailPanel } from "@/components/HistoryDetailPanel";
import { MetricsPanel } from "@/components/MetricsPanel";
import { SchemaPanel } from "@/components/SchemaPanel";
import { CatalogPanel } from "@/components/CatalogPanel";
import { ChatPanel } from "@/components/ChatPanel";
import { getConnections, type Connection } from "@/lib/api";

// ── Types ─────────────────────────────────────────────────────────────────────

type NavTab = "home" | "chat" | "catalog" | "data";

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
  const current = connections.find((c) => c.id === selectedId);

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 px-3 py-1.5 rounded-lg border border-zinc-600/70 bg-zinc-800 hover:bg-zinc-700/60 transition text-xs text-zinc-300 font-mono"
      >
        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 shrink-0" />
        <span className="max-w-[160px] truncate">{current?.name ?? selectedId}</span>
        <ChevronDown size={11} className="text-zinc-500 shrink-0" />
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
    { label: "New Chat",  icon: <MessageSquare size={13} />, action: () => { onGoToChat(); onClose(); } },
    ...EXAMPLE_QUESTIONS.map(q => ({
      label: q,
      icon: <Search size={13} className="text-zinc-500" />,
      action: () => { onGoToChat(q); onClose(); },
    })),
  ].filter(s => !query || s.label.toLowerCase().includes(query.toLowerCase()));

  return (
    <>
      <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm" onClick={onClose} />
      <div className="fixed top-[18%] left-1/2 -translate-x-1/2 z-50 w-full max-w-xl bg-zinc-900 border border-zinc-600 rounded-2xl shadow-2xl overflow-hidden">
        {/* Input row */}
        <div className="flex items-center gap-3 px-4 py-3.5 border-b border-zinc-700/80">
          <Search size={15} className="text-zinc-500 shrink-0" />
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

// ── Home page ──────────────────────────────────────────────────────────────────

function HomePage({
  connections,
  selectedConn,
  onGoToChat,
  onGoToCatalog,
}: {
  connections: Connection[];
  selectedConn: string;
  onGoToChat: (q?: string) => void;
  onGoToCatalog: () => void;
}) {
  const [recentInvs, setRecentInvs] = useState<{ id: string; question: string; started_at: string; status: string; headline: string | null }[]>([]);
  const conn = connections.find(c => c.id === selectedConn);

  useEffect(() => {
    fetch("http://localhost:8000/investigations")
      .then(r => r.json())
      .then(d => setRecentInvs(Array.isArray(d) ? d.slice(0, 5) : []))
      .catch(() => {});
  }, []);

  const quickStarters = [
    "What are the top-selling products this month?",
    "Which marketing channels drive the most revenue?",
    "Why did order count drop last month?",
    "What is our average order value?",
  ];

  return (
    <div className="flex-1 overflow-y-auto min-h-0 bg-zinc-850">
      <div className="max-w-5xl mx-auto px-10 py-12 space-y-10">

        {/* ── Welcome banner ── */}
        <div>
          <h1 className="text-3xl font-semibold text-zinc-100 tracking-tight">
            Welcome to Aughor
          </h1>
          <p className="text-sm text-zinc-500 mt-2">
            Your autonomous data analyst — ask questions, investigate root causes, explore your data.
          </p>
        </div>

        {/* ── Active connection card ── */}
        <div className="rounded-2xl border border-zinc-700/70 bg-zinc-900/60 px-6 py-5 flex items-center gap-4">
          <div className="w-10 h-10 rounded-xl bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center shrink-0">
            <span className="w-2.5 h-2.5 rounded-full bg-emerald-400" />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-semibold text-zinc-200 font-mono truncate">{conn?.name ?? selectedConn}</p>
            <p className="text-xs text-zinc-500 mt-0.5 uppercase tracking-wider">{conn?.conn_type ?? "database"}</p>
          </div>
          <span className="text-[11px] font-medium text-emerald-400 border border-emerald-500/20 bg-emerald-500/10 rounded-full px-2.5 py-1 shrink-0">Connected</span>
        </div>

        {/* ── Quick start ── */}
        <div>
          <p className="text-[11px] text-zinc-500 uppercase tracking-widest font-medium mb-4">Quick start</p>
          <div className="grid grid-cols-2 gap-4">
            <button
              onClick={() => onGoToChat()}
              className="group rounded-2xl border border-zinc-700/70 bg-zinc-900/40 hover:bg-violet-500/5 hover:border-violet-500/30 p-6 text-left transition-all"
            >
              <div className="w-10 h-10 rounded-xl bg-zinc-700/60 border border-zinc-600 flex items-center justify-center mb-4 group-hover:border-violet-500/30 transition">
                <MessageSquare size={17} className="text-zinc-400 group-hover:text-violet-400 transition" />
              </div>
              <p className="text-sm font-semibold text-zinc-200 group-hover:text-white transition">Chat</p>
              <p className="text-xs text-zinc-500 mt-1.5 leading-relaxed">Ask questions, investigate root causes, and explore your data — all in one place.</p>
            </button>
            <button
              onClick={onGoToCatalog}
              className="group rounded-2xl border border-zinc-700/70 bg-zinc-900/40 hover:bg-sky-500/5 hover:border-sky-500/30 p-6 text-left transition-all"
            >
              <div className="w-10 h-10 rounded-xl bg-zinc-700/60 border border-zinc-600 flex items-center justify-center mb-4 group-hover:border-sky-500/30 transition">
                <BookOpen size={17} className="text-zinc-400 group-hover:text-sky-400 transition" />
              </div>
              <p className="text-sm font-semibold text-zinc-200 group-hover:text-white transition">Catalog</p>
              <p className="text-xs text-zinc-500 mt-1.5 leading-relaxed">Browse tables, columns, and row counts in your database.</p>
            </button>
          </div>
        </div>

        {/* ── Starter questions ── */}
        <div>
          <p className="text-[11px] text-zinc-500 uppercase tracking-widest font-medium mb-3">Try asking</p>
          <div className="space-y-1">
            {quickStarters.map(q => (
              <button
                key={q}
                onClick={() => { onGoToChat(q); }}
                className="w-full text-left text-[12px] text-zinc-400 hover:text-zinc-200 flex items-center gap-3 group py-2 transition"
              >
                <span className="w-1 h-1 rounded-full bg-zinc-600 group-hover:bg-violet-400 transition shrink-0" />
                <span className="group-hover:underline underline-offset-2">{q}</span>
              </button>
            ))}
          </div>
        </div>

        {/* ── Recent activity ── */}
        {recentInvs.length > 0 && (
          <div>
            <p className="text-[11px] text-zinc-500 uppercase tracking-widest font-medium mb-3">Recent investigations</p>
            <div className="space-y-1">
              {recentInvs.map(inv => (
                <div key={inv.id} className="flex items-center gap-3 py-2.5 border-b border-zinc-700/40 last:border-0">
                  <Clock size={12} className="text-zinc-600 shrink-0" />
                  <p className="flex-1 text-sm text-zinc-400 truncate">{inv.question}</p>
                  <span className="text-xs text-zinc-600 shrink-0">{timeAgo(inv.started_at)}</span>
                  {inv.status === "timed_out" && (
                    <span className="text-[10px] text-amber-400 border border-amber-500/20 bg-amber-500/10 rounded px-1.5 py-0.5">timed out</span>
                  )}
                  {inv.status === "failed" && (
                    <span className="text-[10px] text-red-400 border border-red-500/20 bg-red-500/10 rounded px-1.5 py-0.5">failed</span>
                  )}
                  {inv.status === "running" && (
                    <span className="text-[10px] text-emerald-400 border border-emerald-500/20 bg-emerald-500/10 rounded px-1.5 py-0.5">running</span>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Main ──────────────────────────────────────────────────────────────────────

const BEAUTYCOMMERCE_ID = "96f8857f";

export default function Home() {
  const [tab, setTab] = useState<NavTab>("home");
  const [selectedConn, setSelectedConn] = useState(BEAUTYCOMMERCE_ID);
  const [schemaConnId, setSchemaConnId] = useState<string | null>(null);
  const [selectedHistoryInvId, setSelectedHistoryInvId] = useState<string | null>(null); // modal
  const [selectedChatSessionId, setSelectedChatSessionId] = useState<string | null>(null);
  const [chatKey, setChatKey] = useState(0);
  const [connRightTab, setConnRightTab] = useState<"schema" | "metrics">("schema");
  const [showHistory, setShowHistory] = useState(false);
  const [showConfigure, setShowConfigure] = useState(false);
  const [showSearch, setShowSearch] = useState(false);
  const [connections, setConnections] = useState<Connection[]>([]);

  useEffect(() => {
    getConnections()
      .then((conns) => {
        setConnections(conns);
        if (!conns.find(c => c.id === BEAUTYCOMMERCE_ID) && conns.length > 0) {
          setSelectedConn(conns[0].id);
        }
      })
      .catch(() => {
        setConnections([{ id: BEAUTYCOMMERCE_ID, name: "beautycommerece", conn_type: "duckdb", dsn_preview: "", schema_name: "analytics", builtin: false }]);
      });
  }, []);

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

  const goToChat = (q?: string) => {
    setSelectedChatSessionId(null);
    setTab("chat");
    void q; // starter question is handled by ChatPanel via suggestions
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
            <BarChart2 size={13} className="text-white" />
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
          <Search size={13} className="shrink-0" />
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
          <div className="flex-1 flex flex-col py-2 gap-0.5 overflow-y-auto px-1.5">
            <NavItem icon={<HomeIcon size={14} />} label="Home" active={tab === "home"} onClick={() => setTab("home")} />

            <p className="px-2 pt-4 pb-1 text-[10px] text-zinc-600 uppercase tracking-widest font-semibold">
              Workspace
            </p>
            <NavItem
              icon={<MessageSquare size={14} />}
              label="Chat"
              active={tab === "chat"}
              onClick={() => { setSelectedChatSessionId(null); setChatKey(k => k + 1); setTab("chat"); }}
            />

            <p className="px-2 pt-4 pb-1 text-[10px] text-zinc-600 uppercase tracking-widest font-semibold">
              Data
            </p>
            <NavItem icon={<BookOpen size={14} />} label="Catalog"      active={tab === "catalog"} onClick={() => setTab("catalog")} />
            <NavItem icon={<Database size={14} />} label="Connections"  active={tab === "data"}    onClick={() => setTab("data")} />
          </div>

          {/* Bottom: settings */}
          <div className="border-t border-zinc-700/80 py-1.5 px-1.5 shrink-0">
            <NavItem icon={<Settings size={14} />} label="Settings" active={false} onClick={() => {}} />
          </div>
        </nav>

        {/* ── Right: topbar + content ── */}
        <div className="flex-1 flex flex-col overflow-hidden min-w-0">

          {/* ── Section topbar ── */}
          <header className="h-13 border-b border-zinc-700/80 flex items-center justify-between px-5 shrink-0 gap-4 bg-zinc-900/60" style={{ height: "52px" }}>

            {/* Section breadcrumb */}
            <div className="flex items-center gap-2 shrink-0">
              <span className="text-sm font-semibold text-zinc-200">
                {tab === "home"    ? "Home"
                 : tab === "chat"  ? "Chat"
                 : tab === "catalog" ? "Catalog"
                 : "Connections"}
              </span>
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
                  setChatKey(k => k + 1);   // remounts ChatPanel → clears conversation
                  setTab("chat");
                }}
                title="New Chat"
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-zinc-800 border border-zinc-700 text-zinc-400 hover:text-zinc-200 hover:border-zinc-600 hover:bg-zinc-700/60 text-xs font-medium transition"
              >
                <Plus size={13} />
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
                <Clock size={13} />
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
                <Settings size={13} />
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
                    <X size={14} />
                  </button>
                </div>
                <HistoryPanel
                  selectedId={selectedHistoryInvId}
                  onSelect={(id, kind) => {
                    setShowHistory(false);
                    if (kind === "chat") {
                      setSelectedChatSessionId(id);
                      setTab("chat");
                    } else {
                      setSelectedHistoryInvId(id); // opens full-screen modal overlay
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

          {/* ── Investigation history detail — full-screen slide-over ── */}
          {selectedHistoryInvId && (
            <>
              <div
                className="fixed inset-0 z-40 bg-black/40 backdrop-blur-sm"
                onClick={() => setSelectedHistoryInvId(null)}
              />
              <div
                className="fixed top-0 right-0 bottom-0 z-50 flex flex-col bg-zinc-900 border-l border-zinc-700/80 shadow-2xl overflow-hidden"
                style={{ width: "90%" }}
              >
                <div className="h-12 border-b border-zinc-700/80 flex items-center px-4 gap-3 shrink-0 bg-zinc-900">
                  <button
                    onClick={() => setSelectedHistoryInvId(null)}
                    className="flex items-center gap-1.5 text-xs text-zinc-400 hover:text-zinc-200 transition"
                  >
                    <ArrowLeft size={14} />
                    Back
                  </button>
                  <span className="text-xs text-zinc-600">·</span>
                  <span className="text-xs text-zinc-500">Investigation Detail</span>
                </div>
                <div className="flex-1 overflow-auto">
                  <HistoryDetailPanel invId={selectedHistoryInvId} />
                </div>
              </div>
            </>
          )}

          {/* ── Main content area ── */}
          <div className="flex-1 flex overflow-hidden min-w-0">

            {/* ════ HOME TAB ════ */}
            {tab === "home" && (
              <HomePage
                connections={connections}
                selectedConn={selectedConn}
                onGoToChat={goToChat}
                onGoToCatalog={() => setTab("catalog")}
              />
            )}

            {/* ════ CHAT TAB ════ */}
            {tab === "chat" && (
              <ChatPanel
                key={chatKey}
                connectionId={selectedConn}
                restoreSessionId={selectedChatSessionId}
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

            {/* ════ DATA / CONNECTIONS TAB ════ */}
            {tab === "data" && (
              <div className="flex-1 flex overflow-hidden">
                <ConnectionsPanel
                  selectedId={selectedConn}
                  onSelect={(id) => { setSelectedConn(id); setTab("chat"); }}
                  activeSchemaId={schemaConnId}
                  onSchemaSelect={setSchemaConnId}
                />
                <div className="flex-1 flex flex-col overflow-hidden border-l border-zinc-700/80">
                  <div className="flex items-center border-b border-zinc-700/80 px-4 shrink-0 bg-zinc-900/40">
                    {(["schema", "metrics"] as const).map((t) => (
                      <button
                        key={t}
                        onClick={() => setConnRightTab(t)}
                        className={`px-4 py-3.5 text-xs font-medium capitalize transition-colors border-b-2 -mb-px ${
                          connRightTab === t
                            ? "border-violet-500 text-violet-400"
                            : "border-transparent text-zinc-500 hover:text-zinc-300"
                        }`}
                      >
                        {t === "schema" ? "Schema" : "Metrics Catalog"}
                      </button>
                    ))}
                  </div>
                  {connRightTab === "schema" ? (
                    <SchemaPanel connId={schemaConnId} connName={schemaConnId ?? undefined} />
                  ) : (
                    <div className="flex-1 overflow-auto p-4">
                      <MetricsPanel />
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
