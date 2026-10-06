/**
 * The look: the four knobs of Radix Themes' panel — accent, grey, radius, scaling — as one
 * person keeps them (ROADMAP §6 item 44).
 *
 * The skin (dark or light) is not here: it has been `<html data-theme>` since before this and
 * stays where it is (`lib/themeSwitch.ts`). These four are the Theme's own props; the root
 * (`app/theme-root.tsx`) reads them from this store and hands them to `<Theme>`, and every
 * token in `aughor-v2/theme/tokens-v2.css` follows because each is a name for a Radix step.
 *
 * Two homes, like the skin: this browser first (so the page paints as it was left), the
 * person's own settings second (so the look follows them to another browser). The shell
 * (`app/page.tsx`) does the second; this module only knows the first.
 */
import { useSyncExternalStore } from "react";

export const ACCENTS = [
  "gray", "gold", "bronze", "brown", "yellow", "amber", "orange", "tomato", "red", "ruby", "crimson",
  "pink", "plum", "purple", "violet", "iris", "indigo", "blue", "cyan", "teal", "jade", "green",
  "grass", "lime", "mint", "sky",
] as const;
export const GREYS = ["gray", "mauve", "slate", "sage", "olive", "sand"] as const;
export const RADII = ["none", "small", "medium", "large", "full"] as const;
export const SCALINGS = ["90%", "95%", "100%", "105%", "110%"] as const;

export type Accent = (typeof ACCENTS)[number];
export type Grey = (typeof GREYS)[number];
export type Radius = (typeof RADII)[number];
export type Scaling = (typeof SCALINGS)[number];
export interface Look { accent: Accent; grey: Grey; radius: Radius; scaling: Scaling }

/** What the user chose for everyone who has not chosen for themselves (2026-10-06). */
export const DEFAULT_LOOK: Look = { accent: "indigo", grey: "gray", radius: "large", scaling: "100%" };

/** The values each knob admits — the same lists the person's settings store validates against
 *  (`aughor/db/user_prefs.py`). */
export const LOOK_VALUES: { [K in keyof Look]: readonly Look[K][] } = {
  accent: ACCENTS, grey: GREYS, radius: RADII, scaling: SCALINGS,
};
export const LOOK_KEYS = Object.keys(LOOK_VALUES) as (keyof Look)[];

const STORAGE_KEY = "aughor_look";

/** Whatever was handed in, with every knob that is not one of its own values put back to the
 *  default: a stored look written by an older build, or by hand, never reaches the Theme raw. */
export function cleanLook(raw: unknown, base: Look = DEFAULT_LOOK): Look {
  const from = (raw && typeof raw === "object" ? raw : {}) as Record<string, unknown>;
  const out = { ...base };
  for (const key of LOOK_KEYS) {
    const value = from[key];
    if ((LOOK_VALUES[key] as readonly unknown[]).includes(value)) (out as Record<string, unknown>)[key] = value;
  }
  return out;
}

function sameLook(a: Look, b: Look): boolean {
  return LOOK_KEYS.every(key => a[key] === b[key]);
}

function readStored(): Look {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    return raw ? cleanLook(JSON.parse(raw)) : DEFAULT_LOOK;
  } catch {
    return DEFAULT_LOOK;   // storage refused, or what is in it is not JSON
  }
}

let current: Look | null = null;
const listeners = new Set<() => void>();

export function getLook(): Look {
  if (typeof window === "undefined") return DEFAULT_LOOK;
  if (current === null) current = readStored();
  return current;
}

/** Change one or more knobs. The page follows at once; the browser remembers. */
export function setLook(change: Partial<Look>): Look {
  const next = cleanLook({ ...getLook(), ...change }, getLook());
  if (sameLook(next, getLook())) return next;
  current = next;
  try { window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next)); } catch { /* the page still follows */ }
  for (const listener of listeners) listener();
  return next;
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

/** The look, live. The server and the first client render both see the default, so hydration
 *  agrees; a person's own look arrives with the first effect. */
export function useLook(): Look {
  return useSyncExternalStore(subscribe, getLook, () => DEFAULT_LOOK);
}

/** For tests: forget what this module has read. */
export function forgetLook(): void {
  current = null;
}
