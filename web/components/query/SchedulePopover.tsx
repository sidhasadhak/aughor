"use client";

/**
 * SE-8D — Schedule, in place. Databricks' editor schedules a query from a small
 * "Add schedule" menu on the button itself; ours used to stash the SQL and navigate
 * to Monitors, which is a page away from the result the user is looking at.
 *
 * This popover creates the monitor RIGHT HERE: a name, a cadence (the same presets
 * the Monitors form offers, plus raw cron), create. What it deliberately does NOT
 * offer is thresholds: the platform's own rule since SE-4 I is that an invented
 * threshold is an alert that fires at 3am for a number nobody chose. The quick path
 * is `any_change` — run on the cadence, record the value, say so when it moves —
 * and it SAYS that on the popover; anything smarter (thresholds, anomaly, drift)
 * goes through "Open in Monitors", which arrives with the SQL already filled.
 *
 * The button reads Schedule (n) once the schedules for THIS statement are known —
 * Databricks' own label. Matching is on the monitor's SQL, whitespace-normalised:
 * a schedule belongs to a statement, not to a tab.
 */
import { useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { createMonitor, getMonitors, type MonitorDef } from "@/lib/api";

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
  onOpenMonitors,
}: {
  connId: string;
  sql: string;
  /** The full Monitors form (thresholds, anomaly, drift), pre-filled with this SQL. */
  onOpenMonitors?: (sql: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [mine, setMine] = useState<MonitorDef[] | null>(null);
  const [name, setName] = useState("");
  const [cron, setCron] = useState("0 9 * * *");
  const [customCron, setCustomCron] = useState(false);
  const [state, setState] = useState<"idle" | "busy" | "fail">("idle");

  // The count on the label — read whenever the statement changes. A list request per
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

  useEffect(() => {
    if (!open) return;
    setName(suggestName(sql));
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, sql]);

  const count = mine?.length ?? 0;
  const label = useMemo(
    () => count > 0 ? `Schedule (${count})` : "Schedule",
    [count],
  );

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

  return (
    <span style={{ position: "relative" }}>
      <Button
        variant="ghost" size="xs" className="aug-fs-ui"
        title="Run this query on a schedule"
        onClick={() => setOpen(v => !v)}
        data-testid="results-schedule"
      >
        {label}
      </Button>
      {open && (
        <>
          <div style={{ position: "fixed", inset: 0, zIndex: 40 }} onClick={() => setOpen(false)} />
          <div className="aug-fs-ui" style={{
            position: "absolute", bottom: "100%", right: 0, zIndex: 41, marginBottom: 6,
            width: 300, padding: "10px 12px", background: "var(--bg-2)",
            border: "1px solid var(--b2)", borderRadius: "var(--r2)", boxShadow: "var(--shadow-md)",
          }}>
            {(mine?.length ?? 0) > 0 && (
              <div style={{ marginBottom: 8 }}>
                <div className="aug-label" style={{ marginBottom: 4 }}>Scheduled</div>
                {mine!.map(m => (
                  <div key={m.id} style={{ display: "flex", alignItems: "baseline", gap: 6, padding: "1px 0" }}>
                    <span style={{ color: "var(--t2)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{m.name}</span>
                    <span className="font-mono aug-fs-xs" style={{ color: "var(--t3)", flexShrink: 0 }}>{m.check_cron}</span>
                    {!m.enabled && <span className="aug-fs-xs" style={{ color: "var(--amb4)", flexShrink: 0 }}>paused</span>}
                  </div>
                ))}
              </div>
            )}

            <div className="aug-label" style={{ marginBottom: 6 }}>Add schedule</div>
            <input
              className="aug-input aug-fs-ui" style={{ width: "100%", marginBottom: 6 }}
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
              <input
                className="aug-input aug-fs-ui font-mono" style={{ width: "100%", marginBottom: 6 }}
                value={cron} onChange={e => setCron(e.target.value)}
                placeholder="m h dom mon dow"
              />
            )}
            <p className="aug-fs-xs" style={{ color: "var(--t3)", margin: "0 0 8px" }}>
              Runs the query on this cadence (server time), records the first cell as the
              tracked value, and alerts when it changes. Thresholds and anomaly rules
              live in Monitors.
            </p>
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <Button variant="default" size="xs" className="aug-fs-ui"
                disabled={state === "busy" || !name.trim() || !cron.trim()}
                onClick={() => void create()}>
                {state === "busy" ? "Creating…" : state === "fail" ? "Failed — retry" : "Create"}
              </Button>
              <span style={{ flex: 1 }} />
              {onOpenMonitors && (
                <Button variant="ghost" size="xs" className="aug-fs-ui"
                  title="The full form — thresholds, anomaly, drift — with this SQL filled in"
                  onClick={() => { setOpen(false); onOpenMonitors(sql); }}>
                  Open in Monitors <Icon name="next" size={11} />
                </Button>
              )}
            </div>
          </div>
        </>
      )}
    </span>
  );
}
