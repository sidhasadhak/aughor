"use client"

import { SegmentedControl } from "@radix-ui/themes"

/**
 * A choice between a few VALUES, on Radix Themes: its segmented control. The chosen one is
 * filled; the rest are one tap away. (A choice between PANELS is `tab-strip.tsx`.)
 *
 *   <Segmented label="Range" value={range} onChange={setRange}
 *     options={[{ value: "1h", label: "1h" }, { value: "24h", label: "24h", title: "The last day" }]} />
 */
export interface SegmentedOption<T extends string> {
  value: T
  label: React.ReactNode
  /** A hover's word for the choice. */
  title?: string
}

export function Segmented<T extends string>({
  value,
  onChange,
  options,
  label,
  disabled,
  size = "1",
  className,
  style,
}: {
  /** "" when none of them is chosen — a brushed window, say, that is no named range. */
  value: T | ""
  onChange: (value: T) => void
  options: readonly SegmentedOption<T>[]
  /** What the choice is, for a reader who cannot see it. */
  label: string
  /** The whole choice held (Themes' control cannot hold one option: offer only what can be chosen). */
  disabled?: boolean
  size?: "1" | "2" | "3"
  className?: string
  style?: React.CSSProperties
}) {
  return (
    <SegmentedControl.Root data-slot="segmented" size={size} value={value} aria-label={label}
      // Radix hands back "" when the chosen item is pressed again; a choice stays chosen.
      onValueChange={next => { if (next) onChange(next as T) }}
      disabled={disabled} className={className} style={style}>
      {options.map(o => (
        <SegmentedControl.Item key={o.value} value={o.value} title={o.title}>
          {/* An icon in a label sits beside its word, not above it. */}
          <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>{o.label}</span>
        </SegmentedControl.Item>
      ))}
    </SegmentedControl.Root>
  )
}
