"use client";

/**
 * Create an agent — Start → Scope → Define → Prove.
 *
 * The flow it replaces asked for a name and a paragraph, then dropped the user on an empty
 * run history. Everything that decides whether the agent can answer anything — which
 * database, which schema, which documents — was on a different tab they had to find.
 *
 * **Scope before prose.** Step 2 is the one this product was missing, and the one every
 * data-agent builder leads with (the incumbents open on a table picker; Snowflake Cortex
 * recommends fewer than ten tables): an agent that has not been told where to look cannot
 * be judged on what it says. It is also a defect fix — `schema_scope` was free text with no
 * validation and hard consequences: a typo produced an agent that 409s on every ask,
 * silently, until somebody asked it something. Here it is a picker over the real catalogue,
 * and the tables it covers are counted on screen.
 *
 * **Only fields that reach the runtime.** The form offers exactly the five GOVERNING_FIELDS
 * plus the name — the set `agent_brief_block`, the document scope, the pack pool and the ask
 * bindings actually read, and the same set the eval digest is computed over. A knob that
 * changes nothing is worse than a missing one, because it teaches the reader the page lies.
 *
 * **The empty-documents disclosure.** Attaching no documents is not neutral: the retrieval
 * seam fails closed for an active agent, so an agent with none sees FEWER documents than
 * asking with no agent at all. That is stated on the step, not buried.
 *
 * **No canvas, deliberately.** An agent here is one record — a scope and a stance — with no
 * producer/consumer relationship between its parts, so a node graph would have nowhere for
 * an edge to terminate. The evidence agrees: OpenAI's own agent canvas is being shut down,
 * Flowise sunset its low-code builder over the same limits, and Copilot Studio keeps a FORM
 * for the agent and reserves its canvas for conversation flow. This repo reached the same
 * conclusion when it parked the workflow builder — there the blocker was that the runtime
 * could not honour the edges a canvas would draw.
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import { StatusChip } from "@/components/brief/StatusChip";
import { Button } from "@/components/ui/button";
import {
  createAgentGolden, createUserAgent, createUserAgentFromTemplate, getCatalogTree,
  getConnections, getPacks, listAgentTemplates, listDocuments,
  type AgentTemplate, type CatalogTree, type Connection, type DocumentEntry,
  type PackSummary, type UserAgent,
} from "@/lib/api";
import { formatCount } from "@/lib/format";

type Step = "start" | "scope" | "define" | "prove";
type Seed = { question: string; needs: string };

const STEPS: { id: Step; label: string; blurb: string }[] = [
  { id: "start",  label: "Start",  blurb: "from a pack, or from scratch" },
  { id: "scope",  label: "Scope",  blurb: "where it may look" },
  { id: "define", label: "Define", blurb: "how it should think" },
  { id: "prove",  label: "Prove",  blurb: "how you'll know it works" },
];

/** Tables covered by a (connection, schema) choice, from the real catalogue. */
function tablesFor(tree: CatalogTree | null, connId: string, schema: string): string[] {
  if (!tree || !connId) return [];
  for (const section of tree.sections ?? []) {
    for (const entry of (section.entries ?? []) as unknown as Array<{
      conn_id: string; schemas?: { name: string; tables?: { name: string }[] }[];
    }>) {
      if (entry.conn_id !== connId) continue;
      const schemas = entry.schemas ?? [];
      const picked = schema ? schemas.filter(s => s.name === schema) : schemas;
      return picked.flatMap(s => (s.tables ?? []).map(t => t.name));
    }
  }
  return [];
}

function schemasFor(tree: CatalogTree | null, connId: string): string[] {
  if (!tree || !connId) return [];
  for (const section of tree.sections ?? []) {
    for (const entry of (section.entries ?? []) as unknown as Array<{
      conn_id: string; schemas?: { name: string }[];
    }>) {
      if (entry.conn_id === connId) return (entry.schemas ?? []).map(s => s.name);
    }
  }
  return [];
}

export function CreateAgentFlow({ onCreated, onCancel }: {
  onCreated: (agent: UserAgent) => void;
  onCancel: () => void;
}) {
  const [step, setStep] = useState<Step>("start");
  const [templates, setTemplates] = useState<AgentTemplate[]>([]);
  const [connections, setConnections] = useState<Connection[]>([]);
  const [documents, setDocuments] = useState<DocumentEntry[]>([]);
  const [packs, setPacks] = useState<PackSummary[]>([]);
  const [tree, setTree] = useState<CatalogTree | null>(null);

  // The agent being composed. Exactly the fields the runtime reads.
  const [template, setTemplate] = useState<AgentTemplate | null>(null);
  const [name, setName] = useState("");
  const [instructions, setInstructions] = useState("");
  const [connectionId, setConnectionId] = useState("");
  const [schemaScope, setSchemaScope] = useState("");
  const [docIds, setDocIds] = useState<string[]>([]);
  const [packIds, setPackIds] = useState<string[]>([]);
  const [seeds, setSeeds] = useState<Seed[]>([]);
  const [goldens, setGoldens] = useState<{ question: string; reference_sql: string }[]>([]);
  const [draft, setDraft] = useState<{ question: string; sql: string }>({ question: "", sql: "" });

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listAgentTemplates().then(setTemplates).catch(() => setTemplates([]));
    getConnections().then(setConnections).catch(() => setConnections([]));
    listDocuments().then(setDocuments).catch(() => setDocuments([]));
    getPacks().then(r => setPacks((r.packs ?? []).filter(x => x.ok)))
      .catch(() => setPacks([]));
    getCatalogTree().then(setTree).catch(() => setTree(null));
  }, []);

  const schemas = useMemo(() => schemasFor(tree, connectionId), [tree, connectionId]);
  const tables = useMemo(() => tablesFor(tree, connectionId, schemaScope),
                         [tree, connectionId, schemaScope]);

  const pickTemplate = (t: AgentTemplate) => {
    setTemplate(t);
    setName(t.name);
    setInstructions(t.instructions);
    setPackIds([t.pack_id]);
    setSeeds(t.suggested_goldens ?? []);
    setStep("scope");
  };

  const startBlank = () => {
    setTemplate(null); setName(""); setInstructions("");
    setPackIds([]); setSeeds([]);
    setStep("scope");
  };

  const canLeaveScope = Boolean(name.trim());

  const create = useCallback(async () => {
    setBusy(true); setError(null);
    try {
      // The template path takes the SAME bindings as the scratch path. It always accepted
      // them; the previous UI sent only `pack_id`, so an agent created from a pack could not be
      // named — and its suggested goldens, returned so the creator could supply SQL "while
      // they still have the domain in mind", were discarded.
      const agent = template
        ? (await createUserAgentFromTemplate({
            pack_id: template.pack_id, name: name.trim(),
            connection_id: connectionId, schema_scope: schemaScope,
          })).agent
        : await createUserAgent({
            name: name.trim(), instructions, connection_id: connectionId,
            schema_scope: schemaScope, doc_ids: docIds, pack_ids: packIds,
          });
      // Goldens are written after the agent exists — each needs its id. A failure here
      // must not orphan the agent, so they are best-effort and reported, not fatal.
      const failed: string[] = [];
      for (const g of goldens) {
        try { await createAgentGolden(agent.id, g); }
        catch { failed.push(g.question); }
      }
      if (failed.length) {
        setError(`Agent created. ${failed.length} golden(s) were refused (the SQL must parse `
          + `and be read-only): ${failed.join(" · ")}`);
      }
      onCreated(agent);
    } catch (e) {
      setError(String((e as Error)?.message || e));
    } finally { setBusy(false); }
  }, [template, name, instructions, connectionId, schemaScope, docIds, packIds, goldens,
      onCreated]);

  const idx = STEPS.findIndex(s => s.id === step);

  return (
    <div style={{ flex: 1, overflowY: "auto", padding: "18px 22px", maxWidth: 940 }}>
      {/* ── header + stepper ── */}
      <div style={{ display: "flex", alignItems: "flex-start", gap: 12, marginBottom: 14 }}>
        <div style={{ flex: 1 }}>
          <h3 className="aug-text-h2" style={{ margin: 0 }}>Create an agent</h3>
          <p className="aug-fs-sm" style={{ color: "var(--t2)", margin: "3px 0 0" }}>
            An agent is a <b>scope</b> and a <b>stance</b>: where it may look, and how it
            should think about what it finds.
          </p>
        </div>
        <Button variant="ghost" size="sm" onClick={onCancel}>Cancel</Button>
      </div>

      <ol style={{ display: "flex", gap: 6, listStyle: "none", padding: 0, margin: "0 0 16px" }}>
        {STEPS.map((s, i) => {
          const state = i === idx ? "on" : i < idx ? "done" : "todo";
          return (
            <li key={s.id} style={{ flex: 1 }}>
              <div style={{
                borderTop: `2px solid ${state === "todo" ? "var(--b2)" : "var(--blue3)"}`,
                paddingTop: 6, opacity: state === "todo" ? 0.55 : 1,
              }}>
                <div className="aug-fs-sm" style={{ color: "var(--t1)", fontWeight: 600 }}>
                  {i + 1}. {s.label}
                </div>
                <div className="aug-fs-xs" style={{ color: "var(--t2)" }}>{s.blurb}</div>
              </div>
            </li>
          );
        })}
      </ol>

      {error && (
        <div className="aug-fs-sm" role="alert" style={{
          padding: "8px 12px", borderRadius: "var(--r2)", background: "var(--red1)",
          border: "1px solid var(--red2)", color: "var(--red5)", marginBottom: 12,
        }}>{error}</div>
      )}

      {/* ── 1 · Start ── */}
      {step === "start" && (
        <Section title="Start from a pack, or from scratch">
          {templates.length === 0 ? (
            <Note>No packs are installed, so there is nothing to start from — create from
              scratch and give the agent its stance yourself.</Note>
          ) : (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 10 }}>
              {templates.map(t => (
                <div key={t.pack_id} style={{
                  background: "var(--bg-2)", border: "1px solid var(--b1)",
                  borderRadius: "var(--r3)", padding: "12px 14px",
                  display: "flex", flexDirection: "column", gap: 7,
                }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <span className="aug-text-ui" style={{ fontWeight: 600 }}>{t.name}</span>
                    {t.status !== "active" && (
                      <StatusChip hue="muted" strength="soft">{t.status}</StatusChip>
                    )}
                  </div>
                  <p className="aug-fs-sm" style={{ color: "var(--t2)", margin: 0 }}>{t.persona}</p>
                  <p className="aug-fs-xs" style={{ color: "var(--t2)", margin: 0 }}>
                    {t.domains.join(" · ")}
                    {t.suggested_goldens.length > 0
                      && ` · ${t.suggested_goldens.length} suggested questions`}
                  </p>
                  <Button variant="secondary" size="sm" onClick={() => pickTemplate(t)}
                    style={{ alignSelf: "flex-start" }}>Start from {t.name}</Button>
                </div>
              ))}
            </div>
          )}
          <div style={{ marginTop: 12 }}>
            <Button variant="outline" size="sm" onClick={startBlank}>Start from scratch</Button>
          </div>
        </Section>
      )}

      {/* ── 2 · Scope ── */}
      {step === "scope" && (
        <>
          <Section title="Name it">
            <Field label="Name" hint="Appears in its answers — the agent is told who it is.">
              <input className="aug-input" value={name} maxLength={120} autoFocus
                onChange={e => setName(e.target.value)}
                placeholder="e.g. Retention Analyst" style={{ width: "100%", maxWidth: 420 }} />
            </Field>
          </Section>

          <Section title="Where it may look"
            note="An agent that has not been told where to look cannot be judged on what it says.">
            <Field label="Connection"
              hint="Leave unset and the agent answers against whichever connection the question came from.">
              <select className="aug-input" value={connectionId} style={{ maxWidth: 420 }}
                onChange={e => { setConnectionId(e.target.value); setSchemaScope(""); }}>
                <option value="">Any — use the question&rsquo;s connection</option>
                {connections.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </Field>

            <Field label="Schema"
              hint={connectionId
                ? "Picked from this connection's real catalogue — a schema that does not exist would make every ask fail."
                : "Choose a connection first to pick a schema."}>
              <select className="aug-input" value={schemaScope} disabled={!connectionId}
                onChange={e => setSchemaScope(e.target.value)} style={{ maxWidth: 420 }}>
                <option value="">All schemas in this connection</option>
                {schemas.map(s => <option key={s} value={s}>{s}</option>)}
              </select>
            </Field>

            {connectionId && (
              <p className="aug-fs-sm" style={{ color: "var(--t2)", margin: "2px 0 0" }}>
                {tables.length === 0
                  ? "No tables found in this scope yet."
                  : <>In scope: <b style={{ color: "var(--t1)" }}>{formatCount(tables.length)} table
                      {tables.length === 1 ? "" : "s"}</b>
                      {tables.length <= 8 && <> — {tables.join(", ")}</>}
                      {tables.length > 30 && (
                        <span style={{ color: "var(--amb4)" }}> · a narrower scope answers
                          more reliably</span>
                      )}
                    </>}
              </p>
            )}
          </Section>

          <Nav onBack={() => setStep("start")} onNext={() => setStep("define")}
            nextDisabled={!canLeaveScope}
            nextHint={canLeaveScope ? undefined : "A name is required."} />
        </>
      )}

      {/* ── 3 · Define ── */}
      {step === "define" && (
        <>
          <Section title="How it should think">
            <Field label="Instructions"
              hint={template
                ? `Prefilled from the ${template.name} pack — edit freely, it is only a starting stance.`
                : "Standing instructions, prepended to every answer this agent gives."}>
              <textarea className="aug-input" value={instructions} rows={8} maxLength={8000}
                onChange={e => setInstructions(e.target.value)}
                placeholder="What this agent is for, what it should prioritise, how it should present findings."
                style={{ width: "100%", resize: "vertical", fontFamily: "var(--font-ui)" }} />
            </Field>
          </Section>

          <Section title="Documents"
            note="Attaching none is not neutral: an agent with no documents attached sees NO documents at all — fewer than asking with no agent.">
            {documents.length === 0 ? (
              <Note>No documents uploaded yet. Upload them from a chat, then attach them here
                later.</Note>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 4, maxHeight: 168,
                            overflowY: "auto" }}>
                {documents.map(d => (
                  <label key={d.doc_id} className="aug-fs-sm"
                    style={{ display: "flex", gap: 8, alignItems: "center", cursor: "pointer" }}>
                    <input type="checkbox" checked={docIds.includes(d.doc_id)}
                      onChange={e => setDocIds(prev => e.target.checked
                        ? [...prev, d.doc_id] : prev.filter(x => x !== d.doc_id))} />
                    <span style={{ color: "var(--t1)" }}>{d.title || d.filename}</span>
                    <span className="aug-fs-xs" style={{ color: "var(--t2)" }}>
                      {formatCount(d.chunk_count)} chunks
                    </span>
                  </label>
                ))}
              </div>
            )}
          </Section>

          {packs.length > 0 && !template && (
            <Section title="Packs"
              note="A pack steers a question only once it is active AND pinned to the connection — binding one here is inert until then.">
              <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                {packs.map(p => (
                  <label key={p.id} className="aug-fs-sm"
                    style={{ display: "flex", gap: 8, alignItems: "center", cursor: "pointer" }}>
                    <input type="checkbox" checked={packIds.includes(p.id)}
                      onChange={e => setPackIds(prev => e.target.checked
                        ? [...prev, p.id] : prev.filter(x => x !== p.id))} />
                    <span style={{ color: "var(--t1)" }}>{p.name}</span>
                    {p.status !== "active" && (
                      <StatusChip hue="muted" strength="soft">{p.status}</StatusChip>
                    )}
                  </label>
                ))}
              </div>
            </Section>
          )}

          <Nav onBack={() => setStep("scope")} onNext={() => setStep("prove")} />
        </>
      )}

      {/* ── 4 · Prove ── */}
      {step === "prove" && (
        <>
          <Section title="How you'll know it works"
            note="A question with reference SQL is ground truth: the suite runs both and compares the result sets, so a pass means the agent got the same answer — not that a model approved of it.">
            {seeds.length > 0 && (
              <div style={{ marginBottom: 12 }}>
                <div className="aug-label" style={{ color: "var(--t2)", marginBottom: 6 }}>
                  Suggested by the {template?.name} pack
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                  {seeds.map(s => (
                    <div key={s.question} style={{
                      display: "flex", alignItems: "center", gap: 10, padding: "7px 10px",
                      background: "var(--bg-1)", border: "1px solid var(--b1)",
                      borderRadius: "var(--r2)",
                    }}>
                      <span className="aug-fs-sm" style={{ flex: 1, color: "var(--t1)" }}>
                        {s.question}
                      </span>
                      <Button variant="ghost" size="xs"
                        onClick={() => { setDraft({ question: s.question, sql: "" });
                                         setSeeds(p => p.filter(x => x !== s)); }}>
                        Add reference SQL →
                      </Button>
                    </div>
                  ))}
                </div>
                <p className="aug-fs-xs" style={{ color: "var(--t2)", margin: "6px 0 0" }}>
                  These carry no SQL on purpose — a suite the model writes for itself measures
                  nothing. Supply the query you would trust, and the question becomes ground truth.
                </p>
              </div>
            )}

            <Field label="Question">
              <input className="aug-input" value={draft.question} style={{ width: "100%" }}
                onChange={e => setDraft(d => ({ ...d, question: e.target.value }))}
                placeholder="A question you already know the right answer to" />
            </Field>
            <Field label="Reference SQL" hint="Read-only, and it must parse.">
              <textarea className="aug-input" value={draft.sql} rows={3}
                onChange={e => setDraft(d => ({ ...d, sql: e.target.value }))}
                placeholder="SELECT …"
                style={{ width: "100%", resize: "vertical", fontFamily: "var(--font-code)" }} />
            </Field>
            <Button variant="outline" size="sm"
              disabled={!draft.question.trim() || !draft.sql.trim()}
              onClick={() => { setGoldens(g => [...g, { question: draft.question.trim(),
                                                        reference_sql: draft.sql.trim() }]);
                               setDraft({ question: "", sql: "" }); }}>
              Add question
            </Button>

            {goldens.length > 0 && (
              <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 4 }}>
                {goldens.map((g, i) => (
                  <div key={i} style={{ display: "flex", alignItems: "center", gap: 10,
                    padding: "7px 10px", background: "var(--bg-2)",
                    border: "1px solid var(--b1)", borderRadius: "var(--r2)" }}>
                    <StatusChip hue="positive" strength="soft">ground truth</StatusChip>
                    <span className="aug-fs-sm" style={{ flex: 1, color: "var(--t1)" }}>
                      {g.question}
                    </span>
                    <Button variant="ghost" size="xs"
                      onClick={() => setGoldens(p => p.filter((_, j) => j !== i))}>Remove</Button>
                  </div>
                ))}
              </div>
            )}

            {goldens.length === 0 && (
              <Note>You can create the agent without any — it will simply have no evidence
                behind it, and its roster chip will say so until it does.</Note>
            )}
          </Section>

          <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 14 }}>
            <Button variant="ghost" size="sm" onClick={() => setStep("define")}>Back</Button>
            <span style={{ flex: 1 }} />
            <span className="aug-fs-sm" style={{ color: "var(--t2)" }}>
              Creating it makes it available in chat straight away.
            </span>
            <Button variant="secondary" size="sm" disabled={busy || !name.trim()}
              onClick={create}>{busy ? "Creating…" : "Create agent"}</Button>
          </div>
        </>
      )}
    </div>
  );
}

// ── small parts ──────────────────────────────────────────────────────────────────

function Section({ title, note, children }: {
  title: string; note?: string; children: React.ReactNode;
}) {
  return (
    <section style={{ marginBottom: 18 }}>
      <h4 className="aug-label" style={{ color: "var(--t2)", margin: "0 0 3px" }}>{title}</h4>
      {note && (
        <p className="aug-fs-sm" style={{ color: "var(--t2)", margin: "0 0 8px", maxWidth: 640 }}>
          {note}
        </p>
      )}
      {children}
    </section>
  );
}

function Field({ label, hint, children }: {
  label: string; hint?: string; children: React.ReactNode;
}) {
  return (
    <div style={{ marginBottom: 10 }}>
      <div className="aug-fs-sm" style={{ color: "var(--t1)", marginBottom: 3, fontWeight: 500 }}>
        {label}
      </div>
      {children}
      {hint && (
        <p className="aug-fs-xs" style={{ color: "var(--t2)", margin: "3px 0 0", maxWidth: 620 }}>
          {hint}
        </p>
      )}
    </div>
  );
}

function Note({ children }: { children: React.ReactNode }) {
  return (
    <p className="aug-fs-sm" style={{
      color: "var(--t2)", margin: 0, padding: "8px 11px", background: "var(--bg-1)",
      border: "1px solid var(--b1)", borderRadius: "var(--r2)", maxWidth: 640,
    }}>{children}</p>
  );
}

function Nav({ onBack, onNext, nextDisabled, nextHint }: {
  onBack: () => void; onNext: () => void; nextDisabled?: boolean; nextHint?: string;
}) {
  return (
    <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 14 }}>
      <Button variant="ghost" size="sm" onClick={onBack}>Back</Button>
      <span style={{ flex: 1 }} />
      {nextHint && <span className="aug-fs-sm" style={{ color: "var(--t2)" }}>{nextHint}</span>}
      <Button variant="secondary" size="sm" onClick={onNext} disabled={nextDisabled}>
        Continue
      </Button>
    </div>
  );
}
