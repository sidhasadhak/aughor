"use client";

/**
 * The sliders of a what-if on a dashboard made from a file. Each is one of the dashboard's values a query card reads as `{{name}}`,
 * bound by the engine, and the reader's own. "As it is" puts each back where the scenario equals the file, a promise the draft
 * was held to before it was offered (`aughor/sheets/dashboard_draft.py`). It says it is a scenario, because none of this is data.
 */
import { useState } from "react";

import { usePieces } from "@/components/dashboards/OntologyPieces";
import { Segmented } from "@/components/ui/segmented";
import { formatCount, pct } from "@/lib/format";
import { withUniqueKeys } from "@/lib/listKeys";

interface Slider { min: number; max: number; step: number; unit: "percent" | "number" }
export interface ScenarioPreset { label: string; values: Record<string, number> }

const AS_IT_IS = "As it is";
const said = (v: number, unit: string) => (unit === "percent" ? pct(v, Math.abs(v * 100 - Math.round(v * 100)) < 1e-9 ? 0 : 1) : formatCount(v));

export function ScenarioInputsPiece({ values, presets }: { values: string[]; presets: ScenarioPreset[] }) {
  const { wire, valueOf, setValue } = usePieces();
  const inputs = values.map(name => {
    const def = wire.values?.[name];
    const slider = def?.from?.by === "reader" ? (def.from as { slider?: Slider | null }).slider ?? null : null;
    const now = valueOf(name);
    const start = typeof def?.value === "number" ? def.value : 0;
    return { name, label: def?.label ?? name, slider, start, value: "value" in now && typeof now.value === "number" ? now.value : start };
  }).filter(i => i.slider);
  const asItIs: ScenarioPreset = { label: AS_IT_IS, values: Object.fromEntries(inputs.map(i => [i.name, i.start])) };
  const all = [asItIs, ...presets.filter(p => p.label !== AS_IT_IS)];
  const matches = (p: ScenarioPreset) => inputs.every(i => (p.values[i.name] ?? i.start) === i.value);
  const on = all.find(matches)?.label ?? "";
  const apply = (label: string) => {
    const p = all.find(x => x.label === label);
    if (!p) return;
    for (const i of inputs) setValue(i.name, (p.values[i.name] ?? i.start) === i.start ? undefined : p.values[i.name]);
  };
  return (
    <div data-testid="scenario-inputs" style={{ background: "var(--bg-2)", border: "1px solid var(--card-edge)", borderRadius: "var(--r3)", padding: "12px 16px" }}>
      {all.length > 1 && (
        <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 10 }}>
          <Segmented label="Scenarios" value={on} options={all.map(p => ({ value: p.label, label: p.label }))} onChange={apply} />
        </div>
      )}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 12 }}>
        {withUniqueKeys(inputs, i => i.name).map(([key, i]) => (
          <Input key={key} label={i.label} slider={i.slider!} start={i.start} value={i.value}
            onSet={v => setValue(i.name, v === i.start ? undefined : v)} />
        ))}
      </div>
    </div>
  );
}

/** One slider. Its number follows the thumb as it moves; the cards read again when it lands, not at every step along the way. */
function Input({ label, slider, start, value, onSet }: { label: string; slider: Slider; start: number; value: number; onSet: (v: number) => void }) {
  const [moving, setMoving] = useState<number | null>(null);
  const shown = moving ?? value;
  const land = () => { if (moving !== null) { onSet(moving); setMoving(null); } };
  return (
    <label data-testid="scenario-input" style={{ display: "block", background: "var(--bg-3)", border: "1px solid var(--b0)", borderRadius: "var(--r2)", padding: "10px 12px" }}>
      <span style={{ display: "flex", justifyContent: "space-between", fontWeight: 500 }}>
        <span>{label}</span><span data-testid="scenario-input-value" style={{ fontVariantNumeric: "tabular-nums" }}>{said(shown, slider.unit)}</span>
      </span>
      <input type="range" className="aug-range" aria-label={label} min={slider.min} max={slider.max} step={slider.step} value={shown}
        style={{ width: "100%", margin: "8px 0 4px", display: "block",
          background: `linear-gradient(to right, var(--accent) ${((shown - slider.min) / (slider.max - slider.min)) * 100}%, var(--bg-4) 0)` }}
        onChange={e => setMoving(Number(e.target.value))} onPointerUp={land} onKeyUp={land} onBlur={land} />
      <span className="aug-fs-sm" style={{ color: "var(--t3)" }}>In your file: {said(start, slider.unit)}</span>
    </label>
  );
}
