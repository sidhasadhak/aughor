"use client"

import * as React from "react"
import { Select as ThemesSelect } from "@radix-ui/themes"

/**
 * A select, on Radix Themes: its size-1 trigger (24px) and its own menu.
 *
 *   <Select value={v} onValueChange={setV} items={{ a: "Alpha", b: "Beta" }}>
 *     <SelectTrigger aria-label="Letter"><SelectValue placeholder="Pick one" /></SelectTrigger>
 *     <SelectContent><SelectItem value="a">Alpha</SelectItem>…</SelectContent>
 *   </Select>
 *
 * `items` (value → label) is what `<SelectValue>` prints when the trigger holds more than the
 * value — an icon beside it, say. A trigger with no children prints the chosen item by itself.
 *
 * An option whose value is the empty string ("none") is legal here and not in Radix, which
 * keeps "" for "nothing chosen"; it travels as a stand-in and comes back as "".
 */
const NONE = "__none__"
const outward = (v: string) => (v === NONE ? "" : v)

const Chosen = React.createContext<{ value: string; items?: Record<string, React.ReactNode> }>({ value: "" })

function Select({
  value,
  defaultValue,
  onValueChange,
  items,
  ...props
}: Omit<React.ComponentProps<typeof ThemesSelect.Root>, "size" | "onValueChange"> & {
  onValueChange?: (value: string) => void
  items?: Record<string, React.ReactNode>
}) {
  // "" names an option only when one of the items is "": otherwise it means nothing is chosen.
  const inward = (v: string | undefined) => (v === "" && items && "" in items ? NONE : v)
  return (
    <Chosen.Provider value={{ value: value ?? "", items }}>
      <ThemesSelect.Root data-slot="select" size="1" value={inward(value)} defaultValue={inward(defaultValue)}
        onValueChange={v => onValueChange?.(outward(v))} {...props} />
    </Chosen.Provider>
  )
}

function SelectTrigger({
  size: _size,
  ...props
}: React.ComponentProps<typeof ThemesSelect.Trigger> & { size?: "sm" | "default" }) {
  return <ThemesSelect.Trigger data-slot="select-trigger" {...props} />
}

/** The chosen item's label, for a trigger that draws something beside it. */
function SelectValue({ placeholder }: { placeholder?: React.ReactNode }) {
  const { value, items } = React.useContext(Chosen)
  const label = items && value in items ? items[value] : undefined
  return <span data-slot="select-value" data-placeholder={label === undefined || undefined}>{label ?? placeholder}</span>
}

function SelectContent(props: React.ComponentProps<typeof ThemesSelect.Content>) {
  return <ThemesSelect.Content data-slot="select-content" {...props} />
}

function SelectItem({ value, ...props }: React.ComponentProps<typeof ThemesSelect.Item>) {
  return <ThemesSelect.Item data-slot="select-item" value={value === "" ? NONE : value} {...props} />
}

export { Select, SelectContent, SelectItem, SelectTrigger, SelectValue }
