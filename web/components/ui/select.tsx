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
  // `data-value` says which option this is, as a native <option value> would: Radix keeps the
  // value in script only, and a test (or a hand on the DOM) has nothing else to find it by.
  return <ThemesSelect.Item data-slot="select-item" data-value={value} value={value === "" ? NONE : value} {...props} />
}

/**
 * A select written the way the native one is written — `value`, `onChange(e)` reading
 * `e.target.value`, `<option>` and `<optgroup>` children — drawn as Themes' select. The 120
 * native selects in the product moved onto it by changing the tag alone (2026-10-06).
 *
 * What differs from a native select, and is meant to: the first option is chosen when
 * nothing is (as the native one shows it), an option whose value is "" is legal (see above),
 * and `multiple` and `size` are not here — a list box is a different thing.
 */
interface Opt { value: string; label: React.ReactNode; disabled?: boolean }
interface Group { label: string; options: Opt[] }

function optionsOf(children: React.ReactNode): (Opt | Group)[] {
  const out: (Opt | Group)[] = []
  React.Children.forEach(children, child => {
    if (!React.isValidElement(child)) return
    const props = child.props as Record<string, unknown>
    if (child.type === "option") {
      out.push({ value: String(props.value ?? textOf(props.children as React.ReactNode)), label: props.children as React.ReactNode, disabled: !!props.disabled })
    } else if (child.type === "optgroup") {
      out.push({ label: String(props.label ?? ""), options: optionsOf(props.children as React.ReactNode).filter((o): o is Opt => "value" in o) })
    } else if (child.type === React.Fragment) {
      out.push(...optionsOf(props.children as React.ReactNode))
    }
  })
  return out
}
const textOf = (node: React.ReactNode): string => (typeof node === "string" || typeof node === "number" ? String(node) : "")
const flat = (opts: (Opt | Group)[]): Opt[] => opts.flatMap(o => ("options" in o ? o.options : [o]))

function SelectField({
  value,
  defaultValue,
  onChange,
  children,
  disabled,
  className,
  style,
  title,
  id,
  name,
  "aria-label": ariaLabel,
  "aria-labelledby": ariaLabelledBy,
  "data-testid": testId,
  ...rest
}: {
  value?: string | number
  defaultValue?: string | number
  onChange?: (e: React.ChangeEvent<HTMLSelectElement>) => void
  children?: React.ReactNode
  disabled?: boolean
  className?: string
  style?: React.CSSProperties
  title?: string
  id?: string
  name?: string
  "aria-label"?: string
  "aria-labelledby"?: string
  "data-testid"?: string
  /** The trigger's own events and focus, for a caller that keeps a key or a click from a row. */
  onKeyDown?: React.KeyboardEventHandler<HTMLButtonElement>
  onClick?: React.MouseEventHandler<HTMLButtonElement>
  onFocus?: React.FocusEventHandler<HTMLButtonElement>
  onBlur?: React.FocusEventHandler<HTMLButtonElement>
  autoFocus?: boolean
}) {
  const opts = optionsOf(children)
  const all = flat(opts)
  const items = Object.fromEntries(all.map(o => [o.value, o.label]))
  // The native select shows its first option when none is chosen; so does this.
  const first = all[0]?.value
  const controlled = value !== undefined
  const shown = controlled ? String(value) : undefined
  const fire = (next: string) => {
    const target = { value: next, name } as unknown as HTMLSelectElement
    onChange?.({ target, currentTarget: target } as React.ChangeEvent<HTMLSelectElement>)
  }
  const item = (o: Opt) => <SelectItem key={o.value} value={o.value} disabled={o.disabled}>{o.label}</SelectItem>
  return (
    <Select value={shown} defaultValue={controlled ? undefined : String(defaultValue ?? first ?? "")} onValueChange={fire}
      items={items} disabled={disabled} name={name}>
      {/* `data-value` on the trigger is the native select's `.value`, for whatever reads it. */}
      <SelectTrigger id={id} className={className} style={style} title={title} aria-label={ariaLabel}
        aria-labelledby={ariaLabelledBy} data-testid={testId} data-value={shown ?? String(defaultValue ?? first ?? "")} {...rest} />
      <SelectContent>
        {opts.map((o, i) => ("options" in o
          ? <ThemesSelect.Group key={`g${i}`}><ThemesSelect.Label>{o.label}</ThemesSelect.Label>{o.options.map(item)}</ThemesSelect.Group>
          : item(o)))}
      </SelectContent>
    </Select>
  )
}

export { Select, SelectContent, SelectField, SelectItem, SelectTrigger, SelectValue }
