"use client"

import type * as React from "react"
import { Checkbox as ThemesCheckbox, Radio as ThemesRadio } from "@radix-ui/themes"

/**
 * A checkbox and a radio, on Radix Themes, written the way the native ones are written —
 * `checked`, `onChange(e)` reading `e.target.checked` — so a call site moves by changing the
 * tag. The label around them stays the caller's.
 */
function Checkbox({ checked, defaultChecked, onChange, disabled, id, name, value, className, style, "aria-label": ariaLabel, title }: {
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
  const fire = (next: boolean | "indeterminate") => {
    const target = { checked: next === true, name, value } as unknown as HTMLInputElement
    onChange?.({ target, currentTarget: target } as React.ChangeEvent<HTMLInputElement>)
  }
  return (
    <ThemesCheckbox data-slot="checkbox" size="1" checked={checked} defaultChecked={defaultChecked} onCheckedChange={fire}
      disabled={disabled} id={id} name={name} value={value} className={className} style={style} aria-label={ariaLabel} title={title} />
  )
}

/** Themes' radio IS a native radio input, drawn its way: `name`, `checked` and `onChange` as before. */
function Radio(props: Omit<React.ComponentProps<typeof ThemesRadio>, "size" | "value"> & { value?: string }) {
  const { value, ...rest } = props
  return <ThemesRadio data-slot="radio" size="1" value={value ?? "on"} {...rest} />
}

export { Checkbox, Radio }
