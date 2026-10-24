"use client";

/**
 * The look, chosen by one person: accent, grey, corners, scaling, edges and typeface (ROADMAP §6
 * items 44 and 53).
 *
 * The first four are the knobs of Radix Themes' own panel; edges and typeface are ours. A choice
 * here moves the whole product at once — every button, table, chip and line — because each design
 * token is a name for a step of the scale the knob selects. It is kept twice, like the skin: in
 * this browser so the page paints as it was left, and in the person's settings so it follows them.
 *
 * A preset is all six at once, named for what it does (`lib/lookValues.ts`); choosing one leaves
 * every knob its own afterwards. The chart palette does not move: a chart's colours are data.
 *
 * Drawn as one card (Settings ▸ Appearance, redone to `aughor-v2/CLARITY.md`): a row per knob, the way back to the
 * default at the label's right end, and the one line that says where the choice is kept.
 */
import { SegmentedControl } from "@radix-ui/themes";
import type { ReactNode } from "react";

import { Card } from "@/components/clarity/kit";
import { Button } from "@/components/ui/button";
import { Tooltip } from "@/components/ui/tooltip";
import { putMyPreference } from "@/lib/api";
import {
  ACCENTS, DEFAULT_LOOK, EDGES, GREYS, LOOK_KEYS, PRESET_NAMES, PRESETS, RADII, SCALINGS, TYPEFACES,
  setLook, useLook, type Edges, type Look, type Preset, type Radius, type Typeface,
} from "@/lib/look";

const RADIUS_WORD: Record<Radius, string> = { none: "Square", small: "Small", medium: "Medium", large: "Large", full: "Round" };
const EDGES_WORD: Record<Edges, string> = { off: "Off", on: "On" };
const TYPEFACE_WORD: Record<Typeface, string> = { inter: "Inter", "source-sans": "Source Sans" };
const PRESET_WORD: Record<Preset, string> = { aughor: "Aughor", workbench: "Workbench" };
/** What a preset sets, said once on hover — the knobs below show it anyway. */
const PRESET_SAID: Record<Preset, string> = {
  aughor: "Indigo · gray · large corners · 100% · no edges · Inter — the default",
  workbench: "Blue · slate · small corners · 95% · boxed cards · Source Sans — a denser, cooler look",
};
const title = (word: string) => word.charAt(0).toUpperCase() + word.slice(1);

/** The preset the look is, if it is one exactly. */
function presetOf(look: Look): Preset | null {
  return PRESET_NAMES.find(name => LOOK_KEYS.every(key => look[key] === PRESETS[name][key])) ?? null;
}

/** Change the look here and in the person's settings. The page has already followed by the
 *  time the store answers; a store that cannot be reached leaves this browser's copy standing. */
export function chooseLook(change: Partial<Look>): void {
  setLook(change);
  for (const key of LOOK_KEYS) {
    const value = change[key];
    if (value !== undefined) putMyPreference(key, value).catch(() => {});
  }
}

function Swatches<T extends string>({ label, values, chosen, onChoose, neutral }: {
  label: string; values: readonly T[]; chosen: T; onChoose: (value: T) => void;
  /** The plain grey is drawn without the tint the current grey would lend it. */
  neutral?: T;
}) {
  return (
    <div role="radiogroup" aria-label={label} style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
      {values.map(value => (
        <Tooltip key={value} content={title(value)}>
          <Button variant="ghost" size="icon" role="radio" aria-checked={chosen === value} aria-label={title(value)}
            onClick={() => onChoose(value)}
            style={{ width: 28, height: 28, borderRadius: "var(--r-pill)", padding: 0,
              boxShadow: chosen === value ? "0 0 0 2px var(--bg-0), 0 0 0 4px var(--t1)" : undefined }}>
            <span aria-hidden style={{ width: 20, height: 20, borderRadius: "var(--r-pill)", display: "block",
              background: `var(--${value}-9)`, filter: value === neutral ? "saturate(0)" : undefined }} />
          </Button>
        </Tooltip>
      ))}
    </div>
  );
}

/** One knob: its name in the left column, its control beside it. */
function Knob({ name, children }: { name: string; children: ReactNode }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "72px minmax(0, 1fr)", gap: 12, alignItems: "center" }}>
      <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>{name}</span>
      <div style={{ minWidth: 0 }}>{children}</div>
    </div>
  );
}

export function LookPanel() {
  const look = useLook();
  const isDefault = LOOK_KEYS.every(key => look[key] === DEFAULT_LOOK[key]);
  const preset = presetOf(look);
  return (
    <Card label="Look" testId="look-panel"
      right={!isDefault && <Button variant="outline" size="xs" onClick={() => chooseLook(DEFAULT_LOOK)}>Back to the default</Button>}>
      <div style={{ display: "grid", gap: 14 }}>
        <Knob name="Preset">
          <div role="radiogroup" aria-label="Preset" style={{ display: "flex", gap: 6 }}>
            {PRESET_NAMES.map(name => (
              <Tooltip key={name} content={PRESET_SAID[name]}>
                <Button variant={preset === name ? "secondary" : "outline"} size="xs" role="radio"
                  aria-checked={preset === name} onClick={() => chooseLook(PRESETS[name])}>
                  {PRESET_WORD[name]}
                </Button>
              </Tooltip>
            ))}
          </div>
        </Knob>
        <Knob name="Accent">
          <Swatches label="Accent" values={ACCENTS} chosen={look.accent} onChoose={accent => chooseLook({ accent })} />
        </Knob>
        <Knob name="Grey">
          <Swatches label="Grey" values={GREYS} chosen={look.grey} onChoose={grey => chooseLook({ grey })} neutral="gray" />
        </Knob>
        <Knob name="Corners">
          <SegmentedControl.Root size="1" value={look.radius} aria-label="Corners"
            onValueChange={value => chooseLook({ radius: value as Radius })}>
            {RADII.map(value => <SegmentedControl.Item key={value} value={value}>{RADIUS_WORD[value]}</SegmentedControl.Item>)}
          </SegmentedControl.Root>
        </Knob>
        <Knob name="Scaling">
          <SegmentedControl.Root size="1" value={look.scaling} aria-label="Scaling"
            onValueChange={value => chooseLook({ scaling: value as Look["scaling"] })}>
            {SCALINGS.map(value => <SegmentedControl.Item key={value} value={value}>{value}</SegmentedControl.Item>)}
          </SegmentedControl.Root>
        </Knob>
        <Knob name="Edges">
          <SegmentedControl.Root size="1" value={look.edges} aria-label="Edges"
            onValueChange={value => chooseLook({ edges: value as Edges })}>
            {EDGES.map(value => <SegmentedControl.Item key={value} value={value}>{EDGES_WORD[value]}</SegmentedControl.Item>)}
          </SegmentedControl.Root>
        </Knob>
        <Knob name="Typeface">
          <SegmentedControl.Root size="1" value={look.typeface} aria-label="Typeface"
            onValueChange={value => chooseLook({ typeface: value as Typeface })}>
            {TYPEFACES.map(value => <SegmentedControl.Item key={value} value={value}>{TYPEFACE_WORD[value]}</SegmentedControl.Item>)}
          </SegmentedControl.Root>
        </Knob>
      </div>
      <div className="aug-fs-xs" style={{ color: "var(--t3)", marginTop: 12 }}>
        Kept for you, in this browser and wherever you sign in. Charts keep their own colours.
      </div>
    </Card>
  );
}
