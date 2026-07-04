"use client";

// Agent Context surface (P2) — the AI FDE "resource ribbon": make the working
// context the agent was given an explicit, inspectable, editable object. Shows
// which tables the agent saw and the token budget they cost, and lets the user
// trim tables to shrink the context (deterministic rescope, no agent re-run).

import { useMemo, useState } from "react";
import { formatCount } from "@/lib/format";
import { rescopeContext } from "@/lib/api";
import type { ContextManifest } from "@/lib/investigationStream";

export function ContextRibbon({
  manifest,
  connectionId,
}: {
  manifest: ContextManifest;
  connectionId: string;
}) {
  const initial = useMemo(() => manifest.tables, [manifest]);
  const [kept, setKept] = useState<string[]>(initial);
  const [tokens, setTokens] = useState<number>(manifest.estimated_tokens);
  const [baseline] = useState<number>(manifest.estimated_tokens);
  const [busy, setBusy] = useState(false);

  const removed = initial.filter((t) => !kept.includes(t));
  const delta = baseline - tokens;

  async function apply(next: string[]) {
    setKept(next);
    setBusy(true);
    try {
      const r = await rescopeContext(connectionId, next);
      setTokens(r.scoped_tokens);
      setKept(r.manifest.tables); // FK expansion may re-add bridge tables
    } catch {
      /* leave the optimistic set; token count just won't update */
    } finally {
      setBusy(false);
    }
  }

  const short = (t: string) => (t.includes(".") ? t.split(".").slice(-1)[0] : t);

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center gap-2 aug-text-xs" style={{ color: "var(--t4)" }}>
        <span className="uppercase tracking-wide">Context</span>
        <span style={{ color: "var(--t3)" }}>
          {kept.length} table{kept.length === 1 ? "" : "s"} · ~{formatCount(tokens)} tokens
        </span>
        {delta > 0 && (
          <span className="font-mono" style={{ color: "#4ade80" }}>
            −{formatCount(delta)} tok
          </span>
        )}
        {busy && <span style={{ color: "var(--t4)" }}>…</span>}
      </div>

      <div className="flex flex-wrap gap-1">
        {kept.map((t) => (
          <button
            key={t}
            title={`Remove ${t} from the agent's context`}
            onClick={() => apply(kept.filter((x) => x !== t))}
            className="group inline-flex items-center gap-1 rounded px-1.5 py-0.5 aug-text-xs font-mono transition-colors"
            style={{ background: "var(--panel2, #16212c)", color: "var(--t2)" }}
          >
            {short(t)}
            <span className="opacity-40 group-hover:opacity-100" style={{ color: "#f87171" }}>
              ✕
            </span>
          </button>
        ))}
      </div>

      {removed.length > 0 && (
        <div className="flex flex-wrap items-center gap-1 aug-text-xs" style={{ color: "var(--t4)" }}>
          <span>add back:</span>
          {removed.map((t) => (
            <button
              key={t}
              onClick={() => apply([...kept, t])}
              className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 font-mono transition-colors hover:opacity-100 opacity-70"
              style={{ border: "1px dashed var(--border, #2a3742)", color: "var(--t3)" }}
            >
              + {short(t)}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
