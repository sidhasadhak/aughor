"use client";

import React, { useEffect, useRef, useState } from "react";
import { useOpenInBuilder } from "@/lib/openInBuilder";
import { SqlResultTable } from "@/components/AugTable";
import { ExportButton } from "@/components/ExportButton";
import TableIcon         from "@atlaskit/icon/core/table";
import DownloadIcon      from "@atlaskit/icon/core/download";
import CloseIcon         from "@atlaskit/icon/core/close";
import CopyIcon          from "@atlaskit/icon/core/copy";
import CheckMarkIcon     from "@atlaskit/icon/core/check-mark";
import ChevronDownIcon   from "@atlaskit/icon/core/chevron-down";
import AngleBracketsIcon from "@atlaskit/icon/core/angle-brackets";
import InformationIcon   from "@atlaskit/icon/core/information";
import WarningIcon       from "@atlaskit/icon/core/warning";
import ArrowRightIcon    from "@atlaskit/icon/core/arrow-right";
import {
  Brief,
  BriefHeadline,
  BriefProse,
  BriefBullets,
  BriefMetrics,
  BriefFigure,
  BriefDetails,
  BriefDetailBlock,
  BriefSection,
  BriefMeta,
  type BriefMetric,
} from "@/components/brief/Brief";
import { ChatTurn } from "@/lib/useChat";
import { validateQuery, sendChatFeedback, proposeLearnedSkill, saveLearnedSkill, type QueryValidation } from "@/lib/api";
import { InvestigationReportView } from "@/components/InvestigationReport";
import { ExplorationReportView } from "@/components/ExplorationReport";
import { DossierTrace } from "@/components/BriefingPanel";
import type { FindingDossier } from "@/lib/api";
import { ThinkingTrace, turnToTraceState } from "@/components/ThinkingTrace";
import { ContextRibbon } from "@/components/ContextRibbon";
import { PlanGateCard } from "@/components/PlanGateCard";
import { deletePlaybookEntry, editPlaybookRecommendation, type PlaybookRef } from "@/lib/api";
import {
  type Gran,
  granFromName,
  detectGranularity,
  fmtDate,
  cleanLabel,
  compactNumber,
  formatPercent,
  formatCount,
  GRAN_WORD,
} from "@/lib/format";
import { Chart } from "@/components/Chart";
import { ResultChartCard } from "@/components/charts/ResultChartCard";
import {
  DATE_COL,
  SHARE_COL,
  ORDINAL_COL,
  DATE_VALUE_RE,
  isNumeric,
  firstNonNull,
} from "@/components/charts/columnRoles";
import { isAdditiveMeasure } from "@/lib/measureKind";

// Format a wall-clock duration for the "Completed in …" line.
function formatElapsed(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)}s`;
  const m = Math.floor(s / 60);
  return `${m}m ${Math.round(s - m * 60)}s`;
}

// ── Public types (re-imported by ChatPanel) ───────────────────────────────────
export interface SourcePanelData {
  columns: string[];
  rows: unknown[][];        // already sorted for display
  sql: string | null;
  title: string;
}

// Column-role classification (DATE_COL / SHARE_COL / ORDINAL_COL / isNumeric /
// firstNonNull / …) now lives in @/components/charts/columnRoles (imported above),
// shared with the extracted <Chart> component.

// Date normalization, granularity detection, date/label formatting, and the
// Gran type now live in @/lib/format (imported above) — the single formatting home.

// ── Smart source-panel title derived from column semantics ────────────────────
function inferSourceTitle(columns: string[], rows: unknown[][]): string {
  if (!columns.length) return "Query result";

  const dateColIdx = columns.findIndex((c, i) => {
    const v = rows[0]?.[i];
    return DATE_COL.test(c) || (typeof v === "string" && DATE_VALUE_RE.test(v as string));
  });
  const numColNames = columns.filter((c, i) =>  isNumeric(firstNonNull(rows, i)) && !ORDINAL_COL.test(c));
  const catColNames = columns.filter((c, i) => !isNumeric(firstNonNull(rows, i)) && i !== dateColIdx && !DATE_COL.test(c));

  const measure = numColNames[0] ? cleanLabel(numColNames[0]) : "";
  const dim     = catColNames[0] ? cleanLabel(catColNames[0]) : "";
  const hasDate = dateColIdx >= 0;
  // Use the actual time grain ("Weekly"/"Daily"/…) instead of assuming monthly.
  const grainWord = hasDate
    ? GRAN_WORD[detectGranularity(columns[dateColIdx], rows.map(r => (r as unknown[])[dateColIdx]))]
    : "";

  if (measure && dim && hasDate) return `${grainWord} ${measure} by ${dim}`;
  if (measure && dim)            return `${measure} by ${dim}`;
  if (measure && hasDate)        return `${grainWord} ${measure}`;
  if (measure)                   return measure;
  if (dim)                       return dim;
  return "Query result";
}

// ── Sort rows: date dims first (ISO-sort = chronological), then text dims A→Z ─
function sortRowsForDisplay(columns: string[], rows: unknown[][]): unknown[][] {
  const dimIdxs = columns
    .map((_, i) => i)
    .filter(i => !isNumeric(firstNonNull(rows, i)));
  if (!dimIdxs.length) return rows;

  return [...rows].sort((a, b) => {
    for (const i of dimIdxs) {
      const va = String((a as unknown[])[i] ?? "");
      const vb = String((b as unknown[])[i] ?? "");
      const cmp = va < vb ? -1 : va > vb ? 1 : 0;
      if (cmp !== 0) return cmp;
    }
    return 0;
  });
}

// ── CSV download helper ───────────────────────────────────────────────────────
function downloadCsv(columns: string[], rows: unknown[][], title: string) {
  const esc = (v: unknown) => {
    const s = String(v ?? "");
    return /[,"\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const csv = [
    columns.map(esc).join(","),
    ...rows.map(r => (r as unknown[]).map(esc).join(",")),
  ].join("\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const url  = URL.createObjectURL(blob);
  const a    = Object.assign(document.createElement("a"), {
    href: url,
    download: `${title.replace(/[^a-z0-9]+/gi, "_").toLowerCase()}.csv`,
  });
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function fmt(col: string, val: unknown, gran?: Gran): string {
  if (val === null || val === "NULL") return "—";
  const s = String(val);
  // Format a date at its true granularity (week→"Jan 5", month→"Jan 2026", …).
  // `gran` is passed when the caller has the whole column (spacing-detected);
  // otherwise fall back to the column name.
  if (/^\d{4}-\d{2}-\d{2}/.test(s)) return fmtDate(s, gran ?? granFromName(col) ?? "day");
  if (ORDINAL_COL.test(col)) return s;
  const n = Number(val);
  if (!isNaN(n)) {
    // Route through the ONE formatter (REC-U8) — no more hand-rolled k/M/%: a
    // share column reads as a percent (ratio-or-percent aware), everything else
    // as the app's compact number, so "45.3K" is "45.3K" everywhere.
    if (SHARE_COL.test(col)) return formatPercent(n, 2);
    return compactNumber(n);
  }
  return s;
}

// ── Single-row numeric result → inline metrics (label/value pairs) ────────────
// Mirrors the old KPICards column selection; rendering goes through <BriefMetrics>.
function columnsToMetrics(columns: string[], rows: unknown[][]): BriefMetric[] {
  const row = rows[0];
  if (!row) return [];
  const numericCols = columns.filter((c, i) => isNumeric(row[i]) && !ORDINAL_COL.test(c));
  const isSingle = numericCols.length === 1;
  return numericCols.map((col) => {
    const idx = columns.indexOf(col);
    return { label: isSingle ? "" : cleanLabel(col), value: fmt(col, row[idx]) };
  });
}

// ── Data summary ──────────────────────────────────────────────────────────────
// Computes a 1-2 sentence actionable insight from the result rows.
// Pure computation — no LLM call, zero latency.
function computeSummary(columns: string[], rows: unknown[][], sql?: string | null): string | null {
  if (!rows.length || !columns.length) return null;
  const n = rows.length;

  const numIdx = columns.findIndex(
    (c, i) => !ORDINAL_COL.test(c) && rows.slice(0, 5).every((r) => isNumeric((r as unknown[])[i]))
  );
  const catIdx = columns.findIndex(
    (c, i) => i !== numIdx && !isNumeric(firstNonNull(rows, i)) && !ORDINAL_COL.test(c)
  );
  const cat2Idx = columns.findIndex(
    (c, i) => i !== numIdx && i !== catIdx && !isNumeric(firstNonNull(rows, i)) && !ORDINAL_COL.test(c)
  );

  if (numIdx === -1) {
    return n === 1 ? "1 result." : `${formatCount(n)} rows returned.`;
  }

  const numCol = columns[numIdx];
  const isShare = SHARE_COL.test(numCol) &&
    rows.slice(0, 5).every((r) => { const v = Number((r as unknown[])[numIdx]); return !isNaN(v) && v <= 1; });
  const fmtVal = (v: number) => fmt(numCol, v);

  if (n === 1) {
    const label = catIdx >= 0 ? String((rows[0] as unknown[])[catIdx]) : cleanLabel(numCol);
    return `${label}: ${fmtVal(Number((rows[0] as unknown[])[numIdx]))}`;
  }

  // No category — just a numeric summary
  if (catIdx < 0) {
    const nums = rows.map((r) => Number((r as unknown[])[numIdx])).filter((v) => !isNaN(v));
    const total = nums.reduce((a, b) => a + b, 0);
    return isShare ? `avg ${fmtVal(total / nums.length)}` : `${fmtVal(total)} total across ${n} rows.`;
  }

  // Additivity gate: share-of-total / concentration is ONLY valid for an ADDITIVE measure
  // (revenue, counts). For a NON-ADDITIVE one (an average/rate/ratio — e.g. AOV) summing the
  // per-group values is meaningless ("credit_card accounts for 20% of 346.89" = five ~€69
  // averages summed). The SQL is authoritative (AVG/ratio → non-additive); else the name.
  const additive = isAdditiveMeasure(numCol, sql);

  // Per-category value: SUM for additive measures, MEAN for non-additive ones.
  const groups = new Map<string, number[]>();
  rows.forEach((r) => {
    const k = String((r as unknown[])[catIdx]);
    const v = Number((r as unknown[])[numIdx]);
    if (!isNaN(v)) { if (!groups.has(k)) groups.set(k, []); groups.get(k)!.push(v); }
  });
  const sorted = [...groups.entries()]
    .map(([k, vs]) => [k, additive ? vs.reduce((a, b) => a + b, 0) : vs.reduce((a, b) => a + b, 0) / vs.length] as [string, number])
    .sort((a, b) => b[1] - a[1]);
  if (!sorted.length) return null;

  const [topName, topVal] = sorted[0];
  const parts: string[] = [];

  if (isShare) {
    parts.push(`${topName} leads at ${fmtVal(topVal)}.`);
  } else if (additive) {
    const aggTotal = sorted.reduce((s, [, v]) => s + v, 0);
    const topPct = aggTotal > 0 ? Math.round((topVal / aggTotal) * 100) : 0;
    const concLabel = topPct >= 30 ? "highly concentrated" : topPct >= 18 ? "concentrated" : "spread";
    parts.push(`${cleanLabel(numCol)} is ${concLabel} — ${topName} alone accounts for ${topPct}% of ${fmtVal(aggTotal)}.`);
    // Top-3 tier sentence (additive only — a share of the real total).
    if (sorted.length >= 4) {
      const top3Sum = sorted.slice(0, 3).reduce((s, [, v]) => s + v, 0);
      const top3Pct = aggTotal > 0 ? Math.round((top3Sum / aggTotal) * 100) : 0;
      const top3Names = sorted.slice(0, 3).map(([k]) => k).join(", ");
      parts.push(`${top3Names} together make up ${top3Pct}%.`);
    }
  } else {
    // Non-additive (average/rate/ratio): describe the spread + leader, never a "share".
    const [loName, loVal] = sorted[sorted.length - 1];
    const flat = loVal > 0 && topVal / loVal <= 1.1;   // within 10% → effectively flat
    parts.push(flat
      ? `${cleanLabel(numCol)} is roughly flat across ${sorted.length} ${cleanLabel(columns[catIdx])}s (${fmtVal(loVal)}–${fmtVal(topVal)}).`
      : `${cleanLabel(numCol)} ranges ${fmtVal(loVal)}–${fmtVal(topVal)} across ${sorted.length} ${cleanLabel(columns[catIdx])}s — highest for ${topName}, lowest for ${loName}.`);
  }

  // Stack dimension: which segment dominates overall (additive only — it sums by segment).
  if (cat2Idx >= 0 && parts.length < 2 && additive) {
    const stackAgg = new Map<string, number>();
    rows.forEach((r) => {
      const sk = String((r as unknown[])[cat2Idx]);
      const v = Number((r as unknown[])[numIdx]);
      if (!isNaN(v)) stackAgg.set(sk, (stackAgg.get(sk) ?? 0) + v);
    });
    if (stackAgg.size > 0) {
      const [topStack] = [...stackAgg.entries()].sort((a, b) => b[1] - a[1])[0];
      parts.push(`${topStack} is the dominant ${cleanLabel(columns[cat2Idx])} across all ${cleanLabel(columns[catIdx])}s.`);
    }
  }

  return parts.slice(0, 2).join(" ") || null;
}

// ── Result figure — the framed block: inline metrics, a chart, or a table ─────
// The ONLY framed object in an Insight brief. Single-row numbers render inline
// (no frame); a chartable / tabular result renders inside one <BriefFigure>.
function ResultFigure({
  turn, onShowSource,
}: {
  turn: ChatTurn;
  onShowSource?: (data: SourcePanelData) => void;
}) {
  const { columns, rows, chartType } = turn;
  if (!columns.length) return null;

  const isSingleRow = rows.length === 1;
  const hasDate = columns.some((c) => DATE_COL.test(c));
  const hasCat  = columns.some((c, i) => !isNumeric(rows[0]?.[i]));
  const hasNum  = columns.some((c, i) => isNumeric(rows[0]?.[i]) && !ORDINAL_COL.test(c));

  const explicitChart = chartType && chartType !== "auto";
  const showChart = explicitChart
    ? hasNum
    : rows.length >= 3 && hasNum && (hasDate || hasCat);

  const sourceTitle = inferSourceTitle(columns, rows);

  function handleSourceClick() {
    onShowSource?.({
      columns,
      rows: sortRowsForDisplay(columns, rows),
      sql: turn.sql,
      title: sourceTitle,
    });
  }

  if (isSingleRow && hasNum) {
    return <BriefMetrics metrics={columnsToMetrics(columns, rows)} />;
  }

  if (showChart) {
    return (
      <div className="flex flex-col gap-1.5">
        <BriefFigure caption={sourceTitle}>
          <ResultChartCard columns={columns} rows={rows} chartType={chartType} chartConfig={turn.chartConfig} title={sourceTitle} />
        </BriefFigure>
        {onShowSource && (
          <button
            onClick={handleSourceClick}
            className="self-end flex items-center gap-1.5 aug-text-xs text-zinc-500 hover:text-zinc-300 transition-colors"
          >
            <TableIcon label="Table" size="small" />
            Source data
          </button>
        )}
      </div>
    );
  }

  return (
    <BriefFigure caption={sourceTitle}>
      <SqlResultTable columns={columns} rows={rows} maxHeight={320} />
    </BriefFigure>
  );
}

// ── SQL block with copy button ────────────────────────────────────────────────
function SqlBlock({ sql }: { sql: string }) {
  const [copied, setCopied] = useState(false);

  function handleCopy() {
    navigator.clipboard.writeText(sql).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  return (
    <div className="relative group/sql">
      <pre className="aug-fs-sm font-code text-zinc-400 rounded p-2.5 pr-10 overflow-x-auto whitespace-pre-wrap leading-relaxed" style={{ background: "var(--code-bg)" }}>
        {sql}
      </pre>
      <button
        onClick={handleCopy}
        title={copied ? "Copied!" : "Copy SQL"}
        className="absolute top-2 right-2 w-6 h-6 rounded flex items-center justify-center text-zinc-500 hover:text-zinc-300 hover:bg-zinc-700/60 transition opacity-0 group-hover/sql:opacity-100"
      >
        {copied
          ? <span className="text-emerald-400"><CheckMarkIcon label="Copied" size="small" /></span>
          : <CopyIcon label="Copy SQL" size="small" />}
      </button>
    </div>
  );
}

// ── SQL syntax highlighter ───────────────────────────────────────────────────
function FormattedSql({ sql }: { sql: string }) {
  // Multi-word keywords must come first in the alternation
  const TOKEN_RE = /(`[^`]*`|'[^']*'|\b(?:GROUP\s+BY|ORDER\s+BY|IS\s+NOT\s+NULL|IS\s+NOT|IS\s+NULL|NOT\s+IN|NOT\s+LIKE|SELECT|FROM|WHERE|JOIN|LEFT|INNER|RIGHT|OUTER|CROSS|ON|AS|IS|NOT|NULL|AND|OR|IN|LIKE|BETWEEN|DISTINCT|COUNT|SUM|AVG|MIN|MAX|CASE|WHEN|THEN|ELSE|END|WITH|UNION|ALL|HAVING|LIMIT|OFFSET|ROUND|DATE_TRUNC|STRFTIME|COALESCE|NULLIF|CAST|ILIKE|LOWER|UPPER|TRIM|LENGTH|REPLACE|SUBSTR|EXTRACT|IF|IIF|ASC|DESC)\b)/gi;

  const parts: React.ReactNode[] = [];
  let lastIdx = 0;
  TOKEN_RE.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = TOKEN_RE.exec(sql)) !== null) {
    if (match.index > lastIdx)
      parts.push(<span key={`p${lastIdx}`}>{sql.slice(lastIdx, match.index)}</span>);
    const tok = match[0];
    if (tok.startsWith("`") || tok.startsWith('"'))
      parts.push(<span key={`p${match.index}`} style={{ color: "#93c5fd" }}>{tok}</span>);
    else if (tok.startsWith("'"))
      parts.push(<span key={`p${match.index}`} style={{ color: "#fbbf24" }}>{tok}</span>);
    else
      parts.push(<span key={`p${match.index}`} style={{ color: "#60a5fa", fontWeight: 500 }}>{tok}</span>);
    lastIdx = match.index + tok.length;
  }
  if (lastIdx < sql.length) parts.push(<span key="tail">{sql.slice(lastIdx)}</span>);

  return (
    <pre className="aug-fs-sm font-code text-zinc-300 p-3 overflow-x-auto whitespace-pre leading-[1.65]" style={{ background: "transparent" }}>
      {parts}
    </pre>
  );
}

// ── Source panel (Databricks-style: table + expandable SQL) — exported so ────
// ChatPanel can render it as a top-level right-side drawer.             ────────
export function SourcePanel({
  columns, rows, sql, title, onClose,
}: {
  columns: string[]; rows: unknown[][]; sql: string | null; title: string; onClose: () => void;
}) {
  const [copied,   setCopied]   = useState(false);
  const openInBuilder = useOpenInBuilder();

  // Detect each date column's true grain once (from the full column), so weekly
  // buckets render as "Jan 5" not four identical "Jan 2026" rows.
  const granByCol: (Gran | undefined)[] = columns.map((c, ci) => {
    const sample = rows.find(r => (r as unknown[])[ci] != null);
    const isDate = sample != null && /^\d{4}-\d{2}-\d{2}/.test(String((sample as unknown[])[ci]));
    return isDate ? detectGranularity(c, rows.map(r => (r as unknown[])[ci])) : undefined;
  });

  function handleCopySql() {
    if (!sql) return;
    navigator.clipboard.writeText(sql).then(() => { setCopied(true); setTimeout(() => setCopied(false), 2000); });
  }

  return (
    <div className="flex flex-col h-full" style={{ background: "#0f1923" }}>
      {/* ── Header ── */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-zinc-700/60 flex-shrink-0">
        <div className="flex items-center gap-1.5 min-w-0">
          <span className="shrink-0 text-zinc-400">
            <TableIcon label="Table" size="small" />
          </span>
          <span className="aug-fs-sm font-medium text-zinc-200 truncate">{title}</span>
        </div>
        <div className="flex items-center gap-0.5 flex-shrink-0 ml-2">
          {/* Download CSV */}
          <button
            onClick={() => downloadCsv(columns, rows, title)}
            title="Download as CSV"
            className="w-6 h-6 flex items-center justify-center rounded hover:bg-zinc-700/60 text-zinc-500 hover:text-zinc-300 transition-colors"
          >
            <DownloadIcon label="Download CSV" size="small" />
          </button>
          {/* Copy SQL */}
          {sql && (
            <button onClick={handleCopySql} title={copied ? "Copied!" : "Copy SQL"}
              className="w-6 h-6 flex items-center justify-center rounded hover:bg-zinc-700/60 text-zinc-500 hover:text-zinc-300 transition-colors">
              {copied
                ? <span className="text-emerald-400"><CheckMarkIcon label="Copied" size="small" /></span>
                : <CopyIcon label="Copy SQL" size="small" />}
            </button>
          )}
          {/* Close */}
          <button onClick={onClose} title="Close"
            className="w-6 h-6 flex items-center justify-center rounded hover:bg-zinc-700/60 text-zinc-500 hover:text-zinc-300 transition-colors">
            <CloseIcon label="Close" size="small" />
          </button>
        </div>
      </div>

      {/* Data table — scrollable */}
      <div className="flex-1 overflow-auto min-h-0">
        <table className="aug-fs-sm w-full">
          <thead className="sticky top-0 z-10" style={{ background: "#0f1923" }}>
            <tr className="border-b border-zinc-700/60">
              {columns.map((c, ci) => (
                <th key={ci} className="px-3 py-1.5 text-left text-zinc-400 whitespace-nowrap font-medium">
                  <div className="flex items-center gap-1">
                    <span className="text-zinc-500 font-mono aug-fs-xs select-none">
                      {isNumeric(rows[0]?.[ci]) ? "1.2" : "Ac"}
                    </span>
                    {cleanLabel(c)}
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, ri) => (
              <tr key={ri} className="border-b border-zinc-700/20 last:border-0 hover:bg-white/[0.02]">
                {columns.map((col, ci) => (
                  <td key={ci} className="px-3 py-1.5 text-zinc-300 font-mono whitespace-nowrap">
                    {fmt(col, (row as unknown[])[ci], granByCol[ci])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* SQL — bottom ~50% of the panel, always visible for easy reading, with a Query Builder
          hand-off. (Was a collapsed "Show code" strip; the SQL is the point, so it stays open.) */}
      {sql && (
        <div className="flex-1 min-h-0 flex flex-col border-t border-zinc-700/60">
          <div className="flex items-center justify-between gap-2 px-3 py-1.5 flex-shrink-0 border-b border-zinc-700/40">
            <span className="flex items-center gap-1.5 aug-fs-sm font-medium text-zinc-300">
              <AngleBracketsIcon label="SQL" size="small" /> SQL
            </span>
            {openInBuilder && (
              <button
                onClick={() => openInBuilder(sql)}
                title="Open this query in the Query Builder"
                className="flex items-center gap-1 aug-fs-xs text-blue-400 hover:text-blue-300 transition-colors whitespace-nowrap"
              >
                Explore with Query Builder
                <ArrowRightIcon label="" size="small" />
              </button>
            )}
          </div>
          <div className="flex-1 overflow-auto min-h-0" style={{ background: "#0a1018" }}>
            <FormattedSql sql={sql} />
          </div>
        </div>
      )}
    </div>
  );
}

// ── Collapsible section ───────────────────────────────────────────────────────
function Section({
  label, defaultOpen = false, children,
}: { label: string; defaultOpen?: boolean; children: React.ReactNode }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="mt-2">
      <button
        onClick={() => setOpen(v => !v)}
        className="flex items-center gap-1 aug-fs-sm text-zinc-500 hover:text-zinc-400 transition-colors py-1"
      >
        <span className={`transition-transform duration-150 inline-block ${open ? "rotate-90" : ""}`}>›</span>
        {label}
      </button>
      {open && <div className="mt-1.5">{children}</div>}
    </div>
  );
}

// ── Dossier (Tier-0 trace) — the explorer's pre-computed derivation, served
// instead of a fresh ADA run. "Investigate deeper" escalates to a seeded ADA. ──
function DossierReportView({ dossier, onDeeper }: { dossier: FindingDossier; onDeeper?: () => void }) {
  return (
    <div style={{ display: "flex", flexDirection: "column" as const, gap: 14 }}>
      <div style={{ display: "inline-flex", alignItems: "center", gap: 8, fontSize: 11, color: "var(--t4)", textTransform: "uppercase" as const, letterSpacing: ".06em" }}>
        <span>Trace · derived during exploration — instant, no re-run</span>
      </div>
      {dossier.finding && (
        <div style={{ fontSize: 14, color: "var(--t1)", lineHeight: 1.6, fontWeight: 500 }}>{dossier.finding}</div>
      )}
      <DossierTrace dossier={dossier} />
      {dossier.sql && (
        <div>
          <div style={{ fontSize: 9, color: "var(--t4)", textTransform: "uppercase" as const, letterSpacing: ".06em", marginBottom: 6 }}>Source query</div>
          <pre style={{ margin: 0, padding: "12px 14px", borderRadius: "var(--r2)", background: "var(--bg-2)", border: "1px solid var(--b1)", fontSize: 11.5, fontFamily: "var(--font-code)", color: "var(--t2)", whiteSpace: "pre-wrap" as const, wordBreak: "break-word" as const, lineHeight: 1.55 }}>{dossier.sql}</pre>
        </div>
      )}
      {onDeeper && (
        <div style={{ display: "flex", alignItems: "center", gap: 10, paddingTop: 2 }}>
          <button onClick={onDeeper} style={{ padding: "6px 12px", borderRadius: "var(--r1)", background: "var(--bg-3)", border: "1px solid var(--b2)", color: "var(--t1)", fontSize: 12, fontWeight: 500, cursor: "pointer" }}>Investigate deeper →</button>
          <span style={{ fontSize: 11, color: "var(--t4)" }}>Runs a fresh analysis, seeded with this trace.</span>
        </div>
      )}
    </div>
  );
}

// ── Investigate body — delegates to the appropriate rich report view ──────────
// ── Turn renderer registry (the gen-UI seam · REC-U6 / LAYER-05) ──────────────
// Each answer *shape* (dossier / ADA / explore / direct) is a registry entry, not a
// branch in a god-component. First match wins — array order IS priority (dossier
// before ADA before explore before direct, exactly the old if-chain). Adding a new
// answer surface = one entry; InvestigateBody never changes. `registerTurnRenderer`
// lets a pack/plugin contribute a surface (prepended → matches before the built-ins)
// without touching this file — the seam the "agent composes its own UI" thesis needs.
export interface TurnRenderProps {
  onShowSource?: (data: SourcePanelData) => void;
  onDeeper?: (question: string, insightId: string | null) => void;
  connectionId?: string;
}

export interface TurnRenderer {
  id: string;
  match: (turn: ChatTurn) => boolean;
  render: (turn: ChatTurn, props: TurnRenderProps) => React.ReactNode;
}

export const TURN_RENDERERS: TurnRenderer[] = [
  {
    id: "dossier", // Tier 0: the explorer's pre-computed dossier — no ADA was run.
    match: (t) => !!t.dossierReport,
    render: (t, p) => (
      <DossierReportView
        dossier={t.dossierReport!}
        onDeeper={p.onDeeper ? () => p.onDeeper!(t.question, t.dossierInsightId) : undefined}
      />
    ),
  },
  {
    id: "ada",
    match: (t) => t.queryMode === "investigate" || !!t.adaReport,
    render: (t, p) => (
      <InvestigationReportView
        report={t.adaReport ?? undefined}
        streamingPhases={t.adaReport ? undefined : t.phases}
        onShowSource={p.onShowSource}
      />
    ),
  },
  {
    id: "explore",
    match: (t) => t.queryMode === "explore" && !!t.exploreReport,
    render: (t, p) => (
      <ExplorationReportView
        report={t.exploreReport!}
        subQuestions={t.subQuestions}
        subqAnswers={t.subqAnswers}
        queryCount={t.subqAnswers.length}
        connectionId={p.connectionId}
        investigationId={t.investigationId ?? undefined}
      />
    ),
  },
  {
    id: "direct", // Direct route — renders like Quick mode, source chip available.
    match: (t) => t.queryMode === "direct",
    render: (t, p) => {
      const rep = t.report as Record<string, unknown> | null;
      const headline = rep ? ((rep.headline ?? rep.summary ?? "") as string) : null;
      return (
        <>
          {headline && <p className="aug-fs-sm text-zinc-300 leading-relaxed mb-2">{headline}</p>}
          <ResultFigure turn={t} onShowSource={p.onShowSource} />
        </>
      );
    },
  },
];

/** Contribute an answer surface without editing this file. Prepended by default so a
 *  plugin's renderer matches before the built-ins (override-wins); pass {last:true} to
 *  append as a fallback. */
export function registerTurnRenderer(renderer: TurnRenderer, opts?: { last?: boolean }): void {
  if (opts?.last) TURN_RENDERERS.push(renderer);
  else TURN_RENDERERS.unshift(renderer);
}

function InvestigateBody({
  turn, onShowSource, onDeeper, connectionId,
}: {
  turn: ChatTurn;
  onShowSource?: (data: SourcePanelData) => void;
  onDeeper?: (question: string, insightId: string | null) => void;
  connectionId?: string;
}) {
  const renderer = TURN_RENDERERS.find((r) => r.match(turn));
  return renderer ? renderer.render(turn, { onShowSource, onDeeper, connectionId }) : null;
}

// ── Collapsible chevron ───────────────────────────────────────────────────────
function Chevron({ open }: { open: boolean }) {
  return (
    <span className={`text-zinc-500 transition-transform duration-150 inline-block ${open ? "rotate-180" : ""}`}>
      <ChevronDownIcon label="" size="small" />
    </span>
  );
}

// ── Referenced playbook items — keep / edit / remove ────────────────────────────
function PlaybookRefs({ refs }: { refs: PlaybookRef[] }) {
  const [items, setItems] = useState<PlaybookRef[]>(refs);
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  useEffect(() => { setItems(refs); }, [refs]);
  if (items.length === 0) return null;

  const remove = async (id: string) => {
    setBusy(id);
    const prev = items;
    setItems(list => list.filter(i => i.id !== id));   // optimistic
    try { await deletePlaybookEntry(id); }
    catch { setItems(prev); }
    finally { setBusy(null); }
  };
  const saveEdit = async (id: string) => {
    const text = draft.trim();
    if (!text) { setEditing(null); return; }
    setBusy(id);
    try {
      await editPlaybookRecommendation(id, text);
      setItems(list => list.map(i => i.id === id ? { ...i, recommendation: text } : i));
      setEditing(null);
    } catch { /* keep editor open on failure */ }
    finally { setBusy(null); }
  };

  return (
    <div className="mt-4 rounded-md border border-amber-700/30" style={{ background: "color-mix(in srgb, #f59e0b 5%, var(--bg-0))" }}>
      <button
        onClick={() => setOpen(v => !v)}
        className="w-full px-3 py-2 border-b border-amber-700/20 flex items-center gap-2 text-left"
      >
        <span className="shrink-0 text-amber-400/90">
          <WarningIcon label="Playbook" size="small" />
        </span>
        <span className="aug-fs-xs font-medium uppercase tracking-wide text-amber-400/90">Playbook referenced</span>
        <span className="aug-fs-xs text-zinc-500">— {items.length} item{items.length !== 1 ? "s" : ""}</span>
        <span className="ml-auto shrink-0 text-amber-600">{open ? "▲" : "▼"}</span>
      </button>
      {open && (
      <div className="divide-y divide-amber-700/15">
        {items.map(item => (
          <div key={item.id} className="px-3 py-2.5 group/pb">
            <div className="flex items-start gap-2">
              <span className="shrink-0 mt-1 w-1.5 h-1.5 rounded-[var(--r-pill)] bg-amber-400/70" />
              <div className="flex-1 min-w-0">
                {editing === item.id ? (
                  <div className="space-y-1.5">
                    <textarea
                      value={draft}
                      onChange={e => setDraft(e.target.value)}
                      rows={2}
                      className="w-full aug-fs-sm text-zinc-200 rounded border border-zinc-700 bg-[--bg-0] px-2 py-1.5 resize-none focus:outline-none focus:border-amber-600"
                    />
                    <div className="flex gap-2">
                      <button onClick={() => saveEdit(item.id)} disabled={busy === item.id}
                        className="aug-fs-xs px-2 py-0.5 rounded bg-amber-600/20 border border-amber-600/40 text-amber-300 hover:bg-amber-600/30">Save</button>
                      <button onClick={() => setEditing(null)}
                        className="aug-fs-xs px-2 py-0.5 rounded border border-zinc-700 text-zinc-400 hover:text-zinc-200">Cancel</button>
                    </div>
                  </div>
                ) : (
                  <>
                    <p className="aug-fs-sm text-zinc-300 leading-relaxed">{item.recommendation}</p>
                    <div className="flex items-center gap-2 mt-1 flex-wrap">
                      {item.trigger_condition && (
                        <span className="text-[10.5px] text-zinc-500">when {item.trigger_condition}</span>
                      )}
                      <span className="aug-fs-xs px-1.5 py-px rounded-[var(--r-pill)] border border-zinc-700 text-zinc-500">
                        {item.historical_success_rate > 0 ? `${Math.round(item.historical_success_rate * 100)}% success` : "no outcome data"}
                      </span>
                    </div>
                  </>
                )}
              </div>
              {editing !== item.id && (
                <div className="flex items-center gap-1 shrink-0 opacity-0 group-hover/pb:opacity-100 transition-opacity">
                  <button onClick={() => { setEditing(item.id); setDraft(item.recommendation); }}
                    className="aug-fs-xs px-1.5 py-0.5 rounded text-zinc-500 hover:text-zinc-200" title="Edit">Edit</button>
                  <button onClick={() => remove(item.id)} disabled={busy === item.id}
                    className="aug-fs-xs px-1.5 py-0.5 rounded text-zinc-500 hover:text-red-400" title="Remove from playbook">Remove</button>
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
      )}
    </div>
  );
}

// ── Inline agent trace — streams during the turn, auto-collapses when done ──────
function InlineAgentTrace({ turn }: { turn: ChatTurn }) {
  const running = turn.status === "loading";
  const [open, setOpen] = useState(running);
  const prevRunning = useRef(running);
  useEffect(() => {
    // Collapse automatically the moment the turn stops running.
    if (prevRunning.current && !running) setOpen(false);
    prevRunning.current = running;
  }, [running]);

  const traceState = turnToTraceState(turn, running);

  return (
    <div className="mb-4 rounded-md border border-zinc-800/60" style={{ background: "var(--bg-0)" }}>
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-3 py-2 group/trace"
      >
        <span className="flex items-center gap-2 aug-fs-xs font-medium uppercase tracking-wide text-violet-400/80">
          {running ? (
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-[var(--r-pill)] bg-violet-400 opacity-60" />
              <span className="relative inline-flex rounded-[var(--r-pill)] h-2 w-2 bg-violet-400" />
            </span>
          ) : (
            <span className="inline-flex h-2 w-2 rounded-[var(--r-pill)] bg-emerald-500" />
          )}
          Agent trace
          {!running && !open && (
            <span className="text-zinc-500 normal-case tracking-normal font-normal">· {traceState.investigationPhases?.length || traceState.subQuestions?.length || traceState.hypotheses?.length || 0} steps</span>
          )}
        </span>
        <Chevron open={open} />
      </button>
      {open && (
        <div className="border-t border-zinc-800/60">
          <ThinkingTrace state={traceState} />
        </div>
      )}
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

// ── Clarifying questions surfaced before deep analysis ───────────────────────
function ClarifyingQuestionsBanner({ questions, contextNote }: { questions: string[]; contextNote: string }) {
  if (!questions || questions.length === 0) return null;
  return (
    <div className="mt-3 mb-3 rounded-[var(--r3)] border border-blue-700/30 p-3" style={{ background: 'color-mix(in srgb, #3b82f6 6%, transparent)' }}>
      <div className="flex items-center gap-2 mb-1.5">
        <span className="aug-fs-xs font-medium uppercase tracking-wide text-blue-400">Clarifying questions</span>
      </div>
      {contextNote && <p className="aug-fs-xs text-blue-300/70 mb-2">{contextNote}</p>}
      <div className="flex flex-wrap gap-1.5">
        {questions.map((q, i) => (
          <span key={i} className="aug-fs-xs px-2 py-0.5 rounded-[var(--r-pill)] border border-blue-700/40 text-blue-300">{q}</span>
        ))}
      </div>
    </div>
  );
}

// ── Insight answer, rendered as a clean Brief ─────────────────────────────────
// Headline + interpretation prose + the one framed result (chart / table /
// metrics) + folded-away machinery. No purple card, no badges, no stacked banners.
function InsightBrief({
  turn, connectionId, onShowSource, onFollowUp, onRunFresh,
}: {
  turn: ChatTurn;
  connectionId?: string;
  onShowSource?: (data: SourcePanelData) => void;
  onFollowUp?: (q: string) => void;
  onRunFresh?: (q: string) => void;
}) {
  const proseText = turn.insight?.narrative?.trim() || computeSummary(turn.columns, turn.rows, turn.sql) || "";
  const anomalies = (turn.insight?.anomalies ?? []).filter(Boolean);
  const inspect = turn.inspectWarning;
  // The narrative + anomalies ride along the follow-ups narrator call (no extra cost),
  // but for a direct lookup they're noise — reveal them on demand via "Explain the data".
  const [explained, setExplained] = useState(false);
  const hasExplanation = !!(proseText || anomalies.length);

  return (
    <Brief>
      {turn.fromCache && (
        <BriefMeta
          items={[
            "From a similar past investigation",
            turn.cachedQuestion && turn.cachedQuestion !== turn.question
              ? <span key="cq" className="italic">originally: &ldquo;{turn.cachedQuestion}&rdquo;</span>
              : null,
            onRunFresh
              ? <button key="rf" onClick={() => onRunFresh(turn.question)} className="text-zinc-400 hover:text-zinc-200 hover:underline underline-offset-2 transition-colors">Run fresh</button>
              : null,
          ]}
        />
      )}

      {turn.headline && <BriefHeadline>{turn.headline}</BriefHeadline>}

      {inspect && inspect.issues.length > 0 && (
        <p className="aug-text-sm text-amber-400/90 leading-relaxed flex items-start gap-1.5">
          <span className="shrink-0 mt-0.5"><WarningIcon label="Warning" size="small" /></span>
          <span>
            Result may be incomplete — {inspect.issues.join("; ")}
            {inspect.suggestedFix ? `. ${inspect.suggestedFix}` : ""}
          </span>
        </p>
      )}

      <ResultFigure turn={turn} onShowSource={onShowSource} />

      {/* Explain the data — on-demand interpretation, so a direct lookup leads with
          the chart + numbers instead of unrequested narration. */}
      {hasExplanation && !explained && (
        <button
          onClick={() => setExplained(true)}
          className="self-start flex items-center gap-1.5 aug-text-sm text-zinc-400 hover:text-zinc-200 transition-colors"
        >
          <InformationIcon label="" size="small" />
          Explain the data
        </button>
      )}
      {explained && (
        <>
          {proseText && <BriefProse text={proseText} />}
          {anomalies.length > 0 && <BriefBullets items={anomalies} />}
        </>
      )}

      {turn.followups.length > 0 && (
        <BriefSection label="Follow-ups">
          <div className="flex flex-col gap-1">
            {turn.followups.map((q, i) => (
              <button
                key={i}
                onClick={() => onFollowUp?.(q)}
                className="text-left flex items-start gap-1.5 aug-text-sm text-zinc-500 hover:text-zinc-300 transition-colors"
              >
                <span className="shrink-0 text-zinc-500 mt-0.5"><ArrowRightIcon label="" size="small" /></span>
                <span>{q}</span>
              </button>
            ))}
          </div>
        </BriefSection>
      )}

      <InsightDetails turn={turn} connectionId={connectionId} onShowSource={onShowSource} />
    </Brief>
  );
}

// ── Opt-in actions on a chat answer: re-validate the query + a feedback signal ──────
function InsightActions({ turn, connectionId }: { turn: ChatTurn; connectionId?: string }) {
  const [verdict, setVerdict] = useState<QueryValidation | null>(null);
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState<"helpful" | "unhelpful" | null>(null);
  const sql = (turn.sql || "").trim();
  if (!sql || !connectionId) return null;

  const runValidate = async () => {
    setBusy(true);
    try { setVerdict(await validateQuery(connectionId, sql)); }
    catch { setVerdict(null); }
    finally { setBusy(false); }
  };
  const rate = (v: "helpful" | "unhelpful") => {
    setFeedback(v);
    if (turn.receiptId) void sendChatFeedback(connectionId, turn.receiptId, v);
  };

  const issues = verdict
    ? [...verdict.fanout_hits,
       ...verdict.join_warnings.map(w => `Join ${w.table_a}.${w.col_a} ↔ ${w.table_b}.${w.col_b}: only ${Math.round(w.overlap * 100)}% value overlap`),
       ...verdict.filter_warnings.map(w => `Filter ${w.column} = ${w.literal} matches no rows${w.suggestion ? ` — did you mean ${w.suggestion}?` : ""}`)]
    : [];

  return (
    <div className="flex flex-col gap-1.5 pt-1">
      <div className="flex items-center gap-2 aug-text-xs text-zinc-500">
        <button onClick={runValidate} disabled={busy}
          className="border border-zinc-700 rounded-md px-2 py-0.5 text-zinc-400 hover:text-zinc-200 transition disabled:opacity-50">
          {busy ? "Validating…" : "Validate"}
        </button>
        <span className="text-zinc-700">·</span>
        <button onClick={() => navigator.clipboard.writeText(sql).catch(() => {})}
          className="text-zinc-500 hover:text-zinc-300 transition">Copy SQL</button>
        <span className="text-zinc-700">·</span>
        <button onClick={() => rate("helpful")}
          className={`transition ${feedback === "helpful" ? "text-emerald-400" : "text-zinc-500 hover:text-zinc-300"}`} title="Helpful">👍</button>
        <button onClick={() => rate("unhelpful")}
          className={`transition ${feedback === "unhelpful" ? "text-amber-400" : "text-zinc-500 hover:text-zinc-300"}`} title="Not helpful">👎</button>
        {feedback && <span className="text-zinc-600 italic">thanks — noted</span>}
      </div>
      {verdict && (
        issues.length === 0 ? (
          <p className="aug-text-xs text-emerald-400/80">✓ Validated — no fan-out, join, or filter issues found.</p>
        ) : (
          <ul className="flex flex-col gap-0.5">
            {issues.map((it, i) => (
              <li key={i} className="aug-text-xs text-amber-300/80 flex items-start gap-1.5">
                <span className="shrink-0 text-amber-400/70">⚠</span>{it}
              </li>
            ))}
          </ul>
        )
      )}
    </div>
  );
}

// ── Insight machinery — folded into one quiet disclosure ──────────────────────
function InsightDetails({
  turn, connectionId, onShowSource,
}: {
  turn: ChatTurn;
  connectionId?: string;
  onShowSource?: (data: SourcePanelData) => void;
}) {
  const hasAnalysis = !!turn.analysis && (!!turn.analysis.intent || turn.analysis.steps.length > 0);
  const hasTables   = turn.tablesUsed.length > 0;
  const hasContext  = !!turn.contextManifest && !!connectionId;
  const hasSource   = turn.columns.length > 0;
  const hasPlaybook = turn.playbookRefs.length > 0;
  const hasElapsed  = turn.elapsedMs != null;
  const hasActions  = !!(turn.sql && turn.sql.trim() && connectionId);
  if (!(hasAnalysis || hasTables || hasContext || hasSource || hasPlaybook || hasElapsed || hasActions)) return null;

  return (
    <BriefDetails>
      {hasContext && (
        <BriefDetailBlock label="Agent context">
          <ContextRibbon manifest={turn.contextManifest!} connectionId={connectionId!} />
        </BriefDetailBlock>
      )}
      {hasActions && (
        <BriefDetailBlock label="Validate &amp; feedback">
          <InsightActions turn={turn} connectionId={connectionId} />
        </BriefDetailBlock>
      )}
      {hasAnalysis && (
        <BriefDetailBlock label="How this was computed">
          {turn.analysis!.intent && (
            <p className="aug-text-sm text-zinc-400 leading-relaxed">{turn.analysis!.intent}</p>
          )}
          {turn.analysis!.steps.length > 0 && (
            <ol className="flex flex-col gap-1">
              {turn.analysis!.steps.map((s, i) => (
                <li key={i} className="flex gap-2 aug-text-sm text-zinc-400 leading-snug">
                  <span className="shrink-0 text-zinc-500 font-mono">{i + 1}.</span>
                  <span>{s}</span>
                </li>
              ))}
            </ol>
          )}
        </BriefDetailBlock>
      )}

      {hasTables && (
        <BriefDetailBlock label="Tables used">
          <p className="aug-text-sm font-mono text-zinc-400">{turn.tablesUsed.join("  ·  ")}</p>
        </BriefDetailBlock>
      )}

      {hasSource && onShowSource && (
        <button
          onClick={() => onShowSource({
            columns: turn.columns,
            rows: sortRowsForDisplay(turn.columns, turn.rows),
            sql: turn.sql,
            title: inferSourceTitle(turn.columns, turn.rows),
          })}
          className="self-start flex items-center gap-1.5 aug-text-sm text-zinc-500 hover:text-zinc-300 transition-colors"
        >
          <TableIcon label="Table" size="small" />
          View source data &amp; SQL
        </button>
      )}

      {hasPlaybook && <PlaybookRefs refs={turn.playbookRefs} />}

      {hasElapsed && (
        <p className="aug-text-xs text-zinc-500">Completed in {formatElapsed(turn.elapsedMs!)}</p>
      )}
    </BriefDetails>
  );
}

export function ChatMessage({
  turn,
  connectionId,
  onFollowUp,
  onRunFresh,
  onShowSource,
  onDeeper,
  onApprovePlan,
  onRejectPlan,
}: {
  turn: ChatTurn;
  connectionId?: string;
  onFollowUp?: (q: string) => void;
  onRunFresh?: (q: string) => void;
  onShowSource?: (data: SourcePanelData) => void;
  onDeeper?: (question: string, insightId: string | null) => void;
  onApprovePlan?: (invId: string, keepIndices: number[]) => void;
  onRejectPlan?: (invId: string) => void;
}) {
  const [collapsed, setCollapsed] = useState(false);
  const isInvestigate = turn.mode === "investigate";
  const hasResult = isInvestigate
    ? !!(turn.adaReport ?? turn.report ?? turn.exploreReport ?? turn.dossierReport)
    : turn.status === "done";
  const isDone = turn.status === "done" || hasResult;
  // Show streaming ADA phases even while still loading (not for direct/explore routes)
  const showStreamingBody = isInvestigate && turn.status === "loading" && turn.phases.length > 0
    && turn.queryMode !== "direct";

  // Context-aware loading text: once the backend tells us the route, use a specific label
  function defaultStatusText(): string {
    if (!isInvestigate) return "Thinking…";
    switch (turn.queryMode) {
      case "direct":  return "Running query…";
      case "explore": return "Investigating…";
      default:        return "Investigating…";
    }
  }

  return (
    /* No card — content flows directly on the page background */
    <div className="group">

      {/* ── Question (right-aligned bubble) ── */}
      <div className="flex justify-end mb-4">
        <div className="flex items-start gap-2 max-w-[75%]">
          {isDone && (
            <button
              onClick={() => setCollapsed(v => !v)}
              className="text-zinc-500 hover:text-zinc-500 transition-colors p-0.5 mt-2 opacity-0 group-hover:opacity-100 shrink-0"
              title={collapsed ? "Expand" : "Collapse"}
            >
              <Chevron open={!collapsed} />
            </button>
          )}
          <div
            className="px-3 py-2 rounded-md aug-fs-sm font-semibold text-white leading-snug"
            style={{ background: isInvestigate ? "#633D96" : "#05355D" }}
          >
            {turn.question}
          </div>
        </div>
      </div>

      {/* ── Inline agent trace (agentic modes) — streams live, collapses when done ── */}
      {isInvestigate && (turn.status === "loading" || isDone || turn.status === "error") && (
        <InlineAgentTrace turn={turn} />
      )}

      {/* ── Editable plan gate (P3): review the sub-question plan before the fan-out ── */}
      {turn.planPending && onApprovePlan && onRejectPlan && (
        <PlanGateCard
          plan={turn.planPending}
          onApprove={(keep) => onApprovePlan(turn.planPending!.investigationId ?? turn.investigationId ?? "", keep)}
          onReject={() => onRejectPlan(turn.planPending!.investigationId ?? turn.investigationId ?? "")}
        />
      )}

      {/* ── Loading state ── */}
      {turn.status === "loading" && (
        <div>
          {/* Clarifying questions surface early in deep analysis */}
          {isInvestigate && turn.clarifyingQuestions.length > 0 && (
            <ClarifyingQuestionsBanner questions={turn.clarifyingQuestions} contextNote={turn.clarifyingContext} />
          )}
          {/* Quick (ask) mode has no multi-step trace — show the simple thinking dots */}
          {!isInvestigate && (
            <div className="flex items-center gap-3 py-2">
              <span className="flex gap-1">
                {[0, 150, 300].map(d => (
                  <span key={d} className="w-1.5 h-1.5 rounded-[var(--r-pill)] bg-zinc-700 animate-bounce" style={{ animationDelay: `${d}ms` }} />
                ))}
              </span>
              <span className="aug-fs-sm text-zinc-500">
                {turn.statusText || defaultStatusText()}
              </span>
            </div>
          )}
          {/* Live ADA phase stream — show completed phases as they arrive */}
          {showStreamingBody && <InvestigateBody turn={turn} />}
        </div>
      )}

      {/* ── Error state ── */}
      {turn.status === "error" && (
        <p className="aug-fs-sm text-red-400 py-1">{turn.error}</p>
      )}

      {/* ── Tables used + timing — Deep Analysis keeps these here for now; the
           Insight brief folds them into its own details. (Phase C moves these
           into the report itself.) ── */}
      {isDone && isInvestigate && turn.tablesUsed.length > 0 && (
        <div className="flex items-center gap-2 flex-wrap mb-3">
          <span className="aug-fs-sm text-zinc-500">Found relevant data</span>
          {turn.tablesUsed.map(t => (
            <span key={t} className="inline-flex items-center gap-1 aug-fs-sm font-mono px-2 py-0.5 rounded-md border border-zinc-700/60 text-zinc-400" style={{ background: "#1e2d3d" }}>
              <span className="shrink-0 text-zinc-500"><TableIcon label="Table" size="small" /></span>
              {t}
            </span>
          ))}
        </div>
      )}
      {isDone && isInvestigate && turn.elapsedMs != null && (
        <p className="aug-fs-xs text-zinc-500 mb-3">Completed in {formatElapsed(turn.elapsedMs)}</p>
      )}

      {/* ── Insight — the final answer as a clean Brief ── */}
      {!collapsed && isDone && !isInvestigate && (
        <InsightBrief
          turn={turn}
          connectionId={connectionId}
          onShowSource={onShowSource}
          onFollowUp={onFollowUp}
          onRunFresh={onRunFresh}
        />
      )}

      {/* ── Deep Analysis — interim wrapping (Phase C rebuilds this on the Brief) ── */}
      {!collapsed && isDone && isInvestigate && (
        <>
          {turn.fromCache && (
            <div className="flex items-start gap-2 mb-4 px-3 py-2 rounded-[var(--r3)] bg-amber-950/30 border border-amber-800/40 aug-fs-xs text-amber-400 leading-snug">
              <span className="shrink-0 mt-0.5 text-amber-500">
                <InformationIcon label="Info" size="small" />
              </span>
              <span className="flex-1">
                <span className="text-amber-300 font-medium">From a similar past investigation</span>
                {turn.cachedQuestion && turn.cachedQuestion !== turn.question && (
                  <span className="text-amber-400/70"> — originally asked: &ldquo;{turn.cachedQuestion}&rdquo;</span>
                )}
              </span>
              {onRunFresh && (
                <button
                  onClick={() => onRunFresh(turn.question)}
                  className="shrink-0 px-2 py-0.5 rounded bg-amber-800/50 hover:bg-amber-700/60 text-amber-200 hover:text-white transition-colors whitespace-nowrap"
                >
                  Run fresh ↺
                </button>
              )}
            </div>
          )}
          <div className="mb-1">
            <InvestigateBody turn={turn} onShowSource={onShowSource} onDeeper={onDeeper} connectionId={connectionId} />
          </div>
          {turn.playbookRefs.length > 0 && <PlaybookRefs refs={turn.playbookRefs} />}
          {turn.followups.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mt-4">
              {turn.followups.map((q, i) => (
                <button
                  key={i}
                  onClick={() => onFollowUp?.(q)}
                  className="flex items-center gap-1 aug-fs-sm text-zinc-500 hover:text-zinc-200 border border-zinc-700/50 hover:border-zinc-600 rounded-[var(--r-pill)] px-2.5 py-[3px] transition-all"
                >
                  <span className="text-zinc-500 shrink-0">
                    <ArrowRightIcon label="" size="small" />
                  </span>
                  {q}
                </button>
              ))}
            </div>
          )}
        </>
      )}

      {/* ── Export this response as PDF / PowerPoint (Insight or Deep Analysis) ── */}
      {isDone && (turn.investigationId || turn.receiptId) && (
        <div className="flex justify-end items-center gap-2 mt-3">
          {turn.investigationId && connectionId && (
            <SaveAsSkillButton invId={turn.investigationId} connectionId={connectionId} />
          )}
          <ExportButton invId={(turn.investigationId ?? turn.receiptId) as string} />
        </div>
      )}
    </div>
  );
}

// Crystallize a finished investigation into a reusable, governed learned skill: propose
// (the candidate from its grounded, read-only SQL) → save (EXPLAIN-gated server-side). A
// 422 means the run wasn't skill-worthy (low confidence / ungrounded / no read-only query).
function SaveAsSkillButton({ invId, connectionId }: { invId: string; connectionId: string }) {
  const [state, setState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [msg, setMsg] = useState("");
  const save = async () => {
    setState("saving"); setMsg("");
    try {
      const candidate = await proposeLearnedSkill(invId, connectionId);
      await saveLearnedSkill(candidate, connectionId);
      setState("saved");
    } catch (e) {
      setState("error"); setMsg((e as Error).message || "Couldn't save");
    }
  };
  if (state === "saved")
    return <span className="aug-fs-xs text-emerald-400">✓ Saved as skill</span>;
  return (
    <button
      onClick={save}
      disabled={state === "saving"}
      title={msg || "Crystallize this investigation into a reusable, governed skill (Ontology ▸ Learned skills)"}
      className="aug-fs-xs text-violet-400 hover:text-violet-300 border border-violet-500/30 rounded px-2.5 py-1 transition disabled:opacity-50"
    >
      {state === "saving" ? "Saving…" : state === "error" ? "Retry — not skill-worthy?" : "Save as skill"}
    </button>
  );
}
