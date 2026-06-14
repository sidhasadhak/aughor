"use client";
import React, { useEffect, useState, useCallback } from "react";
import {
  MonitorDef,
  MonitorAlert,
  getMonitors,
  createMonitor,
  updateMonitor,
  deleteMonitor,
  triggerMonitor,
  getAllAlerts,
  acknowledgeAlert,
  getMetrics,
  Metric,
} from "@/lib/api";

// ── Types ─────────────────────────────────────────────────────────────────────

type AlertOn = MonitorDef["alert_on"];
type View = "list" | "alerts" | "form";

const ALERT_TYPES: { value: AlertOn; label: string; desc: string }[] = [
  { value: "threshold_cross", label: "Threshold", desc: "Alert when value crosses a boundary" },
  { value: "anomaly",         label: "Anomaly",   desc: "Statistical deviation from rolling mean" },
  { value: "trend_reversal",  label: "Trend reversal", desc: "Direction of change flips" },
  { value: "segment_drift",   label: "Segment drift",  desc: "Distribution shifts across a dimension" },
  { value: "data_freshness",  label: "Data freshness", desc: "Table hasn't updated within SLA" },
  { value: "any_change",      label: "Any change",     desc: "Fire on every value change" },
];

const CRON_PRESETS = [
  { label: "Hourly",   cron: "0 * * * *" },
  { label: "Every 6h", cron: "0 */6 * * *" },
  { label: "Daily",    cron: "0 9 * * *" },
  { label: "Weekly",   cron: "0 9 * * 1" },
  { label: "Custom",   cron: "" },
];

const SEVERITY_COLOR: Record<string, string> = {
  critical: "var(--r2)",
  warning:  "var(--chart-threshold-warn, #f59e0b)",
  info:     "var(--blue3)",
};

// ── Blank form state ──────────────────────────────────────────────────────────

function blankForm(connId: string): Partial<MonitorDef> & { conn_id: string; name: string } {
  return {
    conn_id: connId,
    name: "",
    metric_name: null,
    custom_sql: null,
    check_cron: "0 * * * *",
    alert_on: "threshold_cross",
    warning_threshold: null,
    critical_threshold: null,
    threshold_direction: "below",
    sigma_threshold: 2.5,
    history_days: 30,
    dimension_column: null,
    freshness_table: null,
    freshness_column: "updated_at",
    freshness_sla_hours: 24,
    notification_channel: "in_app",
    enabled: true,
  };
}

// ── Main component ────────────────────────────────────────────────────────────

interface Props {
  connId?: string;
  workspaceId?: string;
}

export function MonitorsPanel({ connId, workspaceId }: Props) {
  const [view, setView]           = useState<View>("list");
  const [monitors, setMonitors]   = useState<MonitorDef[]>([]);
  const [alerts, setAlerts]       = useState<MonitorAlert[]>([]);
  const [metrics, setMetrics]     = useState<Metric[]>([]);
  const [loading, setLoading]     = useState(false);
  const [editTarget, setEditTarget] = useState<MonitorDef | null>(null);
  const [form, setForm]           = useState<Partial<MonitorDef> & { conn_id: string; name: string }>(blankForm(connId ?? ""));
  const [cronPreset, setCronPreset] = useState("0 * * * *");
  const [isCustomCron, setIsCustomCron] = useState(false);
  const [metricSource, setMetricSource] = useState<"catalog" | "sql">("catalog");
  const [runResult, setRunResult] = useState<Record<string, string>>({});
  const [saving, setSaving]       = useState(false);
  const [error, setError]         = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [ms, as, mets] = await Promise.all([
        getMonitors(connId, workspaceId),
        getAllAlerts(connId, 100, workspaceId),
        getMetrics().catch(() => []),
      ]);
      setMonitors(ms);
      setAlerts(as);
      setMetrics(mets);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [connId, workspaceId]);

  useEffect(() => { load(); }, [load]);

  // ── Form helpers ─────────────────────────────────────────────────────────────

  function openCreate() {
    setEditTarget(null);
    setForm(blankForm(connId ?? ""));
    setCronPreset("0 * * * *");
    setIsCustomCron(false);
    setMetricSource("catalog");
    setError(null);
    setView("form");
  }

  function openEdit(m: MonitorDef) {
    setEditTarget(m);
    setForm({ ...m });
    const preset = CRON_PRESETS.find(p => p.cron === m.check_cron && p.label !== "Custom");
    setCronPreset(m.check_cron);
    setIsCustomCron(!preset);
    setMetricSource(m.custom_sql ? "sql" : "catalog");
    setError(null);
    setView("form");
  }

  function setField<K extends keyof MonitorDef>(key: K, val: MonitorDef[K]) {
    setForm(f => ({ ...f, [key]: val }));
  }

  async function save() {
    if (!form.name.trim()) { setError("Name is required"); return; }
    if (!form.conn_id)     { setError("Connection ID is required"); return; }
    setSaving(true);
    setError(null);
    try {
      if (editTarget) {
        await updateMonitor(editTarget.id, form);
      } else {
        await createMonitor(form as MonitorDef & { conn_id: string; name: string });
      }
      await load();
      setView("list");
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  }

  async function remove(id: string) {
    if (!confirm("Delete this monitor?")) return;
    await deleteMonitor(id).catch(() => {});
    await load();
  }

  async function runNow(id: string) {
    setRunResult(r => ({ ...r, [id]: "running…" }));
    try {
      const res = await triggerMonitor(id);
      const msg = "fired" in res && res.fired === false
        ? "No condition met"
        : `Fired: ${(res as MonitorAlert).severity} — ${(res as MonitorAlert).message}`;
      setRunResult(r => ({ ...r, [id]: msg }));
      setTimeout(() => setRunResult(r => { const n = { ...r }; delete n[id]; return n; }), 6000);
    } catch {
      setRunResult(r => ({ ...r, [id]: "Error" }));
    }
  }

  async function toggle(m: MonitorDef) {
    await updateMonitor(m.id, { enabled: !m.enabled }).catch(() => {});
    await load();
  }

  async function ack(alertId: string) {
    await acknowledgeAlert(alertId).catch(() => {});
    setAlerts(as => as.map(a => a.id === alertId ? { ...a, acknowledged: true } : a));
  }

  // ── Cron picker ───────────────────────────────────────────────────────────────

  function handleCronPreset(cron: string) {
    if (cron === "") {
      setIsCustomCron(true);
    } else {
      setIsCustomCron(false);
      setCronPreset(cron);
      setField("check_cron", cron);
    }
  }

  // ── Alert count badge ─────────────────────────────────────────────────────────

  const unackedCount = alerts.filter(a => !a.acknowledged).length;

  // ── Render ────────────────────────────────────────────────────────────────────

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", background: "var(--bg-0)", color: "var(--t1)" }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "16px 20px 0", borderBottom: "1px solid var(--bg-3)" }}>
        <div style={{ display: "flex", gap: 2 }}>
          {(["list", "alerts", ...(view === "form" ? ["form"] : [])] as const).map(v => (
            <button
              key={v}
              onClick={() => view !== "form" && setView(v as View)}
              style={{
                padding: "6px 14px",
                background: view === v ? "var(--blue3)" : "transparent",
                color: view === v ? "#fff" : "var(--t3)",
                border: "none",
                borderRadius: "4px 4px 0 0",
                cursor: "pointer",
                fontSize: 12,
                fontWeight: 500,
                position: "relative",
              }}
            >
              {v === "list"   ? "Monitors" :
               v === "alerts" ? <>Alerts {unackedCount > 0 && <span style={{ marginLeft: 4, background: "var(--r2)", color: "#fff", borderRadius: 8, padding: "1px 5px", fontSize: 10 }}>{unackedCount}</span>}</> :
               "Configure"}
            </button>
          ))}
        </div>
        <div style={{ flex: 1 }} />
        {view === "list" && (
          <button className="aug-btn" onClick={openCreate} style={{ fontSize: 12, padding: "5px 12px" }}>
            + New monitor
          </button>
        )}
        {view === "form" && (
          <button onClick={() => setView("list")} style={{ background: "none", border: "none", color: "var(--t3)", cursor: "pointer", fontSize: 12 }}>
            ← Back
          </button>
        )}
      </div>

      {/* Body */}
      <div style={{ flex: 1, overflowY: "auto", padding: 20 }}>
        {loading && <p style={{ color: "var(--t3)", fontSize: 13 }}>Loading…</p>}
        {error && <p style={{ color: "var(--r2)", fontSize: 13, marginBottom: 12 }}>{error}</p>}

        {/* ── Monitor list ── */}
        {view === "list" && !loading && (
          monitors.length === 0
            ? <EmptyState onAdd={openCreate} />
            : <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                {monitors.map(m => (
                  <MonitorCard
                    key={m.id}
                    monitor={m}
                    runResult={runResult[m.id]}
                    alerts={alerts.filter(a => a.monitor_id === m.id)}
                    onEdit={() => openEdit(m)}
                    onDelete={() => remove(m.id)}
                    onRun={() => runNow(m.id)}
                    onToggle={() => toggle(m)}
                  />
                ))}
              </div>
        )}

        {/* ── Alert inbox ── */}
        {view === "alerts" && !loading && (
          alerts.length === 0
            ? <p style={{ color: "var(--t3)", fontSize: 13 }}>No alerts yet.</p>
            : <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {alerts.map(a => (
                  <AlertRow key={a.id} alert={a} onAck={() => ack(a.id)} />
                ))}
              </div>
        )}

        {/* ── Create / edit form ── */}
        {view === "form" && (
          <MonitorForm
            form={form}
            setField={setField}
            metricSource={metricSource}
            setMetricSource={setMetricSource}
            metrics={metrics}
            cronPreset={cronPreset}
            isCustomCron={isCustomCron}
            onCronPreset={handleCronPreset}
            onCustomCronChange={v => { setField("check_cron", v); setCronPreset(v); }}
            saving={saving}
            error={error}
            isEdit={!!editTarget}
            onSave={save}
            onCancel={() => setView("list")}
          />
        )}
      </div>
    </div>
  );
}

// ── Monitor card ──────────────────────────────────────────────────────────────

function MonitorCard({
  monitor, runResult, alerts, onEdit, onDelete, onRun, onToggle,
}: {
  monitor: MonitorDef;
  runResult?: string;
  alerts: MonitorAlert[];
  onEdit: () => void;
  onDelete: () => void;
  onRun: () => void;
  onToggle: () => void;
}) {
  const lastAlert = alerts[0];
  const unacked = alerts.filter(a => !a.acknowledged).length;

  return (
    <div style={{
      background: "var(--bg-1)",
      border: "1px solid var(--bg-3)",
      borderRadius: 6,
      padding: "12px 16px",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        {/* Toggle */}
        <button
          onClick={onToggle}
          title={monitor.enabled ? "Disable" : "Enable"}
          style={{
            width: 32, height: 18, borderRadius: 9,
            background: monitor.enabled ? "var(--blue3)" : "var(--bg-3)",
            border: "none", cursor: "pointer", position: "relative", flexShrink: 0,
          }}
        >
          <span style={{
            position: "absolute", top: 3, left: monitor.enabled ? 16 : 3,
            width: 12, height: 12, borderRadius: "50%",
            background: "#fff", transition: "left .15s",
          }} />
        </button>

        {/* Name + type */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontWeight: 600, fontSize: 13, color: "var(--t1)" }}>{monitor.name}</span>
            <TypeBadge type={monitor.alert_on} />
            {unacked > 0 && (
              <span style={{ background: "var(--r2)", color: "#fff", borderRadius: 8, padding: "1px 6px", fontSize: 10 }}>
                {unacked} alert{unacked > 1 ? "s" : ""}
              </span>
            )}
          </div>
          <div style={{ fontSize: 11, color: "var(--t3)", marginTop: 2 }}>
            {monitor.metric_name ?? "Custom SQL"} · {cronLabel(monitor.check_cron)}
            {lastAlert && (
              <span style={{ marginLeft: 8, color: SEVERITY_COLOR[lastAlert.severity] ?? "var(--t3)" }}>
                · last fired {relTime(lastAlert.triggered_at)}
              </span>
            )}
          </div>
        </div>

        {/* Actions */}
        <div style={{ display: "flex", gap: 6 }}>
          <button onClick={onRun} className="aug-btn" style={{ fontSize: 11, padding: "3px 9px", opacity: 0.85 }}>
            Run now
          </button>
          <button onClick={onEdit} style={ghostBtn}>Edit</button>
          <button onClick={onDelete} style={{ ...ghostBtn, color: "var(--r2)" }}>Delete</button>
        </div>
      </div>

      {runResult && (
        <div style={{ marginTop: 8, fontSize: 11, color: "var(--t3)", paddingLeft: 42 }}>
          {runResult}
        </div>
      )}
    </div>
  );
}

// ── Alert row ─────────────────────────────────────────────────────────────────

function AlertRow({ alert, onAck }: { alert: MonitorAlert; onAck: () => void }) {
  return (
    <div style={{
      display: "flex", alignItems: "flex-start", gap: 12,
      background: alert.acknowledged ? "var(--bg-1)" : "var(--bg-2)",
      border: `1px solid ${alert.acknowledged ? "var(--bg-3)" : SEVERITY_COLOR[alert.severity] ?? "var(--bg-3)"}`,
      borderRadius: 6, padding: "10px 14px",
      opacity: alert.acknowledged ? 0.6 : 1,
    }}>
      <span style={{
        fontSize: 10, fontWeight: 700, padding: "2px 7px", borderRadius: 4,
        background: SEVERITY_COLOR[alert.severity] ?? "var(--bg-3)", color: "#fff",
        textTransform: "uppercase", flexShrink: 0, marginTop: 1,
      }}>
        {alert.severity}
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 500, color: "var(--t1)" }}>{alert.monitor_name}</div>
        <div style={{ fontSize: 12, color: "var(--t2)", marginTop: 2 }}>{alert.message}</div>
        {alert.current_value != null && (
          <div style={{ fontSize: 11, color: "var(--t3)", marginTop: 4 }}>
            Value: <strong>{alert.current_value}</strong>
            {alert.previous_value != null && <> (prev: {alert.previous_value})</>}
            {alert.threshold != null && <> · threshold: {alert.threshold}</>}
          </div>
        )}
        <div style={{ fontSize: 10, color: "var(--t3)", marginTop: 4 }}>{relTime(alert.triggered_at)}</div>
      </div>
      {!alert.acknowledged && (
        <button onClick={onAck} style={ghostBtn}>Ack</button>
      )}
    </div>
  );
}

// ── Monitor form ──────────────────────────────────────────────────────────────

function MonitorForm({
  form, setField, metricSource, setMetricSource, metrics,
  cronPreset, isCustomCron, onCronPreset, onCustomCronChange,
  saving, error, isEdit, onSave, onCancel,
}: {
  form: Partial<MonitorDef> & { conn_id: string; name: string };
  setField: <K extends keyof MonitorDef>(k: K, v: MonitorDef[K]) => void;
  metricSource: "catalog" | "sql";
  setMetricSource: (s: "catalog" | "sql") => void;
  metrics: Metric[];
  cronPreset: string;
  isCustomCron: boolean;
  onCronPreset: (cron: string) => void;
  onCustomCronChange: (v: string) => void;
  saving: boolean;
  error: string | null;
  isEdit: boolean;
  onSave: () => void;
  onCancel: () => void;
}) {
  const alertOn = form.alert_on ?? "threshold_cross";

  return (
    <div style={{ maxWidth: 560, display: "flex", flexDirection: "column", gap: 20 }}>
      <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, color: "var(--t1)" }}>
        {isEdit ? "Edit monitor" : "New monitor"}
      </h3>

      {/* Name */}
      <Field label="Name">
        <input
          className="aug-input"
          value={form.name}
          onChange={e => setField("name", e.target.value as any)}
          placeholder="e.g. Daily revenue drop alert"
          style={{ width: "100%" }}
        />
      </Field>

      {/* Metric source */}
      <Field label="Metric">
        <div style={{ display: "flex", gap: 6, marginBottom: 8 }}>
          {(["catalog", "sql"] as const).map(s => (
            <button key={s} onClick={() => setMetricSource(s)}
              style={{ ...segBtn, background: metricSource === s ? "var(--blue3)" : "var(--bg-2)", color: metricSource === s ? "#fff" : "var(--t2)" }}>
              {s === "catalog" ? "From catalog" : "Custom SQL"}
            </button>
          ))}
        </div>
        {metricSource === "catalog" ? (
          <select className="aug-input" value={form.metric_name ?? ""} onChange={e => setField("metric_name", e.target.value as any)} style={{ width: "100%" }}>
            <option value="">Select a metric…</option>
            {metrics.map(m => <option key={m.name} value={m.name}>{m.label ?? m.name}</option>)}
          </select>
        ) : (
          <textarea
            className="aug-input"
            rows={3}
            value={form.custom_sql ?? ""}
            onChange={e => setField("custom_sql", e.target.value as any)}
            placeholder="SELECT SUM(revenue) FROM orders WHERE date = CURRENT_DATE"
            style={{ width: "100%", fontFamily: "var(--font-mono)", fontSize: 12, resize: "vertical" }}
          />
        )}
      </Field>

      {/* Alert type */}
      <Field label="Alert condition">
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
          {ALERT_TYPES.map(at => (
            <button key={at.value} onClick={() => setField("alert_on", at.value)}
              style={{
                ...segBtn,
                background: alertOn === at.value ? "var(--vio3, #6366f1)" : "var(--bg-2)",
                color: alertOn === at.value ? "#fff" : "var(--t2)",
                flexDirection: "column", alignItems: "flex-start", padding: "8px 10px", gap: 2,
              }}>
              <span style={{ fontWeight: 600, fontSize: 12 }}>{at.label}</span>
              <span style={{ fontSize: 10, opacity: 0.75, textAlign: "left" }}>{at.desc}</span>
            </button>
          ))}
        </div>
      </Field>

      {/* Conditional fields */}
      {alertOn === "threshold_cross" && (
        <>
          <div style={{ display: "flex", gap: 12 }}>
            <Field label="Warning threshold" style={{ flex: 1 }}>
              <input className="aug-input" type="number" value={form.warning_threshold ?? ""}
                onChange={e => setField("warning_threshold", e.target.value ? Number(e.target.value) as any : null as any)}
                placeholder="e.g. 10000" style={{ width: "100%" }} />
            </Field>
            <Field label="Critical threshold" style={{ flex: 1 }}>
              <input className="aug-input" type="number" value={form.critical_threshold ?? ""}
                onChange={e => setField("critical_threshold", e.target.value ? Number(e.target.value) as any : null as any)}
                placeholder="e.g. 8000" style={{ width: "100%" }} />
            </Field>
          </div>
          <Field label="Direction">
            <div style={{ display: "flex", gap: 6 }}>
              {(["below", "above"] as const).map(d => (
                <button key={d} onClick={() => setField("threshold_direction", d)}
                  style={{ ...segBtn, background: form.threshold_direction === d ? "var(--blue3)" : "var(--bg-2)", color: form.threshold_direction === d ? "#fff" : "var(--t2)" }}>
                  {d === "below" ? "Alert when below (e.g. revenue)" : "Alert when above (e.g. error rate)"}
                </button>
              ))}
            </div>
          </Field>
        </>
      )}

      {(alertOn === "anomaly" || alertOn === "trend_reversal") && (
        <div style={{ display: "flex", gap: 12 }}>
          {alertOn === "anomaly" && (
            <Field label={`Sigma threshold (${form.sigma_threshold ?? 2.5}σ)`} style={{ flex: 1 }}>
              <input type="range" min={1} max={5} step={0.5}
                value={form.sigma_threshold ?? 2.5}
                onChange={e => setField("sigma_threshold", Number(e.target.value) as any)}
                style={{ width: "100%" }} />
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, color: "var(--t3)" }}>
                <span>1σ (sensitive)</span><span>5σ (strict)</span>
              </div>
            </Field>
          )}
          <Field label="History window (days)" style={{ flex: 1 }}>
            <input className="aug-input" type="number" min={7} max={365}
              value={form.history_days ?? 30}
              onChange={e => setField("history_days", Number(e.target.value) as any)}
              style={{ width: "100%" }} />
          </Field>
        </div>
      )}

      {alertOn === "segment_drift" && (
        <div style={{ display: "flex", gap: 12 }}>
          <Field label="Dimension column" style={{ flex: 2 }}>
            <input className="aug-input" value={form.dimension_column ?? ""}
              onChange={e => setField("dimension_column", e.target.value as any)}
              placeholder="e.g. region, channel" style={{ width: "100%" }} />
          </Field>
          <Field label={`p-value threshold (${form.drift_p_threshold ?? 0.05})`} style={{ flex: 1 }}>
            <input type="range" min={0.01} max={0.2} step={0.01}
              value={form.drift_p_threshold ?? 0.05}
              onChange={e => setField("drift_p_threshold", Number(e.target.value) as any)}
              style={{ width: "100%" }} />
          </Field>
        </div>
      )}

      {alertOn === "data_freshness" && (
        <>
          <div style={{ display: "flex", gap: 12 }}>
            <Field label="Table" style={{ flex: 2 }}>
              <input className="aug-input" value={form.freshness_table ?? ""}
                onChange={e => setField("freshness_table", e.target.value as any)}
                placeholder="e.g. orders" style={{ width: "100%" }} />
            </Field>
            <Field label="Timestamp column" style={{ flex: 1 }}>
              <input className="aug-input" value={form.freshness_column ?? "updated_at"}
                onChange={e => setField("freshness_column", e.target.value as any)}
                style={{ width: "100%" }} />
            </Field>
          </div>
          <Field label="SLA (hours)">
            <input className="aug-input" type="number" min={1}
              value={form.freshness_sla_hours ?? 24}
              onChange={e => setField("freshness_sla_hours", Number(e.target.value) as any)}
              style={{ width: 120 }} />
          </Field>
        </>
      )}

      {/* Schedule */}
      <Field label="Schedule">
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 8 }}>
          {CRON_PRESETS.map(p => (
            <button key={p.label} onClick={() => onCronPreset(p.cron)}
              style={{
                ...segBtn,
                background: (!isCustomCron && cronPreset === p.cron && p.label !== "Custom") || (isCustomCron && p.label === "Custom")
                  ? "var(--blue3)" : "var(--bg-2)",
                color: (!isCustomCron && cronPreset === p.cron && p.label !== "Custom") || (isCustomCron && p.label === "Custom")
                  ? "#fff" : "var(--t2)",
              }}>
              {p.label}
            </button>
          ))}
        </div>
        {isCustomCron && (
          <input className="aug-input" value={form.check_cron ?? ""}
            onChange={e => onCustomCronChange(e.target.value)}
            placeholder="cron expression, e.g. 0 9 * * 1-5"
            style={{ width: "100%", fontFamily: "var(--font-mono)", fontSize: 12 }} />
        )}
        {!isCustomCron && (
          <div style={{ fontSize: 11, color: "var(--t3)", marginTop: 2 }}>
            Runs: <code style={{ fontFamily: "var(--font-code)" }}>{form.check_cron}</code>
          </div>
        )}
      </Field>

      {/* Notification */}
      <Field label="Notification">
        <div style={{ display: "flex", gap: 6 }}>
          {(["in_app", "slack", "email"] as const).map(ch => (
            <button key={ch} onClick={() => setField("notification_channel", ch as any)}
              style={{ ...segBtn, background: form.notification_channel === ch ? "var(--blue3)" : "var(--bg-2)", color: form.notification_channel === ch ? "#fff" : "var(--t2)" }}>
              {ch === "in_app" ? "In-app" : ch.charAt(0).toUpperCase() + ch.slice(1)}
            </button>
          ))}
        </div>
      </Field>

      {/* Error */}
      {error && <p style={{ color: "var(--r2)", fontSize: 12, margin: 0 }}>{error}</p>}

      {/* Actions */}
      <div style={{ display: "flex", gap: 8, marginTop: 4 }}>
        <button className="aug-btn" onClick={onSave} disabled={saving} style={{ minWidth: 100 }}>
          {saving ? "Saving…" : isEdit ? "Update" : "Create monitor"}
        </button>
        <button onClick={onCancel} style={{ ...ghostBtn, padding: "6px 14px" }}>Cancel</button>
      </div>
    </div>
  );
}

// ── Small helpers ─────────────────────────────────────────────────────────────

function Field({ label, children, style }: { label: string; children: React.ReactNode; style?: React.CSSProperties }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 5, ...style }}>
      <label className="aug-label" style={{ fontSize: 11, color: "var(--t3)", textTransform: "uppercase", letterSpacing: "0.05em" }}>{label}</label>
      {children}
    </div>
  );
}

function TypeBadge({ type }: { type: AlertOn }) {
  const colors: Record<AlertOn, string> = {
    threshold_cross: "var(--blue3)",
    anomaly:         "var(--vio3, #6366f1)",
    trend_reversal:  "var(--chart-threshold-warn, #f59e0b)",
    segment_drift:   "var(--blue2)",
    data_freshness:  "var(--r2)",
    any_change:      "var(--t3)",
  };
  const labels: Record<AlertOn, string> = {
    threshold_cross: "Threshold",
    anomaly:         "Anomaly",
    trend_reversal:  "Trend",
    segment_drift:   "Drift",
    data_freshness:  "Freshness",
    any_change:      "Any change",
  };
  return (
    <span style={{ fontSize: 10, fontWeight: 600, padding: "1px 6px", borderRadius: 4, background: colors[type] + "22", color: colors[type], border: `1px solid ${colors[type]}44` }}>
      {labels[type]}
    </span>
  );
}

function EmptyState({ onAdd }: { onAdd: () => void }) {
  return (
    <div style={{ textAlign: "center", paddingTop: 60, color: "var(--t3)" }}>
      <div style={{ fontSize: 32, marginBottom: 12 }}>📡</div>
      <div style={{ fontSize: 14, fontWeight: 500, color: "var(--t2)", marginBottom: 6 }}>No monitors yet</div>
      <div style={{ fontSize: 12, marginBottom: 20 }}>Set up a monitor to get alerted when metrics cross thresholds, drift, or go stale.</div>
      <button className="aug-btn" onClick={onAdd}>Create first monitor</button>
    </div>
  );
}

function cronLabel(cron: string): string {
  const match = CRON_PRESETS.find(p => p.cron === cron && p.label !== "Custom");
  return match ? match.label : cron;
}

function relTime(iso: string): string {
  try {
    const diff = Date.now() - new Date(iso).getTime();
    const m = Math.floor(diff / 60000);
    if (m < 2)  return "just now";
    if (m < 60) return `${m}m ago`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h}h ago`;
    return `${Math.floor(h / 24)}d ago`;
  } catch { return ""; }
}

const ghostBtn: React.CSSProperties = {
  background: "none", border: "1px solid var(--bg-3)",
  color: "var(--t2)", borderRadius: 4, cursor: "pointer",
  fontSize: 11, padding: "3px 9px",
};

const segBtn: React.CSSProperties = {
  border: "none", borderRadius: 4, cursor: "pointer",
  fontSize: 12, padding: "5px 10px", display: "flex", alignItems: "center",
};
