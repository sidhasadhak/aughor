"use client"

import type * as React from "react"
import { Dialog as ThemesDialog } from "@radix-ui/themes"

import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Icon } from "@/components/ui/icon"

/** A dialog, on Radix Themes: its panel, its scrim, its focus trap. One of the three things
 *  allowed to float. */
function Dialog(props: React.ComponentProps<typeof ThemesDialog.Root>) {
  return <ThemesDialog.Root data-slot="dialog" {...props} />
}

function DialogContent({
  className,
  children,
  showCloseButton = true,
  maxWidth = "384px",
  ...props
}: Omit<React.ComponentProps<typeof ThemesDialog.Content>, "size"> & {
  showCloseButton?: boolean
}) {
  return (
    <ThemesDialog.Content data-slot="dialog-content" size="2" maxWidth={maxWidth}
      className={cn("grid gap-3 text-sm", className)} {...props}>
      {children}
      {showCloseButton && (
        <ThemesDialog.Close>
          <Button variant="ghost" size="icon-sm" aria-label="Close" className="absolute top-2 right-2">
            <Icon name="close" size={14} />
          </Button>
        </ThemesDialog.Close>
      )}
    </ThemesDialog.Content>
  )
}

function DialogHeader({ className, ...props }: React.ComponentProps<"div">) {
  return <div data-slot="dialog-header" className={cn("flex flex-col gap-1.5", className)} {...props} />
}

/** The dialog's name. Themes spaces a title from what follows; here the content's own gap does. */
function DialogTitle(props: React.ComponentProps<typeof ThemesDialog.Title>) {
  return <ThemesDialog.Title data-slot="dialog-title" size="3" mb="0" {...props} />
}

function DialogDescription(props: React.ComponentProps<typeof ThemesDialog.Description>) {
  return <ThemesDialog.Description data-slot="dialog-description" size="2" color="gray" {...props} />
}

export { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle }
