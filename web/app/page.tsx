"use client";

import { useEffect, useRef, useState } from "react";
import { ConnectionsPanel } from "@/components/ConnectionsPanel";
import { HypothesisCard } from "@/components/HypothesisCard";
import { ReportView } from "@/components/ReportView";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { useInvestigation } from "@/lib/useInvestigation";

const EXAMPLE_QUESTIONS = [
  "Why did revenue drop 8% last week?",
  "Which customer segment has the highest payment failure rate?",
  "Is the APAC revenue decline a trend or a one-time event?",
];

type Tab = "investigate" | "connections";

export default function Home() {
  const { state, investigate } = useInvestigation();
  const [input, setInput] = useState("");
  const [tab, setTab] = useState<Tab>("investigate");
  const [selectedConn, setSelectedConn] = useState("fixture");
  const logEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [state.log]);

  const handleSubmit = (q?: string) => {
    const question = q ?? input.trim();
    if (!question || state.status === "running") return;
    setInput("");
    investigate(question, selectedConn);
  };

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 flex flex-col">
      {/* Header */}
      <header className="border-b border-zinc-800 px-6 py-3 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-3">
          <span className="text-base font-semibold tracking-tight">Hermes</span>
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
              Investigating…
            </div>
          )}
          {/* Tab switcher */}
          <div className="flex rounded-md border border-zinc-800 overflow-hidden">
            {(["investigate", "connections"] as Tab[]).map(t => (
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
        {tab === "connections" ? (
          /* ── Connections tab ── */
          <div className="flex-1 max-w-md mx-auto w-full">
            <ConnectionsPanel
              selectedId={selectedConn}
              onSelect={id => { setSelectedConn(id); setTab("investigate"); }}
            />
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
                  disabled={!input.trim() || state.status === "running"}
                  className="w-full rounded-lg bg-zinc-100 text-zinc-900 text-sm font-medium py-2 hover:bg-white disabled:opacity-40 disabled:cursor-not-allowed transition"
                >
                  {state.status === "running" ? "Investigating…" : "Investigate →"}
                </button>
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

              {/* Activity log */}
              {state.log.length > 0 && (
                <ScrollArea className="flex-1 p-4">
                  <p className="text-xs text-zinc-600 uppercase tracking-wide mb-2">Activity</p>
                  <div className="space-y-1">
                    {state.log.map((entry, i) => (
                      <p key={i} className="text-xs text-zinc-500 leading-relaxed">
                        <span className="text-zinc-700 font-mono mr-1">{String(i + 1).padStart(2, "0")}</span>
                        {entry}
                      </p>
                    ))}
                    <div ref={logEndRef} />
                  </div>
                </ScrollArea>
              )}

              {/* Stats */}
              {state.status !== "idle" && (
                <div className="p-4 border-t border-zinc-800 grid grid-cols-2 gap-3 shrink-0">
                  <div className="rounded-md bg-zinc-900 p-3 text-center">
                    <p className="text-xl font-mono font-semibold text-zinc-200">{state.queriesExecuted}</p>
                    <p className="text-xs text-zinc-600 mt-0.5">SQL queries</p>
                  </div>
                  <div className="rounded-md bg-zinc-900 p-3 text-center">
                    <p className="text-xl font-mono font-semibold text-zinc-200">{state.hypotheses.length}</p>
                    <p className="text-xs text-zinc-600 mt-0.5">Hypotheses</p>
                  </div>
                </div>
              )}
            </div>

            {/* Right panel */}
            <div className="flex-1 flex flex-col overflow-hidden">
              {state.status === "idle" ? (
                <div className="flex-1 flex flex-col items-center justify-center gap-4 text-center px-8">
                  <p className="text-3xl font-semibold text-zinc-700">Ask anything.</p>
                  <p className="text-sm text-zinc-600 max-w-sm">
                    Hermes investigates business questions autonomously — forming hypotheses,
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

                    {state.hypotheses.length > 0 && (
                      <div className="space-y-3">
                        <p className="text-xs text-zinc-600 uppercase tracking-wide">
                          Hypotheses — {state.hypotheses.filter(h => h.verdict !== "untested").length} of {state.hypotheses.length} tested
                        </p>
                        {state.hypotheses.map((h, i) => (
                          <HypothesisCard key={h.id} hypothesis={h} index={i} />
                        ))}
                      </div>
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
                      <div className="space-y-3">
                        <Separator className="bg-zinc-800" />
                        <p className="text-xs text-zinc-600 uppercase tracking-wide">Investigation Report</p>
                        <ReportView report={state.report} queryCount={state.queriesExecuted} />
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
