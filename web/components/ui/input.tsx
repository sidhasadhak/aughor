import type * as React from "react"
import { TextField } from "@radix-ui/themes"

/** A field, on Radix Themes (trial, 2026-10-05): its size-1 text field, 24px. `className` and
 *  `style` land on the field's box, as a width always has; everything else is the input's. */
function Input({ className, style, size: _size, color: _color, defaultValue, value, ...props }:
  Omit<React.ComponentProps<"input">, "size" | "color"> & { size?: number; color?: string }) {
  return (
    <TextField.Root data-slot="input" size="1" className={className} style={style}
      {...(value !== undefined ? { value: value as string | number } : {})}
      {...(defaultValue !== undefined ? { defaultValue: defaultValue as string | number } : {})}
      {...(props as Record<string, unknown>)} />
  )
}

export { Input }
