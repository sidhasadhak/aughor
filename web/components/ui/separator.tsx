import type * as React from "react"
import { Separator as ThemesSeparator } from "@radix-ui/themes"

/** A rule between blocks, on Radix Themes: the Theme's own line colour, full length. (A rule
 *  between rows is drawn by the row itself.) */
function Separator({
  orientation = "horizontal",
  ...props
}: Omit<React.ComponentProps<typeof ThemesSeparator>, "size">) {
  return <ThemesSeparator data-slot="separator" size="4" orientation={orientation} {...props} />
}

export { Separator }
