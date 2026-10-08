"use client";

/**
 * PeriodPicker — the one control a cockpit is read by: which period its cards are cut to (Arc
 * CT; the user's mock, 2026-09-28). The Briefing's `RangeControl` lays every choice out as a
 * button; a cockpit is looked at more than it is steered, so here the choice is one menu and
 * what it shows is the period itself, as the server resolved it — "July 2026 · final".
 */
import { useState } from "react";

import type { RangeChoice } from "@/components/brief/BriefRange";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger } from "@/components/ui/select";
import type { CockpitRange } from "@/lib/api";
import { Input } from "@/components/ui/input";

// "Current" is the period under way and "last" the one before (the user, 2026-10-08). Each is read
// only over days whose data has arrived: the server reads where the data ends, so a current day on
// a source a day behind is yesterday, and the range says so.
const CHOICES: { v: string; t: string }[] = [
  { v: "standing", t: "As written" },
  { v: "current_day", t: "Current day" },
  { v: "current_week", t: "Current week" },
  { v: "current_month", t: "Current month" },
  { v: "current_year", t: "Current year" },
  { v: "previous_week", t: "Last week" },
  { v: "previous_month", t: "Last month" },
  { v: "previous_year", t: "Last year" },
  { v: "custom", t: "Custom range…" },
];

const STATUS: Record<CockpitRange["status"], string> = {
  standing: "", final: "final", provisional: "provisional", to_date: "to date",
};

/** The chosen period's name — "Current week", or a custom range's days. */
export function choiceName(value: RangeChoice): string {
  if (value.preset === "custom" && value.start && value.end) return `${value.start} to ${value.end}`;
  return CHOICES.find(c => c.v === value.preset)?.t ?? "Custom range";
}

/** What the trigger says: the period as the server resolved it, and whether it has settled. While
 *  the chosen period is still being read, its name — never the period read before it. */
export function periodWords(value: RangeChoice, showing: CockpitRange | null, reading = false): string {
  if (value.preset === "standing") return "As written";
  const name = choiceName(value);
  if (reading) return `${name} · reading…`;
  if (showing && showing.status !== "standing" && showing.covers) return `${showing.covers} · ${STATUS[showing.status]}`;
  return name;
}

export function PeriodPicker({ value, onChange, showing, disabled, reading = false }: {
  value: RangeChoice;
  onChange: (c: RangeChoice) => void;
  /** The range the cards on screen were read for; null while none is read. */
  showing: CockpitRange | null;
  disabled?: boolean;
  /** The chosen period is being read: what is on screen is still the period before it. */
  reading?: boolean;
}) {
  const [custom, setCustom] = useState(value.preset === "custom");
  const [start, setStart] = useState(value.preset === "custom" ? value.start ?? "" : "");
  const [end, setEnd] = useState(value.preset === "custom" ? value.end ?? "" : "");
  const ready = !!start && !!end && start <= end;
  const items = Object.fromEntries(CHOICES.map(c => [c.v, c.t]));
  return (
    <span data-testid="cockpit-period" style={{ display: "inline-flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
      <span className="aug-fs-sm" style={{ color: "var(--t2)" }}>Period</span>
      <Select value={custom ? "custom" : value.preset} items={items} disabled={disabled}
        onValueChange={v => {
          const next = String(v ?? "");
          if (next === "custom") { setCustom(true); return; }
          setCustom(false);
          onChange({ preset: next } as RangeChoice);
        }}>
        <SelectTrigger aria-label="Cockpit period" style={{ minWidth: 180 }}>
          <span data-testid="cockpit-range">{custom && value.preset !== "custom" ? "Custom range…" : periodWords(value, showing, reading)}</span>
        </SelectTrigger>
        <SelectContent>
          {CHOICES.map(c => <SelectItem key={c.v} value={c.v}>{c.t}</SelectItem>)}
        </SelectContent>
      </Select>
      {custom && (
        <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
          <Input type="date" aria-label="First day" value={start} max={end || undefined}
            onChange={e => setStart(e.target.value)} />
          <span className="aug-fs-sm" style={{ color: "var(--t3)" }}>to</span>
          <Input type="date" aria-label="Last day" value={end} min={start || undefined}
            onChange={e => setEnd(e.target.value)} />
          <Button size="sm" variant="secondary" disabled={disabled || !ready}
            onClick={() => onChange({ preset: "custom", start, end })}>
            Show
          </Button>
        </span>
      )}
    </span>
  );
}
