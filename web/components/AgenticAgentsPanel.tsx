"use client";

/**
 * Agentic Ops · Agents — ONE kind-labelled roster over both agent kinds, with a
 * master–detail body. Consolidates three surfaces that each held a slice of the
 * same question (AgentOverviewPanel, AgentsAdminPanel, page.tsx's AgentsPanel):
 *
 * - charter (built-in, job-metering spend): detail = identity read-out +
 *   GOVERNANCE (enabled / budget / model pin — the real knobs; there are no
 *   per-agent temperature or tool toggles because those mechanisms do not
 *   exist here, and rendering them would be describing a fiction).
 * - persona (user-defined, session-log spend): detail = OVERVIEW (H3's honest
 *   run view: everything it did, spend or the flag that would measure it,
 *   trace drill-ins) + CONFIGURE (instructions, bindings, goldens — the agent's
 *   own regression suite) + hire-from-pack.
 *
 * Charter ≠ persona stays labelled on every row — the collision Wave H dodged
 * twice does not come back in the merge.
 */
import { useCallback, useEffect, useState } from "react";

import { CreateAgentFlow } from "@/components/agentops/CreateAgentFlow";
import { AgentMap } from "@/components/agentops/AgentMap";
import { RunTimeline, type TimelineRun } from "@/components/agentops/RunTimeline";
import { rangeParams, type TimeRange } from "@/components/agentops/useTimeRange";
import { Button } from "@/components/ui/button";
import { StatusChip } from "@/components/brief/StatusChip";
import {
  createAgentGolden, createUserAgent,
  createUserAgentFromTemplate, deleteAgentGolden, deleteUserAgent,
  evaluateUserAgent, getAgentGuardrails, getAgentObservability, getAgents,
  getConnections, getJobs,
  getLlmConfig, getPacks, listAgentGoldens, listAgentRevisions,
  listAgentTemplates, listDocuments, listUserAgents, patchAgent, patchUserAgent,
  restoreAgentRevision, setAgentGuardrails,
  type AgentEvalResult, type AgentGolden, type AgentGuardrails, type AgentObservability,
  type AgentRevision, type AgentRosterEntry, type AgentTemplate, type Connection,
  type DocumentEntry, type LlmConfig, type PackSummary, type UserAgent,
} from "@/lib/api";
import { evalChip } from "@/lib/agentEval";
import { compactNumber, formatTimestamp } from "@/lib/format";
import { BACKEND_LABEL } from "@/lib/llmMeta";

type Selection =
  | { kind: "charter"; id: string }
  | { kind: "persona"; id: string }
  | { kind: "hire" }
  | null;

const STATUS_HUE: Record<string, "positive" | "info" | "caution" | "negative" | "muted"> = {
  complete: "positive", running: "info", paused: "caution",
  failed: "negative", timed_out: "negative",
};

function fmtBudget(n: number | null): string {
  return n == null ? "role default" : compactNumber(n);
}

export function AgenticAgentsPanel({ workspaceId, workspaceName, onOpenTrace, focusAgent,
  range, createSignal, onOpenConnection, onOpenAutomations, onOpenIntegrations }: {
  workspaceId?: string;
  workspaceName?: string;
  /** CR1 drill-in: open a run's trace in the Activity layer's runs mode. */
  onOpenTrace?: (investigationId: string) => void;
  /** DS-5 drill-in: where a node on the agent's Map leads. Each is optional, and an
   *  absent one renders no Open control rather than a button that goes nowhere. */
  onOpenConnection?: (connectionId: string) => void;
  onOpenAutomations?: (automationId: string) => void;
  onOpenIntegrations?: () => void;
  /** An agent opened from the Overview table — selected on arrival. */
  focusAgent?: { id: string; kind: "charter" | "persona" } | null;
  /** The surface's shared window — the agent page's own figures scope to it. */
  range?: TimeRange;
  /** Bumped by the workspace's "+ Create agent" control, from any layer. A counter, not a
   *  flag: pressing Create while already here must re-open the flow. */
  createSignal?: number;
}) {
  const [charters, setCharters] = useState<AgentRosterEntry[]>([]);
  const [personas, setPersonas] = useState<UserAgent[]>([]);
  const [selected, setSelected] = useState<Selection>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(() => {
    getAgents(workspaceId).then(setCharters).catch(() => setCharters([]));
    listUserAgents().then(setPersonas).catch(() => setPersonas([]));
  }, [workspaceId]);

  useEffect(() => { reload(); }, [reload]);
  useEffect(() => {
    setSelected(prev => prev ?? (personas[0] ? { kind: "persona", id: personas[0].id }
      : charters[0] ? { kind: "charter", id: charters[0].id } : null));
  }, [personas, charters]);
  useEffect(() => {
    if (focusAgent) setSelected({ kind: focusAgent.kind, id: focusAgent.id });
  }, [focusAgent]);
  useEffect(() => {
    if (createSignal) setSelected({ kind: "hire" });
  }, [createSignal]);

  const charter = selected?.kind === "charter"
    ? charters.find(c => c.id === selected.id) : undefined;
  const persona = selected?.kind === "persona"
    ? personas.find(p => p.id === selected.id) : undefined;

  return (
    <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>
      {/* ── the one roster ── */}
      <div style={{ width: 268, flexShrink: 0, borderRight: "1px solid var(--b1)",
        overflowY: "auto", padding: 10 }}>
        <div style={{ display: "flex", alignItems: "center", padding: "2px 6px 8px" }}>
          <span className="aug-label" style={{ color: "var(--t2)" }}>Custom agents</span>
          <span style={{ flex: 1 }} />
          <Button variant="secondary" size="xs"
            onClick={() => setSelected({ kind: "hire" })}>+ Create agent</Button>
        </div>
        {personas.length === 0 && (
          <div style={{ padding: "0 6px 10px" }}>
            <p className="aug-fs-sm" style={{ color: "var(--t2)", margin: "0 0 6px" }}>
              No custom agents yet. An agent is a scope and a stance — where it may look,
              and how it should think.
            </p>
            <Button variant="secondary" size="xs"
              onClick={() => setSelected({ kind: "hire" })}>Create your first agent</Button>
          </div>
        )}
        {personas.map(p => (
          <RosterRow key={p.id} name={p.name} kind="persona" enabled={p.enabled}
            sub={evalChip(p.last_eval, p.eval_basis)?.label}
            active={selected?.kind === "persona" && selected.id === p.id}
            onClick={() => setSelected({ kind: "persona", id: p.id })} />
        ))}
        <div className="aug-label" style={{ color: "var(--t2)", padding: "12px 6px 8px" }}>
          Charters {workspaceName ? `· ${workspaceName}` : "· Org"}
        </div>
        {charters.map(c => (
          <RosterRow key={c.id} name={c.name} kind="charter"
            enabled={c.governance.enabled} sub={c.role} reserved={c.reserved}
            active={selected?.kind === "charter" && selected.id === c.id}
            onClick={() => setSelected({ kind: "charter", id: c.id })} />
        ))}
      </div>

      {/* ── detail ── */}
      <div style={{ flex: 1, overflowY: "auto" }}>
        {error && (
          <div style={{ margin: "12px 20px 0", padding: "8px 12px", fontSize: 12,
            borderRadius: "var(--r2)", background: "var(--red1)",
            border: "1px solid var(--red2)", color: "var(--red5)" }}>{error}</div>
        )}
        {selected?.kind === "hire" ? (
          <CreateAgentFlow
            onCreated={a => { reload(); setSelected({ kind: "persona", id: a.id }); }}
            onCancel={() => setSelected(personas[0]
              ? { kind: "persona", id: personas[0].id }
              : charters[0] ? { kind: "charter", id: charters[0].id } : null)} />
        ) : persona ? (
          <AgentDetail key={persona.id} agent={persona} onChanged={reload}
            onDeleted={() => { setSelected(null); reload(); }}
            onError={setError} onOpenTrace={onOpenTrace}
            onOpenConnection={onOpenConnection}
            onOpenAutomations={onOpenAutomations}
            onOpenIntegrations={onOpenIntegrations} />
        ) : charter ? (
          <CharterDetail key={charter.id} charter={charter} workspaceId={workspaceId} range={range}
            onChanged={reload} onError={setError} />
        ) : (
          <div style={{ padding: 24, fontSize: 12, color: "var(--t3)" }}>Select an agent.</div>
        )}
      </div>
    </div>
  );
}

function RosterRow({ name, kind, enabled, sub, active, reserved, onClick }: {
  name: string; kind: "charter" | "persona"; enabled: boolean; sub?: string;
  active: boolean; reserved?: boolean; onClick: () => void;
}) {
  return (
    <Button variant="ghost" size="sm" onClick={onClick}
      style={{ display: "block", width: "100%", height: "auto", textAlign: "left",
        padding: "7px 10px", marginBottom: 2, whiteSpace: "normal",
        opacity: reserved ? 0.55 : 1,
        background: active ? "var(--bg-sel)" : undefined }}>
      <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <span style={{ fontSize: 13, fontWeight: 500, overflow: "hidden",
          textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1, minWidth: 0 }}>{name}</span>
        <StatusChip hue={kind === "charter" ? "info" : "accent"} strength="soft">
          {kind === "persona" ? "custom" : kind}
        </StatusChip>
        {!enabled && <StatusChip hue="caution" strength="soft">paused</StatusChip>}
      </span>
      {sub && (
        <span style={{ display: "block", fontSize: 11, color: "var(--t2)", marginTop: 2,
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{sub}</span>
      )}
    </Button>
  );
}

// ── custom-agent detail ───────────────────────────────────────────────────────────────

function AgentDetail({ agent, onChanged, onDeleted, onError, onOpenTrace,
  onOpenConnection, onOpenAutomations, onOpenIntegrations }: {
  agent: UserAgent; onChanged: () => void; onDeleted: () => void;
  onError: (e: string | null) => void;
  onOpenTrace?: (investigationId: string) => void;
  /** DS-5 — where the map's nodes lead. Optional: a destination this shell does not
   *  offer simply renders no Open control, rather than a button that goes nowhere. */
  onOpenConnection?: (connectionId: string) => void;
  onOpenAutomations?: (automationId: string) => void;
  onOpenIntegrations?: () => void;
}) {
  const [tab, setTab] = useState<"overview" | "map" | "configure">("overview");
  const [busy, setBusy] = useState(false);

  const togglePause = async () => {
    setBusy(true);
    try { await patchUserAgent(agent.id, { enabled: !agent.enabled }); onChanged(); }
    catch (e) { onError(String((e as Error)?.message || e)); }
    finally { setBusy(false); }
  };

  return (
    <div style={{ padding: 20 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 15, fontWeight: 600 }}>{agent.name}</div>
          <div style={{ fontSize: 11, color: "var(--t2)", marginTop: 2 }}>
            custom · {agent.connection_id || "any connection"}
            {agent.schema_scope ? ` · ${agent.schema_scope}` : ""}
            {agent.pack_ids.length > 0 ? ` · ${agent.pack_ids.length} pack${agent.pack_ids.length === 1 ? "" : "s"}` : ""}
          </div>
        </div>
        {(() => {
          const chip = evalChip(agent.last_eval, agent.eval_basis);
          return chip && (
            <span title={chip.detail}>
              <StatusChip hue={chip.hue} strength="soft">{chip.label}</StatusChip>
            </span>
          );
        })()}
        <StatusChip hue={agent.enabled ? "positive" : "caution"} strength="soft">
          {agent.enabled ? "active" : "paused"}
        </StatusChip>
        <Button variant="ghost" size="xs" disabled={busy} onClick={togglePause}>
          {agent.enabled ? "Pause" : "Resume"}
        </Button>
        <Button variant={tab === "overview" ? "secondary" : "ghost"} size="xs"
          onClick={() => setTab("overview")}>Overview</Button>
        {/* DS-5 — "Map", not "Design": that word is the automation card's button and the
            automation canvas's own mode label, and this surface edits nothing. */}
        <Button variant={tab === "map" ? "secondary" : "ghost"} size="xs"
          onClick={() => setTab("map")}>Map</Button>
        <Button variant={tab === "configure" ? "secondary" : "ghost"} size="xs"
          onClick={() => setTab("configure")}>Configure</Button>
      </div>
      {tab === "overview" ? (
        <PersonaOverview agent={agent} onOpenTrace={onOpenTrace} />
      ) : tab === "map" ? (
        <AgentMap agent={agent}
          onOpenConnection={onOpenConnection}
          onOpenAutomations={onOpenAutomations}
          onOpenIntegrations={onOpenIntegrations} />
      ) : (
        <PersonaConfigure agent={agent} onChanged={onChanged}
          onDeleted={onDeleted} onError={onError} />
      )}
    </div>
  );
}

/** H3's honest run view, unchanged in spirit: everything the agent did, spend
 *  or the flag that would measure it — never a confident zero. */
function PersonaOverview({ agent, onOpenTrace }: {
  agent: UserAgent; onOpenTrace?: (invId: string) => void;
}) {
  const [obs, setObs] = useState<AgentObservability | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    getAgentObservability(agent.id)
      .then(o => { if (alive) setObs(o); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [agent.id]);

  if (loading) return <div style={{ fontSize: 12, color: "var(--t3)" }}>Loading…</div>;
  if (!obs) return <div style={{ fontSize: 12, color: "var(--t3)" }}>No observability data.</div>;

  const spend = obs.spend;
  const runs = obs.runs || [];
  const deep = runs.filter(r => r.kind !== "chat").length;
  const quick = runs.length - deep;

  return (
    <>
      {agent.instructions && (
        <div style={{ padding: "10px 14px", background: "var(--bg-2)",
          border: "1px solid var(--b1)", borderRadius: "var(--r3)", fontSize: 12,
          color: "var(--t2)", lineHeight: 1.5, marginBottom: 14, whiteSpace: "pre-wrap" }}>
          {agent.instructions}
        </div>
      )}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 10, marginBottom: 16 }}>
        <Tile label="Runs" value={String(obs.run_count)}
          sub={runs.length ? `${deep} deep · ${quick} quick` : "none yet"} />
        {spend?.measured ? (
          <>
            <Tile label="Model calls" value={compactNumber(spend.calls)} />
            <Tile label="Tokens" value={compactNumber(spend.total_tokens)} />
            <Tile label="Cost" value={spend.cost_usd != null ? `$${spend.cost_usd.toFixed(2)}` : "—"}
              sub={spend.cost_is_complete ? undefined : "some models unpriced"} />
          </>
        ) : null}
        {obs.trace_stats?.latency_p90_ms != null && (
          <Tile label="p90 latency" value={`${(obs.trace_stats.latency_p90_ms / 1000).toFixed(1)}s`} />
        )}
      </div>
      <div className="aug-label" style={{ color: "var(--t2)", marginBottom: 6 }}>Run history</div>
      <div style={{ marginBottom: 16 }}>
        <RunTimeline emptyNote="No runs yet for this agent."
          onOpen={onOpenTrace}
          runs={runs.slice(0, 20).map(r => ({
            id: r.id, state: r.status, at: r.started_at, durationMs: null,
            label: r.headline || r.question,
          }))} />
      </div>
      <div className="aug-label" style={{ color: "var(--t2)", marginBottom: 6 }}>Recent runs</div>
      {runs.length === 0 ? (
        <div className="aug-fs-sm" style={{ color: "var(--t2)" }}>No runs yet for this agent.</div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 1 }}>
          {runs.map(r => (
            <div key={r.id} style={{ display: "flex", alignItems: "center", gap: 10,
              padding: "8px 10px", background: "var(--bg-1)",
              border: "1px solid var(--b1)", borderRadius: "var(--r2)" }}>
              <span style={{ flex: 1, fontSize: 12, color: "var(--t1)", overflow: "hidden",
                textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {r.headline || r.question}
              </span>
              <StatusChip hue="muted" strength="soft">
                {r.kind === "chat" ? `quick${r.query_count > 1 ? ` ·${r.query_count}` : ""}` : "deep"}
              </StatusChip>
              <StatusChip hue={STATUS_HUE[r.status] ?? "muted"} strength="soft">{r.status}</StatusChip>
              <span style={{ fontSize: 11, color: "var(--t3)", flexShrink: 0, width: 110,
                textAlign: "right" }}>{formatTimestamp(r.started_at, "short")}</span>
              {onOpenTrace && r.kind !== "chat" && (
                <Button variant="ghost" size="xs" onClick={() => onOpenTrace(r.id)}
                  title="Open this run's trace">trace</Button>
              )}
            </div>
          ))}
        </div>
      )}
    </>
  );
}

/** The agent's editable surface — fields, bindings and the golden suite
 *  (ported from AgentsAdminPanel, which this panel replaces). */
function PersonaConfigure({ agent, onChanged, onDeleted, onError }: {
  agent: UserAgent; onChanged: () => void; onDeleted: () => void;
  onError: (e: string | null) => void;
}) {
  const [form, setForm] = useState({
    name: agent.name, instructions: agent.instructions,
    connection_id: agent.connection_id, schema_scope: agent.schema_scope,
    doc_ids: agent.doc_ids, pack_ids: agent.pack_ids,
  });
  const [connections, setConnections] = useState<Connection[]>([]);
  const [documents, setDocuments] = useState<DocumentEntry[]>([]);
  const [packs, setPacks] = useState<PackSummary[]>([]);
  const [goldens, setGoldens] = useState<AgentGolden[]>([]);
  const [goldenDraft, setGoldenDraft] = useState({ question: "", reference_sql: "" });
  const [saving, setSaving] = useState(false);
  const [evaluating, setEvaluating] = useState(false);
  const [evalResult, setEvalResult] = useState<AgentEvalResult | null>(null);

  useEffect(() => {
    getConnections().then(setConnections).catch(() => {});
    listDocuments().then(setDocuments).catch(() => {});
    getPacks().then(r => setPacks((r.packs || []).filter(p => p.ok))).catch(() => {});
    listAgentGoldens(agent.id).then(setGoldens).catch(() => {});
  }, [agent.id]);

  // Re-seed the form when the SAVED configuration moves under it — which happens on a
  // restore. Without this the fields keep showing the configuration that was just replaced,
  // and the next "Save changes" quietly undoes the restore the user asked for. Keyed on
  // config_rev, so typing is never interrupted: it only fires when what is stored changed.
  useEffect(() => {
    setForm({
      name: agent.name, instructions: agent.instructions,
      connection_id: agent.connection_id, schema_scope: agent.schema_scope,
      doc_ids: agent.doc_ids, pack_ids: agent.pack_ids,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agent.config_rev]);

  const save = async () => {
    if (!form.name.trim()) { onError("Name is required."); return; }
    setSaving(true);
    onError(null);
    try { await patchUserAgent(agent.id, form); onChanged(); }
    catch (e) { onError(e instanceof Error ? e.message : "Save failed."); }
    finally { setSaving(false); }
  };

  const remove = async () => {
    if (!window.confirm(`Delete agent “${agent.name}”? Its instructions and bindings are removed; documents stay.`)) return;
    await deleteUserAgent(agent.id);
    onDeleted();
  };

  const addGolden = async () => {
    if (!goldenDraft.question.trim() || !goldenDraft.reference_sql.trim()) return;
    try {
      const g = await createAgentGolden(agent.id, goldenDraft);
      setGoldens(gs => [...gs, g]);
      setGoldenDraft({ question: "", reference_sql: "" });
    } catch (e) { onError(e instanceof Error ? e.message : "Add golden failed."); }
  };

  const runEvaluation = async () => {
    setEvaluating(true);
    onError(null);
    try { setEvalResult(await evaluateUserAgent(agent.id)); onChanged(); }
    catch (e) { onError(e instanceof Error ? e.message : "Evaluation failed."); }
    finally { setEvaluating(false); }
  };

  const toggleIn = (key: "doc_ids" | "pack_ids", id: string) =>
    setForm(f => ({ ...f, [key]: f[key].includes(id)
      ? f[key].filter(x => x !== id) : [...f[key], id] }));

  return (
    <div style={{ maxWidth: 640, display: "flex", flexDirection: "column", gap: 14 }}>
      <label style={{ display: "flex", flexDirection: "column", gap: 5 }}>
        <span className="aug-label">Name</span>
        <input className="aug-input" value={form.name} maxLength={120}
          onChange={e => setForm(f => ({ ...f, name: e.target.value }))} />
      </label>
      <label style={{ display: "flex", flexDirection: "column", gap: 5 }}>
        <span className="aug-label">Instructions</span>
        <textarea className="aug-input" rows={6} value={form.instructions} maxLength={8000}
          placeholder="Standing guidance this agent applies to every answer — domain focus, definitions to prefer, tone. It refines, never overrides, safety and grounding rules."
          onChange={e => setForm(f => ({ ...f, instructions: e.target.value }))} />
      </label>
      <label style={{ display: "flex", flexDirection: "column", gap: 5 }}>
        <span className="aug-label">Connection</span>
        <select className="aug-input" value={form.connection_id}
          onChange={e => setForm(f => ({ ...f, connection_id: e.target.value }))}>
          <option value="">Any (use the ask&rsquo;s connection)</option>
          {connections.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
      </label>
      <label style={{ display: "flex", flexDirection: "column", gap: 5 }}>
        <span className="aug-label">Schema scope</span>
        <input className="aug-input" value={form.schema_scope} maxLength={120}
          placeholder="e.g. finance — leave empty for all schemas"
          onChange={e => setForm(f => ({ ...f, schema_scope: e.target.value }))} />
        <span style={{ fontSize: 11, color: "var(--t3)" }}>
          When set, the agent answers within this schema; asking it about another schema is rejected.
        </span>
      </label>
      <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
        <span className="aug-label">Documents</span>
        {documents.length === 0 ? (
          <span style={{ fontSize: 12, color: "var(--t3)" }}>
            No uploaded documents yet — an agent only sees the documents attached to it.
          </span>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 4, maxHeight: 160,
            overflowY: "auto", padding: "8px 10px", border: "1px solid var(--b1)",
            borderRadius: "var(--r2)" }}>
            {documents.map(d => (
              <label key={d.doc_id} style={{ display: "flex", alignItems: "center", gap: 8,
                fontSize: 12, color: "var(--t2)", cursor: "pointer" }}>
                <input type="checkbox" checked={form.doc_ids.includes(d.doc_id)}
                  onChange={() => toggleIn("doc_ids", d.doc_id)} />
                <span style={{ overflow: "hidden", textOverflow: "ellipsis",
                  whiteSpace: "nowrap" }}>{d.title || d.filename}</span>
              </label>
            ))}
          </div>
        )}
      </div>
      {packs.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
          <span className="aug-label">Packs</span>
          <div style={{ display: "flex", flexDirection: "column", gap: 4, maxHeight: 130,
            overflowY: "auto", padding: "8px 10px", border: "1px solid var(--b1)",
            borderRadius: "var(--r2)" }}>
            {packs.map(p => (
              <label key={p.id} style={{ display: "flex", alignItems: "center", gap: 8,
                fontSize: 12, color: "var(--t2)", cursor: "pointer" }}>
                <input type="checkbox" checked={form.pack_ids.includes(p.id)}
                  onChange={() => toggleIn("pack_ids", p.id)} />
                <span>{p.name || p.id}</span>
              </label>
            ))}
          </div>
        </div>
      )}

      {/* the agent's own regression suite */}
      <div style={{ display: "flex", flexDirection: "column", gap: 6, padding: "12px 14px",
        border: "1px solid var(--b1)", borderRadius: "var(--r2)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span className="aug-label">Golden questions</span>
          <span style={{ fontSize: 11, color: "var(--t3)" }}>
            re-run after editing instructions or documents
          </span>
          <span style={{ marginLeft: "auto" }}>
            <Button size="xs" variant="outline" onClick={runEvaluation}
              disabled={evaluating || goldens.length === 0}>
              {evaluating ? "Evaluating…" : "Run evaluation"}
            </Button>
          </span>
        </div>
        {evalResult && (
          <div style={{ fontSize: 12, color: evalResult.passed === evalResult.total
            ? "var(--grn5)" : "var(--amb5)" }}>
            {evalResult.passed}/{evalResult.total} passing
            {evalResult.per_question.filter(p => !p.passed).slice(0, 3).map(p => (
              <div key={p.golden_id} style={{ color: "var(--t3)", fontSize: 12 }}>
                ✗ {p.question} — {p.error}
              </div>
            ))}
          </div>
        )}
        {goldens.map(g => (
          <div key={g.id} style={{ display: "flex", alignItems: "center", gap: 8,
            fontSize: 12, color: "var(--t2)" }}>
            <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis",
              whiteSpace: "nowrap" }} title={g.reference_sql}>{g.question}</span>
            <Button variant="ghost" size="xs" onClick={async () => {
              await deleteAgentGolden(agent.id, g.id);
              setGoldens(gs => gs.filter(x => x.id !== g.id));
            }}>Remove</Button>
          </div>
        ))}
        <input className="aug-input" placeholder="Golden question — e.g. How many active customers?"
          value={goldenDraft.question}
          onChange={e => setGoldenDraft(d => ({ ...d, question: e.target.value }))} />
        <textarea className="aug-input" rows={2}
          placeholder="Reference SQL (the known-correct answer; read-only)"
          value={goldenDraft.reference_sql}
          onChange={e => setGoldenDraft(d => ({ ...d, reference_sql: e.target.value }))} />
        <span>
          <Button size="xs" variant="secondary" onClick={addGolden}
            disabled={!goldenDraft.question.trim() || !goldenDraft.reference_sql.trim()}>
            Add golden
          </Button>
        </span>
      </div>

      <AgentGuardrailsSection agent={agent} onError={onError} />

      <AgentConfigHistory agent={agent} onChanged={onChanged} onError={onError} />

      <div style={{ display: "flex", gap: 8 }}>
        <Button onClick={save} disabled={saving}>{saving ? "Saving…" : "Save changes"}</Button>
        <Button variant="destructive" size="sm" onClick={remove}>Delete agent</Button>
      </div>
    </div>
  );
}

/** H6 + VA-7 — the configuration history, next to the fields that write it.
 *
 *  Only the settings that change how the agent answers are versioned, so a rename never
 *  shows up here. Restoring writes the old configuration forward as a new revision rather
 *  than rewinding: what was tried in between stays on the record.
 *
 *  VA-7: a row now says what the edit MOVED, and opens to show it. Before this it showed
 *  a truncated copy of the instructions, which meant two revisions differing only in
 *  schema scope looked identical, and two differing by one sentence of a long prompt
 *  looked identical too — a history that could be counted but not read. */

const FIELD_LABEL: Record<string, string> = {
  instructions: "Instructions",
  connection_id: "Connection",
  schema_scope: "Schema scope",
  doc_ids: "Documents",
  pack_ids: "Packs",
};

/** One governing value as text. Lists read as a count plus their members, because
 *  "3 documents" answers the question a reader actually has and the names answer the
 *  next one. An empty scope is the RESTRICTIVE case here — say so rather than showing a
 *  blank, which reads as "unset" and means the opposite. */
export function valueText(field: string, value: unknown): string {
  if (Array.isArray(value)) {
    return value.length ? `${value.length}: ${value.join(", ")}` : "none";
  }
  const text = String(value ?? "").trim();
  if (text) return text;
  return field === "instructions" ? "no instructions" : "not set";
}

function FieldDiff({ field, before, after }: {
  field: string; before: unknown; after: unknown;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 3, paddingTop: 6 }}>
      <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>
        {FIELD_LABEL[field] ?? field}
      </span>
      <div style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
        <div className="aug-fs-xs"
             style={{ flex: 1, minWidth: 0, color: "var(--t3)",
                      background: "var(--bg-1)", border: "1px solid var(--b1)",
                      borderRadius: "var(--r-chip)", padding: "4px 6px",
                      whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
          {valueText(field, before)}
        </div>
        <div className="aug-fs-xs"
             style={{ flex: 1, minWidth: 0, color: "var(--t2)",
                      background: "var(--bg-1)", border: "1px solid var(--border)",
                      borderRadius: "var(--r-chip)", padding: "4px 6px",
                      whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
          {valueText(field, after)}
        </div>
      </div>
    </div>
  );
}

/** VA-8 — the guardrails an operator has set on one agent.
 *
 *  Deliberately NOT part of the agent's governing configuration: a guardrail is a
 *  decision ABOUT an agent, not part of what the revision plane versions, and folding it
 *  in would mark every eval chip stale the moment somebody tightened a cap. So this saves
 *  on its own rather than riding the agent's Save button. */

const PII_COPY: Record<string, { label: string; hint: string }> = {
  off: { label: "Off", hint: "Results are shown exactly as the warehouse returned them." },
  redact: { label: "Redact", hint: "Sensitive values are masked; the rest of the row is shown. This is the platform default." },
  block: { label: "Block", hint: "A result containing sensitive values is withheld entirely — not shown with holes in it." },
};

export function AgentGuardrailsSection({ agent, onError }: {
  agent: UserAgent; onError: (e: string | null) => void;
}) {
  const [policy, setPolicy] = useState<AgentGuardrails | null>(null);
  const [modes, setModes] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    let alive = true;
    getAgentGuardrails(agent.id)
      .then(r => {
        if (!alive || !r) return;
        setPolicy(r.guardrails);
        // The vocabulary comes from the API, which reads it off the code. A mode this
        // build cannot enforce must never be offerable here.
        setModes(r.modes?.pii ?? []);
      })
      .catch(() => {});
    return () => { alive = false; };
  }, [agent.id]);

  const save = async (next: AgentGuardrails) => {
    setPolicy(next);
    setSaving(true);
    setSaved(false);
    onError(null);
    try {
      if (await setAgentGuardrails(agent.id, next)) setSaved(true);
      else onError("Could not save guardrails.");
    } finally { setSaving(false); }
  };

  if (!policy) return null;

  const capValue = policy.max_tokens_per_run;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <span className="aug-label">Guardrails</span>
      <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>
        Applied while this agent is answering, and saved on their own — tightening a
        guardrail does not change the agent&apos;s configuration or its evaluation.
      </span>

      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span className="aug-fs-sm" style={{ color: "var(--t2)", minWidth: 96 }}>
          Sensitive data
        </span>
        <select className="aug-input" style={{ maxWidth: 140 }} value={policy.pii}
          onChange={e => save({ ...policy, pii: e.target.value as AgentGuardrails["pii"] })}>
          {modes.map(m => (
            <option key={m} value={m}>{PII_COPY[m]?.label ?? m}</option>
          ))}
        </select>
        <span className="aug-fs-xs" style={{ flex: 1, minWidth: 0, color: "var(--t3)" }}>
          {PII_COPY[policy.pii]?.hint ?? ""}
        </span>
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span className="aug-fs-sm" style={{ color: "var(--t2)", minWidth: 96 }}>
          Tokens per run
        </span>
        <input className="aug-input" style={{ maxWidth: 140 }} type="number" min={1}
          placeholder="no cap"
          value={capValue ?? ""}
          onChange={e => {
            const raw = e.target.value.trim();
            const n = raw === "" ? null : Number(raw);
            // An empty field means "no cap". A zero would arm a budget breached by the
            // first token, which is an outage rather than a guardrail — the API refuses
            // it, and offering it here would only produce a 422.
            save({ ...policy, max_tokens_per_run: n && n > 0 ? Math.floor(n) : null });
          }} />
        <span className="aug-fs-xs" style={{ flex: 1, minWidth: 0, color: "var(--t3)" }}>
          {capValue
            ? `This agent stops once a run has spent ${compactNumber(capValue)} tokens.`
            : "No ceiling beyond whatever the run itself carries."}
        </span>
      </div>

      <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>
        {saving ? "Saving…" : saved ? "Saved." : "\u00a0"}
      </span>
    </div>
  );
}

export function AgentConfigHistory({ agent, onChanged, onError }: {
  agent: UserAgent; onChanged: () => void; onError: (e: string | null) => void;
}) {
  const [revisions, setRevisions] = useState<AgentRevision[]>([]);
  const [busy, setBusy] = useState<number | null>(null);
  const [open, setOpen] = useState<number | null>(null);

  useEffect(() => {
    let alive = true;
    listAgentRevisions(agent.id)
      .then(r => { if (alive) setRevisions(r.revisions); })
      .catch(() => {});
    return () => { alive = false; };
  }, [agent.id, agent.config_rev]);

  const restore = async (version: number) => {
    setBusy(version);
    onError(null);
    try {
      if (await restoreAgentRevision(agent.id, version)) onChanged();
      else onError("Restore failed.");
    } finally { setBusy(null); }
  };

  // Shown from the FIRST revision, not the second. An agent with one entry has a real
  // thing to say — this is the configuration it was born with — and hiding until two
  // meant every agent that predated revision tracking showed nothing at all.
  if (!revisions.length) return null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <span className="aug-label">Configuration history</span>
      <span style={{ fontSize: 11, color: "var(--t3)" }}>
        Instructions, connection, schema scope and bindings. Restoring adds a new revision —
        nothing in between is erased.
      </span>
      {revisions.map((r, i) => {
        // Only the newest revision is "current". An older one can carry the SAME
        // configuration (edit away, edit back) — saying "current" on both would claim two
        // heads; saying "Restore" would offer a button that changes nothing.
        const isHead = i === 0;
        const sameAsHead = !isHead && r.config_rev === agent.config_rev;
        const previous = revisions[i + 1];
        const changed = r.changed ?? [];
        const expandable = changed.length > 0 && previous !== undefined;
        const isOpen = open === r.version;
        return (
          <div key={r.version} style={{
            display: "flex", flexDirection: "column",
            padding: "5px 0", borderTop: "1px solid var(--b1)",
          }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12 }}>
              <span style={{ color: "var(--t3)", minWidth: 28 }}>v{r.version}</span>
              <span style={{ color: "var(--t2)", minWidth: 118 }}>{formatTimestamp(r.at)}</span>
              <span style={{ flex: 1, minWidth: 0, display: "flex", gap: 4,
                             flexWrap: "wrap", alignItems: "center" }}>
                {r.changed === null ? (
                  <span style={{ color: "var(--t3)" }}>earlier history not loaded</span>
                ) : changed.length === 0 ? (
                  <span style={{ color: "var(--t3)" }}>
                    {r.version === 1 ? "the configuration it started with" : "no governing change"}
                  </span>
                ) : (
                  changed.map(f => (
                    <StatusChip key={f} hue="muted" strength="soft">
                      {FIELD_LABEL[f] ?? f}
                    </StatusChip>
                  ))
                )}
              </span>
              {expandable && (
                <Button size="xs" variant="ghost"
                  onClick={() => setOpen(isOpen ? null : r.version)}>
                  {isOpen ? "Hide" : "What changed"}
                </Button>
              )}
              {isHead && <StatusChip hue="info" strength="soft">current</StatusChip>}
              {sameAsHead && (
                <span title="This configuration is the one running now — restoring it would change nothing.">
                  <StatusChip hue="muted" strength="soft">same as current</StatusChip>
                </span>
              )}
              {!isHead && !sameAsHead && (
                <Button size="xs" variant="ghost" disabled={busy !== null}
                  onClick={() => restore(r.version)}>
                  {busy === r.version ? "Restoring…" : "Restore"}
                </Button>
              )}
            </div>
            {isOpen && expandable && (
              <div style={{ paddingLeft: 36, paddingBottom: 4 }}>
                <div className="aug-fs-xs"
                     style={{ display: "flex", gap: 8,
                              color: "var(--t3)", paddingTop: 4 }}>
                  <span style={{ flex: 1 }}>before (v{previous.version})</span>
                  <span style={{ flex: 1 }}>after (v{r.version})</span>
                </div>
                {changed.map(f => (
                  <FieldDiff key={f} field={f}
                    before={previous.config[f]} after={r.config[f]} />
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ── charter detail ───────────────────────────────────────────────────────────────

/** The built-in agent's real knobs, and only the real ones: enabled, per-run
 *  budgets, model pin. Temperature/topP/tool toggles are deliberately absent —
 *  the transport pins temperature platform-wide and capabilities are
 *  governance, not UI switches. */
function CharterDetail({ charter, workspaceId, onChanged, onError, range }: {
  charter: AgentRosterEntry; workspaceId?: string;
  onChanged: () => void; onError: (e: string | null) => void;
  range?: TimeRange;
}) {
  const [busy, setBusy] = useState(false);
  const [charterRuns, setCharterRuns] = useState<TimelineRun[]>([]);

  // A charter's runs are the JOBS of the kinds it owns — one fetch per kind, because
  // /jobs filters on a single kind. A charter that owns none skips the fetch entirely
  // rather than asking for everything and rendering somebody else's work.
  useEffect(() => {
    let alive = true;
    if (charter.job_kinds.length === 0) { setCharterRuns([]); return; }
    Promise.all(charter.job_kinds.map(k => getJobs({ kind: k, limit: 20 }).catch(() => [])))
      .then(lists => {
        if (!alive) return;
        const rows = lists.flat()
          .sort((a, b) => String(b.created_at ?? "").localeCompare(String(a.created_at ?? "")))
          .slice(0, 20)
          .map(j => ({
            id: j.id, state: j.state, at: j.created_at,
            durationMs: j.duration_ms, label: j.title || j.kind,
          }));
        setCharterRuns(rows);
      });
    return () => { alive = false; };
  }, [charter.id, charter.job_kinds, range]);

  const patch = async (body: Parameters<typeof patchAgent>[1]) => {
    setBusy(true);
    try { await patchAgent(charter.id, { ...body, workspace_id: workspaceId }); onChanged(); }
    catch (e) { onError(String((e as Error)?.message || e)); }
    finally { setBusy(false); }
  };

  const gov = charter.governance;
  return (
    <div style={{ padding: 20, maxWidth: 720 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 15, fontWeight: 600 }}>{charter.name}</div>
          <div style={{ fontSize: 11, color: "var(--t2)", marginTop: 2 }}>
            charter · {charter.lane} · {charter.role}
          </div>
        </div>
        {charter.reserved ? (
          <StatusChip hue="muted" strength="soft">reserved — wiring soon</StatusChip>
        ) : charter.lane === "background" ? (
          <>
            <StatusChip hue={gov.enabled ? "positive" : "caution"} strength="soft">
              {gov.enabled ? "active" : "paused"}
            </StatusChip>
            <Button variant="ghost" size="xs" disabled={busy}
              onClick={() => patch({ enabled: !gov.enabled })}>
              {gov.enabled ? "Pause" : "Resume"}
            </Button>
          </>
        ) : (
          <StatusChip hue="muted" strength="soft">always on — user-initiated</StatusChip>
        )}
      </div>
      <div style={{ fontSize: 12, color: "var(--t2)", marginBottom: 12 }}>{charter.goal}</div>

      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 16 }}>
        {charter.job_kinds.map(k => <span key={k} className="aug-tag aug-tag-blue">{k}</span>)}
        {charter.tools.map(t => <span key={t} className="aug-tag">{t}</span>)}
      </div>

      <div style={{ display: "flex", flexWrap: "wrap", gap: 10, marginBottom: 18 }}>
        <Tile label="Runs (recent)" value={String(charter.spend.runs)} />
        <Tile label="Tokens" value={compactNumber(charter.spend.total_tokens)} />
        <Tile label="Queries" value={String(charter.spend.query_count)} />
        <Tile label="Token budget / run" value={fmtBudget(gov.token_budget)}
          sub="enforced live — an over-budget run is cancelled" />
      </div>

      {/* The run history a charter page never had. A charter's work is JOBS, so this reads
          the jobs of its own kinds — the same rows the Overview counts, at one-agent zoom. */}
      <div style={{ marginBottom: 18 }}>
        <div className="aug-label" style={{ color: "var(--t2)", marginBottom: 6 }}>Run history</div>
        <RunTimeline runs={charterRuns} emptyNote={charter.job_kinds.length === 0
          ? "This charter owns no job kind, so it can never show runs here — its work is answered inline, not submitted as a run."
          : "No runs in this window."} />
      </div>

      {!charter.reserved && (
        <div style={{ display: "flex", flexDirection: "column", gap: 10, padding: "12px 14px",
          border: "1px solid var(--b1)", borderRadius: "var(--r3)", background: "var(--bg-2)" }}>
          <span className="aug-label">
            Governance {workspaceId ? "· this workspace" : "· Org (all workspaces)"}
          </span>
          <AgentModelPin pinned={gov.model ?? null} busy={busy}
            onPin={(model, allowPaid) =>
              patch(allowPaid ? { model, allow_paid: true } : { model })} />
          {/* No "use recommended" / "apply to all": the charters carried a hardcoded
              model id per agent, and those were removed with every other model list
              (2026-08-15). An agent runs on the operator's pin, or inherits the role
              binding — there is nothing left for this product to recommend. */}
          <div style={{ fontSize: 11, color: "var(--t2)", lineHeight: 1.5 }}>
            These are the charter&rsquo;s REAL knobs. There is no per-agent temperature,
            topP or tool toggle here: the transport pins temperature platform-wide
            (13% run-to-run flip measured at default temp), and capability changes are
            governance actions, not switches.
          </div>
        </div>
      )}
    </div>
  );
}


/** The charter's model pin — a paste field, not a picker (2026-08-25).
 *
 *  Settings → Models is the ONE surface where models are chosen: the provider is
 *  selected there and each role (coder / narrator / fast) is bound there, as free text
 *  with the provider's catalogue as suggestions. This panel used to render a second,
 *  closed dropdown over the same catalogue — two routes to the same decision, and the
 *  roster's copy could gate a model the Models tab accepts. So the list is gone:
 *  unpinned, an agent runs on the Models-tab bindings (shown here, so the default is
 *  never a mystery); to override, paste a model id from that same provider. Free text
 *  for the Models tab's own reason — a stale list must never gate the model you pay for.
 */
export function AgentModelPin({ pinned, busy, onPin }: {
  pinned: string | null;
  busy: boolean;
  /** Persist the pin. `""` clears it back to the Models-tab bindings. */
  onPin: (model: string, allowPaid: boolean) => void;
}) {
  const [cfg, setCfg] = useState<LlmConfig | null>(null);
  const [draft, setDraft] = useState(pinned ?? "");

  useEffect(() => {
    getLlmConfig().then(setCfg).catch(() => setCfg(null));
  }, []);
  // Re-seed when the SAVED pin moves under the field (a save landed, or a reload) —
  // otherwise the input keeps showing a draft the server never accepted.
  useEffect(() => { setDraft(pinned ?? ""); }, [pinned]);

  const backend = cfg?.backend ?? "";
  const provider = BACKEND_LABEL[backend] ?? backend;
  const roleModels = cfg?.models ?? {};
  const fb = cfg?.fallback;
  const defaultsLine = (["coder", "narrator", "fast"] as const)
    .filter(r => roleModels[r])
    .map(r => `${r} → ${roleModels[r]}`)
    .join(" · ");

  const trimmed = draft.trim();
  const dirty = trimmed !== (pinned ?? "");

  const save = () => {
    // Free-by-default: pinning a paid OpenRouter model is a deliberate act — the
    // server refuses it without allow_paid; this confirm is how the user grants it.
    const paid = backend === "openrouter" && !!trimmed && !trimmed.endsWith(":free");
    if (paid && !window.confirm(
      `${trimmed} is a PAID OpenRouter model — free (:free) models are the default, ` +
      "and every call with this pin bills your OpenRouter credit. Pin it anyway?")) {
      return;
    }
    onPin(trimmed, paid);
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12 }}>
        <span style={{ width: 110, color: "var(--t3)", flexShrink: 0 }}>Model pin</span>
        <input className="aug-input" value={draft} disabled={busy}
          spellCheck={false} autoComplete="off"
          placeholder={provider ? `paste a model id from ${provider}` : "paste a model id"}
          style={{ fontSize: 11, padding: "3px 6px", maxWidth: 260,
            fontFamily: "var(--font-mono)" }}
          onChange={e => setDraft(e.target.value)} />
        {dirty && (
          <Button size="xs" variant="secondary" disabled={busy} onClick={save}>
            {trimmed ? "Pin" : "Clear pin"}
          </Button>
        )}
        {!dirty && pinned && (
          <Button size="xs" variant="ghost" disabled={busy}
            title="Remove the pin — this agent goes back to the models bound in Settings → Models"
            onClick={() => onPin("", false)}>
            Use Models default
          </Button>
        )}
      </label>
      <div style={{ fontSize: 11, color: "var(--t2)", lineHeight: 1.5 }}>
        {pinned ? (
          <>Pinned — this agent&rsquo;s coder and narrator calls run on the pinned model;
            its cheap &ldquo;fast&rdquo; calls stay on the Settings → Models binding. </>
        ) : defaultsLine ? (
          <>No pin — this agent runs on the models chosen in Settings → Models
            ({defaultsLine}). </>
        ) : (
          <>No pin — this agent runs on the models chosen in Settings → Models. </>
        )}
        Paste any model id {provider ? `${provider} serves` : "your provider serves"} to
        pin this agent — there is no list here to go stale, and the provider itself is
        chosen in Settings → Models.
      </div>
      {/* Where this agent's calls land when the primary refuses. The binding is chosen in
          Settings → Models and applies to every agent that is not pinned — shown here
          because a run that fails over answers on a DIFFERENT model, and the roster was
          the one place an operator could not tell that had happened. */}
      <div className="aug-fs-xs" style={{ color: "var(--t2)", lineHeight: 1.5 }}>
        {fb?.active && (
          <span style={{ color: "var(--amb5)", fontWeight: 600 }}>
            Failing over now —{" "}
          </span>
        )}
        {fb?.backend === "none"
          ? <>No fallback: a failing call fails this agent&rsquo;s run.</>
          : fb?.model
            ? <>Fallback: <code style={{ fontFamily: "var(--font-mono)" }}>{fb.model}</code>{" "}
              on {BACKEND_LABEL[fb.backend] ?? fb.backend}.</>
            : fb?.chain?.length
              ? <>Fallback: the built-in order ({fb.chain.join(" → ")}) — each link needs a
                model bound for it, or it is skipped.</>
              : <>No fallback configured.</>}
      </div>
    </div>
  );
}


function Tile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div style={{ flex: "1 1 130px", minWidth: 130, background: "var(--bg-2)",
      border: "1px solid var(--b1)", borderRadius: "var(--r3)", padding: "10px 14px" }}>
      <div style={{ fontSize: 18, fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>{value}</div>
      <div style={{ fontSize: 11, color: "var(--t3)", marginTop: 3 }}>{label}</div>
      {sub && <div style={{ fontSize: 11, color: "var(--t2)", marginTop: 2 }}>{sub}</div>}
    </div>
  );
}
