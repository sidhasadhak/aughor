"use client";
/* ── Documents · Connected sources ──────────────────────────────────────────
   Confluence / Notion knowledge sources, on the surface their content lands on
   (decided 2026-09-06): both connectors feed the SAME doc corpus as an upload,
   so they are connected here, beside upload — not in "Add data", where a person
   expects tables. The connect form's fields are SERVED by the backend
   (/knowledge/sources) from the connector registry: a new field appears here
   with no frontend change, and a secret field renders as a password input whose
   value never comes back out of the server.

   Redone to CLARITY (2026-10-13): one card, its connect buttons at the label's
   right end, "none yet" one muted line; the form opens only when asked. */
import { useCallback, useEffect, useRef, useState } from "react";

import { Card, Chip, Empty, MUTED, ONE_LINE, ROW, RULE } from "@/components/clarity/kit";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ReadFailed } from "@/components/ui/states";
import {
  createKnowledgeSource,
  getKnowledgeSources,
  triggerKnowledgeSync,
  type KnowledgeSource,
  type KnowledgeSourceType,
} from "@/lib/api";
import { relTime } from "@/lib/format";

function pagesOf(source: KnowledgeSource): number | null {
  const pages = source.status?.pages_indexed;
  if (pages == null) return null;
  if (typeof pages === "number") return pages;
  return Object.values(pages).reduce((a, b) => a + b, 0);
}

export function KnowledgeSourcesSection({ onSources }: {
  /** What was read, for the screen's figures: the sources, or null when the read failed. */
  onSources?: (sources: KnowledgeSource[] | null, types: KnowledgeSourceType[]) => void;
} = {}) {
  const [types, setTypes] = useState<KnowledgeSourceType[]>([]);
  const [sources, setSources] = useState<KnowledgeSource[]>([]);
  const [connecting, setConnecting] = useState<KnowledgeSourceType | null>(null);
  const [form, setForm] = useState<Record<string, string>>({});
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [syncing, setSyncing] = useState<string | null>(null);

  // A load that cannot reach the API is said, with a Retry. It used to leave the section on its empty state
  // ("None yet") — the one it shows when nothing is connected — so a failed read taught the reader that no source
  // existed.
  const [loadFailed, setLoadFailed] = useState<string | null>(null);
  // Held in a ref, so a parent that hands a fresh function each render does not re-run the read.
  const report = useRef(onSources);
  useEffect(() => { report.current = onSources; });
  const load = useCallback(async () => {
    try {
      const out = await getKnowledgeSources();
      setTypes(out.types); setSources(out.sources); setLoadFailed(null);
      report.current?.(out.sources, out.types);
    } catch (e) {
      setLoadFailed(e instanceof Error ? e.message : String(e));
      report.current?.(null, []);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const connect = async () => {
    if (!connecting) return;
    setBusy(true);
    setError(null);
    try {
      await createKnowledgeSource(connecting.conn_type, name, form);
      setConnecting(null);
      setForm({});
      setName("");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Connect failed");
    } finally {
      setBusy(false);
    }
  };

  const sync = async (id: string) => {
    setSyncing(id);
    setError(null);
    try {
      await triggerKnowledgeSync(id);
      // The sync runs as a background task server-side; give it a beat, then re-read its state file through the same
      // status the list already renders.
      setTimeout(() => { load(); setSyncing(null); }, 4000);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Sync failed");
      setSyncing(null);
    }
  };

  return (
    <Card label="Connected sources" testId="knowledge-sources"
      right={types.map(t => (
        <Button key={t.conn_type} variant="ghost" size="xs" disabled={busy}
          onClick={() => { setConnecting(connecting?.conn_type === t.conn_type ? null : t); setForm({}); setError(null); }}>
          {connecting?.conn_type === t.conn_type ? "Cancel" : `+ ${t.label}`}
        </Button>
      ))}>
      {connecting && (
        <div style={{ background: "var(--bg-1)", borderRadius: "var(--r2)", padding: 12, marginBottom: 10,
          display: "flex", flexDirection: "column", gap: 8 }}>
          <div className="aug-fs-sm" style={{ color: "var(--t1)", fontWeight: 500 }}>Connect {connecting.label}</div>
          <Input value={name} onChange={e => setName(e.target.value)}
                 placeholder={`Name (e.g. Team ${connecting.label})`} />
          {connecting.fields.map(f => (
            <Input key={f.key}
                   type={f.secret ? "password" : "text"}
                   value={form[f.key] ?? ""}
                   onChange={e => setForm(prev => ({ ...prev, [f.key]: e.target.value }))}
                   placeholder={`${f.label}${f.placeholder ? ` — ${f.placeholder}` : ""}`} />
          ))}
          <div style={ROW}>
            <Button size="xs" disabled={busy} onClick={connect}>{busy ? "Testing…" : "Test & connect"}</Button>
            <span className="aug-fs-xs" style={MUTED}>Credentials are tested live before anything is saved, then encrypted at rest.</span>
          </div>
        </div>
      )}

      {error && (
        <p role="alert" className="aug-fs-xs" style={{ color: "var(--red4)", fontFamily: "var(--font-mono)", whiteSpace: "pre-wrap", margin: "0 0 8px" }}>
          {error}
        </p>
      )}

      {loadFailed !== null ? (
        <ReadFailed what="the knowledge sources" error={loadFailed} onRetry={load} />
      ) : sources.length === 0 && !connecting && (
        <Empty>None yet — a connected wiki&apos;s pages land in the same corpus as an upload.</Empty>
      )}

      {sources.map((s, i) => {
        const pages = pagesOf(s);
        const skippedCount = s.status?.skipped_count ?? 0;
        const skipped = s.status?.pages_skipped ?? [];
        return (
          <div key={s.id} data-testid="knowledge-source" style={{ ...(i ? RULE : {}), padding: "8px 2px" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <Chip>{s.conn_type === "confluence" ? "Confluence" : "Notion"}</Chip>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div className="aug-fs-chrome" style={{ ...ONE_LINE, color: "var(--t1)", fontWeight: 500 }}>{s.name}</div>
                <div className="aug-fs-xs" style={{ ...(s.error ? { color: "var(--red4)" } : MUTED), ...ONE_LINE }} title={s.error}>
                  {s.error ? s.error
                    : <>last sync {s.status?.last_sync ? `${relTime(s.status.last_sync)} ago` : "never"}
                        {pages != null && <> · {pages} pages indexed</>}
                        {skippedCount > 0 && <> · {skippedCount} not indexed</>}</>}
                </div>
              </div>
              <Button variant="ghost" size="xs" disabled={syncing === s.id} onClick={() => sync(s.id)}>
                {syncing === s.id ? "Syncing…" : "Sync now"}
              </Button>
            </div>
            {/* The pages the last sync left out, each with why — a short page used to vanish with nothing on this row
                to say it had existed. */}
            {!s.error && skippedCount > 0 && (
              <details style={{ marginTop: 4 }}>
                <summary className="aug-fs-xs" style={{ color: "var(--t2)", cursor: "pointer" }}>
                  {skippedCount} {skippedCount === 1 ? "page was" : "pages were"} not indexed
                </summary>
                <ul style={{ margin: "4px 0 0", padding: 0, listStyle: "none" }}>
                  {skipped.map((p, k) => (
                    <li key={`${p.url}:${k}`} className="aug-fs-xs" style={MUTED}>
                      {p.url ? <a href={p.url} target="_blank" rel="noreferrer" style={{ color: "var(--t1)" }}>{p.title}</a>
                        : <span style={{ color: "var(--t1)" }}>{p.title}</span>} — {p.reason}
                    </li>
                  ))}
                  {skippedCount > skipped.length && (
                    <li className="aug-fs-xs" style={MUTED}>…and {skippedCount - skipped.length} more, not listed.</li>
                  )}
                </ul>
              </details>
            )}
          </div>
        );
      })}
    </Card>
  );
}
