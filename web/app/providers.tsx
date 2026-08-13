"use client";

/**
 * App-wide client providers.
 *
 * Exists for one reason today: a single `QueryClient` for the whole app, so a request
 * that several components independently need is issued once. Measured before this
 * landed, one page load fired `GET /connections/{id}/schema/rich` **twenty-plus
 * times** — seven components each fetching the same answer, none aware of the others.
 *
 * The client is created inside a `useState` initializer rather than at module scope.
 * A module-level client is shared across every request on the server, which in a
 * Next.js app means one user's cached data can be handed to the next — the standard
 * TanStack Query SSR footgun. Per-mount creation keeps the cache per browser session.
 *
 * Scope note: the SQL-editor program's DP-3 deliberately confined TanStack Query to
 * `components/query/`. This provider is the follow-on that decision anticipated (see
 * the supersession notes in WORLD_CLASS_HARDENING_PLAN.md, WCH-11) — done as its own
 * change rather than smuggled inside a feature PR, and it replaces the workbench's
 * local client rather than adding a second one.
 */
import { useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(() => new QueryClient({
    defaultOptions: {
      queries: {
        // Schema shape changes when the warehouse changes, not between two panels
        // rendering in the same second. Five minutes is long enough to collapse a
        // page load into one request and short enough that a real DDL change shows
        // up without a reload; the explicit refresh path invalidates immediately.
        staleTime: 5 * 60_000,
        gcTime: 10 * 60_000,
        refetchOnWindowFocus: false,
        retry: 1,
      },
    },
  }));

  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
