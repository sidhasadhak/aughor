import type * as React from "react"
import { TextArea } from "@radix-ui/themes"

/** A multi-line field, on Radix Themes: its size-2 text area — 14px, the reading size — which
 *  the reader may pull taller. `className` and `style` go to the box; the rest to the textarea. */
function Textarea(props: Omit<React.ComponentProps<typeof TextArea>, "size">) {
  return <TextArea data-slot="textarea" size="2" resize="vertical" {...props} />
}

export { Textarea }
