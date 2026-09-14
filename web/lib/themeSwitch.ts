/**
 * Flip `<html data-theme>` without animating it.
 *
 * A theme flip changes colour, background, border and shadow on nearly every element at once, and
 * every control that transitions those properties (Button, .aug-pressable, .aug-nav-item,
 * .aug-seg-item …) would fire together: the switch smears for a beat instead of snapping. So
 * transitions are off for the flip — a style that zeroes them goes in, the attribute changes, a
 * forced reflow commits the new colours while that style still applies, and the style comes out
 * two frames later, once the new theme has painted.
 */
export function applyTheme(theme: string, doc: Document = document): void {
  const root = doc.documentElement;
  if (root.getAttribute("data-theme") === theme) return;
  const style = doc.createElement("style");
  style.textContent = "*,*::before,*::after{transition:none!important}";
  doc.head.appendChild(style);
  root.setAttribute("data-theme", theme);
  void doc.body?.offsetHeight;   // read for its side effect: styles flush while transitions are off
  const raf = doc.defaultView?.requestAnimationFrame?.bind(doc.defaultView);
  if (raf) raf(() => raf(() => style.remove()));
  else style.remove();
}
