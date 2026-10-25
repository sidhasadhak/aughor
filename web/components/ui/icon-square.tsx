/**
 * A small square with one glyph in it — the mark beside a name that says what KIND of thing the name is: an
 * entity type, a column, a property (the look study of 2026-10-25, §10: "icons well placed & clear").
 *
 * Monochrome on purpose — `components/icons/columnType.tsx` says why a glyph and not a colour: the glyph carries
 * the distinction, and a hue here would be decoration (INSTRUMENT §2: a hue appears only when a reader can name
 * the state it means). The square is a control's fill with a hairline, so the mark reads as a thing set on the
 * row rather than ink floating beside the text, and every row's name starts at the same x.
 */
import { Icon, type IconName } from "@/components/ui/icon";

export function IconSquare({ name, title, size = 16, testId }: {
  name: IconName;
  /** What the mark means, on hover; a square with no title is decoration to a screen reader and is hidden from it. */
  title?: string;
  size?: number;
  testId?: string;
}) {
  return (
    <span title={title} data-testid={testId} aria-hidden={title ? undefined : true} role={title ? "img" : undefined}
      aria-label={title}
      style={{ width: size, height: size, flexShrink: 0, display: "inline-flex", alignItems: "center", justifyContent: "center",
               borderRadius: "var(--r1)", background: "var(--bg-3)", boxShadow: "inset 0 0 0 1px var(--b1)",
               color: "var(--t2)", lineHeight: 0 }}>
      <Icon name={name} size={Math.round(size * 0.68)} />
    </span>
  );
}
