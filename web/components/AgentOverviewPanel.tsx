"use client";
/* ── Agent Workspace · Overview (native cards) ──────────────────────────────
   Per-agent run history + quality + (when obs.mlflow is on) MLflow trace stats,
   rendered as Aughor's own cards over /agents/custom/{id}/observability. MLflow
   stays backend-only — no iframe/CSP/cross-origin exposure. Degrades to
   history-only when tracing is off (trace_stats == null). */
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { StatusChip, type ChipHue } from "@/components/brief/StatusChip";
import { compactNumber, formatTimestamp } from "@/lib/format";
import {
  getAgentObservability, listUserAgents,
  type AgentObservability, type UserAgent,
} from "@/lib/api";

function Tile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div style={{
      flex: "1 1 120px", minWidth: 120, padding: "12px 14px",
      background: "var(--bg-1)", border: "1px solid var(--b1)", borderRadius: "var(--r3)",
    }}>
      <div style={{ fontSize: 11, color: "var(--t3)", textTransform: "uppercase", letterSpacing: 0.4 }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 600, color: "var(--t1)", marginTop: 4 }}>{value}</div>
      {sub && <div style={{ fontSize: 11, color: "var(--t3)", marginTop: 2 }}>{sub}</div>}
    </div>
  );
}

const STATUS_HUE: Record<string, ChipHue> = {
  complete: "positive", running: "info", paused: "caution",
  failed: "negative", timed_out: "negative",
};

export function AgentOverviewPanel({ onManage }: { onManage?: () => void }) {
  const [agents, setAgents] = useState<UserAgent[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [obs, setObs] = useState<AgentObservability | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    listUserAgents()
      .then(a => { setAgents(a); setSelected(s => s ?? a[0]?.id ?? null); })
      .catch(() => setAgents([]));
  }, []);

  useEffect(() => {
    if (!selected) { setObs(null); return; }
    setLoading(true);
    getAgentObservability(selected)
      .then(setObs).catch(() => setObs(null)).finally(() => setLoading(false));
  }, [selected]);

  const agent = agents.find(a => a.id === selected) ?? null;
  const stats = obs?.trace_stats ?? null;

  if (agents.length === 0) {
    return (
      <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 12, color: "var(--t3)" }}>
        <div style={{ fontSize: 13 }}>No agents yet.</div>
        {onManage && <Button variant="outline" size="sm" onClick={onManage}>Create an agent</Button>}
      </div>
    );
  }

  return (
    <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>
      {/* Agent picker */}
      <div style={{ width: 230, flexShrink: 0, borderRight: "1px solid var(--b1)", overflowY: "auto", padding: 8, display: "flex", flexDirection: "column", gap: 4 }}>
        {agents.map(a => (
          <Button
            key={a.id}
            variant={a.id === selected ? "secondary" : "ghost"}
            onClick={() => setSelected(a.id)}
            className="w-full justify-start h-auto py-2 flex-col items-start gap-0.5"
          >
            <span style={{ fontSize: 13, fontWeight: 500, color: "var(--t1)" }}>{a.name}</span>
            <span style={{ fontSize: 11, color: "var(--t3)" }}>
              {a.enabled ? "enabled" : "paused"}
              {a.last_eval ? ` · ${a.last_eval.passed}/${a.last_eval.total} passing` : ""}
            </span>
          </Button>
        ))}
      </div>

      {/* Detail */}
      <div style={{ flex: 1, overflowY: "auto", padding: "18px 22px" }}>
        {!agent ? null : (
          <>
            <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginBottom: 4 }}>
              <span style={{ fontSize: 16, fontWeight: 600, color: "var(--t1)" }}>{agent.name}</span>
              {agent.last_eval && (
                <span style={{ fontSize: 12, color: "var(--t3)" }}>
                  quality {agent.last_eval.passed}/{agent.last_eval.total}
                </span>
              )}
              {onManage && <Button variant="ghost" size="xs" onClick={onManage} className="ml-auto">Manage</Button>}
            </div>
            {agent.instructions && (
              <div style={{ fontSize: 12, color: "var(--t2)", marginBottom: 16, maxWidth: 640, lineHeight: 1.5 }}>
                {agent.instructions}
              </div>
            )}

            {/* Stat tiles */}
            <div style={{ display: "flex", flexWrap: "wrap", gap: 10, marginBottom: 18 }}>
              <Tile label="Runs" value={loading ? "…" : String(obs?.run_count ?? 0)} sub="investigations" />
              {stats ? (
                <>
                  <Tile label="Traces" value={compactNumber(stats.trace_count)} sub={`${stats.error_count} errored`} />
                  <Tile label="Tokens" value={compactNumber(stats.total_tokens)} />
                  <Tile label="Cost" value={`$${stats.total_cost.toFixed(2)}`} />
                  <Tile label="Latency p50" value={stats.latency_p50_ms != null ? `${(stats.latency_p50_ms / 1000).toFixed(1)}s` : "—"}
                        sub={stats.latency_p90_ms != null ? `p90 ${(stats.latency_p90_ms / 1000).toFixed(1)}s` : undefined} />
                </>
              ) : (
                <div style={{ flex: "1 1 100%", fontSize: 12, color: "var(--t3)", padding: "8px 2px" }}>
                  MLflow tracing is off — showing run history only. Enable{" "}
                  <code style={{ fontSize: 11 }}>obs.mlflow</code> for token, cost & latency stats.
                </div>
              )}
            </div>

            {/* Recent runs */}
            <div style={{ fontSize: 12, fontWeight: 600, color: "var(--t2)", marginBottom: 8 }}>Recent runs</div>
            {(!obs || obs.runs.length === 0) ? (
              <div style={{ fontSize: 12, color: "var(--t3)" }}>{loading ? "Loading…" : "No runs yet for this agent."}</div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 1 }}>
                {obs.runs.map(r => (
                  <div key={r.id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 10px", background: "var(--bg-1)", border: "1px solid var(--b1)", borderRadius: "var(--r2)" }}>
                    <span style={{ flex: 1, fontSize: 12, color: "var(--t1)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {r.headline || r.question}
                    </span>
                    <StatusChip hue={STATUS_HUE[r.status] ?? "muted"} strength="soft">{r.status}</StatusChip>
                    <span style={{ fontSize: 11, color: "var(--t3)", flexShrink: 0, width: 110, textAlign: "right" }}>{formatTimestamp(r.started_at, "short")}</span>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
