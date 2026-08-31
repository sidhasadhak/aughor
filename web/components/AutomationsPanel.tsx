"use client";
import React, { useCallback, useEffect, useMemo, useState } from "react";

import { AutomationGraph } from "@/components/AutomationGraph";
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
  getConnections,
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
  listUserAgents,
  getSlackBots,
  type SlackBotSummary,
  type UserAgent,
} from "@/lib/api";
import {
  CONDITION_KINDS, CRON_PRESETS, ConditionRow, EFFECT_KINDS, EffectRow,
  effectsForWire, ghostBtn, inputStyle, labelStyle, newCondition, newEffect,
} from "@/components/automations/AutomationRows";
import { MiniStat, MiniStatRow } from "@/components/ui/MiniStat";
import { Button } from "@/components/ui/button";

// ── Vocabulary (mirrors the backend Literals) ────────────────────────────────────

type View = "list" | "runs" | "inbox" | "form" | "canvas";

const OUTCOME_COLOR: Record<string, string> = {
  fired:     "var(--grn3)",
  not_fired: "var(--t3)",
  gated:     "var(--chart-threshold-warn, #f59e0b)",
  error:     "var(--red3)",
};

const STATUS_COLOR: Record<string, string> = {
  executed:          "var(--grn3)",
  failed:            "var(--red3)",
  dispatch_error:    "var(--red3)",
  criterion_failed:  "var(--chart-threshold-warn, #f59e0b)",
  approval_required: "var(--chart-threshold-warn, #f59e0b)",
  skipped:           "var(--t3)",
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
  /** The automation whose CANVAS fills the panel. The flow used to render as a 420px
   *  strip inside its list row — a workflow in a drawer. The frames the user pointed
   *  at (Langflow, VoltAgent) give the flow the whole room, and they are right: a
   *  canvas competing with a list for height is a canvas at 55%% zoom forever. */
  const [canvasFor, setCanvasFor] = useState<Automation | null>(null);
  /** DS-3 — the run the canvas is watching. Set BEFORE the request, cleared when it
   *  resolves; the canvas reads its spans in between. */
  const [liveRun, setLiveRun] = useState<string | null>(null);

  const runLive = async (a: Automation) => {
    const id = (globalThis.crypto?.randomUUID?.() ?? `run-${Date.now()}`);
    setLiveRun(id);
    try {
      const run = await runAutomation(a.id, id);
      // Outcomes that emit no span at all — gated, not due — would otherwise leave the
      // canvas waiting for a step that is never going to start.
      flash(run.outcome === "fired" ? "ok" : "err",
            run.outcome === "fired" ? "Ran" : `Did not run — ${run.reason || run.outcome}`);
    } catch (e) {
      flash("err", String((e as Error)?.message || e));
    } finally {
      setLiveRun(null);
      await load();
    }
  };

  const flash = useCallback((tone: "ok" | "err", text: string) => {
    setBanner({ tone, text });
    setTimeout(() => setBanner(b => (b?.text === text ? null : b)), 4000);
  }, []);

  /** W2 follow-up — automations that exist, but not on THIS connection.
   *
   *  The empty state used to say "No automations yet · Create first automation" — the
   *  message for *nothing exists* — while three sat on another connection. This panel is
   *  connection-scoped (`getAutomations(conn)`) and the scope is chosen on a different
   *  screen, so "yet" was the one word a reader could not check. Found by a user losing
   *  time to it. Asked only when the scoped list comes back empty: a second request on
   *  every load, to answer a question nobody asked, is the wrong trade. */
  const [elsewhere, setElsewhere] = useState<{ count: number; where: string[] } | null>(null);

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

  useEffect(() => {
    if (loading || automations.length > 0 || !conn) { setElsewhere(null); return; }
    let live = true;
    void (async () => {
      try {
        const [all, conns] = await Promise.all([getAutomations(), getConnections()]);
        if (!live) return;
        const others = all.filter(a => a.conn_id !== conn);
        const name = new Map(conns.map(c => [c.id, c.name]));
        setElsewhere({
          count: others.length,
          // Named, deduped, in the words the connection picker uses — an id like
          // `8233e4fd` tells a reader nothing about where to go next.
          where: [...new Set(others.map(a => name.get(a.conn_id) ?? a.conn_id))],
        });
      } catch { /* the empty state degrades to its plain form; it must never fail a panel */ }
    })();
    return () => { live = false; };
  }, [loading, automations.length, conn]);

  useEffect(() => { load(); }, [load]);

  /** Show the spinner only when there is nothing on screen yet.
   *
   *  `load()` is also the REFRESH after a canvas save, and gating the list on bare
   *  `loading` unmounted every card while it ran — which destroyed each card's own
   *  "is the flow open" state, so saving a design from the canvas closed the canvas you
   *  had just saved from. Replacing content a reader is already looking at with the word
   *  "Loading…" is the wrong trade even when nothing depends on the state. */
  const showSpinner = loading && automations.length === 0;

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
               v === "inbox" ? <>Inbox {pendingCount > 0 && <span style={{ marginLeft: 4, background: "var(--red3)", color: "#fff", borderRadius: 8, padding: "1px 5px", fontSize: 11 }}>{pendingCount}</span>}</> :
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
          background: banner.tone === "ok" ? "var(--grn1)" : "var(--red1)",
          color: banner.tone === "ok" ? "var(--grn5)" : "var(--red5)",
          border: "1px solid var(--bg-3)",
        }}>{banner.text}</div>
      )}

      {/* Body */}
      <div style={{ flex: 1, overflowY: "auto", padding: 20, position: "relative" }}>
        {showSpinner && <div style={{ color: "var(--t3)", fontSize: 13 }}>Loading…</div>}

        {view === "list" && !showSpinner && (
          automations.length === 0
            ? <EmptyState onAdd={() => { setEditing(null); setView("form"); }}
                elsewhere={elsewhere} />
            : <>
                <MiniStatRow>
                  <MiniStat value={stats.total} label="Automations" />
                  <MiniStat value={stats.enabled} label="Enabled" tone="var(--grn3)" />
                  <MiniStat value={stats.paused} label="Muted" tone="var(--chart-threshold-warn, #f59e0b)" />
                </MiniStatRow>
                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                  {automations.map(a => (
                    <AutomationCard key={a.id} a={a}
                      onToggle={() => onToggle(a)} onPause={() => onPause(a)} onRun={() => onRun(a)}
                      onEdit={() => { setEditing(a); setView("form"); }} onDelete={() => onDelete(a)}
                      onRuns={() => openRuns(a)}
                      onCanvas={() => { setCanvasFor(a); setView("canvas"); }} />
                  ))}
                </div>
              </>
        )}

        {view === "runs" && !showSpinner && (
          <RunsView automations={automations} runsFor={runsFor} runs={runs} onPick={openRuns} />
        )}

        {view === "inbox" && !showSpinner && (
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

        {view === "canvas" && canvasFor && (
          // The canvas gets the ROOM. Height is the panel's, not a strip's; the list is
          // one ← away. `canvasFor` is re-read from the loaded list after a save so the
          // header chip and the next open reflect what is now stored.
          <div style={{ position: "absolute", inset: 0, display: "flex",
            flexDirection: "column", background: "var(--bg-0)", padding: "10px 16px" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, paddingBottom: 8 }}>
              <Button variant="ghost" size="sm" className="aug-fs-sm"
                onClick={() => setView("list")} style={{ color: "var(--t3)" }}>
                ← Automations
              </Button>
              <span className="aug-fs-ui" style={{ fontWeight: 600 }}>{canvasFor.name}</span>
              <span className="aug-fs-xs" style={{
                color: canvasFor.enabled ? "var(--grn4)" : "var(--t4)" }}>
                ● {canvasFor.enabled ? "enabled" : "disabled"}
              </span>
              <span style={{ flex: 1 }} />
              {/* DS-3 — the canvas's own Run now NAMES the run before starting it. The
                  request does not return until the chain is over, so a run the client
                  cannot name is a run it can only be told about. The list's button is
                  unchanged: nothing is watching there. */}
              <Button variant="ghost" size="sm" className="aug-fs-xs" disabled={!!liveRun}
                onClick={() => runLive(canvasFor)}>
                {liveRun ? "Running…" : "Run now"}
              </Button>
            </div>
            <div style={{ flex: 1, minHeight: 0 }}>
              <AutomationGraph
                automationId={canvasFor.id}
                automation={automations.find(x => x.id === canvasFor.id) ?? canvasFor}
                onSaved={load}
                liveRunId={liveRun}
              />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ── List card ─────────────────────────────────────────────────────────────────

function AutomationCard({ a, onToggle, onPause, onRun, onEdit, onDelete, onRuns, onCanvas }: {
  a: Automation;
  onToggle: () => void; onPause: () => void; onRun: () => void;
  onEdit: () => void; onDelete: () => void; onRuns: () => void;
  /** Open this automation's canvas as the panel's full view. */
  onCanvas: () => void;
}) {
  const muted = isFuture(a.paused_until);
  // VA-4b — collapsed by default. The one-line summary is the right density for a list;
  // the graph is what you open when you want to see what feeds what. Mounted only when
  // open, so a page of automations does not fetch a graph per row.
  return (
    <div style={{
      background: "var(--bg-1, var(--bg-2))", border: "1px solid var(--b1)", borderRadius: "var(--r3)",
      padding: "12px 16px", opacity: a.enabled ? 1 : 0.6,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <Button variant="ghost" onClick={onToggle} title={a.enabled ? "Disable" : "Enable"} className="h-auto p-0" style={{
          width: 34, height: 18, borderRadius: 10, border: "none", cursor: "pointer", flexShrink: 0,
          background: a.enabled ? "var(--blue3)" : "var(--bg-3)", position: "relative",
        }}>
          <span style={{
            position: "absolute", top: 2, left: a.enabled ? 18 : 2, width: 14, height: 14,
            borderRadius: "50%", background: "#fff", transition: "left .12s",
          }} />
        </Button>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontSize: 13, fontWeight: 600 }}>{a.name}</span>
            {muted && <span style={{ background: "var(--chart-threshold-warn, #f59e0b)", color: "#fff", borderRadius: 8, padding: "1px 6px", fontSize: 11 }}>muted</span>}
            {a.last_status && <span style={{ color: OUTCOME_COLOR[a.last_status] || "var(--t3)", fontSize: 11 }}>● {a.last_status}</span>}
          </div>
          <div style={{ fontSize: 11, color: "var(--t3)", marginTop: 2 }}>
            {a.conditions.map(describeCondition).join(a.condition_logic === "all" ? " AND " : " OR ")}
            {" → "}
            {a.effects.map(describeEffect).join(", ")}
          </div>
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          <Button variant="ghost" onClick={onCanvas} className="h-auto p-0 font-normal"
                  style={ghostBtn}>Design</Button>
          <Button variant="ghost" onClick={onRun} className="h-auto" style={{ fontSize: 11, padding: "3px 9px", opacity: 0.85 }}>Run now</Button>
          <Button variant="ghost" onClick={onRuns} className="h-auto p-0 font-normal" style={ghostBtn}>History</Button>
          <Button variant="ghost" onClick={onPause} className="h-auto p-0 font-normal" style={ghostBtn}>{muted ? "Unmute" : "Mute"}</Button>
          <Button variant="ghost" onClick={onEdit} className="h-auto p-0 font-normal" style={ghostBtn}>Edit</Button>
          <Button variant="ghost" onClick={onDelete} className="h-auto p-0 font-normal" style={{ ...ghostBtn, color: "var(--red3)" }}>Delete</Button>
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
                fontSize: 11, fontWeight: 700, padding: "2px 7px", borderRadius: 4, textTransform: "uppercase",
                background: OUTCOME_COLOR[r.outcome] || "var(--t3)", color: "#fff",
              }}>{r.outcome.replace("_", " ")}</span>
              <span style={{ fontSize: 12, color: "var(--t2)" }}>{r.reason}</span>
              <div style={{ flex: 1 }} />
              <span style={{ fontSize: 11, color: "var(--t3)" }}>{relTime(r.started_at)} · {r.duration_ms}ms</span>
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
            {r.error && <div style={{ marginTop: 4, fontSize: 11, color: "var(--red3)" }}>{r.error}</div>}
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
            <span style={{ fontSize: 11, color: "var(--t3)" }}>by {p.proposer}</span>
          </div>
          {p.reasoning && <div style={{ fontSize: 12, color: "var(--t2)", marginTop: 4 }}>{p.reasoning}</div>}
          <div style={{ fontSize: 11, color: "var(--t3)", marginTop: 4, fontFamily: "var(--font-mono, monospace)" }}>
            {JSON.stringify(p.params)}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 10 }}>
            <Button variant="ghost" className="h-auto" onClick={() => accept(p)} style={{ fontSize: 11, padding: "3px 12px", background: "var(--blue3)", color: "#fff" }}>Accept</Button>
            <Button variant="ghost" className="h-auto p-0 font-normal" onClick={() => reject(p)} style={{ ...ghostBtn, color: "var(--red3)" }}>Reject</Button>
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
              <span style={{ fontSize: 11, color: "var(--t3)" }}>used {g.use_count}× · by {g.created_by || g.owner_kind}</span>
              <div style={{ flex: 1 }} />
              <Button variant="ghost" className="h-auto p-0 font-normal" onClick={() => revoke(g)} style={{ ...ghostBtn, color: "var(--red3)" }}>Revoke</Button>
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

function AutomationForm({ conn, initial, onCancel, onSaved, onError }: {
  conn: string; initial: Automation | null;
  onCancel: () => void; onSaved: () => void; onError: (t: string) => void;
}) {
  const [name, setName] = useState(initial?.name ?? "");
  const [logic, setLogic] = useState<"all" | "any">(initial?.condition_logic ?? "all");
  const [conditions, setConditions] = useState<AutoCondition[]>(
    initial?.conditions ?? [newCondition()]);
  const [effects, setEffects] = useState<AutoEffect[]>(
    initial?.effects ?? [newEffect()]);
  const [maxRetries, setMaxRetries] = useState(initial?.max_retries ?? 1);
  const [saving, setSaving] = useState(false);
  // The personas an `investigate` effect may run as (Wave H1). Empty when the
  // roster is empty — the picker then simply doesn't render, and
  // an unbound deep-analysis run is still the default.
  const [agents, setAgents] = useState<UserAgent[]>([]);
  const [bots, setBots] = useState<SlackBotSummary[]>([]);
  useEffect(() => { listUserAgents().then(setAgents).catch(() => setAgents([])); }, []);
  useEffect(() => { getSlackBots().then(setBots).catch(() => setBots([])); }, []);

  const setCond = (i: number, c: AutoCondition) => setConditions(cs => cs.map((x, j) => j === i ? c : x));
  const setEff = (i: number, e: AutoEffect) => setEffects(es => es.map((x, j) => j === i ? e : x));

  const save = async () => {
    if (!conn) { onError("No connection selected"); return; }
    if (!name.trim()) { onError("Name is required"); return; }
    // `paramsText` → parsed `params`, in the one place both surfaces share.
    let builtEffects: AutoEffect[];
    try { builtEffects = effectsForWire(effects); }
    catch (err) { onError((err as Error).message); return; }

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
        <Button variant="ghost" className="h-auto p-0 font-normal" onClick={() => setConditions(cs => [...cs, newCondition()])} style={{ ...ghostBtn, color: "var(--blue3)", marginTop: 2 }}>+ add condition</Button>
      </div>

      {/* Effects */}
      <div style={{ marginBottom: 16 }}>
        <label style={labelStyle}>Then (in order)</label>
        {effects.map((e, i) => (
          <EffectRow key={i} e={e} agents={agents} bots={bots} siblings={effects} index={i}
            onChange={ee => setEff(i, ee)}
            onRemove={effects.length > 1 ? () => setEffects(es => es.filter((_, j) => j !== i)) : undefined} />
        ))}
        <Button variant="ghost" className="h-auto p-0 font-normal" onClick={() => setEffects(es => [...es, newEffect()])} style={{ ...ghostBtn, color: "var(--blue3)", marginTop: 2 }}>+ add effect</Button>
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

// ── helpers ───────────────────────────────────────────────────────────────────

function describeCondition(c: AutoCondition): string {
  if (c.kind === "schedule") return `schedule(${c.config.cron ?? ""})`;
  if (c.kind === "metric") return `metric(${c.config.monitor_id ?? ""})`;
  return `${c.kind}(${c.config.table ?? ""})`;
}
function describeEffect(e: AutoEffect): string {
  // `channel` joins the list: a slack_post step described with no target read as a bare
  // "slack_post" on the card, which is the one thing a reader scanning the list wants.
  const t = e.config.action_id || e.config.subscription_id || e.config.trigger_id
    || e.config.question || e.config.channel || "";
  // B1 made these fields BINDABLE, and `String({$from: …})` is "[object Object]" —
  // found by driving a step whose channel is bound. A reference describes itself.
  const target = t && typeof t === "object" && "$from" in (t as object)
    ? String((t as { $from: unknown }).$from) : String(t);
  // W2 — a step that runs per item says so here too, or the list claims one send where
  // N happen.
  const fan = e.for_each ? " · per item" : "";
  return `${e.kind}${target ? `(${target.slice(0, 24)})` : ""}${fan}`;
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

function EmptyState({ onAdd, elsewhere }: {
  onAdd: () => void;
  /** Automations on OTHER connections, when this one has none. `null` while unknown or
   *  when there genuinely are none anywhere — the two read differently on purpose. */
  elsewhere?: { count: number; where: string[] } | null;
}) {
  const hidden = elsewhere && elsewhere.count > 0;
  return (
    <div style={{ textAlign: "center", paddingTop: 60, color: "var(--t3)" }}>
      <div style={{ fontSize: 28, marginBottom: 12 }}>⚙️</div>
      <div className="aug-fs-h2" style={{ fontWeight: 500, color: "var(--t2)", marginBottom: 6 }}>
        {hidden ? "No automations on this connection" : "No automations yet"}
      </div>
      {hidden ? (
        /* The scope, named, and where the rest of them are. "Yet" would be a lie a
           reader has no way to check from this screen. */
        <div className="aug-fs-sm" style={{ marginBottom: 20, lineHeight: 1.5 }}>
          {elsewhere.count} automation{elsewhere.count === 1 ? "" : "s"} exist on{" "}
          {elsewhere.where.join(", ")}. This list shows only the connection you have
          selected — switch to it to see them.
        </div>
      ) : (
        <div className="aug-fs-sm" style={{ marginBottom: 20, lineHeight: 1.5 }}>
          Bind a condition (a schedule, a metric, a data change) to an effect —
          investigate, deliver a briefing, notify, or run a governed action.
        </div>
      )}
      <Button variant="ghost" className="h-auto" onClick={onAdd}>
        {hidden ? "Create one here" : "Create first automation"}
      </Button>
    </div>
  );
}
