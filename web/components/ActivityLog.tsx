"use client";

import React, { useEffect, useRef, useState } from "react";
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
  // Chat-initiated query types
  ask:               { label: "quick",     color: "#9a9ba4", bg: "#1e1f24" },
  investigate:       { label: "agentic",   color: "#c084fc", bg: "#22182e" },
};

function phaseMeta(phase: string) {
  return PHASE_META[phase] ?? { label: phase, color: "#6e6f78", bg: "#1a1a22" };
}

// ── Row metadata derivation ───────────────────────────────────────────────────

interface RowMeta {
  isError:  boolean;
  status:   "success" | "error";
  datetime: string;   // "May 27 · 14:32:15"
  date:     Date;
  object:   string;
  rows:     number | null;
  message:  string;
}

function deriveRowMeta(ep: ExplorationEpisode): RowMeta {
  const isError = ep.observation.startsWith("ERROR:") || ep.observation.startsWith("EXCEPTION:");

  const d    = new Date(ep.ts * 1000);
  const datePart = d.toLocaleDateString([], { month: "short", day: "numeric" });
  const timePart = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  const datetime = `${datePart} · ${timePart}`;

  // Extract primary table from SQL
  const tableMatch =
    ep.sql.match(/\bFROM\s+["'`]?(\w+)["'`]?/i) ??
    ep.sql.match(/\bINTO\s+["'`]?(\w+)["'`]?/i) ??
    ep.sql.match(/\bUPDATE\s+["'`]?(\w+)["'`]?/i);
  const object = tableMatch?.[1] ?? "—";

  // Extract row count from observation
  const rowMatch = ep.observation.match(/\b(\d+)\s+rows?\b/i);
  const rows = rowMatch ? parseInt(rowMatch[1], 10) : null;

  // Clean up message
  const thinkParts = ep.think.split(" | ");
  const message = isError
    ? ep.observation.replace(/^(ERROR|EXCEPTION):\s*/i, "").slice(0, 200)
    : (thinkParts.length >= 3 ? thinkParts.slice(2).join(" | ") : ep.think).slice(0, 200);

  return { isError, status: isError ? "error" : "success", datetime, date: d, object, rows, message };
}

// ── Stable expansion key ──────────────────────────────────────────────────────
// Uses episode_id + ts + phase so it's stable across re-sorts/re-filters.
function expandKey(ep: ExplorationEpisode) {
  return `${ep.episode_id}|${ep.ts}|${ep.phase}`;
}

// ── Sort helpers ──────────────────────────────────────────────────────────────

type SortCol = "seq" | "ts" | "type" | "message" | "status" | "rows" | "object";

interface WithMeta {
  ep:   ExplorationEpisode;
  meta: RowMeta;
  seq:  number; // 1-based original position in API response
}

function sortItems(items: WithMeta[], col: SortCol, dir: "asc" | "desc"): WithMeta[] {
  const m = dir === "asc" ? 1 : -1;
  return [...items].sort((a, b) => {
    switch (col) {
      case "seq":     return m * (a.seq - b.seq);
      case "ts":      return m * (a.ep.ts - b.ep.ts);
      case "type":    return m * phaseMeta(a.ep.phase).label.localeCompare(phaseMeta(b.ep.phase).label);
      case "message": return m * a.meta.message.localeCompare(b.meta.message);
      case "status":  return m * a.meta.status.localeCompare(b.meta.status);
      case "rows":    return m * ((a.meta.rows ?? -1) - (b.meta.rows ?? -1));
      case "object":  return m * a.meta.object.localeCompare(b.meta.object);
      default:        return 0;
    }
  });
}

// ── Date filter helpers ───────────────────────────────────────────────────────

type DateFilter   = "all" | "today" | "yesterday" | "week";
type StatusFilter = "all" | "success" | "error";

function dayStart(d: Date) { return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime(); }

function passesDateFilter(d: Date, filter: DateFilter): boolean {
  if (filter === "all") return true;
  const now      = new Date();
  const today    = dayStart(now);
  const yesterday = today - 86_400_000;
  const weekAgo  = today - 7 * 86_400_000;
  const ts       = dayStart(d);
  if (filter === "today")     return ts === today;
  if (filter === "yesterday") return ts === yesterday;
  if (filter === "week")      return d.getTime() >= weekAgo;
  return true;
}

// ── Status bar ────────────────────────────────────────────────────────────────

interface StatusBarProps {
  status: ExplorationStatus | null; stopped: boolean;
  onStop: () => void; onResume: () => void; onRestart: () => void;
  stopping: boolean; resuming: boolean; restarting: boolean;
}

function StatusBar({ status, stopped, onStop, onResume, onRestart, stopping, resuming, restarting }: StatusBarProps) {
  if (!status) return null;
  const isRunning = !stopped && !["complete", "failed", "pending"].includes(status.phase);
  const isStopped = stopped || status.paused || status.phase === "pending";
  const meta = phaseMeta(status.phase);
  return (
    <div className="flex items-center gap-3 px-4 py-2 border-b shrink-0" style={{ borderColor: "#1e1f24", background: "#0d0e11" }}>
      <span className="flex items-center gap-1.5 text-[10px] px-2 py-0.5 rounded font-medium"
        style={isStopped && !isRunning ? { background: "#1e1f24", color: "#5a5b62" } : { background: meta.bg, color: meta.color }}>
        {isRunning && <span className="inline-block w-1.5 h-1.5 rounded-full animate-pulse" style={{ background: meta.color }} />}
        {isStopped && !isRunning ? "stopped" : status.phase === "complete" ? "complete" : status.phase === "pending" ? "idle" : meta.label}
      </span>
      <span className="text-[10px]" style={{ color: "#3e3f4a" }}>
        {status.queries_executed > 0 && `${status.queries_executed} queries`}
        {status.facts_discovered > 0 && ` · ${status.facts_discovered} facts`}
        {status.insights_found    > 0 && ` · ${status.insights_found} insights`}
      </span>
      <div className="ml-auto flex items-center gap-2">
        <span className="text-[10px]" style={{ color: "#2e2f37" }}>
          {status.tables_total > 0 && `${status.tables_total} tables · ${status.joins_total} joins`}
        </span>
        {isRunning && (
          <button onClick={onStop} disabled={stopping}
            className="flex items-center gap-1 text-[10px] px-2.5 py-1 rounded transition-all disabled:opacity-40"
            style={{ background: "#2a1414", color: "#f87171", border: "0.5px solid #3e2020" }}>
            <span className="w-2 h-2 rounded-sm inline-block" style={{ background: "#f87171" }} />
            {stopping ? "stopping…" : "Stop"}
          </button>
        )}
        {isStopped && !isRunning && (<>
          <button onClick={onResume} disabled={resuming || restarting}
            className="text-[10px] px-2.5 py-1 rounded transition-all disabled:opacity-40"
            style={{ background: "#1a2030", color: "#60a5fa", border: "0.5px solid #2a3a50" }}>
            {resuming ? "resuming…" : "Resume"}
          </button>
          <button onClick={onRestart} disabled={resuming || restarting}
            className="text-[10px] px-2.5 py-1 rounded transition-all disabled:opacity-40"
            style={{ background: "#221a10", color: "#fb923c", border: "0.5px solid #3a2a10" }}>
            {restarting ? "restarting…" : "Restart"}
          </button>
        </>)}
      </div>
    </div>
  );
}

// ── Retry panel ───────────────────────────────────────────────────────────────

function RetryPanel({ ep, connectionId, errorMsg }: { ep: ExplorationEpisode; connectionId: string; errorMsg: string }) {
  const [hint, setHint]       = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult]   = useState<RetryQueryResult | null>(null);
  const [open, setOpen]       = useState(false);

  async function handleRetry() {
    setLoading(true); setResult(null);
    try { setResult(await retryQuery(connectionId, ep.sql, errorMsg, hint)); }
    catch (e: unknown) { setResult({ ok: false, corrected_sql: "", explanation: "", rows: [], columns: [], error: String(e) }); }
    finally { setLoading(false); }
  }

  if (!open) return (
    <button onClick={() => setOpen(true)} className="text-[10px] px-2.5 py-1 rounded mt-2"
      style={{ background: "#1a1e2e", color: "#7ba8f7", border: "0.5px solid #2a3050" }}>
      ↺ Retry with fix
    </button>
  );

  return (
    <div className="rounded-md p-3 space-y-2 mt-2" style={{ background: "#0f1018", border: "0.5px solid #2a2b35" }}>
      <p className="text-[9px] uppercase tracking-widest" style={{ color: "#3e3f4a" }}>Guidance (optional)</p>
      <div className="flex gap-2">
        <input type="text" value={hint} onChange={e => setHint(e.target.value)}
          onKeyDown={e => e.key === "Enter" && !loading && handleRetry()}
          placeholder="e.g. use click_ts instead of click_id…"
          className="flex-1 text-[11px] rounded px-2.5 py-1.5 focus:outline-none"
          style={{ background: "#13141a", border: "0.5px solid #2a2b35", color: "#9a9ba4" }} />
        <button onClick={handleRetry} disabled={loading}
          className="text-[10px] px-3 py-1.5 rounded disabled:opacity-40 shrink-0"
          style={{ background: "#1a2030", color: "#60a5fa", border: "0.5px solid #2a3a50" }}>
          {loading ? "fixing…" : "Run fix"}
        </button>
        <button onClick={() => { setOpen(false); setResult(null); }}
          className="text-[10px] px-2 py-1.5 rounded" style={{ color: "#3e3f4a" }}>✕</button>
      </div>
      {result && (
        <div className="space-y-2 pt-1">
          {result.explanation && <p className="text-[11px]" style={{ color: "#7ba8f7" }}>{result.explanation}</p>}
          <pre className="text-[10px] font-mono rounded p-2 overflow-x-auto"
            style={{ background: "#0a0b0e", color: "#5a5b62", whiteSpace: "pre-wrap", wordBreak: "break-all" }}>
            {result.corrected_sql}
          </pre>
          {result.ok ? (
            <div className="overflow-x-auto rounded" style={{ background: "#0a0b0e" }}>
              <table className="text-[10px] font-mono w-full">
                <thead><tr>{result.columns.map(c => (
                  <th key={c} className="px-2 py-1 text-left font-medium"
                    style={{ color: "#4a4b57", borderBottom: "0.5px solid #1e1f24" }}>{c}</th>
                ))}</tr></thead>
                <tbody>{result.rows.slice(0, 15).map((row, i) => (
                  <tr key={i} style={{ borderBottom: "0.5px solid #111115" }}>
                    {row.map((cell, j) => <td key={j} className="px-2 py-1" style={{ color: "#6e6f78" }}>{cell as string}</td>)}
                  </tr>
                ))}</tbody>
              </table>
            </div>
          ) : (
            <pre className="text-[10px] font-mono rounded p-2"
              style={{ background: "#180f0f", color: "#f87171", whiteSpace: "pre-wrap", wordBreak: "break-all" }}>
              {result.error}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}

// ── Expanded row detail ───────────────────────────────────────────────────────

function ExpandedDetail({ ep, connectionId }: { ep: ExplorationEpisode; connectionId: string }) {
  const isError    = ep.observation.startsWith("ERROR:") || ep.observation.startsWith("EXCEPTION:");
  const obsPreview = ep.observation.slice(0, 600) + (ep.observation.length > 600 ? "…" : "");

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12, padding: "12px 4px 8px" }}>
      {/* SQL */}
      <div>
        <p style={{ fontSize: 9, fontFamily: "var(--font-mono)", color: "#2e2f37", textTransform: "uppercase", letterSpacing: "0.07em", marginBottom: 6 }}>SQL</p>
        <pre style={{ fontSize: 10, fontFamily: "var(--font-mono)", color: "#5a5b62", background: "#0a0b0d", border: "0.5px solid #1a1b20", borderRadius: 4, padding: "8px 10px", overflowX: "auto", whiteSpace: "pre-wrap", wordBreak: "break-all", lineHeight: 1.6, margin: 0 }}>
          {ep.sql || "(no sql)"}
        </pre>
      </div>
      {/* Result */}
      <div>
        <p style={{ fontSize: 9, fontFamily: "var(--font-mono)", color: "#2e2f37", textTransform: "uppercase", letterSpacing: "0.07em", marginBottom: 6 }}>Result</p>
        <pre style={{ fontSize: 10, fontFamily: "var(--font-mono)", color: isError ? "#f87171" : "#5a5b62", background: isError ? "#180f0f" : "#0a0b0d", border: `0.5px solid ${isError ? "#3e1a1a" : "#1a1b20"}`, borderRadius: 4, padding: "8px 10px", overflowX: "auto", whiteSpace: "pre-wrap", wordBreak: "break-all", lineHeight: 1.6, margin: 0 }}>
          {obsPreview}
        </pre>
      </div>
      {/* Query intent */}
      {ep.think && (
        <div>
          <p style={{ fontSize: 9, fontFamily: "var(--font-mono)", color: "#2e2f37", textTransform: "uppercase", letterSpacing: "0.07em", marginBottom: 4 }}>Query intent</p>
          <p style={{ fontSize: 11, color: "#4a4b57", lineHeight: 1.55, margin: 0 }}>{ep.think}</p>
        </div>
      )}
      {isError && ep.sql && <RetryPanel ep={ep} connectionId={connectionId} errorMsg={ep.observation} />}
    </div>
  );
}

// ── Sort indicator ────────────────────────────────────────────────────────────

function SortIcon({ active, dir }: { active: boolean; dir: "asc" | "desc" }) {
  if (!active) return <span style={{ marginLeft: 3, opacity: 0.25 }}>⇅</span>;
  return <span style={{ marginLeft: 3, color: "#7ba8f7" }}>{dir === "asc" ? "↑" : "↓"}</span>;
}

// ── Log table ─────────────────────────────────────────────────────────────────

const DEFAULT_LIMIT = 30;

interface LogTableProps {
  items:        WithMeta[];
  connectionId: string;
  sortCol:      SortCol;
  sortDir:      "asc" | "desc";
  onSort:       (col: SortCol) => void;
}

function LogTable({ items, connectionId, sortCol, sortDir, onSort }: LogTableProps) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const toggle = (key: string) =>
    setExpanded(prev => { const n = new Set(prev); n.has(key) ? n.delete(key) : n.add(key); return n; });

  const TH: React.CSSProperties = {
    position: "sticky", top: 0, zIndex: 1,
    background: "#0a0b0d",
    padding: "7px 8px",
    textAlign: "left", fontSize: 9,
    fontFamily: "var(--font-mono)", color: "#3e3f4a",
    textTransform: "uppercase", letterSpacing: "0.07em",
    borderBottom: "1px solid #1e1f24", fontWeight: 500,
    whiteSpace: "nowrap",
    userSelect: "none",
    cursor: "pointer",
  };

  function thClick(col: SortCol) {
    return { style: { ...TH, color: sortCol === col ? "#7ba8f7" : "#3e3f4a" }, onClick: () => onSort(col) };
  }

  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", tableLayout: "fixed" }}>
        <colgroup>
          <col style={{ width: 44 }} />
          <col style={{ width: 148 }} />
          <col style={{ width: 74 }} />
          <col />
          <col style={{ width: 74 }} />
          <col style={{ width: 54 }} />
          <col style={{ width: 120 }} />
          <col style={{ width: 28 }} />
        </colgroup>
        <thead>
          <tr>
            <th {...thClick("seq")} style={{ ...TH, textAlign: "right", paddingRight: 10, color: sortCol === "seq" ? "#7ba8f7" : "#3e3f4a", cursor: "pointer" }}>
              #<SortIcon active={sortCol === "seq"} dir={sortDir} />
            </th>
            <th {...thClick("ts")}>
              timestamp<SortIcon active={sortCol === "ts"} dir={sortDir} />
            </th>
            <th {...thClick("type")}>
              type<SortIcon active={sortCol === "type"} dir={sortDir} />
            </th>
            <th {...thClick("message")}>
              message<SortIcon active={sortCol === "message"} dir={sortDir} />
            </th>
            <th {...thClick("status")}>
              status<SortIcon active={sortCol === "status"} dir={sortDir} />
            </th>
            <th {...thClick("rows")} style={{ ...TH, textAlign: "right", color: sortCol === "rows" ? "#7ba8f7" : "#3e3f4a", cursor: "pointer" }}>
              rows<SortIcon active={sortCol === "rows"} dir={sortDir} />
            </th>
            <th {...thClick("object")}>
              object<SortIcon active={sortCol === "object"} dir={sortDir} />
            </th>
            <th style={{ ...TH, cursor: "default" }} />
          </tr>
        </thead>
        <tbody>
          {items.map((item, idx) => {
            const { ep, meta, seq } = item;
            const pm     = phaseMeta(ep.phase);
            // Stable key: not position-dependent so it survives re-sort
            const ekey   = expandKey(ep);
            // Fragment key must be unique even for duplicate episodes
            const fkey   = `${ekey}|${idx}`;
            const isOpen = expanded.has(ekey);

            return (
              <React.Fragment key={fkey}>
                <tr
                  onClick={() => toggle(ekey)}
                  style={{
                    borderBottom: isOpen ? "none" : "0.5px solid #111115",
                    cursor: "pointer",
                    background: isOpen ? "#0f1014" : "transparent",
                  }}
                  onMouseEnter={e => { if (!isOpen) (e.currentTarget as HTMLTableRowElement).style.background = "#0d0e12"; }}
                  onMouseLeave={e => { if (!isOpen) (e.currentTarget as HTMLTableRowElement).style.background = "transparent"; }}
                >
                  {/* # */}
                  <td style={{ padding: "7px 10px 7px 8px", textAlign: "right", fontSize: 10, fontFamily: "var(--font-mono)", color: "#2e2f37", whiteSpace: "nowrap" }}>
                    {seq}
                  </td>
                  {/* timestamp */}
                  <td style={{ padding: "7px 8px", fontSize: 10, fontFamily: "var(--font-mono)", color: "#4a4b57", whiteSpace: "nowrap" }}>
                    {meta.datetime}
                  </td>
                  {/* type */}
                  <td style={{ padding: "7px 8px" }}>
                    <span style={{ fontSize: 9, padding: "2px 6px", borderRadius: 3, background: pm.bg, color: pm.color, border: `0.5px solid ${pm.color}33` }}>
                      {pm.label}
                    </span>
                  </td>
                  {/* message */}
                  <td style={{ padding: "7px 8px", fontSize: 11, color: meta.isError ? "#f87171" : "#6e6f78", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {meta.message}
                  </td>
                  {/* status */}
                  <td style={{ padding: "7px 8px" }}>
                    <span style={{
                      fontSize: 9, padding: "2px 6px", borderRadius: 3, fontWeight: 500,
                      background: meta.isError ? "#2a1414" : "#13211a",
                      color: meta.isError ? "#f87171" : "#34d399",
                      border: `0.5px solid ${meta.isError ? "#3e2020" : "#1e3028"}`,
                    }}>
                      {meta.isError ? "error" : "success"}
                    </span>
                  </td>
                  {/* rows */}
                  <td style={{ padding: "7px 8px", fontSize: 10, fontFamily: "var(--font-mono)", color: "#4a4b57", textAlign: "right", whiteSpace: "nowrap" }}>
                    {meta.rows !== null ? meta.rows.toLocaleString() : "—"}
                  </td>
                  {/* object */}
                  <td style={{ padding: "7px 8px", fontSize: 10, fontFamily: "var(--font-mono)", color: "#6e6f78", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {meta.object}
                  </td>
                  {/* expand */}
                  <td style={{ padding: "7px 8px", textAlign: "center", fontSize: 9, color: "#2e2f37" }}>
                    {isOpen ? "▲" : "▼"}
                  </td>
                </tr>

                {/* Detail row — always in DOM when open, no conditional to avoid fragment issues */}
                {isOpen && (
                  <tr style={{ background: "#0f1014", borderBottom: "0.5px solid #1a1b20" }}>
                    <td colSpan={8} style={{ padding: "0 16px" }}>
                      <ExpandedDetail ep={ep} connectionId={connectionId} />
                    </td>
                  </tr>
                )}
              </React.Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ── Segmented control ─────────────────────────────────────────────────────────

function Seg<T extends string>({ value, options, onChange }: { value: T; options: { v: T; label: string }[]; onChange: (v: T) => void }) {
  return (
    <div style={{ display: "flex", gap: 1, padding: 2, background: "#0a0b0d", borderRadius: 5, border: "0.5px solid #1a1b20" }}>
      {options.map(o => (
        <button key={o.v} onClick={() => onChange(o.v)} style={{
          fontSize: 10, padding: "3px 9px", borderRadius: 4, cursor: "pointer",
          background: value === o.v ? "#1a1e2e" : "transparent",
          color: value === o.v ? "#7ba8f7" : "#3e3f4a",
          border: value === o.v ? "0.5px solid #2a3050" : "0.5px solid transparent",
          fontWeight: value === o.v ? 500 : 400,
          transition: "all .1s",
        }}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

// ── Main panel ────────────────────────────────────────────────────────────────

interface Props {
  connectionId: string;
  isActive:     boolean;
}

export function ActivityLog({ connectionId, isActive }: Props) {
  const [episodes, setEpisodes]   = useState<ExplorationEpisode[]>([]);
  const [status, setStatus]       = useState<ExplorationStatus | null>(null);
  const [stopped, setStopped]     = useState(false);
  const [stopping, setStopping]   = useState(false);
  const [resuming, setResuming]   = useState(false);
  const [restarting, setRestarting] = useState(false);
  const [filterDate, setFilterDate]     = useState<DateFilter>("all");
  const [filterStatus, setFilterStatus] = useState<StatusFilter>("all");
  const [showAll, setShowAll]           = useState(false);
  const [sortCol, setSortCol]   = useState<SortCol>("ts");
  const [sortDir, setSortDir]   = useState<"asc" | "desc">("desc");
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!isActive) return;
    let cancelled = false;
    const load = async () => {
      try {
        const [eps, st] = await Promise.all([
          getExplorationEpisodes(connectionId, "", 1000),
          getExplorationStatus(connectionId).catch(() => null),
        ]);
        if (!cancelled) { setEpisodes(eps); setStatus(st); if (st?.paused) setStopped(true); }
      } catch { /* next poll retries */ }
    };
    load();
    const t = setInterval(load, 5_000);
    return () => { cancelled = true; clearInterval(t); };
  }, [connectionId, isActive]);

  function handleSort(col: SortCol) {
    if (col === sortCol) setSortDir(d => d === "asc" ? "desc" : "asc");
    else { setSortCol(col); setSortDir(col === "ts" ? "desc" : "asc"); }
  }

  async function handleStop()    { setStopping(true);   try { await stopExploration(connectionId);    setStopped(true);  } finally { setStopping(false);   } }
  async function handleResume()  { setResuming(true);   try { await resumeExploration(connectionId);  setStopped(false); } finally { setResuming(false);   } }
  async function handleRestart() { setRestarting(true); try { await restartExploration(connectionId); setStopped(false); setEpisodes([]); } finally { setRestarting(false); } }

  // Build withMeta (preserve original seq)
  const withMeta: WithMeta[] = episodes.map((ep, i) => ({
    ep, meta: deriveRowMeta(ep), seq: i + 1,
  }));

  // Filter
  const filtered = withMeta.filter(({ meta }) => {
    if (filterStatus !== "all" && meta.status !== filterStatus) return false;
    if (!passesDateFilter(meta.date, filterDate)) return false;
    return true;
  });

  // Sort
  const sorted = sortItems(filtered, sortCol, sortDir);

  // Slice
  const displayed = showAll ? sorted : sorted.slice(0, DEFAULT_LIMIT);

  const isRunning  = status && !["complete", "failed", "pending"].includes(status.phase);
  const errorCount = filtered.filter(({ meta }) => meta.isError).length;

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

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <StatusBar status={status} stopped={stopped} onStop={handleStop} onResume={handleResume} onRestart={handleRestart} stopping={stopping} resuming={resuming} restarting={restarting} />

      {/* Filter + controls bar */}
      <div className="flex items-center gap-2.5 px-4 py-2 border-b shrink-0 flex-wrap"
        style={{ borderColor: "#1a1b20", background: "#0d0e11" }}>
        <Seg<DateFilter>
          value={filterDate} onChange={setFilterDate}
          options={[
            { v: "all",       label: "All dates"  },
            { v: "today",     label: "Today"      },
            { v: "yesterday", label: "Yesterday"  },
            { v: "week",      label: "This week"  },
          ]}
        />
        <Seg<StatusFilter>
          value={filterStatus} onChange={setFilterStatus}
          options={[
            { v: "all",     label: "All"     },
            { v: "success", label: "Success" },
            { v: "error",   label: "Error"   },
          ]}
        />
        <div style={{ flex: 1 }} />
        {errorCount > 0 && (
          <span style={{ fontSize: 10, padding: "2px 7px", borderRadius: 4, background: "#2a1414", color: "#f87171", border: "0.5px solid #3e2020" }}>
            {errorCount} error{errorCount !== 1 ? "s" : ""}
          </span>
        )}
        <span className="text-[10px]" style={{ color: "#3e3f4a" }}>
          {showAll ? `${filtered.length}` : `${Math.min(DEFAULT_LIMIT, filtered.length)} of ${filtered.length}`}
          {isRunning && <span className="ml-2 animate-pulse" style={{ color: "#4a4b57" }}>● live</span>}
        </span>
        {filtered.length > DEFAULT_LIMIT && (
          <button onClick={() => setShowAll(v => !v)} style={{
            fontSize: 10, padding: "3px 8px", borderRadius: 4, cursor: "pointer",
            background: showAll ? "#1a2030" : "#13141a",
            color: showAll ? "#60a5fa" : "#5a5b62",
            border: `0.5px solid ${showAll ? "#2a3a50" : "#1e1f24"}`,
          }}>
            {showAll ? "Show less" : `Show all ${filtered.length}`}
          </button>
        )}
      </div>

      {/* Table */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto" style={{ background: "#0d0e11" }}>
        {displayed.length === 0 ? (
          <div className="flex items-center justify-center h-32 text-[11px]" style={{ color: "#3e3f4a" }}>
            No entries match the current filters.
          </div>
        ) : (
          <LogTable
            items={displayed}
            connectionId={connectionId}
            sortCol={sortCol}
            sortDir={sortDir}
            onSort={handleSort}
          />
        )}
      </div>
    </div>
  );
}
