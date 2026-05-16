"use client";

import { useState } from "react";
import { ConnectionsPanel } from "@/components/ConnectionsPanel";
import { HistoryPanel } from "@/components/HistoryPanel";
import { HistoryDetailPanel } from "@/components/HistoryDetailPanel";
import { MetricsPanel } from "@/components/MetricsPanel";
import { SchemaPanel } from "@/components/SchemaPanel";
import { FeedbackPrompt } from "@/components/FeedbackPrompt";
import { HypothesisCard } from "@/components/HypothesisCard";
import { ReportView } from "@/components/ReportView";
import { ThinkingTrace } from "@/components/ThinkingTrace";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { useInvestigation } from "@/lib/useInvestigation";
import { ChatPanel } from "@/components/ChatPanel";

const EXAMPLE_QUESTIONS = [
  "Why did revenue drop 8% last week?",
  "What is our MRR this month?",
  "Which customer segment has the highest payment failure rate?",
  "Show me the top 10 customers by revenue",
  "Is the APAC revenue decline a trend or a one-time event?",
];

type Tab = "investigate" | "chat" | "history" | "connections";

export default function Home() {
  const { state, investigate, submitFeedback, loadHistorical } = useInvestigation();
  const [input, setInput] = useState("");
  const [hitl, setHitl] = useState(false);
  const [tab, setTab] = useState<Tab>("investigate");
  const [selectedConn, setSelectedConn] = useState("mydb");
  const [schemaConnId, setSchemaConnId] = useState<string | null>(null);
  const [selectedHistoryId, setSelectedHistoryId] = useState<string | null>(null);
  const [connRightTab, setConnRightTab] = useState<"schema" | "metrics">("schema");

  const handleSubmit = (q?: string) => {
    const question = q ?? input.trim();
    if (!question || state.status === "running") return;
    setInput("");
    investigate(question, selectedConn, hitl);
  };

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 flex flex-col">
      {/* Header */}
      <header className="border-b border-zinc-800 px-6 py-3 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-3">
          <span className="text-base font-semibold tracking-tight">Aughor</span>
          <span className="text-xs text-zinc-500 border border-zinc-700 rounded px-2 py-0.5">
            Autonomous Analyst
          </span>
        </div>
        <div className="flex items-center gap-4">
          {state.status === "running" && (
            <div className="flex items-center gap-2 text-xs text-amber-400">
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-75" />
                <span className="relative inline-flex rounded-full h-2 w-2 bg-amber-400" />
              </span>
              {state.queryMode === "direct" ? "Fetching data…" : "Investigating…"}
            </div>
          )}
          {state.status === "paused" && (
            <div className="flex items-center gap-2 text-xs text-violet-400">
              <span className="relative flex h-2 w-2">
                <span className="relative inline-flex rounded-full h-2 w-2 bg-violet-400" />
              </span>
              Awaiting review…
            </div>
          )}
          {/* Tab switcher */}
          <div className="flex rounded-md border border-zinc-800 overflow-hidden">
            {(["investigate", "chat", "history", "connections"] as Tab[]).map(t => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={`px-3 py-1 text-xs capitalize transition ${
                  tab === t
                    ? "bg-zinc-800 text-zinc-100"
                    : "text-zinc-500 hover:text-zinc-300"
                }`}
              >
                {t}
              </button>
            ))}
          </div>
        </div>
      </header>

      <div className="flex-1 flex overflow-hidden">
        {tab === "history" ? (
          /* ── History tab ── */
          <div className="flex-1 flex overflow-hidden">
            <div className="w-80 shrink-0 border-r border-zinc-800 flex flex-col">
              <HistoryPanel
                selectedId={selectedHistoryId}
                onSelect={setSelectedHistoryId}
              />
            </div>
            <HistoryDetailPanel invId={selectedHistoryId} />
          </div>
        ) : tab === "connections" ? (
          /* ── Connections tab ── */
          <div className="flex-1 flex overflow-hidden">
            <ConnectionsPanel
              selectedId={selectedConn}
              onSelect={id => { setSelectedConn(id); setTab("investigate"); }}
              activeSchemaId={schemaConnId}
              onSchemaSelect={setSchemaConnId}
            />
            {/* Right pane: Schema | Metrics sub-tabs */}
            <div className="flex-1 flex flex-col overflow-hidden border-l border-zinc-800">
              <div className="flex items-center gap-0 border-b border-zinc-800 px-4">
                {(["schema", "metrics"] as const).map((t) => (
                  <button
                    key={t}
                    onClick={() => setConnRightTab(t)}
                    className={`px-4 py-2.5 text-xs font-medium capitalize transition-colors border-b-2 -mb-px ${
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
        ) : tab === "chat" ? (
          /* ── Chat tab ── */
          <div className="flex-1 flex overflow-hidden">
            {/* Connection selector sidebar */}
            <div className="w-52 shrink-0 border-r border-zinc-800 flex flex-col">
              <div className="px-4 py-2 border-b border-zinc-800">
                <p className="text-xs text-zinc-600 mb-1">Connection</p>
                <button
                  onClick={() => setTab("connections")}
                  className="text-xs text-zinc-400 hover:text-zinc-200 font-mono truncate max-w-full transition"
                >
                  {selectedConn === "fixture" ? "Fixture DB (demo)" : selectedConn} ↗
                </button>
              </div>
              <div className="p-3 flex-1">
                <p className="text-[10px] text-zinc-600 uppercase tracking-wider mb-2">Tips</p>
                <ul className="space-y-2 text-[11px] text-zinc-600">
                  <li>↵ to send, Shift+↵ for newline</li>
                  <li>Follow up naturally — context carries</li>
                  <li>✕ clears the session</li>
                </ul>
              </div>
            </div>
            <ChatPanel connectionId={selectedConn} />
          </div>
        ) : (
          /* ── Investigation tab ── */
          <>
            {/* Left panel */}
            <div className="w-72 shrink-0 border-r border-zinc-800 flex flex-col">
              {/* Connection indicator */}
              <div className="px-4 py-2 border-b border-zinc-800 flex items-center justify-between">
                <p className="text-xs text-zinc-600">Connected to</p>
                <button
                  onClick={() => setTab("connections")}
                  className="text-xs text-zinc-400 hover:text-zinc-200 font-mono truncate max-w-[160px] transition"
                >
                  {selectedConn === "fixture" ? "Fixture DB (demo)" : selectedConn} ↗
                </button>
              </div>

              {/* Input */}
              <div className="p-4 border-b border-zinc-800 space-y-3">
                <textarea
                  className="w-full rounded-lg bg-zinc-900 border border-zinc-700 text-sm text-zinc-100 placeholder:text-zinc-600 p-3 resize-none focus:outline-none focus:ring-1 focus:ring-zinc-500 transition"
                  rows={3}
                  placeholder="Ask a business question…"
                  value={input}
                  onChange={e => setInput(e.target.value)}
                  onKeyDown={e => {
                    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSubmit(); }
                  }}
                  disabled={state.status === "running"}
                />
                <button
                  onClick={() => handleSubmit()}
                  disabled={!input.trim() || state.status === "running" || state.status === "paused"}
                  className="w-full rounded-lg bg-zinc-100 text-zinc-900 text-sm font-medium py-2 hover:bg-white disabled:opacity-40 disabled:cursor-not-allowed transition"
                >
                  {state.status === "running"
                    ? (state.queryMode === "direct" ? "Fetching…" : "Investigating…")
                    : "Ask →"
                  }
                </button>
                <label className="flex items-center gap-2 cursor-pointer select-none">
                  <div
                    onClick={() => setHitl(v => !v)}
                    className={`relative w-8 h-4 rounded-full transition ${hitl ? "bg-violet-600" : "bg-zinc-700"}`}
                  >
                    <span className={`absolute top-0.5 left-0.5 w-3 h-3 rounded-full bg-white shadow transition-transform ${hitl ? "translate-x-4" : ""}`} />
                  </div>
                  <span className="text-xs text-zinc-500">Review before report</span>
                </label>
              </div>

              {/* Examples */}
              {state.status === "idle" && (
                <div className="p-4 space-y-2">
                  <p className="text-xs text-zinc-600 uppercase tracking-wide">Try</p>
                  {EXAMPLE_QUESTIONS.map(q => (
                    <button
                      key={q}
                      onClick={() => handleSubmit(q)}
                      className="w-full text-left text-xs text-zinc-400 hover:text-zinc-200 rounded-md px-3 py-2 bg-zinc-900 hover:bg-zinc-800 transition"
                    >
                      {q}
                    </button>
                  ))}
                </div>
              )}

              {/* Thinking trace */}
              {state.status !== "idle" && (
                <ScrollArea className="flex-1">
                  <ThinkingTrace state={state} />
                </ScrollArea>
              )}

              {/* Stats */}
              {state.status !== "idle" && (
                <div className={`p-4 border-t border-zinc-800 grid gap-3 shrink-0 ${state.queryMode === "direct" ? "grid-cols-1" : "grid-cols-2"}`}>
                  <div className="rounded-md bg-zinc-900 p-3 text-center">
                    <p className="text-xl font-mono font-semibold text-zinc-200">{state.queriesExecuted}</p>
                    <p className="text-xs text-zinc-600 mt-0.5">SQL queries</p>
                  </div>
                  {state.queryMode !== "direct" && (
                    <div className="rounded-md bg-zinc-900 p-3 text-center">
                      <p className="text-xl font-mono font-semibold text-zinc-200">{state.hypotheses.length}</p>
                      <p className="text-xs text-zinc-600 mt-0.5">Hypotheses</p>
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* Right panel */}
            <div className="flex-1 flex flex-col overflow-hidden">
              {state.status === "idle" ? (
                <div className="flex-1 flex flex-col items-center justify-center gap-4 text-center px-8">
                  <p className="text-3xl font-semibold text-zinc-700">Ask anything.</p>
                  <p className="text-sm text-zinc-600 max-w-sm">
                    Aughor investigates business questions autonomously — forming hypotheses,
                    running SQL, and delivering a narrative verdict.
                  </p>
                  <button
                    onClick={() => setTab("connections")}
                    className="text-xs text-zinc-600 hover:text-zinc-400 underline underline-offset-2 transition"
                  >
                    Connect your own database →
                  </button>
                </div>
              ) : (
                <ScrollArea className="flex-1">
                  <div className="p-6 space-y-8 max-w-3xl mx-auto">
                    <div>
                      <p className="text-xs text-zinc-600 uppercase tracking-wide mb-2">Question</p>
                      <p className="text-base font-medium text-zinc-200">{state.question}</p>
                    </div>

                    {/* Mode badge */}
                    {state.queryMode === "direct" && (
                      <div className="flex items-center gap-2">
                        <span className="text-xs text-sky-400 border border-sky-500/30 bg-sky-500/10 rounded px-2 py-0.5 font-medium">
                          Direct Query
                        </span>
                        <span className="text-xs text-zinc-600">Fetching data directly</span>
                      </div>
                    )}

                    {/* Hypothesis cards — only for investigate mode */}
                    {state.queryMode !== "direct" && state.hypotheses.length > 0 && (
                      <div className="space-y-3">
                        <p className="text-xs text-zinc-600 uppercase tracking-wide">
                          Supportive Evidences — {state.hypotheses.filter(h => h.verdict !== "untested").length} of {state.hypotheses.length} tested
                        </p>
                        {state.hypotheses.map((h, i) => (
                          <HypothesisCard
                            key={h.id}
                            hypothesis={h}
                            index={i}
                            stats={state.statsPerHypothesis[i]}
                          />
                        ))}
                      </div>
                    )}

                    {state.status === "paused" && state.investigationId && (
                      <FeedbackPrompt
                        investigationId={state.investigationId}
                        hypotheses={state.hypotheses}
                        onSubmit={feedback => submitFeedback(state.investigationId!, feedback)}
                      />
                    )}

                    {state.status === "running" && (
                      <div className="flex items-center gap-3 text-sm text-zinc-500">
                        <div className="flex gap-1">
                          {[0, 1, 2].map(i => (
                            <span
                              key={i}
                              className="inline-block h-1.5 w-1.5 rounded-full bg-zinc-600 animate-bounce"
                              style={{ animationDelay: `${i * 150}ms` }}
                            />
                          ))}
                        </div>
                        Analyzing evidence…
                      </div>
                    )}

                    {state.report && (
                      <div className="space-y-4">
                        <Separator className="bg-zinc-800" />

                        {/* Cache hit banner */}
                        {state.fromCache && state.cachedQuestion && (
                          <div className="rounded-md border border-sky-500/25 bg-sky-500/10 px-3 py-2 flex items-start gap-2">
                            <span className="text-sky-400 shrink-0 text-xs mt-0.5">⚡</span>
                            <div>
                              <p className="text-xs text-sky-400 font-medium">Matched a prior investigation</p>
                              <p className="text-xs text-zinc-500 mt-0.5">Originally asked: "{state.cachedQuestion}"</p>
                            </div>
                          </div>
                        )}

                        {/* Hypotheses tested — shown only after a HITL review */}
                        {state.humanFeedback !== null && state.hypotheses.length > 0 && (
                          <div className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-4 space-y-3">
                            <p className="text-xs text-zinc-500 uppercase tracking-wide">Hypotheses tested</p>
                            <div className="space-y-2">
                              {state.hypotheses.map((h, i) => {
                                const colors: Record<string, string> = {
                                  confirmed: "text-emerald-400 bg-emerald-500/10 border-emerald-500/25",
                                  refuted: "text-red-400 bg-red-500/10 border-red-500/25",
                                  inconclusive: "text-amber-400 bg-amber-500/10 border-amber-500/25",
                                  untested: "text-zinc-500 bg-zinc-800 border-zinc-700",
                                };
                                const cls = colors[h.verdict] ?? colors.untested;
                                return (
                                  <div key={h.id} className={`rounded-lg border px-3 py-2 flex items-start gap-3 ${cls}`}>
                                    <span className="text-xs font-mono shrink-0 mt-0.5 opacity-60">H{i + 1}</span>
                                    <div className="flex-1 min-w-0">
                                      <p className="text-xs text-zinc-300 leading-snug">{h.description}</p>
                                      {h.key_finding && (
                                        <p className="text-xs mt-1 opacity-70 leading-snug">{h.key_finding}</p>
                                      )}
                                    </div>
                                    <div className="shrink-0 flex flex-col items-end gap-1">
                                      <span className="text-xs font-medium capitalize">{h.verdict}</span>
                                      <span className="text-xs opacity-60">{Math.round(h.confidence * 100)}%</span>
                                    </div>
                                  </div>
                                );
                              })}
                            </div>
                          </div>
                        )}

                        {/* Analyst feedback card */}
                        {state.humanFeedback && (
                          <div className="rounded-xl border border-violet-500/25 bg-violet-500/5 px-4 py-3 flex items-start gap-3">
                            <span className="text-violet-400 text-xs mt-0.5 shrink-0">✎</span>
                            <div>
                              <p className="text-xs text-violet-300 font-medium mb-1">Analyst feedback applied</p>
                              <p className="text-xs text-zinc-400 leading-relaxed">{state.humanFeedback}</p>
                            </div>
                          </div>
                        )}

                        <p className="text-xs text-zinc-600 uppercase tracking-wide">
                          {state.queryMode === "direct" ? "Query Report" : "Investigation Report"}
                        </p>
                        <ReportView
                          report={state.report}
                          queryCount={state.queriesExecuted}
                          queryHistory={state.queryHistory}
                          queryMode={state.queryMode}
                        />
                      </div>
                    )}

                    {state.error && (
                      <div className="rounded-lg border border-red-500/30 bg-red-500/5 p-4 text-sm text-red-400">
                        {state.error}
                      </div>
                    )}
                  </div>
                </ScrollArea>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
