/**
 * What a cockpit's elements are called where a person reads them as lines — the builder's layout (Arc AP-1), Arrange,
 * the strip that says which pieces a release touched. ONE home for it: before it, Arrange named every element by its
 * `card` prop, so the ontology's pieces drew as blank lines, and the strip named three of them by their element keys
 * (the study's defects 1 and 5, docs/COCKPIT_APP_BUILDER_STUDY_2026-10-10.md §1.6).
 *
 * The words are the server's own (`_WORDS` and `title_of` in `aughor/cockpit/pieces.py`): a piece is named by what it
 * names — "Objects table · Order, overdue dispatch" — never by a key a person did not choose.
 */
import type { ComponentName } from "@/lib/cockpit/catalog";

/** Each component's word, as a reader says it. */
export const KIND_WORDS: Record<ComponentName, string> = {
  Cockpit: "dashboard",
  Tabs: "tabs",
  Tab: "tab",
  Section: "section",
  Card: "card",
  Note: "note",
  Image: "image",
  ProcessBoard: "process board",
  ObjectTable: "objects table",
  ObjectDetail: "object detail",
  ActionButton: "action button",
  ObjectFilters: "filter column",
  ObjectFigure: "figure",
  ObjectChart: "chart",
  ActionButtons: "action buttons",
  ObjectList: "object list",
  ObjectMap: "map",
  ObjectTimeline: "timeline",
  ChooseOne: "choose one",
  ObjectSearch: "search",
  Drawer: "drawer",
};

/** A component's word, or the type itself when it is none of the catalog's. */
export function kindWord(type: string | undefined): string {
  return KIND_WORDS[type as ComponentName] ?? String(type ?? "");
}

const words = (id: unknown): string => String(id ?? "").replace(/[_-]+/g, " ").trim();
/** A set's, a value's or a choice's name in words: `chosen-order` → "chosen order". */
export const wireWords = (name: string): string => words(name);
/** What each set of a spec is called — for `nameOf`'s `setTitle`. */
export function setTitles(spec: unknown): (name: string) => string | undefined {
  const sets = (spec as { sets?: Record<string, { label?: string }> } | null)?.sets ?? {};
  return name => sets[name]?.label;
}
const cut = (s: string, n: number): string => (s.length > n ? `${s.slice(0, n)}…` : s);

type El = { type?: string; props?: Record<string, unknown>; children?: string[] };

/** What one element is called: its kind and the words that name it. A card by its title, from `cardTitle`; a note by
 *  its first words; an image by its caption; a piece by what it reads — its entity by the name the ontology gives it,
 *  from `entityTitle`, else by its id in words; a section or a tab by its own title. */
export function nameOf(elements: Record<string, El | undefined>, key: string,
  cardTitle: (id: string) => string | undefined = () => undefined,
  entityTitle: (id: string) => string | undefined = () => undefined,
  setTitle: (name: string) => string | undefined = () => undefined): { kind: string; title: string } {
  const el = elements[key];
  const type = el?.type ?? "";
  const p = el?.props ?? {};
  const kind = kindWord(type);
  const entity = (id: unknown): string => entityTitle(String(id ?? "")) || words(id);
  const title = ((): string => {
    switch (type) {
      case "Cockpit": return String(p.title ?? "");
      // Arc AP-4 — an untitled section laid out in sections is called by its layout: "In columns", "In rows", "As tabs"
      case "Section": return String(p.title ?? (p.layout === "columns" ? "In columns" : p.layout === "rows" ? "In rows" : p.layout === "tabs" ? "As tabs" : ""));
      case "Tab": return String(p.label ?? "");
      case "Card": return cardTitle(String(p.card ?? "")) || String(p.card ?? "");
      case "Note": return cut(String(p.text ?? "").replace(/\s+/g, " ").trim(), 60);
      case "Image": return String(p.caption ?? "");
      case "ProcessBoard": return words(p.process);
      case "ActionButton": return words(p.action);
      case "ObjectTable":
        // a table reading a set is called by the set (Arc AP-2)
        if (p.set) return setTitle(String(p.set)) ?? words(p.set);
        return [entity(p.entity), p.segment ? words(p.segment) : ""].filter(Boolean).join(", ");
      case "ObjectDetail": {
        const table = elements[String(p.follows ?? "")];
        // a title that stands on its own line, in the layout as in a refusal: "Chosen in Waiting"
        if (table?.type === "ObjectTable") return `Chosen in ${nameOf(elements, String(p.follows), cardTitle, entityTitle, setTitle).title}`;
        // a detail following an object a click chooses is called by it: "The chosen order"
        return p.follows ? `The ${words(p.follows)}` : "";
      }
      // a filter column counting within a set says so: "Customer Order · within Waiting"
      case "ObjectFilters": return p.set ? `${entity(p.entity)} · within ${setTitle(String(p.set)) ?? words(p.set)}` : entity(p.entity);
      case "ObjectFigure": case "ObjectChart": return String(p.label ?? "");
      // Arc AP-4 — the pieces the picker adds, by what they read; a search by what it is called
      case "ObjectList": case "ObjectMap": case "ObjectTimeline": case "ChooseOne":
        if (p.set) return setTitle(String(p.set)) ?? words(p.set);
        return entity(p.entity);
      case "ObjectSearch": return String(p.label ?? "");
      case "Drawer": return String(p.title ?? "");
      case "ActionButtons": return (Array.isArray(p.buttons) ? p.buttons as { action?: unknown; label?: unknown }[] : [])
        .map(b => String(b.label ?? "") || words(b.action)).filter(Boolean).join(" · ");
      default: return "";
    }
  })();
  return { kind, title };
}

/** One line: "Objects table · Order, overdue dispatch", or the kind alone when nothing names it. */
export function lineOf(elements: Record<string, El | undefined>, key: string,
  cardTitle?: (id: string) => string | undefined, entityTitle?: (id: string) => string | undefined,
  setTitle?: (name: string) => string | undefined): string {
  const { kind, title } = nameOf(elements, key, cardTitle, entityTitle, setTitle);
  const Kind = kind.charAt(0).toUpperCase() + kind.slice(1);
  return title ? `${Kind} · ${title}` : Kind;
}
