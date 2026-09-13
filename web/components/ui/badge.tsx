import { mergeProps } from "@base-ui/react/merge-props"
import { useRender } from "@base-ui/react/use-render"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

/** A badge is an 11px mono rectangle at 3px — tint 1, border 2, text 4 of its hue. Seven
 *  hues: the six intent hues and neutral. A hue appears only when a reader can name the
 *  state it means (INSTRUMENT.md §2). */
const badgeVariants = cva(
  "group/badge inline-flex w-fit shrink-0 items-center justify-center gap-[5px] overflow-hidden rounded-[var(--r1)] border px-[7px] py-[2px] font-mono text-xs font-normal leading-[1.45] whitespace-nowrap [&>svg]:pointer-events-none [&>svg]:size-3!",
  {
    variants: {
      variant: {
        default: "border-[var(--blue2)] bg-[var(--blue1)] text-[var(--blue4)]",
        secondary: "border-[var(--b2)] bg-[var(--bg-3)] text-[var(--t2)]",
        destructive: "border-[var(--red2)] bg-[var(--red1)] text-[var(--red4)]",
        green: "border-[var(--grn2)] bg-[var(--grn1)] text-[var(--grn4)]",
        amber: "border-[var(--amb2)] bg-[var(--amb1)] text-[var(--amb4)]",
        violet: "border-[var(--vio2)] bg-[var(--vio1)] text-[var(--vio4)]",
        cyan: "border-[var(--cyn2)] bg-[var(--cyn1)] text-[var(--cyn4)]",
        outline: "border-[var(--b2)] bg-transparent text-[var(--t2)]",
        ghost: "border-transparent bg-transparent text-[var(--t2)]",
        link: "border-transparent bg-transparent text-[var(--blue3)] hover:text-[var(--blue4)]",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

function Badge({
  className,
  variant = "default",
  render,
  ...props
}: useRender.ComponentProps<"span"> & VariantProps<typeof badgeVariants>) {
  return useRender({
    defaultTagName: "span",
    props: mergeProps<"span">(
      {
        className: cn(badgeVariants({ variant }), className),
      },
      props
    ),
    render,
    state: {
      slot: "badge",
      variant,
    },
  })
}

export { Badge, badgeVariants }
