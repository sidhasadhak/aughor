import { Button as ButtonPrimitive } from "@base-ui/react/button"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"
import { IconsBeside } from "@/components/ui/icon"

/**
 * The one button system — the Instrument component sheet (web/aughor-v2/INSTRUMENT.md §4).
 *
 * Radius 3, label 12/600, two heights: 26 and a small 22. A press steps the background and
 * nothing moves — a label that moves under a cursor reads as a misclick in a dense row — except
 * on the one Primary per view, which also scales to 0.96 (.aug-press, 150ms ease-out; decided
 * 2026-09-14): a single main action is worth feeling. `static` opts a Primary out. Focus is the
 * global 2px --bfocus ring (app/globals.css), never a border change.
 *
 * Variant → the sheet's name:
 *   default      Primary    --blue-solid fill, white label. One per view.
 *   secondary    Secondary  --bg-3 fill, --b2 border, --t1 label.
 *   outline      Ghost      transparent, --b2 border, --t2 label.
 *   minimal      Ghost      the older name for the same look, kept for its call sites.
 *   link         Minimal    --blue3 label, no border — the "show source" affordance.
 *   ghost        Quiet      no chrome until hover: the toolbar / menu-row idiom. Not on the
 *                           sheet, but it carries 500+ icon and row actions a border would box in.
 *   destructive             transparent, --red2 border, --red4 label.
 */
const buttonVariants = cva(
  "group/button inline-flex shrink-0 items-center justify-center gap-1.5 rounded-[var(--r1)] border border-transparent bg-clip-padding text-sm font-medium leading-none whitespace-nowrap select-none transition-[background-color,border-color,color] duration-[var(--dur-1)] ease-[var(--ease-out)] disabled:pointer-events-none disabled:cursor-not-allowed aria-invalid:border-[var(--red2)] [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-3.5",
  {
    variants: {
      variant: {
        default:
          "border-[var(--primary)] bg-[var(--primary)] font-semibold text-white hover:border-[var(--primary-hover)] hover:bg-[var(--primary-hover)] active:brightness-90 disabled:border-[var(--b2)] disabled:bg-[var(--bg-4)] disabled:text-[var(--t3)] disabled:opacity-55",
        secondary:
          "border-[var(--b2)] bg-[var(--bg-3)] font-semibold text-[var(--t1)] hover:border-[var(--b3)] hover:bg-[var(--bg-4)] active:bg-[var(--bg-4)] aria-expanded:bg-[var(--bg-4)] disabled:border-[var(--b1)] disabled:bg-[var(--bg-1)] disabled:text-[var(--t3)] disabled:opacity-60",
        outline:
          "border-[var(--b2)] bg-transparent font-semibold text-[var(--t2)] hover:border-[var(--b3)] hover:bg-[var(--bg-3)] hover:text-[var(--t1)] active:bg-[var(--bg-4)] aria-expanded:bg-[var(--bg-3)] aria-expanded:text-[var(--t1)] disabled:border-[var(--b1)] disabled:text-[var(--t3)] disabled:opacity-60",
        minimal:
          "border-[var(--b2)] bg-transparent font-semibold text-[var(--t2)] hover:border-[var(--b3)] hover:bg-[var(--bg-3)] hover:text-[var(--t1)] active:bg-[var(--bg-4)] aria-expanded:bg-[var(--bg-3)] aria-expanded:text-[var(--t1)] disabled:border-[var(--b1)] disabled:text-[var(--t3)] disabled:opacity-60",
        ghost:
          "bg-transparent hover:bg-[var(--bg-hover)] hover:text-[var(--t1)] active:bg-[var(--bg-4)] aria-expanded:bg-[var(--bg-hover)] aria-expanded:text-[var(--t1)] disabled:opacity-60",
        destructive:
          "border-[var(--red2)] bg-transparent font-semibold text-[var(--red4)] hover:bg-[var(--red1)] active:bg-[var(--red1)] disabled:opacity-60",
        link:
          "bg-transparent font-semibold text-[var(--blue3)] hover:text-[var(--blue4)] active:bg-[var(--bg-3)] disabled:text-[var(--t3)] disabled:opacity-60",
      },
      size: {
        default: "h-[26px] px-[11px]",
        lg: "h-[26px] px-[11px]",
        sm: "h-[26px] px-[11px]",
        xs: "h-[22px] gap-1 px-2 text-xs [&_svg:not([class*='size-'])]:size-3",
        icon: "size-[26px]",
        "icon-lg": "size-[26px]",
        "icon-sm": "size-[22px]",
        "icon-xs": "size-[22px] [&_svg:not([class*='size-'])]:size-3",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

function Button({
  className,
  variant = "default",
  size = "default",
  static: isStatic = false,
  children,
  ...props
}: ButtonPrimitive.Props & VariantProps<typeof buttonVariants> & {
  /** Keep a Primary still on press, where the scale would distract. */
  static?: boolean
}) {
  // A labelled button's icons sit beside a 500–600 label, so they take the semibold stroke; an
  // icon-only size has no label to match and keeps the regular one.
  const labelled = !String(size).startsWith("icon")
  // The Primary — one per view — is the only press that scales.
  const press = variant === "default" && !isStatic
  return (
    <ButtonPrimitive
      data-slot="button"
      className={cn(buttonVariants({ variant, size, className }), press && "aug-press")}
      {...props}
    >
      {labelled ? <IconsBeside weight="semibold">{children}</IconsBeside> : children}
    </ButtonPrimitive>
  )
}

export { Button, buttonVariants }
