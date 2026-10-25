/**
 * The look's VALUES: what each of the six knobs admits, the default, the presets, and the key it is kept
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
/** Whether a card is boxed by a hairline — on is the skin's own grammar since 2026-10-25; off takes it away. */
export const EDGES = ["off", "on"] as const;
/** The face the interface is set in. Figures, ids and code keep their own. */
export const TYPEFACES = ["inter", "source-sans"] as const;

export type Accent = (typeof ACCENTS)[number];
export type Grey = (typeof GREYS)[number];
export type Radius = (typeof RADII)[number];
export type Scaling = (typeof SCALINGS)[number];
export type Edges = (typeof EDGES)[number];
export type Typeface = (typeof TYPEFACES)[number];
export interface Look {
  accent: Accent; grey: Grey; radius: Radius; scaling: Scaling; edges: Edges; typeface: Typeface;
}

/** What the user chose for everyone who has not chosen for themselves (2026-10-06; typeface, added
 *  2026-10-25, defaults to what the page was; edges defaults to the skin's own grammar, on). */
export const DEFAULT_LOOK: Look = {
  accent: "indigo", grey: "gray", radius: "large", scaling: "100%", edges: "on", typeface: "inter",
};

/** A preset is all six knobs at once, named for what it does. `aughor` is the default; `workbench`
 *  is the operations look the user asked for on 2026-10-25 (the design study of that date, in docs/):
 *  a cool grey, one blue, square corners, a step denser, every card boxed, a narrower face. */
export const PRESETS = {
  aughor: DEFAULT_LOOK,
  workbench: { accent: "blue", grey: "slate", radius: "small", scaling: "95%", edges: "on", typeface: "source-sans" },
} as const satisfies Record<string, Look>;
export type Preset = keyof typeof PRESETS;
export const PRESET_NAMES = Object.keys(PRESETS) as Preset[];

/** The values each knob admits — the same lists the person's settings store validates against
 *  (`aughor/db/user_prefs.py`). */
export const LOOK_VALUES: { [K in keyof Look]: readonly Look[K][] } = {
  accent: ACCENTS, grey: GREYS, radius: RADII, scaling: SCALINGS, edges: EDGES, typeface: TYPEFACES,
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
