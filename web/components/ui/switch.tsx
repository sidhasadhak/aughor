"use client"

import type * as React from "react"
import { Switch as ThemesSwitch } from "@radix-ui/themes"

/**
 * An on/off switch, on Radix Themes, written the way the checkbox is — `checked`, `onChange(e)`
 * reading `e.target.checked` — so a hand-drawn pill (a coloured track, a white knob moved by
 * `left`) moves by changing the tag. The label beside it stays the caller's.
 */
function Switch({ checked, defaultChecked, onChange, disabled, id, name, value, className, style, "aria-label": ariaLabel, title }: {
  checked?: boolean
  defaultChecked?: boolean
  onChange?: (e: React.ChangeEvent<HTMLInputElement>) => void
  disabled?: boolean
  id?: string
  name?: string
  value?: string
  className?: string
  style?: React.CSSProperties
  "aria-label"?: string
  title?: string
}) {
  const fire = (next: boolean) => {
    const target = { checked: next, name, value } as unknown as HTMLInputElement
    onChange?.({ target, currentTarget: target } as React.ChangeEvent<HTMLInputElement>)
  }
  return (
    <ThemesSwitch data-slot="switch" size="1" checked={checked} defaultChecked={defaultChecked} onCheckedChange={fire}
      disabled={disabled} id={id} name={name} value={value} className={className} style={style} aria-label={ariaLabel} title={title} />
  )
}

export { Switch }
