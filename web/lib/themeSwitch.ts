/**
 * Flip `<html data-theme>` without animating it.
 *
 * A theme flip changes colour, background, border and shadow on nearly every element at once, and
 * every control that transitions those properties (Button, .aug-pressable, .aug-nav-item …) would
 * fire together: the switch smears for a beat instead of snapping. So transitions are off for the
 * flip — a style that zeroes them goes in, the attribute changes, a forced reflow commits the new
 * colours while that style still applies, and the style comes out two frames later, once the new
 * theme has painted.
 *
 * The skin's home in this browser. The boot script (`lib/themeBoot.ts`) reads the same key before
 * the first paint; the shell (`app/page.tsx`) writes it and mirrors it to the person's settings.
 */
export const THEME_KEY = "aughor_theme";

export function applyTheme(theme: string, doc: Document = document): void {
  const root = doc.documentElement;
  if (root.getAttribute("data-theme") === theme) return;
  const style = doc.createElement("style");
  style.textContent = "*,*::before,*::after{transition:none!important}";
  doc.head.appendChild(style);
  root.setAttribute("data-theme", theme);
  // Radix keys its colour scales on a class, so the same switch sets it.
  root.classList.toggle("light", theme === "light");
  root.classList.toggle("dark", theme !== "light");
  void doc.body?.offsetHeight;   // read for its side effect: styles flush while transitions are off
  const raf = doc.defaultView?.requestAnimationFrame?.bind(doc.defaultView);
  if (raf) raf(() => raf(() => style.remove()));
  else style.remove();
}
