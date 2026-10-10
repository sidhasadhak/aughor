/**
 * The cockpit's catalog — the ONE home of what a composed cockpit may contain (Arc CT, CT-2;
 * ROADMAP §3.50, docs/COCKPIT_JSON_RENDER_STUDY_2026-09-28.md; the canvas,
 * docs/COCKPIT_CANVAS_2026-10-08.md).
 *
 * Seven components, no actions. The law of the arc is in the `Card`: it holds a card's id and
 * nothing about what that card measures. Its SQL, its limits, its history and its provenance
 * stay in the card store, and it is drawn by `CockpitTile`.
 *
 * Two of the seven are a person's own and measure nothing (the canvas, 2026-10-08). A `Note`
 * is their words, typed by them; an `Image` is a file they uploaded, by its object id. Both say
 * who placed them and when — stamped by the server, never by the browser — and neither is a
 * source: the narrator does not read a note, no claim cites it, a model never writes one. A
 * model may move either or take it off, because that is arrangement.
 *
 * Every element in a section has a `size`, from a closed set (the user, 2026-10-08: "make each
 * component size adjustable… without losing the elegance and robustness"): a column span of 1
 * to 3 and a row span of 1 or 2, six names, never free pixels. Left out, an element is small.
 *
 * A section a person has resized is on the GRID instead (Arc AP, the user 2026-10-10: "they become
 * either too large or small.. The size needs to be adjusted one grade point at a time"): twelve
 * columns and rows of one grade, each element placed by `w` columns and `h` rows, within what its
 * kind may take (`LIMITS`). Still never pixels — the spec says grid units, and the screen draws them.
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

/** Raised when a component or a prop is added, renamed or removed. 2: Note, Image and `size`. 3: the ontology's
 *  pieces — ProcessBoard, ObjectTable, ObjectDetail and ActionButton (Arc OC-4). 4: a cockpit started from an object —
 *  ObjectFilters, ObjectFigure and ObjectChart (2026-10-10). 5: a cockpit built in place (Arc AP-1, 2026-10-10) — sizes
 *  one grade at a time (a section's `grid`, each placed element's `w` and `h`, the filter column's `w`) and a chart's
 *  measure and split (`agg`, `path`, `format`, `split`, `top`). */
export const COCKPIT_VOCABULARY_VERSION = 5;

/** The five tones an answer part may carry (`aughor/agent/present_tool.py`); parity is tested. */
export const TONES = ["good", "warn", "bad", "info", "neutral"] as const;
export type Tone = (typeof TONES)[number];

export const MAX_TITLE = 120;
export const MAX_LABEL = 40;
export const MAX_COLUMNS = 4;
/** A note is a reminder, not a document: a Markdown subset, this long at most. */
export const MAX_NOTE = 2000;
/** An image's caption, which also stands for it when the reader may not see it. */
export const MAX_CAPTION = 120;

/** The sizes an element may take: columns across × rows down. A section never draws more
 *  columns than it has, so a span is cut to the section's columns when it is drawn. */
export const SIZES = ["small", "wide", "tall", "large", "full", "hero"] as const;
export type Size = (typeof SIZES)[number];
export const SPAN: Record<Size, { w: 1 | 2 | 3; h: 1 | 2 }> = {
  small: { w: 1, h: 1 }, wide: { w: 2, h: 1 }, tall: { w: 1, h: 2 },
  large: { w: 2, h: 2 }, full: { w: 3, h: 1 }, hero: { w: 3, h: 2 },
};
/** The size whose span this is, when one has it. */
export function sizeOf(w: number, h: number): Size | null {
  return SIZES.find(s => SPAN[s].w === w && SPAN[s].h === h) ?? null;
}

/** The grid a resized section is laid on (Arc AP-1): twelve columns, and rows whose GRADE — a row and the gap under
 *  it — is 40 px, so one step of height is always 40 px and one step of width one column. */
export const GRID = { columns: 12, row: 28, gap: 12 } as const;
export const GRADE = GRID.row + GRID.gap;
/** How tall `h` rows are drawn: the rows and the gaps between them. */
export const rowsTall = (h: number): number => h * GRID.row + Math.max(0, h - 1) * GRID.gap;
/** The most rows anything may take. */
export const MAX_ROWS = 30;

/** What each kind may take on the grid — columns and rows, least and most — so nothing becomes too small to read or
 *  too large for what it holds (the user, 2026-10-10). A card may be a figure or a chart, so it takes either's room. */
export const LIMITS = {
  Card: { w: [2, 12], h: [2, 16] },
  Note: { w: [2, 12], h: [2, 16] },
  Image: { w: [2, 12], h: [3, 16] },
  ProcessBoard: { w: [3, 12], h: [4, 14] },
  ObjectTable: { w: [4, 12], h: [4, 20] },
  ObjectDetail: { w: [2, 12], h: [3, 16] },
  ObjectFigure: { w: [2, 6], h: [2, 4] },
  ObjectChart: { w: [3, 12], h: [4, 14] },
} as const satisfies Record<string, { w: readonly [number, number]; h: readonly [number, number] }>;
export type GridKind = keyof typeof LIMITS;

/** The filter column's width, in grades of 40 px: 200 to 400 px. Left out, it is 272 px, as it was drawn before. */
export const FILTER_WIDTH = { least: 5, most: 10 } as const;
export const FILTER_DEFAULT_PX = 272;

/** A card id as the card store writes it: eight hex characters, or an id its caller chose. */
const CARD_ID = /^[A-Za-z0-9_-]{1,64}$/;
/** An uploaded object's id, as the volume store writes it. */
const OBJECT_ID = /^[A-Za-z0-9_-]{1,64}$/;
/** A tab's name is an identifier the state holds, never text a reader sees. */
const TAB_NAME = /^[a-z][a-z0-9_-]{0,31}$/;
/** An id the ontology declares — an entity, a segment, a process, an action — by its own spelling. */
const ONTOLOGY_ID = /^[A-Za-z_][A-Za-z0-9_ .-]{0,127}$/;
/** A property path through to-one links (`status`, `user.country`). */
const PROPERTY_PATH = /^[A-Za-z_][A-Za-z0-9_.]{0,127}$/;
/** An element key in the same spec. */
const ELEMENT_KEY = /^[A-Za-z0-9_-]{1,64}$/;
/** The most columns an objects table lists beside each object's key. */
export const MAX_TABLE_COLUMNS = 8;
/** The most properties a filter column offers. */
export const MAX_FILTERS = 6;
/** The aggregates a figure may take — the object door's own (`AggName` in `aughor/semantic/object_query.py`). */
export const FIGURE_AGGS = ["count", "count_distinct", "sum", "avg", "min", "max"] as const;
/** How a figure's value is written. */
export const FIGURE_FORMATS = ["number", "money"] as const;
/** The days a chart of objects per day may span (the `days` prop's literals, below). */
export const CHART_DAYS = [7, 14, 30, 60, 90] as const;
/** How many of a split's values a chart draws, most first; the rest are folded into Other (Arc AP-1). Six at most: a
 *  chart has six series colours, and a seventh value is never a generated hue — it folds into Other. */
export const CHART_TOPS = [3, 4, 5, 6] as const;
/** The measures a chart may split: a split stacks its bars, so what they measure must add up. */
export const SPLIT_AGGS = ["count", "sum"] as const;

const size = z.enum(SIZES).nullable().optional();
/** An element's room on a section's grid: columns across and rows down (Arc AP-1). */
const w = z.number().int().min(1).max(GRID.columns).nullable().optional();
const h = z.number().int().min(1).max(MAX_ROWS).nullable().optional();

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
        /** On the grid: twelve columns and rows of one grade, each element placed by `w` and `h`. */
        grid: z.literal(GRID.columns).nullable().optional(),
      }),
      slots: ["default"],
      description: "A titled group of cards, notes and images. May be shown by a condition. On the grid (grid: 12), each element it holds says its w and h.",
    },
    Card: {
      props: z.object({
        card: z.string().regex(CARD_ID),
        tone: z.enum(TONES).nullable().optional(),
        size, w, h,
      }),
      description: "One card from the card store, by its id. Never a figure, never SQL. May be shown by a condition.",
    },
    Note: {
      props: z.object({
        text: z.string().min(1).max(MAX_NOTE),
        size, w, h,
        // Stamped by the server when the note is kept; whatever a client sends here is replaced.
        author: z.string().max(120).optional(),
        written_at: z.string().max(40).optional(),
      }),
      description: "A person's own words, typed by them. Never written by a model, never measured, cited by nothing.",
    },
    Image: {
      props: z.object({
        object: z.string().regex(OBJECT_ID),
        caption: z.string().min(1).max(MAX_CAPTION),
        size, w, h,
      }),
      description: "An image a person uploaded, by its object id, with a caption. Never chosen by a model, never measured.",
    },
    ProcessBoard: {
      props: z.object({ process: z.string().regex(ONTOLOGY_ID), size, w, h }),
      description: "A declared process, by its id: each stage and how many objects reach it, each promise with how often it is broken and how many objects are open and already past it.",
    },
    ObjectTable: {
      props: z.object({
        entity: z.string().regex(ONTOLOGY_ID),
        segment: z.string().regex(ONTOLOGY_ID).nullable().optional(),
        columns: z.array(z.string().regex(PROPERTY_PATH)).max(MAX_TABLE_COLUMNS).nullable().optional(),
        sort: z.string().regex(PROPERTY_PATH).nullable().optional(),
        descending: z.boolean().nullable().optional(),
        size, w, h,
      }),
      description: "The objects of an entity, or of a segment of it, a page at a time: each object's key and the columns named, read through the object door.",
    },
    ObjectDetail: {
      props: z.object({ follows: z.string().regex(ELEMENT_KEY), size, w, h }),
      description: "The object chosen in the objects table it follows, by that table's element key: its properties, edits marked, and the declared actions it holds.",
    },
    ActionButton: {
      props: z.object({ action: z.string().regex(ONTOLOGY_ID) }),
      description: "A declared action, by its id, run on the object its detail shows — or proposed for approval when running it needs one.",
    },
    ObjectFilters: {
      props: z.object({
        entity: z.string().regex(ONTOLOGY_ID),
        properties: z.array(z.object({
          path: z.string().regex(PROPERTY_PATH),
          label: z.string().min(1).max(MAX_LABEL),
          /** The object a property is read through, when it is not the entity's own ("via Customer"). */
          via: z.string().max(MAX_LABEL).nullable().optional(),
        }).strict()).min(1).max(MAX_FILTERS),
        /** Its width in grades of 40 px (Arc AP-1); left out, 272 px. */
        w: z.number().int().min(FILTER_WIDTH.least).max(FILTER_WIDTH.most).nullable().optional(),
      }),
      description: "The cockpit's filter column: each property's values with how many objects hold each. A reader's click narrows every piece over the same entity, for that reader only. The cockpit's first child, at most one.",
    },
    ObjectFigure: {
      props: z.object({
        entity: z.string().regex(ONTOLOGY_ID),
        label: z.string().min(1).max(MAX_LABEL),
        agg: z.enum(FIGURE_AGGS),
        path: z.string().regex(PROPERTY_PATH).nullable().optional(),
        format: z.enum(FIGURE_FORMATS).nullable().optional(),
        size, w, h,
      }),
      description: "One figure over an entity's objects — a count, or an aggregate of a property — read through the object door, narrowed by the reader's filters and said beside the whole.",
    },
    ObjectChart: {
      props: z.object({
        entity: z.string().regex(ONTOLOGY_ID),
        label: z.string().min(1).max(MAX_LABEL),
        time: z.string().regex(PROPERTY_PATH),
        days: z.union([z.literal(7), z.literal(14), z.literal(30), z.literal(60), z.literal(90)]).nullable().optional(),
        /** What a bar measures (Arc AP-1): left out, how many objects; else an aggregate of a property, as a figure's. */
        agg: z.enum(FIGURE_AGGS).nullable().optional(),
        path: z.string().regex(PROPERTY_PATH).nullable().optional(),
        format: z.enum(FIGURE_FORMATS).nullable().optional(),
        /** A property each bar is split by: its `top` most common values, the rest folded into Other. */
        split: z.string().regex(PROPERTY_PATH).nullable().optional(),
        top: z.union([z.literal(3), z.literal(4), z.literal(5), z.literal(6)]).nullable().optional(),
        size, w, h,
      }),
      description: "An entity's objects per day over its last days — the reader's filtered objects as bars, all of them as a line behind. A bar may measure a property's aggregate, and be split by a property's most common values.",
    },
  },
  actions: {},
});

/** Arc OC-4 — the pieces bound to the ontology. A person places them by hand; a model may arrange one and is never
 *  told how to write one (`grammar.ts` teaches `WRITTEN`). */
export type PieceName = "ProcessBoard" | "ObjectTable" | "ObjectDetail" | "ActionButton" | "ObjectFilters" | "ObjectFigure"
  | "ObjectChart";
export const PIECE_NAMES: readonly PieceName[] = [
  "ProcessBoard", "ObjectTable", "ObjectDetail", "ActionButton", "ObjectFilters", "ObjectFigure", "ObjectChart",
];

export type WrittenName = "Cockpit" | "Tabs" | "Tab" | "Section" | "Card" | "Note" | "Image";
/** The components a writer of a cockpit is told about — every one but the ontology's pieces. */
export const WRITTEN: readonly WrittenName[] = ["Cockpit", "Tabs", "Tab", "Section", "Card", "Note", "Image"];

export type ComponentName = WrittenName | PieceName;
export const COMPONENT_NAMES: readonly ComponentName[] = [...WRITTEN, ...PIECE_NAMES];

/** The components a section holds — each sized, each in its place. */
export const PLACED: readonly ComponentName[] = [
  "Card", "Note", "Image", "ProcessBoard", "ObjectTable", "ObjectDetail", "ObjectFigure", "ObjectChart",
];
/** The two that are a person's own: a model arranges them and never makes one. */
export const STATIC: readonly ComponentName[] = ["Note", "Image"];

/** What each component may hold. A cockpit's shape is fixed so that a reader can predict it. */
export const MAY_HOLD: Record<ComponentName, readonly ComponentName[]> = {
  Cockpit: ["Tabs", "Section", "ObjectFilters"],
  Tabs: ["Tab"],
  Tab: ["Section"],
  Section: PLACED,
  Card: [],
  Note: [],
  Image: [],
  ProcessBoard: [],
  ObjectTable: [],
  ObjectDetail: ["ActionButton"],
  ActionButton: [],
  ObjectFilters: [],
  ObjectFigure: [],
  ObjectChart: [],
};

/** The components a condition may show or hide. A tab is never conditional. */
export const MAY_BE_CONDITIONAL: readonly ComponentName[] = ["Section", "Card", "Note", "Image"];

/** The props a reader sees as text that a MODEL may have written. The server holds these to the
 *  numerals law. A note's text and an image's caption are a person's own words and are not here:
 *  a figure in a note is the person's, and it grounds nothing. */
export const READER_TEXT: Partial<Record<ComponentName, readonly string[]>> = {
  Cockpit: ["title"],
  Tab: ["label"],
  Section: ["title"],
};
