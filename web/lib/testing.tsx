/**
 * Testing Library, with the one thing every Radix Themes component needs around it: a Theme.
 *
 * A Themes select, dialog or tooltip draws its pop-up inside a `<Theme>` of its own and reads
 * the one above it to do so; with none above, it throws. The app has one at the root
 * (`app/theme-root.tsx`). A component test that renders such a component imports `render`
 * from here instead of from `@testing-library/react` — everything else is re-exported as is.
 */
import { render as plainRender, type RenderOptions } from "@testing-library/react";
import { Theme } from "@radix-ui/themes";
import type { ReactElement } from "react";

export * from "@testing-library/react";

export function render(ui: ReactElement, options?: Omit<RenderOptions, "wrapper">) {
  return plainRender(ui, { wrapper: Theme, ...options });
}
