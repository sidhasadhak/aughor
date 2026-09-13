"use client"

import { Tabs as TabsPrimitive } from "@base-ui/react/tabs"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

/**
 * Selection, as the component sheet draws it — and never both kinds in one header:
 *   variant="default"  segmented — fills: --bg-4 selected, --b2 dividers, radius 4
 *   variant="line"     tabs — an underline: 2px --blue3 under the active tab, weight 600
 */
function Tabs({
  className,
  orientation = "horizontal",
  ...props
}: TabsPrimitive.Root.Props) {
  return (
    <TabsPrimitive.Root
      data-slot="tabs"
      data-orientation={orientation}
      className={cn(
        "group/tabs flex gap-2 data-horizontal:flex-col",
        className
      )}
      {...props}
    />
  )
}

const tabsListVariants = cva(
  "group/tabs-list inline-flex w-fit items-stretch text-[var(--t2)] group-data-vertical/tabs:flex-col",
  {
    variants: {
      variant: {
        default: "overflow-hidden rounded-[var(--r2)] border border-[var(--b2)]",
        line: "gap-[18px] border-b border-[var(--b1)]",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

function TabsList({
  className,
  variant = "default",
  ...props
}: TabsPrimitive.List.Props & VariantProps<typeof tabsListVariants>) {
  return (
    <TabsPrimitive.List
      data-slot="tabs-list"
      data-variant={variant}
      className={cn(tabsListVariants({ variant }), className)}
      {...props}
    />
  )
}

function TabsTrigger({ className, ...props }: TabsPrimitive.Tab.Props) {
  return (
    <TabsPrimitive.Tab
      data-slot="tabs-trigger"
      className={cn(
        "relative inline-flex items-center justify-center gap-1.5 text-sm whitespace-nowrap text-[var(--t2)] transition-colors duration-[var(--dur-1)] hover:text-[var(--t1)] disabled:pointer-events-none disabled:opacity-50 aria-disabled:pointer-events-none aria-disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0",
        "group-data-[variant=default]/tabs-list:border-l group-data-[variant=default]/tabs-list:border-[var(--b2)] group-data-[variant=default]/tabs-list:px-2.5 group-data-[variant=default]/tabs-list:py-[3px] group-data-[variant=default]/tabs-list:first:border-l-0 group-data-[variant=default]/tabs-list:hover:bg-[var(--bg-3)] group-data-[variant=default]/tabs-list:data-active:bg-[var(--bg-4)] group-data-[variant=default]/tabs-list:data-active:font-semibold group-data-[variant=default]/tabs-list:data-active:text-[var(--t1)]",
        "group-data-[variant=line]/tabs-list:-mb-px group-data-[variant=line]/tabs-list:border-b-2 group-data-[variant=line]/tabs-list:border-transparent group-data-[variant=line]/tabs-list:pb-[7px] group-data-[variant=line]/tabs-list:data-active:border-[var(--blue3)] group-data-[variant=line]/tabs-list:data-active:font-semibold group-data-[variant=line]/tabs-list:data-active:text-[var(--t1)]",
        className
      )}
      {...props}
    />
  )
}

function TabsContent({ className, ...props }: TabsPrimitive.Panel.Props) {
  return (
    <TabsPrimitive.Panel
      data-slot="tabs-content"
      className={cn("flex-1 text-sm", className)}
      {...props}
    />
  )
}

export { Tabs, TabsList, TabsTrigger, TabsContent, tabsListVariants }
