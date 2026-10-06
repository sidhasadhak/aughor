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
  MonitorProof,
  backtestMonitor,
  drillMonitor,
  getMonitorProof,
} from "@/lib/api";
import { MiniStat, MiniStatRow } from "@/components/ui/MiniStat";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Segmented } from "@/components/ui/segmented";
import { Switch } from "@/components/ui/switch";
import { TabStrip } from "@/components/ui/tab-strip";
import { RadioCards } from "@radix-ui/themes";
import { EmptyState as SharedEmptyState } from "@/components/ui/empty-state";
import { takeMonitorDraft } from "@/lib/query/monitorDraft";
import { Loading } from "@/components/ui/states";
import { SelectField } from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";

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
  critical: "var(--red3)",
  warning:  "var(--amb3)",
  info:     "var(--blue3)",
};
/** The same severities as a badge: the hue names the state (INSTRUMENT.md §2). */
const SEVERITY_BADGE: Record<string, "destructive" | "amber" | "default"> = {
  critical: "destructive", warning: "amber", info: "default",
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
    grace_period_hours: 4,
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

  // SE-4 I — a statement handed over by the query workbench's "Schedule". Opens the
  // form on the custom-SQL source with the SQL already in it, and stops there: the
  // thresholds are the user's call, and a monitor invented with a default one is an
  // alert that fires at 3am for a number nobody chose.
  useEffect(() => {
    const draft = takeMonitorDraft(connId ?? "");
    if (!draft) return;
    setEditTarget(null);
    setForm({ ...blankForm(draft.connId), custom_sql: draft.sql, name: "" });
    setMetricSource("sql");
    setView("form");
  }, [connId]);

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
    try {
      await deleteMonitor(id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed");
    }
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
    try {
      await updateMonitor(m.id, { enabled: !m.enabled });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Update failed");
    }
    await load();
  }

  async function ack(alertId: string) {
    try {
      await acknowledgeAlert(alertId);
      setAlerts(as => as.map(a => a.id === alertId ? { ...a, acknowledged: true } : a));
    } catch (e) {
      // Optimistic flip on a failed ack left the UI lying until the next load.
      setError(e instanceof Error ? e.message : "Acknowledge failed");
    }
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
      {/* Header: the views as a tab strip — the form, while it is open, is a tab of its own that the
          others do not leave — and the row's one door at its end. */}
      <TabStrip label="Monitor views" value={view} onChange={v => { if (view !== "form") setView(v); }}
        style={{ padding: "12px 20px 0", flexShrink: 0 }}
        tabs={[
          { id: "list" as View, label: "Monitors" },
          { id: "alerts" as View, label: "Alerts", badge: unackedCount },
          ...(view === "form" ? [{ id: "form" as View, label: "Configure" }] : []),
        ]}
        trailing={<>
          {view === "list" && <Button variant="ghost" size="xs" onClick={openCreate}>+ New monitor</Button>}
          {view === "form" && <Button variant="ghost" size="xs" onClick={() => setView("list")}>← Back</Button>}
        </>} />

      {/* Body */}
      <div style={{ flex: 1, overflowY: "auto", padding: 20 }}>
        {loading && <Loading what="monitors" />}
        {error && <p style={{ color: "var(--red3)", fontSize: 13, marginBottom: 12 }}>{error}</p>}

        {/* ── Summary ── real counts across the workspace's monitors/alerts */}
        {view === "list" && !loading && monitors.length > 0 && (
          <MiniStatRow>
            <MiniStat value={monitors.length} label="Total monitors" />
            <MiniStat value={monitors.filter(m => m.enabled).length} label="Active" tone="var(--grn4)" />
            <MiniStat value={unackedCount} label="Unacked alerts" tone={unackedCount > 0 ? "var(--amb4)" : "var(--t1)"} />
          </MiniStatRow>
        )}

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
        <Switch checked={monitor.enabled} onChange={onToggle} title={monitor.enabled ? "Disable" : "Enable"} aria-label={monitor.enabled ? "Disable" : "Enable"} />

        {/* Name + type */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontWeight: 600, fontSize: 13, color: "var(--t1)" }}>{monitor.name}</span>
            <TypeBadge type={monitor.alert_on} />
            {unacked > 0 && (
              <Badge variant="destructive">{unacked} alert{unacked > 1 ? "s" : ""}</Badge>
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
          <Button variant="ghost" onClick={onRun} className="h-auto" style={{ fontSize: 11, padding: "3px 9px", opacity: 0.85 }}>
            Run now
          </Button>
          <Button variant="ghost" onClick={onEdit} className="h-auto p-0 font-normal" style={ghostBtn}>Edit</Button>
          <Button variant="ghost" onClick={onDelete} className="h-auto p-0 font-normal" style={{ ...ghostBtn, color: "var(--red3)" }}>Delete</Button>
        </div>
      </div>

      {runResult && (
        <div style={{ marginTop: 8, fontSize: 11, color: "var(--t3)", paddingLeft: 42 }}>
          {runResult}
        </div>
      )}
      <MonitorProofRow monitorId={monitor.id} />
    </div>
  );
}

// ── Proof — idea 6, alerts that prove they work ─────────────────────────────────
// The backtest, the drill and "last proven working" were API doors only: a monitor
// could be proven, but nobody on a screen could ask for the proof or see it.

type ProofOutcome = { tone: "ok" | "warn"; text: string };

export function MonitorProofRow({ monitorId }: { monitorId: string }) {
  const [proof, setProof] = useState<MonitorProof | null>(null);
  const [proofFailed, setProofFailed] = useState(false);
  const [busy, setBusy] = useState<"" | "backtest" | "check" | "send">("");
  const [outcome, setOutcome] = useState<ProofOutcome | null>(null);

  const readProof = useCallback(() => {
    getMonitorProof(monitorId)
      .then(p => { setProof(p); setProofFailed(false); })
      .catch(() => setProofFailed(true));
  }, [monitorId]);
  useEffect(() => { readProof(); }, [readProof]);

  async function run(kind: "backtest" | "check" | "send") {
    if (kind === "send" && !confirm(
      "Send a [DRILL] alert through this monitor's real channel? The people it notifies will see it.")) return;
    setBusy(kind);
    setOutcome(null);
    try {
      if (kind === "backtest") {
        const b = await backtestMonitor(monitorId);
        // The server's sentence has no subject ("would have fired 3 times in the last 362 days";
        // the quieter σ, when there is one, is already in it); a failed replay says why instead.
        setOutcome(b.ok && b.sentence
          ? { tone: "ok", text: `This alert ${b.sentence}` }
          : { tone: "warn", text: b.reason || b.sentence || "The backtest could not run." });
      } else {
        const d = await drillMonitor(monitorId, kind === "send");
        const text = !d.fired ? `The rule did not fire on a synthetic outlier: ${d.detail}`
          : d.delivered === true ? `Delivered a [DRILL] alert through ${d.channel || "its channel"}.`
          : d.delivered === false ? `The rule fired, but delivery failed: ${d.detail}`
          : "The rule fired on a synthetic outlier — no message was sent.";
        setOutcome({ tone: d.fired && d.delivered !== false ? "ok" : "warn", text });
        readProof();
      }
    } catch (e) {
      setOutcome({ tone: "warn", text: e instanceof Error ? e.message : "The request failed" });
    } finally {
      setBusy("");
    }
  }

  const btn = (kind: "backtest" | "check" | "send", label: string, title: string) => (
    <Button variant="ghost" onClick={() => run(kind)} disabled={busy !== ""} title={title}
            className="h-auto p-0 font-normal" style={ghostBtn}>
      {busy === kind ? `${label}…` : label}
    </Button>
  );

  return (
    <div style={{ marginTop: 8, paddingLeft: 42 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
        {proof || proofFailed ? (
          <span style={{ fontSize: 11, color: "var(--t3)", flex: 1, minWidth: 160 }}>
            {proof ? proof.sentence : "Could not read whether this alert was proven."}
          </span>
        ) : (
          <Loading what="its proof" inline style={{ fontSize: 11, flex: 1, minWidth: 160 }} />
        )}
        {btn("backtest", "Backtest", "Replay the last year of this monitor's own series under its rule — one warehouse query")}
        {btn("check", "Check rule", "Feed the rule a synthetic outlier; nothing is sent")}
        {btn("send", "Send test alert", "Feed the rule a synthetic outlier and deliver the [DRILL] alert through its real channel")}
      </div>
      {outcome && (
        <div role="status" style={{ marginTop: 6, fontSize: 11, color: outcome.tone === "ok" ? "var(--t2)" : "var(--amb4)" }}>
          {outcome.text}
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
      <Badge variant={SEVERITY_BADGE[alert.severity] ?? "secondary"} style={{ textTransform: "uppercase", flexShrink: 0, marginTop: 1 }}>
        {alert.severity}
      </Badge>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 500, color: "var(--t1)" }}>{alert.monitor_name}</div>
        <div style={{ fontSize: 12, color: "var(--t2)", marginTop: 2 }}>{alert.message}</div>
        {alert.caveat && (
          <div style={{
            fontSize: 11, color: SEVERITY_COLOR.warning, marginTop: 4,
          }}>
            ⚠ Value may be mis-computed — {alert.caveat}
          </div>
        )}
        {alert.current_value != null && (
          <div style={{ fontSize: 11, color: "var(--t3)", marginTop: 4 }}>
            Value: <strong>{alert.current_value}</strong>
            {alert.previous_value != null && <> (prev: {alert.previous_value})</>}
            {alert.threshold != null && <> · threshold: {alert.threshold}</>}
          </div>
        )}
        <div style={{ fontSize: 11, color: "var(--t3)", marginTop: 4 }}>{relTime(alert.triggered_at)}</div>
      </div>
      {!alert.acknowledged && (
        <Button variant="ghost" onClick={onAck} className="h-auto p-0 font-normal" style={ghostBtn}>Ack</Button>
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
        <Input
          value={form.name}
          onChange={e => setField("name", e.target.value as any)}
          placeholder="e.g. Daily revenue drop alert"
          style={{ width: "100%" }}
        />
      </Field>

      {/* Metric source */}
      <Field label="Metric">
        <Segmented label="Metric source" value={metricSource} onChange={setMetricSource} style={{ marginBottom: 8, alignSelf: "flex-start" }}
          options={[{ value: "catalog", label: "From catalog" }, { value: "sql", label: "Custom SQL" }]} />
        {metricSource === "catalog" ? (
          <SelectField value={form.metric_name ?? ""} onChange={e => setField("metric_name", e.target.value as any)} style={{ width: "100%" }}>
            <option value="">Select a metric…</option>
            {metrics.map(m => <option key={m.name} value={m.name}>{m.label ?? m.name}</option>)}
          </SelectField>
        ) : (
          <Textarea
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
        {/* A choice with a sentence under each option: Themes' radio cards. */}
        <RadioCards.Root size="1" columns="2" gap="2" aria-label="Alert condition" value={alertOn}
          onValueChange={v => setField("alert_on", v as AlertOn)}>
          {ALERT_TYPES.map(at => (
            <RadioCards.Item key={at.value} value={at.value} style={{ flexDirection: "column", alignItems: "flex-start", gap: 2 }}>
              <span style={{ fontWeight: 600, fontSize: 12 }}>{at.label}</span>
              <span className="aug-fs-xs" style={{ color: "var(--t3)", textAlign: "left" }}>{at.desc}</span>
            </RadioCards.Item>
          ))}
        </RadioCards.Root>
      </Field>

      {/* Conditional fields */}
      {alertOn === "threshold_cross" && (
        <>
          <div style={{ display: "flex", gap: 12 }}>
            <Field label="Warning threshold" style={{ flex: 1 }}>
              <Input type="number" value={form.warning_threshold ?? ""}
                onChange={e => setField("warning_threshold", e.target.value ? Number(e.target.value) as any : null as any)}
                placeholder="e.g. 10000" style={{ width: "100%" }} />
            </Field>
            <Field label="Critical threshold" style={{ flex: 1 }}>
              <Input type="number" value={form.critical_threshold ?? ""}
                onChange={e => setField("critical_threshold", e.target.value ? Number(e.target.value) as any : null as any)}
                placeholder="e.g. 8000" style={{ width: "100%" }} />
            </Field>
          </div>
          <Field label="Direction">
            <Segmented label="Direction" value={form.threshold_direction ?? ""} onChange={d => setField("threshold_direction", d)} style={{ alignSelf: "flex-start" }}
              options={[{ value: "below", label: "Alert when below (e.g. revenue)" }, { value: "above", label: "Alert when above (e.g. error rate)" }]} />
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
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: "var(--t3)" }}>
                <span>1σ (sensitive)</span><span>5σ (strict)</span>
              </div>
            </Field>
          )}
          <Field label="History window (days)" style={{ flex: 1 }}>
            <Input type="number" min={7} max={365}
              value={form.history_days ?? 30}
              onChange={e => setField("history_days", Number(e.target.value) as any)}
              style={{ width: "100%" }} />
          </Field>
        </div>
      )}

      {alertOn === "segment_drift" && (
        <div style={{ display: "flex", gap: 12 }}>
          <Field label="Dimension column" style={{ flex: 2 }}>
            <Input value={form.dimension_column ?? ""}
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
              <Input value={form.freshness_table ?? ""}
                onChange={e => setField("freshness_table", e.target.value as any)}
                placeholder="e.g. orders" style={{ width: "100%" }} />
            </Field>
            <Field label="Timestamp column" style={{ flex: 1 }}>
              <Input value={form.freshness_column ?? "updated_at"}
                onChange={e => setField("freshness_column", e.target.value as any)}
                style={{ width: "100%" }} />
            </Field>
          </div>
          <Field label="SLA (hours)">
            <Input type="number" min={1}
              value={form.freshness_sla_hours ?? 24}
              onChange={e => setField("freshness_sla_hours", Number(e.target.value) as any)}
              style={{ width: 120 }} />
          </Field>
        </>
      )}

      {/* Schedule */}
      <Field label="Schedule">
        <Segmented label="Schedule" style={{ marginBottom: 8, alignSelf: "flex-start" }}
          value={isCustomCron ? "Custom" : (CRON_PRESETS.find(p => p.cron === cronPreset && p.label !== "Custom")?.label ?? "")}
          onChange={label => onCronPreset(CRON_PRESETS.find(p => p.label === label)?.cron ?? "")}
          options={CRON_PRESETS.map(p => ({ value: p.label, label: p.label }))} />
        {isCustomCron && (
          <Input value={form.check_cron ?? ""}
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

      {/* Grace period (anti-flap debounce) */}
      <Field label="Grace period (hours)">
        <Input type="number" min={0} step={0.5}
          value={form.grace_period_hours ?? 4}
          onChange={e => setField("grace_period_hours", Number(e.target.value) as any)}
          style={{ width: 120 }} />
        <div style={{ fontSize: 11, color: "var(--t3)", marginTop: 2 }}>
          After an alert fires, suppress further same- or lower-severity alerts for this many hours (anti-flap). Escalations fire immediately.
        </div>
      </Field>

      {/* Notification */}
      <Field label="Notification">
        <Segmented label="Notification" value={form.notification_channel ?? ""} onChange={ch => setField("notification_channel", ch as MonitorDef["notification_channel"])} style={{ alignSelf: "flex-start" }}
          options={[{ value: "in_app", label: "In-app" }, { value: "slack", label: "Slack" }, { value: "email", label: "Email" }]} />
      </Field>

      {/* Error */}
      {error && <p style={{ color: "var(--red3)", fontSize: 12, margin: 0 }}>{error}</p>}

      {/* Actions */}
      <div style={{ display: "flex", gap: 8, marginTop: 4 }}>
        <Button variant="ghost" className="h-auto" onClick={onSave} disabled={saving} style={{ minWidth: 100 }}>
          {saving ? "Saving…" : isEdit ? "Update" : "Create monitor"}
        </Button>
        <Button variant="ghost" onClick={onCancel} className="h-auto p-0 font-normal" style={{ ...ghostBtn, padding: "6px 14px" }}>Cancel</Button>
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
  const tones: Record<AlertOn, "default" | "violet" | "amber" | "cyan" | "destructive" | "secondary"> = {
    threshold_cross: "default",
    anomaly:         "violet",
    trend_reversal:  "amber",
    segment_drift:   "cyan",
    data_freshness:  "destructive",
    any_change:      "secondary",
  };
  const labels: Record<AlertOn, string> = {
    threshold_cross: "Threshold",
    anomaly:         "Anomaly",
    trend_reversal:  "Trend",
    segment_drift:   "Drift",
    data_freshness:  "Freshness",
    any_change:      "Any change",
  };
  return <Badge variant={tones[type]}>{labels[type]}</Badge>;
}

function EmptyState({ onAdd }: { onAdd: () => void }) {
  return (
    <SharedEmptyState icon="gauge" title="No monitors yet"
      action={<Button variant="ghost" className="h-auto" onClick={onAdd}>Create first monitor</Button>}>
      Set up a monitor to get alerted when metrics cross thresholds, drift, or go stale.
    </SharedEmptyState>
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

