import type * as React from "react"
import { TextArea } from "@radix-ui/themes"

import { fieldClass, fieldStyle } from "@/components/ui/field"

/** A multi-line field, on Radix Themes: its size-2 text area — 14px, the reading size and every
 *  form field's (`ui/field.ts`) — which the reader may pull taller. `className` and `style` go to
 *  the box and may place it and set its height, not its text or paint; `bespoke` keeps them all. */
function Textarea({ className, style, bespoke, ...props }:
  Omit<React.ComponentProps<typeof TextArea>, "size"> & { bespoke?: boolean }) {
  return <TextArea data-slot="textarea" data-field={bespoke ? undefined : "form"} size="2" resize="vertical" {...props}
    className={bespoke ? className : fieldClass(className, true)} style={bespoke ? style : fieldStyle(style, true)} />
}

export { Textarea }
