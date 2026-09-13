import * as React from "react"

import { cn } from "@/lib/utils"

/** The field spec at multi-line height: at least three rows, radius 4, --bg-3, --b2. */
function Textarea({ className, ...props }: React.ComponentProps<"textarea">) {
  return (
    <textarea
      data-slot="textarea"
      className={cn(
        "flex field-sizing-content min-h-14 w-full rounded-[var(--r2)] border border-[var(--b2)] bg-[var(--bg-3)] px-[9px] py-[7px] text-sm leading-[1.55] text-[var(--t1)] transition-colors duration-[var(--dur-1)] placeholder:text-[var(--t3)] hover:border-[var(--b3)] disabled:cursor-not-allowed disabled:border-[var(--b1)] disabled:bg-[var(--bg-1)] disabled:text-[var(--t3)] disabled:opacity-60 aria-invalid:border-[var(--red2)]",
        className
      )}
      {...props}
    />
  )
}

export { Textarea }
