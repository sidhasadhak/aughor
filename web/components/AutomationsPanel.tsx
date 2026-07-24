"use client";
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  Automation,
  AutomationRun,
  AutoCondition,
  AutoEffect,
  ConditionKind,
  EffectKind,
  NewAutomation,
  StagedProposal,
  StandingGrant,
  getAutomations,
  createAutomation,
  updateAutomation,
  deleteAutomation,
  setAutomationEnabled,
  pauseAutomation,
  runAutomation,
  getAutomationRuns,
  getProposals,
  acceptProposal,
  rejectProposal,
  getGrants,
  revokeGrant,
} from "@/lib/api";
import { MiniStat, MiniStatRow } from "@/components/ui/MiniStat";
import { Button } from "@/components/ui/button";

// ── Vocabulary (mirrors the backend Literals) ────────────────────────────────────

type View = "list" | "runs" | "inbox" | "form";

const CONDITION_KINDS: { value: ConditionKind; label: string; desc: string }[] = [
  { value: "schedule",       label: "Schedule",       desc: "Fire on a cron cadence" },
  { value: "metric",         label: "Metric",         desc: "Delegate to an existing monitor by id" },
  { value: "source_change",  label: "Source change",  desc: "A table's rows changed (add / delete / backfill)" },
  { value: "entity_appears", label: "New entity",     desc: "A new key appeared in a table" },
];

const EFFECT_KINDS: { value: EffectKind; label: string; desc: string }[] = [
  { value: "notify",         label: "Notify",         desc: "Send through an Action Hub trigger" },
  { value: "investigate",    label: "Investigate",    desc: "Run a deep investigation" },
  { value: "brief",          label: "Deliver brief",  desc: "Deliver a brief subscription" },
  { value: "kinetic_action", label: "Declared action", desc: "Run a governed KineticAction" },
];

const CRON_PRESETS = [
  { label: "Hourly",  cron: "0 * * * *" },
  { label: "Daily",   cron: "0 9 * * *" },
  { label: "Weekly",  cron: "0 9 * * 1" },
  { label: "Custom",  cron: "" },
];

const OUTCOME_COLOR: Record<string, string> = {
  fired:     "var(--g2, #16a34a)",
  not_fired: "var(--t3)",
  gated:     "var(--chart-threshold-warn, #f59e0b)",
  error:     "var(--r2)",
};

const STATUS_COLOR: Record<string, string> = {
  executed:          "var(--g2, #16a34a)",
  failed:            "var(--r2)",
  dispatch_error:    "var(--r2)",
  criterion_failed:  "var(--chart-threshold-warn, #f59e0b)",
  approval_required: "var(--chart-threshold-warn, #f59e0b)",
  skipped:           "var(--t3)",
};

const ghostBtn: React.CSSProperties = {
  background: "none", border: "none", color: "var(--t3)", cursor: "pointer", fontSize: 11,
};

// Time helpers kept at module scope: `Date.now()` / argless `new Date()` are impure and the
// React-purity lint forbids them inside a component/hook body (they belong outside render).
function isFuture(iso: string | null | undefined): boolean {
  return !!iso && new Date(iso).getTime() > Date.now();
}
function muteUntilISO(hours = 24): string {
  return new Date(Date.now() + hours * 3600 * 1000).toISOString();
}

// ── Panel ─────────────────────────────────────────────────────────────────────

type Props = { connId?: string; workspaceId?: string };

export function AutomationsPanel({ connId }: Props) {
  const conn = connId || "";
  const [view, setView] = useState<View>("list");
  const [automations, setAutomations] = useState<Automation[]>([]);
  const [loading, setLoading] = useState(true);
  const [banner, setBanner] = useState<{ tone: "ok" | "err"; text: string } | null>(null);

  // runs view
  const [runsFor, setRunsFor] = useState<Automation | null>(null);
  const [runs, setRuns] = useState<AutomationRun[]>([]);

  // inbox view
  const [proposals, setProposals] = useState<StagedProposal[]>([]);
  const [grants, setGrants] = useState<StandingGrant[]>([]);

  // form
  const [editing, setEditing] = useState<Automation | null>(null);

  const flash = useCallback((tone: "ok" | "err", text: string) => {
    setBanner({ tone, text });
    setTimeout(() => setBanner(b => (b?.text === text ? null : b)), 4000);
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setAutomations(await getAutomations(conn || undefined));
    } catch {
      setAutomations([]);
    } finally {
      setLoading(false);
    }
  }, [conn]);

  useEffect(() => { load(); }, [load]);

  const loadInbox = useCallback(async () => {
    if (!conn) return;
    try {
      const [p, g] = await Promise.all([getProposals(conn), getGrants(conn)]);
      setProposals(p); setGrants(g);
    } catch { /* inbox off → empty */ }
  }, [conn]);

  useEffect(() => { if (view === "inbox") loadInbox(); }, [view, loadInbox]);

  const openRuns = useCallback(async (a: Automation) => {
    setRunsFor(a); setView("runs");
    try { setRuns(await getAutomationRuns(a.id)); } catch { setRuns([]); }
  }, []);

  const onToggle = async (a: Automation) => {
    try { await setAutomationEnabled(a.id, !a.enabled); await load(); }
    catch { flash("err", "Could not toggle"); }
  };
  const onPause = async (a: Automation) => {
    // Mute for 24h, or clear an existing mute.
    const until = isFuture(a.paused_until) ? null : muteUntilISO();
    try { await pauseAutomation(a.id, until); await load(); }
    catch { flash("err", "Could not pause"); }
  };
  const onRun = async (a: Automation) => {
    try {
      const run = await runAutomation(a.id);
      flash(run.outcome === "fired" ? "ok" : "err",
        `${a.name}: ${run.outcome}${run.reason ? ` — ${run.reason}` : ""}`);
      await load();
      if (runsFor?.id === a.id) setRuns(await getAutomationRuns(a.id));
    } catch { flash("err", "Run failed"); }
  };
  const onDelete = async (a: Automation) => {
    if (!confirm(`Delete automation "${a.name}"?`)) return;
    try { await deleteAutomation(a.id); await load(); }
    catch { flash("err", "Could not delete"); }
  };

  const stats = useMemo(() => {
    const enabled = automations.filter(a => a.enabled).length;
    const paused = automations.filter(a => isFuture(a.paused_until)).length;
    return { total: automations.length, enabled, paused };
  }, [automations]);

  const TABS: View[] = ["list", "runs", "inbox"];
  const pendingCount = proposals.filter(p => p.status === "pending").length;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", background: "var(--bg-0)", color: "var(--t1)" }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "16px 20px 0", borderBottom: "1px solid var(--bg-3)" }}>
        <div style={{ display: "flex", gap: 2 }}>
          {([...TABS, ...(view === "form" ? (["form"] as View[]) : [])]).map(v => (
            <Button
              key={v} variant="ghost"
              onClick={() => view !== "form" && setView(v)}
              className="h-auto"
              style={{
                padding: "6px 14px", fontSize: 12, borderRadius: 0, fontWeight: 500,
                background: view === v ? "var(--blue3)" : "transparent",
                color: view === v ? "#fff" : "var(--t3)",
                borderBottom: view === v ? "2px solid var(--blue3)" : "2px solid transparent",
              }}>
              {v === "list" ? "Automations" :
               v === "runs" ? "Runs" :
               v === "inbox" ? <>Inbox {pendingCount > 0 && <span style={{ marginLeft: 4, background: "var(--r2)", color: "#fff", borderRadius: 8, padding: "1px 5px", fontSize: 10 }}>{pendingCount}</span>}</> :
               "Edit"}
            </Button>
          ))}
        </div>
        <div style={{ flex: 1 }} />
        {view === "list" && (
          <Button variant="ghost" className="h-auto" onClick={() => { setEditing(null); setView("form"); }} style={{ fontSize: 12, padding: "5px 12px" }}>
            + New automation
          </Button>
        )}
        {view === "form" && (
          <Button variant="ghost" onClick={() => setView("list")} className="h-auto p-0 font-normal" style={{ ...ghostBtn, fontSize: 12 }}>
            ← Cancel
          </Button>
        )}
      </div>

      {banner && (
        <div style={{
          margin: "10px 20px 0", padding: "8px 12px", borderRadius: "var(--r3)", fontSize: 12,
          background: banner.tone === "ok" ? "var(--g1, #dcfce7)" : "var(--r1, #fee2e2)",
          color: banner.tone === "ok" ? "var(--g3, #166534)" : "var(--r3-text, #991b1b)",
          border: "1px solid var(--bg-3)",
        }}>{banner.text}</div>
      )}

      {/* Body */}
      <div style={{ flex: 1, overflowY: "auto", padding: 20 }}>
        {loading && <div style={{ color: "var(--t3)", fontSize: 13 }}>Loading…</div>}

        {view === "list" && !loading && (
          automations.length === 0
            ? <EmptyState onAdd={() => { setEditing(null); setView("form"); }} />
            : <>
                <MiniStatRow>
                  <MiniStat value={stats.total} label="Automations" />
                  <MiniStat value={stats.enabled} label="Enabled" tone="var(--g2, #16a34a)" />
                  <MiniStat value={stats.paused} label="Muted" tone="var(--chart-threshold-warn, #f59e0b)" />
                </MiniStatRow>
                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                  {automations.map(a => (
                    <AutomationCard key={a.id} a={a}
                      onToggle={() => onToggle(a)} onPause={() => onPause(a)} onRun={() => onRun(a)}
                      onEdit={() => { setEditing(a); setView("form"); }} onDelete={() => onDelete(a)}
                      onRuns={() => openRuns(a)} />
                  ))}
                </div>
              </>
        )}

        {view === "runs" && !loading && (
          <RunsView automations={automations} runsFor={runsFor} runs={runs} onPick={openRuns} />
        )}

        {view === "inbox" && !loading && (
          <InboxView
            conn={conn} proposals={proposals} grants={grants}
            onReload={loadInbox} flash={flash} />
        )}

        {view === "form" && (
          <AutomationForm
            conn={conn} initial={editing}
            onCancel={() => setView("list")}
            onSaved={async () => { await load(); setView("list"); flash("ok", "Saved"); }}
            onError={t => flash("err", t)} />
        )}
      </div>
    </div>
  );
}

// ── List card ─────────────────────────────────────────────────────────────────

function AutomationCard({ a, onToggle, onPause, onRun, onEdit, onDelete, onRuns }: {
  a: Automation;
  onToggle: () => void; onPause: () => void; onRun: () => void;
  onEdit: () => void; onDelete: () => void; onRuns: () => void;
}) {
  const muted = isFuture(a.paused_until);
  return (
    <div style={{
      background: "var(--bg-1, var(--bg-2))", border: "1px solid var(--b1)", borderRadius: "var(--r3)",
      padding: "12px 16px", opacity: a.enabled ? 1 : 0.6,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <button onClick={onToggle} title={a.enabled ? "Disable" : "Enable"} style={{
          width: 34, height: 18, borderRadius: 10, border: "none", cursor: "pointer", flexShrink: 0,
          background: a.enabled ? "var(--blue3)" : "var(--bg-3)", position: "relative",
        }}>
          <span style={{
            position: "absolute", top: 2, left: a.enabled ? 18 : 2, width: 14, height: 14,
            borderRadius: "50%", background: "#fff", transition: "left .12s",
          }} />
        </button>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontSize: 13, fontWeight: 600 }}>{a.name}</span>
            {muted && <span style={{ background: "var(--chart-threshold-warn, #f59e0b)", color: "#fff", borderRadius: 8, padding: "1px 6px", fontSize: 10 }}>muted</span>}
            {a.last_status && <span style={{ color: OUTCOME_COLOR[a.last_status] || "var(--t3)", fontSize: 10 }}>● {a.last_status}</span>}
          </div>
          <div style={{ fontSize: 11, color: "var(--t3)", marginTop: 2 }}>
            {a.conditions.map(describeCondition).join(a.condition_logic === "all" ? " AND " : " OR ")}
            {" → "}
            {a.effects.map(describeEffect).join(", ")}
          </div>
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          <Button variant="ghost" onClick={onRun} className="h-auto" style={{ fontSize: 11, padding: "3px 9px", opacity: 0.85 }}>Run now</Button>
          <Button variant="ghost" onClick={onRuns} className="h-auto p-0 font-normal" style={ghostBtn}>History</Button>
          <Button variant="ghost" onClick={onPause} className="h-auto p-0 font-normal" style={ghostBtn}>{muted ? "Unmute" : "Mute"}</Button>
          <Button variant="ghost" onClick={onEdit} className="h-auto p-0 font-normal" style={ghostBtn}>Edit</Button>
          <Button variant="ghost" onClick={onDelete} className="h-auto p-0 font-normal" style={{ ...ghostBtn, color: "var(--r2)" }}>Delete</Button>
        </div>
      </div>
    </div>
  );
}

// ── Runs view (the reason a tick did NOTHING) ─────────────────────────────────

function RunsView({ automations, runsFor, runs, onPick }: {
  automations: Automation[]; runsFor: Automation | null; runs: AutomationRun[];
  onPick: (a: Automation) => void;
}) {
  return (
    <div>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 14 }}>
        {automations.map(a => (
          <Button key={a.id} variant="ghost" className="h-auto" onClick={() => onPick(a)} style={{
            fontSize: 11, padding: "4px 10px",
            background: runsFor?.id === a.id ? "var(--blue3)" : "var(--bg-2)",
            color: runsFor?.id === a.id ? "#fff" : "var(--t2)",
          }}>{a.name}</Button>
        ))}
      </div>
      {!runsFor && <div style={{ color: "var(--t3)", fontSize: 13 }}>Pick an automation to see its tick history.</div>}
      {runsFor && runs.length === 0 && <div style={{ color: "var(--t3)", fontSize: 13 }}>No ticks yet — hit “Run now”.</div>}
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {runs.map(r => (
          <div key={r.id} style={{ background: "var(--bg-2)", border: "1px solid var(--b1)", borderRadius: 6, padding: "10px 14px" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{
                fontSize: 10, fontWeight: 700, padding: "2px 7px", borderRadius: 4, textTransform: "uppercase",
                background: OUTCOME_COLOR[r.outcome] || "var(--t3)", color: "#fff",
              }}>{r.outcome.replace("_", " ")}</span>
              <span style={{ fontSize: 12, color: "var(--t2)" }}>{r.reason}</span>
              <div style={{ flex: 1 }} />
              <span style={{ fontSize: 10, color: "var(--t3)" }}>{relTime(r.started_at)} · {r.duration_ms}ms</span>
            </div>
            {r.effects.length > 0 && (
              <div style={{ marginTop: 6, display: "flex", flexDirection: "column", gap: 3, paddingLeft: 4 }}>
                {r.effects.map((e, i) => (
                  <div key={i} style={{ fontSize: 11, color: "var(--t3)" }}>
                    <span style={{ color: STATUS_COLOR[e.status] || "var(--t3)", fontWeight: 600 }}>{e.status}</span>
                    {" · "}{e.kind}{e.target ? ` (${e.target})` : ""}{e.attempts > 1 ? ` ×${e.attempts}` : ""}
                    {e.message ? <span style={{ color: "var(--t3)" }}> — {e.message}</span> : null}
                  </div>
                ))}
              </div>
            )}
            {r.error && <div style={{ marginTop: 4, fontSize: 11, color: "var(--r2)" }}>{r.error}</div>}
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Inbox view (proposal queue + grants) ──────────────────────────────────────

function InboxView({ conn, proposals, grants, onReload, flash }: {
  conn: string; proposals: StagedProposal[]; grants: StandingGrant[];
  onReload: () => void; flash: (t: "ok" | "err", s: string) => void;
}) {
  const [mintFor, setMintFor] = useState<Record<string, boolean>>({});
  const pending = proposals.filter(p => p.status === "pending");
  const resolved = proposals.filter(p => p.status !== "pending");

  const accept = async (p: StagedProposal) => {
    try {
      const r = await acceptProposal(p.id, "operator", !!mintFor[p.id]);
      flash("ok", `Accepted → ${r.status}${r.minted_grant ? " (grant minted)" : ""}`);
      onReload();
    } catch (e) { flash("err", (e as Error).message); }
  };
  const reject = async (p: StagedProposal) => {
    try { await rejectProposal(p.id, "operator"); flash("ok", "Rejected"); onReload(); }
    catch (e) { flash("err", (e as Error).message); }
  };
  const revoke = async (g: StandingGrant) => {
    try { await revokeGrant(g.id); flash("ok", "Grant revoked"); onReload(); }
    catch (e) { flash("err", (e as Error).message); }
  };

  if (!conn) return <div style={{ color: "var(--t3)", fontSize: 13 }}>Select a connection to see its proposal queue.</div>;

  return (
    <div>
      <MiniStatRow>
        <MiniStat value={pending.length} label="Pending proposals" tone="var(--blue3)" />
        <MiniStat value={grants.length} label="Standing grants" />
      </MiniStatRow>

      {pending.length === 0 && grants.length === 0 && (
        <div style={{ color: "var(--t3)", fontSize: 13, paddingTop: 12 }}>
          No staged proposals. When the agent proposes a declared action, it lands here for you to accept or reject.
          <div style={{ marginTop: 6, fontSize: 11 }}>(Requires the <code>automations.proposals</code> flag.)</div>
        </div>
      )}

      {pending.map(p => (
        <div key={p.id} style={{ background: "var(--bg-2)", border: "1px solid var(--b1)", borderRadius: 6, padding: "12px 14px", marginBottom: 10 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontSize: 13, fontWeight: 600 }}>{p.action_id}</span>
            <span style={{ fontSize: 10, color: "var(--t3)" }}>by {p.proposer}</span>
          </div>
          {p.reasoning && <div style={{ fontSize: 12, color: "var(--t2)", marginTop: 4 }}>{p.reasoning}</div>}
          <div style={{ fontSize: 11, color: "var(--t3)", marginTop: 4, fontFamily: "var(--font-mono, monospace)" }}>
            {JSON.stringify(p.params)}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 10 }}>
            <Button variant="ghost" className="h-auto" onClick={() => accept(p)} style={{ fontSize: 11, padding: "3px 12px", background: "var(--blue3)", color: "#fff" }}>Accept</Button>
            <Button variant="ghost" className="h-auto p-0 font-normal" onClick={() => reject(p)} style={{ ...ghostBtn, color: "var(--r2)" }}>Reject</Button>
            <label style={{ fontSize: 11, color: "var(--t3)", display: "flex", alignItems: "center", gap: 5, cursor: "pointer" }}>
              <input type="checkbox" checked={!!mintFor[p.id]} onChange={e => setMintFor(m => ({ ...m, [p.id]: e.target.checked }))} />
              also allow this target unattended
            </label>
          </div>
        </div>
      ))}

      {grants.length > 0 && (
        <>
          <div style={{ fontSize: 11, fontWeight: 600, color: "var(--t3)", textTransform: "uppercase", margin: "16px 0 8px" }}>Standing grants</div>
          {grants.map(g => (
            <div key={g.id} style={{ display: "flex", alignItems: "center", gap: 10, background: "var(--bg-2)", border: "1px solid var(--b1)", borderRadius: 6, padding: "8px 12px", marginBottom: 6 }}>
              <span style={{ fontSize: 12 }}><b>{g.action_id}</b> → {g.target_arg}=<code>{g.target_value}</code></span>
              <span style={{ fontSize: 10, color: "var(--t3)" }}>used {g.use_count}× · by {g.created_by || g.owner_kind}</span>
              <div style={{ flex: 1 }} />
              <Button variant="ghost" className="h-auto p-0 font-normal" onClick={() => revoke(g)} style={{ ...ghostBtn, color: "var(--r2)" }}>Revoke</Button>
            </div>
          ))}
        </>
      )}

      {resolved.length > 0 && (
        <>
          <div style={{ fontSize: 11, fontWeight: 600, color: "var(--t3)", textTransform: "uppercase", margin: "16px 0 8px" }}>Recently resolved</div>
          {resolved.slice(0, 8).map(p => (
            <div key={p.id} style={{ fontSize: 11, color: "var(--t3)", padding: "4px 0" }}>
              <span style={{ color: STATUS_COLOR[p.status] || "var(--t3)", fontWeight: 600 }}>{p.status}</span>
              {" · "}{p.action_id} · {p.resolved_by || "—"}{p.status_message ? ` — ${p.status_message}` : ""}
            </div>
          ))}
        </>
      )}
    </div>
  );
}

// ── Author form ───────────────────────────────────────────────────────────────

const inputStyle: React.CSSProperties = {
  width: "100%", padding: "7px 10px", fontSize: 13, borderRadius: "var(--r3)",
  border: "1px solid var(--b1)", background: "var(--bg-1, var(--bg-2))", color: "var(--t1)",
};
const labelStyle: React.CSSProperties = { fontSize: 11, fontWeight: 600, color: "var(--t3)", marginBottom: 5, display: "block", textTransform: "uppercase" };

function AutomationForm({ conn, initial, onCancel, onSaved, onError }: {
  conn: string; initial: Automation | null;
  onCancel: () => void; onSaved: () => void; onError: (t: string) => void;
}) {
  const [name, setName] = useState(initial?.name ?? "");
  const [logic, setLogic] = useState<"all" | "any">(initial?.condition_logic ?? "all");
  const [conditions, setConditions] = useState<AutoCondition[]>(
    initial?.conditions ?? [{ kind: "schedule", config: { cron: "0 9 * * *" } }]);
  const [effects, setEffects] = useState<AutoEffect[]>(
    initial?.effects ?? [{ kind: "notify", config: { trigger_id: "" } }]);
  const [maxRetries, setMaxRetries] = useState(initial?.max_retries ?? 1);
  const [saving, setSaving] = useState(false);

  const setCond = (i: number, c: AutoCondition) => setConditions(cs => cs.map((x, j) => j === i ? c : x));
  const setEff = (i: number, e: AutoEffect) => setEffects(es => es.map((x, j) => j === i ? e : x));

  const save = async () => {
    if (!conn) { onError("No connection selected"); return; }
    if (!name.trim()) { onError("Name is required"); return; }
    // Build the payload; kinetic_action params come in as a JSON string in config.paramsText.
    let builtEffects: AutoEffect[];
    try {
      builtEffects = effects.map(e => {
        if (e.kind === "kinetic_action") {
          const raw = String((e.config as { paramsText?: string }).paramsText ?? "{}").trim() || "{}";
          const { paramsText: _omit, ...rest } = e.config as Record<string, unknown>;
          void _omit;
          return { kind: e.kind, config: { ...rest, params: JSON.parse(raw) } };
        }
        return e;
      });
    } catch { onError("Declared-action params must be valid JSON"); return; }

    const payload: NewAutomation = {
      conn_id: conn, name: name.trim(), conditions, condition_logic: logic,
      effects: builtEffects, max_retries: maxRetries,
    };
    setSaving(true);
    try {
      if (initial) await updateAutomation(initial.id, payload);
      else await createAutomation(payload);
      onSaved();
    } catch (e) {
      onError((e as Error).message || "Save failed");
    } finally { setSaving(false); }
  };

  return (
    <div style={{ maxWidth: 640 }}>
      <div style={{ marginBottom: 16 }}>
        <label style={labelStyle}>Name</label>
        <input style={inputStyle} value={name} onChange={e => setName(e.target.value)} placeholder="e.g. Refund spike watch" />
      </div>

      {/* Conditions */}
      <div style={{ marginBottom: 16 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
          <label style={{ ...labelStyle, marginBottom: 0 }}>When</label>
          {conditions.length > 1 && (
            <select value={logic} onChange={e => setLogic(e.target.value as "all" | "any")}
              style={{ ...inputStyle, width: "auto", padding: "3px 8px", fontSize: 11 }}>
              <option value="all">all match</option>
              <option value="any">any match</option>
            </select>
          )}
        </div>
        {conditions.map((c, i) => (
          <ConditionRow key={i} c={c} onChange={cc => setCond(i, cc)}
            onRemove={conditions.length > 1 ? () => setConditions(cs => cs.filter((_, j) => j !== i)) : undefined} />
        ))}
        <Button variant="ghost" className="h-auto p-0 font-normal" onClick={() => setConditions(cs => [...cs, { kind: "schedule", config: { cron: "0 9 * * *" } }])} style={{ ...ghostBtn, color: "var(--blue3)", marginTop: 2 }}>+ add condition</Button>
      </div>

      {/* Effects */}
      <div style={{ marginBottom: 16 }}>
        <label style={labelStyle}>Then (in order)</label>
        {effects.map((e, i) => (
          <EffectRow key={i} e={e} onChange={ee => setEff(i, ee)}
            onRemove={effects.length > 1 ? () => setEffects(es => es.filter((_, j) => j !== i)) : undefined} />
        ))}
        <Button variant="ghost" className="h-auto p-0 font-normal" onClick={() => setEffects(es => [...es, { kind: "notify", config: { trigger_id: "" } }])} style={{ ...ghostBtn, color: "var(--blue3)", marginTop: 2 }}>+ add effect</Button>
      </div>

      <div style={{ marginBottom: 20, display: "flex", gap: 16, alignItems: "center" }}>
        <div>
          <label style={labelStyle}>Retries per effect</label>
          <input type="number" min={0} max={5} value={maxRetries} onChange={e => setMaxRetries(Math.max(0, Math.min(5, Number(e.target.value))))}
            style={{ ...inputStyle, width: 80 }} />
        </div>
      </div>

      <div style={{ display: "flex", gap: 10 }}>
        <Button onClick={save} disabled={saving} style={{ background: "var(--blue3)", color: "#fff", fontSize: 13, padding: "7px 18px" }}>
          {saving ? "Saving…" : initial ? "Save changes" : "Create automation"}
        </Button>
        <Button variant="ghost" onClick={onCancel} className="font-normal" style={{ ...ghostBtn, fontSize: 13 }}>Cancel</Button>
      </div>
    </div>
  );
}

function ConditionRow({ c, onChange, onRemove }: { c: AutoCondition; onChange: (c: AutoCondition) => void; onRemove?: () => void }) {
  const set = (patch: Record<string, unknown>) => onChange({ ...c, config: { ...c.config, ...patch } });
  return (
    <div style={{ display: "flex", gap: 8, alignItems: "flex-start", marginBottom: 8 }}>
      <select value={c.kind} onChange={e => onChange({ kind: e.target.value as ConditionKind, config: {} })}
        style={{ ...inputStyle, width: 150 }}>
        {CONDITION_KINDS.map(k => <option key={k.value} value={k.value}>{k.label}</option>)}
      </select>
      <div style={{ flex: 1 }}>
        {c.kind === "schedule" && (
          <div style={{ display: "flex", gap: 6 }}>
            <select value={CRON_PRESETS.find(p => p.cron === c.config.cron)?.cron ?? ""}
              onChange={e => e.target.value && set({ cron: e.target.value })}
              style={{ ...inputStyle, width: 110 }}>
              {CRON_PRESETS.map(p => <option key={p.label} value={p.cron}>{p.label}</option>)}
            </select>
            <input style={inputStyle} value={String(c.config.cron ?? "")} onChange={e => set({ cron: e.target.value })} placeholder="cron e.g. 0 9 * * *" />
          </div>
        )}
        {c.kind === "metric" && (
          <input style={inputStyle} value={String(c.config.monitor_id ?? "")} onChange={e => set({ monitor_id: e.target.value })} placeholder="monitor id" />
        )}
        {(c.kind === "source_change" || c.kind === "entity_appears") && (
          <input style={inputStyle} value={String(c.config.table ?? "")} onChange={e => set({ table: e.target.value })} placeholder="table (schema.table)" />
        )}
      </div>
      {onRemove && <button onClick={onRemove} style={{ ...ghostBtn, color: "var(--r2)", padding: "6px 4px" }}>✕</button>}
    </div>
  );
}

function EffectRow({ e, onChange, onRemove }: { e: AutoEffect; onChange: (e: AutoEffect) => void; onRemove?: () => void }) {
  const set = (patch: Record<string, unknown>) => onChange({ ...e, config: { ...e.config, ...patch } });
  return (
    <div style={{ display: "flex", gap: 8, alignItems: "flex-start", marginBottom: 8 }}>
      <select value={e.kind} onChange={ev => onChange({ kind: ev.target.value as EffectKind, config: {} })}
        style={{ ...inputStyle, width: 150 }}>
        {EFFECT_KINDS.map(k => <option key={k.value} value={k.value}>{k.label}</option>)}
      </select>
      <div style={{ flex: 1 }}>
        {e.kind === "notify" && (
          <input style={inputStyle} value={String(e.config.trigger_id ?? "")} onChange={ev => set({ trigger_id: ev.target.value })} placeholder="Action Hub trigger id" />
        )}
        {e.kind === "investigate" && (
          <input style={inputStyle} value={String(e.config.question ?? "")} onChange={ev => set({ question: ev.target.value })} placeholder="investigation question" />
        )}
        {e.kind === "brief" && (
          <input style={inputStyle} value={String(e.config.subscription_id ?? "")} onChange={ev => set({ subscription_id: ev.target.value })} placeholder="brief subscription id" />
        )}
        {e.kind === "kinetic_action" && (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <input style={inputStyle} value={String(e.config.action_id ?? "")} onChange={ev => set({ action_id: ev.target.value })} placeholder="declared action id" />
            <input style={inputStyle} value={String((e.config as { paramsText?: string }).paramsText ?? "")} onChange={ev => set({ paramsText: ev.target.value })} placeholder='params JSON e.g. {"amount": 500}' />
          </div>
        )}
      </div>
      {onRemove && <button onClick={onRemove} style={{ ...ghostBtn, color: "var(--r2)", padding: "6px 4px" }}>✕</button>}
    </div>
  );
}

// ── helpers ───────────────────────────────────────────────────────────────────

function describeCondition(c: AutoCondition): string {
  if (c.kind === "schedule") return `schedule(${c.config.cron ?? ""})`;
  if (c.kind === "metric") return `metric(${c.config.monitor_id ?? ""})`;
  return `${c.kind}(${c.config.table ?? ""})`;
}
function describeEffect(e: AutoEffect): string {
  const t = e.config.action_id || e.config.subscription_id || e.config.trigger_id || e.config.question || "";
  return `${e.kind}${t ? `(${String(t).slice(0, 24)})` : ""}`;
}

function relTime(iso: string): string {
  try {
    const diff = Date.now() - new Date(iso).getTime();
    const m = Math.floor(diff / 60000);
    if (m < 2) return "just now";
    if (m < 60) return `${m}m ago`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h}h ago`;
    return `${Math.floor(h / 24)}d ago`;
  } catch { return iso; }
}

function EmptyState({ onAdd }: { onAdd: () => void }) {
  return (
    <div style={{ textAlign: "center", paddingTop: 60, color: "var(--t3)" }}>
      <div style={{ fontSize: 32, marginBottom: 12 }}>⚙️</div>
      <div style={{ fontSize: 14, fontWeight: 500, color: "var(--t2)", marginBottom: 6 }}>No automations yet</div>
      <div style={{ fontSize: 12, marginBottom: 20 }}>Bind a condition (a schedule, a metric, a data change) to an effect — investigate, deliver a brief, notify, or run a governed action.</div>
      <Button variant="ghost" className="h-auto" onClick={onAdd}>Create first automation</Button>
    </div>
  );
}
