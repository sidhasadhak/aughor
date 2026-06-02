"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import { API_BASE } from "@/lib/config";
import { ActivityLog } from "@/components/ActivityLog";

// ── Types ─────────────────────────────────────────────────────────────────────

interface AuditRecord {
  id: string;
  ts: string;
  connection_id: string;
  hypothesis_id: string;
  sql_digest: string;
  sql_full: string;
  verdict: "safe" | "suspicious" | "blocked";
  row_count: number;
  duration_ms: number;
  pii_redacted: number;
  error: string | null;
}

interface AuditStats {
  total: number;
  blocked: number;
  suspicious: number;
  errors: number;
  pii_redacted: number;
  avg_duration_ms: number;
}

interface QueryBudget {
  connection_id: string;
  max_rows: number;
  warn_time_ms: number;
  max_time_ms: number;
  is_default: boolean;
}

// ── API helpers ───────────────────────────────────────────────────────────────

async function fetchAuditLog(
  connId?: string,
  verdict?: string,
  limit = 100,
): Promise<AuditRecord[]> {
  const qs = new URLSearchParams({ limit: String(limit) });
  if (connId) qs.set("connection_id", connId);
  if (verdict) qs.set("verdict", verdict);
  const res = await fetch(`${API_BASE}/security/audit?${qs}`);
  if (!res.ok) throw new Error("Failed to fetch audit log");
  const data = await res.json();
  return data.records ?? [];
}

async function fetchAuditStats(connId?: string): Promise<AuditStats> {
  const qs = connId ? `?connection_id=${connId}` : "";
  const res = await fetch(`${API_BASE}/security/audit/stats${qs}`);
  if (!res.ok) throw new Error("Failed to fetch audit stats");
  return res.json();
}

async function fetchBudget(connId: string): Promise<QueryBudget> {
  const res = await fetch(`${API_BASE}/security/budget/${connId}`);
  if (!res.ok) throw new Error("Failed to fetch budget");
  return res.json();
}

async function saveBudget(
  connId: string,
  patch: { max_rows?: number; warn_time_ms?: number; max_time_ms?: number },
): Promise<void> {
  const res = await fetch(`${API_BASE}/security/budget/${connId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!res.ok) throw new Error("Failed to update budget");
}

// ── Verdict badge ─────────────────────────────────────────────────────────────

const VERDICT_COLOR: Record<string, string> = {
  safe:       "var(--green3, #4ade80)",
  suspicious: "var(--amb3, #f59e0b)",
  blocked:    "var(--r2, #f87171)",
};

function VerdictBadge({ verdict }: { verdict: string }) {
  const color = VERDICT_COLOR[verdict] ?? "var(--t3)";
  return (
    <span style={{
      fontSize: 10,
      fontWeight: 600,
      color,
      border: `1px solid ${color}`,
      borderRadius: 3,
      padding: "1px 5px",
      textTransform: "uppercase",
      letterSpacing: "0.05em",
    }}>
      {verdict}
    </span>
  );
}

// ── Stat card ─────────────────────────────────────────────────────────────────

function StatCard({
  label,
  value,
  accent = "var(--blue3)",
  warn = false,
}: {
  label: string;
  value: string | number;
  accent?: string;
  warn?: boolean;
}) {
  return (
    <div style={{
      flex: 1,
      minWidth: 100,
      background: "var(--bg-1)",
      border: `1px solid ${warn ? "var(--r2, #f87171)" : "var(--bg-3)"}`,
      borderRadius: 6,
      padding: "10px 14px",
    }}>
      <div style={{ fontSize: 20, fontWeight: 700, color: warn ? "var(--r2, #f87171)" : accent, lineHeight: 1 }}>
        {value}
      </div>
      <div style={{ fontSize: 11, color: "var(--t3)", marginTop: 4 }}>{label}</div>
    </div>
  );
}

// ── Budget editor ─────────────────────────────────────────────────────────────

function BudgetEditor({ connId }: { connId: string }) {
  const [budget, setBudget] = useState<QueryBudget | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [draft, setDraft] = useState<{ max_rows: number; warn_time_ms: number; max_time_ms: number } | null>(null);

  useEffect(() => {
    fetchBudget(connId).then(b => {
      setBudget(b);
      setDraft({ max_rows: b.max_rows, warn_time_ms: b.warn_time_ms, max_time_ms: b.max_time_ms });
    }).catch(() => {});
  }, [connId]);

  if (!budget || !draft) return (
    <div style={{ fontSize: 12, color: "var(--t3)", padding: "8px 0" }}>Loading budget…</div>
  );

  async function handleSave() {
    if (!draft) return;
    setSaving(true);
    try {
      await saveBudget(connId, draft);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch {
      // silently ignore — user will see no "Saved" feedback
    } finally {
      setSaving(false);
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {budget.is_default && (
        <div style={{ fontSize: 11, color: "var(--amb3, #f59e0b)", marginBottom: 4 }}>
          Using default budget — saving will create a per-connection override.
        </div>
      )}
      {(["max_rows", "warn_time_ms", "max_time_ms"] as const).map(key => (
        <label key={key} style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 12, color: "var(--t2)", width: 110, flexShrink: 0 }}>
            {key === "max_rows" ? "Max rows" : key === "warn_time_ms" ? "Warn (ms)" : "Max time (ms)"}
          </span>
          <input
            type="number"
            value={draft[key]}
            onChange={e => setDraft(d => d ? { ...d, [key]: Number(e.target.value) } : d)}
            style={{
              width: 100,
              background: "var(--bg-0)",
              border: "1px solid var(--bg-3)",
              borderRadius: 4,
              padding: "4px 8px",
              color: "var(--t1)",
              fontSize: 12,
            }}
          />
        </label>
      ))}
      <button
        onClick={handleSave}
        disabled={saving}
        style={{
          alignSelf: "flex-start",
          marginTop: 4,
          background: "var(--blue3, #3b82f6)",
          color: "#fff",
          border: "none",
          borderRadius: 4,
          padding: "5px 14px",
          fontSize: 12,
          cursor: "pointer",
          opacity: saving ? 0.6 : 1,
        }}
      >
        {saved ? "Saved" : saving ? "Saving…" : "Save budget"}
      </button>
    </div>
  );
}

// ── SQL expander cell ─────────────────────────────────────────────────────────

function SqlCell({ digest, full }: { digest: string; full: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button
        onClick={() => setOpen(o => !o)}
        style={{
          background: "none",
          border: "none",
          color: "var(--t2)",
          cursor: "pointer",
          fontSize: 11,
          fontFamily: "monospace",
          textAlign: "left",
          padding: 0,
        }}
        title="Click to expand"
      >
        {digest.length > 60 ? digest.slice(0, 60) + "…" : digest}
      </button>
      {open && (
        <pre style={{
          marginTop: 6,
          background: "var(--bg-0)",
          border: "1px solid var(--bg-3)",
          borderRadius: 4,
          padding: "8px 10px",
          fontSize: 11,
          color: "var(--t1)",
          whiteSpace: "pre-wrap",
          wordBreak: "break-all",
          maxHeight: 200,
          overflow: "auto",
        }}>
          {full}
        </pre>
      )}
    </div>
  );
}

// ── Main panel ────────────────────────────────────────────────────────────────

const VERDICT_FILTERS = ["all", "safe", "suspicious", "blocked"] as const;

// ── Sort helpers ──────────────────────────────────────────────────────────────

type SecSortCol = "ts" | "connection" | "verdict" | "rows" | "duration" | "pii";

const VERDICT_RANK: Record<string, number> = { blocked: 0, suspicious: 1, safe: 2 };

function sortRecords(rows: AuditRecord[], col: SecSortCol, dir: "asc" | "desc"): AuditRecord[] {
  const m = dir === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    switch (col) {
      case "ts":         return m * a.ts.localeCompare(b.ts);
      case "connection": return m * a.connection_id.localeCompare(b.connection_id);
      case "verdict":    return m * ((VERDICT_RANK[a.verdict] ?? 9) - (VERDICT_RANK[b.verdict] ?? 9));
      case "rows":       return m * (a.row_count - b.row_count);
      case "duration":   return m * (a.duration_ms - b.duration_ms);
      case "pii":        return m * (a.pii_redacted - b.pii_redacted);
      default:           return 0;
    }
  });
}

function SortIcon({ active, dir }: { active: boolean; dir: "asc" | "desc" }) {
  if (!active) return <span style={{ marginLeft: 3, opacity: 0.25 }}>⇅</span>;
  return <span style={{ marginLeft: 3, color: "var(--blue3)" }}>{dir === "asc" ? "↑" : "↓"}</span>;
}

// ── Lens toggle ───────────────────────────────────────────────────────────────

type Lens = "security" | "activity";

function LensToggle({ value, onChange }: { value: Lens; onChange: (v: Lens) => void }) {
  const opts: { v: Lens; label: string }[] = [
    { v: "security", label: "Security" },
    { v: "activity", label: "Activity" },
  ];
  return (
    <div style={{ display: "flex", gap: 1, padding: 2, background: "var(--bg-1)", borderRadius: 6, border: "0.5px solid var(--b1)" }}>
      {opts.map(o => (
        <button key={o.v} onClick={() => onChange(o.v)} style={{
          fontSize: 11, fontWeight: value === o.v ? 600 : 400, padding: "3px 12px", borderRadius: 4, cursor: "pointer",
          background: value === o.v ? "var(--bg-3)" : "transparent",
          color: value === o.v ? "var(--t1)" : "var(--t3)",
          border: value === o.v ? "0.5px solid var(--b2)" : "0.5px solid transparent",
          transition: "all .1s",
        }}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function SecurityAuditPanel({
  connId,
  lens = "security",
  onLensChange,
}: {
  connId?: string;
  lens?: Lens;
  onLensChange?: (v: Lens) => void;
}) {
  const [stats, setStats]     = useState<AuditStats | null>(null);
  const [records, setRecords] = useState<AuditRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState<string | null>(null);
  const [verdictFilter, setVerdictFilter] = useState<string>("all");
  const [showBudget, setShowBudget]       = useState(false);
  const [sortCol, setSortCol]   = useState<SecSortCol>("ts");
  const [sortDir, setSortDir]   = useState<"asc" | "desc">("desc");

  function handleSort(col: SecSortCol) {
    if (col === sortCol) setSortDir(d => d === "asc" ? "desc" : "asc");
    else { setSortCol(col); setSortDir(col === "ts" ? "desc" : "asc"); }
  }

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const verdict = verdictFilter === "all" ? undefined : verdictFilter;
      const [s, r] = await Promise.all([
        fetchAuditStats(connId),
        fetchAuditLog(connId, verdict, 200),
      ]);
      setStats(s);
      setRecords(r);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load audit data");
    } finally {
      setLoading(false);
    }
  }, [connId, verdictFilter]);

  useEffect(() => { load(); }, [load]);

  const sortedRecords = useMemo(() => sortRecords(records, sortCol, sortDir), [records, sortCol, sortDir]);

  // ── Render ──────────────────────────────────────────────────────────────────

  return (
    <div style={{
      flex: 1,
      display: "flex",
      flexDirection: "column",
      overflow: "hidden",
      background: "var(--bg-0)",
    }}>
      {/* Header */}
      <div style={{
        padding: "14px 20px",
        borderBottom: "1px solid var(--bg-2)",
        display: "flex",
        alignItems: "center",
        gap: 12,
        flexShrink: 0,
      }}>
        <span style={{ fontSize: 13, fontWeight: 600, color: "var(--t1)" }}>Security &amp; Audit</span>
        {connId && (
          <span style={{
            fontSize: 10,
            color: "var(--t3)",
            background: "var(--bg-2)",
            borderRadius: 3,
            padding: "2px 6px",
            fontFamily: "monospace",
          }}>
            {connId.slice(0, 8)}
          </span>
        )}
        <LensToggle value={lens} onChange={v => onLensChange?.(v)} />
        <div style={{ flex: 1 }} />
        {lens === "security" && connId && (
          <button
            onClick={() => setShowBudget(b => !b)}
            style={{
              fontSize: 11,
              color: showBudget ? "var(--blue3)" : "var(--t3)",
              background: showBudget ? "var(--bg-2)" : "none",
              border: "1px solid var(--bg-3)",
              borderRadius: 4,
              padding: "4px 10px",
              cursor: "pointer",
            }}
          >
            Query Budget
          </button>
        )}
        {lens === "security" && (
          <button
            onClick={load}
            disabled={loading}
            style={{
              fontSize: 11,
              color: "var(--t3)",
              background: "none",
              border: "1px solid var(--bg-3)",
              borderRadius: 4,
              padding: "4px 10px",
              cursor: "pointer",
              opacity: loading ? 0.5 : 1,
            }}
          >
            {loading ? "Loading…" : "Refresh"}
          </button>
        )}
      </div>

      {/* Activity lens — exploration episode log (merged Audit Log) */}
      {lens === "activity" && (
        <ActivityLog connectionId={connId ?? ""} isActive />
      )}

      {lens === "security" && (
      <div style={{ flex: 1, overflow: "auto", padding: "16px 20px", display: "flex", flexDirection: "column", gap: 16 }}>

        {/* Budget editor (collapsible) */}
        {showBudget && connId && (
          <div style={{
            background: "var(--bg-1)",
            border: "1px solid var(--bg-3)",
            borderRadius: 6,
            padding: "14px 16px",
          }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: "var(--t2)", marginBottom: 12 }}>
              Query Budget — {connId.slice(0, 8)}
            </div>
            <BudgetEditor connId={connId} />
          </div>
        )}

        {/* Error state */}
        {error && (
          <div style={{
            padding: "10px 14px",
            background: "rgba(248,113,113,0.08)",
            border: "1px solid var(--r2, #f87171)",
            borderRadius: 6,
            fontSize: 12,
            color: "var(--r2, #f87171)",
          }}>
            {error}
          </div>
        )}

        {/* Stats cards */}
        {stats && (
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            <StatCard label="Total queries"   value={stats.total ?? 0}                                         accent="var(--blue3)" />
            <StatCard label="Blocked"         value={stats.blocked ?? 0}     warn={(stats.blocked ?? 0) > 0}  accent="var(--r2, #f87171)" />
            <StatCard label="Suspicious"      value={stats.suspicious ?? 0}                                    accent="var(--amb3, #f59e0b)" />
            <StatCard label="Errors"          value={stats.errors ?? 0}                                        accent="var(--r2, #f87171)" />
            <StatCard label="PII redactions"  value={stats.pii_redacted ?? 0}                                  accent="var(--amb3, #f59e0b)" />
            <StatCard label="Avg duration"    value={stats.avg_duration_ms != null ? `${Math.round(stats.avg_duration_ms)}ms` : "—"} accent="var(--t2)" />
          </div>
        )}

        {/* Filters */}
        <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <span style={{ fontSize: 11, color: "var(--t3)", marginRight: 4 }}>Verdict</span>
          {VERDICT_FILTERS.map(v => (
            <button
              key={v}
              onClick={() => setVerdictFilter(v)}
              style={{
                fontSize: 11,
                fontWeight: verdictFilter === v ? 600 : 400,
                color: verdictFilter === v ? "var(--t1)" : "var(--t3)",
                background: verdictFilter === v ? "var(--bg-2)" : "none",
                border: "1px solid " + (verdictFilter === v ? "var(--bg-3)" : "transparent"),
                borderRadius: 4,
                padding: "3px 10px",
                cursor: "pointer",
                textTransform: "capitalize",
              }}
            >
              {v}
            </button>
          ))}
          <div style={{ flex: 1 }} />
          <span style={{ fontSize: 11, color: "var(--t3)" }}>{records.length} record{records.length !== 1 ? "s" : ""}</span>
        </div>

        {/* Audit table */}
        {!loading && records.length === 0 && !error && (
          <div style={{
            flex: 1,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            gap: 8,
            paddingTop: 60,
          }}>
            <div style={{ fontSize: 28 }}>🔒</div>
            <div style={{ fontSize: 13, color: "var(--t2)", fontWeight: 500 }}>No audit records</div>
            <div style={{ fontSize: 12, color: "var(--t3)" }}>
              {verdictFilter !== "all" ? `No ${verdictFilter} queries found` : "Queries will appear here once the agent runs"}
            </div>
          </div>
        )}

        {records.length > 0 && (
          <div style={{
            background: "var(--bg-1)",
            border: "1px solid var(--bg-2)",
            borderRadius: 6,
            overflow: "auto",
          }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
              <thead>
                <tr style={{ borderBottom: "1px solid var(--bg-3)" }}>
                  {([
                    { label: "Time",       col: "ts"         as const, align: "left"  },
                    { label: "Connection", col: "connection" as const, align: "left"  },
                    { label: "Verdict",    col: "verdict"    as const, align: "left"  },
                    { label: "SQL",        col: null,                   align: "left"  },
                    { label: "Rows",       col: "rows"       as const, align: "right" },
                    { label: "Duration",   col: "duration"   as const, align: "right" },
                    { label: "PII",        col: "pii"        as const, align: "center"},
                    { label: "Error",      col: null,                   align: "left"  },
                  ]).map(h => {
                    const active = h.col != null && sortCol === h.col;
                    return (
                      <th
                        key={h.label}
                        onClick={h.col ? () => handleSort(h.col!) : undefined}
                        style={{
                          padding: "8px 12px",
                          textAlign: h.align as React.CSSProperties["textAlign"],
                          fontSize: 10,
                          fontWeight: 600,
                          color: active ? "var(--blue3)" : "var(--t3)",
                          textTransform: "uppercase",
                          letterSpacing: "0.04em",
                          whiteSpace: "nowrap",
                          cursor: h.col ? "pointer" : "default",
                          userSelect: "none",
                        }}
                      >
                        {h.label}
                        {h.col && <SortIcon active={active} dir={sortDir} />}
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody>
                {sortedRecords.map((rec, i) => (
                  <tr
                    key={rec.id}
                    style={{
                      borderBottom: i < sortedRecords.length - 1 ? "1px solid var(--bg-2)" : "none",
                      background: rec.verdict === "blocked" ? "rgba(248,113,113,0.04)"
                               : rec.verdict === "suspicious" ? "rgba(245,158,11,0.04)"
                               : "transparent",
                    }}
                  >
                    <td style={{ padding: "8px 12px", color: "var(--t3)", whiteSpace: "nowrap" }}>
                      {rec.ts.replace("T", " ").replace("Z", "")}
                    </td>
                    <td style={{ padding: "8px 12px", color: "var(--t2)", fontFamily: "monospace", whiteSpace: "nowrap" }}>
                      {rec.connection_id.slice(0, 8)}
                      {rec.hypothesis_id && (
                        <span style={{ marginLeft: 4, fontSize: 10, color: "var(--t3)" }}>
                          {rec.hypothesis_id}
                        </span>
                      )}
                    </td>
                    <td style={{ padding: "8px 12px", whiteSpace: "nowrap" }}>
                      <VerdictBadge verdict={rec.verdict} />
                    </td>
                    <td style={{ padding: "8px 12px", maxWidth: 320 }}>
                      <SqlCell digest={rec.sql_digest} full={rec.sql_full} />
                    </td>
                    <td style={{ padding: "8px 12px", color: "var(--t2)", textAlign: "right", whiteSpace: "nowrap" }}>
                      {rec.row_count.toLocaleString()}
                    </td>
                    <td style={{ padding: "8px 12px", color: "var(--t2)", textAlign: "right", whiteSpace: "nowrap" }}>
                      {rec.duration_ms < 1000
                        ? `${Math.round(rec.duration_ms)}ms`
                        : `${(rec.duration_ms / 1000).toFixed(1)}s`}
                    </td>
                    <td style={{ padding: "8px 12px", color: rec.pii_redacted > 0 ? "var(--amb3, #f59e0b)" : "var(--t3)", textAlign: "center" }}>
                      {rec.pii_redacted > 0 ? rec.pii_redacted : "—"}
                    </td>
                    <td style={{ padding: "8px 12px", color: "var(--r2, #f87171)", maxWidth: 180 }}>
                      {rec.error ? (
                        <span title={rec.error} style={{ cursor: "help" }}>
                          {rec.error.slice(0, 40)}{rec.error.length > 40 ? "…" : ""}
                        </span>
                      ) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      )}
    </div>
  );
}
