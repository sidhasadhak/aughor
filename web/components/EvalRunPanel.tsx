"use client";
import React, { useEffect, useState, useCallback } from "react";
import type { TableColumnsType } from "antd";
import {
  EvalRun,
  EvalSuite,
  EvalResult,
  getEvalRuns,
  getEvalRun,
  getEvalSuites,
} from "@/lib/api";
import { subscribeKernelEvents } from "@/lib/events";
import { AugTable } from "@/components/AugTable";
import { MiniStat, MiniStatRow } from "@/components/ui/MiniStat";
import { StatusChip, type ChipHue } from "@/components/brief/StatusChip";
import { Button } from "@/components/ui/button";

interface Props {
  connId?: string;
  workspaceId?: string;
}

const STATUS_HUE: Record<string, ChipHue> = {
  succeeded: "positive",
  running: "info",
  failed: "negative",
};

export function EvalRunPanel({ }: Props) {
  const [runs, setRuns]       = useState<EvalRun[]>([]);
  const [suites, setSuites]   = useState<Record<string, EvalSuite>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState<string | null>(null);
  const [openRun, setOpenRun] = useState<(EvalRun & { results: EvalResult[] }) | null>(null);

  const load = useCallback(async () => {
    try {
      const [rs, ss] = await Promise.all([
        getEvalRuns(undefined, 100),
        getEvalSuites().catch(() => [] as EvalSuite[]),
      ]);
      setRuns(rs);
      setSuites(Object.fromEntries(ss.map(s => [s.id, s])));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load runs");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    setLoading(true);
    load();
    // Eval runs are SYNCHRONOUS today (the run route blocks and returns the summary),
    // so nothing streams `eval.*` yet. The 60s interval is the real refresh — it makes a
    // run started elsewhere appear — and the kernel subscription is the forward-looking
    // hook for when runs move onto the job kernel (then `job.state` will fire per run).
    const t = setInterval(load, 60_000);
    const unsub = subscribeKernelEvents(() => load(), { kinds: ["eval.", "job.state"] });
    return () => { clearInterval(t); unsub(); };
  }, [load]);

  async function open(runId: string) {
    setError(null);
    try { setOpenRun(await getEvalRun(runId)); }
    catch (e) { setError(e instanceof Error ? e.message : "Failed to open run"); }
  }

  if (openRun) {
    return <RunDetail run={openRun} suiteName={suites[openRun.suite_id]?.name} onBack={() => { setOpenRun(null); load(); }} />;
  }

  const succeeded = runs.filter(r => r.status === "succeeded").length;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", background: "var(--bg-0)", color: "var(--t1)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "16px 20px 12px", borderBottom: "1px solid var(--bg-3)" }}>
        <div style={{ fontSize: 13, fontWeight: 600 }}>Runs</div>
        <div style={{ flex: 1 }} />
        <Button variant="ghost" onClick={load} className="h-auto p-0 font-normal" style={{ background: "none", border: "1px solid var(--bg-3)", color: "var(--t2)", borderRadius: 4, cursor: "pointer", fontSize: 11, padding: "3px 9px" }}>Refresh</Button>
      </div>

      <div style={{ flex: 1, overflowY: "auto", padding: 20 }}>
        {loading && <p style={{ color: "var(--t3)", fontSize: 13 }}>Loading…</p>}
        {error && <p style={{ color: "var(--red4, #ef4444)", fontSize: 13, marginBottom: 12 }}>{error}</p>}

        {!loading && runs.length > 0 && (
          <MiniStatRow>
            <MiniStat value={runs.length} label="Runs" />
            <MiniStat value={succeeded} label="Succeeded" tone="var(--grn4)" />
          </MiniStatRow>
        )}

        {!loading && runs.length === 0 && (
          <div style={{ textAlign: "center", paddingTop: 60, color: "var(--t3)" }}>
            <div style={{ fontSize: 28, marginBottom: 12 }}>📊</div>
            <div style={{ fontSize: 15, fontWeight: 500, color: "var(--t2)", marginBottom: 6 }}>No runs yet</div>
            <div style={{ fontSize: 12 }}>Run a suite from the Suites tab — its result lands here as a replicated band.</div>
          </div>
        )}

        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {runs.map(r => (
            <RunCard key={r.id} run={r} suiteName={suites[r.suite_id]?.name} onOpen={() => open(r.id)} />
          ))}
        </div>
      </div>
    </div>
  );
}

// ── Run card ──────────────────────────────────────────────────────────────────

function RunCard({ run, suiteName, onOpen }: { run: EvalRun; suiteName?: string; onOpen: () => void }) {
  const s = run.summary || {};
  const pr = s.pass_rate;
  return (
    <div style={{ background: "var(--bg-1)", border: "1px solid var(--bg-3)", borderRadius: 6, padding: "11px 14px", cursor: "pointer", display: "flex", alignItems: "center", gap: 12 }}
      onClick={onOpen}>
      <StatusChip hue={STATUS_HUE[run.status] ?? "muted"}>{run.status}</StatusChip>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: "var(--t1)" }}>{suiteName ?? run.suite_id}</div>
        <div style={{ fontSize: 11, color: "var(--t3)", marginTop: 2 }}>
          {relTime(run.started_at)} · {run.iterations} iter
          {s.total != null && <> · {s.stable_pass}/{s.total} stable</>}
          {s.flaky ? <> · <span style={{ color: "var(--amb4, #f59e0b)" }}>{s.flaky} flaky</span></> : null}
        </div>
      </div>
      {pr != null && (
        <div style={{ textAlign: "right" }}>
          <div style={{ fontSize: 15, fontWeight: 700, color: pr >= 0.999 ? "var(--grn4)" : "var(--t1)", fontVariantNumeric: "tabular-nums" }}>{(pr * 100).toFixed(1)}%</div>
          <div style={{ fontSize: 11, color: "var(--t3)" }}>pass rate</div>
        </div>
      )}
    </div>
  );
}

// ── Run detail ──────────────────────────────────────────────────────────────────

function RunDetail({ run, suiteName, onBack }: {
  run: EvalRun & { results: EvalResult[] }; suiteName?: string; onBack: () => void;
}) {
  const s = run.summary || {};
  const pct = (n?: number | null) => (n == null ? "—" : `${(n * 100).toFixed(1)}%`);

  const columns: TableColumnsType<EvalResult & { key: React.Key }> = [
    { title: "Case", dataIndex: "case_id", key: "case_id",
      render: (v: string) => <code style={{ fontFamily: "var(--font-mono)", fontSize: 11 }}>{v}</code> },
    { title: "Iter", dataIndex: "iteration", key: "iteration", width: 60, align: "right" },
    { title: "Passed", dataIndex: "passed", key: "passed", width: 90,
      render: (v: boolean | null) => <BoolChip v={v} yes="pass" no="fail" /> },
    { title: "Correct", dataIndex: "correct", key: "correct", width: 90,
      render: (v: boolean | null) => <BoolChip v={v} yes="correct" no="wrong" /> },
    { title: "ms", dataIndex: "duration_ms", key: "duration_ms", width: 70, align: "right",
      render: (v: number | null) => (v == null ? "—" : v.toFixed(1)) },
    { title: "Fired", dataIndex: "fired", key: "fired",
      render: (v: string[]) => v && v.length
        ? <span style={{ fontSize: 11 }}>{v.map(n => <code key={n} style={{ fontFamily: "var(--font-code)", color: "var(--amb4, #f59e0b)", marginRight: 6 }}>{n}</code>)}</span>
        : <span style={{ color: "var(--t3)" }}>—</span> },
    { title: "Error", dataIndex: "error", key: "error",
      render: (v: string) => v ? <span title={v} style={{ color: "var(--red4, #ef4444)", fontSize: 11 }}>{v.slice(0, 60)}</span> : <span style={{ color: "var(--t3)" }}>—</span> },
  ];

  const dataSource = run.results.map((r, i) => ({ ...r, key: i }));

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", background: "var(--bg-0)", color: "var(--t1)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "16px 20px 12px", borderBottom: "1px solid var(--bg-3)" }}>
        <StatusChip hue={STATUS_HUE[run.status] ?? "muted"}>{run.status}</StatusChip>
        <div style={{ fontSize: 13, fontWeight: 600 }}>{suiteName ?? run.suite_id}</div>
        <div style={{ flex: 1 }} />
        <Button variant="ghost" onClick={onBack} className="h-auto p-0 font-normal" style={{ background: "none", border: "none", color: "var(--t3)", cursor: "pointer", fontSize: 12 }}>← All runs</Button>
      </div>

      <div style={{ flex: 1, overflowY: "auto", padding: 20 }}>
        <MiniStatRow>
          <MiniStat value={pct(s.pass_rate)} label="Pass rate (stable)" tone={(s.pass_rate ?? 0) >= 0.999 ? "var(--grn4)" : "var(--t1)"} />
          <MiniStat value={s.total != null ? `${s.stable_pass}/${s.total}` : "—"} label="Stable pass" />
          <MiniStat value={s.flaky ?? 0} label="Flaky" tone={(s.flaky ?? 0) > 0 ? "var(--amb4, #f59e0b)" : "var(--t1)"} />
          <MiniStat value={s.errors ?? 0} label="Errors" tone={(s.errors ?? 0) > 0 ? "var(--red4, #ef4444)" : "var(--t1)"} />
          {s.robustness != null && <MiniStat value={pct(s.robustness)} label="Robustness" />}
          {s.accuracy != null && <MiniStat value={pct(s.accuracy)} label="Accuracy" />}
        </MiniStatRow>

        <div style={{ fontSize: 11, color: "var(--t3)", marginBottom: 12 }}>
          {run.iterations} iteration{run.iterations === 1 ? "" : "s"} · started {relTime(run.started_at)} · run <code style={{ fontFamily: "var(--font-code)" }}>{run.id}</code>
        </div>

        <AugTable<EvalResult & { key: React.Key }>
          columns={columns}
          dataSource={dataSource}
          pagination={run.results.length > 50 ? { pageSize: 50, size: "small" } : false}
          scroll={{ x: "max-content" }}
        />
      </div>
    </div>
  );
}

function BoolChip({ v, yes, no }: { v: boolean | null; yes: string; no: string }) {
  if (v == null) return <span style={{ color: "var(--t3)", fontSize: 11 }}>—</span>;
  return <StatusChip hue={v ? "positive" : "negative"} strength="soft">{v ? yes : no}</StatusChip>;
}

function relTime(iso: string): string {
  try {
    const diff = Date.now() - new Date(iso).getTime();
    const m = Math.floor(diff / 60000);
    if (m < 2)  return "just now";
    if (m < 60) return `${m}m ago`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h}h ago`;
    return `${Math.floor(h / 24)}d ago`;
  } catch { return ""; }
}
