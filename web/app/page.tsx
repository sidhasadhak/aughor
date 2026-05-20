"use client";

import { useEffect, useState } from "react";
import {
  MessageSquare,
  BarChart2,
  Database,
  Settings,
  ChevronDown,
  PanelRightOpen,
  PanelRightClose,
} from "lucide-react";

import { ConnectionsPanel } from "@/components/ConnectionsPanel";
import { HistoryPanel } from "@/components/HistoryPanel";
import { HistoryDetailPanel } from "@/components/HistoryDetailPanel";
import { MetricsPanel } from "@/components/MetricsPanel";
import { SchemaPanel } from "@/components/SchemaPanel";
import { FeedbackPrompt } from "@/components/FeedbackPrompt";
import { ReportView } from "@/components/ReportView";
import { ExplorationReportView } from "@/components/ExplorationReport";
import { InvestigationReportView } from "@/components/InvestigationReport";
import { ThinkingTrace } from "@/components/ThinkingTrace";
import { Separator } from "@/components/ui/separator";
import { useInvestigation } from "@/lib/useInvestigation";
import { ChatPanel } from "@/components/ChatPanel";
import { getConnections, type Connection } from "@/lib/api";

// ── Types ─────────────────────────────────────────────────────────────────────

type NavTab = "chat" | "investigate" | "data";

// ── Example questions ─────────────────────────────────────────────────────────

const EXAMPLE_QUESTIONS = [
  "Why did revenue drop 8% last week?",
  "What is our MRR this month?",
  "Which customer segment has the highest payment failure rate?",
  "Is the APAC revenue decline a trend or a one-time event?",
  "Show me the top 10 customers by revenue",
];

// ── Nav sidebar item ──────────────────────────────────────────────────────────

function NavItem({
  icon,
  label,
  active,
  onClick,
  bottom,
}: {
  icon: React.ReactNode;
  label: string;
  active?: boolean;
  onClick: () => void;
  bottom?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      className={`
        relative w-full flex items-center gap-3 px-4 py-2.5 text-sm font-medium transition-all
        ${active
          ? "bg-zinc-700/80 text-zinc-100"
          : "text-zinc-500 hover:text-zinc-200 hover:bg-zinc-700/40"}
        ${bottom ? "mt-auto" : ""}
      `}
    >
      {active && (
        <span className="absolute left-0 top-1/2 -translate-y-1/2 w-[3px] h-6 bg-violet-500 rounded-r-full" />
      )}
      <span className={`shrink-0 ${active ? "text-violet-400" : ""}`}>{icon}</span>
      <span className="truncate text-[13px]">{label}</span>
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
        className="flex items-center gap-2 px-3 py-1.5 rounded-md border border-zinc-600 bg-zinc-700/50 hover:bg-zinc-700 transition text-xs text-zinc-300 font-mono"
      >
        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 shrink-0" />
        <span className="max-w-[140px] truncate">{current?.name ?? selectedId}</span>
        <ChevronDown size={11} className="text-zinc-500 shrink-0" />
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} />
          <div className="absolute top-full left-0 mt-1.5 w-56 bg-zinc-800 border border-zinc-600 rounded-lg shadow-2xl z-40 overflow-hidden">
            <div className="px-3 pt-2.5 pb-1">
              <p className="text-[10px] text-zinc-500 uppercase tracking-widest font-medium mb-1.5">
                Connections
              </p>
            </div>
            <div className="pb-1">
              {connections.map((c) => (
                <button
                  key={c.id}
                  onClick={() => { onSelect(c.id); setOpen(false); }}
                  className={`w-full flex items-center gap-2.5 px-3 py-2 text-xs transition hover:bg-zinc-700/60 ${
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
            <div className="border-t border-zinc-600 px-3 py-2">
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

// ── Phase stepper panel (left panel during investigation) ─────────────────────

function InvestigateLeftPanel({
  state,
  selectedHistoryId,
  onHistorySelect,
}: {
  state: ReturnType<typeof useInvestigation>["state"];
  selectedHistoryId: string | null;
  onHistorySelect: (id: string | null) => void;
}) {
  const isActive = state.status === "running" || state.status === "paused";

  return (
    <div className="w-56 shrink-0 border-r border-zinc-600 flex flex-col overflow-hidden bg-zinc-800/60">
      {isActive ? (
        <>
          <div className="px-4 py-3 border-b border-zinc-600 shrink-0">
            <p className="text-[10px] text-zinc-500 uppercase tracking-widest font-medium">
              Analysis Progress
            </p>
          </div>
          <div className="flex-1 overflow-y-auto min-h-0">
            <ThinkingTrace state={state} />
          </div>
          <div className={`p-3 border-t border-zinc-600 grid gap-2 shrink-0 ${
            state.queryMode === "direct" ? "grid-cols-1" : "grid-cols-2"
          }`}>
            <div className="rounded-md bg-zinc-800 border border-zinc-600 p-2.5 text-center">
              <p className="text-lg font-mono font-semibold text-zinc-200">
                {state.queriesExecuted}
              </p>
              <p className="text-[10px] text-zinc-500 mt-0.5">SQL queries</p>
            </div>
            {state.queryMode === "explore" && (
              <div className="rounded-md bg-zinc-800 border border-zinc-600 p-2.5 text-center">
                <p className="text-lg font-mono font-semibold text-zinc-200">
                  {state.subQuestions.length}
                </p>
                <p className="text-[10px] text-zinc-500 mt-0.5">sub-questions</p>
              </div>
            )}
            {state.queryMode === "investigate" && (
              <div className="rounded-md bg-zinc-800 border border-zinc-600 p-2.5 text-center">
                <p className="text-lg font-mono font-semibold text-zinc-200">
                  {state.investigationPhases.length}
                </p>
                <p className="text-[10px] text-zinc-500 mt-0.5">phases done</p>
              </div>
            )}
          </div>
        </>
      ) : (
        <HistoryPanel
          selectedId={selectedHistoryId}
          onSelect={onHistorySelect}
        />
      )}
    </div>
  );
}

// ── Main ──────────────────────────────────────────────────────────────────────

const TAB_LABELS: Record<NavTab, string> = {
  chat: "Chat",
  investigate: "Deep Analysis",
  data: "Data",
};

export default function Home() {
  const { state, investigate, submitFeedback } = useInvestigation();
  const [input, setInput] = useState("");
  const [hitl, setHitl] = useState(false);
  const [tab, setTab] = useState<NavTab>("chat");
  const [selectedConn, setSelectedConn] = useState("mydb");
  const [schemaConnId, setSchemaConnId] = useState<string | null>(null);
  const [selectedHistoryId, setSelectedHistoryId] = useState<string | null>(null);
  const [connRightTab, setConnRightTab] = useState<"schema" | "metrics">("schema");
  const [showSchema, setShowSchema] = useState(false);
  const [connections, setConnections] = useState<Connection[]>([]);

  useEffect(() => {
    getConnections()
      .then(setConnections)
      .catch(() => {
        setConnections([{ id: selectedConn, name: selectedConn, conn_type: "postgres", dsn_preview: "", schema_name: null, builtin: false }]);
      });
  }, []);

  const handleSubmit = (q?: string) => {
    const question = q ?? input.trim();
    if (!question || state.status === "running") return;
    setInput("");
    investigate(question, selectedConn, hitl);
  };

  const isRunning = state.status === "running";
  const isPaused = state.status === "paused";

  return (
    <div className="h-screen overflow-hidden bg-zinc-800 text-zinc-100 flex">

      {/* ── Left navigation sidebar (Databricks-style) ── */}
      <nav className="w-52 shrink-0 bg-zinc-900 border-r border-zinc-600 flex flex-col overflow-hidden">

        {/* Brand */}
        <div className="px-4 py-4 border-b border-zinc-600 shrink-0">
          <div className="flex items-center gap-2">
            <div className="w-6 h-6 rounded bg-violet-600 flex items-center justify-center shrink-0">
              <BarChart2 size={13} className="text-white" />
            </div>
            <span className="text-sm font-semibold tracking-tight text-zinc-100">Aughor</span>
          </div>
          <p className="text-[10px] text-zinc-500 mt-1 ml-8">Autonomous Analyst</p>
        </div>

        {/* Primary nav */}
        <div className="flex-1 flex flex-col py-2 overflow-y-auto">
          <p className="px-4 pt-2 pb-1 text-[10px] text-zinc-600 uppercase tracking-widest font-medium">
            Workspace
          </p>
          <NavItem
            icon={<MessageSquare size={15} />}
            label="Chat"
            active={tab === "chat"}
            onClick={() => setTab("chat")}
          />
          <NavItem
            icon={<BarChart2 size={15} />}
            label="Deep Analysis"
            active={tab === "investigate"}
            onClick={() => setTab("investigate")}
          />

          <p className="px-4 pt-4 pb-1 text-[10px] text-zinc-600 uppercase tracking-widest font-medium">
            Catalog
          </p>
          <NavItem
            icon={<Database size={15} />}
            label="Data"
            active={tab === "data"}
            onClick={() => setTab("data")}
          />
        </div>

        {/* Bottom: settings */}
        <div className="border-t border-zinc-600 py-2 shrink-0">
          <NavItem
            icon={<Settings size={15} />}
            label="Settings"
            active={false}
            onClick={() => {}}
          />
        </div>
      </nav>

      {/* ── Right: topbar + content ── */}
      <div className="flex-1 flex flex-col overflow-hidden min-w-0">

        {/* ── Topbar ── */}
        <header className="h-12 border-b border-zinc-600 flex items-center justify-between px-5 shrink-0 gap-4 bg-zinc-800">
          {/* Section breadcrumb */}
          <div className="flex items-center gap-2 shrink-0">
            <span className="text-sm font-medium text-zinc-300">{TAB_LABELS[tab]}</span>
          </div>

          {/* Connection selector */}
          {tab !== "data" && (
            <ConnectionSelector
              connections={connections.length > 0 ? connections : [{ id: selectedConn, name: selectedConn, conn_type: "postgres", dsn_preview: "", schema_name: null, builtin: false }]}
              selectedId={selectedConn}
              onSelect={setSelectedConn}
              onManage={() => setTab("data")}
            />
          )}

          {/* Right: status + schema toggle */}
          <div className="flex items-center gap-3 shrink-0">
            {isRunning && (
              <div className="flex items-center gap-1.5 text-[11px] text-amber-400">
                <span className="relative flex h-1.5 w-1.5">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-75" />
                  <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-amber-400" />
                </span>
                {state.queryMode === "direct" ? "Fetching…" : state.queryMode === "explore" ? "Exploring…" : "Investigating…"}
              </div>
            )}
            {isPaused && (
              <div className="flex items-center gap-1.5 text-[11px] text-violet-400">
                <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-violet-400" />
                Awaiting review…
              </div>
            )}

            {tab !== "data" && (
              <button
                onClick={() => setShowSchema((v) => !v)}
                title={showSchema ? "Hide schema" : "Show schema"}
                className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-md border text-xs transition ${
                  showSchema
                    ? "border-violet-500/50 bg-violet-500/10 text-violet-400"
                    : "border-zinc-600 text-zinc-500 hover:text-zinc-300 hover:border-zinc-500"
                }`}
              >
                {showSchema
                  ? <><PanelRightClose size={12} /> <span>Schema</span></>
                  : <><PanelRightOpen size={12} /> <span>Schema</span></>}
              </button>
            )}
          </div>
        </header>

        {/* ── Main content area ── */}
        <div className="flex-1 flex overflow-hidden min-w-0">

          {/* ════ CHAT TAB ════ */}
          {tab === "chat" && (
            <ChatPanel connectionId={selectedConn} />
          )}

          {/* ════ INVESTIGATE TAB ════ */}
          {tab === "investigate" && (
            <div className="flex-1 flex overflow-hidden">

              {/* Left panel: phase trace (running) or history (idle) */}
              <InvestigateLeftPanel
                state={state}
                selectedHistoryId={selectedHistoryId}
                onHistorySelect={setSelectedHistoryId}
              />

              {/* Right: canvas + input at bottom */}
              <div className="flex-1 flex flex-col overflow-hidden">

                {/* Canvas (scrollable) */}
                <div className="flex-1 overflow-y-auto min-h-0">
                  {state.status === "idle" && !selectedHistoryId ? (
                    <div className="h-full flex flex-col items-center justify-center gap-5 text-center px-8 py-12">
                      <div>
                        <p className="text-2xl font-semibold text-zinc-600 mb-2">
                          Deep Analysis
                        </p>
                        <p className="text-sm text-zinc-500 max-w-sm leading-relaxed">
                          Ask a business question. Aughor investigates autonomously — forming
                          hypotheses, running SQL, and delivering a narrative verdict.
                        </p>
                      </div>
                      <div className="flex flex-col gap-1.5 w-full max-w-sm mt-1">
                        {EXAMPLE_QUESTIONS.map((q) => (
                          <button
                            key={q}
                            onClick={() => handleSubmit(q)}
                            className="text-left text-xs text-zinc-400 hover:text-zinc-200 rounded-md px-3 py-2.5 bg-zinc-700/40 hover:bg-zinc-700/70 border border-zinc-600 transition"
                          >
                            {q}
                          </button>
                        ))}
                      </div>
                      <button
                        onClick={() => setTab("data")}
                        className="text-xs text-zinc-600 hover:text-zinc-400 underline underline-offset-2 transition"
                      >
                        Manage connections →
                      </button>
                    </div>
                  ) : state.status === "idle" && selectedHistoryId ? (
                    <HistoryDetailPanel invId={selectedHistoryId} />
                  ) : (
                    <div className="p-6 space-y-8 max-w-3xl mx-auto">
                      {/* Question */}
                      <div>
                        <p className="text-[10px] text-zinc-500 uppercase tracking-widest mb-1.5">
                          Question
                        </p>
                        <p className="text-base font-medium text-zinc-200">
                          {state.question}
                        </p>
                      </div>

                      {/* Mode badge */}
                      {state.queryMode === "direct" && (
                        <div className="flex items-center gap-2">
                          <span className="text-xs text-sky-400 border border-sky-500/30 bg-sky-500/10 rounded-full px-2.5 py-0.5 font-medium">
                            Direct Query
                          </span>
                          <span className="text-xs text-zinc-500">Single-pass answer</span>
                        </div>
                      )}
                      {state.queryMode === "explore" && (
                        <div className="flex items-center gap-2">
                          <span className="text-xs text-teal-400 border border-teal-500/30 bg-teal-500/10 rounded-full px-2.5 py-0.5 font-medium">
                            Exploration
                          </span>
                          <span className="text-xs text-zinc-500">Open-ended chain analysis</span>
                        </div>
                      )}
                      {state.queryMode === "investigate" && (
                        <div className="flex items-center gap-2">
                          <span className="text-xs text-violet-400 border border-violet-500/30 bg-violet-500/10 rounded-full px-2.5 py-0.5 font-medium">
                            Deep Investigation
                          </span>
                          <span className="text-xs text-zinc-500">ADA — root-cause analysis</span>
                        </div>
                      )}

                      {state.queryMode === "investigate" && !state.adaReport && state.investigationPhases.length > 0 && (
                        <InvestigationReportView streamingPhases={state.investigationPhases} />
                      )}

                      {isPaused && state.investigationId && (
                        <FeedbackPrompt
                          investigationId={state.investigationId}
                          hypotheses={state.hypotheses}
                          onSubmit={(feedback) => submitFeedback(state.investigationId!, feedback)}
                        />
                      )}

                      {isRunning && (
                        <div className="flex items-center gap-3 text-sm text-zinc-500">
                          <span className="flex gap-1">
                            {[0, 1, 2].map((i) => (
                              <span
                                key={i}
                                className="inline-block h-1.5 w-1.5 rounded-full bg-zinc-600 animate-bounce"
                                style={{ animationDelay: `${i * 150}ms` }}
                              />
                            ))}
                          </span>
                          Analyzing evidence…
                        </div>
                      )}

                      {state.queryMode === "explore" && state.exploreReport && (
                        <div className="space-y-4">
                          <Separator className="bg-zinc-700" />
                          <p className="text-[10px] text-zinc-500 uppercase tracking-widest">
                            Exploration Report
                          </p>
                          <ExplorationReportView
                            report={state.exploreReport}
                            subQuestions={state.subQuestions}
                            subqAnswers={state.subqAnswers}
                            queryCount={state.queriesExecuted}
                          />
                        </div>
                      )}

                      {state.queryMode === "investigate" && state.adaReport && (
                        <div className="space-y-4">
                          <Separator className="bg-zinc-700" />
                          <InvestigationReportView report={state.adaReport} />
                        </div>
                      )}

                      {state.queryMode === "direct" && state.report && (
                        <div className="space-y-4">
                          <Separator className="bg-zinc-700" />
                          {state.fromCache && state.cachedQuestion && (
                            <div className="rounded-md border border-sky-500/25 bg-sky-500/10 px-3 py-2 flex items-start gap-2">
                              <span className="text-sky-400 text-xs shrink-0 mt-0.5">⚡</span>
                              <div>
                                <p className="text-xs text-sky-400 font-medium">
                                  Matched a prior investigation
                                </p>
                                <p className="text-xs text-zinc-500 mt-0.5">
                                  Originally asked: "{state.cachedQuestion}"
                                </p>
                              </div>
                            </div>
                          )}
                          <p className="text-[10px] text-zinc-500 uppercase tracking-widest">
                            Query Report
                          </p>
                          <ReportView
                            report={state.report}
                            queryCount={state.queriesExecuted}
                            queryHistory={state.queryHistory}
                            queryMode={state.queryMode}
                            hypotheses={state.hypotheses}
                          />
                        </div>
                      )}

                      {state.error && (
                        <div className="rounded-md border border-red-500/30 bg-red-500/5 p-4 text-sm text-red-400">
                          {state.error}
                        </div>
                      )}
                    </div>
                  )}
                </div>

                {/* Input bar — pinned at bottom */}
                <div className="shrink-0 border-t border-zinc-600 p-4 space-y-2.5 bg-zinc-800">
                  <textarea
                    className="w-full rounded-md bg-zinc-700/50 border border-zinc-600 text-sm text-zinc-100 placeholder:text-zinc-500 px-4 py-3 resize-none focus:outline-none focus:ring-1 focus:ring-violet-500/50 focus:border-violet-500/50 transition"
                    rows={2}
                    placeholder="Ask a deep business question…"
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && !e.shiftKey) {
                        e.preventDefault();
                        handleSubmit();
                      }
                    }}
                    disabled={isRunning}
                  />
                  <div className="flex items-center justify-between gap-3">
                    <label className="flex items-center gap-2 cursor-pointer select-none">
                      <div
                        onClick={() => setHitl((v) => !v)}
                        className={`relative w-7 h-3.5 rounded-full transition ${
                          hitl ? "bg-violet-600" : "bg-zinc-600"
                        }`}
                      >
                        <span
                          className={`absolute top-0.5 left-0.5 w-2.5 h-2.5 rounded-full bg-white shadow transition-transform ${
                            hitl ? "translate-x-3.5" : ""
                          }`}
                        />
                      </div>
                      <span className="text-[11px] text-zinc-500">Review before report</span>
                    </label>

                    <button
                      onClick={() => handleSubmit()}
                      disabled={!input.trim() || isRunning || isPaused}
                      className="rounded-md bg-violet-600 text-white text-sm font-medium px-5 py-2 hover:bg-violet-500 disabled:opacity-40 disabled:cursor-not-allowed transition"
                    >
                      {isRunning
                        ? (state.queryMode === "direct"
                          ? "Fetching…"
                          : state.queryMode === "explore"
                          ? "Exploring…"
                          : "Investigating…")
                        : "Investigate →"}
                    </button>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* ════ DATA TAB ════ */}
          {tab === "data" && (
            <div className="flex-1 flex overflow-hidden">
              <ConnectionsPanel
                selectedId={selectedConn}
                onSelect={(id) => { setSelectedConn(id); setTab("chat"); }}
                activeSchemaId={schemaConnId}
                onSchemaSelect={setSchemaConnId}
              />
              <div className="flex-1 flex flex-col overflow-hidden border-l border-zinc-600">
                <div className="flex items-center border-b border-zinc-600 px-4 shrink-0">
                  {(["schema", "metrics"] as const).map((t) => (
                    <button
                      key={t}
                      onClick={() => setConnRightTab(t)}
                      className={`px-4 py-3 text-xs font-medium capitalize transition-colors border-b-2 -mb-px ${
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

        {/* Schema sidebar (right) — Chat & Investigate tabs */}
        {showSchema && tab !== "data" && (
          <div className="w-96 shrink-0 border-l border-zinc-600 flex flex-col overflow-hidden">
            <div className="flex items-center justify-between px-4 py-3 border-b border-zinc-600 shrink-0">
              <span className="text-xs font-medium text-zinc-400">
                Schema
                <span className="font-mono text-zinc-500 ml-1.5">{selectedConn}</span>
              </span>
            </div>
            <SchemaPanel connId={selectedConn} connName={selectedConn} />
          </div>
        )}
      </div>
    </div>
  );
}
