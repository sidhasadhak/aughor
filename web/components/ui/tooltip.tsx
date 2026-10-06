import type * as React from "react"
import { Tooltip as ThemesTooltip } from "@radix-ui/themes"

/**
 * A tooltip, on Radix Themes: what it says is `content`, and its one child is what it names.
 *
 *   <Tooltip content="Copy the link"><Button …/></Tooltip>
 *
 * `disabled` draws the child alone — a labelled row needs no tooltip until its label is hidden.
 * The Theme's root waits 200ms before the first tooltip and opens a neighbour at once; a caller
 * a cursor merely crosses (the rail) asks for longer with `delayDuration`.
 */
function Tooltip({
  disabled,
  children,
  ...props
}: React.ComponentProps<typeof ThemesTooltip> & { disabled?: boolean }) {
  if (disabled || !props.content) return <>{children}</>
  return <ThemesTooltip {...props}>{children}</ThemesTooltip>
}

export { Tooltip }
