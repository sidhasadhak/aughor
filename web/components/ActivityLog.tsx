"use client";

import { useEffect, useRef, useState } from "react";
import {
  getExplorationEpisodes,
  getExplorationStatus,
  stopExploration,
  resumeExploration,
  restartExploration,
  retryQuery,
  type ExplorationEpisode,
  type ExplorationStatus,
  type RetryQueryResult,
} from "@/lib/api";

// ── Phase metadata ────────────────────────────────────────────────────────────

const PHASE_META: Record<string, { label: string; color: string; bg: string }> = {
  exploration:       { label: "schema",    color: "#9a9ba4", bg: "#1e1f24" },
  null_meaning:      { label: "nulls",     color: "#7ba8f7", bg: "#1a1e2e" },
  join_verification: { label: "joins",     color: "#f97316", bg: "#2a1e14" },
  lifecycle_mapping: { label: "lifecycle", color: "#4ade80", bg: "#1a2820" },
  distribution:      { label: "dist",      color: "#c084fc", bg: "#22182e" },
  cross_table:       { label: "patterns",  color: "#f87171", bg: "#2a1a1a" },
  domain_intel:      { label: "intel",     color: "#60a5fa", bg: "#1a2030" },
};

function phaseMeta(phase: string) {
  return PHASE_META[phase] ?? { label: phase, color: "#6e6f78", bg: "#1a1a22" };
}

// ── Status bar ────────────────────────────────────────────────────────────────

interface StatusBarProps {
  status: ExplorationStatus | null;
  stopped: boolean;
  onStop: () => void;
  onResume: () => void;
  onRestart: () => void;
  stopping: boolean;
  resuming: boolean;
  restarting: boolean;
}

function StatusBar({ status, stopped, onStop, onResume, onRestart, stopping, resuming, restarting }: StatusBarProps) {
  if (!status) return null;
  const isRunning = !stopped && !["complete", "failed", "pending"].includes(status.phase);
  const isStopped = stopped || status.paused || status.phase === "pending";
  const meta = phaseMeta(status.phase);

  return (
    <div
      className="flex items-center gap-3 px-4 py-2 border-b shrink-0"
      style={{ borderColor: "#1e1f24", background: "#0d0e11" }}
    >
      <span
        className="flex items-center gap-1.5 text-[10px] px-2 py-0.5 rounded font-medium"
        style={isStopped && !isRunning
          ? { background: "#1e1f24", color: "#5a5b62" }
          : { background: meta.bg, color: meta.color }
        }
      >
        {isRunning && (
          <span className="inline-block w-1.5 h-1.5 rounded-full animate-pulse" style={{ background: meta.color }} />
        )}
        {isStopped && !isRunning ? "stopped"
          : status.phase === "complete" ? "complete"
          : status.phase === "pending" ? "idle"
          : meta.label}
      </span>
      <span className="text-[10px]" style={{ color: "#3e3f4a" }}>
        {status.queries_executed > 0 && `${status.queries_executed} queries`}
        {status.facts_discovered > 0 && ` · ${status.facts_discovered} facts`}
        {status.insights_found > 0 && ` · ${status.insights_found} insights`}
      </span>
      <div className="ml-auto flex items-center gap-2">
        <span className="text-[10px]" style={{ color: "#2e2f37" }}>
          {status.tables_total > 0 && `${status.tables_total} tables · ${status.joins_total} joins`}
        </span>
        {isRunning && (
          <button
            onClick={onStop}
            disabled={stopping}
            className="flex items-center gap-1 text-[10px] px-2.5 py-1 rounded transition-all disabled:opacity-40"
            style={{ background: "#2a1414", color: "#f87171", border: "0.5px solid #3e2020" }}
          >
            <span className="w-2 h-2 rounded-sm inline-block" style={{ background: "#f87171" }} />
            {stopping ? "stopping…" : "Stop"}
          </button>
        )}
        {isStopped && !isRunning && (
          <>
            <button
              onClick={onResume}
              disabled={resuming || restarting}
              className="text-[10px] px-2.5 py-1 rounded transition-all disabled:opacity-40"
              style={{ background: "#1a2030", color: "#60a5fa", border: "0.5px solid #2a3a50" }}
            >
              {resuming ? "resuming…" : "Resume"}
            </button>
            <button
              onClick={onRestart}
              disabled={resuming || restarting}
              className="text-[10px] px-2.5 py-1 rounded transition-all disabled:opacity-40"
              style={{ background: "#221a10", color: "#fb923c", border: "0.5px solid #3a2a10" }}
            >
              {restarting ? "restarting…" : "Restart"}
            </button>
          </>
        )}
      </div>
    </div>
  );
}

// ── Retry panel ───────────────────────────────────────────────────────────────

interface RetryPanelProps {
  ep: ExplorationEpisode;
  connectionId: string;
  errorMsg: string;
}

function RetryPanel({ ep, connectionId, errorMsg }: RetryPanelProps) {
  const [hint, setHint] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<RetryQueryResult | null>(null);
  const [open, setOpen] = useState(false);

  async function handleRetry() {
    setLoading(true);
    setResult(null);
    try {
      const r = await retryQuery(connectionId, ep.sql, errorMsg, hint);
      setResult(r);
    } catch (e: unknown) {
      setResult({ ok: false, corrected_sql: "", explanation: "", rows: [], columns: [], error: String(e) });
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="mt-2">
      {!open ? (
        <button
          onClick={() => setOpen(true)}
          className="text-[10px] px-2.5 py-1 rounded transition-all"
          style={{ background: "#1a1e2e", color: "#7ba8f7", border: "0.5px solid #2a3050" }}
        >
          ↺ Retry with fix
        </button>
      ) : (
        <div className="rounded-md p-3 space-y-2" style={{ background: "#0f1018", border: "0.5px solid #2a2b35" }}>
          <p className="text-[9px] uppercase tracking-widest" style={{ color: "#3e3f4a" }}>Guidance (optional)</p>
          <div className="flex gap-2">
            <input
              type="text"
              value={hint}
              onChange={e => setHint(e.target.value)}
              onKeyDown={e => e.key === "Enter" && !loading && handleRetry()}
              placeholder="e.g. use click_ts instead of click_id, join on impression_id…"
              className="flex-1 text-[11px] rounded px-2.5 py-1.5 focus:outline-none"
              style={{ background: "#13141a", border: "0.5px solid #2a2b35", color: "#9a9ba4" }}
            />
            <button
              onClick={handleRetry}
              disabled={loading}
              className="text-[10px] px-3 py-1.5 rounded transition-all disabled:opacity-40 shrink-0"
              style={{ background: "#1a2030", color: "#60a5fa", border: "0.5px solid #2a3a50" }}
            >
              {loading ? "fixing…" : "Run fix"}
            </button>
            <button
              onClick={() => { setOpen(false); setResult(null); }}
              className="text-[10px] px-2 py-1.5 rounded"
              style={{ color: "#3e3f4a" }}
            >
              ✕
            </button>
          </div>

          {result && (
            <div className="space-y-2 pt-1">
              {result.explanation && (
                <p className="text-[11px]" style={{ color: "#7ba8f7" }}>
                  {result.explanation}
                </p>
              )}
              <div>
                <p className="text-[9px] uppercase tracking-widest mb-1" style={{ color: "#2e2f37" }}>Corrected SQL</p>
                <pre
                  className="text-[10px] font-mono rounded p-2 overflow-x-auto"
                  style={{ background: "#0a0b0e", color: "#5a5b62", whiteSpace: "pre-wrap", wordBreak: "break-all" }}
                >
                  {result.corrected_sql}
                </pre>
              </div>
              {result.ok ? (
                <div>
                  <p className="text-[9px] uppercase tracking-widest mb-1" style={{ color: "#2e2f37" }}>
                    Result — {result.row_count} rows
                  </p>
                  <div className="overflow-x-auto rounded" style={{ background: "#0a0b0e" }}>
                    <table className="text-[10px] font-mono w-full">
                      <thead>
                        <tr>
                          {result.columns.map(c => (
                            <th key={c} className="px-2 py-1 text-left font-medium" style={{ color: "#4a4b57", borderBottom: "0.5px solid #1e1f24" }}>
                              {c}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {result.rows.slice(0, 15).map((row, i) => (
                          <tr key={i} style={{ borderBottom: "0.5px solid #111115" }}>
                            {row.map((cell, j) => (
                              <td key={j} className="px-2 py-1" style={{ color: "#6e6f78" }}>{cell}</td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              ) : (
                <pre
                  className="text-[10px] font-mono rounded p-2"
                  style={{ background: "#180f0f", color: "#f87171", whiteSpace: "pre-wrap", wordBreak: "break-all" }}
                >
                  {result.error}
                </pre>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Log row ───────────────────────────────────────────────────────────────────

interface LogRowProps {
  ep: ExplorationEpisode;
  connectionId: string;
}

function LogRow({ ep, connectionId }: LogRowProps) {
  const [expanded, setExpanded] = useState(false);
  const meta = phaseMeta(ep.phase);

  const isError = ep.observation.startsWith("ERROR:") || ep.observation.startsWith("EXCEPTION:");
  const ts = new Date(ep.ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  const thinkDisplay = ep.think.length > 120 ? ep.think.slice(0, 120) + "…" : ep.think;
  const obsPreview = ep.observation.slice(0, 400) + (ep.observation.length > 400 ? "…" : "");

  return (
    <div className="group border-b" style={{ borderColor: "#111115" }}>
      {/* Main row */}
      <button
        className="w-full text-left px-4 py-2 flex items-start gap-3 hover:bg-white/[0.02] transition-colors"
        onClick={() => setExpanded(e => !e)}
      >
        <span className="shrink-0 text-[9px] font-mono mt-0.5 w-12 text-right" style={{ color: "#2e2f37" }}>
          {ts}
        </span>
        <span
          className="shrink-0 text-[9px] px-1.5 py-0.5 rounded mt-0.5 font-medium w-14 text-center"
          style={{ background: meta.bg, color: meta.color }}
        >
          {meta.label}
        </span>
        <span className="flex-1 text-[11px] leading-relaxed text-left" style={{ color: isError ? "#f87171" : "#9a9ba4" }}>
          {thinkDisplay}
        </span>
        {isError && (
          <span className="shrink-0 text-[9px] mt-0.5 px-1.5 py-0.5 rounded" style={{ background: "#2a1414", color: "#f87171" }}>
            error
          </span>
        )}
        <span className="shrink-0 text-[9px] opacity-0 group-hover:opacity-100 transition-opacity mt-0.5 ml-1" style={{ color: "#3e3f4a" }}>
          {expanded ? "▲" : "▼"}
        </span>
      </button>

      {/* Expanded detail */}
      {expanded && (
        <div className="px-4 pb-3 pl-[calc(1rem+3rem+0.75rem+3.5rem+0.75rem)] space-y-2">
          <div>
            <p className="text-[9px] uppercase tracking-widest mb-1" style={{ color: "#2e2f37" }}>SQL</p>
            <pre
              className="text-[10px] font-mono leading-relaxed overflow-x-auto rounded p-2"
              style={{ background: "#0a0b0e", color: "#5a5b62", whiteSpace: "pre-wrap", wordBreak: "break-all" }}
            >
              {ep.sql || "(no sql)"}
            </pre>
          </div>
          <div>
            <p className="text-[9px] uppercase tracking-widest mb-1" style={{ color: "#2e2f37" }}>Result</p>
            <pre
              className="text-[10px] font-mono leading-relaxed overflow-x-auto rounded p-2"
              style={{
                background: isError ? "#180f0f" : "#0a0b0e",
                color: isError ? "#f87171" : "#5a5b62",
                whiteSpace: "pre-wrap",
                wordBreak: "break-all",
              }}
            >
              {obsPreview}
            </pre>
          </div>
          {isError && ep.sql && (
            <RetryPanel ep={ep} connectionId={connectionId} errorMsg={ep.observation} />
          )}
        </div>
      )}
    </div>
  );
}

// ── Main panel ────────────────────────────────────────────────────────────────

interface Props {
  connectionId: string;
  isActive: boolean;
}

export function ActivityLog({ connectionId, isActive }: Props) {
  const [episodes, setEpisodes] = useState<ExplorationEpisode[]>([]);
  const [status, setStatus] = useState<ExplorationStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [following, setFollowing] = useState(true);
  const [stopped, setStopped] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [resuming, setResuming] = useState(false);
  const [restarting, setRestarting] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!isActive) return;
    let cancelled = false;

    const load = async () => {
      try {
        const [eps, st] = await Promise.all([
          getExplorationEpisodes(connectionId, "", 300),
          getExplorationStatus(connectionId).catch(() => null),
        ]);
        if (!cancelled) {
          setEpisodes(eps);
          setStatus(st);
          setLoading(false);
          // Sync stopped state from backend — survives tab switches and page remounts
          if (st?.paused) setStopped(true);
        }
      } catch {
        if (!cancelled) setLoading(false);
      }
    };

    load();
    const t = setInterval(load, 5_000);
    return () => { cancelled = true; clearInterval(t); };
  }, [connectionId, isActive]);

  useEffect(() => {
    if (following && bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [episodes, following]);

  const handleScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    setFollowing(el.scrollHeight - el.scrollTop - el.clientHeight < 60);
  };

  async function handleStop() {
    setStopping(true);
    try {
      await stopExploration(connectionId);
      setStopped(true);
    } finally {
      setStopping(false);
    }
  }

  async function handleResume() {
    setResuming(true);
    try {
      await resumeExploration(connectionId);
      setStopped(false);
    } finally {
      setResuming(false);
    }
  }

  async function handleRestart() {
    setRestarting(true);
    try {
      await restartExploration(connectionId);
      setStopped(false);
      setEpisodes([]);
    } finally {
      setRestarting(false);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-40 text-sm" style={{ color: "#3e3f4a" }}>
        Loading activity…
      </div>
    );
  }

  if (episodes.length === 0) {
    return (
      <div className="h-full flex flex-col">
        <StatusBar status={status} stopped={stopped} onStop={handleStop} onResume={handleResume} onRestart={handleRestart} stopping={stopping} resuming={resuming} restarting={restarting} />
        <div className="flex-1 flex flex-col items-center justify-center gap-2" style={{ color: "#3e3f4a" }}>
          <p className="text-[12px]">No activity recorded yet.</p>
          <p className="text-[11px]" style={{ color: "#2e2f37" }}>Activity appears here as background exploration runs.</p>
        </div>
      </div>
    );
  }

  const isRunning = status && !["complete", "failed", "pending"].includes(status.phase);

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <StatusBar status={status} stopped={stopped} onStop={handleStop} onResume={handleResume} onRestart={handleRestart} stopping={stopping} resuming={resuming} restarting={restarting} />

      {/* Controls bar */}
      <div
        className="flex items-center justify-between px-4 py-1.5 border-b shrink-0"
        style={{ borderColor: "#1a1b20", background: "#0d0e11" }}
      >
        <span className="text-[10px]" style={{ color: "#3e3f4a" }}>
          {episodes.length} entries
          {isRunning && <span className="ml-2 animate-pulse" style={{ color: "#4a4b57" }}>● live</span>}
        </span>
        <button
          onClick={() => setFollowing(f => !f)}
          className="text-[10px] px-2 py-0.5 rounded transition-colors"
          style={{
            background: following ? "#1a2030" : "#13141a",
            color: following ? "#60a5fa" : "#3e3f4a",
            border: `0.5px solid ${following ? "#2a3a50" : "#1e1f24"}`,
          }}
        >
          {following ? "↓ following" : "follow"}
        </button>
      </div>

      {/* Log feed */}
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto font-mono"
        style={{ background: "#0d0e11" }}
      >
        {episodes.map((ep, i) => (
          <LogRow key={`${ep.episode_id}-${ep.ts}-${i}`} ep={ep} connectionId={connectionId} />
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
