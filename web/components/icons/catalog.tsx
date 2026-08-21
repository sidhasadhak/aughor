/**
 * The catalog icon set — catalog, schema, table, chevron.
 *
 * Lifted verbatim out of `CatalogScreen`, where they were file-local, because two
 * other surfaces were drawing the same three concepts with different glyphs and
 * different colours: the Catalog screen's layered-square schema icon versus
 * QueryBuilder's stacked-planes one, its banded-rows table versus a grid rectangle.
 * A schema should not change shape depending on which tab you are looking at.
 *
 * These four were hand-drawn on a 16px grid with per-path opacity, from a time when
 * the app had no icon set. It has one now (`components/ui/icon.tsx`, Tabler), so the
 * drawings are gone and these are thin adapters over it — the three call sites keep
 * their existing props and the glyphs finally match the rest of the interface.
 *
 * Colour is still a prop rather than baked in, and every caller passes a TOKEN
 * (`var(--blue3)` for a schema, `var(--t2)` for a catalog) — so these follow the
 * theme like everything else, and light/dark needs no second definition.
 */

import { Icon } from "@/components/ui/icon";

export const IcoCatalog = ({ color = "currentColor", size = 16 }: { color?: string; size?: number }) => (
  <span style={{ color, display: "inline-flex", flexShrink: 0 }}><Icon name="db" size={size} /></span>
);

export const IcoSchema = ({ color = "currentColor", size = 14 }: { color?: string; size?: number }) => (
  <span style={{ color, display: "inline-flex", flexShrink: 0 }}><Icon name="schema" size={size} /></span>
);

export const IcoTable = ({ active = false, size = 14 }: { active?: boolean; size?: number }) => (
  <span style={{ color: active ? "var(--blue4)" : "var(--t4)", display: "inline-flex", flexShrink: 0 }}>
    <Icon name="table" size={size} />
  </span>
);

export const Chevron = ({ open }: { open: boolean }) => (
  <span style={{
    display: "inline-flex", flexShrink: 0, color: "var(--t4)",
    transition: "transform .15s", transform: open ? "rotate(90deg)" : "rotate(0deg)",
  }}>
    <Icon name="chevr" size={12} />
  </span>
);
