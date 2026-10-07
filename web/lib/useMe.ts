"use client";

import { useEffect, useState } from "react";

import { getMyAccess, type MyAccess } from "./api";
import { getIdToken } from "./auth";

/**
 * Who the person reading is, as the server records them (`GET /rbac/me`): the signed-in person,
 * else this install's own login. Every write is recorded under that name by the server itself, so
 * a form shows it and never asks for one.
 *
 * Read once and shared: several panels on one page ask, and one request answers them all. The
 * read is kept per sign-in token, so signing in or out reads it again; a failed read is not kept.
 */
let cached: { token: string | null; me: Promise<MyAccess | null> } | null = null;

function token(): string | null {
  try { return getIdToken(); } catch { return null; }
}

export function readMe(): Promise<MyAccess | null> {
  const t = token();
  if (cached && cached.token === t) return cached.me;
  const me: Promise<MyAccess | null> = getMyAccess().catch(() => {
    if (cached?.me === me) cached = null;
    return null;
  });
  cached = { token: t, me };
  return me;
}

/** Forget the shared read — for tests, which mock the server per case. */
export function forgetMe(): void {
  cached = null;
}

/** The reader as the server records them; null until it has answered (or when it could not). */
export function useMe(): MyAccess | null {
  const [me, setMe] = useState<MyAccess | null>(null);
  useEffect(() => {
    let live = true;
    void readMe().then(m => { if (live) setMe(m); });
    return () => { live = false; };
  }, []);
  return me;
}
