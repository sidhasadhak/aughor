"use client";

/**
 * Settings ▸ Appearance, redone to `aughor-v2/CLARITY.md`: two related cards on one row — the theme (dark or light)
 * and the look (accent, grey, corners, scaling, `LookPanel`). It used to sit inline in `app/page.tsx` as a pair of
 * hand-styled buttons; the screen still owns the theme, so it hands the chosen one and its setter in, and choosing
 * calls that setter exactly as before (it writes the stored preference — `lib/themeSwitch.ts`).
 */
import { Card } from "@/components/clarity/kit";
import { LookPanel } from "@/components/LookPanel";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";

import { Pair, Stack } from "./parts";

export type ThemeChoice = "dark" | "light";

const MODES: Array<{ id: ThemeChoice; icon: "moon" | "sun"; label: string; desc: string }> = [
  { id: "dark", icon: "moon", label: "Dark", desc: "Dark backgrounds, light text" },
  { id: "light", icon: "sun", label: "Light", desc: "White backgrounds, dark text" },
];

export function AppearancePanel({ theme, setTheme }: { theme: ThemeChoice; setTheme: (t: ThemeChoice) => void }) {
  return (
    <Stack testId="appearance-panel">
      <Pair>
        <Card label="Theme">
          <div role="radiogroup" aria-label="Theme" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
            {MODES.map(m => {
              const on = theme === m.id;
              return (
                <Button key={m.id} variant="ghost" role="radio" aria-checked={on} onClick={() => setTheme(m.id)}
                  style={{ height: "auto", margin: 0, padding: "10px 12px", justifyContent: "flex-start", gap: 10,
                    textAlign: "left", whiteSpace: "normal", borderRadius: "var(--r3)",
                    background: on ? "var(--bg-sel)" : "var(--bg-3)",
                    boxShadow: on ? "inset 0 0 0 1px var(--blue3)" : "inset 0 0 0 1px var(--b1)" }}>
                  <span aria-hidden style={{ color: on ? "var(--blue4)" : "var(--t2)", display: "inline-flex" }}>
                    <Icon name={m.icon} size={14} />
                  </span>
                  <span style={{ display: "flex", flexDirection: "column", minWidth: 0, flex: 1 }}>
                    <span className="aug-fs-sm" style={{ fontWeight: 600, color: on ? "var(--blue4)" : "var(--t1)" }}>{m.label}</span>
                    <span className="aug-fs-xs" style={{ color: "var(--t3)", fontWeight: 400 }}>{m.desc}</span>
                  </span>
                  {on && <span aria-hidden style={{ color: "var(--blue3)", display: "inline-flex" }}><Icon name="check" size={13} /></span>}
                </Button>
              );
            })}
          </div>
        </Card>
        <LookPanel />
      </Pair>
    </Stack>
  );
}
