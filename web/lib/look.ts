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
 * (`app/page.tsx`) does the second; this module only knows the first. What the knobs admit,
 * the default and the browser key live in `lib/lookValues.ts` (no React there: the root
 * layout hands them to the boot script that paints the look before React does).
 */
import { useSyncExternalStore } from "react";

import { cleanLook, DEFAULT_LOOK, LOOK_KEY, LOOK_KEYS, type Look } from "@/lib/lookValues";

export {
  ACCENTS, GREYS, RADII, SCALINGS, DEFAULT_LOOK, LOOK_VALUES, LOOK_KEYS, LOOK_KEY, cleanLook,
  type Accent, type Grey, type Radius, type Scaling, type Look,
} from "@/lib/lookValues";

function sameLook(a: Look, b: Look): boolean {
  return LOOK_KEYS.every(key => a[key] === b[key]);
}

function readStored(): Look {
  try {
    const raw = window.localStorage.getItem(LOOK_KEY);
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
  try { window.localStorage.setItem(LOOK_KEY, JSON.stringify(next)); } catch { /* the page still follows */ }
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
