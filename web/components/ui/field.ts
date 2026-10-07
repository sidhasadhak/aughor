import type * as React from "react"

/**
 * A form field's height, text and paint are the field's own: one size in every form (the user,
 * 2026-10-07 — "the size of input fields and text size inside them … consistent across the
 * platform"). Measured that day: 321 of the 519 fields carried a size, text or paint override
 * kept from the native fields they replaced. The MCP server form padded a 24px box until its
 * text was cut off, and the same field drew at 11, 12, 13 and 14px across the product.
 *
 * What a caller PLACES passes through — width, flex, margins, grid cell, alignment, and how many
 * lines a multi-line field starts at. What it SIZES, SETS IN A TYPE or PAINTS does not: every
 * field's text is the UI face (`globals.css` has always forced it on inputs and textareas, so a
 * `font-mono` here only ever reached a select).
 *
 * A field that draws itself and is not a form field (the canvas's ask box, the ⌘K search, the
 * SQL editor's own controls) says `bespoke` and keeps everything it is given.
 */
const OWNED_STYLE = /^(padding.*|fontSize|fontWeight|fontFamily|font|lineHeight|letterSpacing|border.*|background.*|color|boxShadow|outline.*)$/
const HEIGHT_STYLE = /^(height|minHeight|maxHeight|blockSize|minBlockSize|maxBlockSize)$/

const KEPT_TEXT = /^text-(left|right|center|justify|start|end|ellipsis|clip|wrap|nowrap|balance|pretty)$/
const OWNED_CLASS = [
  /^aug-(input|select|textarea)$/, // the native fields' own look
  /^aug-(fs|text)-/,               // the type scale: a size (and, for aug-text-*, a colour)
  /^text-/,                        // a size or a colour — alignment is KEPT_TEXT
  /^p[xytblrse]?-/,                // padding
  /^leading-/,
  /^font-/,                        // a weight or a face
  /^(border|rounded|bg|outline|ring|shadow|placeholder|caret|transition|duration|ease)(-|$)/,
]
const HEIGHT_CLASS = /^(min-|max-)?h-/

/** The style a caller may set on a field. A multi-line field keeps its heights. */
export function fieldStyle(style: React.CSSProperties | undefined, multiline = false): React.CSSProperties | undefined {
  if (!style) return style
  const kept = Object.fromEntries(Object.entries(style).filter(([key]) =>
    !OWNED_STYLE.test(key) && (multiline || !HEIGHT_STYLE.test(key))))
  return Object.keys(kept).length ? kept : undefined
}

/** The classes a caller may set on a field, read through Tailwind's variants (`focus:`, `dark:`, `!`). */
export function fieldClass(className: string | undefined, multiline = false): string | undefined {
  if (!className) return className
  const kept = className.split(/\s+/).filter(token => {
    const utility = token.replace(/^(?:[\w-]+(?:\[[^\]]*\])?:)*!?/, "").replace(/!$/, "")
    if (!utility) return false
    if (KEPT_TEXT.test(utility)) return true
    if (OWNED_CLASS.some(re => re.test(utility))) return false
    return multiline || !HEIGHT_CLASS.test(utility)
  })
  return kept.join(" ") || undefined
}
