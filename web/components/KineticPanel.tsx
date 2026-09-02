"use client";

/**
 * KineticPanel — Wave K5 — the human surface for the kinetic plane:
 *   1. Actions      — the declared KineticActions on this connection; author/edit one.
 *   2. Propose      — ground a context, see the agent's staged proposals, execute one (governed).
 *   3. Annotations  — the human overlay edits (annotations/corrections) merged onto reads.
 *
 * Mirrors SemanticLayerPanel's self-contained fetch pattern (no api.gen dependency), so it stays a
 * plain "use client" React component. The write endpoints are flag-gated on the backend; when a flag
 * is off the surface shows an inline hint rather than failing loudly.
 */

import React, { useCallback, useEffect, useState } from "react";
import { getApiBase } from "@/lib/config";
import { Button } from "@/components/ui/button";

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

type Tab = "Actions" | "Propose" | "Annotations";

function TabBar({ active, onChange }: { active: Tab; onChange: (t: Tab) => void }) {
  const tabs: Tab[] = ["Actions", "Propose", "Annotations"];
  return (
    <div style={{ display: "flex", gap: 4, borderBottom: "1px solid var(--b0)", marginBottom: 16, paddingBottom: 6 }}>
      {tabs.map(t => (
        <Button key={t} size="sm" variant={active === t ? "secondary" : "ghost"} onClick={() => onChange(t)}>{t}</Button>
      ))}
    </div>
  );
}

const card: React.CSSProperties = { border: "1px solid var(--b0)", borderRadius: 8, padding: 12, marginBottom: 10 };
const input: React.CSSProperties = { width: "100%", padding: "6px 8px", fontSize: 12, border: "1px solid var(--b0)", borderRadius: 6, background: "var(--bg-2)", color: "var(--t1)", marginBottom: 6, boxSizing: "border-box" };
const hint: React.CSSProperties = { fontSize: 12, color: "var(--t3)", padding: "8px 0" };

function Err({ e }: { e: string | null }) {
  return e ? <div style={{ ...hint, color: "var(--destructive)" }}>{e}</div> : null;
}

// ── 1. Declared actions ─────────────────────────────────────────────────────────

function ActionsTab({ connectionId }: { connectionId: string }) {
  const [actions, setActions] = useState<Record<string, any>>({});
  const [err, setErr] = useState<string | null>(null);
  const [id, setId] = useState("");
  const [kind, setKind] = useState("side_effect");
  const [description, setDescription] = useState("");
  const [risk, setRisk] = useState("high");
  const [params, setParams] = useState('[{"name": "amount_eur", "data_type": "NUMERIC", "required": true}]');
  const [criteria, setCriteria] = useState('[{"expr": "amount_eur <= 10000", "message": "Refunds over EUR 10,000 need finance sign-off."}]');
  // DS-13 — the declarative custom component. Named fields rather than a JSON blob, which
  // is the whole claim: the competitor's "new component" opens a Python editor and this
  // opens a form. `params` and `criteria` above stay JSON because they are lists of a
  // shape this panel has always taken that way; the call itself is the thing DS-13
  // promises you can describe without writing anything executable.
  const [httpUrl, setHttpUrl] = useState("");
  const [httpMethod, setHttpMethod] = useState("POST");
  const [httpAuthHeader, setHttpAuthHeader] = useState("");
  const [httpSecret, setHttpSecret] = useState("");
  const [httpHeaders, setHttpHeaders] = useState('{"Content-Type": "application/json"}');
  const [httpBody, setHttpBody] = useState('{"summary": "{amount_eur}"}');

  const load = useCallback(() => {
    apiFetch(`/ontology/kinetic-actions?connection_id=${encodeURIComponent(connectionId)}`)
      .then(setActions).catch(e => setErr(String(e.message || e)));
  }, [connectionId]);
  useEffect(() => { load(); }, [load]);

  const save = async () => {
    setErr(null);
    try {
      const body: any = { kind, description, risk };
      if (params.trim()) body.params = JSON.parse(params);
      if (criteria.trim()) body.submission_criteria = JSON.parse(criteria);
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
      setId(""); setHttpSecret(""); load();
    } catch (e: any) { setErr(String(e.message || e)); }
  };

  return (
    <div>
      <Err e={err} />
      {Object.keys(actions).length === 0
        ? <div style={hint}>No declared actions yet — author one below.</div>
        : Object.values(actions).map((a: any) => (
          <div key={a.id} style={card}>
            <div style={{ fontWeight: 600, fontSize: 13 }}>{a.id} <span style={{ color: "var(--t3)", fontWeight: 400 }}>· {a.kind} · {a.risk}</span></div>
            {a.description && <div style={{ fontSize: 12, color: "var(--t3)", margin: "4px 0" }}>{a.description}</div>}
            <div style={{ fontSize: 11, color: "var(--t3)" }}>
              params: {(a.params || []).map((p: any) => `${p.name}:${p.data_type}`).join(", ") || "—"}
            </div>
            {(a.submission_criteria || []).map((c: any, i: number) => (
              <div key={i} style={{ fontSize: 11, color: "var(--t3)" }}>must satisfy: <code>{c.expr}</code></div>
            ))}
            {/* DS-13 — what the action DOES. The credential arrives masked from the
                server (`mask_action_secrets`); this renders whatever it was given and
                never asks for the raw value. */}
            {(a.side_effects || []).map((se: any, i: number) => (
              <div key={`se${i}`} className="aug-fs-xs" style={{ color: "var(--t3)" }}>
                {se.kind === "http"
                  ? <>calls <code>{String(se.config?.method || "POST")} {String(se.config?.url || "")}</code>
                    {se.config?.auth_secret ? <> · key <code>{String(se.config.auth_secret)}</code></> : null}</>
                  : <>side effect: <code>{se.kind}</code></>}
              </div>
            ))}
          </div>
        ))}

      <div style={{ ...card, marginTop: 16 }}>
        <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 8 }}>Author an action</div>
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
        <label style={hint}>params (JSON)</label>
        <textarea style={{ ...input, minHeight: 44, fontFamily: "monospace" }} value={params} onChange={e => setParams(e.target.value)} />
        <label style={hint}>submission criteria (JSON) — each message is shown verbatim on failure</label>
        <textarea style={{ ...input, minHeight: 44, fontFamily: "monospace" }} value={criteria} onChange={e => setCriteria(e.target.value)} />
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
    </div>
  );
}

// ── 2. Propose ──────────────────────────────────────────────────────────────────

function ProposeTab({ connectionId }: { connectionId: string }) {
  const [context, setContext] = useState("");
  const [proposals, setProposals] = useState<any[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const propose = async () => {
    setBusy(true); setErr(null); setProposals(null);
    try {
      const r = await post(`/kinetic-actions/propose?connection_id=${encodeURIComponent(connectionId)}`, { context });
      setProposals(r.proposals || []);
    } catch (e: any) { setErr(String(e.message || e)); }
    finally { setBusy(false); }
  };

  const execute = async (p: any) => {
    setErr(null);
    try {
      await post(`/kinetic-actions/${encodeURIComponent(p.action_id)}/execute?connection_id=${encodeURIComponent(connectionId)}`, { params: p.params, actor: "human" });
      alert(`Executed ${p.action_id}`);
    } catch (e: any) { setErr(String(e.message || e)); }   // a 428 is intercepted by the global ApprovalModal
  };

  return (
    <div>
      <Err e={err} />
      <div style={hint}>Paste a finding; the agent proposes any warranted declared actions (staged — nothing runs until you execute).</div>
      <textarea style={{ ...input, minHeight: 80 }} placeholder="e.g. Order X9001 was charged EUR 480 twice — a clear duplicate charge." value={context} onChange={e => setContext(e.target.value)} />
      <Button variant="default" size="sm" disabled={busy || !context.trim()} onClick={propose}>{busy ? "Proposing…" : "Propose actions"}</Button>

      {proposals && proposals.length === 0 && <div style={hint}>The agent abstained — nothing to propose.</div>}
      {proposals && proposals.map((p, i) => (
        <div key={i} style={{ ...card, marginTop: 10 }}>
          <div style={{ fontWeight: 600, fontSize: 13 }}>{p.action_id} <span style={{ color: p.ok ? "var(--t1)" : "var(--t3)", fontWeight: 400 }}>· {p.status}</span></div>
          {p.reasoning && <div style={{ fontSize: 12, color: "var(--t3)", margin: "4px 0" }}>{p.reasoning}</div>}
          <div style={{ fontSize: 11, fontFamily: "monospace", color: "var(--t3)" }}>{JSON.stringify(p.params)}</div>
          {p.message && <div style={{ fontSize: 12, color: "var(--destructive)", marginTop: 4 }}>{p.message}</div>}
          {p.ok && <div style={{ marginTop: 8 }}><Button variant="secondary" size="sm" onClick={() => execute(p)}>Execute (governed)</Button></div>}
        </div>
      ))}
    </div>
  );
}

// ── 3. Annotations (overlay edits) ────────────────────────────────────────────────

function AnnotationsTab({ connectionId }: { connectionId: string }) {
  const [edits, setEdits] = useState<any[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [f, setF] = useState({ table: "", column: "", key_column: "", row_key: "", body: "", kind: "annotation" });

  const load = useCallback(() => {
    apiFetch(`/kinetic-actions/annotations?connection_id=${encodeURIComponent(connectionId)}`)
      .then(r => setEdits(r.edits || [])).catch(e => setErr(String(e.message || e)));
  }, [connectionId]);
  useEffect(() => { load(); }, [load]);

  const save = async () => {
    setErr(null);
    try {
      await post(`/kinetic-actions/annotate?connection_id=${encodeURIComponent(connectionId)}`, f);
      setF({ ...f, body: "" }); load();
    } catch (e: any) { setErr(String(e.message || e)); }
  };

  return (
    <div>
      <Err e={err} />
      {edits.length === 0
        ? <div style={hint}>No overlay edits yet. Enable <code>kinetic.overlay</code> and annotate a value below.</div>
        : edits.map((e, i) => (
          <div key={i} style={card}>
            <div style={{ fontSize: 12, fontFamily: "monospace" }}>{e.table}{e.column ? `.${e.column}` : ""}{e.row_key ? `#${e.key_column}=${e.row_key}` : ""}</div>
            <div style={{ fontSize: 12, marginTop: 2 }}>{e.body} <span style={{ color: "var(--t3)" }}>· {e.source}</span></div>
          </div>
        ))}

      <div style={{ ...card, marginTop: 16 }}>
        <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 8 }}>Annotate a value</div>
        <input style={input} placeholder="table" value={f.table} onChange={e => setF({ ...f, table: e.target.value })} />
        <div style={{ display: "flex", gap: 6 }}>
          <input style={{ ...input, flex: 1 }} placeholder="column (optional)" value={f.column} onChange={e => setF({ ...f, column: e.target.value })} />
          <input style={{ ...input, flex: 1 }} placeholder="key column (optional)" value={f.key_column} onChange={e => setF({ ...f, key_column: e.target.value })} />
          <input style={{ ...input, flex: 1 }} placeholder="row key (optional)" value={f.row_key} onChange={e => setF({ ...f, row_key: e.target.value })} />
        </div>
        <input style={input} placeholder="annotation / correction text" value={f.body} onChange={e => setF({ ...f, body: e.target.value })} />
        <Button variant="default" size="sm" disabled={!f.table.trim() || !f.body.trim()} onClick={save}>Save annotation</Button>
      </div>
    </div>
  );
}

export function KineticPanel({ connectionId }: { connectionId: string }) {
  const [tab, setTab] = useState<Tab>("Actions");
  if (!connectionId) return <div style={hint}>Select a connection to manage its kinetic plane.</div>;
  return (
    <div style={{ padding: 16, maxWidth: 720 }}>
      <TabBar active={tab} onChange={setTab} />
      {tab === "Actions" && <ActionsTab connectionId={connectionId} />}
      {tab === "Propose" && <ProposeTab connectionId={connectionId} />}
      {tab === "Annotations" && <AnnotationsTab connectionId={connectionId} />}
    </div>
  );
}

export default KineticPanel;
