/**
 * The look's VALUES: what each of the four knobs admits, the default, and the key it is kept
 * under in this browser — with no React in them, so the root layout (a server component) can
 * hand them to the boot script (`lib/themeBoot.ts`). The store and the hook are `lib/look.ts`.
 */
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

/** The look's home in this browser; the boot script reads the same key. */
export const LOOK_KEY = "aughor_look";

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
