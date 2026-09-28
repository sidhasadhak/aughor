/**
 * The cockpit's catalog — the ONE home of what a composed cockpit may contain (Arc CT, CT-2;
 * ROADMAP §3.50, docs/COCKPIT_JSON_RENDER_STUDY_2026-09-28.md).
 *
 * Five components, no actions. The law of the arc is in the last of them: a `Card` element
 * holds a card's id and nothing about what that card measures. Its SQL, its limits, its
 * history and its provenance stay in the card store, and it is drawn by `PinnedCardBody`.
 *
 * What the library's own `catalog.validate` checks, measured in CT-1: component NAMES and the
 * shape of an element. It does not check a prop against its schema — a tone outside the list,
 * a number where a card id belongs and a prop nobody declared all pass. `rules.ts` checks
 * those; this file only declares them.
 *
 * The server reads this vocabulary through the validator bundle (`aughor/cockpit/validate.py`)
 * rather than holding a second copy.
 */
import { defineCatalog } from "@json-render/core";
import { schema } from "@json-render/react/schema";
import { z } from "zod";

/** Raised when a component or a prop is added, renamed or removed. */
export const COCKPIT_VOCABULARY_VERSION = 1;

/** The five tones an answer part may carry (`aughor/agent/present_tool.py`); parity is tested. */
export const TONES = ["good", "warn", "bad", "info", "neutral"] as const;
export type Tone = (typeof TONES)[number];

export const MAX_TITLE = 120;
export const MAX_LABEL = 40;
export const MAX_COLUMNS = 4;

/** A card id as the card store writes it: eight hex characters, or an id its caller chose. */
const CARD_ID = /^[A-Za-z0-9_-]{1,64}$/;
/** A tab's name is an identifier the state holds, never text a reader sees. */
const TAB_NAME = /^[a-z][a-z0-9_-]{0,31}$/;

export const cockpitCatalog = defineCatalog(schema, {
  components: {
    Cockpit: {
      props: z.object({ title: z.string().min(1).max(MAX_TITLE) }),
      slots: ["default"],
      description: "The root. Holds one Tabs, or one or more Section. Its title names the cockpit; it is not drawn as a header.",
    },
    Tabs: {
      props: z.object({ value: z.string() }),
      slots: ["default"],
      description: "Holds Tab elements. Its value is always { \"$bindState\": \"/tab\" }.",
    },
    Tab: {
      props: z.object({
        name: z.string().regex(TAB_NAME),
        label: z.string().min(1).max(MAX_LABEL),
      }),
      slots: ["default"],
      description: "One tab. Holds Section elements. `name` is its identifier; `label` is what a reader sees.",
    },
    Section: {
      props: z.object({
        title: z.string().min(1).max(MAX_TITLE),
        columns: z.number().int().min(1).max(MAX_COLUMNS).nullable().optional(),
      }),
      slots: ["default"],
      description: "A titled group of cards. Holds Card elements. May be shown by a condition.",
    },
    Card: {
      props: z.object({
        card: z.string().regex(CARD_ID),
        tone: z.enum(TONES).nullable().optional(),
      }),
      description: "One card from the card store, by its id. Never a figure, never SQL. May be shown by a condition.",
    },
  },
  actions: {},
});

export type ComponentName = "Cockpit" | "Tabs" | "Tab" | "Section" | "Card";
export const COMPONENT_NAMES: readonly ComponentName[] = ["Cockpit", "Tabs", "Tab", "Section", "Card"];

/** What each component may hold. A cockpit's shape is fixed so that a reader can predict it. */
export const MAY_HOLD: Record<ComponentName, readonly ComponentName[]> = {
  Cockpit: ["Tabs", "Section"],
  Tabs: ["Tab"],
  Tab: ["Section"],
  Section: ["Card"],
  Card: [],
};

/** The components a condition may show or hide. A tab is never conditional. */
export const MAY_BE_CONDITIONAL: readonly ComponentName[] = ["Section", "Card"];

/** The props a reader sees as text. The server holds these to the numerals law. */
export const READER_TEXT: Partial<Record<ComponentName, readonly string[]>> = {
  Cockpit: ["title"],
  Tab: ["label"],
  Section: ["title"],
};
