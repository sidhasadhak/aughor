"use client";

import { useEffect, useState } from "react";
import { getCapabilities, type Capabilities } from "./api";

/**
 * Read the active tier + granted capabilities for show/lock/upsell UI.
 *
 * Fail-open by design: until the fetch resolves (and if it ever fails) `can()` returns
 * true, so the UI never flashes-locked or blocks. With the default `enterprise` tier the
 * server returns every capability, so nothing is gated until a lower tier is assigned.
 *
 *   const { can } = useCapabilities(connectionId);
 *   {can("monitors") ? <MonitorsPanel/> : <UpsellCard feature="Monitors" tier="Pro"/>}
 */
export function useCapabilities(connectionId?: string) {
  const [caps, setCaps] = useState<Capabilities | null>(null);

  useEffect(() => {
    let cancelled = false;
    getCapabilities(connectionId)
      .then(c => { if (!cancelled) setCaps(c); })
      .catch(() => { /* fail-open — leave caps null */ });
    return () => { cancelled = true; };
  }, [connectionId]);

  const can = (cap: string): boolean =>
    !caps || caps.capabilities.length === 0 || caps.capabilities.includes(cap);

  return {
    tier: caps?.tier ?? "enterprise",
    capabilities: caps?.capabilities ?? [],
    can,
    loading: caps === null,
  };
}
