"use client";

import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  createMetric,
  deleteMetric,
  getMetricCatalogue,
  getMetrics,
  materialiseMetric,
  getMetricFreshness,
  updateMetric,
  validateMetric,
  transitionMetric,
  getMetricAudit,
  getDefinitionReport,
  type CatalogueMetric,
  type Metric,
  type MetricValidationResult,
  type MetricFreshnessResult,
  type MetricAuditEntry,
  type DefinitionReport,
  type DefinitionClaim,
} from "@/lib/api";

// ── Governance lifecycle (B-8) ──────────────────────────────────────────────────
const STATUS_STYLE: Record<string, string> = {
  draft:      "border-zinc-600 bg-zinc-800 text-zinc-400",
  proposed:   "border-amber-500/40 bg-amber-500/10 text-amber-400",
  approved:   "border-emerald-500/40 bg-emerald-500/10 text-emerald-400",
  deprecated: "border-zinc-700 bg-zinc-800/60 text-zinc-500 line-through",
};
// Legal transitions per state — mirrors aughor/semantic/governance.py.
const NEXT_ACTIONS: Record<string, string[]> = {
  draft:      ["propose"],
  proposed:   ["approve", "reject"],
  approved:   ["deprecate"],
  deprecated: ["propose"],
};

/** A3 — one claim, rendered so that "could not check" never reads like "nothing to report".
 *
 *  An UNAVAILABLE section is drawn in the SAME weight as one with findings, because the thing
 *  it is telling the approver — we could not answer this — is exactly as load-bearing as an
 *  answer. Greying it out would reproduce, in CSS, the collapse the server refuses to make. */
function ClaimBlock({ title, claim }: { title: string; claim: DefinitionClaim }) {
  const tone =
    claim.outcome === "unavailable" ? "border-amber-500/40 text-amber-300"
    : claim.findings.some(f => f.severity === "defect") ? "border-red-500/40 text-red-300"
    : claim.outcome === "findings" ? "border-amber-500/40 text-amber-300"
    : "border-zinc-700 text-zinc-400";
  return (
    <div className={`rounded border ${tone.split(" ")[0]} bg-zinc-900/40 p-2`}>
      <div className="flex items-baseline gap-2">
        <span className="aug-fs-xs font-medium text-zinc-300">{title}</span>
        <span className={`aug-fs-xs ${tone.split(" ")[1]}`}>{claim.outcome.replace("_", " ")}</span>
      </div>
      <div className="aug-fs-xs text-zinc-400 mt-1">{claim.summary}</div>
      {claim.findings.length > 0 && (
        <ul className="mt-1.5 flex flex-col gap-1">
          {claim.findings.map(f => (
            <li key={f.code} className="aug-fs-xs">
              <span className={f.severity === "defect" ? "text-red-400" : "text-amber-400"}>
                {f.severity === "defect" ? "✕" : "!"}
              </span>{" "}
              <span className="text-zinc-300">{f.what}</span>
              {/* The evidence is not decoration: a finding a reader cannot check is one they
                  must take on faith, which is what this screen exists to stop. */}
              <div className="text-zinc-500 pl-4 font-mono">{f.evidence}</div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** A3 — the report beside the ask.
 *
 *  Deliberately renders NO recommendation and pre-selects nothing. The drafting study found
 *  jev-align placing the menu cursor on the model's own answer at exactly the screen the design
 *  insists must be human, and refused it: on an ambiguous row the pre-selection is a coin flip
 *  that one keypress records as a human judgement. The definition is the user's call, so this
 *  shows what was measured and stops. */
function DefinitionReportBlock({ report }: { report: DefinitionReport }) {
  const pop = report.population;
  return (
    <div className="mt-2 rounded-md border border-zinc-700 bg-zinc-900/60 p-2.5 flex flex-col gap-2">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="aug-fs-xs font-medium text-zinc-300">Before you decide</span>
        <span className="aug-fs-xs px-1.5 rounded border border-zinc-600 text-zinc-500">advisory</span>
        {report.defects.length > 0 && (
          <span className="aug-fs-xs px-1.5 rounded border border-red-500/40 text-red-400">
            {report.defects.length} defect{report.defects.length > 1 ? "s" : ""}
          </span>
        )}
      </div>
      <ClaimBlock title="What it changes" claim={report.predecessor} />
      <ClaimBlock title="Whether it runs" claim={report.execution} />
      <ClaimBlock title="What it declares" claim={report.declaration} />
      <ClaimBlock title="What could be compared" claim={report.segments} />
      {/* The population line is stated LAST but never omitted. A4's lesson, applied: a caveat
          printed after a row of green ticks reads as a footnote to reassurance — so when the
          numbers cannot be pinned, this says so in the amber it deserves rather than in grey. */}
      <div className={`aug-fs-xs rounded border p-2 ${
        pop.reproducible ? "border-zinc-700 text-zinc-500"
                         : "border-amber-500/40 text-amber-300"}`}>
        <span className="font-medium">Population: {pop.mode}</span>
        {pop.reason && <span className="text-zinc-400"> — {pop.reason}</span>}
        {pop.token && <span className="text-zinc-500 font-mono"> {pop.token}</span>}
      </div>
    </div>
  );
}

// ── Dates (Arc BR-2) ──────────────────────────────────────────────────────────────
// How the metric is measured for a date range. The platform sets these by rule — the user's
// call (ROADMAP §6 item 34(b)) — and says which rule; a person confirms or corrects them here,
// and from then on the platform leaves them alone.

const KIND_WORDS: Record<string, string> = {
  flow: "adds up over a range", stock: "a level at a date", cohort: "tied to one date, completed by a later one",
};

function datesSentence(m: Metric): string {
  if (!m.time_kind || !m.time_column) return "Not set — this metric cannot be measured for a date range yet.";
  if (m.time_kind === "cohort") {
    const settles = m.settles_after_days != null ? `, settles after ${m.settles_after_days} days` : ", settling time not yet measured";
    return `Cohort — tied to ${m.time_column}, completed by ${m.outcome_column ?? "?"}${settles}.`;
  }
  if (m.time_kind === "stock") return `Stock — a row counts from ${m.time_column} until ${m.until_column ?? "?"}.`;
  return `Flow — a row counts on the day of ${m.time_column}.`;
}

function DatesSection({ metric, onChanged }: { metric: Metric; onChanged: () => void }) {
  const [editing, setEditing] = useState(false);
  const [kind, setKind] = useState(metric.time_kind ?? "flow");
  const [column, setColumn] = useState(metric.time_column ?? "");
  const [outcome, setOutcome] = useState(metric.outcome_column ?? "");
  const [until, setUntil] = useState(metric.until_column ?? "");
  const [settles, setSettles] = useState(metric.settles_after_days != null ? String(metric.settles_after_days) : "");
  const [actor, setActor] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const save = async (fields: Partial<Metric>) => {
    setErr("");
    if (!actor.trim()) { setErr("Enter who is confirming this."); return; }
    setBusy(true);
    try {
      await updateMetric(metric.name, { ...metric, ...fields, time_confirmed_by: actor.trim() });
      setEditing(false);
      onChanged();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not save the dates");
    } finally { setBusy(false); }
  };

  const confirmed = !!metric.time_confirmed_by;
  return (
    <div className="rounded-md border border-zinc-700 bg-zinc-800/40 p-3" data-testid="metric-dates">
      <div className="flex items-center gap-2 mb-2 flex-wrap">
        <span className="text-xs font-medium text-zinc-300">Dates</span>
        {metric.time_kind && (
          <span className="aug-fs-xs px-1.5 rounded border border-zinc-600 text-zinc-400">
            {confirmed ? `confirmed by ${metric.time_confirmed_by}` : "set automatically"}
          </span>
        )}
      </div>
      <p className="aug-fs-xs text-zinc-300">{datesSentence(metric)}</p>
      {metric.time_kind && (
        <p className="aug-fs-xs text-zinc-500 mt-1">{KIND_WORDS[metric.time_kind] ?? ""}{metric.time_source ? ` · ${metric.time_source}` : ""}</p>
      )}
      {!editing ? (
        <div className="flex items-center gap-2 mt-2 flex-wrap">
          <input className="aug-input aug-fs-xs" placeholder="Who is confirming" value={actor}
            onChange={e => setActor(e.target.value)} aria-label="Who is confirming the dates" />
          {metric.time_kind && !confirmed && (
            <Button size="sm" variant="secondary" disabled={busy} onClick={() => save({})}>Confirm</Button>
          )}
          <Button size="sm" variant="ghost" onClick={() => setEditing(true)}>Correct…</Button>
        </div>
      ) : (
        <div className="grid gap-2 mt-2">
          <label className="aug-fs-xs text-zinc-400">Kind
            <select className="aug-select aug-fs-xs ml-2" value={kind} onChange={e => setKind(e.target.value as "flow" | "stock" | "cohort")}>
              <option value="flow">Flow — adds up over a range</option>
              <option value="stock">Stock — a level at a date</option>
              <option value="cohort">Cohort — completed by a later date</option>
            </select>
          </label>
          <input className="aug-input aug-fs-xs" placeholder="Date column, e.g. created_at" value={column}
            onChange={e => setColumn(e.target.value)} aria-label="Date column" />
          {kind === "cohort" && (
            <>
              <input className="aug-input aug-fs-xs" placeholder="Completing date, e.g. returned_at" value={outcome}
                onChange={e => setOutcome(e.target.value)} aria-label="Completing date column" />
              <input className="aug-input aug-fs-xs" placeholder="Settles after (days)" value={settles}
                onChange={e => setSettles(e.target.value)} aria-label="Settles after days" />
            </>
          )}
          {kind === "stock" && (
            <input className="aug-input aug-fs-xs" placeholder="Counts until, e.g. sold_at" value={until}
              onChange={e => setUntil(e.target.value)} aria-label="Counts until column" />
          )}
          <input className="aug-input aug-fs-xs" placeholder="Who is confirming" value={actor}
            onChange={e => setActor(e.target.value)} aria-label="Who is confirming the dates" />
          <div className="flex items-center gap-2">
            <Button size="sm" variant="secondary" disabled={busy || !column.trim()}
              onClick={() => save({
                time_kind: kind, time_column: column.trim(),
                outcome_column: kind === "cohort" ? outcome.trim() || null : null,
                until_column: kind === "stock" ? until.trim() || null : null,
                settles_after_days: kind === "cohort" && settles.trim() ? Number(settles) : null,
              })}>Save dates</Button>
            <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>Cancel</Button>
          </div>
        </div>
      )}
      {err && <p className="aug-fs-xs text-red-400 mt-1">{err}</p>}
    </div>
  );
}

function GovernanceSection({ metric, onChanged }: { metric: Metric; onChanged: () => void }) {
  const [actor, setActor] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState("");
  const [audit, setAudit] = useState<MetricAuditEntry[]>([]);
  const [showAudit, setShowAudit] = useState(false);
  const [report, setReport] = useState<DefinitionReport | null>(null);
  const [reportErr, setReportErr] = useState("");

  const status = metric.status ?? "draft";
  const actions = NEXT_ACTIONS[status] ?? [];

  useEffect(() => {
    let alive = true;
    getMetricAudit(metric.name).then(a => { if (alive) setAudit(a); }).catch(() => {});
    return () => { alive = false; };
  }, [metric.name]);

  // A3 — fetched whenever there is a decision to take. A metric with no next action has nobody
  // to inform, so the call is not made at all rather than made and hidden. `wantReport` is
  // DERIVED rather than pushed into state: setting state synchronously in an effect body
  // triggers cascading renders (react-hooks/set-state-in-effect), and the render below gates on
  // the same value, so there is nothing to reset.
  const reportConn = metric.connection;
  const wantReport = !!reportConn && reportConn !== "*" && actions.length > 0;

  useEffect(() => {
    if (!wantReport || !reportConn) return;
    let alive = true;
    getDefinitionReport(metric.name, reportConn)
      .then(r => { if (alive) { setReport(r); setReportErr(""); } })
      .catch(e => {
        if (alive) { setReport(null); setReportErr(e instanceof Error ? e.message : "unavailable"); }
      });
    return () => { alive = false; };
  }, [metric.name, reportConn, metric.sql, status, wantReport]);

  const run = async (action: string) => {
    setErr("");
    if (!actor.trim()) { setErr("Enter who's performing this (actor)."); return; }
    setBusy(action);
    try {
      // The connection is SENT — without it the server looks for a global metric of this name
      // and 404s every scoped one. See `transitionMetric`'s note.
      await transitionMetric(metric.name, action, actor.trim(), metric.connection);
      setAudit(await getMetricAudit(metric.name));
      onChanged();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Transition failed");
    } finally { setBusy(null); }
  };

  return (
    <div className="rounded-md border border-zinc-700 bg-zinc-800/40 p-3">
      <div className="flex items-center gap-2 mb-2 flex-wrap">
        <span className="text-xs font-medium text-zinc-300">Governance</span>
        <span className={`aug-fs-xs px-1.5 rounded border ${STATUS_STYLE[status] ?? STATUS_STYLE.draft}`}>
          {status}{metric.version ? ` v${metric.version}` : ""}
        </span>
        {metric.approved_by && status === "approved" && (
          <span className="aug-fs-xs text-zinc-500">approved by {metric.approved_by}</span>
        )}
        {metric.proposed_by && status === "proposed" && (
          <span className="aug-fs-xs text-zinc-500">proposed by {metric.proposed_by}</span>
        )}
      </div>
      {/* A3 — above the buttons on purpose. A report placed after the control that acts on it
          is read after the decision, which is the same as not being read. */}
      {wantReport && report && <div className="mb-2"><DefinitionReportBlock report={report} /></div>}
      {wantReport && reportErr && (
        <div className="aug-fs-xs text-amber-400 mb-2">
          The definition report is unavailable: {reportErr}
        </div>
      )}
      {actions.length > 0 && (
        <div className="flex items-center gap-2 flex-wrap">
          <input
            value={actor}
            onChange={(e) => setActor(e.target.value)}
            placeholder="actor (you / team)"
            className="text-xs bg-zinc-900 border border-zinc-700 rounded px-2 py-1 text-zinc-200 w-36 outline-none focus:border-zinc-500"
          />
          {actions.map(a => (
            <button
              key={a}
              disabled={!!busy}
              onClick={() => run(a)}
              className={`text-xs px-2 py-1 rounded border capitalize disabled:opacity-50 ${
                a === "approve" ? "border-emerald-500/40 text-emerald-400 hover:bg-emerald-500/10"
                : (a === "reject" || a === "deprecate") ? "border-red-500/40 text-red-400 hover:bg-red-500/10"
                : "border-amber-500/40 text-amber-400 hover:bg-amber-500/10"}`}
            >
              {busy === a ? "…" : a}
            </button>
          ))}
        </div>
      )}
      {err && <div className="aug-fs-xs text-red-400 mt-1.5">{err}</div>}
      {audit.length > 0 && (
        <div className="mt-2">
          <button onClick={() => setShowAudit(s => !s)} className="aug-fs-xs text-zinc-400 hover:text-zinc-200">
            {showAudit ? "▾" : "▸"} audit trail ({audit.length})
          </button>
          {showAudit && (
            <div className="mt-1 flex flex-col gap-0.5">
              {audit.map((a, i) => (
                <div key={i} className="aug-fs-xs text-zinc-500 font-mono">
                  {a.at.slice(0, 19).replace("T", " ")} · <span className="text-zinc-300">{a.actor}</span>{" "}
                  {a.action} <span className="text-zinc-600">{a.from}→{a.to}</span>{a.version ? ` v${a.version}` : ""}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Empty defaults ─────────────────────────────────────────────────────────────

const EMPTY_METRIC: Metric = {
  name: "", label: "", sql: "",
  tables: [], dimensions: [], filters: [],
  unit: null, caveats: null,
  target_value: null, warning_threshold: null, critical_threshold: null,
  target_period: null, benchmark_source: null,
  owner: null, freshness_sla: null, freshness_check_sql: null,
  quality_tests: [], lineage: [], wrong_usage_examples: [],
  approved_by: null, approved_at: null,
};

// ── Form state ─────────────────────────────────────────────────────────────────

interface FormState {
  name: string; label: string; sql: string;
  tables: string; dimensions: string; filters: string;
  unit: string; caveats: string;
  target_value: string; warning_threshold: string; critical_threshold: string;
  target_period: string; benchmark_source: string;
  // governance
  owner: string; freshness_sla: string; freshness_check_sql: string;
  quality_tests: string;   // newline-separated
  lineage: string;         // newline-separated
  wrong_usage_examples: string; // newline-separated
  approved_by: string; approved_at: string;
}

const EMPTY_FORM: FormState = {
  name: "", label: "", sql: "",
  tables: "", dimensions: "", filters: "",
  unit: "", caveats: "",
  target_value: "", warning_threshold: "", critical_threshold: "",
  target_period: "", benchmark_source: "",
  owner: "", freshness_sla: "", freshness_check_sql: "",
  quality_tests: "", lineage: "", wrong_usage_examples: "",
  approved_by: "", approved_at: "",
};

function parseList(val: string): string[] {
  return val.split(",").map((s) => s.trim()).filter(Boolean);
}
function parseLines(val: string): string[] {
  return val.split("\n").map((s) => s.trim()).filter(Boolean);
}
function joinList(arr: string[]): string { return arr.join(", "); }
function joinLines(arr: string[]): string { return arr.join("\n"); }
function parseOptFloat(s: string): number | null {
  const n = parseFloat(s.trim());
  return isNaN(n) ? null : n;
}

function metricToForm(m: Metric): FormState {
  return {
    name: m.name, label: m.label, sql: m.sql,
    tables: joinList(m.tables),
    dimensions: joinList(m.dimensions),
    filters: joinList(m.filters),
    unit: m.unit ?? "", caveats: m.caveats ?? "",
    target_value: m.target_value != null ? String(m.target_value) : "",
    warning_threshold: m.warning_threshold != null ? String(m.warning_threshold) : "",
    critical_threshold: m.critical_threshold != null ? String(m.critical_threshold) : "",
    target_period: m.target_period ?? "", benchmark_source: m.benchmark_source ?? "",
    owner: m.owner ?? "", freshness_sla: m.freshness_sla ?? "",
    freshness_check_sql: m.freshness_check_sql ?? "",
    quality_tests: joinLines(m.quality_tests),
    lineage: joinLines(m.lineage),
    wrong_usage_examples: joinLines(m.wrong_usage_examples),
    approved_by: m.approved_by ?? "", approved_at: m.approved_at ?? "",
  };
}

function formToMetric(f: FormState): Metric {
  return {
    name: f.name.trim(), label: f.label.trim(), sql: f.sql.trim(),
    tables: parseList(f.tables), dimensions: parseList(f.dimensions),
    filters: parseList(f.filters),
    unit: f.unit.trim() || null, caveats: f.caveats.trim() || null,
    target_value: parseOptFloat(f.target_value),
    warning_threshold: parseOptFloat(f.warning_threshold),
    critical_threshold: parseOptFloat(f.critical_threshold),
    target_period: f.target_period.trim() || null,
    benchmark_source: f.benchmark_source.trim() || null,
    owner: f.owner.trim() || null,
    freshness_sla: f.freshness_sla.trim() || null,
    freshness_check_sql: f.freshness_check_sql.trim() || null,
    quality_tests: parseLines(f.quality_tests),
    lineage: parseLines(f.lineage),
    wrong_usage_examples: parseLines(f.wrong_usage_examples),
    approved_by: f.approved_by.trim() || null,
    approved_at: f.approved_at.trim() || null,
  };
}

// ── Component ──────────────────────────────────────────────────────────────────

export function MetricsPanel({ connId }: { connId?: string }) {
  const [metrics, setMetrics] = useState<Metric[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);

  // validation / freshness state
  const [validating, setValidating] = useState(false);
  const [validationResult, setValidationResult] = useState<MetricValidationResult | null>(null);
  const [checkingFreshness, setCheckingFreshness] = useState(false);
  const [freshnessResult, setFreshnessResult] = useState<MetricFreshnessResult | null>(null);

  // The CATALOGUE is what this tab lists: every metric that applies to this connection,
  // not just the ones already in the registry. Most of what applies is not in the registry
  // — an industry package's recipe is role-bound until this connection binds those roles,
  // and the explorer's judgement lives on the business profile. Both are computed server
  // side and materialised only when someone edits one.
  const [rows, setRows] = useState<CatalogueMetric[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [expanded, setExpanded] = useState<string | null>(null);
  const [materialising, setMaterialising] = useState<string | null>(null);
  const [rowError, setRowError] = useState<Record<string, string>>({});

  const load = async () => {
    // `metrics` still holds the raw registry: the governance section and the duplicate-name
    // warning read it, and both are about what is STORED, not about what applies.
    try { setMetrics(await getMetrics(connId)); } catch {}
    if (!connId) { setRows([]); setCounts({}); return; }
    try {
      const cat = await getMetricCatalogue(connId);
      setRows(cat.metrics); setCounts(cat.counts);
    } catch { setRows([]); setCounts({}); }
  };

  useEffect(() => { load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [connId]);

  // Opening a row is the edit gesture. An already-editable row opens straight into the
  // editor; a computed one opens to its provenance with a Customise action, because a
  // recipe is copied before it is changed — editing it in place would rewrite a definition
  // shared by every connection that reads the same package.
  const toggleRow = (row: CatalogueMetric) => {
    if (expanded === row.name) { setExpanded(null); cancelForm(); return; }
    setExpanded(row.name);
    setRowError((prev) => ({ ...prev, [row.name]: "" }));
    const stored = metrics.find((m) => m.name === row.name);
    if (row.editable && stored) startEdit(stored);
    else { setAdding(false); setSelected(null); }
  };

  const customise = async (row: CatalogueMetric) => {
    if (!connId) return;
    setMaterialising(row.name);
    setRowError((prev) => ({ ...prev, [row.name]: "" }));
    try {
      const made = await materialiseMetric(connId, row.name);
      await load();
      startEdit(made);
      setExpanded(made.name);
    } catch (e: unknown) {
      setRowError((prev) => ({
        ...prev,
        [row.name]: e instanceof Error ? e.message : "Could not make this metric editable",
      }));
    } finally { setMaterialising(null); }
  };

  const startAdd = () => {
    setAdding(true); setSelected(null);
    setForm(EMPTY_FORM); setError("");
    setValidationResult(null); setFreshnessResult(null);
  };

  const startEdit = (m: Metric) => {
    setAdding(false); setSelected(m.name);
    setForm(metricToForm(m)); setError("");
    setValidationResult(null); setFreshnessResult(null);
  };

  const cancelForm = () => {
    setAdding(false); setSelected(null);
    setForm(EMPTY_FORM); setError("");
    setValidationResult(null); setFreshnessResult(null);
  };

  const handleSave = async () => {
    setError("");
    const metric = formToMetric(form);
    if (!metric.name) { setError("Name is required"); return; }
    if (!metric.label) { setError("Label is required"); return; }
    if (!metric.sql) { setError("SQL expression is required"); return; }
    setSaving(true);
    try {
      // Scope every write to the connection this tab is showing. Without it the request
      // fell back to the server's "*" default, so editing theLook's metric republished
      // its SQL — over `inventory_items` — to every connection, including ones with no
      // such table. A metric with no connection is a house default, and that is a
      // deliberate choice, not what an edit here means.
      const scoped = connId ? { ...metric, connection: connId } : metric;
      if (adding) { await createMetric(scoped); }
      else { await updateMetric(selected!, scoped); }
      await load();
      cancelForm();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally { setSaving(false); }
  };

  const handleDelete = async (m: Metric) => {
    setDeleting(m.name);
    try {
      // Pass the formula so only this grain is removed when a name has several
      // definitions — not every same-named row.
      await deleteMetric(m.name, m.sql);
      if (selected === m.name) cancelForm();
      await load();
    } catch {}
    finally { setDeleting(null); }
  };

  const handleValidate = async () => {
    if (!connId || !selected) return;
    setValidating(true); setValidationResult(null);
    try {
      setValidationResult(await validateMetric(selected, connId));
    } catch (e: unknown) {
      setValidationResult({
        metric: selected, passed: false, results: [],
        message: e instanceof Error ? e.message : "Validation failed",
      });
    } finally { setValidating(false); }
  };

  const handleFreshness = async () => {
    if (!connId || !selected) return;
    setCheckingFreshness(true); setFreshnessResult(null);
    try {
      setFreshnessResult(await getMetricFreshness(selected, connId));
    } catch (e: unknown) {
      setFreshnessResult({
        metric: selected, latest_data_at: null, sla: null, ok: false,
        message: e instanceof Error ? e.message : "Freshness check failed",
      });
    } finally { setCheckingFreshness(false); }
  };

  // A metric name is its identity (save_metric upserts by name), so two rows
  // sharing one is an unresolved conflict. The backend dedupes downstream
  // (most-recent wins) and logs a WARNING; this list reads the RAW catalog by
  // design so a human can see and fix it — surface the same signal right here.
  const nameCounts = metrics.reduce<Record<string, number>>((acc, m) => {
    acc[m.name] = (acc[m.name] ?? 0) + 1;
    return acc;
  }, {});

  const isEditing = adding || selected !== null;

  // The editor, unchanged. It used to be the right pane of a ResizableSplit; it now renders
  // INSIDE the expanded row, because this sub-tab is a table you open in place (asked for
  // 2026-09-18). Same state, same fields, same governance section.
  const editor = (
    <div className="min-w-0">
        {!isEditing && (
          <div className="h-full flex items-center justify-center text-zinc-500 text-sm">
            Select a metric to edit, or add a new one
          </div>
        )}

        {isEditing && (
          <div className="aug-metric-editor pb-8">
          <div className="flex flex-col gap-3 min-w-0">
            <h3 className="text-sm font-semibold text-zinc-300">
              {adding ? "New Metric" : `Edit — ${selected}`}
            </h3>

            {/* ── Core fields ─────────────────────────────────────────────── */}
            <Field label="Name (snake_case)" required>
              <input
                className={inputCls}
                placeholder="mrr"
                value={form.name}
                disabled={!adding}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
              />
            </Field>

            <Field label="Label" required>
              <input
                className={inputCls}
                placeholder="Monthly Recurring Revenue"
                value={form.label}
                onChange={(e) => setForm({ ...form, label: e.target.value })}
              />
            </Field>

            <Field label="SQL Expression" required hint="Aggregate expression — no SELECT keyword">
              <textarea
                className={`${inputCls} font-mono text-xs min-h-[72px] resize-y`}
                placeholder="SUM(amount) FILTER (WHERE status = 'active')"
                value={form.sql}
                onChange={(e) => setForm({ ...form, sql: e.target.value })}
              />
            </Field>

            <div className="grid grid-cols-2 gap-3">
              <Field label="Tables" hint="Comma-separated">
                <input
                  className={inputCls}
                  placeholder="subscriptions, payments"
                  value={form.tables}
                  onChange={(e) => setForm({ ...form, tables: e.target.value })}
                />
              </Field>
              <Field label="Unit">
                <input
                  className={inputCls}
                  placeholder="$ or % or days"
                  value={form.unit}
                  onChange={(e) => setForm({ ...form, unit: e.target.value })}
                />
              </Field>
            </div>

            <Field label="Dimensions" hint="Columns this metric can be sliced by, comma-separated">
              <input
                className={inputCls}
                placeholder="order_date, country, plan_type"
                value={form.dimensions}
                onChange={(e) => setForm({ ...form, dimensions: e.target.value })}
              />
            </Field>

            <Field label="Always-on Filters" hint="WHERE conditions always applied, comma-separated">
              <input
                className={inputCls}
                placeholder="is_test = false, deleted_at IS NULL"
                value={form.filters}
                onChange={(e) => setForm({ ...form, filters: e.target.value })}
              />
            </Field>

            <Field label="Caveats">
              <input
                className={inputCls}
                placeholder="Finance-approved. Excludes internal test accounts."
                value={form.caveats}
                onChange={(e) => setForm({ ...form, caveats: e.target.value })}
              />
            </Field>

            {/* ── Health Scorecard ─────────────────────────────────────────── */}
            <SectionHeader label="Health Scorecard" />
            <div className="grid grid-cols-3 gap-3">
              <Field label="Target value" hint="green">
                <input
                  className={inputCls} type="number" placeholder="e.g. 0.08"
                  value={form.target_value}
                  onChange={(e) => setForm({ ...form, target_value: e.target.value })}
                />
              </Field>
              <Field label="Warning ≥" hint="yellow">
                <input
                  className={inputCls} type="number" placeholder="e.g. 0.10"
                  value={form.warning_threshold}
                  onChange={(e) => setForm({ ...form, warning_threshold: e.target.value })}
                />
              </Field>
              <Field label="Critical ≥" hint="red">
                <input
                  className={inputCls} type="number" placeholder="e.g. 0.15"
                  value={form.critical_threshold}
                  onChange={(e) => setForm({ ...form, critical_threshold: e.target.value })}
                />
              </Field>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Target period">
                <input
                  className={inputCls} placeholder="monthly, quarterly, ytd"
                  value={form.target_period}
                  onChange={(e) => setForm({ ...form, target_period: e.target.value })}
                />
              </Field>
              <Field label="Benchmark source">
                <input
                  className={inputCls} placeholder="internal: FY2025 plan"
                  value={form.benchmark_source}
                  onChange={(e) => setForm({ ...form, benchmark_source: e.target.value })}
                />
              </Field>
            </div>

            {/* ── Governance (M21) ─────────────────────────────────────────── */}
            <SectionHeader label="Governance" />

            <div className="grid grid-cols-2 gap-3">
              <Field label="Owner">
                <input
                  className={inputCls} placeholder="Revenue team"
                  value={form.owner}
                  onChange={(e) => setForm({ ...form, owner: e.target.value })}
                />
              </Field>
              <Field label="Approved by">
                <input
                  className={inputCls} placeholder="Finance"
                  value={form.approved_by}
                  onChange={(e) => setForm({ ...form, approved_by: e.target.value })}
                />
              </Field>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <Field label="Freshness SLA" hint="human description">
                <input
                  className={inputCls} placeholder="daily by 6am UTC"
                  value={form.freshness_sla}
                  onChange={(e) => setForm({ ...form, freshness_sla: e.target.value })}
                />
              </Field>
              <Field label="Approved at" hint="YYYY-MM-DD">
                <input
                  className={inputCls} placeholder="2026-01-15"
                  value={form.approved_at}
                  onChange={(e) => setForm({ ...form, approved_at: e.target.value })}
                />
              </Field>
            </div>

            <Field label="Freshness check SQL" hint="must return a single timestamp">
              <textarea
                className={`${inputCls} font-mono text-xs min-h-[56px] resize-y`}
                placeholder="SELECT MAX(updated_at) FROM orders"
                value={form.freshness_check_sql}
                onChange={(e) => setForm({ ...form, freshness_check_sql: e.target.value })}
              />
            </Field>

            <Field label="Lineage" hint="one source per line">
              <textarea
                className={`${inputCls} text-xs min-h-[56px] resize-y`}
                placeholder={"orders table — raw Stripe charges\nrefunds table — Stripe refund events"}
                value={form.lineage}
                onChange={(e) => setForm({ ...form, lineage: e.target.value })}
              />
            </Field>

            <Field label="Quality tests" hint="one SQL assertion per line — must return a truthy scalar to pass">
              <textarea
                className={`${inputCls} font-mono text-xs min-h-[80px] resize-y`}
                placeholder={"SELECT COUNT(*) > 0 FROM orders\nSELECT SUM(amount) > 0 FROM orders WHERE status = 'paid'"}
                value={form.quality_tests}
                onChange={(e) => setForm({ ...form, quality_tests: e.target.value })}
              />
            </Field>

            <Field label="Anti-patterns (NEVER rules)" hint="one per line — injected as NEVER instructions for the LLM">
              <textarea
                className={`${inputCls} text-xs min-h-[56px] resize-y`}
                placeholder={"COUNT(refunds) / COUNT(orders) — ignores refund amounts\nSUM(amount) without status filter — includes cancelled orders"}
                value={form.wrong_usage_examples}
                onChange={(e) => setForm({ ...form, wrong_usage_examples: e.target.value })}
              />
            </Field>

            {/* ── Validation / freshness results ───────────────────────────── */}
            {validationResult && (
              <ValidationResultBlock result={validationResult} />
            )}
            {freshnessResult && (
              <FreshnessResultBlock result={freshnessResult} />
            )}

            {error && <p className="text-xs text-red-400">{error}</p>}

            {/* ── Action row ───────────────────────────────────────────────── */}
            <div className="flex flex-wrap gap-2 mt-1">
              <Button
                size="sm"
                onClick={handleSave}
                disabled={saving}
                className="bg-violet-600 hover:bg-violet-500 text-white"
              >
                {saving ? "Saving…" : adding ? "Create" : "Update"}
              </Button>
              <Button size="sm" variant="ghost" onClick={cancelForm} className="text-zinc-400">
                Cancel
              </Button>
              {!adding && connId && (
                <>
                  <Button
                    size="sm" variant="ghost"
                    onClick={handleValidate}
                    disabled={validating}
                    className="text-blue-400 hover:text-blue-300 border border-blue-500/30"
                  >
                    {validating ? "Running…" : "Validate now"}
                  </Button>
                  <Button
                    size="sm" variant="ghost"
                    onClick={handleFreshness}
                    disabled={checkingFreshness}
                    className="text-zinc-400 hover:text-zinc-300 border border-zinc-600"
                  >
                    {checkingFreshness ? "Checking…" : "Check freshness"}
                  </Button>
                </>
              )}
            </div>
          </div>

          {/* ── Governance lifecycle (B-8) — existing metrics only. Its own column beside the
                 fields (asked for 2026-09-25): the advisory reads while you edit, and the first
                 field keeps the top of the row instead of sitting under a report. Under 1100 px
                 it stacks back above the fields, as it always did. */}
          {!adding && (() => {
            const sm = metrics.find((m) => m.name === selected);
            return sm ? (
              <div className="aug-metric-governance">
                <GovernanceSection metric={sm} onChanged={load} />
                <DatesSection key={`${sm.name}:${sm.time_column ?? ""}:${sm.time_confirmed_by ?? ""}`}
                  metric={sm} onChanged={load} />
              </div>
            ) : null;
          })()}
          </div>
        )}
    </div>
  );

  return (
    <div className="flex flex-col gap-3 h-full overflow-y-auto pr-1">
      <CatalogueHeader counts={counts} connId={connId} onAdd={startAdd} />

      {adding && (
        <div className="rounded-md border border-violet-500/30 bg-violet-500/5 p-3">{editor}</div>
      )}

      {rows.length === 0 && !adding && (
        <p className="aug-text-ui text-zinc-500 mt-2">
          {connId
            ? "Nothing applies to this connection yet. The explorer proposes metrics as it profiles the data, and an industry package contributes its own once its roles are bound to this connection."
            : "Select a connection to see the metrics that apply to it."}
        </p>
      )}

      {rows.length > 0 && (
        <table className="w-full border-collapse">
          <thead>
            <tr className="border-b border-zinc-700 text-left">
              <Th className="w-[40%]">Metric</Th>
              <Th className="w-[13%]">Source</Th>
              <Th className="w-[12%]">Unit</Th>
              <Th className="w-[21%]">State</Th>
              <Th className="w-[14%]">Where it lives</Th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <MetricRow
                key={`${row.source}:${row.name}`}
                row={row}
                open={expanded === row.name}
                onToggle={() => toggleRow(row)}
                onCustomise={() => customise(row)}
                busy={materialising === row.name}
                error={rowError[row.name] ?? ""}
                duplicate={(nameCounts[row.name] ?? 0) > 1}
                editor={selected === row.name ? editor : null}
              />
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function Th({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <th className={`aug-fs-xs font-semibold text-zinc-500 uppercase tracking-wider pb-2 pr-3 ${className}`}>
      {children}
    </th>
  );
}


// ── Sub-components ─────────────────────────────────────────────────────────────

function SectionHeader({ label }: { label: string }) {
  return (
    <div className="pt-2 border-t border-zinc-700/50">
      <p className="aug-fs-xs font-semibold text-zinc-500 uppercase tracking-wider">{label}</p>
    </div>
  );
}

function ValidationResultBlock({ result }: { result: MetricValidationResult }) {
  return (
    <div className={`rounded-md border p-3 text-xs ${result.passed ? "border-emerald-500/30 bg-emerald-500/5" : "border-red-500/30 bg-red-500/5"}`}>
      <p className={`font-semibold mb-2 ${result.passed ? "text-emerald-400" : "text-red-400"}`}>
        {result.passed ? "✓ All tests passed" : "✗ Tests failed"} — {result.message}
      </p>
      {result.results.map((r, i) => (
        <div key={i} className="mb-1">
          <span className={r.passed ? "text-emerald-400" : "text-red-400"}>{r.passed ? "✓" : "✗"}</span>
          <span className="font-mono text-zinc-400 ml-1.5 break-all">{r.test_sql}</span>
          {r.error && <p className="text-red-300 mt-0.5 ml-4">{r.error}</p>}
        </div>
      ))}
      {result.results.length === 0 && (
        <p className="text-zinc-500">No quality tests defined for this metric.</p>
      )}
    </div>
  );
}

function FreshnessResultBlock({ result }: { result: MetricFreshnessResult }) {
  return (
    <div className={`rounded-md border p-3 text-xs ${result.ok ? "border-emerald-500/30 bg-emerald-500/5" : "border-amber-500/30 bg-amber-500/5"}`}>
      <p className={`font-semibold ${result.ok ? "text-emerald-400" : "text-amber-400"}`}>
        {result.ok ? "⏱ Freshness OK" : "⚠ Freshness issue"} — {result.message}
      </p>
      {result.sla && (
        <p className="text-zinc-400 mt-1">SLA: {result.sla}</p>
      )}
    </div>
  );
}

const inputCls =
  "w-full rounded-md border border-zinc-600 bg-zinc-800 px-3 py-1.5 text-sm text-zinc-200 placeholder:text-zinc-400 focus:outline-none focus:border-violet-500 transition-colors";

function Field({
  label, required, hint, children,
}: {
  label: string; required?: boolean; hint?: string; children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1">
      <label className="text-xs text-zinc-400">
        {label}
        {required && <span className="text-violet-400 ml-0.5">*</span>}
        {hint && <span className="text-zinc-500 ml-1">— {hint}</span>}
      </label>
      {children}
    </div>
  );
}


// ── The catalogue table ───────────────────────────────────────────────────────
// Three sources in one list. A row says where it came from and whether this connection can
// actually compute it, because "applicable" and "available" are different claims and a
// table that blurred them would be the confident-wrong report in miniature.

const SOURCE_STYLE: Record<string, { label: string; cls: string; title: string }> = {
  defined: {
    label: "Defined", cls: "border-emerald-500/40 bg-emerald-500/10 text-emerald-400",
    title: "A definition in your registry — edited here, and what the agents use.",
  },
  industry: {
    label: "Industry", cls: "border-sky-500/40 bg-sky-500/10 text-sky-400",
    title: "A recipe from the knowledge package for the industry set in Settings.",
  },
  explorer: {
    label: "Explorer", cls: "border-violet-500/40 bg-violet-500/10 text-violet-400",
    title: "Proposed by the explorer from this connection's own tables and columns.",
  },
};

const STATE_TEXT: Record<string, { label: string; cls: string; title: string }> = {
  defined: { label: "In use", cls: "text-zinc-300",
             title: "A stored definition. Its governance status is shown when you open it." },
  proposed: { label: "Proposed", cls: "text-zinc-400",
              title: "Computable here, but not yet a governed definition. Open it to customise." },
  needs_binding: { label: "Needs binding", cls: "text-amber-400",
                   title: "This recipe names roles this connection has not bound, so it cannot be computed here yet." },
  needs_formula: { label: "Needs a formula", cls: "text-amber-400",
                   title: "The columns are identified but no SQL was proposed. Open it and supply one." },
  // Distinct from "Needs a formula" on purpose. A formula WAS written and the build-time
  // audit refused to trust it, so the work is to fix what it names — often the connection
  // rather than the SQL. Every metric landing here is a statement about the connection.
  formula_rejected: { label: "Formula rejected", cls: "text-amber-400",
                      title: "A formula was proposed and the audit could not trust it, so it was dropped. Hover the row for the reason." },
};

function CatalogueHeader({ counts, connId, onAdd }:
    { counts: Record<string, number>; connId?: string; onAdd: () => void }) {
  const parts: string[] = [];
  if (counts.defined) parts.push(`${counts.defined} defined`);
  if (counts.industry) parts.push(`${counts.industry} from your industry`);
  if (counts.explorer) parts.push(`${counts.explorer} proposed by the explorer`);
  return (
    <div className="flex items-start justify-between gap-3">
      <div className="min-w-0">
        <div className="aug-fs-xs font-semibold text-zinc-400 uppercase tracking-wider">
          Metrics for this connection
        </div>
        <p className="aug-text-ui text-zinc-500 mt-1">
          {connId
            ? (parts.length
                ? `${counts.total} apply here — ${parts.join(", ")}. Open one to edit it.`
                : "")
            : "Select a connection."}
        </p>
      </div>
      <Button
        onClick={onAdd}
        className="shrink-0 bg-transparent text-violet-400 hover:text-violet-300 border border-transparent"
      >
        + Add
      </Button>
    </div>
  );
}

function MetricRow({ row, open, onToggle, onCustomise, busy, error, duplicate, editor }: {
  row: CatalogueMetric;
  open: boolean;
  onToggle: () => void;
  onCustomise: () => void;
  busy: boolean;
  error: string;
  duplicate: boolean;
  editor: React.ReactNode;
}) {
  const src = SOURCE_STYLE[row.source] ?? SOURCE_STYLE.defined;
  const st = STATE_TEXT[row.state] ?? STATE_TEXT.proposed;
  const where = row.tables.length ? row.tables.join(", ") : (row.pack_id || "—");
  return (
    <>
      <tr
        onClick={onToggle}
        className={`border-b border-zinc-800 cursor-pointer transition-colors ${
          open ? "bg-zinc-800/60" : "hover:bg-zinc-800/40"
        }`}
      >
        <td className="py-2 pr-3 align-top">
          <div className="flex items-start gap-1.5 min-w-0">
            <span className={`text-zinc-500 shrink-0 transition-transform ${open ? "rotate-90" : ""}`}>›</span>
            <div className="min-w-0">
              <div className="aug-text-ui font-medium text-zinc-200 truncate">{row.label}</div>
              <div className="aug-fs-xs text-zinc-500 font-mono truncate">{row.name}</div>
            </div>
            {duplicate && (
              <span className="aug-fs-xs text-amber-400 shrink-0" title="Two definitions share this name.">
                ⚠ dup
              </span>
            )}
          </div>
        </td>
        <td className="py-2 pr-3 align-top">
          <span className={`aug-fs-xs px-1 rounded border ${src.cls}`} title={src.title}>{src.label}</span>
        </td>
        <td className="py-2 pr-3 align-top aug-fs-xs text-zinc-400 truncate">{row.unit || "—"}</td>
        <td className="py-2 pr-3 align-top">
          <span className={`aug-fs-xs ${st.cls}`} title={row.reason || st.title}>{st.label}</span>
          {row.state === "defined" && row.status ? (
            <span className="aug-fs-xs text-zinc-500"> · {row.status}</span>
          ) : null}
        </td>
        <td className="py-2 pr-3 align-top aug-fs-xs text-zinc-500 font-mono truncate" title={where}>{where}</td>
      </tr>

      {open && (
        <tr className="border-b border-zinc-800 bg-zinc-900/40">
          <td colSpan={5} className="px-3 py-3">
            {editor ?? (
              <MetricProvenance row={row} onCustomise={onCustomise} busy={busy} error={error} />
            )}
          </td>
        </tr>
      )}
    </>
  );
}

/** What a computed row shows before it is copied: what it means, and what it would take. */
function MetricProvenance({ row, onCustomise, busy, error }: {
  row: CatalogueMetric; onCustomise: () => void; busy: boolean; error: string;
}) {
  const blocked = row.state === "needs_binding";
  return (
    <div className="flex flex-col gap-3 max-w-3xl">
      {row.definition && <p className="aug-text-ui text-zinc-300">{row.definition}</p>}
      {row.why_it_matters && <p className="aug-text-ui text-zinc-400">{row.why_it_matters}</p>}

      {row.sql ? (
        <div>
          <SectionHeader label="Formula" />
          <pre className="aug-fs-xs font-mono text-zinc-300 whitespace-pre-wrap bg-zinc-900 rounded p-2 border border-zinc-800">
            {row.sql}
          </pre>
        </div>
      ) : (
        <p className="aug-text-ui text-amber-400">
          No formula was proposed for this one — open it after customising and supply the SQL.
        </p>
      )}

      {row.grain && <p className="aug-fs-xs text-zinc-500">Grain — {row.grain}</p>}

      {blocked && (
        <p className="aug-text-ui text-amber-400">
          {`This connection has not bound ${row.missing_roles.join(", ") || "the roles"} that `
            + `${row.label} is defined over, so it cannot be computed here yet. Its formula `
            + `still names roles rather than your columns.`}
        </p>
      )}

      {row.sane_range && (row.sane_range.min != null || row.sane_range.max != null) && (
        <div>
          <SectionHeader label="Published range" />
          <p className="aug-fs-xs text-zinc-400">
            {row.sane_range.min} – {row.sane_range.max}
            {row.sane_range.basis ? ` · ${row.sane_range.basis}` : ""}
          </p>
          <p className="aug-fs-xs text-zinc-500 mt-1">
            Published for the population above — not a measurement of your data.
          </p>
        </div>
      )}

      {row.anti_patterns.length > 0 && (
        <div>
          <SectionHeader label="Never" />
          <ul className="aug-fs-xs text-zinc-400 list-disc pl-4 flex flex-col gap-1">
            {row.anti_patterns.map((a, i) => <li key={i}>{a}</li>)}
          </ul>
        </div>
      )}

      {error && <p className="aug-text-ui text-red-400">{error}</p>}

      <div className="flex items-center gap-2">
        <Button
          onClick={onCustomise}
          disabled={busy || blocked}
          className="bg-violet-600 hover:bg-violet-500 text-white disabled:opacity-40"
        >
          {busy ? "Copying…" : "Customise for this connection"}
        </Button>
        <span className="aug-fs-xs text-zinc-500">
          {blocked
            ? "Bind the roles first."
            : "Takes a copy scoped to this connection, as a draft. The original is untouched."}
        </span>
      </div>
    </div>
  );
}
