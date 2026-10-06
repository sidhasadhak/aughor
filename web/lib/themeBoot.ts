/**
 * The skin and the look before the first paint.
 *
 * Both live in this browser (`lib/themeSwitch.ts` keeps the skin under THEME_KEY, `lib/look.ts`
 * the look under LOOK_KEY) and both reach `<html>` from React — the skin as `data-theme` and
 * the Radix class, the look as the Theme's own `data-*` attributes. React can only do that
 * after it hydrates, so a light-skin reader saw a dark frame on every load, and a person with
 * their own accent saw indigo for that frame. This script runs in `<head>`, before the body
 * paints, and sets what React will set — so hydration finds the attributes already right and
 * leaves them (the root carries `suppressHydrationWarning`, as it does for the rail's `data-nav`).
 *
 * The lists are the same arrays the Theme is handed (`LOOK_VALUES`): a stored value that is not
 * one of them is left to the default, exactly as `cleanLook` leaves it.
 */
import { DEFAULT_LOOK, LOOK_KEY, LOOK_VALUES, type Look } from "@/lib/lookValues";
import { THEME_KEY } from "@/lib/themeSwitch";

/** Which `<html>` attribute Radix Themes keeps each knob in. */
export const LOOK_ATTRIBUTE: Record<keyof Look, string> = {
  accent: "data-accent-color",
  grey: "data-gray-color",
  radius: "data-radius",
  scaling: "data-scaling",
};

/** Inline and pre-paint. Blocked storage, or nothing stored, leaves the default: dark, indigo. */
export const THEME_BOOT = [
  "try{",
  "var d=document.documentElement,s=localStorage;",
  `var t=s.getItem(${JSON.stringify(THEME_KEY)})==="light"?"light":"dark";`,
  'd.setAttribute("data-theme",t);d.classList.remove("light","dark");d.classList.add(t);d.style.colorScheme=t;',
  `var l=JSON.parse(s.getItem(${JSON.stringify(LOOK_KEY)})||"{}")||{};`,
  `var v=${JSON.stringify(LOOK_VALUES)},a=${JSON.stringify(LOOK_ATTRIBUTE)},f=${JSON.stringify(DEFAULT_LOOK)};`,
  "for(var k in v)d.setAttribute(a[k],v[k].indexOf(l[k])>=0?l[k]:f[k]);",
  "}catch(e){}",
].join("");
