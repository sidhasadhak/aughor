"use client";

import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  createMetric,
  deleteMetric,
  getMetrics,
  updateMetric,
  type Metric,
} from "@/lib/api";

const EMPTY_METRIC: Metric = {
  name: "",
  label: "",
  sql: "",
  tables: [],
  dimensions: [],
  filters: [],
  unit: null,
  caveats: null,
};

function parseList(val: string): string[] {
  return val.split(",").map((s) => s.trim()).filter(Boolean);
}

function joinList(arr: string[]): string {
  return arr.join(", ");
}

interface FormState {
  name: string;
  label: string;
  sql: string;
  tables: string;
  dimensions: string;
  filters: string;
  unit: string;
  caveats: string;
}

function metricToForm(m: Metric): FormState {
  return {
    name: m.name,
    label: m.label,
    sql: m.sql,
    tables: joinList(m.tables),
    dimensions: joinList(m.dimensions),
    filters: joinList(m.filters),
    unit: m.unit ?? "",
    caveats: m.caveats ?? "",
  };
}

function formToMetric(f: FormState): Metric {
  return {
    name: f.name.trim(),
    label: f.label.trim(),
    sql: f.sql.trim(),
    tables: parseList(f.tables),
    dimensions: parseList(f.dimensions),
    filters: parseList(f.filters),
    unit: f.unit.trim() || null,
    caveats: f.caveats.trim() || null,
  };
}

const EMPTY_FORM: FormState = {
  name: "", label: "", sql: "", tables: "", dimensions: "", filters: "", unit: "", caveats: "",
};

export function MetricsPanel() {
  const [metrics, setMetrics] = useState<Metric[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);

  const load = async () => {
    try { setMetrics(await getMetrics()); } catch {}
  };

  useEffect(() => { load(); }, []);

  const selectedMetric = metrics.find((m) => m.name === selected) ?? null;

  const startAdd = () => {
    setAdding(true);
    setSelected(null);
    setForm(EMPTY_FORM);
    setError("");
  };

  const startEdit = (m: Metric) => {
    setAdding(false);
    setSelected(m.name);
    setForm(metricToForm(m));
    setError("");
  };

  const cancelForm = () => {
    setAdding(false);
    setSelected(null);
    setForm(EMPTY_FORM);
    setError("");
  };

  const handleSave = async () => {
    setError("");
    const metric = formToMetric(form);
    if (!metric.name) { setError("Name is required"); return; }
    if (!metric.label) { setError("Label is required"); return; }
    if (!metric.sql) { setError("SQL expression is required"); return; }
    setSaving(true);
    try {
      if (adding) {
        await createMetric(metric);
      } else {
        await updateMetric(selected!, metric);
      }
      await load();
      cancelForm();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (name: string) => {
    setDeleting(name);
    try {
      await deleteMetric(name);
      if (selected === name) cancelForm();
      await load();
    } catch {}
    finally { setDeleting(null); }
  };

  const isEditing = adding || selected !== null;

  return (
    <div className="flex h-full gap-4">
      {/* Left: metric list */}
      <div className="w-64 flex-shrink-0 flex flex-col gap-2">
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
          {metrics.map((m) => (
            <div
              key={m.name}
              onClick={() => startEdit(m)}
              className={`group flex items-start justify-between rounded-md px-3 py-2 cursor-pointer transition-colors ${
                selected === m.name
                  ? "bg-violet-500/15 border border-violet-500/30"
                  : "hover:bg-zinc-800/60 border border-transparent"
              }`}
            >
              <div className="min-w-0">
                <div className="text-sm font-medium text-zinc-200 truncate">{m.label}</div>
                <div className="text-xs text-zinc-500 font-mono truncate">{m.name}</div>
              </div>
              <div className="flex items-center gap-1 ml-2 flex-shrink-0">
                {m.unit && (
                  <Badge className="text-[10px] px-1 py-0 border-zinc-700 bg-zinc-800 text-zinc-400">
                    {m.unit}
                  </Badge>
                )}
                <button
                  onClick={(e) => { e.stopPropagation(); handleDelete(m.name); }}
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

      {/* Right: detail / form */}
      <div className="flex-1 min-w-0">
        {!isEditing && !selectedMetric && (
          <div className="h-full flex items-center justify-center text-zinc-600 text-sm">
            Select a metric to edit, or add a new one
          </div>
        )}

        {isEditing && (
          <div className="flex flex-col gap-3 max-w-xl">
            <h3 className="text-sm font-semibold text-zinc-300">
              {adding ? "New Metric" : `Edit — ${selected}`}
            </h3>

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

            <Field label="SQL Expression" required hint="The exact aggregate expression — no SELECT keyword">
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

            {error && <p className="text-xs text-red-400">{error}</p>}

            <div className="flex gap-2 mt-1">
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
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const inputCls =
  "w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-1.5 text-sm text-zinc-200 placeholder:text-zinc-600 focus:outline-none focus:border-violet-500 transition-colors";

function Field({
  label,
  required,
  hint,
  children,
}: {
  label: string;
  required?: boolean;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1">
      <label className="text-xs text-zinc-400">
        {label}
        {required && <span className="text-violet-400 ml-0.5">*</span>}
        {hint && <span className="text-zinc-600 ml-1">— {hint}</span>}
      </label>
      {children}
    </div>
  );
}
