"use client";
/* ── Documents · Connected sources ──────────────────────────────────────────
   Confluence / Notion knowledge sources, on the surface their content lands on
   (decided 2026-09-06): both connectors feed the SAME doc corpus as an upload,
   so they are connected here, beside upload — not in "Add data", where a person
   expects tables. The connect form's fields are SERVED by the backend
   (/knowledge/sources) from the connector registry: a new field appears here
   with no frontend change, and a secret field renders as a password input whose
   value never comes back out of the server. */
import { useCallback, useEffect, useState } from "react";
import {
  createKnowledgeSource,
  getKnowledgeSources,
  triggerKnowledgeSync,
  type KnowledgeSource,
  type KnowledgeSourceType,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

function timeAgo(iso?: string | null): string {
  if (!iso) return "never";
  const mins = Math.floor((Date.now() - new Date(iso).getTime()) / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function pagesOf(source: KnowledgeSource): number | null {
  const pages = source.status?.pages_indexed;
  if (pages == null) return null;
  if (typeof pages === "number") return pages;
  return Object.values(pages).reduce((a, b) => a + b, 0);
}

export function KnowledgeSourcesSection() {
  const [types, setTypes] = useState<KnowledgeSourceType[]>([]);
  const [sources, setSources] = useState<KnowledgeSource[]>([]);
  const [connecting, setConnecting] = useState<KnowledgeSourceType | null>(null);
  const [form, setForm] = useState<Record<string, string>>({});
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [syncing, setSyncing] = useState<string | null>(null);

  // A load that cannot reach the API leaves the section on its empty state — the state it already
  // renders before the first answer arrives, and the one it shows when nothing is connected. Every
  // other call in this component catches (connect, sync), and so does every loader in the panel
  // beside it; this one did not, so an offline browser got an unhandled rejection instead of
  // "None yet".
  const load = useCallback(async () => {
    const out = await getKnowledgeSources().catch(() => null);
    if (out) { setTypes(out.types); setSources(out.sources); }
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
      // The sync runs as a background task server-side; give it a beat, then re-read
      // its state file through the same status the list already renders.
      setTimeout(() => { load(); setSyncing(null); }, 4000);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Sync failed");
      setSyncing(null);
    }
  };

  return (
    <div className="rounded-md border border-zinc-700 bg-zinc-900/40 p-4 space-y-3">
      <div className="flex items-baseline gap-2">
        <h3 className="aug-fs-ui font-semibold text-zinc-200">Connected sources</h3>
        <p className="aug-fs-xs text-zinc-500">
          Confluence and Notion pages land in the same corpus as an upload.
        </p>
        <span className="flex-1" />
        {types.map(t => (
          <Button key={t.conn_type} variant="ghost" size="xs" disabled={busy}
            onClick={() => { setConnecting(connecting?.conn_type === t.conn_type ? null : t); setForm({}); setError(null); }}
            className="h-auto px-2 py-0.5 aug-fs-xs font-normal border border-zinc-700 text-zinc-300">
            {connecting?.conn_type === t.conn_type ? "Cancel" : `+ ${t.label}`}
          </Button>
        ))}
      </div>

      {connecting && (
        <div className="rounded border border-zinc-700 bg-zinc-950/60 p-3 space-y-2">
          <p className="aug-fs-sm text-zinc-300 font-medium">Connect {connecting.label}</p>
          <Input value={name} onChange={e => setName(e.target.value)}
                 placeholder={`Name (e.g. Team ${connecting.label})`}
                 className="aug-fs-sm" />
          {connecting.fields.map(f => (
            <Input key={f.key}
                   type={f.secret ? "password" : "text"}
                   value={form[f.key] ?? ""}
                   onChange={e => setForm(prev => ({ ...prev, [f.key]: e.target.value }))}
                   placeholder={`${f.label}${f.placeholder ? ` — ${f.placeholder}` : ""}`}
                   className="aug-fs-sm" />
          ))}
          <div className="flex items-center gap-2">
            <Button size="xs" disabled={busy} onClick={connect}
                    className="h-auto px-2.5 py-1 aug-fs-xs">
              {busy ? "Testing…" : "Test & connect"}
            </Button>
            <p className="aug-fs-xs text-zinc-500">
              Credentials are tested live before anything is saved, then encrypted at rest.
            </p>
          </div>
        </div>
      )}

      {error && (
        <p className="aug-fs-xs text-red-400 font-mono whitespace-pre-wrap">{error}</p>
      )}

      {sources.length === 0 && !connecting && (
        <p className="aug-fs-xs text-zinc-600">
          None yet — connect a wiki and its pages become retrievable context.
        </p>
      )}

      {sources.map(s => {
        const pages = pagesOf(s);
        return (
          <div key={s.id} className="flex items-center gap-3 rounded border border-zinc-800 bg-zinc-800/40 px-3 py-2">
            <span className="aug-fs-xs font-mono px-1.5 py-0.5 rounded border border-violet-500/30 bg-violet-500/10 text-violet-400">
              {s.conn_type === "confluence" ? "Confluence" : "Notion"}
            </span>
            <div className="flex-1 min-w-0">
              <p className="aug-fs-sm text-zinc-200 truncate">{s.name}</p>
              <p className="aug-fs-xs text-zinc-500 font-mono mt-0.5">
                {s.error ? s.error
                  : <>last sync {timeAgo(s.status?.last_sync)}{pages != null && <> · {pages} pages indexed</>}</>}
              </p>
            </div>
            <Button variant="ghost" size="xs" disabled={syncing === s.id}
                    onClick={() => sync(s.id)}
                    className="h-auto px-2 py-1 aug-fs-xs font-normal border border-zinc-700 text-zinc-300">
              {syncing === s.id ? "Syncing…" : "Sync now"}
            </Button>
          </div>
        );
      })}
    </div>
  );
}
