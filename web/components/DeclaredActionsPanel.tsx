"use client";

/**
 * DeclaredActionsPanel — what Aughor may do on a connection (Aughor Intelligence · 07 Actions).
 *
 * Numbered sections beside a rail. §01 the declared actions — what each does, what it is about, and
 * its gate — with the door to the action designer (`ontology/ActionDesigner`), which replaced the declare form on
 * 2026-10-09: the walk-through found that form a developer's, pre-filled with someone else's refund rule; §02 the overlay edits a person wrote over the data,
 * each withdrawable, with the form that annotates a value; §03 proposing actions from a finding. The
 * rail holds what is awaiting approval, with the doors that resolve it, and the permission model as
 * the code enforces it.
 *
 * Proposals are staged, never run from here. `POST /kinetic-actions/propose` writes each valid one
 * to the inbox, where it waits in the rail until a person approves it — which runs it exactly once —
 * or rejects it. This panel used to execute a proposal directly and leave its staged row pending, so
 * the same side effect could later be approved and run a second time.
 *
 * Drawn only from stored data. Left out: an action's scope and state and its runs in the last 30
 * days (no count is kept), an overlay edit's previous value (not stored), a dry-run door (none
 * exists), and a "disabled" gate (no such tier).
 */

import React, { useCallback, useEffect, useState } from "react";

import { ActionDesigner } from "@/components/ontology/ActionDesigner";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { ProposalCard } from "@/components/ProposalCard";
import { SkeletonRows } from "@/components/ui/motion";
import { toast } from "@/components/ui/toast";
import { getProposals, type StagedProposal } from "@/lib/api";
import { dismissSend, getSends, retrySend, type ActionSend } from "@/lib/objects";
import { claimsOf, getIdToken } from "@/lib/auth";
import { getApiBase } from "@/lib/config";
import { countNoun, formatCount, formatTimestamp, relTime } from "@/lib/format";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";

async function apiFetch(path: string, opts?: RequestInit) {
  const res = await fetch(`${getApiBase()}${path}`, { headers: { "Content-Type": "application/json" }, ...opts });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(text || `HTTP ${res.status}`);
  }
  return res.json();
}
const post = (p: string, b: unknown) => apiFetch(p, { method: "POST", body: JSON.stringify(b) });
const del = (p: string) => apiFetch(p, { method: "DELETE" });

/** Who is acting — the signed-in email, else the word the actions inbox uses. Provenance, not auth. */
const actorName = () => claimsOf(getIdToken())?.email || "human";

const input: React.CSSProperties = { width: "100%", padding: "6px 8px", fontSize: 12, border: "1px solid var(--b0)", borderRadius: 6, background: "var(--bg-2)", color: "var(--t1)", marginBottom: 6, boxSizing: "border-box" };

function Err({ e }: { e: string | null }) {
  return e ? <p className="aug-actions-err">{e}</p> : null;
}

/** The gate an action's risk puts on it, as `govern/actions.py` enforces it. */
const GATE: Record<string, { label: string; ask: boolean; title: string }> = {
  read_only: { label: "runs, audited", ask: false, title: "Read-only: never gated; every run is audited" },
  low:       { label: "runs, audited", ask: false, title: "Low risk — reversible or additive: runs without asking; every run is audited" },
  high:      { label: "needs approval", ask: true, title: "High risk: a person approves each run, or a standing grant pre-approves one target" },
};

/** What an action does, one line each: the calls it makes, what it writes, what it takes, what it must satisfy. */
function effectLines(a: any): string[] {
  const out: string[] = [];
  for (const se of a.side_effects || []) {
    out.push(se.kind === "http"
      ? `calls ${String(se.config?.method || "POST")} ${String(se.config?.url || "")}${se.config?.auth_secret ? " · key set" : ""}`
      : `side effect: ${String(se.kind)}`);
  }
  for (const e of a.edits || []) {
    out.push(`writes ${String(e.property)} on ${String(e.object)}${e.value ? ` = ${String(e.value)}` : ""} — an overlay, never the source`);
  }
  const params = (a.params || []).map((p: any) => `${p.name}:${p.kind === "object" ? p.object_type : p.data_type}`);
  if (params.length) out.push(`params ${params.join(", ")}`);
  for (const c of a.submission_criteria || []) out.push(`must satisfy ${String(c.expr)}`);
  if (a.verification?.sql) out.push(`verified by ${String(a.verification.sql)}`);
  if (a.reversibility === "irreversible") out.push("irreversible");
  else if (a.undo?.action_id) {
    const hours = Number(a.undo.window_hours) || 0;
    out.push(`undone by ${String(a.undo.action_id)}${hours > 0 ? ` within ${hours} h` : ""}`);
  }
  return out;
}

function Section({ title, meta, children }: { title: string; meta?: string; children: React.ReactNode }) {
  return (
    <section className="aug-brief-sec">
      <div className="aug-brief-body">
        <div className="aug-brief-head">
          <span className="aug-brief-eyebrow">{title}</span>
          {meta && <span className="aug-brief-meta">{meta}</span>}
        </div>
        {children}
      </div>
    </section>
  );
}

// ── §02 · annotating a value ─────────────────────────────────────────────────────

function AnnotateForm({ connectionId, onSaved }: { connectionId: string; onSaved: () => void }) {
  const [err, setErr] = useState<string | null>(null);
  const [f, setF] = useState({ table: "", column: "", key_column: "", row_key: "", body: "", kind: "annotation" });

  const save = async () => {
    setErr(null);
    try {
      await post(`/kinetic-actions/annotate?connection_id=${encodeURIComponent(connectionId)}`, f);
      setF({ ...f, body: "" }); onSaved();
    } catch (e: any) { setErr(String(e.message || e)); }
  };

  return (
    <div className="aug-actions-form">
      <div className="aug-actions-form-title">Annotate a value</div>
      <Err e={err} />
      <Input style={input} placeholder="table" value={f.table} onChange={e => setF({ ...f, table: e.target.value })} />
      <div style={{ display: "flex", gap: 6 }}>
        <Input style={{ ...input, flex: 1 }} placeholder="column (optional)" value={f.column} onChange={e => setF({ ...f, column: e.target.value })} />
        <Input style={{ ...input, flex: 1 }} placeholder="key column (optional)" value={f.key_column} onChange={e => setF({ ...f, key_column: e.target.value })} />
        <Input style={{ ...input, flex: 1 }} placeholder="row key (optional)" value={f.row_key} onChange={e => setF({ ...f, row_key: e.target.value })} />
      </div>
      <Input style={input} placeholder="annotation / correction text" value={f.body} onChange={e => setF({ ...f, body: e.target.value })} />
      <Button variant="default" size="sm" disabled={!f.table.trim() || !f.body.trim()} onClick={save}>Save annotation</Button>
    </div>
  );
}

// ── §03 · proposing from a finding ───────────────────────────────────────────────

function ProposeSection({ connectionId, onStaged }: { connectionId: string; onStaged: () => void }) {
  const [context, setContext] = useState("");
  const [proposals, setProposals] = useState<any[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const propose = async () => {
    setBusy(true); setErr(null); setProposals(null);
    try {
      const r = await post(`/kinetic-actions/propose?connection_id=${encodeURIComponent(connectionId)}`, { context });
      setProposals(r.proposals || []);
      onStaged();   // every valid proposal is now in the inbox: the rail shows it for approval
    } catch (e: any) { setErr(String(e.message || e)); }
    finally { setBusy(false); }
  };

  return (
    <>
      <Err e={err} />
      <p className="aug-brief-note">
        Paste a finding. The agent proposes any declared action it warrants; each valid proposal is staged in
        Awaiting approval, and nothing runs until a person approves it. Proposing uses a model call.
      </p>
      <Textarea style={{ ...input, minHeight: 72, marginTop: 8 }} placeholder="e.g. Order X9001 was charged EUR 480 twice — a clear duplicate charge." value={context} onChange={e => setContext(e.target.value)} />
      <Button variant="secondary" size="sm" disabled={busy || !context.trim()} onClick={propose}>
        {busy ? "Proposing…" : "Propose actions"}
      </Button>
      {proposals && proposals.length === 0 && <p className="aug-brief-note">The agent abstained — nothing to propose.</p>}
      {proposals && proposals.length > 0 && (
        <div className="aug-actions-proposals">
          {proposals.map((p, i) => (
            <div key={i} className="aug-actions-proposal">
              <div className="aug-approval-head">
                <span className="aug-approval-kind">{p.action_id}</span>
                <span className="aug-brief-meta">{p.inbox_id ? "staged · awaiting approval" : String(p.status)}</span>
              </div>
              {p.reasoning && <span className="aug-approval-why">{p.reasoning}</span>}
              <span className="aug-approval-params">
                {Object.entries(p.params ?? {}).map(([k, v]) => `${k}: ${String(v)}`).join(" · ") || "no parameters"}
              </span>
              {!p.ok && p.message && <p className="aug-actions-err">{p.message}</p>}
            </div>
          ))}
        </div>
      )}
    </>
  );
}

// ── The layer ────────────────────────────────────────────────────────────────────

const SEND_WORDS: Record<ActionSend["status"], string> = {
  queued: "waiting to be sent again", sending: "being sent", delivered: "delivered",
  unknown: "no answer — being checked", dead: "waits for you", dismissed: "left undelivered",
};

/** Arc OC-6 — the outbox of this connection's declared actions: the calls that wait for a person first, with Retry
 *  and Dismiss, then what was delivered or is being retried and why. Shown while the outbox is on, or holds any call. */
function SendsSection({ connectionId }: { connectionId: string }) {
  const [state, setState] = useState<{ enabled: boolean; sends: ActionSend[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState("");
  // the call a person is leaving undelivered, and why — asked on the row, never in a native prompt (an embedded
  // browser refuses `window.prompt`, and the button then did nothing; 2026-10-10)
  const [leaving, setLeaving] = useState<{ id: string; why: string } | null>(null);
  const load = useCallback(() => {
    getSends(connectionId).then(r => { setState({ enabled: !!r?.enabled, sends: r?.sends ?? [] }); setError(null); })
      .catch(e => setError(String(e.message || e)));
  }, [connectionId]);
  useEffect(() => { if (connectionId) load(); }, [connectionId, load]);
  if (!state) return error ? <Err e={error} /> : null;
  if (!state.enabled && state.sends.length === 0) {
    // Off is said, never implied: a section that hid itself read as a feature that does not exist (2026-10-10).
    return (
      <Section title="Sends" meta="the outbox is off">
        <p className="aug-brief-note" data-testid="sends-off">
          A declared action's calls to other systems go out once, when it is pressed, and are not kept. Switch the outbox
          on in Settings → System → Feature flags to keep each call, retry it by why it failed, and hand you the ones
          that need a person.
        </p>
      </Section>
    );
  }
  const waiting = state.sends.filter(s => s.status === "dead" || s.status === "unknown");
  const rest = state.sends.filter(s => s.status !== "dead" && s.status !== "unknown").slice(0, 20);
  const act = async (s: ActionSend, what: "retry" | "dismiss", why = "") => {
    setBusy(s.id);
    try {
      if (what === "retry") await retrySend(connectionId, s.id);
      else await dismissSend(connectionId, s.id, why);
      setLeaving(null);
      load();
    } catch (e) {
      toast.error(what === "retry" ? "Not sent" : "Not dismissed", { description: String((e as Error).message || e).slice(0, 240) });
    } finally { setBusy(""); }
  };
  const row = (s: ActionSend, door: boolean) => (
    <React.Fragment key={s.id}>
    <TableRow data-testid="send-row">
      <TableCell className="aug-actions-id">{s.action_name}<span className="aug-actions-kind">{s.effect.kind}{s.effect.lane === "writeback" ? " · writeback" : ""}</span></TableCell>
      <TableCell className="aug-ledger-claim">
        <span className="aug-ledger-text">{SEND_WORDS[s.status]}{s.attempts ? ` · ${countNoun(s.attempts, "attempt")}` : ""}</span>
        {/* a call a person left undelivered says who and why — their reason, beside what the call itself met */}
        {s.status === "dismissed" && (s.resolved_by || s.note) && (
          <span className="aug-ledger-query" data-testid="send-left-by">
            {[s.resolved_by && `by ${s.resolved_by}`, s.note].filter(Boolean).join(" — ")}
          </span>
        )}
        {/* a call that landed says what settled it — its check found it, nothing sent again — not the error before;
            the line wraps: unwrapped, a long reason pushed the "when" column off the table (live, 2026-10-10) */}
        {(s.status === "delivered" ? s.reconciled : s.last_error || s.reconciled) && (
          <span className="aug-ledger-query" data-testid="send-said" style={{ whiteSpace: "normal", overflowWrap: "anywhere" }}>
            {s.status === "delivered" ? s.reconciled : s.last_error || s.reconciled}
          </span>
        )}
      </TableCell>
      <TableCell className="num aug-ledger-when" title={formatTimestamp(s.updated_at)}>{relTime(s.updated_at)}</TableCell>
      <TableCell className="aug-org-door">
        {door && (
          <span style={{ display: "flex", gap: 4 }}>
            <Button size="xs" variant="outline" disabled={!!busy} data-testid="send-retry" onClick={() => void act(s, "retry")}>
              Retry
            </Button>
            <Button size="xs" variant="ghost" disabled={!!busy} data-testid="send-dismiss"
              onClick={() => setLeaving({ id: s.id, why: "" })}>
              Dismiss
            </Button>
          </span>
        )}
      </TableCell>
    </TableRow>
    {leaving?.id === s.id && (
      <TableRow data-testid="send-dismiss-form">
        <TableCell colSpan={4}>
          <span style={{ display: "flex", gap: 6, alignItems: "center" }}>
            <Input value={leaving.why} aria-label="Why it is left undelivered" placeholder="Why is it left undelivered?"
              onChange={(e) => setLeaving({ id: s.id, why: e.target.value })} />
            <Button size="xs" variant="outline" disabled={!!busy || !leaving.why.trim()} data-testid="send-dismiss-confirm"
              onClick={() => void act(s, "dismiss", leaving.why.trim())}>
              Leave it undelivered
            </Button>
            <Button size="xs" variant="ghost" onClick={() => setLeaving(null)}>Cancel</Button>
          </span>
        </TableCell>
      </TableRow>
    )}
    </React.Fragment>
  );
  return (
    <Section title="Sends" meta={waiting.length ? `${countNoun(waiting.length, "call")} wait${waiting.length === 1 ? "s" : ""} for you`
      : "a declared action's calls to other systems, delivered through the outbox"}>
      <Err e={error} />
      {state.sends.length === 0 ? <p className="aug-brief-note">No call has been sent yet.</p> : (
        <div className="aug-moves-wrap">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="aug-actions-col-id">action</TableHead>
                <TableHead>what became of it</TableHead>
                <TableHead className="num aug-memory-col-when">when</TableHead>
                <TableHead className="aug-memory-col-door"><span className="sr-only">Retry or dismiss</span></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {waiting.map(s => row(s, true))}
              {rest.map(s => row(s, false))}
            </TableBody>
          </Table>
        </div>
      )}
    </Section>
  );
}

export function DeclaredActionsPanel({ connectionId }: { connectionId: string }) {
  const [actions, setActions] = useState<Record<string, any>>({});
  const [actionsErr, setActionsErr] = useState<string | null>(null);
  const [edits, setEdits] = useState<any[]>([]);
  const [editsErr, setEditsErr] = useState<string | null>(null);
  const [busyEdit, setBusyEdit] = useState<string | null>(null);
  const [pending, setPending] = useState<StagedProposal[] | null>(null);
  const [designing, setDesigning] = useState(false);

  const loadActions = useCallback(() => {
    apiFetch(`/ontology/kinetic-actions?connection_id=${encodeURIComponent(connectionId)}`)
      .then(r => { setActions(r || {}); setActionsErr(null); }).catch(e => setActionsErr(String(e.message || e)));
  }, [connectionId]);
  const loadEdits = useCallback(() => {
    apiFetch(`/kinetic-actions/annotations?connection_id=${encodeURIComponent(connectionId)}`)
      .then(r => { setEdits(r?.edits || []); setEditsErr(null); }).catch(e => setEditsErr(String(e.message || e)));
  }, [connectionId]);
  const loadPending = useCallback(() => {
    getProposals(connectionId, "pending").then(r => setPending(r ?? [])).catch(() => setPending([]));
  }, [connectionId]);

  useEffect(() => {
    if (!connectionId) return;
    loadActions(); loadEdits(); loadPending();
  }, [connectionId, loadActions, loadEdits, loadPending]);

  // ON-4 — one edit, unsaid. The connection-wide purge was the only way back before this.
  const withdraw = async (id: string) => {
    setEditsErr(null); setBusyEdit(id);
    try {
      await del(`/kinetic-actions/annotations/${encodeURIComponent(id)}?connection_id=${encodeURIComponent(connectionId)}`);
      loadEdits();
    } catch (e: any) { setEditsErr(String(e.message || e)); }
    finally { setBusyEdit(null); }
  };

  if (!connectionId) {
    return <div className="aug-ledger-pad"><p className="aug-brief-note">Select a connection to see what Aughor may do on it.</p></div>;
  }

  const actionList = Object.values(actions) as any[];
  const meta = [
    countNoun(actionList.length, "declared action"),
    pending ? `${formatCount(pending.length)} awaiting approval` : "",
    countNoun(edits.length, "overlay edit"),
  ].filter(Boolean).join(" · ");

  return (
    <div className="aug-profile">
      <div className="aug-profile-main">
        <div className="aug-brief-strip">
          <span className="aug-brief-eyebrow">Actions</span>
          <span className="aug-brief-meta">{meta}</span>
        </div>

        <Section title="Declared actions" meta="what Aughor is permitted to do on this connection, and what it must ask first">
          <Err e={actionsErr} />
          {actionList.length === 0 ? (
            <p className="aug-brief-note">No declared actions yet — declare one below.</p>
          ) : (
            <div className="aug-moves-wrap">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="aug-actions-col-id">action</TableHead>
                    <TableHead>what it does</TableHead>
                    <TableHead className="aug-actions-col-about">about</TableHead>
                    <TableHead className="aug-actions-col-gate">gate</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {actionList.map(a => {
                    const gate = GATE[a.risk];
                    return (
                      <TableRow key={a.id}>
                        <TableCell className="aug-actions-id">{a.id}<span className="aug-actions-kind">{a.kind}</span></TableCell>
                        <TableCell className="aug-ledger-claim">
                          <span className="aug-ledger-text">{a.description || "—"}</span>
                          {effectLines(a).map((line, i) => <span key={i} className="aug-ledger-query">{line}</span>)}
                        </TableCell>
                        <TableCell className="aug-actions-about">{a.object_type || "—"}</TableCell>
                        <TableCell>
                          <span className={`aug-actions-gate${gate?.ask ? " aug-actions-gate-ask" : ""}`} title={gate?.title}>
                            {gate ? gate.label : String(a.risk || "—")}
                          </span>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          )}
          {designing ? (
            <div style={{ display: "flex", border: "1px solid var(--b1)", borderRadius: "var(--r3)", marginTop: 8 }}>
              <ActionDesigner connectionId={connectionId} within=""
                onClose={() => { setDesigning(false); loadActions(); }} onDeclared={() => loadActions()} />
            </div>
          ) : (
            <Button variant="outline" size="sm" style={{ marginTop: 8 }} data-testid="actions-new" onClick={() => setDesigning(true)}>
              <Icon name="plus" size={12} /> New action
            </Button>
          )}
        </Section>

        <SendsSection connectionId={connectionId} />

        <Section title="Overlay edits" meta="a person's edit over the data — merged when it is read, never written to the source">
          <Err e={editsErr} />
          {edits.length === 0 ? (
            <p className="aug-brief-note">No overlay edits yet — annotate or correct a value below.</p>
          ) : (
            <div className="aug-moves-wrap">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="aug-actions-col-target">target</TableHead>
                    <TableHead>edit</TableHead>
                    <TableHead className="num aug-memory-col-when">when</TableHead>
                    <TableHead className="aug-memory-col-door"><span className="sr-only">Withdraw</span></TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {edits.map((e, i) => (
                    <TableRow key={e.id || i}>
                      <TableCell className="aug-actions-target">
                        {e.table}{e.column ? `.${e.column}` : ""}{e.row_key ? `#${e.key_column}=${e.row_key}` : ""}
                      </TableCell>
                      <TableCell className="aug-ledger-claim">
                        <span className="aug-ledger-text">{e.body}</span>
                        <span className="aug-ledger-query">{[e.kind, e.actor || e.source, e.origin, e.note].filter(Boolean).join(" · ")}</span>
                      </TableCell>
                      <TableCell className="num aug-ledger-when" title={e.created_at ? formatTimestamp(e.created_at) : undefined}>
                        {e.created_at ? relTime(e.created_at) : "—"}
                      </TableCell>
                      <TableCell className="aug-org-door">
                        <Button size="xs" variant="ghost" disabled={busyEdit === e.id} onClick={() => withdraw(e.id)}
                          title="Withdraw this edit — the next read stops merging it and the source value, never written, is what shows">
                          {busyEdit === e.id ? "Withdrawing…" : "Withdraw"}
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
          <AnnotateForm connectionId={connectionId} onSaved={loadEdits} />
        </Section>

        <Section title="Propose from a finding" meta="the agent stages; a person approves">
          <ProposeSection connectionId={connectionId} onStaged={loadPending} />
        </Section>
      </div>

      <aside className="aug-profile-rail" aria-label="Approvals and the permission model">
        <div className="aug-profile-rail-head">
          <span className="aug-brief-eyebrow">Awaiting approval</span>
          <span className="aug-brief-meta">{pending ? formatCount(pending.length) : ""}</span>
        </div>
        <div className="aug-profile-block">
          {pending === null ? (
            <SkeletonRows rows={2} />
          ) : pending.length === 0 ? (
            <p className="aug-brief-note">
              Nothing is waiting. A proposal lands here when the agent or an automation stages one; approving it runs it once.
            </p>
          ) : (
            <div className="aug-approvals">
              {/* SP-9 — the ONE approval card; what either click creates, never raw params. */}
              {pending.map(p => (
                <ProposalCard key={p.id} proposal={p} actor={actorName()}
                  onResolved={(t, m) => {
                    if (t === "ok") { toast.info(m); loadEdits(); }
                    loadPending();
                  }} />
              ))}
            </div>
          )}
        </div>

        <div className="aug-profile-rail-head">
          <span className="aug-brief-eyebrow">Permission model</span>
        </div>
        <div className="aug-profile-block">
          <dl className="aug-actions-perm">
            <div><dt>read_only</dt><dd>Never gated. Every run is audited.</dd></div>
            <div><dt>low</dt><dd>Reversible or additive: runs without asking, and every run is audited.</dd></div>
            <div>
              <dt className="aug-actions-gate-ask">high</dt>
              <dd>A person approves each run. Approving a staged proposal is that approval, once; a standing grant can pre-approve one target.</dd>
            </div>
          </dl>
        </div>
      </aside>
    </div>
  );
}
