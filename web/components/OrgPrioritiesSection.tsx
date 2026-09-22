"use client";

/**
 * OrgPrioritiesSection — Settings ▸ Organization ▸ "This quarter's priorities" (CB-6, 2026-09-23).
 *
 * What the organisation is trying to do now, written by people and never inferred: each row names a
 * metric, a target, which way is good, and by when. Triage ranks a finding that bears on one higher,
 * and the Briefing says which goal a cited finding bears on. Saved with the organisation settings.
 */
import type { Priority } from "@/lib/api";
import { Button } from "@/components/ui/button";

const EMPTY_ROW: Priority = { metric: "", target: "", direction: "", by: "", note: "" };

export function OrgPrioritiesSection({ value, onChange }: { value: Priority[]; onChange: (next: Priority[]) => void }) {
  const rows = value ?? [];
  const set = (i: number, patch: Partial<Priority>) => onChange(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  return (
    <section aria-label="This quarter's priorities" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div>
        <h3 className="text-sm font-medium text-zinc-200">This quarter's priorities</h3>
        <p className="aug-fs-xs text-zinc-500">
          What the organisation is trying to do now, in your words. A finding that bears on one ranks higher in the Briefing, and the brief says which goal it bears on.
        </p>
      </div>
      {rows.map((r, i) => (
        <div key={i} className="flex flex-wrap items-end gap-2" data-testid="priority-row">
          <label className="flex flex-col aug-fs-xs text-zinc-500">metric
            <input className="aug-input" aria-label={`Priority ${i + 1} metric`} value={r.metric} placeholder="return rate"
              onChange={e => set(i, { metric: e.target.value })} />
          </label>
          <label className="flex flex-col aug-fs-xs text-zinc-500">target
            <input className="aug-input" aria-label={`Priority ${i + 1} target`} value={r.target} placeholder="< 8%"
              onChange={e => set(i, { target: e.target.value })} />
          </label>
          <label className="flex flex-col aug-fs-xs text-zinc-500">good when
            <select className="aug-input" aria-label={`Priority ${i + 1} direction`} value={r.direction}
              onChange={e => set(i, { direction: e.target.value as Priority["direction"] })}>
              <option value="">(unsaid)</option>
              <option value="up">up</option>
              <option value="down">down</option>
            </select>
          </label>
          <label className="flex flex-col aug-fs-xs text-zinc-500">by
            <input className="aug-input" aria-label={`Priority ${i + 1} by`} value={r.by} placeholder="Q4"
              onChange={e => set(i, { by: e.target.value })} />
          </label>
          <Button size="sm" variant="ghost" onClick={() => onChange(rows.filter((_, j) => j !== i))}>Remove</Button>
        </div>
      ))}
      <div>
        <Button size="sm" variant="secondary" onClick={() => onChange([...rows, { ...EMPTY_ROW }])}>Add a priority</Button>
      </div>
    </section>
  );
}
