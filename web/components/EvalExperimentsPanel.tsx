"use client";
import React, { useCallback, useEffect, useState } from "react";
import type { TableColumnsType } from "antd";
import {
  EvalExperiment,
  EvalSuite,
  ExperimentCompare,
  ExperimentCompareRow,
  compareEvalExperiment,
  getEvalExperiments,
  getEvalSuites,
} from "@/lib/api";
import { AugTable } from "@/components/AugTable";
import { MiniStat, MiniStatRow } from "@/components/ui/MiniStat";
import { StatusChip, type ChipHue } from "@/components/brief/StatusChip";
import { Button } from "@/components/ui/button";

interface Props {
  connId?: string;
  workspaceId?: string;
}

/** Verdict → chip hue, the compare module's own vocabulary. */
const VERDICT_HUE: Record<string, ChipHue> = {
  correct: "positive",
  wrong: "negative",
  error: "negative",
  "no-ref": "muted",
};

const KIND_HUE: Record<string, ChipHue> = {
  gained: "positive",
  lost: "negative",
  other: "caution",
};

function relTime(iso?: string | null): string {
  if (!iso) return "—";
  const ms = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(ms / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 48) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function axisLabel(exp: EvalExperiment): string {
  if (exp.axis.kind === "flag") return exp.axis.name ?? "flag";
  return `${exp.axis.a_model ?? "?"} vs ${exp.axis.b_model ?? "?"}`;
}

function accuracyOf(run: EvalExperiment["a"]): string {
  if (run.correctness_known == null || !run.correctness_known) return "—";
  return `${run.correct}/${run.correctness_known}`;
}

/**
 * Experiments — A/B pairs DERIVED from the eval run history, never stored.
 *
 * Two runs of one suite whose recorded requests differ on exactly one axis (a flag,
 * or a model pin) are an experiment; this panel lists the pairs and renders the
 * per-case reading — which cases moved, in which direction, and what their SQL
 * became. Runs are produced by `run_experiment` (today driven from
 * `scripts/flag_ab_grid.py`, whose guards — the inertness pre-check and the pinned
 * temperature — are what make a pair worth reading).
 */
export function EvalExperimentsPanel({ }: Props) {
  const [experiments, setExperiments] = useState<EvalExperiment[]>([]);
  const [suites, setSuites] = useState<Record<string, EvalSuite>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<ExperimentCompare | null>(null);

  const load = useCallback(async () => {
    try {
      const [exps, ss] = await Promise.all([
        getEvalExperiments(undefined, 50),
        getEvalSuites().catch(() => [] as EvalSuite[]),
      ]);
      setExperiments(exps);
      setSuites(Object.fromEntries(ss.map(s => [s.id, s])));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load experiments");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  async function openPair(exp: EvalExperiment) {
    setError(null);
    try { setOpen(await compareEvalExperiment(exp.a.run_id, exp.b.run_id)); }
    catch (e) { setError(e instanceof Error ? e.message : "Failed to compare"); }
  }

  if (open) {
    return <CompareDetail cmp={open} suiteName={suites[open.suite_id]?.name}
                          onBack={() => setOpen(null)} />;
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", background: "var(--bg-0)", color: "var(--t1)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "16px 20px 12px", borderBottom: "1px solid var(--bg-3)" }}>
        <div className="aug-fs-ui" style={{ fontWeight: 600 }}>Experiments</div>
        <div style={{ flex: 1 }} />
        <Button variant="ghost" onClick={load} className="h-auto p-0 font-normal aug-fs-xs" style={{ background: "none", border: "1px solid var(--bg-3)", color: "var(--t2)", borderRadius: 4, cursor: "pointer", padding: "3px 9px" }}>Refresh</Button>
      </div>

      <div style={{ flex: 1, overflowY: "auto", padding: 20 }}>
        {loading && <p className="aug-fs-ui" style={{ color: "var(--t3)" }}>Loading…</p>}
        {error && <p className="aug-fs-ui" style={{ color: "var(--red4, #ef4444)", marginBottom: 12 }}>{error}</p>}

        {!loading && experiments.length === 0 && (
          <div style={{ textAlign: "center", paddingTop: 60, color: "var(--t3)" }}>
            <div className="aug-fs-glyph" style={{ marginBottom: 12 }}>⚗️</div>
            <div className="aug-fs-h2" style={{ fontWeight: 500, color: "var(--t2)", marginBottom: 6 }}>No experiments yet</div>
            <div className="aug-fs-sm" style={{ maxWidth: 420, margin: "0 auto" }}>
              An experiment is two runs of one suite that differ on exactly one axis —
              a flag, or a model. Run a suite under both cells (the A/B grid runner)
              and the pair appears here with its per-case diff.
            </div>
          </div>
        )}

        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {experiments.map(exp => (
            <div key={`${exp.a.run_id}-${exp.b.run_id}`}
              style={{ background: "var(--bg-1)", border: "1px solid var(--bg-3)", borderRadius: 6, padding: "11px 14px", cursor: "pointer", display: "flex", alignItems: "center", gap: 12 }}
              onClick={() => openPair(exp)}>
              <StatusChip hue={exp.axis.kind === "flag" ? "info" : "caution"}>{exp.axis.kind}</StatusChip>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div className="aug-fs-ui" style={{ fontWeight: 600, color: "var(--t1)" }}>
                  <code style={{ fontFamily: "var(--font-code)" }}>{axisLabel(exp)}</code>
                </div>
                <div className="aug-fs-xs" style={{ color: "var(--t3)", marginTop: 2 }}>
                  {suites[exp.suite_id]?.name ?? exp.suite_id} · baseline {relTime(exp.a.started_at)} · variant {relTime(exp.b.started_at)}
                </div>
              </div>
              <div style={{ textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
                <div className="aug-fs-h2" style={{ fontWeight: 700 }}>
                  {accuracyOf(exp.a)} <span style={{ color: "var(--t3)", fontWeight: 400 }}>→</span> {accuracyOf(exp.b)}
                </div>
                <div className="aug-fs-xs" style={{ color: "var(--t3)" }}>accuracy a → b</div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── Compare detail ────────────────────────────────────────────────────────────

function CompareDetail({ cmp, suiteName, onBack }: {
  cmp: ExperimentCompare; suiteName?: string; onBack: () => void;
}) {
  const paired = cmp.accuracy.paired;
  const axis = cmp.axis;

  const columns: TableColumnsType<ExperimentCompareRow & { key: React.Key }> = [
    { title: "Question", dataIndex: "question", key: "question",
      render: (v: string) => <span className="aug-fs-sm">{v || "—"}</span> },
    { title: "Baseline", dataIndex: "a", key: "a", width: 100,
      render: (v: string) => <StatusChip hue={VERDICT_HUE[v] ?? "muted"}>{v}</StatusChip> },
    { title: "Variant", dataIndex: "b", key: "b", width: 100,
      render: (v: string) => <StatusChip hue={VERDICT_HUE[v] ?? "muted"}>{v}</StatusChip> },
    { title: "Flip", dataIndex: "kind", key: "kind", width: 90,
      render: (v: string) => <StatusChip hue={KIND_HUE[v] ?? "muted"}>{v}</StatusChip> },
    { title: "SQL (baseline → variant)", key: "sql",
      render: (_: unknown, r: ExperimentCompareRow) => (
        (r.a_sql || r.b_sql)
          ? <div className="aug-fs-xs" style={{ fontFamily: "var(--font-code)", maxWidth: 420 }}>
              <div title={r.a_sql} style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", color: "var(--t2)" }}>{r.a_sql || "—"}</div>
              <div title={r.b_sql} style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", color: "var(--t1)" }}>{r.b_sql || "—"}</div>
            </div>
          : <span className="aug-fs-xs" style={{ color: "var(--t3)" }} title={r.a_error || r.b_error}>
              {(r.a_error || r.b_error) ? (r.a_error || r.b_error).slice(0, 60) : "—"}
            </span>
      ) },
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", background: "var(--bg-0)", color: "var(--t1)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "16px 20px 12px", borderBottom: "1px solid var(--bg-3)" }}>
        <StatusChip hue={axis?.kind === "flag" ? "info" : "caution"}>{axis?.kind ?? "pair"}</StatusChip>
        <div className="aug-fs-ui" style={{ fontWeight: 600 }}>
          <code style={{ fontFamily: "var(--font-code)" }}>
            {axis?.kind === "flag" ? axis?.name : `${axis?.a_model ?? "?"} vs ${axis?.b_model ?? "?"}`}
          </code>
          <span style={{ color: "var(--t3)", fontWeight: 400 }}> · {suiteName ?? cmp.suite_id}</span>
        </div>
        <div style={{ flex: 1 }} />
        <Button variant="ghost" onClick={onBack} className="h-auto p-0 font-normal aug-fs-sm" style={{ background: "none", border: "none", color: "var(--t3)", cursor: "pointer" }}>← All experiments</Button>
      </div>

      <div style={{ flex: 1, overflowY: "auto", padding: 20 }}>
        <MiniStatRow>
          <MiniStat value={paired.cases} label="Paired cases" />
          <MiniStat value={`${paired.a_correct}/${paired.cases}`} label="Baseline correct" />
          <MiniStat value={`${paired.b_correct}/${paired.cases}`} label="Variant correct"
                    tone={paired.b_correct > paired.a_correct ? "var(--grn4)"
                          : paired.b_correct < paired.a_correct ? "var(--red4, #ef4444)" : "var(--t1)"} />
          <MiniStat value={cmp.flips.gained} label="Gained" tone={cmp.flips.gained ? "var(--grn4)" : "var(--t1)"} />
          <MiniStat value={cmp.flips.lost} label="Lost" tone={cmp.flips.lost ? "var(--red4, #ef4444)" : "var(--t1)"} />
          {cmp.flips.unrun > 0 && <MiniStat value={cmp.flips.unrun} label="Unrun (excluded)" tone="var(--amb4, #f59e0b)" />}
        </MiniStatRow>

        <div className="aug-fs-xs" style={{ color: "var(--t3)", marginBottom: 12 }}>
          Accuracy on the paired subset is the honest number — a case one cell never
          reached counts as unrun, never as a flip.
          {!cmp.sql_available && " (These runs predate per-case SQL capture; verdicts only.)"}
        </div>

        {cmp.rows.length === 0 ? (
          <div className="aug-fs-sm" style={{ color: "var(--t3)", padding: "20px 0" }}>
            No case changed verdict between the two cells — {cmp.flips.same} agreed.
          </div>
        ) : (
          <AugTable<ExperimentCompareRow & { key: React.Key }>
            columns={columns}
            dataSource={cmp.rows.map((r, i) => ({ ...r, key: i }))}
            pagination={cmp.rows.length > 50 ? { pageSize: 50, size: "small" } : false}
            scroll={{ x: "max-content" }}
          />
        )}
      </div>
    </div>
  );
}
