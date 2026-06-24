"use client";

import { RichSchema, SchemaTable, SchemaJoin, SchemaWarning } from "@/lib/api";
import { TABLE_PALETTES, type TablePalette } from "@/lib/palette";
import { formatCount } from "@/lib/format";

// ── Column type → colour chip ─────────────────────────────────────────────────
// Strip precision/length from type names so chips stay compact (VARCHAR(255) → VARCHAR)
function typeChip(rawType: string): { label: string; cls: string } {
  const t = rawType.toUpperCase();
  const short = rawType.replace(/\(.*\)/, "").trim();
  if (/^(INT|BIGINT|INTEGER|SMALLINT|TINYINT|NUMERIC|DECIMAL|FLOAT|DOUBLE|REAL|HUGEINT|UBIGINT)/.test(t))
    return { label: short, cls: "bg-blue-500/15 text-blue-300" };
  if (/^(VARCHAR|TEXT|CHAR|STRING|BLOB)/.test(t))
    return { label: short, cls: "bg-emerald-500/15 text-emerald-300" };
  if (/^(DATE|TIME|TIMESTAMP|INTERVAL)/.test(t))
    return { label: short, cls: "bg-amber-500/15 text-amber-300" };
  if (/^(BOOL|BOOLEAN)/.test(t))
    return { label: short, cls: "bg-amber-500/15 text-amber-300" };
  return { label: short, cls: "bg-zinc-700/60 text-zinc-400" };
}

// ── Table card ────────────────────────────────────────────────────────────────
function TableCard({ table, palette }: { table: SchemaTable; palette: TablePalette }) {
  const totalCols = table.columns.length;

  return (
    <div className={`rounded border ${palette.border} bg-zinc-800 overflow-hidden flex flex-col`}>
      {/* Card header — compact */}
      <div className={`${palette.header} px-2.5 py-1.5 flex items-center justify-between gap-2`}>
        <div className="flex items-center gap-1.5 min-w-0">
          <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${palette.dot}`} />
          <span className="font-mono font-semibold text-[11px] text-white truncate">{table.name}</span>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          {table.row_count && (
            <span className={`text-[11px] px-1 py-px rounded font-mono ${palette.badge}`}>
              {formatCount(Number(table.row_count))}r
            </span>
          )}
          <span className="text-[11px] px-1 py-px rounded bg-zinc-800/80 text-zinc-500 font-mono">
            {totalCols}c
          </span>
        </div>
      </div>

      {/* Column list — tight rows */}
      <div className="divide-y divide-zinc-600/40 flex-1">
        {table.columns.map((col) => {
          const chip = typeChip(col.type);
          return (
            <div key={col.name} className="px-2.5 py-[3px] flex items-center justify-between gap-2 hover:bg-zinc-700/40 transition-colors">
              <div className="flex items-center gap-1 min-w-0">
                {col.is_fk && (
                  <span title="Foreign key" className="text-[8px] text-zinc-500 font-mono border border-zinc-600 rounded px-0.5 leading-tight shrink-0">FK</span>
                )}
                <span className="text-[11px] font-mono text-zinc-300 truncate">{col.name}</span>
              </div>
              <span className={`text-[11px] font-mono px-1 py-px rounded shrink-0 ${chip.cls}`}>{chip.label}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Join paths ────────────────────────────────────────────────────────────────
function JoinPaths({ joins }: { joins: SchemaJoin[] }) {
  if (!joins.length) return null;
  return (
    <div>
      <h3 className="text-[11px] font-semibold text-zinc-500 uppercase tracking-wider mb-2">
        Detected Join Paths
      </h3>
      <div className="grid grid-cols-1 gap-1.5">
        {joins.map((j, i) => (
          <div
            key={i}
            className="flex items-center gap-2 px-3 py-2 rounded-lg bg-zinc-800 border border-zinc-600 text-xs font-mono"
          >
            <span className="text-zinc-300">{j.t1}</span>
            <span className="text-zinc-500">.</span>
            <span className="text-amber-400">{j.c1}</span>
            <span className="text-zinc-500 mx-1">→</span>
            <span className="text-zinc-300">{j.t2}</span>
            <span className="text-zinc-500">.</span>
            <span className="text-amber-400">{j.c2}</span>
            <span className={`ml-auto text-[11px] px-1.5 py-0.5 rounded ${
              j.match === "exact"
                ? "bg-emerald-500/15 text-emerald-400"
                : "bg-amber-500/15 text-amber-400"
            }`}>
              {j.match}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── SQL Warnings & Modeling Notes ────────────────────────────────────────────
function Warnings({ warnings }: { warnings: SchemaWarning[] }) {
  return (
    <div>
      <h3 className="text-[11px] font-semibold text-zinc-500 uppercase tracking-wider mb-2">
        SQL Warnings &amp; Modeling Notes
      </h3>
      {warnings.length === 0 ? (
        <div className="flex items-center gap-2 px-3 py-2.5 rounded-lg bg-zinc-800 border border-zinc-600 text-xs text-zinc-500">
          <span className="text-emerald-500">✓</span>
          No type mismatches or modeling issues detected
        </div>
      ) : (
        <div className="space-y-1.5">
          {warnings.map((w, i) => (
            <div
              key={i}
              className={`flex items-start gap-2 px-3 py-2 rounded-lg text-xs border ${
                w.level === "warn"
                  ? "bg-amber-500/5 border-amber-500/20 text-amber-300"
                  : "bg-zinc-800 border-zinc-600 text-zinc-400"
              }`}
            >
              <span className="shrink-0 mt-px">{w.level === "warn" ? "⚠" : "ℹ"}</span>
              <span>{w.message}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Stats bar ─────────────────────────────────────────────────────────────────
function StatChip({ value, label, accent }: { value: string | number; label: string; accent?: string }) {
  return (
    <div className="flex items-baseline gap-1 px-2 py-1 rounded bg-zinc-800 border border-zinc-600">
      <span className={`text-xs font-semibold tabular-nums ${accent ?? "text-zinc-100"}`}>{value}</span>
      <span className="text-[11px] text-zinc-500">{label}</span>
    </div>
  );
}

function StatsBar({ schema }: { schema: RichSchema }) {
  const totalCols = schema.tables.reduce((s, t) => s + t.columns.length, 0);
  const warnCount = schema.warnings.filter(w => w.level === "warn").length;
  return (
    <div className="flex items-center gap-2 flex-wrap mb-2">
      <StatChip value={schema.tables.length} label="tables" />
      <StatChip value={totalCols} label="columns" />
      <StatChip value={schema.joins.length} label="join paths" />
      {warnCount > 0 && (
        <StatChip value={`⚠ ${warnCount}`} label={warnCount === 1 ? "warning" : "warnings"} accent="text-amber-400" />
      )}
    </div>
  );
}

// ── Main export ───────────────────────────────────────────────────────────────
export function SchemaCards({ schema, search }: { schema: RichSchema; search?: string }) {
  const q = (search ?? "").toLowerCase().trim();
  const filtered = q
    ? schema.tables.filter(
        (t) =>
          t.name.toLowerCase().includes(q) ||
          t.columns.some((c) => c.name.toLowerCase().includes(q))
      )
    : schema.tables;

  return (
    <div className="p-3 space-y-4">
      <StatsBar schema={schema} />

      {filtered.length === 0 && q ? (
        <p className="text-xs text-zinc-500 py-4 text-center">No tables match &quot;{q}&quot;</p>
      ) : (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-2">
          {filtered.map((table, i) => {
            const origIndex = schema.tables.indexOf(table);
            return (
              <TableCard
                key={table.name}
                table={table}
                palette={TABLE_PALETTES[origIndex % TABLE_PALETTES.length]}
              />
            );
          })}
        </div>
      )}

      <JoinPaths joins={schema.joins} />
      <Warnings warnings={schema.warnings} />
    </div>
  );
}
