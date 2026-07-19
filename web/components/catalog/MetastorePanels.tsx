"use client";

/**
 * Catalog Explorer — metastore panels (Databricks-style).
 *
 *  • VolumesPanel      — the governed unstructured tier: browse/create volumes,
 *                        upload/download/delete objects under a catalog.
 *  • PermissionsPanel  — workspace access to a catalog: membership ∪ explicit grants,
 *                        with grant/revoke of the explicit layer.
 *
 * Both wire to the /metastore endpoints. Styled with the app's .aug-* classes +
 * design tokens (var(--…)), matching CatalogScreen.
 */
import { useEffect, useState } from "react";
import {
  createVolume, listVolumes, listVolumeObjects, uploadVolumeObject,
  deleteVolumeObject, volumeObjectContentUrl,
  getWorkspaces, listWorkspaceGrants, grantWorkspaceCatalog, revokeWorkspaceCatalog,
  type MetastoreVolume, type MetastoreVolumeObject, type Workspace,
} from "@/lib/api";
import { Button } from "@/components/ui/button";

function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

// ── Volumes ────────────────────────────────────────────────────────────────────

export function VolumesPanel({ catalogId }: { catalogId: string }) {
  const [volumes, setVolumes] = useState<MetastoreVolume[]>([]);
  const [selected, setSelected] = useState<string>("");   // volume id
  const [objects, setObjects] = useState<MetastoreVolumeObject[]>([]);
  const [newName, setNewName] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const loadVolumes = () => {
    listVolumes(catalogId)
      .then(vs => { setVolumes(vs); if (vs.length && !vs.find(v => v.id === selected)) setSelected(vs[0].id); })
      .catch(e => setErr(String(e.message ?? e)));
  };
  useEffect(() => { setSelected(""); loadVolumes(); /* eslint-disable-next-line */ }, [catalogId]);
  useEffect(() => { if (selected) listVolumeObjects(selected).then(setObjects).catch(() => setObjects([])); else setObjects([]); }, [selected]);

  const create = async () => {
    if (!newName.trim()) return;
    setBusy(true); setErr("");
    try { const v = await createVolume(catalogId, newName.trim()); setNewName(""); loadVolumes(); setSelected(v.id); }
    catch (e) { setErr(String((e as Error).message)); }
    finally { setBusy(false); }
  };

  const onUpload = async (file: File) => {
    if (!selected) return;
    setBusy(true); setErr("");
    try { await uploadVolumeObject(selected, file); listVolumeObjects(selected).then(setObjects); }
    catch (e) { setErr(String((e as Error).message)); }
    finally { setBusy(false); }
  };

  const onDelete = async (objId: string) => {
    await deleteVolumeObject(selected, objId);
    listVolumeObjects(selected).then(setObjects);
  };

  return (
    <div style={{ flex: 1, display: "flex", minHeight: 0, overflow: "hidden" }}>
      {/* volume list */}
      <div style={{ width: 220, borderRight: "0.5px solid var(--b1)", display: "flex", flexDirection: "column", minHeight: 0 }}>
        <div style={{ padding: "10px 12px", borderBottom: "0.5px solid var(--b1)" }}>
          <div style={{ display: "flex", gap: 6 }}>
            <input className="aug-input" value={newName} onChange={e => setNewName(e.target.value)}
              onKeyDown={e => e.key === "Enter" && create()} placeholder="New volume…"
              style={{ flex: 1, fontSize: 12 }} />
            <Button variant="default" size="xs" disabled={busy || !newName.trim()} onClick={create}>Add</Button>
          </div>
        </div>
        <div style={{ flex: 1, overflowY: "auto" }}>
          {volumes.length === 0 && <p style={{ padding: 12, fontSize: 11, color: "var(--t4)" }}>No volumes yet.</p>}
          {volumes.map(v => (
            <div key={v.id} onClick={() => setSelected(v.id)}
              style={{ padding: "9px 12px", cursor: "pointer", borderBottom: "0.5px solid var(--b0)",
                background: v.id === selected ? "var(--bg-1)" : "transparent", display: "flex", alignItems: "center", gap: 8 }}>
              <IcoVolume />
              <span style={{ fontSize: 12, color: "var(--t1)", fontWeight: v.id === selected ? 600 : 400 }}>{v.name}</span>
            </div>
          ))}
        </div>
      </div>

      {/* object list for the selected volume */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0 }}>
        {!selected ? (
          <p style={{ padding: 20, fontSize: 12, color: "var(--t4)" }}>Select or create a volume to manage its objects.</p>
        ) : (
          <>
            <div style={{ padding: "10px 16px", borderBottom: "0.5px solid var(--b1)", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <span style={{ fontSize: 12, color: "var(--t2)" }}>{objects.length} object{objects.length !== 1 ? "s" : ""}</span>
              <label className="aug-btn aug-btn-sm aug-btn-primary" style={{ cursor: busy ? "default" : "pointer", opacity: busy ? 0.6 : 1 }}>
                {busy ? "Uploading…" : "Upload object"}
                <input type="file" style={{ display: "none" }} disabled={busy}
                  onChange={e => { const f = e.target.files?.[0]; if (f) onUpload(f); e.currentTarget.value = ""; }} />
              </label>
            </div>
            {err && <p style={{ padding: "8px 16px", fontSize: 11, color: "var(--red4)" }}>{err}</p>}
            <div style={{ flex: 1, overflowY: "auto" }}>
              {objects.length === 0 && <p style={{ padding: 20, fontSize: 12, color: "var(--t4)" }}>No objects. Upload a file to get started.</p>}
              {objects.map(o => (
                <div key={o.id} style={{ display: "grid", gridTemplateColumns: "1fr 90px 130px 120px", padding: "10px 16px", borderBottom: "0.5px solid var(--b0)", alignItems: "center", gap: 8 }}>
                  <span style={{ fontSize: 12, color: "var(--t1)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{o.name}</span>
                  <span style={{ fontSize: 11, color: "var(--t4)", textAlign: "right" }}>{fmtBytes(o.size_bytes)}</span>
                  <span style={{ fontSize: 11, color: "var(--t4)" }}>{o.mime_type}</span>
                  <span style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
                    <a href={volumeObjectContentUrl(selected, o.id)} target="_blank" rel="noreferrer"
                      style={{ fontSize: 11, color: "var(--blue4)", textDecoration: "none" }}>Download</a>
                    <button onClick={() => onDelete(o.id)} style={{ fontSize: 11, color: "var(--red4)", background: "none", border: "none", cursor: "pointer", padding: 0 }}>Delete</button>
                  </span>
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// ── Permissions (grants) ────────────────────────────────────────────────────────

export function PermissionsPanel({ catalogId }: { catalogId: string }) {
  const [rows, setRows] = useState<{ ws: Workspace; member: boolean; granted: boolean }[]>([]);
  const [busy, setBusy] = useState("");

  const load = async () => {
    const wss = await getWorkspaces();
    const out = await Promise.all(wss.map(async ws => {
      const granted = (await listWorkspaceGrants(ws.id).catch((): string[] => [])).includes(catalogId);
      return { ws, member: (ws.connection_ids || []).includes(catalogId), granted };
    }));
    setRows(out);
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [catalogId]);

  const toggle = async (wsId: string, granted: boolean) => {
    setBusy(wsId);
    try {
      if (granted) await revokeWorkspaceCatalog(wsId, catalogId);
      else await grantWorkspaceCatalog(wsId, catalogId);
      await load();
    } catch (e) {
      // A silent failure skipped load() and the grant appeared unchanged.
      window.alert(e instanceof Error ? e.message : "Grant change failed");
    } finally { setBusy(""); }
  };

  return (
    <div style={{ flex: 1, overflowY: "auto", padding: "16px 20px" }}>
      <p style={{ fontSize: 12, color: "var(--t2)", marginBottom: 16, maxWidth: 620, lineHeight: 1.5 }}>
        Which workspaces can access this catalog. The gate is <b style={{ color: "var(--t1)" }}>membership ∪ explicit grants</b> —
        a member sees it via its connection list; an <b style={{ color: "var(--t1)" }}>explicit grant</b> adds access beyond membership and is durable across membership edits.
      </p>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 160px 110px", padding: "5px 4px", borderBottom: "0.5px solid var(--b1)" }}>
        {["Workspace", "Access", ""].map(h => (
          <span key={h} style={{ fontSize: 11, color: "var(--t4)", textTransform: "uppercase", letterSpacing: "0.07em", fontWeight: 600 }}>{h}</span>
        ))}
      </div>
      {rows.map(({ ws, member, granted }) => (
        <div key={ws.id} style={{ display: "grid", gridTemplateColumns: "1fr 160px 110px", padding: "11px 4px", borderBottom: "0.5px solid var(--b0)", alignItems: "center" }}>
          <span style={{ fontSize: 12, color: "var(--t1)" }}>{ws.name}{ws.is_default ? " (default)" : ""}</span>
          <span style={{ display: "flex", gap: 6 }}>
            {member && <span className="aug-tag aug-tag-blue" style={{ fontSize: 10 }}>Member</span>}
            {granted && <span className="aug-tag aug-tag-green" style={{ fontSize: 10 }}>Granted</span>}
            {!member && !granted && <span style={{ fontSize: 11, color: "var(--t4)" }}>No access</span>}
          </span>
          <span style={{ justifySelf: "end" }}>
            {granted ? (
              <Button variant="ghost" size="xs" disabled={busy === ws.id} onClick={() => toggle(ws.id, true)}>Revoke</Button>
            ) : (
              <Button variant="default" size="xs" disabled={busy === ws.id} onClick={() => toggle(ws.id, false)}>Grant</Button>
            )}
          </span>
        </div>
      ))}
      {rows.length === 0 && <p style={{ padding: "16px 4px", fontSize: 12, color: "var(--t4)" }}>No workspaces.</p>}
    </div>
  );
}

function IcoVolume() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" style={{ color: "var(--vio4)", flexShrink: 0 }}>
      <path d="M2 4.5C2 3.7 2.7 3 3.5 3h9c.8 0 1.5.7 1.5 1.5v7c0 .8-.7 1.5-1.5 1.5h-9C2.7 13 2 12.3 2 11.5v-7Z" stroke="currentColor" strokeWidth="1.2" />
      <path d="M2 6h12" stroke="currentColor" strokeWidth="1.2" />
    </svg>
  );
}
