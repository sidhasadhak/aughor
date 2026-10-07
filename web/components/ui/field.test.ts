/**
 * A form field's size, text and paint are its own (2026-10-07). The MCP server form passed
 * `padding: "7px 10px"` and a 14px class to a 24px field and its text was cut off; across the
 * product the same field drew at 11, 12, 13 and 14px. What a caller places passes through.
 */
import { describe, expect, it } from "vitest"

import { fieldClass, fieldStyle } from "@/components/ui/field"

describe("a field keeps what places it and drops what sizes or paints it", () => {
  it("the MCP server form's own style keeps only its width", () => {
    const inputStyle = {
      width: "100%", padding: "7px 10px", borderRadius: "var(--r3)",
      border: "1px solid var(--b1)", background: "var(--bg-1)", color: "var(--t1)",
    }
    expect(fieldStyle(inputStyle)).toEqual({ width: "100%" })
    expect(fieldClass("aug-fs-ui")).toBeUndefined()
  })

  it("reads Tailwind's variants, and keeps alignment and layout — not a face", () => {
    expect(fieldClass(
      "w-full rounded-md border border-zinc-600 bg-zinc-800 px-3 py-1.5 text-sm text-zinc-200 " +
      "placeholder:text-zinc-400 focus:outline-none focus:border-violet-500 transition-colors aug-input h-7 " +
      "font-mono text-right flex-1 min-w-0",
    )).toBe("w-full text-right flex-1 min-w-0")
    expect(fieldStyle({ flex: 1, fontSize: 12, fontFamily: "var(--font-mono)", marginTop: 8, height: 28 }))
      .toEqual({ flex: 1, marginTop: 8 })
  })

  it("a multi-line field keeps how tall it starts", () => {
    expect(fieldStyle({ minHeight: 72, padding: 8, fontSize: 12 }, true)).toEqual({ minHeight: 72 })
    expect(fieldClass("min-h-[56px] aug-fs-xs resize-none", true)).toBe("min-h-[56px] resize-none")
  })
})
