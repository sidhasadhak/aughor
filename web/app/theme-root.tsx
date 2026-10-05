"use client";

/**
 * Radix Themes' root, drawn ON `<html>` (ROADMAP §6 item 44).
 *
 * `<Theme asChild>` puts its class and its `data-*` attributes on the element it is given
 * instead of on a `<div>` of its own. Given `<html>`, the Theme's variables are declared at
 * the root — which is where every Instrument token is declared too
 * (`aughor-v2/theme/tokens-v2.css`), each as a name for a Radix step. So a token resolves
 * against the person's accent, grey, radius and scaling everywhere: the page, the body's own
 * background, a toast or a menu portalled into `<body>`. A Theme on a wrapper inside `<body>`
 * leaves all of those on the default look.
 *
 * Two inputs. The skin is `<html data-theme>`, the attribute the app has always switched
 * (`lib/themeSwitch.ts`); the four knobs are the look (`lib/look.ts`).
 */
import { useEffect, useState } from "react";
import { Theme } from "@radix-ui/themes";

import { useLook } from "@/lib/look";

/** Light or dark, as `<html data-theme>` says it. */
function useAppearance(): "light" | "dark" {
  const [mode, setMode] = useState<"light" | "dark">("dark");
  useEffect(() => {
    const root = document.documentElement;
    const sync = () => setMode(root.getAttribute("data-theme") === "light" ? "light" : "dark");
    sync();
    const seen = new MutationObserver(sync);
    seen.observe(root, { attributes: true, attributeFilter: ["data-theme"] });
    return () => seen.disconnect();
  }, []);
  return mode;
}

export function ThemeRoot({ children }: { children: React.ReactElement }) {
  const appearance = useAppearance();
  const look = useLook();
  return (
    // No background of its own: `body` paints the page from `--bg-0`, as it always has.
    <Theme asChild appearance={appearance} accentColor={look.accent} grayColor={look.grey}
      radius={look.radius} scaling={look.scaling} panelBackground="solid" hasBackground={false}>
      {children}
    </Theme>
  );
}
