import { useCallback, useEffect, useSyncExternalStore } from "react";

import { isNavCollapsed, setNavCollapsed } from "@/lib/navCollapse";

function subscribe(onChange: () => void) {
  const watcher = new MutationObserver(onChange);
  watcher.observe(document.documentElement, { attributes: true, attributeFilter: ["data-nav"] });
  return () => watcher.disconnect();
}

/**
 * The rail's collapsed state (lib/navCollapse.ts) and its toggle. ⌘\ or Ctrl+\ toggles it too —
 * except while focus is in a field or an editor, whose keys it must not take.
 */
export function useNavCollapsed(): [collapsed: boolean, toggle: () => void] {
  const collapsed = useSyncExternalStore(subscribe, () => isNavCollapsed(), () => false);
  const toggle = useCallback(() => setNavCollapsed(!isNavCollapsed()), []);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey) || e.key !== "\\") return;
      const target = e.target as HTMLElement | null;
      if (target && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName ?? ""))) return;
      e.preventDefault();
      toggle();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [toggle]);
  return [collapsed, toggle];
}
