"use client";

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
import type { DataQualityNote, Report } from "@/lib/types";

interface Props {
  report: Report;
  queryCount: number;
}

export function ReportView({ report, queryCount }: Props) {
  const dqNotes = report.data_quality_notes ?? [];

  return (
    <div className="space-y-6">
      {/* Headline */}
      <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-5">
        <p className="text-xs font-medium uppercase tracking-widest text-emerald-400 mb-2">Verdict</p>
        <p className="text-lg font-semibold text-white leading-snug">{report.headline}</p>
      </div>

      {/* Diagnosis */}
      <div className="space-y-2">
        <h3 className="text-sm font-semibold text-zinc-300 uppercase tracking-wide">Diagnosis</h3>
        <p className="text-sm text-zinc-300 leading-relaxed">{report.verdict}</p>
      </div>

      <Separator className="bg-zinc-800" />

      {/* Key findings */}
      {report.key_findings.length > 0 && (
        <div className="space-y-3">
          <h3 className="text-sm font-semibold text-zinc-300 uppercase tracking-wide">Key Findings</h3>
          <Table>
            <TableHeader>
              <TableRow className="border-zinc-800 hover:bg-transparent">
                <TableHead className="text-zinc-500 w-8">#</TableHead>
                <TableHead className="text-zinc-500">Finding</TableHead>
                <TableHead className="text-zinc-500">Evidence</TableHead>
                <TableHead className="text-zinc-500 text-right w-24">Confidence</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {report.key_findings.map((f, i) => (
                <TableRow key={i} className="border-zinc-800 hover:bg-zinc-900/40">
                  <TableCell className="text-zinc-500 font-mono text-xs">{i + 1}</TableCell>
                  <TableCell className="text-zinc-200 text-sm">{f.claim}</TableCell>
                  <TableCell className="text-zinc-400 text-xs max-w-[260px]">{f.evidence}</TableCell>
                  <TableCell className="text-right">
                    <Badge
                      variant="outline"
                      className={
                        f.confidence >= 0.7
                          ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-400"
                          : "border-amber-500/30 bg-amber-500/10 text-amber-400"
                      }
                    >
                      {Math.round(f.confidence * 100)}%
                    </Badge>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      {/* Ruled out */}
      {report.what_is_not_the_cause.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-sm font-semibold text-zinc-300 uppercase tracking-wide">Ruled Out</h3>
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

      {/* Risks */}
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

      <p className="text-xs text-zinc-600 text-center">{queryCount} SQL queries executed</p>
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
