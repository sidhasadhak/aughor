import type * as React from "react"
import { Card as ThemesCard } from "@radix-ui/themes"

import { cn } from "@/lib/utils"

/**
 * A card, on Radix Themes: its surface card — the Theme's panel colour, a hairline, the
 * Theme's radius — padded by the card itself, so the parts below carry no padding of their own.
 * `size="sm"` is its tighter padding.
 */
function Card({
  className,
  size = "default",
  ...props
}: Omit<React.ComponentProps<typeof ThemesCard>, "size"> & { size?: "default" | "sm" }) {
  return (
    <ThemesCard data-slot="card" size={size === "sm" ? "1" : "2"} variant="surface"
      className={cn("flex flex-col gap-3 text-sm", className)} {...props} />
  )
}

function CardHeader({ className, ...props }: React.ComponentProps<"div">) {
  return <div data-slot="card-header" className={cn("grid auto-rows-min items-start gap-1", className)} {...props} />
}

function CardTitle({ className, ...props }: React.ComponentProps<"div">) {
  return <div data-slot="card-title" className={cn("text-base leading-snug font-semibold", className)} {...props} />
}

function CardDescription({ className, ...props }: React.ComponentProps<"div">) {
  return <div data-slot="card-description" className={cn("text-sm text-[var(--t2)]", className)} {...props} />
}

function CardContent({ className, ...props }: React.ComponentProps<"div">) {
  return <div data-slot="card-content" className={className} {...props} />
}

export { Card, CardHeader, CardTitle, CardDescription, CardContent }
