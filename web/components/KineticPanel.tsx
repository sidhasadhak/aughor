"use client";

/**
 * KineticPanel — what Aughor may do on a connection (Aughor Intelligence · 07 Actions).
 *
 * Numbered sections beside a rail. §01 the declared actions — what each does, what it is about, and
 * its gate — with the form that declares one; §02 the overlay edits a person wrote over the data,
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

import { Button } from "@/components/ui/button";
import { SkeletonRows } from "@/components/ui/motion";
import { toast } from "@/components/ui/toast";
import { acceptProposal, getProposals, rejectProposal, type StagedProposal } from "@/lib/api";
import { claimsOf, getIdToken } from "@/lib/auth";
import { getApiBase } from "@/lib/config";
import { countNoun, formatCount, formatTimestamp, relTime } from "@/lib/format";

async function apiFetch(path: string, opts?: RequestInit) {
  const res = await fetch(`${getApiBase()}${path}`, { headers: { "Content-Type": "application/json" }, ...opts });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(text || `HTTP ${res.status}`);
  }
  return res.json();
}
const put = (p: string, b: unknown) => apiFetch(p, { method: "PUT", body: JSON.stringify(b) });
const post = (p: string, b: unknown) => apiFetch(p, { method: "POST", body: JSON.stringify(b) });
const del = (p: string) => apiFetch(p, { method: "DELETE" });

/** Who is acting — the signed-in email, else the word the actions inbox uses. Provenance, not auth. */
const actorName = () => claimsOf(getIdToken())?.email || "human";

const input: React.CSSProperties = { width: "100%", padding: "6px 8px", fontSize: 12, border: "1px solid var(--b0)", borderRadius: 6, background: "var(--bg-2)", color: "var(--t1)", marginBottom: 6, boxSizing: "border-box" };
const hint: React.CSSProperties = { fontSize: 12, color: "var(--t3)", padding: "8px 0" };

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
  return out;
}

function Section({ mark, title, meta, children }: { mark: string; title: string; meta?: string; children: React.ReactNode }) {
  return (
    <section className="aug-brief-sec">
      <div className="aug-brief-gutter" aria-hidden>{mark}</div>
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

// ── §01 · declaring an action ────────────────────────────────────────────────────

function DeclareActionForm({ connectionId, onSaved }: { connectionId: string; onSaved: () => void }) {
  const [err, setErr] = useState<string | null>(null);
  const [id, setId] = useState("");
  const [kind, setKind] = useState("side_effect");
  const [description, setDescription] = useState("");
  const [risk, setRisk] = useState("high");
  // PX-2 — params and criteria are typed ROWS, not JSON textareas. The crown-jewel
  // governance plane had the least-designed authoring surface on the platform: two
  // unlabeled JSON blobs. Both are lists of flat shapes, so rows are lossless.
  // ON-4 — an action can be ABOUT an object type, take one of its objects as a parameter, and write a
  // property onto it. All three were API-only until now: the panel listed them and could not declare one,
  // so the only way to author `flag_order_for_review` was to PUT the override by hand.
  const [objectType, setObjectType] = useState("");
  const [params, setParams] = useState<
    { name: string; kind: "value" | "object"; data_type: string; object_type: string; required: boolean }[]>(
    [{ name: "amount_eur", kind: "value", data_type: "NUMERIC", object_type: "", required: true }]);
  const [edits, setEdits] = useState<{ object: string; property: string; value: string; note: string }[]>([]);
  const [criteria, setCriteria] = useState<{ expr: string; message: string }[]>(
    [{ expr: "amount_eur <= 10000", message: "Refunds over EUR 10,000 need finance sign-off." }]);
  // DS-13 — the declarative custom component: named fields rather than a JSON blob, so the call is
  // described without writing anything executable.
  const [httpUrl, setHttpUrl] = useState("");
  const [httpMethod, setHttpMethod] = useState("POST");
  const [httpAuthHeader, setHttpAuthHeader] = useState("");
  const [httpSecret, setHttpSecret] = useState("");
  const [httpHeaders, setHttpHeaders] = useState('{"Content-Type": "application/json"}');
  const [httpBody, setHttpBody] = useState('{"summary": "{amount_eur}"}');

  const save = async () => {
    setErr(null);
    try {
      const body: any = { kind, description, risk };
      if (objectType.trim()) body.object_type = objectType.trim();
      const cleanParams = params.filter(p => p.name.trim());
      if (cleanParams.length) body.params = cleanParams.map(p => p.kind === "object"
        ? { name: p.name.trim(), kind: "object", object_type: p.object_type.trim(), required: p.required }
        : { name: p.name.trim(), data_type: p.data_type, required: p.required });
      // An edit names one of the object params above and the property it writes; `{param}` placeholders in
      // the value or the note are filled from the proposal, the way a side effect's body is.
      const cleanEdits = edits.filter(e => e.object.trim() && e.property.trim());
      if (cleanEdits.length) body.edits = cleanEdits.map(e => ({
        object: e.object.trim(), property: e.property.trim(), value: e.value.trim(), note: e.note.trim() }));
      const cleanCriteria = criteria.filter(c => c.expr.trim());
      if (cleanCriteria.length) body.submission_criteria = cleanCriteria.map(c => ({
        expr: c.expr.trim(), message: c.message.trim() }));
      if (kind === "side_effect" && httpUrl.trim()) {
        const config: any = { url: httpUrl.trim(), method: httpMethod };
        if (httpHeaders.trim()) config.headers = JSON.parse(httpHeaders);
        if (httpBody.trim()) config.body = JSON.parse(httpBody);
        if (httpAuthHeader.trim()) {
          config.auth_header = httpAuthHeader.trim();
          // Sent ONLY when the person typed one. Left empty, the server carries the
          // stored credential forward — a form that posts back the mask it was showing
          // would otherwise overwrite the key with bullets.
          if (httpSecret.trim()) config.auth_secret = httpSecret.trim();
        }
        body.side_effects = [{ kind: "http", config }];
      }
      await put(`/ontology/kinetic-actions/${encodeURIComponent(id)}?connection_id=${encodeURIComponent(connectionId)}`, body);
      setId(""); setHttpSecret(""); onSaved();
    } catch (e: any) { setErr(String(e.message || e)); }
  };

  return (
    <div className="aug-actions-form">
      <div className="aug-actions-form-title">Declare an action</div>
      <Err e={err} />
      <input style={input} placeholder="action id (e.g. refund_order)" value={id} onChange={e => setId(e.target.value)} />
      <div style={{ display: "flex", gap: 6 }}>
        <select style={{ ...input, flex: 1 }} value={kind} onChange={e => setKind(e.target.value)}>
          <option value="side_effect">side_effect</option>
          <option value="annotate">annotate</option>
          <option value="query">query</option>
        </select>
        <select style={{ ...input, flex: 1 }} value={risk} onChange={e => setRisk(e.target.value)}>
          <option value="high">high</option>
          <option value="low">low</option>
          <option value="read_only">read_only</option>
        </select>
      </div>
      <input style={input} placeholder="description" value={description} onChange={e => setDescription(e.target.value)} />
      <input style={input} placeholder="object type this action is about (e.g. order) — optional"
        value={objectType} onChange={e => setObjectType(e.target.value)} />
      <label style={hint}>the parameters a proposal must fill — an object parameter names ONE object, read live</label>
      {params.map((p, i) => (
        <div key={i} style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <input style={{ ...input, flex: 2 }} placeholder="name (e.g. amount_eur)"
            value={p.name} onChange={e => setParams(ps => ps.map((x, j) => j === i ? { ...x, name: e.target.value } : x))} />
          <select style={{ ...input, width: 90 }} value={p.kind}
            onChange={e => setParams(ps => ps.map((x, j) => j === i ? { ...x, kind: e.target.value as "value" | "object" } : x))}>
            <option value="value">value</option>
            <option value="object">object</option>
          </select>
          {p.kind === "object" ? (
            <input style={{ ...input, flex: 1 }} placeholder="object type (e.g. order)" value={p.object_type}
              onChange={e => setParams(ps => ps.map((x, j) => j === i ? { ...x, object_type: e.target.value } : x))} />
          ) : (
            <select style={{ ...input, flex: 1 }} value={p.data_type}
              onChange={e => setParams(ps => ps.map((x, j) => j === i ? { ...x, data_type: e.target.value } : x))}>
              {["TEXT", "NUMERIC", "INTEGER", "BOOLEAN", "DATE"].map(t => <option key={t} value={t}>{t}</option>)}
            </select>
          )}
          <label className="aug-fs-xs" style={{ color: "var(--t3)", display: "flex", alignItems: "center", gap: 4, marginBottom: 6, whiteSpace: "nowrap" }}>
            <input type="checkbox" checked={p.required}
              onChange={e => setParams(ps => ps.map((x, j) => j === i ? { ...x, required: e.target.checked } : x))} />
            required
          </label>
          <Button size="xs" variant="ghost" className="mb-1.5"
            onClick={() => setParams(ps => ps.filter((_, j) => j !== i))}>✕</Button>
        </div>
      ))}
      <Button size="xs" variant="ghost" className="mb-2"
        onClick={() => setParams(ps => [...ps, { name: "", kind: "value", data_type: "TEXT", object_type: "", required: true }])}>
        + Add a parameter
      </Button>
      <label style={hint}>what a proposal must satisfy — the message is shown verbatim when it fails</label>
      {criteria.map((c, i) => (
        <div key={i} style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <input style={{ ...input, flex: 2, fontFamily: "var(--font-mono)" }} placeholder="amount_eur <= 10000"
            value={c.expr} onChange={e => setCriteria(cs => cs.map((x, j) => j === i ? { ...x, expr: e.target.value } : x))} />
          <input style={{ ...input, flex: 3 }} placeholder="why — shown to the proposer on failure"
            value={c.message} onChange={e => setCriteria(cs => cs.map((x, j) => j === i ? { ...x, message: e.target.value } : x))} />
          <Button size="xs" variant="ghost" className="mb-1.5"
            onClick={() => setCriteria(cs => cs.filter((_, j) => j !== i))}>✕</Button>
        </div>
      ))}
      <Button size="xs" variant="ghost" className="mb-2"
        onClick={() => setCriteria(cs => [...cs, { expr: "", message: "" }])}>
        + Add a criterion
      </Button>
      <label style={hint}>
        what an accepted proposal writes onto the object — an overlay merged at read time, never the source
      </label>
      {edits.map((e, i) => (
        <div key={i} style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <input style={{ ...input, flex: 1 }} placeholder="object param (e.g. order)" value={e.object}
            onChange={ev => setEdits(es => es.map((x, j) => j === i ? { ...x, object: ev.target.value } : x))} />
          <input style={{ ...input, flex: 1 }} placeholder="property (e.g. review_flag)" value={e.property}
            onChange={ev => setEdits(es => es.map((x, j) => j === i ? { ...x, property: ev.target.value } : x))} />
          <input style={{ ...input, flex: 1 }} placeholder="value (e.g. true)" value={e.value}
            onChange={ev => setEdits(es => es.map((x, j) => j === i ? { ...x, value: ev.target.value } : x))} />
          <input style={{ ...input, flex: 2 }} placeholder="note — {param} is filled from the proposal" value={e.note}
            onChange={ev => setEdits(es => es.map((x, j) => j === i ? { ...x, note: ev.target.value } : x))} />
          <Button size="xs" variant="ghost" className="mb-1.5"
            onClick={() => setEdits(es => es.filter((_, j) => j !== i))}>✕</Button>
        </div>
      ))}
      <Button size="xs" variant="ghost" className="mb-2"
        onClick={() => setEdits(es => [...es, { object: "", property: "", value: "true", note: "" }])}>
        + Add an edit
      </Button>
      {kind === "side_effect" && (
        <>
          <label style={hint}>the call this action makes — described, never coded</label>
          <div style={{ display: "flex", gap: 6 }}>
            <select style={{ ...input, width: 110 }} value={httpMethod} onChange={e => setHttpMethod(e.target.value)}>
              {["POST", "GET", "PUT", "PATCH", "DELETE"].map(m => <option key={m} value={m}>{m}</option>)}
            </select>
            <input style={{ ...input, flex: 1 }} placeholder="https://events.pagerduty.com/v2/enqueue"
              value={httpUrl} onChange={e => setHttpUrl(e.target.value)} />
          </div>
          <div style={{ display: "flex", gap: 6 }}>
            <input style={{ ...input, flex: 1 }} placeholder="auth header (e.g. Authorization)"
              value={httpAuthHeader} onChange={e => setHttpAuthHeader(e.target.value)} />
            <input style={{ ...input, flex: 1 }} type="password" placeholder="credential — stored encrypted"
              value={httpSecret} onChange={e => setHttpSecret(e.target.value)} />
          </div>
          <label style={hint}>headers (JSON)</label>
          <textarea style={{ ...input, minHeight: 36, fontFamily: "monospace" }} value={httpHeaders} onChange={e => setHttpHeaders(e.target.value)} />
          <label style={hint}>body (JSON) — {"{param}"} placeholders are filled from the declared params</label>
          <textarea style={{ ...input, minHeight: 44, fontFamily: "monospace" }} value={httpBody} onChange={e => setHttpBody(e.target.value)} />
        </>
      )}
      <Button variant="default" size="sm" disabled={!id.trim()} onClick={save}>Save action</Button>
    </div>
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
      <input style={input} placeholder="table" value={f.table} onChange={e => setF({ ...f, table: e.target.value })} />
      <div style={{ display: "flex", gap: 6 }}>
        <input style={{ ...input, flex: 1 }} placeholder="column (optional)" value={f.column} onChange={e => setF({ ...f, column: e.target.value })} />
        <input style={{ ...input, flex: 1 }} placeholder="key column (optional)" value={f.key_column} onChange={e => setF({ ...f, key_column: e.target.value })} />
        <input style={{ ...input, flex: 1 }} placeholder="row key (optional)" value={f.row_key} onChange={e => setF({ ...f, row_key: e.target.value })} />
      </div>
      <input style={input} placeholder="annotation / correction text" value={f.body} onChange={e => setF({ ...f, body: e.target.value })} />
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
      <textarea style={{ ...input, minHeight: 72, marginTop: 8 }} placeholder="e.g. Order X9001 was charged EUR 480 twice — a clear duplicate charge." value={context} onChange={e => setContext(e.target.value)} />
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
              <span className="aug-approval-params">{JSON.stringify(p.params)}</span>
              {!p.ok && p.message && <p className="aug-actions-err">{p.message}</p>}
            </div>
          ))}
        </div>
      )}
    </>
  );
}

// ── The layer ────────────────────────────────────────────────────────────────────

export function KineticPanel({ connectionId }: { connectionId: string }) {
  const [actions, setActions] = useState<Record<string, any>>({});
  const [actionsErr, setActionsErr] = useState<string | null>(null);
  const [edits, setEdits] = useState<any[]>([]);
  const [editsErr, setEditsErr] = useState<string | null>(null);
  const [busyEdit, setBusyEdit] = useState<string | null>(null);
  const [pending, setPending] = useState<StagedProposal[] | null>(null);
  const [busyProposal, setBusyProposal] = useState<string | null>(null);
  const [proposalErr, setProposalErr] = useState<Record<string, string>>({});

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

  const resolve = async (p: StagedProposal, how: "approve" | "reject") => {
    setBusyProposal(p.id); setProposalErr(x => ({ ...x, [p.id]: "" }));
    try {
      if (how === "approve") {
        const r = await acceptProposal(p.id, actorName());
        toast.info(`Ran ${r.action_id}`, { description: "Approved and run once — the approval is recorded." });
        loadEdits();
      } else {
        await rejectProposal(p.id, actorName());
      }
      loadPending();
    } catch (e) {
      setProposalErr(x => ({ ...x, [p.id]: e instanceof Error ? e.message : String(e) }));
      loadPending();
    } finally { setBusyProposal(null); }
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

        <Section mark="01" title="Declared actions" meta="what Aughor is permitted to do on this connection, and what it must ask first">
          <Err e={actionsErr} />
          {actionList.length === 0 ? (
            <p className="aug-brief-note">No declared actions yet — declare one below.</p>
          ) : (
            <div className="aug-moves-wrap">
              <table className="aug-dt aug-ledger-table">
                <thead>
                  <tr>
                    <th className="aug-actions-col-id">action</th>
                    <th>what it does</th>
                    <th className="aug-actions-col-about">about</th>
                    <th className="aug-actions-col-gate">gate</th>
                  </tr>
                </thead>
                <tbody>
                  {actionList.map(a => {
                    const gate = GATE[a.risk];
                    return (
                      <tr key={a.id}>
                        <td className="aug-actions-id">{a.id}<span className="aug-actions-kind">{a.kind}</span></td>
                        <td className="aug-ledger-claim">
                          <span className="aug-ledger-text">{a.description || "—"}</span>
                          {effectLines(a).map((line, i) => <span key={i} className="aug-ledger-query">{line}</span>)}
                        </td>
                        <td className="aug-actions-about">{a.object_type || "—"}</td>
                        <td>
                          <span className={`aug-actions-gate${gate?.ask ? " aug-actions-gate-ask" : ""}`} title={gate?.title}>
                            {gate ? gate.label : String(a.risk || "—")}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          <DeclareActionForm connectionId={connectionId} onSaved={loadActions} />
        </Section>

        <Section mark="02" title="Overlay edits" meta="a person's edit over the data — merged when it is read, never written to the source">
          <Err e={editsErr} />
          {edits.length === 0 ? (
            <p className="aug-brief-note">No overlay edits yet — annotate or correct a value below.</p>
          ) : (
            <div className="aug-moves-wrap">
              <table className="aug-dt aug-ledger-table">
                <thead>
                  <tr>
                    <th className="aug-actions-col-target">target</th>
                    <th>edit</th>
                    <th className="num aug-memory-col-when">when</th>
                    <th className="aug-memory-col-door"><span className="sr-only">Withdraw</span></th>
                  </tr>
                </thead>
                <tbody>
                  {edits.map((e, i) => (
                    <tr key={e.id || i}>
                      <td className="aug-actions-target">
                        {e.table}{e.column ? `.${e.column}` : ""}{e.row_key ? `#${e.key_column}=${e.row_key}` : ""}
                      </td>
                      <td className="aug-ledger-claim">
                        <span className="aug-ledger-text">{e.body}</span>
                        <span className="aug-ledger-query">{[e.kind, e.actor || e.source, e.origin, e.note].filter(Boolean).join(" · ")}</span>
                      </td>
                      <td className="num aug-ledger-when" title={e.created_at ? formatTimestamp(e.created_at) : undefined}>
                        {e.created_at ? relTime(e.created_at) : "—"}
                      </td>
                      <td className="aug-org-door">
                        <Button size="xs" variant="ghost" disabled={busyEdit === e.id} onClick={() => withdraw(e.id)}
                          title="Withdraw this edit — the next read stops merging it and the source value, never written, is what shows">
                          {busyEdit === e.id ? "Withdrawing…" : "Withdraw"}
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <AnnotateForm connectionId={connectionId} onSaved={loadEdits} />
        </Section>

        <Section mark="03" title="Propose from a finding" meta="the agent stages; a person approves">
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
              {pending.map(p => (
                <div key={p.id} className="aug-approval">
                  <div className="aug-approval-head">
                    <span className="aug-approval-kind">{p.action_id}</span>
                    <span className="aug-brief-meta" title={formatTimestamp(p.created_at)}>waiting {relTime(p.created_at)}</span>
                  </div>
                  {p.reasoning && <span className="aug-approval-why">{p.reasoning}</span>}
                  <span className="aug-approval-params">
                    {p.kind === "integration" && p.grant_id ? `as ${p.grant_id} · ` : ""}{JSON.stringify(p.params)}
                  </span>
                  <div className="aug-inspector-doors">
                    <Button size="xs" disabled={busyProposal === p.id} onClick={() => resolve(p, "approve")}
                      title="Approve and run it once — the approval is recorded">
                      Approve and run
                    </Button>
                    <Button size="xs" variant="ghost" disabled={busyProposal === p.id} onClick={() => resolve(p, "reject")}>
                      Reject
                    </Button>
                  </div>
                  {proposalErr[p.id] && <p className="aug-actions-err">{proposalErr[p.id]}</p>}
                </div>
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
