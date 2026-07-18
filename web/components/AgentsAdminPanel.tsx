"use client";
/* ── Agents — user-defined domain personas (flag `agents.user_defined`) ──
   Builder + roster for /agents/custom: name → instructions → bound connection →
   attached documents → enabled. The picked agent is used from the ask composer
   (ChatPanel) and each answer carries an AgentBadge receipt. Modeled on
   MonitorsPanel (list/form views, inline error, .aug-input, <Button>). */
import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { StatusChip } from "@/components/brief/StatusChip";
import {
  createAgentGolden, createUserAgent, deleteAgentGolden, deleteUserAgent,
  evaluateUserAgent, getConnections, getPacks, listAgentGoldens, listDocuments,
  listUserAgents, patchUserAgent,
  type AgentEvalResult, type AgentGolden, type Connection, type DocumentEntry,
  type PackSummary, type UserAgent,
} from "@/lib/api";

interface FormState {
  name: string;
  instructions: string;
  connection_id: string;
  schema_scope: string;
  doc_ids: string[];
  pack_ids: string[];
}

const EMPTY_FORM: FormState = {
  name: "", instructions: "", connection_id: "", schema_scope: "",
  doc_ids: [], pack_ids: [],
};

export function AgentsAdminPanel() {
  const [agents, setAgents] = useState<UserAgent[]>([]);
  const [connections, setConnections] = useState<Connection[]>([]);
  const [documents, setDocuments] = useState<DocumentEntry[]>([]);
  const [packs, setPacks] = useState<PackSummary[]>([]);
  const [view, setView] = useState<"list" | "form">("list");
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [editTarget, setEditTarget] = useState<UserAgent | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [goldens, setGoldens] = useState<AgentGolden[]>([]);
  const [goldenDraft, setGoldenDraft] = useState({ question: "", reference_sql: "" });
  const [evaluating, setEvaluating] = useState(false);
  const [evalResult, setEvalResult] = useState<AgentEvalResult | null>(null);

  const reload = useCallback(() => {
    listUserAgents().then(setAgents).catch(() => setAgents([]));
  }, []);

  useEffect(() => {
    reload();
    getConnections().then(setConnections).catch(() => {});
    listDocuments().then(setDocuments).catch(() => {});
    getPacks().then(r => setPacks((r.packs || []).filter(p => p.ok))).catch(() => {});
  }, [reload]);

  function openCreate() {
    setForm(EMPTY_FORM);
    setEditTarget(null);
    setError(null);
    setView("form");
  }

  function openEdit(a: UserAgent) {
    setForm({ name: a.name, instructions: a.instructions,
              connection_id: a.connection_id, schema_scope: a.schema_scope,
              doc_ids: a.doc_ids, pack_ids: a.pack_ids });
    setGoldens([]);
    setEvalResult(null);
    setGoldenDraft({ question: "", reference_sql: "" });
    listAgentGoldens(a.id).then(setGoldens).catch(() => {});
    setEditTarget(a);
    setError(null);
    setView("form");
  }

  async function save() {
    if (!form.name.trim()) { setError("Name is required."); return; }
    setSaving(true);
    setError(null);
    try {
      if (editTarget) await patchUserAgent(editTarget.id, form);
      else await createUserAgent(form);
      reload();
      setView("list");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed.");
    } finally {
      setSaving(false);
    }
  }

  async function toggle(a: UserAgent) {
    try {
      await patchUserAgent(a.id, { enabled: !a.enabled });
      reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Toggle failed.");
    }
  }

  async function remove(a: UserAgent) {
    if (!window.confirm(`Delete agent “${a.name}”? Its instructions and bindings are removed; documents stay.`)) return;
    await deleteUserAgent(a.id);
    reload();
  }

  function toggleDoc(docId: string) {
    setForm(f => ({
      ...f,
      doc_ids: f.doc_ids.includes(docId)
        ? f.doc_ids.filter(d => d !== docId)
        : [...f.doc_ids, docId],
    }));
  }

  async function addGolden() {
    if (!editTarget || !goldenDraft.question.trim() || !goldenDraft.reference_sql.trim()) return;
    try {
      const g = await createAgentGolden(editTarget.id, goldenDraft);
      setGoldens(gs => [...gs, g]);
      setGoldenDraft({ question: "", reference_sql: "" });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Add golden failed.");
    }
  }

  async function removeGolden(g: AgentGolden) {
    if (!editTarget) return;
    await deleteAgentGolden(editTarget.id, g.id);
    setGoldens(gs => gs.filter(x => x.id !== g.id));
  }

  async function runEvaluation() {
    if (!editTarget) return;
    setEvaluating(true);
    setError(null);
    try {
      setEvalResult(await evaluateUserAgent(editTarget.id));
      reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Evaluation failed.");
    } finally {
      setEvaluating(false);
    }
  }

  function togglePack(packId: string) {
    setForm(f => ({
      ...f,
      pack_ids: f.pack_ids.includes(packId)
        ? f.pack_ids.filter(p => p !== packId)
        : [...f.pack_ids, packId],
    }));
  }

  const connName = (id: string) => connections.find(c => c.id === id)?.name || id || "any connection";

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between",
                    padding: "14px 20px", borderBottom: "1px solid var(--b1)" }}>
        <div>
          <div style={{ fontSize: 14, fontWeight: 600, color: "var(--t1)" }}>Agents</div>
          <div style={{ fontSize: 11.5, color: "var(--t3)" }}>
            Reusable personas: standing instructions + bound documents + a connection.
            Pick one from the ask composer to answer as that agent.
          </div>
        </div>
        {view === "list" && <Button size="sm" onClick={openCreate}>New agent</Button>}
      </div>

      {error && (
        <div style={{ margin: "10px 20px 0", padding: "8px 12px", fontSize: 12,
                      borderRadius: "var(--r2)", background: "var(--red1)",
                      border: "1px solid var(--red2)", color: "var(--red5)" }}>
          {error}
        </div>
      )}

      <div className="flex-1 overflow-y-auto" style={{ padding: 20 }}>
        {view === "list" ? (
          agents.length === 0 ? (
            <div style={{ fontSize: 12.5, color: "var(--t3)", maxWidth: 520, lineHeight: 1.6 }}>
              No agents yet. An agent bundles standing instructions, a set of uploaded
              documents, and a connection into a persona you can answer as — with the
              full trust substrate (guards, receipts, access control) unchanged.
              {" "}If “New agent” fails, ask an operator to enable the
              {" "}<code>agents.user_defined</code> flag in Settings → System.
            </div>
          ) : (
            /* Persona card grid — icon + name + status, the instructions as the description,
               binding meta, and the manage actions along the footer. */
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: 14 }}>
              {agents.map(a => (
                <div key={a.id} style={{
                  display: "flex", flexDirection: "column", gap: 10, padding: 16, minHeight: 156,
                  background: "var(--bg-2)", border: "1px solid var(--b1)", borderRadius: "var(--r3)",
                  transition: "border-color .12s",
                }}
                  onMouseEnter={e => { e.currentTarget.style.borderColor = "var(--b3)"; }}
                  onMouseLeave={e => { e.currentTarget.style.borderColor = "var(--b1)"; }}
                >
                  <div style={{ display: "flex", alignItems: "flex-start", gap: 11 }}>
                    <div style={{
                      width: 34, height: 34, borderRadius: "var(--r2)", flexShrink: 0,
                      background: "color-mix(in srgb, var(--vio3) 16%, transparent)",
                      border: "1px solid color-mix(in srgb, var(--vio3) 32%, transparent)",
                      display: "flex", alignItems: "center", justifyContent: "center",
                    }}>
                      <svg width={16} height={16} viewBox="0 0 24 24" fill="none" stroke="var(--vio4)"
                           strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round">
                        <path d="M12 2l2.4 7.4H22l-6.2 4.5 2.4 7.4L12 17l-6.2 4.3 2.4-7.4L2 9.4h7.6L12 2z" />
                      </svg>
                    </div>
                    <div style={{ minWidth: 0, flex: 1 }}>
                      <div style={{ fontSize: 13.5, fontWeight: 600, color: "var(--t1)",
                                    overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {a.name}
                      </div>
                      <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 4, flexWrap: "wrap" }}>
                        <StatusChip hue={a.enabled ? "positive" : "muted"}>
                          {a.enabled ? "enabled" : "disabled"}
                        </StatusChip>
                        {a.last_eval && a.last_eval.total > 0 && (
                          <StatusChip hue={a.last_eval.passed === a.last_eval.total ? "positive" : "caution"}>
                            {a.last_eval.passed}/{a.last_eval.total} passing
                          </StatusChip>
                        )}
                      </div>
                    </div>
                  </div>
                  <div style={{
                    flex: 1, fontSize: 12, color: "var(--t3)", lineHeight: 1.5,
                    display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden",
                  }}>
                    {a.instructions || "No standing instructions."}
                  </div>
                  <div style={{ fontSize: 11, color: "var(--t4)", overflow: "hidden",
                                textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {connName(a.connection_id)}
                    {a.schema_scope ? ` · ${a.schema_scope}` : ""}
                    {" · "}{a.doc_ids.length} document{a.doc_ids.length === 1 ? "" : "s"}
                    {a.pack_ids.length > 0 ? ` · ${a.pack_ids.length} pack${a.pack_ids.length === 1 ? "" : "s"}` : ""}
                  </div>
                  <div style={{ display: "flex", gap: 6, borderTop: "1px solid var(--b1)", paddingTop: 10 }}>
                    <Button variant="ghost" size="xs" onClick={() => toggle(a)}>
                      {a.enabled ? "Disable" : "Enable"}
                    </Button>
                    <Button variant="outline" size="xs" onClick={() => openEdit(a)}>Edit</Button>
                    <Button variant="destructive" size="xs" onClick={() => remove(a)}>Delete</Button>
                  </div>
                </div>
              ))}
            </div>
          )
        ) : (
          /* ── Form ── */
          <div style={{ maxWidth: 640, display: "flex", flexDirection: "column", gap: 14 }}>
            <label style={{ display: "flex", flexDirection: "column", gap: 5 }}>
              <span className="aug-label">Name</span>
              <input className="aug-input" value={form.name} maxLength={120}
                     placeholder="e.g. Churn Analyst"
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
                <option value="">Any (use the ask’s connection)</option>
                {connections.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
              <span style={{ fontSize: 11, color: "var(--t3)" }}>
                When bound, the agent always answers over this connection.
              </span>
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
                  No uploaded documents yet — add some under Data → Documents, then attach them here.
                  An agent only sees the documents attached to it.
                </span>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 4,
                              maxHeight: 180, overflowY: "auto", padding: "8px 10px",
                              border: "1px solid var(--b1)", borderRadius: "var(--r2)" }}>
                  {documents.map(d => (
                    <label key={d.doc_id}
                           style={{ display: "flex", alignItems: "center", gap: 8,
                                    fontSize: 12, color: "var(--t2)", cursor: "pointer" }}>
                      <input type="checkbox"
                             checked={form.doc_ids.includes(d.doc_id)}
                             onChange={() => toggleDoc(d.doc_id)} />
                      <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {d.title || d.filename}
                      </span>
                    </label>
                  ))}
                </div>
              )}
            </div>

            {packs.length > 0 && (
              <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
                <span className="aug-label">Expertise packs</span>
                <div style={{ display: "flex", flexDirection: "column", gap: 4,
                              maxHeight: 140, overflowY: "auto", padding: "8px 10px",
                              border: "1px solid var(--b1)", borderRadius: "var(--r2)" }}>
                  {packs.map(p => (
                    <label key={p.id}
                           style={{ display: "flex", alignItems: "center", gap: 8,
                                    fontSize: 12, color: "var(--t2)", cursor: "pointer" }}>
                      <input type="checkbox"
                             checked={form.pack_ids.includes(p.id)}
                             onChange={() => togglePack(p.id)} />
                      <span>{p.name || p.id}</span>
                    </label>
                  ))}
                </div>
                <span style={{ fontSize: 11, color: "var(--t3)" }}>
                  A preference: pack steering is restricted to these packs when the agent runs.
                  A pack still only steers where it is deployed on the connection.
                </span>
              </div>
            )}

            {editTarget && (
              <div style={{ display: "flex", flexDirection: "column", gap: 6,
                            padding: "12px 14px", border: "1px solid var(--b1)",
                            borderRadius: "var(--r2)" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span className="aug-label">Golden questions</span>
                  <span style={{ fontSize: 11, color: "var(--t3)" }}>
                    the agent&rsquo;s own regression suite — re-run after editing instructions or documents
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
                                   whiteSpace: "nowrap" }}
                          title={g.reference_sql}>
                      {g.question}
                    </span>
                    <Button variant="ghost" size="xs" onClick={() => removeGolden(g)}>Remove</Button>
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
            )}

            <div style={{ display: "flex", gap: 8, marginTop: 4 }}>
              <Button onClick={save} disabled={saving}>
                {saving ? "Saving…" : editTarget ? "Save changes" : "Create agent"}
              </Button>
              <Button variant="ghost" onClick={() => setView("list")} disabled={saving}>Cancel</Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
