"use client";
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { AutomationGraph } from "@/components/AutomationGraph";
import {
  Automation,
  AutomationRun,
  AutoCondition,
  AutoEffect,
  importForeignFlow,
  type ImportFlowResult,
  proposeAutomation,
  StagedProposal,
  StandingGrant,
  getAutomations,
  getConnections,
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
import { ghostBtn, useIntegrationGrants } from "@/components/automations/AutomationRows";
import { bindingRefs } from "@/lib/automationFlow";
import { MiniStat, MiniStatRow } from "@/components/ui/MiniStat";
import { Button } from "@/components/ui/button";

// ── Vocabulary (mirrors the backend Literals) ────────────────────────────────────

type View = "list" | "runs" | "inbox" | "canvas";

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

  // DS-1R — canvas-first creation ("while creating the automation itself, the workflow
  // screen should be the starting point… a blank canvas with only the trigger node
  // placed by default" — the user, 2026-09-02). `creating` holds the seed a new canvas
  // starts from: a DS-15 proposal's chain, or nothing for the blank canvas.
  const [creating, setCreating] =
    useState<{ seed?: { conditions: AutoCondition[]; effects: AutoEffect[] } } | null>(null);
  const [createName, setCreateName] = useState("");
  const [outcome, setOutcome] = useState("");
  const [proposing, setProposing] = useState(false);
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
      //
      // DS-8 — `paused` is neither "ran" nor "did not run": the chain ran, did real work,
      // and stopped in the middle for a person. Flashing it red as "Did not run" would tell
      // the author their automation is broken at the exact moment it behaved correctly.
      flash(run.outcome === "error" ? "err" : "ok",
            run.outcome === "fired" ? "Ran"
              : run.outcome === "paused" ? `Waiting on approval — ${run.reason}`
              : `Did not run — ${run.reason || run.outcome}`);
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

  /** DS-15 — ask the agent for a chain, then draw the draft on a fresh canvas.
   *
   * A REFUSAL is rendered as a message, not an error: "nothing on this deployment can do
   * that" is a considered answer, and the reason (which bot is missing, which kind is
   * unavailable) is the useful half. Only a proposal opens the canvas — where a person
   * sees the chain as it will run, edits it in place, and presses the same Create.
   */
  const onPropose = async () => {
    if (!outcome.trim() || !conn) return;
    setProposing(true);
    try {
      const p = await proposeAutomation(outcome.trim(), conn);
      if (p.verdict !== "proposed" || !p.draft) {
        flash("err", p.reason || "nothing here can do that yet");
        return;
      }
      setCanvasFor(null);
      setCreateName(p.draft.name || "Proposed automation");
      setCreating({ seed: { conditions: p.draft.conditions, effects: p.draft.effects } });
      setView("canvas");
      // The receipt in one line: the dry run walked the chain without dispatching.
      const steps = (p.draft.effects || []).length;
      flash("ok", `Proposed ${steps} step${steps === 1 ? "" : "s"} — dry-run checked, nothing saved yet.`
        + (p.notes ? ` Note: ${p.notes}` : ""));
      setOutcome("");
    } catch (e) {
      flash("err", (e as Error).message);
    } finally {
      setProposing(false);
    }
  };

  /** DS-16 — the migration funnel: a Langflow/Flowise export, translated. The report
   *  is shown BEFORE the canvas — the refusals and their alternatives are half the
   *  receipt, and a reader deciding whether the translation is faithful needs them in
   *  front of the chain, not behind a toast. */
  const [importReport, setImportReport] = useState<ImportFlowResult | null>(null);
  const importFileRef = useRef<HTMLInputElement>(null);

  const onImportFile = async (file: File) => {
    let doc: unknown;
    try { doc = JSON.parse(await file.text()); }
    catch { flash("err", `${file.name} is not JSON — export the flow from the editor`); return; }
    try { setImportReport(await importForeignFlow(doc)); }
    catch (e) { flash("err", (e as Error).message); }
  };

  const openImportedDraft = () => {
    const r = importReport;
    if (!r?.draft) return;
    setImportReport(null);
    setCanvasFor(null);
    setCreateName(r.name || "Imported flow");
    setCreating({ seed: { conditions: r.draft.conditions, effects: r.draft.effects } });
    setView("canvas");
    const holes = r.to_fill?.length ? ` — still to fill: ${r.to_fill.join(", ")}` : "";
    flash("ok", `Imported from ${r.source} — nothing saved yet${holes}.`);
  };

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
      flash(run.outcome === "error" ? "err" : "ok",
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
          {TABS.map(v => (
            <Button
              key={v} variant="ghost"
              onClick={() => setView(v)}
              className="h-auto"
              style={{
                padding: "6px 14px", fontSize: 12, borderRadius: 0, fontWeight: 500,
                background: view === v ? "var(--blue3)" : "transparent",
                color: view === v ? "#fff" : "var(--t3)",
                borderBottom: view === v ? "2px solid var(--blue3)" : "2px solid transparent",
              }}>
              {v === "list" ? "Automations" :
               v === "runs" ? "Runs" :
               <>Inbox {pendingCount > 0 && <span style={{ marginLeft: 4, background: "var(--red3)", color: "#fff", borderRadius: 8, padding: "1px 5px", fontSize: 11 }}>{pendingCount}</span>}</>}
            </Button>
          ))}
        </div>
        <div style={{ flex: 1 }} />
        {view === "list" && (
          <>
            {/* DS-15 — the other way in. Creation by PROPOSAL: describe the outcome, the
                agent drafts a chain grounded in what this deployment actually has, and it
                arrives as a seeded form with a dry-run receipt. Nothing is saved until the
                person presses the same Create button they always would. */}
            <input
              className="aug-fs-sm"
              placeholder="or describe it — e.g. post a Monday pipeline summary to #revenue"
              value={outcome}
              onChange={e => setOutcome(e.target.value)}
              onKeyDown={e => { if (e.key === "Enter") void onPropose(); }}
              style={{
                width: 340, padding: "5px 10px", marginRight: 8,
                borderRadius: "var(--r3)", border: "1px solid var(--b1)",
                background: "var(--bg-1, var(--bg-2))", color: "var(--t1)",
              }} />
            <Button variant="ghost" className="h-auto aug-fs-sm" disabled={!outcome.trim() || proposing}
              onClick={() => void onPropose()} style={{ padding: "5px 12px" }}>
              {proposing ? "Drafting…" : "Propose"}
            </Button>
            <input ref={importFileRef} type="file" accept=".json,application/json"
              style={{ display: "none" }}
              onChange={e => {
                const f = e.target.files?.[0];
                e.target.value = "";
                if (f) void onImportFile(f);
              }} />
            <Button variant="ghost" className="h-auto aug-fs-sm"
              title="Translate a Langflow or Flowise flow export into a governed chain"
              onClick={() => importFileRef.current?.click()}
              style={{ padding: "5px 12px" }}>
              Import flow…
            </Button>
            <Button variant="ghost" className="h-auto"
              onClick={() => { setCanvasFor(null); setCreateName("Untitled automation");
                               setCreating({}); setView("canvas"); }}
              style={{ fontSize: 12, padding: "5px 12px" }}>
              + New automation
            </Button>
          </>
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
        {/* DS-16 — the translation report, shown BEFORE the canvas: the refusals and
            their alternatives are half the receipt. */}
        {importReport && (
          <div data-testid="import-report" style={{ position: "absolute", inset: 0,
            zIndex: 10, background: "var(--bg-0)", padding: "10px 16px",
            display: "flex", flexDirection: "column", gap: 10 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <span className="aug-fs-ui" style={{ fontWeight: 600 }}>
                {importReport.verdict === "imported"
                  ? `Translated “${importReport.name}” from ${importReport.source}`
                  : importReport.verdict === "nothing_mapped"
                    ? "Nothing in this flow mapped onto a governed step"
                    : "Could not read this file"}
              </span>
              <span style={{ flex: 1 }} />
              <Button variant="ghost" size="sm" className="aug-fs-sm"
                onClick={() => setImportReport(null)}>Cancel</Button>
              {importReport.verdict === "imported" && (
                <Button variant="default" size="sm" className="aug-fs-sm"
                  onClick={openImportedDraft}>
                  Open on canvas — nothing saved yet
                </Button>
              )}
            </div>
            {importReport.reason && (
              <div className="aug-fs-sm" style={{ color: "var(--t3)" }}>{importReport.reason}</div>
            )}
            {!!importReport.to_fill?.length && (
              <div className="aug-fs-sm" style={{ color: "var(--amb4)" }}>
                Still to fill on the canvas: {importReport.to_fill.join(" · ")}
              </div>
            )}
            {importReport.suggested_agent && (
              <div className="aug-fs-sm" style={{ padding: "8px 10px",
                border: "1px solid var(--b1)", borderRadius: "var(--r2)",
                color: "var(--t2)" }}>
                The flow&rsquo;s agent proposes a NEW agent record (nothing created):{" "}
                <b>{importReport.suggested_agent.name}</b> —{" "}
                <span style={{ color: "var(--t3)" }}>
                  {importReport.suggested_agent.instructions.slice(0, 160)}
                  {importReport.suggested_agent.instructions.length > 160 ? "…" : ""}
                </span>{" "}
                Create it from Agent Ops → Roster, then bind the step to it.
              </div>
            )}
            <div style={{ flex: 1, overflowY: "auto", display: "flex",
              flexDirection: "column", gap: 4 }}>
              {importReport.report.map(row => (
                <div key={row.node_id} className="aug-fs-sm" style={{ display: "flex",
                  gap: 8, padding: "6px 9px", border: "1px solid var(--b1)",
                  borderRadius: "var(--r2)", alignItems: "baseline" }}>
                  <span style={{ flexShrink: 0, fontWeight: 600, color:
                    row.disposition === "mapped" ? "var(--grn4)"
                    : row.disposition === "refused" ? "var(--red4)"
                    : "var(--t3)" }}>
                    {row.disposition}
                  </span>
                  <span style={{ flexShrink: 0, fontFamily: "var(--font-mono)",
                    color: "var(--t2)" }}>{row.component}</span>
                  <span style={{ color: "var(--t3)" }}>{row.detail}</span>
                </div>
              ))}
            </div>
          </div>
        )}
        {showSpinner && <div style={{ color: "var(--t3)", fontSize: 13 }}>Loading…</div>}

        {view === "list" && !showSpinner && (
          automations.length === 0
            ? <EmptyState onAdd={() => { setCanvasFor(null); setCreateName("Untitled automation");
                                         setCreating({}); setView("canvas"); }}
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
                      onEdit={() => { setCreating(null); setCanvasFor(a); setView("canvas"); }} onDelete={() => onDelete(a)}
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

        {view === "canvas" && (canvasFor || creating) && (
          // The canvas gets the ROOM — full-bleed, one header strip (the graph's own),
          // no rail. `canvasFor` is re-read from the loaded list after a save so the
          // header chip and the next open reflect what is now stored; `creating` is the
          // canvas-first birth of a record that does not exist yet.
          <div style={{ position: "absolute", inset: 0, display: "flex",
            flexDirection: "column", background: "var(--bg-0)", padding: "10px 16px" }}>
            {canvasFor ? (
              <AutomationGraph
                automationId={canvasFor.id}
                automation={automations.find(x => x.id === canvasFor.id) ?? canvasFor}
                header={{
                  name: canvasFor.name, enabled: canvasFor.enabled,
                  onBack: () => setView("list"),
                  // DS-3 — the canvas's own Run now NAMES the run before starting it.
                  // The request does not return until the chain is over, so a run the
                  // client cannot name is a run it can only be told about.
                  onRunNow: () => void runLive(canvasFor), running: !!liveRun,
                }}
                onSaved={load}
                liveRunId={liveRun}
              />
            ) : (
              <AutomationGraph
                create={{ connId: conn, seed: creating?.seed }}
                header={{
                  name: createName, onName: setCreateName,
                  onBack: () => { setCreating(null); setView("list"); },
                }}
                onCreated={async (a) => {
                  setCreating(null); setCanvasFor(a);
                  await load(); flash("ok", `Created "${a.name}"`);
                }}
              />
            )}
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

/** One row of the runs rail: a real run, or a run of consecutive quiet ticks. */
export type RunRow =
  | { kind: "run"; run: AutomationRun }
  | { kind: "quiet"; count: number; newest: string; oldest: string; reason: string };

/** Collapse ADJACENT scheduler ticks that did nothing, so the run that DID something is
 *  visible without scrolling.
 *
 * Measured on this deployment 2026-09-03: **99 of the last 100 runs were `not_fired`** —
 * pure scheduler ticks reading "schedule(0 9 * * *): next due …", carrying no effects and
 * no error. One fired run was buried under ninety-nine identical cards.
 *
 * **Adjacent only, and the front row keeps the count** — the stacking rule this project
 * already applies on every canvas, brought to a list.
 *
 * **This must not HIDE anything, or it becomes the catalogue that lies.** So a tick is only
 * collapsible when it did nothing at all: `not_fired`, no effects, no error. A `not_fired`
 * run that somehow carried an effect stays a full card, because "the schedule was not due"
 * and "something happened and was not recorded as firing" are different sentences and only
 * one of them is boring. The group states the exact count, the span it covers, and the
 * shared reason when every tick in it gives the same one.
 */
export function collapseQuietTicks(runs: AutomationRun[]): RunRow[] {
  const out: RunRow[] = [];
  for (const run of runs) {
    const quiet = run.outcome === "not_fired"
      && (run.effects?.length ?? 0) === 0
      && !run.error;
    const last = out[out.length - 1];
    if (!quiet) {
      out.push({ kind: "run", run });
      continue;
    }
    if (last && last.kind === "quiet") {
      last.count += 1;
      // `runs` arrives newest-first, so each further tick extends the OLDER end.
      last.oldest = run.started_at;
      // A shared reason is only shared while every tick agrees; the moment one differs the
      // group stops claiming one rather than quietly showing the first.
      if (last.reason && last.reason !== run.reason) last.reason = "";
    } else {
      out.push({ kind: "quiet", count: 1, newest: run.started_at,
                 oldest: run.started_at, reason: run.reason ?? "" });
    }
  }
  return out;
}


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
        {collapseQuietTicks(runs).map(row => row.kind === "quiet" ? (
          // A run of ticks that did nothing, as ONE row. The count and the span are exact:
          // this collapses, it does not hide.
          <div key={`quiet:${row.newest}`} style={{
            display: "flex", alignItems: "center", gap: 8, padding: "6px 14px",
            border: "1px dashed var(--b1)", borderRadius: 6, color: "var(--t3)",
          }}>
            <span style={{ fontSize: 11, fontWeight: 700, padding: "2px 7px", borderRadius: 4,
              textTransform: "uppercase", background: "var(--bg-2)", color: "var(--t3)" }}>
              not fired ×{row.count}
            </span>
            <span style={{ fontSize: 12 }}>
              {row.reason || "the schedule was not due"}
            </span>
            <div style={{ flex: 1 }} />
            <span style={{ fontSize: 11 }}>
              {row.count > 1 ? `${relTime(row.oldest)} → ${relTime(row.newest)}` : relTime(row.newest)}
            </span>
          </div>
        ) : (() => { const r = row.run; return (
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
        ); })())}
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
  // DS-11's completion — the accounts, so an integration proposal can say WHOSE consent
  // it spends in the words a person picked it by ("slack · Aughor HQ"), not as the id the
  // step happens to store. A grant that is gone falls back to the id: unlovely, and still
  // the honest answer to "which account was this?".
  const accounts = useIntegrationGrants();
  const accountLabel = (id: string) => {
    const g = accounts.find(a => a.id === id);
    return g ? `${g.provider}${g.account ? ` · ${g.account}` : ""}` : id;
  };
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
            {/* DS-11's completion — WHOSE consent this would spend. A person approving a
                write has to be told which account it goes out as; the card said only what
                would be done, which reads the same for two different accounts. */}
            {p.kind === "integration" && p.grant_id && (
              <span className="aug-fs-xs" style={{ color: "var(--amb4)" }}>
                as {accountLabel(p.grant_id)}
              </span>
            )}
            <span style={{ fontSize: 11, color: "var(--t3)" }}>by {p.proposer}</span>
          </div>
          {p.reasoning && <div style={{ fontSize: 12, color: "var(--t2)", marginTop: 4 }}>{p.reasoning}</div>}
          <div style={{ fontSize: 11, color: "var(--t3)", marginTop: 4, fontFamily: "var(--font-mono, monospace)" }}>
            {JSON.stringify(p.params)}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 10 }}>
            <Button variant="ghost" className="h-auto" onClick={() => accept(p)} style={{ fontSize: 11, padding: "3px 12px", background: "var(--blue3)", color: "#fff" }}>Accept</Button>
            <Button variant="ghost" className="h-auto p-0 font-normal" onClick={() => reject(p)} style={{ ...ghostBtn, color: "var(--red3)" }}>Reject</Button>
            {/* A standing GRANT is target-bound to a declared action's coerced params; the
                standing permission for an integration write is an allowlist entry on
                (operation, account), which has a door of its own under Approvals. Offering
                a checkbox that does nothing is worse than not offering one. */}
            {p.kind === "integration" ? (
              <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>
                to allow this account unattended, approve it under Approvals
              </span>
            ) : (
              <label style={{ fontSize: 11, color: "var(--t3)", display: "flex", alignItems: "center", gap: 5, cursor: "pointer" }}>
                <input type="checkbox" checked={!!mintFor[p.id]} onChange={e => setMintFor(m => ({ ...m, [p.id]: e.target.checked }))} />
                also allow this target unattended
              </label>
            )}
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
  // found by driving a step whose channel is bound. DS-6's join hit the identical
  // hole one form over ("slack_post([object Object])", found the same way), so both
  // shapes now go through the one helper that reads references — a third binding
  // form would land in `bindingRefs`, not here.
  const refs = bindingRefs(t);
  const target = refs.length ? refs.join(" or ") : String(t);
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
