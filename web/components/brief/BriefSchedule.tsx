"use client";

/**
 * BriefSchedule — PX-6's wire-or-delete sweep, on the WIRE side.
 *
 * "Push me this briefing on a schedule" was a fully built capability with no form:
 * five typed client wrappers (list / create / update / delete / test) sat in
 * lib/api.ts with zero callers while the backend ran the cron. This card is the
 * missing form. A delivery rides an existing Notifications trigger (webhook /
 * Slack / Jira) — when none exists, the honest state names that door instead of
 * offering a create that cannot deliver anywhere.
 */

import { useCallback, useEffect, useState } from "react";
import {
  createBriefSubscription, deleteBriefSubscription, getActionTriggers,
  getBriefSubscriptions, testBriefSubscription, updateBriefSubscription,
  type ActionTrigger, type BriefSubscription,
} from "@/lib/api";
import { formatTimestamp } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";

const CRON_PRESETS: { label: string; cron: string }[] = [
  { label: "Weekdays 8:00 UTC", cron: "0 8 * * 1-5" },
  { label: "Daily 8:00 UTC", cron: "0 8 * * *" },
  { label: "Mondays 8:00 UTC", cron: "0 8 * * 1" },
];

const field: React.CSSProperties = {
  background: "var(--bg-1)", border: "1px solid var(--b1)", borderRadius: "var(--r2)",
  color: "var(--t1)", padding: "5px 8px",
};

export function BriefSchedule({ connId }: { connId: string }) {
  const [subs, setSubs] = useState<BriefSubscription[]>([]);
  const [triggers, setTriggers] = useState<ActionTrigger[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [note, setNote] = useState("");
  const [form, setForm] = useState({ name: "", period: "week" as "week" | "day",
    send_cron: CRON_PRESETS[0].cron, trigger_id: "" });

  const load = useCallback(async () => {
    try {
      const [s, t] = await Promise.all([
        getBriefSubscriptions(connId), getActionTriggers().catch(() => []),
      ]);
      setSubs(s);
      setTriggers(t.filter(x => x.enabled));
      setForm(f => ({ ...f, trigger_id: f.trigger_id || t.find(x => x.enabled)?.id || "" }));
      setErr("");
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setLoaded(true); }
  }, [connId]);
  useEffect(() => { load(); }, [load]);

  const run = async (fn: () => Promise<unknown>, done: string) => {
    setBusy(true); setErr(""); setNote("");
    try { await fn(); setNote(done); await load(); }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };

  return (
    <div className="aug-fs-sm" style={{ border: "1px solid var(--b0)", borderRadius: "var(--r3)",
      background: "var(--bg-2)", padding: 12, margin: "0 0 16px" }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 8 }}>
        <span style={{ fontWeight: 600, color: "var(--t1)" }}>Scheduled delivery</span>
        <span className="aug-fs-xs" style={{ color: "var(--t4)" }}>
          this briefing, pushed to a Notifications trigger on a cron
        </span>
      </div>

      {loaded && subs.length === 0 && triggers.length === 0 && (
        <EmptyState variant="inline"
          title="No delivery triggers exist yet — a schedule needs somewhere to send.">
          Create a webhook or Slack trigger under Operations ▸ Notifications first;
          this form will then offer it.
        </EmptyState>
      )}

      {subs.map(s => (
        <div key={s.id} style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap",
          padding: "6px 10px", border: "1px solid var(--b1)", borderRadius: "var(--r2)",
          background: "var(--bg-1)", marginBottom: 6 }}>
          <span style={{ color: "var(--t1)", fontWeight: 500 }}>{s.name}</span>
          <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>
            {s.period === "week" ? "weekly brief" : "daily brief"} ·{" "}
            <span style={{ fontFamily: "var(--font-mono)" }}>{s.send_cron}</span>
          </span>
          <span className="aug-fs-xs" style={{ color: s.last_status === "ok" ? "var(--grn4)"
            : s.last_status ? "var(--red4)" : "var(--t4)" }}>
            {s.last_sent_at
              ? `last sent ${formatTimestamp(s.last_sent_at, "short")} · ${s.last_status}`
              : "never sent yet"}
          </span>
          {s.last_error && (
            <span className="aug-fs-xs" style={{ color: "var(--red4)" }} title={s.last_error}>
              {s.last_error.slice(0, 60)}
            </span>
          )}
          <span style={{ flex: 1 }} />
          <Button size="xs" variant="ghost" disabled={busy}
            onClick={() => run(() => updateBriefSubscription(s.id, {
              conn_id: s.conn_id, name: s.name, trigger_id: s.trigger_id,
              period: s.period, send_cron: s.send_cron, enabled: !s.enabled,
            }), s.enabled ? "Paused." : "Resumed.")}>
            {s.enabled ? "Pause" : "Resume"}
          </Button>
          <Button size="xs" variant="ghost" disabled={busy}
            onClick={() => run(() => testBriefSubscription(s.id),
              "Test delivery sent — the result is on the row after reload.")}>
            Send a test
          </Button>
          <Button size="xs" variant="ghost" disabled={busy}
            className="text-zinc-500 hover:text-red-400"
            onClick={() => run(() => deleteBriefSubscription(s.id), "Removed.")}>
            Remove
          </Button>
        </div>
      ))}

      {triggers.length > 0 && (
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginTop: 8 }}>
          <input style={{ ...field, width: 180 }} placeholder="Name this delivery"
            value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} />
          <select style={field} value={form.period}
            onChange={e => setForm(f => ({ ...f, period: e.target.value as "week" | "day" }))}>
            <option value="week">weekly brief</option>
            <option value="day">daily brief</option>
          </select>
          <select style={field} value={form.send_cron}
            onChange={e => setForm(f => ({ ...f, send_cron: e.target.value }))}>
            {CRON_PRESETS.map(p => <option key={p.cron} value={p.cron}>{p.label}</option>)}
          </select>
          <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>to</span>
          <select style={field} value={form.trigger_id}
            onChange={e => setForm(f => ({ ...f, trigger_id: e.target.value }))}>
            {triggers.map(t => <option key={t.id} value={t.id}>{t.name} ({t.type})</option>)}
          </select>
          <Button size="sm" disabled={busy || !form.name.trim() || !form.trigger_id}
            onClick={() => run(() => createBriefSubscription({
              conn_id: connId, name: form.name.trim(), trigger_id: form.trigger_id,
              period: form.period, send_cron: form.send_cron, enabled: true,
            }), "Scheduled — the first delivery follows the cron.")}>
            Schedule it
          </Button>
        </div>
      )}
      {note && <p className="aug-fs-xs" style={{ color: "var(--grn4)", margin: "8px 0 0" }}>{note}</p>}
      {err && <p className="aug-fs-xs" style={{ color: "var(--red4)", margin: "8px 0 0" }}>{err}</p>}
    </div>
  );
}
