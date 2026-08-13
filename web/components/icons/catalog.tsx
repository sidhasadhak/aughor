/**
 * The catalog icon set — catalog, schema, table, chevron.
 *
 * Lifted verbatim out of `CatalogScreen`, where they were file-local, because two
 * other surfaces were drawing the same three concepts with different glyphs and
 * different colours: the Catalog screen's layered-square schema icon versus
 * QueryBuilder's stacked-planes one, its banded-rows table versus a grid rectangle.
 * A schema should not change shape depending on which tab you are looking at.
 *
 * Colour is a prop rather than baked in, and every caller passes a TOKEN
 * (`var(--blue3)` for a schema, `var(--t2)` for a catalog) — so these follow the
 * theme like everything else, and light/dark needs no second definition.
 */

export const IcoCatalog = ({ color = "currentColor", size = 16 }: { color?: string; size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 16 16" fill="none" style={{ flexShrink: 0 }}>
    <ellipse cx="8" cy="5" rx="6" ry="2.5" stroke={color} strokeWidth="1.2" />
    <path d="M2 5v6c0 1.4 2.7 2.5 6 2.5s6-1.1 6-2.5V5" stroke={color} strokeWidth="1.2" fill="none" />
    <path d="M2 8c0 1.4 2.7 2.5 6 2.5s6-1.1 6-2.5" stroke={color} strokeWidth="1.2" opacity=".5" />
  </svg>
);

export const IcoSchema = ({ color = "currentColor", size = 14 }: { color?: string; size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 16 16" fill="none" style={{ flexShrink: 0 }}>
    <path d="M2 3h5v5H2z" stroke={color} strokeWidth="1.2" fill="none" strokeLinejoin="round" opacity=".6" />
    <path d="M9 3h5v5H9z" stroke={color} strokeWidth="1.2" fill="none" strokeLinejoin="round" opacity=".4" />
    <path d="M5.5 10.5h5v2.5h-5z" stroke={color} strokeWidth="1.2" fill="none" strokeLinejoin="round" opacity=".35" />
  </svg>
);

export const IcoTable = ({ active = false, size = 14 }: { active?: boolean; size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 16 16" fill="none"
    style={{ flexShrink: 0, color: active ? "var(--blue4)" : "var(--t4)" }}>
    <rect x="1" y="2" width="14" height="3" rx="1" fill="currentColor" opacity=".8" />
    <rect x="1" y="6.5" width="14" height="2.5" fill="currentColor" opacity=".5" />
    <rect x="1" y="10.5" width="14" height="3" rx="1" fill="currentColor" opacity=".3" />
  </svg>
);

export const Chevron = ({ open }: { open: boolean }) => (
  <svg width="10" height="10" viewBox="0 0 10 10" fill="none"
    style={{
      flexShrink: 0, transition: "transform .15s",
      transform: open ? "rotate(90deg)" : "rotate(0deg)", color: "var(--t4)",
    }}>
    <path d="M3 2l4 3-4 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);
