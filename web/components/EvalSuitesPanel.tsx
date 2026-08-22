"use client";
import React, { useEffect, useState, useCallback } from "react";
import {
  EvalSuite,
  EvalCase,
  EvalRunSummary,
  EvalEvaluator,
  Connection,
  getEvalSuites,
  getEvalSuite,
  createEvalSuite,
  deleteEvalSuite,
  addEvalCases,
  deleteEvalCase,
  runEvalSuite,
  getEvaluators,
  getConnections,
} from "@/lib/api";
import { MiniStat, MiniStatRow } from "@/components/ui/MiniStat";
import { StatusChip, type ChipHue } from "@/components/brief/StatusChip";
import { Button } from "@/components/ui/button";
import type { EvalsLayer } from "@/components/EvalsWorkspace";

// ── Types ─────────────────────────────────────────────────────────────────────

type View = "list" | "detail" | "form";

interface Props {
  connId?: string;
  workspaceId?: string;
  onLayerChange?: (l: EvalsLayer) => void;
}

// ── Main component ────────────────────────────────────────────────────────────

export function EvalSuitesPanel({ connId, onLayerChange }: Props) {
  const [view, setView]         = useState<View>("list");
  const [suites, setSuites]     = useState<EvalSuite[]>([]);
  const [connections, setConnections] = useState<Connection[]>([]);
  const [evaluators, setEvaluators]   = useState<EvalEvaluator[]>([]);
  const [loading, setLoading]   = useState(false);
  const [error, setError]       = useState<string | null>(null);

  // Create-suite form
  const [form, setForm] = useState({ name: "", description: "", connection_id: connId ?? "" });
  const [saving, setSaving] = useState(false);

  // Detail view
  const [detail, setDetail] = useState<(EvalSuite & { cases: EvalCase[] }) | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [ss, cs, evs] = await Promise.all([
        getEvalSuites(),
        getConnections().catch(() => []),
        getEvaluators().then(r => r.evaluators).catch(() => []),
      ]);
      setSuites(ss);
      setConnections(cs);
      setEvaluators(evs);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // ── Actions ──────────────────────────────────────────────────────────────────

  function openCreate() {
    setForm({ name: "", description: "", connection_id: connId ?? "" });
    setError(null);
    setView("form");
  }

  async function openDetail(suiteId: string) {
    setError(null);
    try {
      const d = await getEvalSuite(suiteId);
      setDetail(d);
      setView("detail");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to open suite");
    }
  }

  async function saveSuite() {
    if (!form.name.trim()) { setError("Name is required"); return; }
    setSaving(true);
    setError(null);
    try {
      const created = await createEvalSuite({
        name: form.name.trim(),
        description: form.description.trim(),
        target: "reference",
        connection_id: form.connection_id,
      });
      await load();
      await openDetail(created.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create suite");
    } finally {
      setSaving(false);
    }
  }

  async function removeSuite(id: string) {
    if (!confirm("Delete this suite and all its cases and runs?")) return;
    try {
      await deleteEvalSuite(id);
      if (detail?.id === id) { setDetail(null); setView("list"); }
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed");
    }
  }

  async function refreshDetail() {
    if (!detail) return;
    try { setDetail(await getEvalSuite(detail.id)); } catch { /* keep prior */ }
  }

  // ── Render ────────────────────────────────────────────────────────────────────

  const totalCases = suites.reduce((n, s) => n + (s.config?.case_count as number ?? 0), 0);

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", background: "var(--bg-0)", color: "var(--t1)" }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "16px 20px 12px", borderBottom: "1px solid var(--bg-3)" }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: view === "list" ? "var(--t1)" : "var(--t3)" }}>
          {view === "list" ? "Eval suites"
            : view === "form" ? "New suite"
            : detail?.name ?? "Suite"}
        </div>
        <div style={{ flex: 1 }} />
        {view === "list" && (
          <Button variant="ghost" className="h-auto" onClick={openCreate} style={{ fontSize: 12, padding: "5px 12px" }}>
            + New suite
          </Button>
        )}
        {view !== "list" && (
          <Button variant="ghost" onClick={() => { setView("list"); load(); }} className="h-auto p-0 font-normal" style={{ background: "none", border: "none", color: "var(--t3)", cursor: "pointer", fontSize: 12 }}>
            ← All suites
          </Button>
        )}
      </div>

      {/* Body */}
      <div style={{ flex: 1, overflowY: "auto", padding: 20 }}>
        {loading && <p style={{ color: "var(--t3)", fontSize: 13 }}>Loading…</p>}
        {error && <p style={{ color: "var(--red4, #ef4444)", fontSize: 13, marginBottom: 12 }}>{error}</p>}

        {/* ── LIST ── */}
        {view === "list" && !loading && (
          <>
            {suites.length > 0 && (
              <MiniStatRow>
                <MiniStat value={suites.length} label="Suites" />
                <MiniStat value={totalCases || "—"} label="Cases" />
                <MiniStat value={evaluators.length} label="Evaluators" tone="var(--blue4)" />
              </MiniStatRow>
            )}
            {suites.length === 0
              ? <EmptyState onAdd={openCreate} />
              : <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                  {suites.map(s => (
                    <SuiteCard
                      key={s.id}
                      suite={s}
                      connName={connections.find(c => c.id === s.connection_id)?.name}
                      onOpen={() => openDetail(s.id)}
                      onDelete={() => removeSuite(s.id)}
                    />
                  ))}
                </div>}
          </>
        )}

        {/* ── CREATE FORM ── */}
        {view === "form" && (
          <SuiteForm
            form={form}
            setForm={setForm}
            connections={connections}
            saving={saving}
            error={error}
            onSave={saveSuite}
            onCancel={() => setView("list")}
          />
        )}

        {/* ── DETAIL ── */}
        {view === "detail" && detail && (
          <SuiteDetail
            suite={detail}
            evaluators={evaluators}
            onChanged={refreshDetail}
            onDelete={() => removeSuite(detail.id)}
            onViewRuns={() => onLayerChange?.("runs")}
            setError={setError}
          />
        )}
      </div>
    </div>
  );
}

// ── Suite card ────────────────────────────────────────────────────────────────

function SuiteCard({ suite, connName, onOpen, onDelete }: {
  suite: EvalSuite; connName?: string; onOpen: () => void; onDelete: () => void;
}) {
  return (
    <div style={{ background: "var(--bg-1)", border: "1px solid var(--bg-3)", borderRadius: 6, padding: "12px 16px", cursor: "pointer" }}
      onClick={onOpen}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontWeight: 600, fontSize: 13, color: "var(--t1)" }}>{suite.name}</span>
            <StatusChip hue="info" strength="soft">{suite.target}</StatusChip>
          </div>
          <div style={{ fontSize: 11, color: "var(--t3)", marginTop: 3 }}>
            {suite.description || "No description"}
            {connName && <> · <span style={{ color: "var(--t2)" }}>{connName}</span></>}
          </div>
        </div>
        <div style={{ display: "flex", gap: 6 }} onClick={e => e.stopPropagation()}>
          <Button variant="ghost" onClick={onOpen} className="h-auto p-0 font-normal" style={ghostBtn}>Open</Button>
          <Button variant="ghost" onClick={onDelete} className="h-auto p-0 font-normal" style={{ ...ghostBtn, color: "var(--red4, #ef4444)" }}>Delete</Button>
        </div>
      </div>
    </div>
  );
}

// ── Suite form ────────────────────────────────────────────────────────────────

function SuiteForm({ form, setForm, connections, saving, error, onSave, onCancel }: {
  form: { name: string; description: string; connection_id: string };
  setForm: React.Dispatch<React.SetStateAction<{ name: string; description: string; connection_id: string }>>;
  connections: Connection[];
  saving: boolean;
  error: string | null;
  onSave: () => void;
  onCancel: () => void;
}) {
  return (
    <div style={{ maxWidth: 560, display: "flex", flexDirection: "column", gap: 20 }}>
      <Field label="Name">
        <input className="aug-input" value={form.name}
          onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
          placeholder="e.g. Golden SQL — revenue questions" style={{ width: "100%" }} />
      </Field>
      <Field label="Description">
        <textarea className="aug-input" rows={2} value={form.description}
          onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
          placeholder="What this suite measures" style={{ width: "100%", resize: "vertical" }} />
      </Field>
      <Field label="Connection">
        <select className="aug-input" value={form.connection_id}
          onChange={e => setForm(f => ({ ...f, connection_id: e.target.value }))} style={{ width: "100%" }}>
          <option value="">Select a connection…</option>
          {connections.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <div style={{ fontSize: 11, color: "var(--t3)", marginTop: 4 }}>
          A <code style={{ fontFamily: "var(--font-code)" }}>reference</code> suite replays each case&apos;s own SQL against this connection and
          scores the result against itself — a no-model harness check that should score ~100%.
        </div>
      </Field>
      {error && <p style={{ color: "var(--red4, #ef4444)", fontSize: 12, margin: 0 }}>{error}</p>}
      <div style={{ display: "flex", gap: 8 }}>
        <Button variant="ghost" className="h-auto" onClick={onSave} disabled={saving} style={{ minWidth: 100 }}>
          {saving ? "Creating…" : "Create suite"}
        </Button>
        <Button variant="ghost" onClick={onCancel} className="h-auto p-0 font-normal" style={{ ...ghostBtn, padding: "6px 14px" }}>Cancel</Button>
      </div>
    </div>
  );
}

// ── Suite detail (cases + run) ──────────────────────────────────────────────────

function SuiteDetail({ suite, evaluators, onChanged, onDelete, onViewRuns, setError }: {
  suite: EvalSuite & { cases: EvalCase[] };
  evaluators: EvalEvaluator[];
  onChanged: () => void;
  onDelete: () => void;
  onViewRuns: () => void;
  setError: (s: string | null) => void;
}) {
  const [question, setQuestion] = useState("");
  const [artifact, setArtifact] = useState("");
  const [adding, setAdding] = useState(false);
  const [iterations, setIterations] = useState(1);
  const [running, setRunning] = useState(false);
  const [summary, setSummary] = useState<EvalRunSummary | null>(null);

  async function addCase() {
    if (!artifact.trim()) { setError("A case needs SQL to replay (the artifact)"); return; }
    setAdding(true);
    setError(null);
    try {
      await addEvalCases(suite.id, [{ question: question.trim(), artifact: artifact.trim() }]);
      setQuestion(""); setArtifact("");
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to add case");
    } finally {
      setAdding(false);
    }
  }

  async function removeCase(id: string) {
    try { await deleteEvalCase(id); onChanged(); }
    catch (e) { setError(e instanceof Error ? e.message : "Delete failed"); }
  }

  async function run() {
    setRunning(true);
    setError(null);
    setSummary(null);
    try {
      const s = await runEvalSuite(suite.id, { iterations });
      setSummary(s);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Run failed");
    } finally {
      setRunning(false);
    }
  }

  const detCount = evaluators.filter(e => e.deterministic).length;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24, maxWidth: 720 }}>
      {/* Meta */}
      <div style={{ fontSize: 12, color: "var(--t3)" }}>
        {suite.description && <div style={{ marginBottom: 4, color: "var(--t2)" }}>{suite.description}</div>}
        <StatusChip hue="info" strength="soft">{suite.target}</StatusChip>
        <span style={{ marginLeft: 8 }}>{suite.cases.length} case{suite.cases.length === 1 ? "" : "s"}</span>
        {!suite.connection_id && <span style={{ marginLeft: 8, color: "var(--amb4, #f59e0b)" }}>· no connection — not runnable</span>}
      </div>

      {/* Run section */}
      <section style={{ background: "var(--bg-1)", border: "1px solid var(--bg-3)", borderRadius: 8, padding: 16 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12 }}>
          <span style={{ fontSize: 13, fontWeight: 600 }}>Run</span>
          <span style={{ fontSize: 11, color: "var(--t3)" }}>{detCount} deterministic evaluators</span>
          <div style={{ flex: 1 }} />
          <label style={{ fontSize: 11, color: "var(--t3)" }}>iterations</label>
          <input className="aug-input" type="number" min={1} max={10} value={iterations}
            onChange={e => setIterations(Math.max(1, Math.min(10, Number(e.target.value) || 1)))}
            style={{ width: 56 }} title="Repeat each case N times — a case that passes some but not all is FLAKY, not rounded to pass/fail" />
          <Button variant="ghost" className="h-auto" onClick={run} disabled={running || suite.cases.length === 0}
            style={{ minWidth: 90 }}>
            {running ? "Running…" : "Run suite"}
          </Button>
        </div>
        {summary
          ? <RunSummaryView summary={summary} onViewRuns={onViewRuns} />
          : <div style={{ fontSize: 11, color: "var(--t3)" }}>
              A run is a <em>band</em>, not a point: with {iterations} iteration{iterations === 1 ? "" : "s"}, a case that passes
              only some of them is reported as <strong>flaky</strong>, never rounded into the pass rate.
            </div>}
      </section>

      {/* Cases */}
      <section>
        <div style={{ fontSize: 12, fontWeight: 600, color: "var(--t2)", marginBottom: 8 }}>Cases</div>
        {suite.cases.length === 0
          ? <p style={{ fontSize: 12, color: "var(--t3)" }}>No cases yet. Add one below — the SQL is what gets replayed and scored.</p>
          : <div style={{ display: "flex", flexDirection: "column", gap: 6, marginBottom: 12 }}>
              {suite.cases.map(cs => (
                <div key={cs.id} style={{ background: "var(--bg-1)", border: "1px solid var(--bg-3)", borderRadius: 6, padding: "9px 12px", display: "flex", gap: 10, alignItems: "flex-start" }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    {cs.question && <div style={{ fontSize: 12, color: "var(--t1)", marginBottom: 3 }}>{cs.question}</div>}
                    <code style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--t3)", whiteSpace: "pre-wrap", wordBreak: "break-word" }}>{cs.artifact || "(no SQL)"}</code>
                  </div>
                  <Button variant="ghost" onClick={() => removeCase(cs.id)} className="h-auto p-0 font-normal" style={{ ...ghostBtn, color: "var(--red4, #ef4444)" }}>Remove</Button>
                </div>
              ))}
            </div>}

        {/* Add case */}
        <div style={{ display: "flex", flexDirection: "column", gap: 8, background: "var(--bg-1)", border: "1px solid var(--bg-3)", borderRadius: 6, padding: 12 }}>
          <input className="aug-input" value={question} onChange={e => setQuestion(e.target.value)}
            placeholder="Question (optional label, e.g. 'Total revenue by month')" style={{ width: "100%" }} />
          <textarea className="aug-input" rows={2} value={artifact} onChange={e => setArtifact(e.target.value)}
            placeholder="SELECT ... — the SQL this case replays" style={{ width: "100%", fontFamily: "var(--font-mono)", fontSize: 12, resize: "vertical" }} />
          <div>
            <Button variant="ghost" className="h-auto" onClick={addCase} disabled={adding} style={{ fontSize: 12 }}>
              {adding ? "Adding…" : "+ Add case"}
            </Button>
          </div>
        </div>
      </section>

      {/* Danger */}
      <div>
        <Button variant="ghost" onClick={onDelete} className="h-auto p-0 font-normal" style={{ ...ghostBtn, color: "var(--red4, #ef4444)" }}>Delete suite</Button>
      </div>
    </div>
  );
}

// ── Run summary view ────────────────────────────────────────────────────────────

function RunSummaryView({ summary, onViewRuns }: { summary: EvalRunSummary; onViewRuns: () => void }) {
  const pct = (n: number) => `${(n * 100).toFixed(1)}%`;
  const passHue: ChipHue = summary.pass_rate >= 0.999 ? "positive" : summary.pass_rate >= 0.8 ? "caution" : "negative";
  const fired = Object.entries(summary.fired_counts || {}).sort((a, b) => b[1] - a[1]);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <MiniStatRow style={{ marginBottom: 0 }}>
        <MiniStat value={pct(summary.pass_rate)} label="Pass rate (stable)" tone={summary.pass_rate >= 0.999 ? "var(--grn4)" : "var(--t1)"} />
        <MiniStat value={`${summary.stable_pass}/${summary.total}`} label="Stable pass" />
        <MiniStat value={summary.flaky} label="Flaky" tone={summary.flaky > 0 ? "var(--amb4, #f59e0b)" : "var(--t1)"} />
        <MiniStat value={summary.errors} label="Errors" tone={summary.errors > 0 ? "var(--red4, #ef4444)" : "var(--t1)"} />
        {summary.robustness != null && <MiniStat value={pct(summary.robustness)} label="Robustness" />}
        {summary.accuracy != null && <MiniStat value={pct(summary.accuracy)} label="Accuracy" />}
      </MiniStatRow>
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <StatusChip hue={passHue}>{summary.stable_pass === summary.total ? "all stable" : `${summary.flaky} flaky · ${summary.stable_fail} fail`}</StatusChip>
        <span style={{ fontSize: 11, color: "var(--t3)" }}>{summary.iterations} iteration{summary.iterations === 1 ? "" : "s"} · run {summary.run_id}</span>
        <div style={{ flex: 1 }} />
        <Button variant="ghost" onClick={onViewRuns} className="h-auto p-0 font-normal" style={ghostBtn}>View run history →</Button>
      </div>
      {fired.length > 0 && (
        <div style={{ fontSize: 11, color: "var(--t3)" }}>
          Evaluators fired:{" "}
          {fired.map(([name, n]) => (
            <span key={name} style={{ marginRight: 10 }}>
              <code style={{ fontFamily: "var(--font-code)", color: "var(--t2)" }}>{name}</code> ×{n}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Small helpers ─────────────────────────────────────────────────────────────

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
      <label className="aug-label" style={{ fontSize: 11, color: "var(--t3)", textTransform: "uppercase", letterSpacing: "0.05em" }}>{label}</label>
      {children}
    </div>
  );
}

function EmptyState({ onAdd }: { onAdd: () => void }) {
  return (
    <div style={{ textAlign: "center", paddingTop: 60, color: "var(--t3)" }}>
      <div style={{ fontSize: 28, marginBottom: 12 }}>✓</div>
      <div style={{ fontSize: 15, fontWeight: 500, color: "var(--t2)", marginBottom: 6 }}>No eval suites yet</div>
      <div style={{ fontSize: 12, marginBottom: 20 }}>A suite runs the same cases under a target and reports a measurement as a band — replicated, never a single-run point.</div>
      <Button variant="ghost" className="h-auto" onClick={onAdd}>Create first suite</Button>
    </div>
  );
}

const ghostBtn: React.CSSProperties = {
  background: "none", border: "1px solid var(--bg-3)",
  color: "var(--t2)", borderRadius: 4, cursor: "pointer",
  fontSize: 11, padding: "3px 9px",
};
