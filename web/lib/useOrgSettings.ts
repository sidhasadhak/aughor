"use client";

import { useSyncExternalStore } from "react";
import { orgSettingsVersion, subscribeOrgSettings } from "@/lib/orgSettings";

/**
 * Re-render the calling component when the org-settings cache changes (currency, chart
 * palette, date format). Returns the cache version — include it in option/memo deps so a
 * memoized chart rebuilds once the cache is populated, instead of capturing a stale empty
 * cache on first render.
 */
export function useOrgSettings(): number {
  return useSyncExternalStore(subscribeOrgSettings, orgSettingsVersion, () => 0);
}
