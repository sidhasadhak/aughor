"use client";

import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ResizableSplit } from "@/components/ResizableSplit";
import {
  createMetric,
  deleteMetric,
  getMetrics,
  getMetricFreshness,
  updateMetric,
  validateMetric,
  type Metric,
  type MetricValidationResult,
  type MetricFreshnessResult,
} from "@/lib/api";

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

  const load = async () => {
    try { setMetrics(await getMetrics()); } catch {}
  };

  useEffect(() => { load(); }, []);

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
      if (adding) { await createMetric(metric); }
      else { await updateMetric(selected!, metric); }
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

  return (
    <ResizableSplit storageKey="metrics" initial={272} min={200} max={440} className="h-full"
      left={
      <div className="flex flex-col gap-2 h-full overflow-y-auto pr-2">
        <div className="flex items-center justify-between mb-1">
          <span className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">Metrics</span>
          <button
            onClick={startAdd}
            className="text-xs text-violet-400 hover:text-violet-300 transition-colors"
          >
            + Add
          </button>
        </div>

        {metrics.length === 0 && !adding && (
          <p className="text-xs text-zinc-500 mt-2">
            No metrics defined yet. Add a KPI formula to ensure consistent SQL across all investigations.
          </p>
        )}

        <div className="flex flex-col gap-1">
          {metrics.map((m, i) => (
            <div
              key={`${m.name}:${i}`}
              onClick={() => startEdit(m)}
              className={`group flex items-start justify-between rounded-md px-3 py-2 cursor-pointer transition-colors ${
                selected === m.name
                  ? "bg-violet-500/15 border border-violet-500/30"
                  : "hover:bg-zinc-700/60 border border-transparent"
              }`}
            >
              <div className="min-w-0">
                <div className="flex items-center gap-1.5">
                  <span className="text-sm font-medium text-zinc-200 truncate">{m.label}</span>
                  {m.approved_by && (
                    <span className="text-[10px] text-emerald-400/80">✓</span>
                  )}
                  {nameCounts[m.name] > 1 && (
                    <span
                      className="text-[10px] text-amber-400 shrink-0"
                      title={`Duplicate name "${m.name}" — two definitions share this identity. Downstream only one is used (most-recent wins). Delete removes ALL copies (then re-add one canonical definition), or rename/scope one here.`}
                    >
                      ⚠ dup
                    </span>
                  )}
                </div>
                <div className="text-xs text-zinc-500 font-mono truncate">{m.name}</div>
                {m.owner && (
                  <div className="text-[11px] text-zinc-500 truncate">{m.owner}</div>
                )}
              </div>
              <div className="flex items-center gap-1 ml-2 flex-shrink-0">
                {m.target_value != null && (
                  <span className="w-[5px] h-[5px] rounded-full bg-emerald-400/60 shrink-0" title="Has target" />
                )}
                {m.quality_tests.length > 0 && (
                  <span className="w-[5px] h-[5px] rounded-full bg-blue-400/60 shrink-0" title="Has quality tests" />
                )}
                {m.unit && (
                  <Badge className="text-[11px] px-1 py-0 border-zinc-600 bg-zinc-800 text-zinc-400">
                    {m.unit}
                  </Badge>
                )}
                <button
                  onClick={(e) => { e.stopPropagation(); handleDelete(m); }}
                  className="opacity-0 group-hover:opacity-100 text-zinc-500 hover:text-red-400 text-xs transition-all ml-1"
                  disabled={deleting === m.name}
                >
                  {deleting === m.name ? "…" : "✕"}
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>
      }
      right={
      <div className="flex-1 min-w-0 overflow-y-auto pl-2">
        {!isEditing && (
          <div className="h-full flex items-center justify-center text-zinc-500 text-sm">
            Select a metric to edit, or add a new one
          </div>
        )}

        {isEditing && (
          <div className="flex flex-col gap-3 max-w-xl pb-8">
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
        )}
      </div>
      }
    />
  );
}

// ── Sub-components ─────────────────────────────────────────────────────────────

function SectionHeader({ label }: { label: string }) {
  return (
    <div className="pt-2 border-t border-zinc-700/50">
      <p className="text-[11px] font-semibold text-zinc-500 uppercase tracking-wider">{label}</p>
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
