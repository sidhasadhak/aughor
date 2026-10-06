/**
 * Testing Library, with the one thing every Radix Themes component needs around it: a Theme.
 *
 * A Themes select, dialog or tooltip draws its pop-up inside a `<Theme>` of its own and reads
 * the one above it to do so; with none above, it throws. The app has one at the root
 * (`app/theme-root.tsx`). A component test that renders such a component imports `render`
 * from here instead of from `@testing-library/react` — everything else is re-exported as is.
 */
import { fireEvent, render as plainRender, type RenderOptions } from "@testing-library/react";
import { Theme } from "@radix-ui/themes";
import type { ReactElement } from "react";

export * from "@testing-library/react";

export function render(ui: ReactElement, options?: Omit<RenderOptions, "wrapper">) {
  return plainRender(ui, { wrapper: Theme, ...options });
}

/**
 * Change a control's value the way a test of the native one did — `change(el, { target: { value } })`.
 *
 * On an input or a text area this is `fireEvent.change`. On a select — a Themes select is a
 * button (`role="combobox"`) with its options in a menu — it opens the menu from the keyboard,
 * finds the option by the value it carries, and chooses it with Enter, which is what a person
 * at the keyboard does. The select's `onChange` then fires as the native one's did.
 */
export function change(el: Element, init: { target: { value: string | number } }) {
  const trigger = el as HTMLElement;
  if (trigger.tagName !== "BUTTON" || trigger.getAttribute("role") !== "combobox") {
    return fireEvent.change(el, init);
  }
  const want = String(init.target.value);
  fireEvent.keyDown(trigger, { key: "ArrowDown" });
  const option = [...document.querySelectorAll('[role="option"]')].find(o => o.getAttribute("data-value") === want);
  if (!option) {
    fireEvent.keyDown(trigger, { key: "Escape" });
    throw new Error(`change(): the select has no option whose value is ${JSON.stringify(want)}`);
  }
  fireEvent.keyDown(option, { key: "Enter" });
  return true;
}

/** Choose a select's option by its value, as `userEvent.selectOptions(el, value)` chose a native
 *  one's: a Themes select from the keyboard (see `change`), a native select by its own event. */
export async function choose(el: Element, value: string) {
  const trigger = el as HTMLElement;
  if (trigger.tagName === "SELECT") return fireEvent.change(el, { target: { value } });
  return change(el, { target: { value } });
}

/** A select's options — value and text — as a test read a native select's `<option>`s. A Themes
 *  select draws them only while open, so this opens it from the keyboard, reads, and closes. */
export function optionsOf(el: Element): { value: string; text: string }[] {
  if (el.tagName === "SELECT") {
    return [...el.querySelectorAll("option")].map(o => ({ value: o.value, text: o.textContent ?? "" }));
  }
  fireEvent.keyDown(el, { key: "ArrowDown" });
  const found = [...document.querySelectorAll('[role="option"]')]
    .map(o => ({ value: o.getAttribute("data-value") ?? "", text: (o.textContent ?? "").trim() }));
  fireEvent.keyDown(el, { key: "Escape" });
  return found;
}

/** A control's value: a native field's own, a Themes select's from its trigger. */
export function valueOf(el: Element): string {
  if ("value" in el && typeof (el as HTMLInputElement).value === "string" && el.tagName !== "BUTTON") return (el as HTMLInputElement).value;
  return el.getAttribute("data-value") ?? "";
}
