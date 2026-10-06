"use client"

import { Tabs } from "@radix-ui/themes"

import { Badge } from "@/components/ui/badge"

/**
 * A row of tabs that opens PANELS the page draws itself, on Radix Themes: its tab list — an
 * underline in the accent under the open one. The page keeps the panels (a workspace keeps its
 * layers mounted; this is only the strip), so there is no `Tabs.Content` here.
 *
 *   <TabStrip label="Record" value={layer} onChange={setLayer}
 *     tabs={[{ id: "claims", label: "Claims" }, { id: "decisions", label: "Decisions", badge: 2 }]} />
 */
export interface TabStripTab<T extends string> {
  id: T
  label: React.ReactNode
  /** A hover's sentence for the tab. */
  title?: string
  /** A count of what waits in the tab, drawn beside its name. */
  badge?: number
}

export function TabStrip<T extends string>({
  value,
  onChange,
  tabs,
  label,
  size = "2",
  trailing,
  className,
  style,
}: {
  value: T
  onChange: (id: T) => void
  tabs: readonly TabStripTab<T>[]
  /** What the tabs are, for a reader who cannot see them. */
  label: string
  size?: "1" | "2"
  /** Drawn at the strip's right end: the one control that belongs to the row. */
  trailing?: React.ReactNode
  className?: string
  style?: React.CSSProperties
}) {
  return (
    <Tabs.Root data-slot="tab-strip" value={value} onValueChange={id => onChange(id as T)} className={className} style={style}>
      <Tabs.List size={size} aria-label={label} style={trailing ? { alignItems: "center" } : undefined}>
        {tabs.map(t => (
          <Tabs.Trigger key={t.id} value={t.id} title={t.title}>
            {t.label}
            {(t.badge ?? 0) > 0 && (
              // Amber: something in this tab is waiting on a human.
              <Badge variant="amber" style={{ marginLeft: 6 }}>{t.badge}</Badge>
            )}
          </Tabs.Trigger>
        ))}
        {trailing && <span style={{ marginLeft: "auto", display: "inline-flex", alignItems: "center" }}>{trailing}</span>}
      </Tabs.List>
    </Tabs.Root>
  )
}
