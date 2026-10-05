import type * as React from "react"
import { Badge as ThemesBadge } from "@radix-ui/themes"

/** A badge, on Radix Themes: its `surface` look — tint, border and text of
 *  one hue — is the look ours always had. A hue appears only when a reader can name the state
 *  it means (INSTRUMENT.md §2). */
type Variant = "default" | "secondary" | "destructive" | "green" | "amber" | "violet" | "cyan" | "outline" | "ghost" | "link"

const LOOK: Record<Variant, { variant: "surface" | "outline" | "soft"; color?: "gray" | "red" | "green" | "amber" | "violet" | "cyan" }> = {
  default: { variant: "surface" },
  secondary: { variant: "surface", color: "gray" },
  destructive: { variant: "surface", color: "red" },
  green: { variant: "surface", color: "green" },
  amber: { variant: "surface", color: "amber" },
  violet: { variant: "surface", color: "violet" },
  cyan: { variant: "surface", color: "cyan" },
  outline: { variant: "outline", color: "gray" },
  ghost: { variant: "soft", color: "gray" },
  link: { variant: "soft" },
}

function Badge({ variant = "default", color: _color, ...props }: Omit<React.ComponentProps<"span">, "color"> & {
  variant?: Variant | null
  color?: string
}) {
  return <ThemesBadge data-slot="badge" size="1" {...LOOK[variant ?? "default"]} {...props} />
}

export { Badge }
