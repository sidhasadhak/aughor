/**
 * A design token's value, for script that needs a real colour or a real number.
 *
 * Most of the app never reads a token: it writes `var(--b1)` and the browser does the rest.
 * Three things cannot — the result grid (Ant Design derives shades in script), the charts
 * (Vega is handed a config of colours) and a chart's PNG export — and since 2026-10-06 what
 * they read is not a hex. A token is a name for a Radix step, and on a wide-gamut screen
 * Radix declares its steps as `color(display-p3 …)`; a page colour may be the keyword
 * `white`. A colour parser that knows hex and `rgb()` makes black of both.
 *
 * So one reader, used by all three: the value is painted on a 1×1 canvas and read back,
 * which is the browser's own conversion to sRGB. Where there is no stylesheet (the server,
 * a test), the fallback is `lib/tokenFallback.ts` — the same steps at the default look.
 */
import { useEffect, useState } from "react";

import { TOKEN_FALLBACK, type TokenName } from "@/lib/tokenFallback";

const HEX = /^#(?:[0-9a-f]{3}|[0-9a-f]{6})$/i;
const SENTINEL = "#010203";
const converted = new Map<string, string>();
let ctx: CanvasRenderingContext2D | null | undefined;

function canvas(): CanvasRenderingContext2D | null {
  if (ctx !== undefined) return ctx;
  try {
    const el = document.createElement("canvas");
    el.width = el.height = 1;
    ctx = el.getContext("2d", { willReadFrequently: true });
  } catch {
    ctx = null;   // no canvas here (a test's document)
  }
  return ctx ?? null;
}

const two = (n: number) => n.toString(16).padStart(2, "0");

/** Any CSS colour as sRGB: `#rrggbb`, or `rgba(…)` when it is see-through. "" when the
 *  browser does not read it as a colour at all. */
export function toSrgb(value: string): string {
  const v = value.trim();
  if (!v) return "";
  if (HEX.test(v)) return v;
  const known = converted.get(v);
  if (known !== undefined) return known;
  const c = canvas();
  if (!c) return "";
  c.fillStyle = SENTINEL;
  c.fillStyle = v;                       // an unreadable value leaves the sentinel standing
  let out = "";
  if (c.fillStyle !== SENTINEL || v.toLowerCase() === SENTINEL) {
    c.clearRect(0, 0, 1, 1);
    c.fillRect(0, 0, 1, 1);
    const [r, g, b, a] = c.getImageData(0, 0, 1, 1).data;
    out = a === 255 ? `#${two(r)}${two(g)}${two(b)}`
      : a === 0 ? "rgba(0, 0, 0, 0)"
      // The canvas holds colour premultiplied; divide it back out.
      : `rgba(${Math.round(r * 255 / a)}, ${Math.round(g * 255 / a)}, ${Math.round(b * 255 / a)}, ${+(a / 255).toFixed(3)})`;
  }
  converted.set(v, out);
  return out;
}

const skinNow = (): "light" | "dark" =>
  typeof document !== "undefined" && document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark";

/** A colour token as it stands on the page now, in sRGB. */
export function tokenColor(name: TokenName, mode: "light" | "dark" = skinNow()): string {
  const fallback = TOKEN_FALLBACK[mode][name];
  if (typeof window === "undefined") return fallback;
  const raw = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return (raw && toSrgb(raw)) || fallback;
}

/** A length token in pixels — a Radix radius is a `calc()`, which only layout can resolve. */
export function tokenPx(name: string, fallback: number): number {
  if (typeof document === "undefined" || !document.body) return fallback;
  const probe = document.createElement("div");
  probe.style.cssText = `position:absolute;visibility:hidden;pointer-events:none;width:var(${name})`;
  document.body.appendChild(probe);
  const px = parseFloat(getComputedStyle(probe).width);
  probe.remove();
  return Number.isFinite(px) && px > 0 ? px : fallback;
}

/** What `<html>` says about the skin and the look. A token's value can change when any of
 *  these does, so script that has read tokens reads them again when this string changes. */
const WATCHED = ["data-theme", "data-accent-color", "data-gray-color", "data-radius", "data-scaling", "class"];
const stampNow = (): string =>
  typeof document === "undefined" ? "" : WATCHED.map(a => document.documentElement.getAttribute(a) ?? "").join("|");

export function useThemeStamp(): string {
  const [stamp, setStamp] = useState(stampNow);
  useEffect(() => {
    const sync = () => setStamp(stampNow());
    sync();
    const seen = new MutationObserver(sync);
    seen.observe(document.documentElement, { attributes: true, attributeFilter: WATCHED });
    return () => seen.disconnect();
  }, []);
  return stamp;
}
