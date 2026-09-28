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

const CHOICES: { v: string; t: string }[] = [
  { v: "standing", t: "As written" },
  { v: "yesterday", t: "Latest day" },
  { v: "last_week", t: "Latest week" },
  { v: "last_month", t: "Latest month" },
  { v: "last_year", t: "Latest year" },
  { v: "month_to_date", t: "Month to date" },
  { v: "year_to_date", t: "Year to date" },
  { v: "custom", t: "Custom range…" },
];

const STATUS: Record<CockpitRange["status"], string> = {
  standing: "", final: "final", provisional: "provisional", to_date: "to date",
};

/** What the trigger says: the period as the server resolved it, and whether it has settled. */
export function periodWords(value: RangeChoice, showing: CockpitRange | null): string {
  if (value.preset === "standing") return "As written";
  if (showing && showing.status !== "standing" && showing.covers) return `${showing.covers} · ${STATUS[showing.status]}`;
  return CHOICES.find(c => c.v === value.preset)?.t ?? "";
}

export function PeriodPicker({ value, onChange, showing, disabled }: {
  value: RangeChoice;
  onChange: (c: RangeChoice) => void;
  /** The range the cards on screen were read for; null while none is read. */
  showing: CockpitRange | null;
  disabled?: boolean;
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
          <span data-testid="cockpit-range">{custom && value.preset !== "custom" ? "Custom range…" : periodWords(value, showing)}</span>
        </SelectTrigger>
        <SelectContent>
          {CHOICES.map(c => <SelectItem key={c.v} value={c.v}>{c.t}</SelectItem>)}
        </SelectContent>
      </Select>
      {custom && (
        <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
          <input type="date" aria-label="First day" value={start} max={end || undefined}
            onChange={e => setStart(e.target.value)} className="aug-input aug-fs-sm" />
          <span className="aug-fs-sm" style={{ color: "var(--t3)" }}>to</span>
          <input type="date" aria-label="Last day" value={end} min={start || undefined}
            onChange={e => setEnd(e.target.value)} className="aug-input aug-fs-sm" />
          <Button size="sm" variant="secondary" disabled={disabled || !ready}
            onClick={() => onChange({ preset: "custom", start, end })}>
            Show
          </Button>
        </span>
      )}
    </span>
  );
}
