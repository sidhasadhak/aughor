import type * as React from "react"
import { TextField } from "@radix-ui/themes"

import { fieldClass, fieldStyle } from "@/components/ui/field"

/** A field, on Radix Themes: its size-2 text field — 32px, 14px text, the size of every form
 *  field (`ui/field.ts`). `className` and `style` land on the field's box and may place it, not
 *  size or paint it; `bespoke` is a field that draws itself (24px, everything as given). */
function Input({ className, style, size: _size, color: _color, bespoke, defaultValue, value, ...props }:
  Omit<React.ComponentProps<"input">, "size" | "color"> & { size?: number; color?: string; bespoke?: boolean }) {
  return (
    <TextField.Root data-slot="input" data-field={bespoke ? undefined : "form"} size={bespoke ? "1" : "2"}
      className={bespoke ? className : fieldClass(className)} style={bespoke ? style : fieldStyle(style)}
      {...(value !== undefined ? { value: value as string | number } : {})}
      {...(defaultValue !== undefined ? { defaultValue: defaultValue as string | number } : {})}
      {...(props as Record<string, unknown>)} />
  )
}

export { Input }
