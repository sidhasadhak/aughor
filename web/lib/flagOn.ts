"use client";

/**
 * Whether one feature flag is on, for a leaf that offers a control only while it is — read once per page for every
 * leaf that asks, as `DecideDoor` reads its own. A read that fails (an older server, no network in a test) is off, and
 * is asked again next time: a control is never offered on a guess.
 */
import { useEffect, useState } from "react";

import { getSystemFlags } from "@/lib/api";

const reads = new Map<string, Promise<boolean>>();

export function flagOn(name: string): Promise<boolean> {
  let read = reads.get(name);
  if (!read) {
    read = Promise.resolve().then(() => getSystemFlags()).then(f => !!f?.[name]?.value).catch(() => {
      reads.delete(name);
      return false;
    });
    reads.set(name, read);
  }
  return read;
}

/** For tests: forget what was read, so the next read asks again. */
export function forgetFlags(): void {
  reads.clear();
}

export function useFlagOn(name: string): boolean {
  const [on, setOn] = useState(false);
  useEffect(() => {
    let alive = true;
    void flagOn(name).then(v => { if (alive) setOn(v); });
    return () => { alive = false; };
  }, [name]);
  return on;
}
