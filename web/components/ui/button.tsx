import type * as React from "react"
import { Button as ThemesButton, IconButton as ThemesIconButton } from "@radix-ui/themes"

import { IconsBeside } from "@/components/ui/icon"
import { cn } from "@/lib/utils"

/**
 * The one button system, on Radix Themes (ROADMAP §6 item 44).
 *
 * The call sites keep the names they have always used; each maps to a Themes variant and colour,
 * so the Theme's accent, grey, radius and scaling move every button at once.
 *
 *   default      solid, accent        the one Primary per view
 *   secondary    surface, grey        a filled secondary
 *   outline      outline, grey        (and `minimal`, the older name for the same look)
 *   ghost        ghost, grey          no chrome until hover: toolbar and row actions
 *   destructive  outline, red
 *   link         ghost, accent        the "show source" affordance
 *
 * Themes has three heights (24, 32, 40). Ours were 26 and 22; both become 24 — its size 1
 * (the user chose Radix's own density, 2026-10-06).
 *
 * One thing is ours still: the one Primary per view scales to 0.96 while pressed (.aug-press;
 * decided 2026-09-14 — a single main action is worth feeling). `static` opts a Primary out.
 */
type Variant = "default" | "secondary" | "outline" | "minimal" | "ghost" | "destructive" | "link"
type Size = "default" | "lg" | "sm" | "xs" | "icon" | "icon-lg" | "icon-sm" | "icon-xs"

const LOOK: Record<Variant, { variant: "solid" | "surface" | "outline" | "ghost"; color?: "gray" | "red"; highContrast?: boolean }> = {
  default: { variant: "solid" },
  secondary: { variant: "surface", color: "gray", highContrast: true },
  outline: { variant: "outline", color: "gray" },
  minimal: { variant: "outline", color: "gray" },
  ghost: { variant: "ghost", color: "gray" },
  destructive: { variant: "outline", color: "red" },
  link: { variant: "ghost" },
}

function Button({
  variant = "default",
  size = "default",
  static: isStatic = false,
  color: _color,
  className,
  children,
  ...props
}: Omit<React.ComponentProps<"button">, "color"> & {
  variant?: Variant | null
  size?: Size | null
  /** A Primary that should not scale on press. */
  static?: boolean
  color?: string
}) {
  const look = LOOK[variant ?? "default"]
  const cls = cn((variant ?? "default") === "default" && !isStatic && "aug-press", className)
  if (String(size).startsWith("icon")) {
    return <ThemesIconButton data-slot="button" size="1" {...look} className={cls} {...props}>{children}</ThemesIconButton>
  }
  return (
    <ThemesButton data-slot="button" size="1" {...look} className={cls} {...props}>
      <IconsBeside weight="semibold">{children}</IconsBeside>
    </ThemesButton>
  )
}

export { Button }
