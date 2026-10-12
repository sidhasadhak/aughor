"use client";

/**
 * SE-8D — Schedule, in place. A query should be schedulable from where its result is;
 * ours used to stash the SQL and navigate
 * to Monitors, which is a page away from the result the user is looking at.
 *
 * This popover creates the monitor RIGHT HERE: a name, a cadence (the same presets
 * the Monitors form offers, plus raw cron), create. What it deliberately does NOT
 * offer is thresholds: the platform's own rule since SE-4 I is that an invented
 * threshold is an alert that fires at 3am for a number nobody chose. The quick path
 * is `any_change` — run on the cadence, record the value, say so when it moves —
 * and it SAYS that on the popover, as chips; anything smarter (thresholds, anomaly, drift)
 * goes through "Open in Monitors", which arrives with the SQL already filled.
 *
 * It holds no button of its own since the editor was redone to CLARITY (2026-10-12): the result's Tools ▾ opens it,
 * and reads "Schedule (n)" from `onCount` once the schedules for THIS statement are known. Matching is on the
 * monitor's SQL, whitespace-normalised: a schedule belongs to a statement, not to a tab.
 */
import { useEffect, useState } from "react";
import { Chip, Label } from "@/components/clarity/kit";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { createMonitor, getMonitors, type MonitorDef } from "@/lib/api";
import { Input } from "@/components/ui/input";

const CRON_PRESETS = [
  { label: "Hourly", cron: "0 * * * *" },
  { label: "Every 6h", cron: "0 */6 * * *" },
  { label: "Daily 9:00", cron: "0 9 * * *" },
  { label: "Weekly Mon 9:00", cron: "0 9 * * 1" },
];

function normSql(sql: string): string {
  return (sql || "").replace(/\s+/g, " ").trim().replace(/;$/, "");
}

/** A first-guess monitor name from the SQL. */
function suggestName(sql: string): string {
  const m = /\bfrom\s+([A-Za-z_][\w.]*)/i.exec(sql);
  return m ? `Watch — ${m[1]}` : "Watch — query";
}

export function SchedulePopover({
  connId,
  sql,
  open,
  onOpenChange,
  onCount,
  onOpenMonitors,
}: {
  connId: string;
  sql: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** How many schedules this statement already has, once read — the menu's "Schedule (n)". */
  onCount?: (n: number) => void;
  /** The full Monitors form (thresholds, anomaly, drift), pre-filled with this SQL. */
  onOpenMonitors?: (sql: string) => void;
}) {
  const [mine, setMine] = useState<MonitorDef[] | null>(null);
  const [name, setName] = useState("");
  const [cron, setCron] = useState("0 9 * * *");
  const [customCron, setCustomCron] = useState(false);
  const [state, setState] = useState<"idle" | "busy" | "fail">("idle");
  const setOpen = onOpenChange;

  // The count on the menu — read whenever the statement changes. A list request per
  // run mirrors what the history rail already does with the audit log.
  useEffect(() => {
    let alive = true;
    if (!connId || !sql.trim()) { setMine(null); return; }
    getMonitors(connId)
      .then(all => {
        if (!alive) return;
        const want = normSql(sql);
        setMine(all.filter(m => m.custom_sql && normSql(m.custom_sql) === want));
      })
      .catch(() => { if (alive) setMine(null); });
    return () => { alive = false; };
  }, [connId, sql]);

  const count = mine?.length ?? 0;
  useEffect(() => { onCount?.(count); }, [count, onCount]);

  useEffect(() => {
    if (!open) return;
    setName(suggestName(sql));
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, sql, setOpen]);

  const create = async () => {
    if (!connId || !sql.trim() || !name.trim() || !cron.trim()) return;
    setState("busy");
    try {
      const m = await createMonitor({
        conn_id: connId,
        name: name.trim(),
        custom_sql: sql,
        check_cron: cron.trim(),
        alert_on: "any_change",
        notification_channel: "in_app",
        enabled: true,
      });
      setMine(prev => [...(prev ?? []), m]);
      setState("idle");
      setOpen(false);
    } catch {
      setState("fail");
      setTimeout(() => setState("idle"), 2000);
    }
  };

  if (!open) return null;
  return (
    <>
      <div style={{ position: "fixed", inset: 0, zIndex: 40 }} onClick={() => setOpen(false)} />
      <div className="aug-fs-ui" data-testid="schedule-popover" style={{
        position: "absolute", top: "100%", right: 0, zIndex: 41, marginTop: 6,
        width: 300, padding: "10px 12px", background: "var(--bg-2)",
        border: "1px solid var(--b2)", borderRadius: "var(--r2)", boxShadow: "var(--shadow-md)",
      }}>
        {(mine?.length ?? 0) > 0 && (
          <div style={{ marginBottom: 8 }}>
            <Label right={mine!.length}>Scheduled</Label>
            {mine!.map(m => (
              <div key={m.id} style={{ display: "flex", alignItems: "baseline", gap: 6, padding: "1px 0" }}>
                <span style={{ color: "var(--t2)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{m.name}</span>
                <span className="font-mono aug-fs-xs" style={{ color: "var(--t3)", flexShrink: 0 }}>{m.check_cron}</span>
                {!m.enabled && <span className="aug-fs-xs" style={{ color: "var(--amb4)", flexShrink: 0 }}>paused</span>}
              </div>
            ))}
          </div>
        )}

        <Label>Add schedule</Label>
        <Input style={{ width: "100%", marginBottom: 6 }}
          value={name} onChange={e => setName(e.target.value)} placeholder="Schedule name"
        />
        <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginBottom: 6 }}>
          {CRON_PRESETS.map(p => (
            <Button key={p.cron} size="xs" className="aug-fs-ui"
              variant={!customCron && cron === p.cron ? "secondary" : "ghost"}
              onClick={() => { setCron(p.cron); setCustomCron(false); }}>
              {p.label}
            </Button>
          ))}
          <Button size="xs" className="aug-fs-ui"
            variant={customCron ? "secondary" : "ghost"}
            onClick={() => setCustomCron(true)}>
            Cron…
          </Button>
        </div>
        {customCron && (
          <Input style={{ width: "100%", marginBottom: 6 }}
            value={cron} onChange={e => setCron(e.target.value)}
            placeholder="m h dom mon dow"
          />
        )}
        {/* What a quick schedule does, as facts: it runs on the server's clock, tracks the first cell, and alerts on
            any change of it. Thresholds and anomaly rules are Monitors' — the door at the foot. */}
        <div style={{ display: "flex", flexWrap: "wrap", gap: 4, margin: "0 0 8px" }}>
          <Chip>server time</Chip>
          <Chip title="The first cell of the result is the value it tracks">tracks the first cell</Chip>
          <Chip>alerts on any change</Chip>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <Button variant="default" size="xs" className="aug-fs-ui"
            disabled={state === "busy" || !name.trim() || !cron.trim()}
            onClick={() => void create()}>
            {state === "busy" ? "Creating…" : state === "fail" ? "Failed — retry" : "Create"}
          </Button>
          <span style={{ flex: 1 }} />
          {onOpenMonitors && (
            <Button variant="ghost" size="xs" className="aug-fs-ui"
              title="Thresholds, anomaly and drift rules — the full form, with this SQL filled in"
              onClick={() => { setOpen(false); onOpenMonitors(sql); }}>
              Open in Monitors <Icon name="next" size={11} />
            </Button>
          )}
        </div>
      </div>
    </>
  );
}
