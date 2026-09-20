/**
 * The column-type mark — ONE glyph per data type, on every surface that lists columns.
 *
 * ── WHY A GLYPH AND NOT A DOT ────────────────────────────────────────────────
 * The catalog rail used to mark a column's type with a coloured dot: emerald for a
 * number, blue for a date, zinc for everything else. A dot carries no meaning of its
 * own, so the rail shipped a legend above the tree teaching the reader what three
 * colours meant — and the legend only ever decoded the three the rail drew. TIMESTAMP
 * and DATE arrived as the same blue, BOOLEAN and VARCHAR as the same zinc, and a reader
 * who had scrolled the legend out of view was back to looking at confetti.
 *
 * A glyph says it without a key: `123` is a number, `ABC` is text, a calendar is a day,
 * a clock is an instant. That is why a warehouse console draws columns this way, and it
 * is also the accessible form — a shape survives colour-blindness, a greyscale
 * screenshot and a dimmed row, none of which a hue does.
 *
 * ── AND NOT COLOUR AT ALL ────────────────────────────────────────────────────
 * The mark is monochrome (`--t3`) on purpose. FOUR palettes for one fact were live at
 * once: the rail's dot (num/date/text), the Catalog screen's square, that screen's
 * *differently* coloured type label (varchar blue, int violet, float green, date
 * amber), and Configure's table (varchar sky, int amber, double violet, date emerald,
 * bool rose). Once the glyph carries the distinction, colour has nothing left to say,
 * so type text renders in ordinary `--t3` beside it.
 *
 * The kinds, and which spellings reach them, are `columnTypeKind` in `lib/format.ts` —
 * one definition, shared with the numeric gate that decides which columns get a
 * distribution.
 */
import { columnTypeKind, COLUMN_KIND_LABEL, type ColumnTypeKind } from "@/lib/format";
import { Icon, type IconName } from "@/components/ui/icon";

/** Kind → the role this product asks the icon set for. WHICH DRAWING answers each role
 *  is chosen in `components/ui/icon.tsx` and nowhere else. `unknown` gets a neutral
 *  point rather than nothing at all: every row keeps a mark, so the names stay in a
 *  straight line and a missing type reads as a gap instead of as a VARCHAR. */
const GLYPH: Record<ColumnTypeKind, IconName> = {
  num: "num", date: "date", time: "time", text: "text", bool: "bool",
  json: "json", geo: "geo", binary: "binary", unknown: "dot",
};

/**
 * The mark itself.
 *
 * `title` defaults to the declared type as the warehouse spells it, falling back to the
 * kind's word — so hovering the `123` beside a truncated column name still answers
 * "BIGINT", which is what a person hovering a type mark is actually asking.
 */
export function ColumnTypeIcon({
  type, size = 14, color = "var(--t3)", title,
}: { type?: string | null; size?: number; color?: string; title?: string }) {
  const kind = columnTypeKind(type);
  return (
    <span
      title={title ?? (type || COLUMN_KIND_LABEL[kind])}
      data-column-type={kind}
      style={{ color, display: "inline-flex", flexShrink: 0, lineHeight: 0 }}
    >
      <Icon name={GLYPH[kind]} size={size} />
    </span>
  );
}
