import * as React from "react"
import { Input as InputPrimitive } from "@base-ui/react/input"

import { cn } from "@/lib/utils"

/** A field: height 28, radius 4, --bg-3 fill, --b2 border that steps to --b3 on hover.
 *  Focus is the global 2px ring; an error is a --red2 border (aria-invalid). */
function Input({ className, type, ...props }: React.ComponentProps<"input">) {
  return (
    <InputPrimitive
      type={type}
      data-slot="input"
      className={cn(
        "h-7 w-full min-w-0 rounded-[var(--r2)] border border-[var(--b2)] bg-[var(--bg-3)] px-[9px] text-sm text-[var(--t1)] transition-colors duration-[var(--dur-1)] file:inline-flex file:h-5 file:border-0 file:bg-transparent file:text-sm file:font-medium file:text-[var(--t1)] placeholder:text-[var(--t3)] hover:border-[var(--b3)] disabled:pointer-events-none disabled:cursor-not-allowed disabled:border-[var(--b1)] disabled:bg-[var(--bg-1)] disabled:text-[var(--t3)] disabled:opacity-60 aria-invalid:border-[var(--red2)]",
        className
      )}
      {...props}
    />
  )
}

export { Input }
