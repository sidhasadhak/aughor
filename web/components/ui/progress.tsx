import type * as React from "react"
import { Progress as ThemesProgress } from "@radix-ui/themes"

/** Progress, on Radix Themes: its thinnest bar, in the accent. Never a ring — and the figure is
 *  always printed beside it by the caller, because a bar alone cannot be cited. */
function Progress(props: Omit<React.ComponentProps<typeof ThemesProgress>, "size">) {
  return <ThemesProgress data-slot="progress" size="1" {...props} />
}

export { Progress }
