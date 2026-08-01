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

import { Button } from "@/components/ui/button";
import { StatusChip } from "@/components/brief/StatusChip";
import {
  applyRecommendedAgentModels, createAgentGolden, createUserAgent,
  createUserAgentFromTemplate, deleteAgentGolden, deleteUserAgent,
  evaluateUserAgent, getAgentObservability, getAgents, getConnections,
  getLlmConfig, getLlmModels, getPacks, listAgentGoldens, listAgentRevisions,
  listAgentTemplates, listDocuments, listUserAgents, patchAgent, patchUserAgent,
  restoreAgentRevision,
  type AgentEvalResult, type AgentGolden, type AgentObservability,
  type AgentRevision, type AgentRosterEntry, type AgentTemplate, type Connection,
  type DocumentEntry, type PackSummary, type UserAgent,
} from "@/lib/api";
import { evalChip } from "@/lib/agentEval";
import { compactNumber, formatTimestamp } from "@/lib/format";

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

export function AgenticAgentsPanel({ workspaceId, workspaceName, onOpenTrace, focusAgent }: {
  workspaceId?: string;
  workspaceName?: string;
  /** CR1 drill-in: open a run's trace in the Activity layer's runs mode. */
  onOpenTrace?: (investigationId: string) => void;
  /** An agent opened from the Fleet table — selected on arrival. */
  focusAgent?: { id: string; kind: "charter" | "persona" } | null;
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
          <span className="aug-label" style={{ color: "var(--t3)" }}>Custom agents</span>
          <span style={{ flex: 1 }} />
          <Button variant="outline" size="xs"
            onClick={() => setSelected({ kind: "hire" })}>+ Create</Button>
        </div>
        {personas.length === 0 && (
          <div style={{ fontSize: 11.5, color: "var(--t4)", padding: "0 6px 10px" }}>
            None yet — create one from a pack or from scratch.
          </div>
        )}
        {personas.map(p => (
          <RosterRow key={p.id} name={p.name} kind="persona" enabled={p.enabled}
            sub={evalChip(p.last_eval, p.eval_basis)?.label}
            active={selected?.kind === "persona" && selected.id === p.id}
            onClick={() => setSelected({ kind: "persona", id: p.id })} />
        ))}
        <div className="aug-label" style={{ color: "var(--t3)", padding: "12px 6px 8px" }}>
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
          <HireDetail onDone={a => { reload(); setSelected({ kind: "persona", id: a.id }); }}
            onError={setError} />
        ) : persona ? (
          <PersonaDetail key={persona.id} persona={persona} onChanged={reload}
            onDeleted={() => { setSelected(null); reload(); }}
            onError={setError} onOpenTrace={onOpenTrace} />
        ) : charter ? (
          <CharterDetail key={charter.id} charter={charter} workspaceId={workspaceId}
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
        <span style={{ fontSize: 12.5, fontWeight: 500, overflow: "hidden",
          textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1, minWidth: 0 }}>{name}</span>
        <StatusChip hue={kind === "charter" ? "info" : "accent"} strength="soft">
          {kind === "persona" ? "custom" : kind}
        </StatusChip>
        {!enabled && <StatusChip hue="caution" strength="soft">paused</StatusChip>}
      </span>
      {sub && (
        <span style={{ display: "block", fontSize: 10.5, color: "var(--t4)", marginTop: 2,
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{sub}</span>
      )}
    </Button>
  );
}

// ── persona detail ───────────────────────────────────────────────────────────────

function PersonaDetail({ persona, onChanged, onDeleted, onError, onOpenTrace }: {
  persona: UserAgent; onChanged: () => void; onDeleted: () => void;
  onError: (e: string | null) => void;
  onOpenTrace?: (investigationId: string) => void;
}) {
  const [tab, setTab] = useState<"overview" | "configure">("overview");
  const [busy, setBusy] = useState(false);

  const togglePause = async () => {
    setBusy(true);
    try { await patchUserAgent(persona.id, { enabled: !persona.enabled }); onChanged(); }
    catch (e) { onError(String((e as Error)?.message || e)); }
    finally { setBusy(false); }
  };

  return (
    <div style={{ padding: 20 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 15, fontWeight: 600 }}>{persona.name}</div>
          <div style={{ fontSize: 11, color: "var(--t4)", marginTop: 2 }}>
            custom · {persona.connection_id || "any connection"}
            {persona.schema_scope ? ` · ${persona.schema_scope}` : ""}
            {persona.pack_ids.length > 0 ? ` · ${persona.pack_ids.length} pack${persona.pack_ids.length === 1 ? "" : "s"}` : ""}
          </div>
        </div>
        {(() => {
          const chip = evalChip(persona.last_eval, persona.eval_basis);
          return chip && (
            <span title={chip.detail}>
              <StatusChip hue={chip.hue} strength="soft">{chip.label}</StatusChip>
            </span>
          );
        })()}
        <StatusChip hue={persona.enabled ? "positive" : "caution"} strength="soft">
          {persona.enabled ? "active" : "paused"}
        </StatusChip>
        <Button variant="ghost" size="xs" disabled={busy} onClick={togglePause}>
          {persona.enabled ? "Pause" : "Resume"}
        </Button>
        <Button variant={tab === "overview" ? "secondary" : "ghost"} size="xs"
          onClick={() => setTab("overview")}>Overview</Button>
        <Button variant={tab === "configure" ? "secondary" : "ghost"} size="xs"
          onClick={() => setTab("configure")}>Configure</Button>
      </div>
      {tab === "overview"
        ? <PersonaOverview persona={persona} onOpenTrace={onOpenTrace} />
        : <PersonaConfigure persona={persona} onChanged={onChanged}
            onDeleted={onDeleted} onError={onError} />}
    </div>
  );
}

/** H3's honest run view, unchanged in spirit: everything the agent did, spend
 *  or the flag that would measure it — never a confident zero. */
function PersonaOverview({ persona, onOpenTrace }: {
  persona: UserAgent; onOpenTrace?: (invId: string) => void;
}) {
  const [obs, setObs] = useState<AgentObservability | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    getAgentObservability(persona.id)
      .then(o => { if (alive) setObs(o); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [persona.id]);

  if (loading) return <div style={{ fontSize: 12, color: "var(--t3)" }}>Loading…</div>;
  if (!obs) return <div style={{ fontSize: 12, color: "var(--t3)" }}>No observability data.</div>;

  const spend = obs.spend;
  const runs = obs.runs || [];
  const deep = runs.filter(r => r.kind !== "chat").length;
  const quick = runs.length - deep;

  return (
    <>
      {persona.instructions && (
        <div style={{ padding: "10px 14px", background: "var(--bg-2)",
          border: "1px solid var(--b1)", borderRadius: "var(--r3)", fontSize: 12,
          color: "var(--t2)", lineHeight: 1.5, marginBottom: 14, whiteSpace: "pre-wrap" }}>
          {persona.instructions}
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
      {spend && !spend.measured && (
        <div style={{ fontSize: 12, color: "var(--t3)", marginBottom: 16 }}>
          Spend is not measured — {spend.reason}. Enable{" "}
          <code style={{ fontSize: 11 }}>{spend.enable_flag}</code> to attribute model
          calls per agent.
        </div>
      )}
      <div className="aug-label" style={{ color: "var(--t3)", marginBottom: 6 }}>Recent runs</div>
      {runs.length === 0 ? (
        <div style={{ fontSize: 12, color: "var(--t3)" }}>No runs yet for this agent.</div>
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

/** The persona's editable surface — fields, bindings and the golden suite
 *  (ported from AgentsAdminPanel, which this panel replaces). */
function PersonaConfigure({ persona, onChanged, onDeleted, onError }: {
  persona: UserAgent; onChanged: () => void; onDeleted: () => void;
  onError: (e: string | null) => void;
}) {
  const [form, setForm] = useState({
    name: persona.name, instructions: persona.instructions,
    connection_id: persona.connection_id, schema_scope: persona.schema_scope,
    doc_ids: persona.doc_ids, pack_ids: persona.pack_ids,
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
    listAgentGoldens(persona.id).then(setGoldens).catch(() => {});
  }, [persona.id]);

  // Re-seed the form when the SAVED configuration moves under it — which happens on a
  // restore. Without this the fields keep showing the configuration that was just replaced,
  // and the next "Save changes" quietly undoes the restore the user asked for. Keyed on
  // config_rev, so typing is never interrupted: it only fires when what is stored changed.
  useEffect(() => {
    setForm({
      name: persona.name, instructions: persona.instructions,
      connection_id: persona.connection_id, schema_scope: persona.schema_scope,
      doc_ids: persona.doc_ids, pack_ids: persona.pack_ids,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [persona.config_rev]);

  const save = async () => {
    if (!form.name.trim()) { onError("Name is required."); return; }
    setSaving(true);
    onError(null);
    try { await patchUserAgent(persona.id, form); onChanged(); }
    catch (e) { onError(e instanceof Error ? e.message : "Save failed."); }
    finally { setSaving(false); }
  };

  const remove = async () => {
    if (!window.confirm(`Delete agent “${persona.name}”? Its instructions and bindings are removed; documents stay.`)) return;
    await deleteUserAgent(persona.id);
    onDeleted();
  };

  const addGolden = async () => {
    if (!goldenDraft.question.trim() || !goldenDraft.reference_sql.trim()) return;
    try {
      const g = await createAgentGolden(persona.id, goldenDraft);
      setGoldens(gs => [...gs, g]);
      setGoldenDraft({ question: "", reference_sql: "" });
    } catch (e) { onError(e instanceof Error ? e.message : "Add golden failed."); }
  };

  const runEvaluation = async () => {
    setEvaluating(true);
    onError(null);
    try { setEvalResult(await evaluateUserAgent(persona.id)); onChanged(); }
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
          <span style={{ fontSize: 11.5, color: "var(--t3)" }}>
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
              <div key={p.golden_id} style={{ color: "var(--t3)", fontSize: 11.5 }}>
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
              await deleteAgentGolden(persona.id, g.id);
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

      <PersonaHistory persona={persona} onChanged={onChanged} onError={onError} />

      <div style={{ display: "flex", gap: 8 }}>
        <Button onClick={save} disabled={saving}>{saving ? "Saving…" : "Save changes"}</Button>
        <Button variant="destructive" size="sm" onClick={remove}>Delete agent</Button>
      </div>
    </div>
  );
}

/** H6 — the configuration history, next to the fields that write it.
 *
 *  Only the settings that change how the agent answers are versioned, so a rename never
 *  shows up here. Restoring writes the old configuration forward as a new revision rather
 *  than rewinding: what was tried in between stays on the record. */
function PersonaHistory({ persona, onChanged, onError }: {
  persona: UserAgent; onChanged: () => void; onError: (e: string | null) => void;
}) {
  const [revisions, setRevisions] = useState<AgentRevision[]>([]);
  const [busy, setBusy] = useState<number | null>(null);

  useEffect(() => {
    let alive = true;
    listAgentRevisions(persona.id)
      .then(r => { if (alive) setRevisions(r.revisions); })
      .catch(() => {});
    return () => { alive = false; };
  }, [persona.id, persona.config_rev]);

  const restore = async (version: number) => {
    setBusy(version);
    onError(null);
    try {
      if (await restoreAgentRevision(persona.id, version)) onChanged();
      else onError("Restore failed.");
    } finally { setBusy(null); }
  };

  if (revisions.length <= 1) return null;

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
        const sameAsHead = !isHead && r.config_rev === persona.config_rev;
        return (
          <div key={r.version} style={{
            display: "flex", alignItems: "center", gap: 8, fontSize: 11.5,
            padding: "5px 0", borderTop: "1px solid var(--b1)",
          }}>
            <span style={{ color: "var(--t3)", minWidth: 28 }}>v{r.version}</span>
            <span style={{ color: "var(--t4)", minWidth: 118 }}>{formatTimestamp(r.at)}</span>
            <span style={{
              flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis",
              whiteSpace: "nowrap", color: "var(--t3)",
            }}>
              {String((r.config as { instructions?: string }).instructions || "").trim()
                || "no instructions"}
            </span>
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
function CharterDetail({ charter, workspaceId, onChanged, onError }: {
  charter: AgentRosterEntry; workspaceId?: string;
  onChanged: () => void; onError: (e: string | null) => void;
}) {
  const [models, setModels] = useState<string[]>([]);
  const [catalogBackend, setCatalogBackend] = useState("");
  const [busy, setBusy] = useState(false);
  const [applyNote, setApplyNote] = useState("");

  useEffect(() => {
    getLlmModels()
      .then(c => { setModels(c.models.map(m => m.id)); setCatalogBackend(c.backend); })
      .catch(() => {
        getLlmConfig()
          .then(c => setModels([...new Set(Object.values(c.models || {}))].filter(Boolean) as string[]))
          .catch(() => setModels([]));
      });
  }, []);

  const patch = async (body: Parameters<typeof patchAgent>[1]) => {
    setBusy(true);
    try { await patchAgent(charter.id, { ...body, workspace_id: workspaceId }); onChanged(); }
    catch (e) { onError(String((e as Error)?.message || e)); }
    finally { setBusy(false); }
  };

  // Free-by-default: pinning a paid OpenRouter model is a deliberate act — the
  // server refuses it without allow_paid; this confirm is how the user grants it.
  const pinModel = (model: string) => {
    const paid = catalogBackend === "openrouter" && model && !model.endsWith(":free");
    if (paid && !window.confirm(
      `${model} is a PAID OpenRouter model — free (:free) models are the default, ` +
      "and every call with this pin bills your OpenRouter credit. Pin it anyway?")) {
      return;
    }
    patch(paid ? { model, allow_paid: true } : { model });
  };

  const gov = charter.governance;
  return (
    <div style={{ padding: 20, maxWidth: 720 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 15, fontWeight: 600 }}>{charter.name}</div>
          <div style={{ fontSize: 11, color: "var(--t4)", marginTop: 2 }}>
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

      {!charter.reserved && (
        <div style={{ display: "flex", flexDirection: "column", gap: 10, padding: "12px 14px",
          border: "1px solid var(--b1)", borderRadius: "var(--r3)", background: "var(--bg-2)" }}>
          <span className="aug-label">
            Governance {workspaceId ? "· this workspace" : "· Org (all workspaces)"}
          </span>
          <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12 }}>
            <span style={{ width: 110, color: "var(--t3)" }}>Model pin</span>
            <select className="aug-input" value={gov.model ?? ""} disabled={busy}
              onChange={e => pinModel(e.target.value)}
              style={{ fontSize: 11, padding: "3px 6px", maxWidth: 260 }}>
              <option value="">Role default</option>
              {models.map(m => <option key={m} value={m}>{m}</option>)}
              {gov.model && !models.includes(gov.model) && (
                <option value={gov.model}>{gov.model}</option>
              )}
            </select>
            {charter.recommended_model && gov.model !== charter.recommended_model && (
              <Button variant="ghost" size="xs" disabled={busy}
                onClick={() => pinModel(charter.recommended_model!)}
                title={`Recommended for ${charter.name}: ${charter.recommended_model}`}>
                use recommended
              </Button>
            )}
            {charter.recommended_model && gov.model === charter.recommended_model && (
              <span style={{ fontSize: 10, color: "var(--grn4)" }}>recommended</span>
            )}
          </label>
          <div style={{ fontSize: 11, color: "var(--t3)" }}>
            <Button variant="ghost" size="xs" disabled={busy} onClick={async () => {
              setBusy(true);
              const r = await applyRecommendedAgentModels({ workspace_id: workspaceId });
              setApplyNote(r ? `Pinned ${r.applied.length} for ${r.backend}` : "Could not apply.");
              onChanged();
              setBusy(false);
            }}>Apply recommended models to all</Button>
            {applyNote && <span style={{ color: "var(--grn4)", marginLeft: 8 }}>{applyNote}</span>}
          </div>
          <div style={{ fontSize: 11, color: "var(--t4)", lineHeight: 1.5 }}>
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

// ── hire / create ────────────────────────────────────────────────────────────────

function HireDetail({ onDone, onError }: {
  onDone: (a: UserAgent) => void; onError: (e: string | null) => void;
}) {
  const [templates, setTemplates] = useState<AgentTemplate[]>([]);
  const [name, setName] = useState("");
  const [instructions, setInstructions] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => { listAgentTemplates().then(setTemplates).catch(() => setTemplates([])); }, []);

  const hire = async (tpl: AgentTemplate) => {
    setSaving(true);
    onError(null);
    try { onDone((await createUserAgentFromTemplate({ pack_id: tpl.pack_id })).agent); }
    catch (e) { onError(e instanceof Error ? e.message : String(e)); }
    finally { setSaving(false); }
  };

  const create = async () => {
    if (!name.trim()) { onError("Name is required."); return; }
    setSaving(true);
    onError(null);
    try {
      onDone(await createUserAgent({ name, instructions, connection_id: "",
        schema_scope: "", doc_ids: [], pack_ids: [] }));
    } catch (e) { onError(e instanceof Error ? e.message : String(e)); }
    finally { setSaving(false); }
  };

  return (
    <div style={{ padding: 20, maxWidth: 720 }}>
      {templates.length > 0 && (
        <>
          <div className="aug-label" style={{ color: "var(--t3)", marginBottom: 4 }}>
            Create from a pack
          </div>
          <div style={{ fontSize: 11.5, color: "var(--t3)", marginBottom: 10, lineHeight: 1.5 }}>
            Starts the agent with the pack&rsquo;s reasoning stance and keeps the pack
            bound. Its questions come along as suggestions — each still needs reference
            SQL for your connection before it can be measured.
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 10, marginBottom: 22 }}>
            {templates.map(t => (
              <div key={t.pack_id} style={{ flex: "1 1 240px", maxWidth: 330, padding: 14,
                display: "flex", flexDirection: "column", gap: 8, background: "var(--bg-2)",
                border: "1px solid var(--b1)", borderRadius: "var(--r3)" }}>
                <div style={{ fontSize: 13, fontWeight: 600 }}>{t.name}</div>
                <div style={{ fontSize: 11.5, color: "var(--t3)", lineHeight: 1.45 }}>{t.persona}</div>
                <div style={{ fontSize: 11, color: "var(--t4)" }}>
                  {t.domains.join(" · ")}
                  {t.suggested_goldens.length > 0
                    ? ` — ${t.suggested_goldens.length} suggested questions` : ""}
                </div>
                <Button size="sm" variant="outline" disabled={saving}
                  onClick={() => hire(t)} className="self-start">Create {t.name}</Button>
              </div>
            ))}
          </div>
        </>
      )}
      <div className="aug-label" style={{ color: "var(--t3)", marginBottom: 8 }}>
        Or create from scratch
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 10, maxWidth: 560 }}>
        <input className="aug-input" placeholder="Name — e.g. Churn Analyst" value={name}
          maxLength={120} onChange={e => setName(e.target.value)} />
        <textarea className="aug-input" rows={4} maxLength={8000} value={instructions}
          placeholder="Standing instructions (bind connection, documents and packs after creating)"
          onChange={e => setInstructions(e.target.value)} />
        <span>
          <Button onClick={create} disabled={saving}>
            {saving ? "Creating…" : "Create agent"}
          </Button>
        </span>
      </div>
    </div>
  );
}

function Tile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div style={{ flex: "1 1 130px", minWidth: 130, background: "var(--bg-2)",
      border: "1px solid var(--b1)", borderRadius: "var(--r3)", padding: "10px 14px" }}>
      <div style={{ fontSize: 18, fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>{value}</div>
      <div style={{ fontSize: 10.5, color: "var(--t3)", marginTop: 3 }}>{label}</div>
      {sub && <div style={{ fontSize: 10, color: "var(--t4)", marginTop: 2 }}>{sub}</div>}
    </div>
  );
}
