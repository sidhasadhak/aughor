"use client";

import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { DataQualityNote, QueryCitation, Report } from "@/lib/types";

interface Props {
  report: Report;
  queryCount: number;
  queryHistory?: QueryCitation[];
  queryMode?: "direct" | "investigate" | null;
}

export function ReportView({ report, queryCount, queryHistory = [], queryMode }: Props) {
  const dqNotes = report.data_quality_notes ?? [];
  const isDirect = queryMode === "direct";

  // For direct mode: find the first successful query that has row data
  const directTable = isDirect
    ? queryHistory.find(q => !q.error && q.columns?.length && q.rows?.length)
    : undefined;

  return (
    <div className="space-y-6">
      {/* Headline */}
      <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-5">
        <p className="text-xs font-medium uppercase tracking-widest text-emerald-400 mb-2">Verdict</p>
        <p className="text-lg font-semibold text-white leading-snug">{report.headline}</p>
      </div>

      {/* Direct query result table — shown immediately after Verdict */}
      {isDirect && directTable && (
        <DirectResultTable table={directTable} />
      )}

      {/* Short Summary (direct) or Diagnosis (investigate) */}
      <div className="space-y-2">
        <h3 className="text-sm font-semibold text-zinc-300 uppercase tracking-wide">
          {isDirect ? "Short Summary" : "Diagnosis"}
        </h3>
        <p className="text-sm text-zinc-300 leading-relaxed">{report.verdict}</p>
      </div>

      <Separator className="bg-zinc-800" />

      {/* Key findings */}
      {report.key_findings.length > 0 && (
        <div className="space-y-3">
          <h3 className="text-sm font-semibold text-zinc-300 uppercase tracking-wide">Key Findings</h3>
          <div className="space-y-2">
            {report.key_findings.map((f, i) => {
              const citations = queryHistory.filter(
                q => q.hypothesis_id && f.hypothesis_id &&
                     q.hypothesis_id.toUpperCase() === f.hypothesis_id.toUpperCase()
              );
              return (
                <FindingRow key={i} index={i} finding={f} citations={citations} />
              );
            })}
          </div>
        </div>
      )}

      {/* Data quality notes — only shown when the agent found real issues */}
      {dqNotes.length > 0 && (
        <>
          <Separator className="bg-zinc-800" />
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-semibold text-orange-400 uppercase tracking-wide">
                Data Quality Issues
              </h3>
              <Badge variant="outline" className="border-orange-500/30 bg-orange-500/10 text-orange-400 text-xs">
                {dqNotes.length} found
              </Badge>
            </div>
            <p className="text-xs text-zinc-500">
              These structural issues were detected during the investigation and may affect analysis accuracy.
            </p>
            <div className="space-y-3">
              {dqNotes.map((note, i) => (
                <DataQualityCard key={i} note={note} />
              ))}
            </div>
          </div>
        </>
      )}

      <Separator className="bg-zinc-800" />

      {/* Watch — before Recommended Actions */}
      {report.risks.length > 0 && (
        <div className="rounded-lg border border-amber-500/20 bg-amber-500/5 p-4 space-y-2">
          <h3 className="text-xs font-semibold text-amber-400 uppercase tracking-wide">Watch</h3>
          <ul className="space-y-1">
            {report.risks.map((risk, i) => (
              <li key={i} className="text-xs text-amber-300/80 flex gap-2">
                <span>⚠</span>{risk}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Recommended actions */}
      {report.recommended_actions.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-sm font-semibold text-zinc-300 uppercase tracking-wide">Recommended Actions</h3>
          <ol className="space-y-2">
            {report.recommended_actions.map((action, i) => (
              <li key={i} className="flex items-start gap-3 text-sm text-zinc-300">
                <span className="shrink-0 mt-0.5 flex h-5 w-5 items-center justify-center rounded-full bg-zinc-800 text-xs font-mono text-zinc-400">
                  {i + 1}
                </span>
                {action}
              </li>
            ))}
          </ol>
        </div>
      )}

      {/* Ruled Out — at the bottom */}
      {report.what_is_not_the_cause.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-sm font-semibold text-zinc-500 uppercase tracking-wide">Ruled Out</h3>
          <ul className="space-y-1">
            {report.what_is_not_the_cause.map((item, i) => (
              <li key={i} className="flex items-start gap-2 text-sm text-zinc-500">
                <span className="mt-0.5 text-red-500/60">✕</span>
                {item}
              </li>
            ))}
          </ul>
        </div>
      )}

      <p className="text-xs text-zinc-600 text-center">{queryCount} SQL queries executed</p>
    </div>
  );
}

function FindingRow({
  index,
  finding,
  citations,
}: {
  index: number;
  finding: { claim: string; evidence: string; confidence: number; hypothesis_id: string | null };
  citations: QueryCitation[];
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 overflow-hidden">
      <div className="flex items-start gap-3 p-3">
        <span className="shrink-0 mt-0.5 text-xs font-mono text-zinc-600 w-5 text-right">
          {index + 1}
        </span>
        <div className="flex-1 min-w-0">
          <p className="text-sm text-zinc-200">{finding.claim}</p>
          <p className="mt-0.5 text-xs text-zinc-500 leading-relaxed">{finding.evidence}</p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <Badge
            variant="outline"
            className={
              finding.confidence >= 0.7
                ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-400"
                : "border-amber-500/30 bg-amber-500/10 text-amber-400"
            }
          >
            {Math.round(finding.confidence * 100)}%
          </Badge>
          {citations.length > 0 && (
            <button
              onClick={() => setOpen(o => !o)}
              className="flex items-center gap-1 text-xs text-zinc-500 hover:text-zinc-300 border border-zinc-700 rounded px-1.5 py-0.5 transition"
              title="Show source queries"
            >
              <span className="font-mono">{finding.hypothesis_id}</span>
              <span className="text-zinc-700">{open ? "▲" : "▼"}</span>
            </button>
          )}
        </div>
      </div>
      {open && citations.length > 0 && (
        <div className="border-t border-zinc-800 divide-y divide-zinc-800/60">
          {citations.map((c, i) => (
            <div key={i} className="px-4 py-2 space-y-1">
              <pre className="text-xs text-zinc-400 bg-zinc-950 rounded p-2 overflow-x-auto whitespace-pre-wrap font-mono leading-relaxed">
                {c.sql}
              </pre>
              <p className="text-xs text-zinc-600">
                {c.error
                  ? <span className="text-red-400">{c.error}</span>
                  : <span>{c.row_count} row{c.row_count !== 1 ? "s" : ""}</span>
                }
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function DirectResultTable({ table }: { table: QueryCitation }) {
  const columns = table.columns ?? [];
  const rows = table.rows ?? [];
  const VISIBLE_ROWS = 20;

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-zinc-300 uppercase tracking-wide">Query Results</h3>
        <span className="text-xs text-zinc-600 font-mono">
          {table.row_count} row{table.row_count !== 1 ? "s" : ""}
          {rows.length > VISIBLE_ROWS ? ` · scroll to see all` : ""}
        </span>
      </div>
      <div className="rounded-lg border border-zinc-800 overflow-hidden">
        {/* max-h shows ~20 rows; inner scroll reveals the rest */}
        <div className="overflow-x-auto overflow-y-auto max-h-[400px]">
          <Table>
            <TableHeader>
              <TableRow className="border-zinc-800 hover:bg-transparent">
                {columns.map(col => (
                  <TableHead key={col} className="text-xs text-zinc-500 font-mono whitespace-nowrap bg-zinc-900/80 h-8">
                    {col}
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row, ri) => (
                <TableRow key={ri} className="border-zinc-800/50 hover:bg-zinc-800/30">
                  {(row as unknown[]).map((cell, ci) => (
                    <TableCell key={ci} className="text-xs text-zinc-300 font-mono py-1.5 whitespace-nowrap">
                      {cell === null || cell === undefined ? (
                        <span className="text-zinc-600 italic">null</span>
                      ) : (
                        String(cell)
                      )}
                    </TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </div>
      <details className="group">
        <summary className="text-xs text-zinc-600 cursor-pointer hover:text-zinc-400 transition list-none flex items-center gap-1">
          <span className="group-open:hidden">▶</span>
          <span className="hidden group-open:inline">▼</span>
          SQL
        </summary>
        <pre className="mt-1 text-xs text-zinc-400 bg-zinc-950 rounded p-3 overflow-x-auto whitespace-pre-wrap font-mono leading-relaxed">
          {table.sql}
        </pre>
      </details>
    </div>
  );
}

function DataQualityCard({ note }: { note: DataQualityNote }) {
  const target = note.column ? `${note.table}.${note.column}` : note.table;
  return (
    <div className="rounded-lg border border-orange-500/20 bg-orange-500/5 p-4 space-y-2">
      <div className="flex items-start justify-between gap-3">
        <code className="text-xs font-mono text-orange-300 bg-orange-500/10 px-2 py-0.5 rounded">
          {target}
        </code>
      </div>
      <p className="text-sm text-zinc-300">{note.issue}</p>
      <p className="text-xs text-zinc-500">
        <span className="text-zinc-400 font-medium">Impact: </span>{note.impact}
      </p>
      <div className="border-t border-orange-500/10 pt-2">
        <p className="text-xs text-zinc-500">
          <span className="text-orange-400 font-medium">Fix: </span>{note.recommended_fix}
        </p>
      </div>
    </div>
  );
}
