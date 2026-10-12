"use client";

/**
 * OrgPrioritiesSection — Settings ▸ Organization ▸ "This quarter's priorities" (CB-6, 2026-09-23).
 *
 * What the organisation is trying to do now, written by people and never inferred: each row names a
 * metric, a target, which way is good, and by when. Triage ranks a finding that bears on one higher,
 * and the Briefing says which goal a cited finding bears on. Saved with the organisation settings.
 *
 * A card (CLARITY, 2026-10-12): the count and the one tool at the label's right end, a row per priority, and one
 * muted line when there is none.
 */
import type { Priority } from "@/lib/api";
import { Card, Empty } from "@/components/clarity/kit";
import { Button } from "@/components/ui/button";
import { SelectField } from "@/components/ui/select";
import { Input } from "@/components/ui/input";

import { Field } from "./settings/parts";

const EMPTY_ROW: Priority = { metric: "", target: "", direction: "", by: "", note: "" };

export function OrgPrioritiesSection({ value, onChange }: { value: Priority[]; onChange: (next: Priority[]) => void }) {
  const rows = value ?? [];
  const set = (i: number, patch: Partial<Priority>) => onChange(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  return (
    <Card label="This quarter's priorities" ariaLabel="This quarter's priorities"
      right={<>
        {rows.length > 0 && <span>{rows.length}</span>}
        <Button size="xs" variant="ghost" onClick={() => onChange([...rows, { ...EMPTY_ROW }])}>Add a priority</Button>
      </>}>
      {rows.length === 0 && (
        <Empty>A finding that bears on a priority ranks higher, and the Briefing says which goal it bears on.</Empty>
      )}
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {rows.map((r, i) => (
          // A priority has no id of its own until it is saved; its place in the list is what the editor addresses.
          <div key={i} data-testid="priority-row" style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "flex-end" }}>
            <div style={{ flex: "2 1 160px", minWidth: 0 }}><Field label="metric">
              <Input aria-label={`Priority ${i + 1} metric`} value={r.metric} placeholder="return rate"
                onChange={e => set(i, { metric: e.target.value })} />
            </Field></div>
            <div style={{ flex: "1 1 90px", minWidth: 0 }}><Field label="target">
              <Input aria-label={`Priority ${i + 1} target`} value={r.target} placeholder="< 8%"
                onChange={e => set(i, { target: e.target.value })} />
            </Field></div>
            <div style={{ flex: "1 1 110px", minWidth: 0 }}><Field label="good when">
              <SelectField aria-label={`Priority ${i + 1} direction`} value={r.direction}
                onChange={e => set(i, { direction: e.target.value as Priority["direction"] })}>
                <option value="">(unsaid)</option>
                <option value="up">up</option>
                <option value="down">down</option>
              </SelectField>
            </Field></div>
            <div style={{ flex: "1 1 80px", minWidth: 0 }}><Field label="by">
              <Input aria-label={`Priority ${i + 1} by`} value={r.by} placeholder="Q4"
                onChange={e => set(i, { by: e.target.value })} />
            </Field></div>
            <Button size="sm" variant="ghost" onClick={() => onChange(rows.filter((_, j) => j !== i))}>Remove</Button>
          </div>
        ))}
      </div>
    </Card>
  );
}
