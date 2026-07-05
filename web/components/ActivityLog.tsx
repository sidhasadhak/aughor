"use client";

import React, { useEffect, useRef, useState } from "react";
import {
  getExplorationEpisodes,
  getExplorationStatus,
  stopExploration,
  resumeExploration,
  restartExploration,
  retryQuery,
  getCanvasExplorationEpisodes,
  getCanvasExplorationStatus,
  stopCanvasExploration,
  resumeCanvasExploration,
  restartCanvasExploration,
  fixEpisode,
  fixAll,
  type ExplorationEpisode,
  type ExplorationStatus,
  type RetryQueryResult,
  type FixSaveResult,
  type FixAllResult,
} from "@/lib/api";
import { subscribeKernelEvents } from "@/lib/events";
import { formatCount } from "@/lib/format";

// ── Phase metadata ────────────────────────────────────────────────────────────

// Token-driven (no raw hex): hardcoded dark-theme values made these chips —
// and most of this table — unreadable in light mode and the # column nearly
// invisible everywhere.
const PHASE_META: Record<string, { label: string; color: string; bg: string }> = {
  exploration:       { label: "schema",    color: "var(--t2)",    bg: "var(--bg-3)" },
  null_meaning:      { label: "nulls",     color: "var(--blue4)", bg: "var(--blue1)" },
  join_verification: { label: "joins",     color: "var(--amb4)",  bg: "var(--amb1)" },
  lifecycle_mapping: { label: "lifecycle", color: "var(--grn4)",  bg: "var(--grn1)" },
  distribution:      { label: "dist",      color: "var(--vio4)",  bg: "var(--vio1)" },
  cross_table:       { label: "patterns",  color: "var(--red4)",  bg: "var(--red1)" },
  domain_intel:      { label: "intel",     color: "var(--blue4)", bg: "var(--blue1)" },
  // Chat-initiated query types
  ask:               { label: "quick",     color: "var(--t2)",    bg: "var(--bg-3)" },
  investigate:       { label: "agentic",   color: "var(--vio4)",  bg: "var(--vio1)" },
};

function phaseMeta(phase: string) {
  return PHASE_META[phase] ?? { label: phase, color: "var(--t3)", bg: "var(--bg-3)" };
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
    <div className="flex items-center gap-3 px-4 py-2 border-b shrink-0" style={{ borderColor: "var(--b2)", background: "var(--bg-0)" }}>
      <span className="flex items-center gap-1.5 aug-fs-xs px-2 py-0.5 rounded font-medium"
        style={isStopped && !isRunning ? { background: "var(--bg-3)", color: "var(--t3)" } : { background: meta.bg, color: meta.color }}>
        {isRunning && <span className="inline-block w-1.5 h-1.5 rounded-[var(--r-pill)] animate-pulse" style={{ background: meta.color }} />}
        {isStopped && !isRunning ? "stopped" : status.phase === "complete" ? "complete" : status.phase === "pending" ? "idle" : meta.label}
      </span>
      <span className="aug-fs-xs" style={{ color: "var(--t4)" }}>
        {status.queries_executed > 0 && `${status.queries_executed} queries`}
        {status.facts_discovered > 0 && ` · ${status.facts_discovered} facts`}
        {status.insights_found    > 0 && ` · ${status.insights_found} insights`}
      </span>
      <div className="ml-auto flex items-center gap-2">
        <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>
          {status.tables_total > 0 && `${status.tables_total} tables · ${status.joins_total} joins`}
        </span>
        {isRunning && (
          <button onClick={onStop} disabled={stopping}
            className="flex items-center gap-1 aug-fs-xs px-2.5 py-1 rounded transition-all disabled:opacity-40"
            style={{ background: "var(--red1)", color: "var(--red4)", border: "0.5px solid var(--red2)" }}>
            <span className="w-2 h-2 rounded-sm inline-block" style={{ background: "var(--red4)" }} />
            {stopping ? "stopping…" : "Stop"}
          </button>
        )}
        {isStopped && !isRunning && (<>
          <button onClick={onResume} disabled={resuming || restarting}
            className="aug-fs-xs px-2.5 py-1 rounded transition-all disabled:opacity-40"
            style={{ background: "var(--blue1)", color: "var(--blue4)", border: "0.5px solid var(--blue2)" }}>
            {resuming ? "resuming…" : "Resume"}
          </button>
          <button onClick={onRestart} disabled={resuming || restarting}
            className="aug-fs-xs px-2.5 py-1 rounded transition-all disabled:opacity-40"
            style={{ background: "var(--amb1)", color: "var(--amb4)", border: "0.5px solid var(--amb2)" }}>
            {restarting ? "restarting…" : "Restart"}
          </button>
        </>)}
      </div>
    </div>
  );
}

// ── Retry panel ───────────────────────────────────────────────────────────────

function RetryPanel({ ep, connectionId, errorMsg, canvasId }: { ep: ExplorationEpisode; connectionId: string; errorMsg: string; canvasId?: string }) {
  const [hint, setHint]       = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult]   = useState<RetryQueryResult | null>(null);
  const [open, setOpen]       = useState(false);
  const [saving, setSaving]   = useState(false);
  const [saved, setSaved]     = useState<FixSaveResult | null>(null);

  async function handleRetry() {
    setLoading(true); setResult(null); setSaved(null);
    try { setResult(await retryQuery(connectionId, ep.sql, errorMsg, hint)); }
    catch (e: unknown) { setResult({ ok: false, corrected_sql: "", explanation: "", rows: [], columns: [], error: String(e) }); }
    finally { setLoading(false); }
  }

  async function handleSave() {
    setSaving(true);
    try {
      setSaved(await fixEpisode(connectionId, { sql: ep.sql, error: errorMsg, think: ep.think, phase: ep.phase }, hint, canvasId ?? ""));
    } catch (e: unknown) {
      setSaved({ ok: false, stored: false, corrected_sql: "", error: String(e) });
    } finally { setSaving(false); }
  }

  if (!open) return (
    <button onClick={() => setOpen(true)} className="aug-fs-xs px-2.5 py-1 rounded mt-2"
      style={{ background: "var(--blue1)", color: "var(--blue4)", border: "0.5px solid var(--blue2)" }}>
      ↺ Retry with fix
    </button>
  );

  return (
    <div className="rounded-md p-3 space-y-2 mt-2" style={{ background: "var(--bg-0)", border: "0.5px solid var(--b2)" }}>
      <p className="aug-fs-xs uppercase tracking-widest" style={{ color: "var(--t4)" }}>Guidance (optional)</p>
      <div className="flex gap-2">
        <input type="text" value={hint} onChange={e => setHint(e.target.value)}
          onKeyDown={e => e.key === "Enter" && !loading && handleRetry()}
          placeholder="e.g. use click_ts instead of click_id…"
          className="flex-1 aug-fs-xs rounded px-2.5 py-1.5 focus:outline-none"
          style={{ background: "var(--bg-1)", border: "0.5px solid var(--b2)", color: "var(--t2)" }} />
        <button onClick={handleRetry} disabled={loading}
          className="aug-fs-xs px-3 py-1.5 rounded disabled:opacity-40 shrink-0"
          style={{ background: "var(--blue1)", color: "var(--blue4)", border: "0.5px solid var(--blue2)" }}>
          {loading ? "fixing…" : "Run fix"}
        </button>
        <button onClick={() => { setOpen(false); setResult(null); }}
          className="aug-fs-xs px-2 py-1.5 rounded" style={{ color: "var(--t4)" }}>✕</button>
      </div>
      {result && (
        <div className="space-y-2 pt-1">
          {result.explanation && <p className="aug-fs-xs" style={{ color: "var(--blue4)" }}>{result.explanation}</p>}
          <pre className="aug-fs-xs font-code rounded p-2 overflow-x-auto"
            style={{ background: "var(--code-bg)", color: "var(--t3)", whiteSpace: "pre-wrap", wordBreak: "break-all" }}>
            {result.corrected_sql}
          </pre>
          {result.ok ? (
            <>
              <div className="overflow-x-auto rounded" style={{ background: "var(--code-bg)" }}>
                <table className="aug-fs-xs font-mono w-full">
                  <thead><tr>{result.columns.map(c => (
                    <th key={c} className="px-2 py-1 text-left font-medium"
                      style={{ color: "var(--t3)", borderBottom: "0.5px solid var(--b2)" }}>{c}</th>
                  ))}</tr></thead>
                  <tbody>{result.rows.slice(0, 15).map((row, i) => (
                    <tr key={i} style={{ borderBottom: "0.5px solid var(--b0)" }}>
                      {row.map((cell, j) => <td key={j} className="px-2 py-1" style={{ color: "var(--t3)" }}>{cell as string}</td>)}
                    </tr>
                  ))}</tbody>
                </table>
              </div>
              {/* Save the successful fix as a finding (through the Phase-8 guards) */}
              {!saved ? (
                <button onClick={handleSave} disabled={saving}
                  className="aug-fs-xs px-3 py-1.5 rounded disabled:opacity-40"
                  style={{ background: "var(--grn1)", color: "var(--grn4)", border: "0.5px solid var(--grn2)" }}>
                  {saving ? "saving…" : "Save as finding"}
                </button>
              ) : (
                <SaveFeedback saved={saved} />
              )}
            </>
          ) : (
            <pre className="aug-fs-xs font-code rounded p-2"
              style={{ background: "var(--red1)", color: "var(--red4)", whiteSpace: "pre-wrap", wordBreak: "break-all" }}>
              {result.error}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}

// ── Save-as-finding feedback ──────────────────────────────────────────────────

function SaveFeedback({ saved }: { saved: FixSaveResult }) {
  let tone = { bg: "var(--grn1)", fg: "var(--grn4)", bd: "var(--grn2)" };  // saved clean
  let text = "✓ Saved as finding";
  if (!saved.ok) { tone = { bg: "var(--red1)", fg: "var(--red4)", bd: "var(--red2)" }; text = `✕ ${saved.error ?? "save failed"}`; }
  else if (saved.stored && saved.insight?.unverified) {
    tone = { bg: "var(--amb1)", fg: "var(--amb4)", bd: "var(--amb2)" };
    text = `⚠ Saved as unverified — ${saved.insight.verification_note}`;
  } else if (!saved.stored) {
    tone = { bg: "var(--blue1)", fg: "var(--blue4)", bd: "var(--blue2)" };
    text = `✓ Query fixed — ${saved.reason ?? "no finding stored"}`;
  }
  return (
    <p className="aug-fs-xs px-2.5 py-1.5 rounded" style={{ background: tone.bg, color: tone.fg, border: `0.5px solid ${tone.bd}` }}>
      {text}
    </p>
  );
}

// ── Expanded row detail ───────────────────────────────────────────────────────

function ExpandedDetail({ ep, connectionId, canvasId }: { ep: ExplorationEpisode; connectionId: string; canvasId?: string }) {
  const isError    = ep.observation.startsWith("ERROR:") || ep.observation.startsWith("EXCEPTION:");
  const obsPreview = ep.observation.slice(0, 600) + (ep.observation.length > 600 ? "…" : "");

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12, padding: "12px 4px 8px" }}>
      {/* SQL */}
      <div>
        <p style={{ fontSize: 9, fontFamily: "var(--font-mono)", color: "var(--t4)", textTransform: "uppercase", letterSpacing: "0.07em", marginBottom: 6 }}>SQL</p>
        <pre style={{ fontSize: 10, fontFamily: "var(--font-code)", color: "var(--t3)", background: "var(--bg-0)", border: "0.5px solid var(--b1)", borderRadius: 4, padding: "8px 10px", overflowX: "auto", whiteSpace: "pre-wrap", wordBreak: "break-all", lineHeight: 1.6, margin: 0 }}>
          {ep.sql || "(no sql)"}
        </pre>
      </div>
      {/* Result */}
      <div>
        <p style={{ fontSize: 9, fontFamily: "var(--font-mono)", color: "var(--t4)", textTransform: "uppercase", letterSpacing: "0.07em", marginBottom: 6 }}>Result</p>
        <pre style={{ fontSize: 10, fontFamily: "var(--font-code)", color: isError ? "var(--red4)" : "var(--t3)", background: isError ? "var(--red1)" : "var(--code-bg)", border: `0.5px solid ${isError ? "var(--red2)" : "var(--b1)"}`, borderRadius: 4, padding: "8px 10px", overflowX: "auto", whiteSpace: "pre-wrap", wordBreak: "break-all", lineHeight: 1.6, margin: 0 }}>
          {obsPreview}
        </pre>
      </div>
      {/* Query intent */}
      {ep.think && (
        <div>
          <p style={{ fontSize: 9, fontFamily: "var(--font-mono)", color: "var(--t4)", textTransform: "uppercase", letterSpacing: "0.07em", marginBottom: 4 }}>Query intent</p>
          <p style={{ fontSize: 11, color: "var(--t3)", lineHeight: 1.55, margin: 0 }}>{ep.think}</p>
        </div>
      )}
      {isError && ep.sql && <RetryPanel ep={ep} connectionId={connectionId} errorMsg={ep.observation} canvasId={canvasId} />}
    </div>
  );
}

// ── Sort indicator ────────────────────────────────────────────────────────────

function SortIcon({ active, dir }: { active: boolean; dir: "asc" | "desc" }) {
  if (!active) return <span style={{ marginLeft: 3, opacity: 0.25 }}>⇅</span>;
  return <span style={{ marginLeft: 3, color: "var(--blue4)" }}>{dir === "asc" ? "↑" : "↓"}</span>;
}

// ── Log table ─────────────────────────────────────────────────────────────────

const DEFAULT_LIMIT = 30;

interface LogTableProps {
  items:        WithMeta[];
  connectionId: string;
  canvasId?:    string;
  sortCol:      SortCol;
  sortDir:      "asc" | "desc";
  onSort:       (col: SortCol) => void;
}

function LogTable({ items, connectionId, canvasId, sortCol, sortDir, onSort }: LogTableProps) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const toggle = (key: string) =>
    setExpanded(prev => { const n = new Set(prev); n.has(key) ? n.delete(key) : n.add(key); return n; });

  const TH: React.CSSProperties = {
    position: "sticky", top: 0, zIndex: 1,
    background: "var(--bg-0)",
    padding: "7px 8px",
    textAlign: "left", fontSize: 9,
    fontFamily: "var(--font-mono)", color: "var(--t4)",
    textTransform: "uppercase", letterSpacing: "0.07em",
    borderBottom: "1px solid var(--b2)", fontWeight: 500,
    whiteSpace: "nowrap",
    userSelect: "none",
    cursor: "pointer",
  };

  function thClick(col: SortCol) {
    return { style: { ...TH, color: sortCol === col ? "var(--blue4)" : "var(--t4)" }, onClick: () => onSort(col) };
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
            <th {...thClick("seq")} style={{ ...TH, textAlign: "right", paddingRight: 10, color: sortCol === "seq" ? "var(--blue4)" : "var(--t4)", cursor: "pointer" }}>
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
            <th {...thClick("rows")} style={{ ...TH, textAlign: "right", color: sortCol === "rows" ? "var(--blue4)" : "var(--t4)", cursor: "pointer" }}>
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
                    borderBottom: isOpen ? "none" : "0.5px solid var(--b0)",
                    cursor: "pointer",
                    background: isOpen ? "var(--bg-2)" : "transparent",
                  }}
                  onMouseEnter={e => { if (!isOpen) (e.currentTarget as HTMLTableRowElement).style.background = "var(--bg-3)"; }}
                  onMouseLeave={e => { if (!isOpen) (e.currentTarget as HTMLTableRowElement).style.background = "transparent"; }}
                >
                  {/* # — var(--b0) was a BORDER token used as text: near-invisible */}
                  <td style={{ padding: "7px 10px 7px 8px", textAlign: "right", fontSize: 10, fontFamily: "var(--font-mono)", color: "var(--t3)", whiteSpace: "nowrap" }}>
                    {seq}
                  </td>
                  {/* timestamp */}
                  <td style={{ padding: "7px 8px", fontSize: 10, fontFamily: "var(--font-mono)", color: "var(--t3)", whiteSpace: "nowrap" }}>
                    {meta.datetime}
                  </td>
                  {/* type */}
                  <td style={{ padding: "7px 8px" }}>
                    <span style={{ fontSize: 9, padding: "2px 6px", borderRadius: 3, background: pm.bg, color: pm.color, border: `0.5px solid color-mix(in srgb, ${pm.color} 25%, transparent)` }}>
                      {pm.label}
                    </span>
                  </td>
                  {/* message */}
                  <td style={{ padding: "7px 8px", fontSize: 11, color: meta.isError ? "var(--red4)" : "var(--t3)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {meta.message}
                  </td>
                  {/* status */}
                  <td style={{ padding: "7px 8px" }}>
                    <span style={{
                      fontSize: 9, padding: "2px 6px", borderRadius: 3, fontWeight: 500,
                      background: meta.isError ? "var(--red1)" : "var(--grn1)",
                      color: meta.isError ? "var(--red4)" : "var(--grn4)",
                      border: `0.5px solid ${meta.isError ? "var(--red2)" : "var(--grn2)"}`,
                    }}>
                      {meta.isError ? "error" : "success"}
                    </span>
                  </td>
                  {/* rows */}
                  <td style={{ padding: "7px 8px", fontSize: 10, fontFamily: "var(--font-mono)", color: "var(--t3)", textAlign: "right", whiteSpace: "nowrap" }}>
                    {formatCount(meta.rows)}
                  </td>
                  {/* object */}
                  <td style={{ padding: "7px 8px", fontSize: 10, fontFamily: "var(--font-mono)", color: "var(--t3)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {meta.object}
                  </td>
                  {/* expand */}
                  <td style={{ padding: "7px 8px", textAlign: "center", fontSize: 9, color: "var(--t4)" }}>
                    {isOpen ? "▲" : "▼"}
                  </td>
                </tr>

                {/* Detail row — always in DOM when open, no conditional to avoid fragment issues */}
                {isOpen && (
                  <tr style={{ background: "var(--bg-2)", borderBottom: "0.5px solid var(--b1)" }}>
                    <td colSpan={8} style={{ padding: "0 16px" }}>
                      <ExpandedDetail ep={ep} connectionId={connectionId} canvasId={canvasId} />
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
    <div style={{ display: "flex", gap: 1, padding: 2, background: "var(--bg-0)", borderRadius: 5, border: "0.5px solid var(--b1)" }}>
      {options.map(o => (
        <button key={o.v} onClick={() => onChange(o.v)} style={{
          fontSize: 10, padding: "3px 9px", borderRadius: 4, cursor: "pointer",
          background: value === o.v ? "var(--blue1)" : "transparent",
          color: value === o.v ? "var(--blue4)" : "var(--t4)",
          border: value === o.v ? "0.5px solid var(--blue2)" : "0.5px solid transparent",
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
  canvasId?:    string;
}

export function ActivityLog({ connectionId, isActive, canvasId }: Props) {
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
  const [fixingAll, setFixingAll]       = useState(false);
  const [fixAllSummary, setFixAllSummary] = useState<FixAllResult["summary"] | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!isActive) return;
    let cancelled = false;
    const load = async () => {
      try {
        const [eps, st] = canvasId
          ? await Promise.all([
              getCanvasExplorationEpisodes(canvasId, "", 1000),
              getCanvasExplorationStatus(canvasId).catch(() => null),
            ])
          : await Promise.all([
              getExplorationEpisodes(connectionId, "", 1000),
              getExplorationStatus(connectionId).catch(() => null),
            ]);
        if (!cancelled) { setEpisodes(eps); setStatus(st); if (st?.paused) setStopped(true); }
      } catch { /* next poll retries */ }
    };
    load();
    // K2: kernel events drive refresh; the interval is only a slow fallback.
    const t = setInterval(load, 60_000);
    const unsub = subscribeKernelEvents(() => load(), {
      kinds: ["exploration."], connId: connectionId, canvasId: canvasId || undefined,
    });
    return () => { cancelled = true; clearInterval(t); unsub(); };
  }, [connectionId, canvasId, isActive]);

  function handleSort(col: SortCol) {
    if (col === sortCol) setSortDir(d => d === "asc" ? "desc" : "asc");
    else { setSortCol(col); setSortDir(col === "ts" ? "desc" : "asc"); }
  }

  async function handleStop() {
    setStopping(true);
    try {
      if (canvasId) await stopCanvasExploration(canvasId);
      else await stopExploration(connectionId);
      setStopped(true);
    } finally { setStopping(false); }
  }
  async function handleResume() {
    setResuming(true);
    try {
      if (canvasId) await resumeCanvasExploration(canvasId);
      else await resumeExploration(connectionId);
      setStopped(false);
    } finally { setResuming(false); }
  }
  async function handleRestart() {
    setRestarting(true);
    try {
      if (canvasId) await restartCanvasExploration(canvasId);
      else await restartExploration(connectionId);
      setStopped(false); setEpisodes([]);
    } finally { setRestarting(false); }
  }

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

  // Fix-all: repair ONLY the errored episodes currently visible under the filter. The
  // client passes exactly that set, so the server never re-derives "all errors" or
  // generates fresh queries — a date filter (e.g. "Yesterday") naturally scopes the batch.
  async function handleFixAll() {
    const errs = filtered.filter(({ meta }) => meta.isError).map(({ ep }) => ep);
    if (errs.length === 0 || fixingAll) return;
    setFixingAll(true); setFixAllSummary(null);
    try {
      const r = await fixAll(
        connectionId,
        errs.map(ep => ({ sql: ep.sql, error: ep.observation, think: ep.think, phase: ep.phase })),
        "", canvasId ?? "",
      );
      setFixAllSummary(r.summary);
    } catch { /* surfaced by the unchanged error rows on next poll */ }
    finally { setFixingAll(false); }
  }

  if (episodes.length === 0) {
    return (
      <div className="h-full flex flex-col">
        <StatusBar status={status} stopped={stopped} onStop={handleStop} onResume={handleResume} onRestart={handleRestart} stopping={stopping} resuming={resuming} restarting={restarting} />
        <div className="flex-1 flex flex-col items-center justify-center gap-2" style={{ color: "var(--t4)" }}>
          <p className="aug-fs-sm">No activity recorded yet.</p>
          <p className="aug-fs-xs" style={{ color: "var(--t4)" }}>Activity appears here as background exploration runs.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <StatusBar status={status} stopped={stopped} onStop={handleStop} onResume={handleResume} onRestart={handleRestart} stopping={stopping} resuming={resuming} restarting={restarting} />

      {/* Filter + controls bar */}
      <div className="flex items-center gap-2.5 px-4 py-2 border-b shrink-0 flex-wrap"
        style={{ borderColor: "var(--b1)", background: "var(--bg-0)" }}>
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
          <span style={{ fontSize: 10, padding: "2px 7px", borderRadius: 4, background: "var(--red1)", color: "var(--red4)", border: "0.5px solid var(--red2)" }}>
            {errorCount} error{errorCount !== 1 ? "s" : ""}
          </span>
        )}
        {errorCount > 0 && (
          <button onClick={handleFixAll} disabled={fixingAll}
            title={`Repair the ${errorCount} errored quer${errorCount !== 1 ? "ies" : "y"} visible under the current filter`}
            style={{
              fontSize: 10, padding: "3px 9px", borderRadius: 4, cursor: "pointer",
              background: "var(--amb1)", color: "var(--amb4)", border: "0.5px solid var(--amb2)",
              opacity: fixingAll ? 0.5 : 1,
            }}>
            {fixingAll ? "fixing…" : `Fix all (${errorCount})`}
          </button>
        )}
        {fixAllSummary && (
          <span style={{ fontSize: 10, color: "var(--t4)" }}>
            fixed {fixAllSummary.fixed}/{fixAllSummary.total} · saved {fixAllSummary.saved}
            {fixAllSummary.flagged > 0 && ` (${fixAllSummary.flagged} flagged)`}
            {fixAllSummary.failed > 0 && ` · ${fixAllSummary.failed} still failing`}
          </span>
        )}
        <span className="aug-fs-xs" style={{ color: "var(--t4)" }}>
          {showAll ? `${filtered.length}` : `${Math.min(DEFAULT_LIMIT, filtered.length)} of ${filtered.length}`}
          {isRunning && <span className="ml-2 animate-pulse" style={{ color: "var(--t3)" }}>● live</span>}
        </span>
        {filtered.length > DEFAULT_LIMIT && (
          <button onClick={() => setShowAll(v => !v)} style={{
            fontSize: 10, padding: "3px 8px", borderRadius: 4, cursor: "pointer",
            background: showAll ? "var(--blue1)" : "var(--bg-1)",
            color: showAll ? "var(--blue4)" : "var(--t3)",
            border: `0.5px solid ${showAll ? "var(--blue2)" : "var(--bg-3)"}`,
          }}>
            {showAll ? "Show less" : `Show all ${filtered.length}`}
          </button>
        )}
      </div>

      {/* Table */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto" style={{ background: "var(--bg-0)" }}>
        {displayed.length === 0 ? (
          <div className="flex items-center justify-center h-32 aug-fs-xs" style={{ color: "var(--t4)" }}>
            No entries match the current filters.
          </div>
        ) : (
          <LogTable
            items={displayed}
            connectionId={connectionId}
            canvasId={canvasId}
            sortCol={sortCol}
            sortDir={sortDir}
            onSort={handleSort}
          />
        )}
      </div>
    </div>
  );
}
