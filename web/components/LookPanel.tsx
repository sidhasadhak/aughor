"use client";

/**
 * The look, chosen by one person: accent, grey, corners and scaling (ROADMAP §6 item 44).
 *
 * These are the four knobs of Radix Themes' own panel. A choice here moves the whole product
 * at once — every button, table, chip and line — because each design token is a name for a
 * step of the scale the knob selects. It is kept twice, like the skin: in this browser so the
 * page paints as it was left, and in the person's settings so it follows them.
 *
 * The chart palette does not move: a chart's colours are data.
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
  ACCENTS, DEFAULT_LOOK, GREYS, LOOK_KEYS, RADII, SCALINGS, setLook, useLook,
  type Look, type Radius,
} from "@/lib/look";

const RADIUS_WORD: Record<Radius, string> = { none: "Square", small: "Small", medium: "Medium", large: "Large", full: "Round" };
const title = (word: string) => word.charAt(0).toUpperCase() + word.slice(1);

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
  return (
    <Card label="Look" testId="look-panel"
      right={!isDefault && <Button variant="outline" size="xs" onClick={() => chooseLook(DEFAULT_LOOK)}>Back to the default</Button>}>
      <div style={{ display: "grid", gap: 14 }}>
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
      </div>
      <div className="aug-fs-xs" style={{ color: "var(--t3)", marginTop: 12 }}>
        Kept for you, in this browser and wherever you sign in. Charts keep their own colours.
      </div>
    </Card>
  );
}
