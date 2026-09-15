"use client";

/**
 * ScheduleEditor — the schedule trigger as a person states one, not as cron.
 *
 * The user's screenshot (2026-09-15): the When drawer rendered "Daily" beside a bare
 * text box holding "0 9" — a cron fragment doing the work of a time control, crammed
 * sideways into a 312px rail. This editor states the same fact the way it is said:
 * an occurrence (hourly · daily · weekly · monthly), a real time control, weekday or
 * day-of-month pickers where the occurrence needs one, and a plain-words summary with
 * the clock named — UTC, because that is what the scheduler evaluates today (SP-13
 * moves it to the reader's timezone; lying about that here would arm a 9am that fires
 * at 7). Custom keeps the raw cron one click away: the field is the truth, and a
 * shape this editor cannot say (steps, ranges) round-trips through it untouched.
 */

import React from "react";

import { Button } from "@/components/ui/button";
import { inputStyle } from "@/components/automations/AutomationRows";

type Occurrence = "hourly" | "daily" | "weekly" | "monthly" | "custom";

export type ScheduleShape = {
  occurrence: Occurrence;
  /** "HH:MM" for daily/weekly/monthly; minute-of-hour for hourly. */
  time: string;
  minute: number;
  /** Cron weekday numbers, 0/7=Sun … 6=Sat, ascending. Weekly only. */
  weekdays: number[];
  /** 1–28. Monthly only — days every month has, so a schedule never silently skips. */
  dayOfMonth: number;
  /** The raw expression, always the saved truth. */
  cron: string;
};

const DAY_WORDS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTH_WORDS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

const two = (n: number) => String(n).padStart(2, "0");

/** Parse the cron shapes this platform writes; anything else is `custom`, untouched. */
export function parseCron(cron: string): ScheduleShape {
  const base: ScheduleShape = {
    occurrence: "custom", time: "09:00", minute: 0, weekdays: [1], dayOfMonth: 1,
    cron: cron.trim(),
  };
  const f = cron.trim().split(/\s+/);
  if (f.length !== 5) return base;
  const [m, h, dom, mon, dow] = f;
  const mi = /^\d{1,2}$/.test(m) ? Number(m) : NaN;
  const hi = /^\d{1,2}$/.test(h) ? Number(h) : NaN;
  const ok = (n: number, max: number) => Number.isInteger(n) && n >= 0 && n <= max;

  if (ok(mi, 59) && h === "*" && dom === "*" && mon === "*" && dow === "*") {
    return { ...base, occurrence: "hourly", minute: mi };
  }
  if (!ok(mi, 59) || !ok(hi, 23) || mon !== "*") return base;
  const time = `${two(hi)}:${two(mi)}`;
  if (dom === "*" && dow === "*") return { ...base, occurrence: "daily", time };
  if (dom === "*" && /^\d(,\d)*$/.test(dow.replace(/7/g, "0"))) {
    const days = [...new Set(dow.split(",").map(d => Number(d) % 7))].sort();
    if (days.every(d => d >= 0 && d <= 6)) {
      return { ...base, occurrence: "weekly", time, weekdays: days };
    }
    return base;
  }
  if (dow === "*" && /^\d{1,2}$/.test(dom) && Number(dom) >= 1 && Number(dom) <= 28) {
    return { ...base, occurrence: "monthly", time, dayOfMonth: Number(dom) };
  }
  return base;
}

export function toCron(s: ScheduleShape): string {
  const [h, m] = (s.time || "09:00").split(":").map(Number);
  switch (s.occurrence) {
    case "hourly": return `${s.minute} * * * *`;
    case "daily": return `${m} ${h} * * *`;
    case "weekly": return `${m} ${h} * * ${(s.weekdays.length ? s.weekdays : [1]).join(",")}`;
    case "monthly": return `${m} ${h} ${s.dayOfMonth} * *`;
    default: return s.cron;
  }
}

/** The schedule in the words a person would say it — the clock always named. */
export function cronWords(cron: string): string {
  const s = parseCron(cron);
  switch (s.occurrence) {
    case "hourly": return `Every hour at minute ${s.minute}`;
    case "daily": return `Every day at ${s.time} UTC`;
    case "weekly": {
      const days = s.weekdays.map(d => DAY_WORDS[d]).join(", ");
      return `Every ${days} at ${s.time} UTC`;
    }
    case "monthly": return `Monthly on day ${s.dayOfMonth} at ${s.time} UTC`;
    default: return cron ? `On the cron schedule ${cron} (UTC)` : "";
  }
}

/** The next fire, computed only for the shapes whose next fire is trivial arithmetic —
 *  a custom expression gets no guess, because a wrong next-run is worse than none. */
export function nextFireUtc(cron: string, now = new Date()): Date | null {
  const s = parseCron(cron);
  if (s.occurrence === "custom") return null;
  const [h, m] = (s.time || "09:00").split(":").map(Number);
  const t = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate(),
    s.occurrence === "hourly" ? now.getUTCHours() : h,
    s.occurrence === "hourly" ? s.minute : m, 0, 0));
  const stepDay = () => t.setUTCDate(t.getUTCDate() + 1);
  if (s.occurrence === "hourly") {
    if (t <= now) t.setUTCHours(t.getUTCHours() + 1);
    return t;
  }
  if (s.occurrence === "daily") {
    if (t <= now) stepDay();
    return t;
  }
  if (s.occurrence === "weekly") {
    const days = s.weekdays.length ? s.weekdays : [1];
    for (let i = 0; i < 8; i++) {
      if (t > now && days.includes(t.getUTCDay())) return t;
      stepDay();
    }
    return t;
  }
  // monthly
  t.setUTCDate(s.dayOfMonth);
  if (t <= now) t.setUTCMonth(t.getUTCMonth() + 1, s.dayOfMonth);
  return t;
}

const fieldLabel: React.CSSProperties = {
  fontSize: 11, fontWeight: 600, color: "var(--t3)", textTransform: "uppercase",
  letterSpacing: "0.04em", display: "block", marginBottom: 3,
};

function DayChips({ value, onChange }: { value: number[]; onChange: (d: number[]) => void }) {
  const toggle = (d: number) => {
    const next = value.includes(d) ? value.filter(x => x !== d) : [...value, d].sort();
    // A weekly schedule with no day would never fire while looking armed — the last
    // selected day stays.
    if (next.length) onChange(next);
  };
  return (
    <div role="group" aria-label="Days of the week" style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
      {[1, 2, 3, 4, 5, 6, 0].map(d => {
        const on = value.includes(d);
        return (
          <Button key={d} variant="ghost" size="xs" onClick={() => toggle(d)}
            aria-pressed={on} className="aug-fs-xs h-auto font-normal"
            style={{
              padding: "4px 8px", borderRadius: "var(--r-pill)",
              border: `1px solid ${on ? "var(--blue3)" : "var(--b1)"}`,
              background: on ? "var(--blue1, var(--bg-3))" : "var(--bg-1, var(--bg-2))",
              color: on ? "var(--blue4)" : "var(--t2)", fontWeight: on ? 600 : 400,
            }}>
            {DAY_WORDS[d]}
          </Button>
        );
      })}
    </div>
  );
}

export function ScheduleEditor({ cron, onCron }: {
  cron: string;
  onCron: (cron: string) => void;
}) {
  const s = parseCron(cron);
  // A fresh schedule trigger arrives with no expression at all. Seed the default the
  // rest of the platform already uses (daily at 09:00 UTC) so the editor never shows
  // controls describing a schedule that is not there.
  React.useEffect(() => {
    if (!cron.trim()) onCron("0 9 * * *");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cron]);

  const put = (patch: Partial<ScheduleShape>) => onCron(toCron({ ...s, ...patch }));
  const next = nextFireUtc(cron);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ display: "flex", gap: 8 }}>
        <div style={{ flex: 1 }}>
          <label style={fieldLabel}>Repeats</label>
          <select value={s.occurrence} aria-label="How often"
            onChange={e => {
              const occurrence = e.target.value as Occurrence;
              if (occurrence === "custom") onCron(s.cron || toCron(s));
              else put({ occurrence });
            }}
            style={{ ...inputStyle, padding: "6px 8px" }}>
            <option value="hourly">Hourly</option>
            <option value="daily">Daily</option>
            <option value="weekly">Weekly</option>
            <option value="monthly">Monthly</option>
            <option value="custom">Custom (cron)</option>
          </select>
        </div>
        {(s.occurrence === "daily" || s.occurrence === "weekly" || s.occurrence === "monthly") && (
          <div>
            <label style={fieldLabel}>At (UTC)</label>
            <input type="time" value={s.time} aria-label="Time of day, UTC"
              onChange={e => e.target.value && put({ time: e.target.value })}
              style={{ ...inputStyle, padding: "5px 8px", width: 96 }} />
          </div>
        )}
        {s.occurrence === "hourly" && (
          <div>
            <label style={fieldLabel}>At minute</label>
            <input type="number" min={0} max={59} value={s.minute} aria-label="Minute of the hour"
              onChange={e => put({ minute: Math.min(59, Math.max(0, Number(e.target.value) || 0)) })}
              style={{ ...inputStyle, padding: "5px 8px", width: 72 }} />
          </div>
        )}
        {s.occurrence === "monthly" && (
          <div>
            <label style={fieldLabel}>On day</label>
            <select value={s.dayOfMonth} aria-label="Day of the month"
              onChange={e => put({ dayOfMonth: Number(e.target.value) })}
              style={{ ...inputStyle, padding: "6px 8px", width: 72 }}>
              {Array.from({ length: 28 }, (_, i) => i + 1).map(d =>
                <option key={d} value={d}>{d}</option>)}
            </select>
          </div>
        )}
      </div>

      {s.occurrence === "weekly" && (
        <div>
          <label style={fieldLabel}>On</label>
          <DayChips value={s.weekdays} onChange={weekdays => put({ weekdays })} />
        </div>
      )}

      {s.occurrence === "custom" && (
        <div>
          <label style={fieldLabel}>Cron expression (UTC)</label>
          <input style={inputStyle} value={cron} aria-label="Cron expression"
            onChange={e => onCron(e.target.value)} placeholder="e.g. 0 9 * * 1-5" />
        </div>
      )}

      {/* The schedule read back in words — what a person can check at a glance, with
          the clock named. The next run is stated only when its arithmetic is exact. */}
      <div className="aug-fs-xs" style={{ color: "var(--t3)", lineHeight: 1.5 }}>
        {cronWords(cron)}
        {next && (
          <> · next run {`${DAY_WORDS[next.getUTCDay()]} ${next.getUTCDate()} ${MONTH_WORDS[next.getUTCMonth()]}, ${two(next.getUTCHours())}:${two(next.getUTCMinutes())} UTC`}</>
        )}
      </div>
    </div>
  );
}
