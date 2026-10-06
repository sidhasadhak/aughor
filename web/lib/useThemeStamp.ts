/**
 * What `<html>` says about the skin and the look, as one string. A token's value can change
 * when any of these does, so script that has read tokens (`lib/tokenColor.ts`) reads them
 * again when this changes. Its own module so the colour reader stays free of React — the
 * chart config that uses the reader is bundled for the headless export path.
 */
import { useEffect, useState } from "react";

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
