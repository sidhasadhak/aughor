"use client";

/**
 * SE-4 J — the version rail for a saved query.
 *
 * `update_saved_query` overwrites the only row, and has recorded a lifecycle revision
 * beside it since Wave V3 — but nothing could READ that history, so a saved query had a
 * version trail and no way to see or use it. This is the surface for it.
 *
 * **Selecting a version DIFFS it; it never loads it.** The rail shows what changed and
 * offers Restore as a separate, explicit act. A rail that swapped the editor's contents
 * on click would make browsing history indistinguishable from editing, and the thing you
 * were comparing against would be gone by the time you decided.
 *
 * The diff is `@codemirror/merge`'s unified view over the SQL, beside the server's
 * FIELD-level changelog for everything else — a spec change reports as a path
 * (`spec.filters[0].op`), which a text diff of re-indented JSON could not tell you.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { MergeView } from "@codemirror/merge";
import { EditorState } from "@codemirror/state";
import { Button } from "@/components/ui/button";
import { toast } from "@/components/ui/toast";
import { aughorEditorTheme, aughorSyntaxHighlighting } from "@/components/query/editor/theme";
import {
  listSavedQueryVersions, diffSavedQueryVersion, restoreSavedQuery,
  type SavedQueryVersion, type SavedQueryChange,
} from "@/lib/api";

export function VersionRail({
  queryId,
  onRestored,
}: {
  queryId: string;
  /** The live record changed — the mode that owns it must reload. */
  onRestored: () => void;
}) {
  const [versions, setVersions] = useState<SavedQueryVersion[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [changes, setChanges] = useState<SavedQueryChange[]>([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const host = useRef<HTMLDivElement | null>(null);
  const merge = useRef<MergeView | null>(null);

  const load = useCallback(async () => {
    if (!queryId) return;
    setLoading(true);
    try {
      const list = await listSavedQueryVersions(queryId);
      setVersions(list);
      setSelected(list.length > 1 ? list[0].version : null);
    } catch {
      setVersions([]);
    }
    setLoading(false);
  }, [queryId]);

  useEffect(() => { void load(); }, [load]);

  // Field-level changes for the selected version.
  useEffect(() => {
    if (selected === null) { setChanges([]); return; }
    let alive = true;
    void diffSavedQueryVersion(queryId, selected)
      .then(d => { if (alive) setChanges(d.changes); })
      .catch(() => { if (alive) setChanges([]); });
    return () => { alive = false; };
  }, [queryId, selected]);

  // The SQL diff. Rebuilt on selection change rather than reconfigured: MergeView owns
  // two documents, and swapping both is what a new comparison IS — there is no
  // incremental state worth preserving between two unrelated version pairs.
  useEffect(() => {
    merge.current?.destroy();
    merge.current = null;
    if (selected === null || !host.current) return;
    const idx = versions.findIndex(v => v.version === selected);
    if (idx < 0) return;
    const after = versions[idx];
    const before = versions[idx + 1];          // the one before it, newest-first
    if (!before) return;
    merge.current = new MergeView({
      a: { doc: before.sql ?? "", extensions: [EditorState.readOnly.of(true), aughorEditorTheme, aughorSyntaxHighlighting] },
      b: { doc: after.sql ?? "", extensions: [EditorState.readOnly.of(true), aughorEditorTheme, aughorSyntaxHighlighting] },
      parent: host.current,
      collapseUnchanged: { margin: 2, minSize: 4 },
      // Unified: this rail is narrow, and a side-by-side split inside it would give each
      // side ~120px — narrower than most SELECT lines, so every row would wrap.
      orientation: "a-b",
      gutter: false,
      highlightChanges: true,
    });
    return () => { merge.current?.destroy(); merge.current = null; };
  }, [selected, versions]);

  useEffect(() => () => { merge.current?.destroy(); }, []);

  const restore = async (version: number) => {
    setBusy(true);
    try {
      await restoreSavedQuery(queryId, version);
      toast.success(`Restored version ${version}`);
      await load();
      onRestored();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Restore failed");
    }
    setBusy(false);
  };

  if (!queryId) {
    return (
      <div style={{ padding: "12px 14px", fontSize: 13, color: "var(--t3)" }}>
        Save this query to start a version history.
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", minHeight: 0, flex: 1 }}>
      <div className="aug-label" style={{ padding: "8px 12px 4px", color: "var(--t3)" }}>
        Versions
      </div>

      {loading && (
        <div style={{ padding: "0 12px 8px", fontSize: 13, color: "var(--t3)" }}>Loading…</div>
      )}
      {!loading && versions.length === 0 && (
        <div style={{ padding: "0 12px 8px", fontSize: 13, color: "var(--t3)" }}>
          No versions yet — one is recorded each time you save a change.
        </div>
      )}

      <div style={{ overflow: "auto", maxHeight: 180, flexShrink: 0 }}>
        {versions.map((v, i) => (
          <button
            key={v.version}
            onClick={() => setSelected(v.version)}
            style={{
              display: "flex", alignItems: "baseline", gap: 8, width: "100%",
              textAlign: "left", padding: "4px 12px", border: "none", cursor: "pointer",
              background: v.version === selected ? "var(--bg-2)" : "transparent",
              color: "var(--t2)", fontSize: 13,
            }}
          >
            <span style={{ color: "var(--t1)" }}>v{v.version}</span>
            {i === 0 && <span className="aug-fs-ui" style={{ color: "var(--t3)" }}>current</span>}
            <span className="aug-fs-ui" style={{ color: "var(--t3)", marginLeft: "auto" }}>
              {v.created_at ? v.created_at.slice(0, 16).replace("T", " ") : ""}
            </span>
          </button>
        ))}
      </div>

      {selected !== null && (
        <>
          <div
            style={{
              display: "flex", alignItems: "center", gap: 8,
              padding: "6px 12px", borderTop: "1px solid var(--b0)",
            }}
          >
            <span className="aug-fs-ui" style={{ color: "var(--t3)" }}>
              {changes.length === 0
                ? "No field changes"
                : `${changes.length} ${changes.length === 1 ? "change" : "changes"}`}
            </span>
            <div style={{ flex: 1 }} />
            <Button
              variant="ghost" size="xs" className="aug-fs-ui"
              disabled={busy || versions[0]?.version === selected}
              title={versions[0]?.version === selected
                ? "This is the current version"
                : `Restore version ${selected} onto the live query`}
              onClick={() => void restore(selected)}
            >
              Restore
            </Button>
          </div>

          {changes.length > 0 && (
            <div style={{ padding: "0 12px 6px", maxHeight: 110, overflow: "auto" }}>
              {changes.map((c, i) => (
                <div key={i} className="aug-fs-ui" style={{ color: "var(--t3)" }}>
                  <span style={{ color: "var(--t2)" }}>{c.path}</span>
                  {" — "}{c.kind}
                </div>
              ))}
            </div>
          )}

          <div ref={host} style={{ flex: 1, minHeight: 0, overflow: "auto" }} />
        </>
      )}
    </div>
  );
}
