/**
 * The navigation rail's collapsed state: an attribute on <html>, remembered per browser.
 *
 * The attribute, not React state, is the truth, because it must be right before the first paint —
 * a rail that renders open and then snaps shut shifts the whole screen on every load. The root
 * layout runs NAV_COLLAPSE_BOOT in <head> to set it from storage before the body paints, CSS keyed
 * on it draws the collapsed rail, and useNavCollapsed() follows it for aria and hover labels.
 * Per browser, not per user: how wide a rail should be depends on the screen it is on.
 */
export const NAV_COLLAPSED_KEY = "aughor_nav_collapsed";

/** Inline and pre-paint: set data-nav from storage. Blocked storage leaves the rail open. */
export const NAV_COLLAPSE_BOOT =
  `try{if(localStorage.getItem("${NAV_COLLAPSED_KEY}")==="1")document.documentElement.setAttribute("data-nav","collapsed")}catch(e){}`;

export function isNavCollapsed(doc: Document = document): boolean {
  return doc.documentElement.getAttribute("data-nav") === "collapsed";
}

export function setNavCollapsed(collapsed: boolean, doc: Document = document): void {
  if (collapsed) doc.documentElement.setAttribute("data-nav", "collapsed");
  else doc.documentElement.removeAttribute("data-nav");
  try {
    doc.defaultView?.localStorage.setItem(NAV_COLLAPSED_KEY, collapsed ? "1" : "0");
  } catch {
    // Storage refused: the attribute still holds for this page.
  }
}
