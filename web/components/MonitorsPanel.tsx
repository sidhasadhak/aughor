"use client";
/**
 * Monitors — redone to `aughor-v2/CLARITY.md` (2026-10-12): four figures (how many, open alerts, proven to fire,
 * checks a day), then what needs a person — open alerts, monitors never proven to fire — then the alerts over twelve
 * weeks, then the monitors as rows of one line each. A monitor's rule, query, proof and its Edit and Delete sit behind
 * its Details; identical alerts fold into one row with a count.
 */
import React, { useEffect, useState, useCallback, useMemo } from "react";
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
  getActionTriggers,
  type ActionTrigger,
  Metric,
  MonitorProof,
  backtestMonitor,
  drillMonitor,
  getMonitorProof,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Segmented } from "@/components/ui/segmented";
import { Switch } from "@/components/ui/switch";
import { TabStrip } from "@/components/ui/tab-strip";
import { RadioCards } from "@radix-ui/themes";
import { EmptyState as SharedEmptyState } from "@/components/ui/empty-state";
import { takeMonitorDraft } from "@/lib/query/monitorDraft";
import { Loading, ReadFailed } from "@/components/ui/states";
import { SelectField } from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Icon } from "@/components/ui/icon";
import { formatCount, relTime } from "@/lib/format";
import {
  alertText, alertsByWeek, channelWords, checksPerDay, dayMonth, FIRES, firedOnly, foldAlerts, fromRemovedMonitors, isOpen,
  isRecovery, proofState, proofWords, removedWords, ruleWords,
  scheduleMix, scheduleWords, short, type AlertGroup, type ProofState,
} from "@/lib/monitorSummary";
import {
  CARD, Chip, Columns, Dot, Figure, Figures, Label, MUTED, NeedsRow, NeedsYou, ONE_LINE, Page, ROW, type Tone,
} from "@/components/clarity/kit";

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

/** A severity names a state by its hue (INSTRUMENT §3): critical adverse, warning needs a person, info plain. */
const SEVERITY_HUE: Record<string, "red" | "amber" | "blue"> = { critical: "red", warning: "amber", info: "blue" };

const plural = (n: number, one: string, many = `${one}s`) => `${formatCount(n)} ${n === 1 ? one : many}`;

/** The proof chip's tone: amber where a person is owed a proof, green where the alert path was seen end to end. */
const PROOF_TONE: Record<ProofState, Tone> = {
  proven: "up", delivered: "up", checked: "plain", undelivered: "amber", silent: "amber", never: "amber", unknown: "plain",
};

/** The server's proof sentence with its timestamps as a person reads them. */
function proofSentence(s: string): string {
  return s.replace(/\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})?/g, iso => dayMonth(iso));
}

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
  /** Where an alert can go besides in-app; null when they could not be read. */
  const [triggers, setTriggers]   = useState<ActionTrigger[] | null>(null);
  const [loading, setLoading]     = useState(false);
  const [loaded, setLoaded]       = useState(false);
  const [readFailed, setReadFailed] = useState<string | null>(null);
  const [editTarget, setEditTarget] = useState<MonitorDef | null>(null);
  const [form, setForm]           = useState<Partial<MonitorDef> & { conn_id: string; name: string }>(blankForm(connId ?? ""));
  const [cronPreset, setCronPreset] = useState("0 * * * *");
  const [isCustomCron, setIsCustomCron] = useState(false);
  const [metricSource, setMetricSource] = useState<"catalog" | "sql">("catalog");
  const [runResult, setRunResult] = useState<Record<string, string>>({});
  const [saving, setSaving]       = useState(false);
  const [error, setError]         = useState<string | null>(null);
  /** Each monitor's proof — null where the read failed, absent while it is being read. */
  const [proofs, setProofs]       = useState<Record<string, MonitorProof | null>>({});
  const [checking, setChecking]   = useState(false);
  const [openRows, setOpenRows]   = useState<ReadonlySet<string>>(new Set());

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

  const readProofs = useCallback(async (ms: MonitorDef[]) => {
    const got = await Promise.allSettled(ms.map(m => getMonitorProof(m.id)));
    setProofs(Object.fromEntries(ms.map((m, i) => {
      const r = got[i];
      return [m.id, r.status === "fulfilled" ? r.value : null];
    })));
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [ms, as, mets, trs] = await Promise.all([
        getMonitors(connId, workspaceId),
        getAllAlerts(connId, 100, workspaceId),
        getMetrics().catch(() => []),
        getActionTriggers().catch(() => null),
      ]);
      setMonitors(ms);
      setAlerts(as);
      setMetrics(mets);
      setTriggers(trs);
      setReadFailed(null);
      void readProofs(ms);
    } catch (e: unknown) {
      setReadFailed(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
      setLoaded(true);
    }
  }, [connId, workspaceId, readProofs]);

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
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
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
      // What it read is said with the verdict, so "no condition met" can be checked against the line (Gap 36).
      const read = res.read ? ` · ${res.read}` : "";
      const msg = "fired" in res && res.fired === false
        ? `No condition met${read}`
        : `Would fire: ${(res as MonitorAlert).severity} — ${alertText((res as MonitorAlert).message)}${read} · shown, not sent`;
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

  async function ack(ids: string[]) {
    const failed: string[] = [];
    await Promise.all(ids.map(id => acknowledgeAlert(id).then(
      () => setAlerts(as => as.map(a => a.id === id ? { ...a, acknowledged: true } : a)),
      // Optimistic flip on a failed ack left the UI lying until the next load.
      e => { failed.push(e instanceof Error ? e.message : "Acknowledge failed"); },
    )));
    if (failed.length) setError(failed[0]);
  }

  /** Feeds each rule a synthetic outlier — no warehouse query, nothing sent — and reads the proofs again. */
  async function checkRules(ms: MonitorDef[]) {
    setChecking(true);
    setError(null);
    for (const m of ms) {
      try { await drillMonitor(m.id, false); }
      catch (e) { setError(`${m.name}: ${e instanceof Error ? e.message : "the check failed"}`); }
    }
    await readProofs(monitors);
    setChecking(false);
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

  // open: not acknowledged, and not closed by a recovery (TC-4) — a recovery itself waits on nobody
  const openAlerts = useMemo(() => alerts.filter(isOpen), [alerts]);

  // ── Render ────────────────────────────────────────────────────────────────────

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", background: "var(--bg-0)", color: "var(--t1)" }}>
      {/* The views as a tab strip — the form, while it is open, is a tab of its own that the others do not leave —
          and the row's one door at its end. The first view is "Overview": the tab above already says "Monitors". */}
      <TabStrip label="Monitor views" value={view} onChange={v => { if (view !== "form") setView(v); }}
        style={{ padding: "12px 20px 0", flexShrink: 0 }}
        tabs={[
          { id: "list" as View, label: "Overview" },
          { id: "alerts" as View, label: "Alerts", badge: openAlerts.length },
          ...(view === "form" ? [{ id: "form" as View, label: "Configure" }] : []),
        ]}
        trailing={<>
          {view !== "form" && <Button variant="ghost" size="xs" onClick={openCreate}><Icon name="plus" size={12} />New monitor</Button>}
          {view === "form" && <Button variant="ghost" size="xs" onClick={() => setView("list")}><Icon name="back" size={12} />Back</Button>}
        </>} />

      {view === "form" ? (
        <div style={{ flex: 1, overflowY: "auto", padding: 20 }}>
          <MonitorForm
            form={form}
            setField={setField}
            metricSource={metricSource}
            setMetricSource={setMetricSource}
            metrics={metrics}
            triggers={triggers}
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
        </div>
      ) : (
        <Page testId={view === "list" ? "monitors-overview" : "monitors-alerts"}>
          {error && <div role="alert" className="aug-fs-sm" style={{ color: "var(--red4)" }}>{error}</div>}
          {readFailed && <ReadFailed what="the monitors" error={readFailed} onRetry={load} />}
          {!loaded && loading && <Loading what="monitors" />}
          {loaded && !readFailed && view === "alerts" && <AlertsList alerts={alerts} monitors={monitors} onAck={ack} />}
          {loaded && !readFailed && view === "list" && (monitors.length === 0
            ? <EmptyState onAdd={openCreate} />
            : <Overview monitors={monitors} alerts={alerts} openAlerts={openAlerts} proofs={proofs} metrics={metrics} triggers={triggers}
                checking={checking} runResult={runResult} openRows={openRows}
                onToggleRow={id => setOpenRows(p => { const n = new Set(p); if (n.has(id)) n.delete(id); else n.add(id); return n; })}
                onAck={ack} onSeeAlerts={() => setView("alerts")} onCheckRules={checkRules} onEdit={openEdit}
                onDelete={m => remove(m.id)} onRun={m => runNow(m.id)} onToggle={toggle}
                onProofChanged={() => readProofs(monitors)} />)}
        </Page>
      )}
    </div>
  );
}

// ── The overview: figures, Needs you, the picture, the list ───────────────────

function Overview({ monitors, alerts, openAlerts, proofs, metrics, triggers, checking, runResult, openRows, onToggleRow, onAck,
  onSeeAlerts, onCheckRules, onEdit, onDelete, onRun, onToggle, onProofChanged }: {
  monitors: MonitorDef[];
  alerts: MonitorAlert[];
  openAlerts: MonitorAlert[];
  proofs: Record<string, MonitorProof | null>;
  metrics: Metric[];
  triggers: ActionTrigger[] | null;
  checking: boolean;
  runResult: Record<string, string>;
  openRows: ReadonlySet<string>;
  onToggleRow: (id: string) => void;
  onAck: (ids: string[]) => void;
  onSeeAlerts: () => void;
  onCheckRules: (ms: MonitorDef[]) => void;
  onEdit: (m: MonitorDef) => void;
  onDelete: (m: MonitorDef) => void;
  onRun: (m: MonitorDef) => void;
  onToggle: (m: MonitorDef) => void;
  onProofChanged: () => void;
}) {
  const on = monitors.filter(m => m.enabled);
  const read = monitors.filter(m => m.id in proofs);
  const unread = read.filter(m => proofs[m.id] === null);
  const stateOf = (m: MonitorDef) => proofState(proofs[m.id]);
  const fires = read.filter(m => FIRES.has(stateOf(m)));
  const endToEnd = read.filter(m => stateOf(m) === "proven" || stateOf(m) === "delivered");
  const never = read.filter(m => stateOf(m) === "never");
  const broken = read.filter(m => stateOf(m) === "silent" || stateOf(m) === "undelivered");
  const perDay = on.map(m => checksPerDay(m.check_cron));
  const known = perDay.filter((n): n is number => n != null);
  // a recovery (TC-4) closes an alert and is none: never counted, charted or "last"
  const fired = firedOnly(alerts);
  const lastAlert = [...fired].sort((a, b) => b.triggered_at.localeCompare(a.triggered_at))[0];
  const acked = fired.filter(a => a.acknowledged).length;
  const closed = fired.filter(a => !a.acknowledged && a.closed_by).length;

  const openByMonitor = new Map<string, MonitorAlert[]>();
  for (const a of openAlerts) openByMonitor.set(a.monitor_id, [...(openByMonitor.get(a.monitor_id) ?? []), a]);
  const alertsOf = (id: string) => alerts.filter(a => a.monitor_id === id);

  const weeks = alertsByWeek(fired, new Date(), 12);
  const inWeeks = weeks.reduce((s, w) => s + w.n, 0);
  // an alert outlives its monitor (supersede, do not delete): said apart, as Notifications says its removed triggers
  const since = weeks[0]?.start.toISOString() ?? "";
  const removedInWeeks = removedWords(fired.filter(a => a.triggered_at >= since), monitors);
  const removed = removedWords(fired, monitors);

  return (
    <>
      <Figures testId="monitor-figures">
        <Figure label="Monitors" value={formatCount(monitors.length)} testId="fig-monitors"
          sub={on.length === monitors.length ? "all on" : `${on.length} on · ${monitors.length - on.length} off`} />
        <Figure label="Open alerts" value={formatCount(openAlerts.length)} tone={openAlerts.length ? "amber" : undefined} testId="fig-open"
          sub={fired.length === 0 ? "none has fired here yet"
            : `${formatCount(acked)} acknowledged${closed ? ` · ${formatCount(closed)} closed by a recovery` : ""} · last ${dayMonth(lastAlert.triggered_at)}${removed ? ` · ${removed}` : ""}`} />
        <Figure label="Proven to fire" testId="fig-proven"
          value={read.length < monitors.length ? "—" : `${fires.length} of ${monitors.length}`}
          sub={read.length < monitors.length ? "reading their proofs…"
            : unread.length ? `${unread.length} could not be read`
            : endToEnd.length ? `${endToEnd.length} delivered end to end` : "none delivered end to end"} />
        <Figure label="Checks a day" value={known.length ? short(known.reduce((s, n) => s + n, 0)) : "—"} testId="fig-checks"
          title="Each check runs the monitor's query on its connection"
          sub={on.length ? `${scheduleMix(on)}${known.length < on.length ? " · not all counted" : ""}` : "every monitor is off"} />
      </Figures>

      <NeedsYou testId="monitor-needs" empty={read.length < monitors.length || unread.length
        ? "Nothing needs you · no open alert"
        : "Nothing needs you · no open alert, and every monitor has been seen to fire"}>
        {[
          ...[...openByMonitor.entries()].map(([id, open]) => (
            <NeedsRow key={`open-${id}`} testId="needs-open"
              title={`${open[0].monitor_name}${monitors.some(m => m.id === id) ? "" : " · since removed"} · ${plural(open.length, "open alert")}`}
              detail={`${alertText(open[0].message)}${open.some(a => a.caveat) ? " · value may be mis-computed" : ""}`}
              actions={<>
                <Button size="xs" variant="secondary" onClick={() => onAck(open.map(a => a.id))}>
                  {open.length === 1 ? "Acknowledge" : "Acknowledge all"}
                </Button>
                <Button size="xs" variant="ghost" onClick={onSeeAlerts}>See alerts</Button>
              </>} />
          )),
          never.length > 0 && (
            <NeedsRow key="never" testId="needs-never"
              title={`${never.length === 1 ? "1 monitor has" : `${never.length} monitors have`} never been proven to fire`}
              detail="Checking feeds each rule a made-up outlier — no query runs and nothing is sent"
              actions={<Button size="xs" variant="secondary" disabled={checking} onClick={() => onCheckRules(never)}>
                {checking ? "Checking…" : never.length === 1 ? "Check its rule" : "Check their rules"}
              </Button>} />
          ),
          ...broken.map(m => (
            <NeedsRow key={`broken-${m.id}`} testId="needs-broken"
              title={`${m.name}: ${stateOf(m) === "silent" ? "its rule did not fire in a drill" : "its test alert was not delivered"}`}
              detail={proofs[m.id]?.last_drill?.detail}
              actions={<Button size="xs" variant="secondary" onClick={() => onEdit(m)}>Edit</Button>} />
          )),
        ]}
      </NeedsYou>

      {/* The picture appears when there is something to picture: with no alert in the twelve weeks, the figure above
          already says when the last one fired, or that none has. */}
      {inWeeks > 0 && (
        <section aria-label="Alerts over twelve weeks" data-testid="monitor-alert-weeks" style={CARD}>
          <Label right={<span>{`${plural(inWeeks, "alert")}${removedInWeeks ? ` · ${removedInWeeks}` : ""}${alerts.length >= 100 ? " · of the latest 100 read" : ""}`}</span>}>
            Alerts · last 12 weeks
          </Label>
          <Columns columns={weeks.map(w => ({
            key: w.start.toISOString(), value: w.n, label: dayMonth(w.start.toISOString()),
            tip: `Week of ${dayMonth(w.start.toISOString())}: ${plural(w.n, "alert")}${w.n ? ` — ${Object.entries(w.bySeverity)
              .map(([s, n]) => `${n} ${s}`).join(", ")}` : ""}`,
          }))} />
        </section>
      )}

      <section aria-label="Monitors" data-testid="monitor-list" style={CARD}>
        <Label>Monitors</Label>
        {monitors.map((m, i) => (
          <MonitorRow key={m.id} monitor={m} first={i === 0} proof={proofs[m.id]} proofRead={m.id in proofs}
            metricLabel={m.metric_name ? (metrics.find(x => x.name === m.metric_name)?.label ?? m.metric_name) : null}
            channel={channelWords(m.notification_channel, triggers)}
            alerts={alertsOf(m.id)} open={openRows.has(m.id)} runResult={runResult[m.id]}
            onToggleOpen={() => onToggleRow(m.id)} onEdit={() => onEdit(m)} onDelete={() => onDelete(m)}
            onRun={() => onRun(m)} onToggle={() => onToggle(m)} onProofChanged={onProofChanged} />
        ))}
      </section>
    </>
  );
}

// ── A monitor, one row ────────────────────────────────────────────────────────

function MonitorRow({ monitor, first, proof, proofRead, metricLabel, channel, alerts, open, runResult, onToggleOpen, onEdit,
  onDelete, onRun, onToggle, onProofChanged }: {
  monitor: MonitorDef;
  first: boolean;
  proof: MonitorProof | null | undefined;
  proofRead: boolean;
  metricLabel: string | null;
  /** Where its alerts go, in words (`channelWords`). */
  channel: string;
  alerts: MonitorAlert[];
  open: boolean;
  runResult?: string;
  onToggleOpen: () => void;
  onEdit: () => void;
  onDelete: () => void;
  onRun: () => void;
  onToggle: () => void;
  onProofChanged: () => void;
}) {
  const lastAlert = [...firedOnly(alerts)].sort((a, b) => b.triggered_at.localeCompare(a.triggered_at))[0];
  const unacked = alerts.filter(isOpen).length;
  const state = proofRead ? proofState(proof) : "unknown";
  const meta = [
    ruleWords(monitor), scheduleWords(monitor.check_cron), channel,
    metricLabel ?? "your own query", lastAlert ? `last fired ${relTime(lastAlert.triggered_at)} ago` : "",
  ].filter(Boolean).join(" · ");

  return (
    <div data-testid="monitor-row" style={{ borderTop: first ? undefined : "1px solid var(--b0)", padding: "9px 2px" }}>
      <div style={{ display: "grid", gridTemplateColumns: "auto minmax(0, 1fr) auto auto", gap: 12, alignItems: "center" }}>
        <Switch checked={monitor.enabled} onChange={onToggle}
          title={monitor.enabled ? "Turn off" : "Turn on"} aria-label={`${monitor.enabled ? "Turn off" : "Turn on"} ${monitor.name}`} />
        <div style={{ minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
            <span className="aug-fs-chrome" title={monitor.name} style={{ ...ONE_LINE, fontWeight: 600, color: "var(--t1)" }}>{monitor.name}</span>
            {proofRead && (
              <Chip tone={PROOF_TONE[state]} title={proof ? proofSentence(proof.sentence) : "Could not read whether this alert was proven"}>
                {proof ? proofWords(proof) : "proof unread"}
              </Chip>
            )}
            {unacked > 0 && <Chip tone="amber">{`${unacked} open`}</Chip>}
            {!monitor.enabled && <Chip>off</Chip>}
          </div>
          <div className="aug-fs-xs" title={meta} style={{ ...MUTED, ...ONE_LINE }}>{meta}</div>
        </div>
        <Button size="xs" variant="outline" onClick={onRun}>Run now</Button>
        <Button size="xs" variant="ghost" aria-expanded={open} onClick={onToggleOpen}>
          Details <Icon name={open ? "chevu" : "chevd"} size={12} />
        </Button>
      </div>

      {runResult && <div role="status" className="aug-fs-xs" style={{ ...MUTED, marginTop: 6, paddingLeft: 48 }}>{runResult}</div>}

      {open && (
        <div data-testid="monitor-details" style={{ padding: "10px 0 2px 48px", display: "flex", flexDirection: "column", gap: 10 }}>
          <MonitorProofRow monitorId={monitor.id} proof={proofRead ? proof : undefined} onChanged={onProofChanged} />
          <div style={ROW}>
            <Chip title="After an alert, the same or a lower severity stays quiet this long; a worse one fires at once">
              {`quiet ${monitor.grace_period_hours} h after an alert`}
            </Chip>
            {monitor.created_at && <Chip>{`made ${dayMonth(monitor.created_at)}`}</Chip>}
          </div>
          {monitor.custom_sql ? (
            <pre className="aug-fs-xs" style={{ margin: 0, background: "var(--code-bg)", borderRadius: "var(--r2)", padding: "8px 10px",
              whiteSpace: "pre-wrap", wordBreak: "break-word", maxHeight: 160, overflow: "auto", fontFamily: "var(--font-code)",
              color: "var(--t2)" }}>{monitor.custom_sql}</pre>
          ) : <div className="aug-fs-sm" style={{ color: "var(--t2)" }}>Watches the metric {metricLabel ?? monitor.metric_name}</div>}
          <div style={ROW}>
            <Button size="xs" variant="outline" onClick={onEdit}>Edit</Button>
            <Button size="xs" variant="destructive" onClick={onDelete}>Delete</Button>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Proof — idea 6, alerts that prove they work ─────────────────────────────────
// The backtest, the drill and "last proven working" were API doors only: a monitor
// could be proven, but nobody on a screen could ask for the proof or see it.

type ProofOutcome = { tone: "ok" | "warn"; text: string };

/** The proof's sentence and the three ways to earn one. Reads its own proof when the page has not (`proof` absent). */
export function MonitorProofRow({ monitorId, proof: given, onChanged }: {
  monitorId: string;
  /** The page's read of this monitor's proof — null when that read failed; absent to read it here. */
  proof?: MonitorProof | null;
  onChanged?: () => void;
}) {
  const [own, setOwn] = useState<MonitorProof | null>(null);
  const [ownFailed, setOwnFailed] = useState(false);
  const [busy, setBusy] = useState<"" | "backtest" | "check" | "send">("");
  const [outcome, setOutcome] = useState<ProofOutcome | null>(null);
  const standalone = given === undefined;

  const readProof = useCallback(() => {
    if (!standalone) { onChanged?.(); return; }
    getMonitorProof(monitorId)
      .then(p => { setOwn(p); setOwnFailed(false); })
      .catch(() => setOwnFailed(true));
  }, [monitorId, standalone, onChanged]);
  useEffect(() => { if (standalone) readProof(); }, [standalone, readProof]);

  const proof = standalone ? own : given;
  const failed = standalone ? ownFailed : given === null;

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
    <Button size="xs" variant="ghost" onClick={() => run(kind)} disabled={busy !== ""} title={title}>
      {busy === kind ? `${label}…` : label}
    </Button>
  );

  return (
    <div>
      <div style={{ ...ROW, gap: 6 }}>
        {proof || failed ? (
          <span className="aug-fs-xs" style={{ ...MUTED, flex: "1 1 160px", minWidth: 160 }}>
            {proof ? proofSentence(proof.sentence) : "Could not read whether this alert was proven."}
          </span>
        ) : (
          <Loading what="its proof" inline style={{ flex: "1 1 160px", minWidth: 160 }} />
        )}
        {btn("backtest", "Backtest", "Replay the last year of this monitor's own series under its rule — one warehouse query")}
        {btn("check", "Check rule", "Feed the rule a synthetic outlier; nothing is sent")}
        {btn("send", "Send test alert", "Feed the rule a synthetic outlier and deliver the [DRILL] alert through its real channel")}
      </div>
      {outcome && (
        <div role="status" className="aug-fs-xs" style={{ marginTop: 6, color: outcome.tone === "ok" ? "var(--t2)" : "var(--amb4)" }}>
          {outcome.text}
        </div>
      )}
    </div>
  );
}

// ── Alerts, repeats folded ────────────────────────────────────────────────────

function AlertsList({ alerts, monitors, onAck }: { alerts: MonitorAlert[]; monitors: MonitorDef[]; onAck: (ids: string[]) => void }) {
  const groups = useMemo(() => foldAlerts(alerts), [alerts]);
  const open = alerts.filter(isOpen).length;
  const gone = useMemo(() => new Set(fromRemovedMonitors(alerts, monitors).map(a => a.monitor_id)), [alerts, monitors]);
  return (
    <section aria-label="Alerts" data-testid="alert-list" style={CARD}>
      <Label right={alerts.length ? <span>{`${formatCount(alerts.length)}${alerts.length >= 100 ? " latest" : ""} · ${open} open`}</span> : null}>
        Alerts
      </Label>
      {groups.length === 0 ? <div className="aug-fs-sm" style={MUTED}>No alerts yet.</div>
        : groups.map((g, i) => <AlertRow key={g.key} g={g} first={i === 0} removed={gone.has(g.latest.monitor_id)}
            onAck={() => onAck(g.open)} />)}
    </section>
  );
}

function AlertRow({ g, first, removed, onAck }: { g: AlertGroup; first: boolean; removed: boolean; onAck: () => void }) {
  const a = g.latest;
  const settled = g.open.length === 0;
  // TC-4 — a recovery is one row of its own, nothing to acknowledge; the alert it closed reads "closed", not "acknowledged"
  const recovery = isRecovery(a);
  const when = g.count === 1 ? `${relTime(a.triggered_at)} ago`
    : dayMonth(g.first) === dayMonth(g.last) ? `${g.count} times · ${dayMonth(g.last)}` : `${g.count} times · ${dayMonth(g.first)} – ${dayMonth(g.last)}`;
  return (
    <div data-testid="alert-row" style={{ borderTop: first ? undefined : "1px solid var(--b0)", padding: "8px 2px", opacity: settled ? 0.6 : 1 }}>
      <div style={{ display: "grid", gridTemplateColumns: "12px minmax(0, 1fr) auto auto", gap: 10, alignItems: "center" }}>
        <Dot hue={recovery ? "green" : SEVERITY_HUE[a.severity] ?? "grey"} title={recovery ? "recovered" : a.severity} />
        <div style={{ minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
            <span className="aug-fs-chrome" style={{ ...ONE_LINE, fontWeight: 500, color: "var(--t1)" }}>{a.monitor_name}</span>
            {recovery
              ? <Chip tone="up" title="Back within its limit. A recovery is recorded here and never sent.">recovered</Chip>
              : <span className="aug-fs-xs" style={MUTED}>{a.severity}</span>}
            {a.caveat && <Chip tone="amber" title={a.caveat}>value may be mis-computed</Chip>}
            {removed && <Chip title="This monitor no longer exists — these alerts are history">since removed</Chip>}
          </div>
          <div className="aug-fs-xs" title={a.message} style={{ ...MUTED, ...ONE_LINE }}>
            {alertText(a.message)}{a.previous_value != null && !recovery ? ` · was ${short(a.previous_value)}` : ""} · {when}
          </div>
        </div>
        <span className="aug-fs-chrome" style={{ color: "var(--t2)", fontVariantNumeric: "tabular-nums", minWidth: 24, textAlign: "right" }}>
          {g.count > 1 ? `×${g.count}` : ""}
        </span>
        {recovery ? <span />
          : settled ? (a.closed_by && !a.acknowledged
            ? <span className="aug-fs-xs" style={MUTED} title={a.closed_at ? `Closed by a recovery ${relTime(a.closed_at)} ago` : undefined}>closed</span>
            : <span className="aug-fs-xs" style={MUTED}>acknowledged</span>)
          : <Button size="xs" variant="secondary" onClick={onAck}>{g.open.length > 1 ? `Acknowledge ${g.open.length}` : "Acknowledge"}</Button>}
      </div>
    </div>
  );
}

// ── Monitor form ──────────────────────────────────────────────────────────────

function MonitorForm({
  form, setField, metricSource, setMetricSource, metrics, triggers,
  cronPreset, isCustomCron, onCronPreset, onCustomCronChange,
  saving, error, isEdit, onSave, onCancel,
}: {
  form: Partial<MonitorDef> & { conn_id: string; name: string };
  setField: <K extends keyof MonitorDef>(k: K, v: MonitorDef[K]) => void;
  metricSource: "catalog" | "sql";
  setMetricSource: (s: "catalog" | "sql") => void;
  metrics: Metric[];
  triggers: ActionTrigger[] | null;
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
  const channel = form.notification_channel || "in_app";
  // A stored channel that names no trigger (the form once offered "slack" and "email") is shown as what it is.
  const stranded = triggers !== null && channel !== "in_app" && !triggers.some(t => t.id === channel);

  return (
    <div style={{ maxWidth: 560, display: "flex", flexDirection: "column", gap: 20 }}>
      <h3 className="aug-fs-h2" style={{ margin: 0, fontWeight: 600, color: "var(--t1)" }}>
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
            rows={3}
            value={form.custom_sql ?? ""}
            onChange={e => setField("custom_sql", e.target.value as any)}
            placeholder="SELECT SUM(revenue) FROM orders WHERE date = CURRENT_DATE"
            style={{ width: "100%", resize: "vertical" }}
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
              <span className="aug-fs-sm" style={{ fontWeight: 600 }}>{at.label}</span>
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
              <div className="aug-fs-xs" style={{ display: "flex", justifyContent: "space-between", color: "var(--t3)" }}>
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
            style={{ width: "100%" }} />
        )}
        {!isCustomCron && (
          <div className="aug-fs-xs" style={{ color: "var(--t3)", marginTop: 2 }}>
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
        <div className="aug-fs-xs" style={{ color: "var(--t3)", marginTop: 2 }}>
          After an alert, the same or a lower severity stays quiet this long; a worse one fires at once.
        </div>
      </Field>

      {/* Notification */}
      <Field label="Notification">
        <SelectField aria-label="Notification" value={channel} onChange={e => setField("notification_channel", e.target.value)}
          style={{ width: "100%" }}>
          <option value="in_app">In-app</option>
          {(triggers ?? []).map(t => <option key={t.id} value={t.id}>{`${t.name} (${t.type})${t.enabled ? "" : " — off"}`}</option>)}
          {stranded && <option value={channel}>{`"${channel}" — no such destination`}</option>}
        </SelectField>
        {triggers !== null && triggers.length === 0 && (
          <div className="aug-fs-xs" style={{ color: "var(--t3)", marginTop: 2 }}>
            Alerts stay in-app until a webhook or Slack trigger exists under Operations ▸ Notifications.
          </div>
        )}
        {stranded && (
          <div className="aug-fs-xs" style={{ color: "var(--red4)", marginTop: 2 }}>
            {`"${channel}" names no destination, so these alerts are sent nowhere. Choose one.`}
          </div>
        )}
      </Field>

      {/* Error */}
      {error && <p className="aug-fs-sm" style={{ color: "var(--red4)", margin: 0 }}>{error}</p>}

      {/* Actions */}
      <div style={{ display: "flex", gap: 8, marginTop: 4 }}>
        <Button size="sm" onClick={onSave} disabled={saving} style={{ minWidth: 100 }}>
          {saving ? "Saving…" : isEdit ? "Update" : "Create monitor"}
        </Button>
        <Button size="sm" variant="ghost" onClick={onCancel}>Cancel</Button>
      </div>
    </div>
  );
}

// ── Small helpers ─────────────────────────────────────────────────────────────

function Field({ label, children, style }: { label: string; children: React.ReactNode; style?: React.CSSProperties }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 5, ...style }}>
      <label className="aug-label aug-fs-xs" style={{ color: "var(--t3)", textTransform: "uppercase", letterSpacing: "0.05em" }}>{label}</label>
      {children}
    </div>
  );
}

function EmptyState({ onAdd }: { onAdd: () => void }) {
  return (
    <SharedEmptyState icon="gauge" title="No monitors yet"
      action={<Button variant="secondary" size="xs" onClick={onAdd}>Create first monitor</Button>}>
      A monitor alerts you when a metric crosses a line, drifts, or goes stale.
    </SharedEmptyState>
  );
}
