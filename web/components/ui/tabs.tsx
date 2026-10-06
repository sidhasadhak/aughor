import type * as React from "react"
import { Tabs as ThemesTabs } from "@radix-ui/themes"

/**
 * Tabs, on Radix Themes: an underline in the accent under the open tab. One look — a choice
 * between VALUES (not panels) is a segmented control, which is Themes' own `SegmentedControl`.
 */
function Tabs(props: React.ComponentProps<typeof ThemesTabs.Root>) {
  return <ThemesTabs.Root data-slot="tabs" {...props} />
}

function TabsList(props: Omit<React.ComponentProps<typeof ThemesTabs.List>, "size">) {
  return <ThemesTabs.List data-slot="tabs-list" size="1" {...props} />
}

function TabsTrigger(props: React.ComponentProps<typeof ThemesTabs.Trigger>) {
  return <ThemesTabs.Trigger data-slot="tabs-trigger" {...props} />
}

function TabsContent(props: React.ComponentProps<typeof ThemesTabs.Content>) {
  return <ThemesTabs.Content data-slot="tabs-content" {...props} />
}

export { Tabs, TabsList, TabsTrigger, TabsContent }
