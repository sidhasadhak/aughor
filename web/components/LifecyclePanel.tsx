"use client";
/**
 * V6b — the lifecycle React panel, the deferral Wave V carried since #219.
 *
 * One compact surface over the kernel's artifact lifecycle: the revision
 * history (draft/published, when), publish and revert (history is never
 * rewound — a revert is a NEW version), and the freeze pin with its honesty
 * badge — a drifted pin says "this lags", it never wears an ok it hasn't
 * earned, and a refused freeze (409) shows the refusal's reason instead of a
 * lock icon over a guarantee that does not exist.
 */
import { useCallback, useEffect, useState } from "react";
import { getApiBase } from "@/lib/config";
import { formatTimestamp } from "@/lib/format";
import { Button } from "@/components/ui/button";

interface Revision {
  version: number;
  state: string;
  created_at: string;
  published_at?: string | null;
}

interface FreezeState {
  frozen: boolean;
  version?: number | null;
  status?: string;
  reason?: string;
  describe?: string;
}

async function _json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail ?? `HTTP ${res.status}`);
  }
  return res.json();
}

export function LifecyclePanel({
  kind,
  naturalKey,
  connectionId,
}: {
  kind: string;
  /** e.g. `canvas:<id>` — the artifact's stable lifecycle key. */
  naturalKey: string;
  /** Needed only to freeze (the pin records the data behind the version). */
  connectionId?: string;
}) {
  const [revisions, setRevisions] = useState<Revision[]>([]);
  const [published, setPublished] = useState<number | null>(null);
  const [freeze, setFreeze] = useState<FreezeState | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const base = getApiBase();
  const qk = `natural_key=${encodeURIComponent(naturalKey)}`;

  const load = useCallback(async () => {
    try {
      const h = await _json<{ revisions: Revision[]; published_version: number | null }>(
        await fetch(`${base}/lifecycle/${kind}/history?${qk}`));
      setRevisions(h.revisions);
      setPublished(h.published_version);
      setFreeze(await _json<FreezeState>(await fetch(`${base}/lifecycle/${kind}/freeze?${qk}`)));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "lifecycle unavailable");
    }
  }, [base, kind, qk]);

  useEffect(() => { void load(); }, [load]);

  const act = async (fn: () => Promise<Response>) => {
    setBusy(true);
    setError(null);
    try {
      await _json(await fn());
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "action failed");
    } finally {
      setBusy(false);
    }
  };

  const publish = (version?: number) => act(() => fetch(
    `${base}/lifecycle/${kind}/publish?${qk}${version != null ? `&version=${version}` : ""}`,
    { method: "POST" }));
  const revert = (toVersion: number) => act(() => fetch(
    `${base}/lifecycle/${kind}/revert?${qk}&to_version=${toVersion}`, { method: "POST" }));
  const pin = (version: number) => act(() => fetch(
    `${base}/lifecycle/${kind}/freeze?${qk}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ connection_id: connectionId ?? "", version, tables: [] }),
    }));
  const unpin = () => act(() => fetch(`${base}/lifecycle/${kind}/freeze?${qk}`, { method: "DELETE" }));

  if (!revisions.length && !error) return null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: "var(--t2)" }}>History &amp; lifecycle</div>

      {freeze?.frozen && (
        <div style={{ fontSize: 11, padding: "4px 8px", borderRadius: "var(--r2)",
                      background: "var(--bg-2)", border: "1px solid var(--b2)",
                      color: freeze.status === "ok" ? "var(--t2)" : "var(--amb4, var(--t2))" }}>
          {freeze.status === "ok"
            ? `Pinned to v${freeze.version}`
            : `Pinned to v${freeze.version} — ${freeze.reason || "drifted"}`}
          <Button variant="ghost" size="xs" disabled={busy} onClick={unpin}
                  className="h-auto p-0 ml-2 aug-fs-xs font-normal text-zinc-500 hover:text-zinc-300 hover:bg-transparent dark:hover:bg-transparent">
            Unfreeze
          </Button>
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 1, maxHeight: 180, overflowY: "auto" }}>
        {revisions.map((r) => (
          <div key={r.version}
               style={{ display: "flex", alignItems: "center", gap: 8, padding: "4px 8px",
                        borderRadius: "var(--r1)", background: "var(--bg-1)", fontSize: 11 }}>
            <span style={{ color: "var(--t1)", minWidth: 28 }}>v{r.version}</span>
            <span style={{ color: "var(--t3)", flex: 1 }}>
              {r.version === published ? "published" : r.state}
              {" · "}{formatTimestamp(r.created_at)}
            </span>
            {r.version !== published && (
              <Button variant="ghost" size="xs" disabled={busy} onClick={() => publish(r.version)}
                      className="h-auto p-0 aug-fs-xs font-normal text-zinc-500 hover:text-zinc-300 hover:bg-transparent dark:hover:bg-transparent">
                Publish
              </Button>
            )}
            <Button variant="ghost" size="xs" disabled={busy} onClick={() => revert(r.version)}
                    title="Restore this version's content as a NEW version — history is never rewound"
                    className="h-auto p-0 aug-fs-xs font-normal text-zinc-500 hover:text-zinc-300 hover:bg-transparent dark:hover:bg-transparent">
              Revert to
            </Button>
            {!freeze?.frozen && (
              <Button variant="ghost" size="xs" disabled={busy} onClick={() => pin(r.version)}
                      title="Pin the artifact to this version and the data behind it"
                      className="h-auto p-0 aug-fs-xs font-normal text-zinc-500 hover:text-zinc-300 hover:bg-transparent dark:hover:bg-transparent">
                Freeze
              </Button>
            )}
          </div>
        ))}
      </div>

      {error && <div style={{ fontSize: 11, color: "var(--red4, #f87171)" }}>{error}</div>}
    </div>
  );
}
