"use client";

/**
 * Who a sheet is shared with (Arc SH, SH-8). Without `sheets.sharing` a sheet is its workspace's, and the pop-up says
 * exactly that (the arc's call 8). With it, the sheet's maker chooses: everyone in the workspace, or only the people and
 * groups chosen — each able to read it or to edit it. Anyone else who opens it sees who it is shared with, what they
 * may do themselves, and that only its maker changes it.
 */
import { useEffect, useMemo, useRef, useState } from "react";

import { MUTED } from "@/components/clarity/kit";
import { useCloseOutside } from "@/components/sheets/useCloseOutside";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { Input } from "@/components/ui/input";
import { Segmented } from "@/components/ui/segmented";
import {
  readSharing, saveSharing, who, type SheetShare, type SheetSharing, type SheetView,
} from "@/lib/sheets";

const KIND_WORDS: Record<SheetShare["kind"], string> = { person: "", group: "group", role: "built-in group" };

/** What was typed into "Add", read as a share: a group's or a built-in group's name or id, else a person's id. */
export function typedShare(text: string, groups: SheetSharing["groups"], level: "view" | "edit"): SheetShare | null {
  const t = text.trim().replace(/^user:/, "");
  if (!t) return null;
  const low = t.toLowerCase();
  const g = groups.find(x => x.id.toLowerCase() === low || x.name.toLowerCase() === low);
  return g ? { kind: g.kind, id: g.id, level, name: g.name } : { kind: "person", id: t, level, name: t };
}

export function SharePop({ name, sheetId, views, me, sharing, onDone, onChanged }: {
  name: string; sheetId: string; views?: SheetView[]; me?: string;
  /** `sheets.sharing` on: people and groups may be chosen. */
  sharing?: boolean;
  onDone: () => void; onChanged?: (s: SheetSharing) => void;
}) {
  const shared = views?.filter(v => v.shared).length ?? 0;
  const mine = views?.filter(v => !v.shared && v.owner === me).length ?? 0;
  const ref = useRef<HTMLDivElement>(null);
  useCloseOutside(ref, onDone);
  return (
    <div ref={ref} role="dialog" aria-label={`Share · ${name}`} className="aug-fs-sm" style={{ position: "absolute", right: 0,
      top: "100%", zIndex: 20, width: sharing ? 360 : 300, background: "var(--bg-2)", border: "1px solid var(--b1)",
      borderRadius: "var(--r3)", padding: "10px 12px", display: "flex", flexDirection: "column", gap: 6 }}>
      <span className="aug-fs-xs" style={MUTED}>Share · {name}</span>
      {sharing ? <Chooser sheetId={sheetId} me={me} onChanged={onChanged} /> : (
        <>
          <span><b>Everyone in Workspace</b> can read and edit this sheet.</span>
          <span className="aug-fs-xs" style={MUTED}>Choosing people, as readers or editors, comes in a later step.</span>
        </>
      )}
      {views && (
        <span className="aug-fs-xs">Views: <b>{shared} shared</b>{mine ? <> · <b>{mine} your own</b> (only you see {mine === 1 ? "it" : "them"})</> : ""}</span>
      )}
      <div style={{ display: "flex", gap: 6, justifyContent: "flex-end" }}>
        <Button variant="outline" size="xs" onClick={() => {
          const url = new URL(window.location.href);
          url.searchParams.set("tab", "spreadsheets");
          url.searchParams.set("sheet", sheetId);
          void navigator.clipboard?.writeText(url.toString());
        }}>Copy link</Button>
        <Button variant="ghost" size="xs" onClick={onDone}>Done</Button>
      </div>
    </div>
  );
}

function Chooser({ sheetId, me, onChanged }: { sheetId: string; me?: string; onChanged?: (s: SheetSharing) => void }) {
  const [got, setGot] = useState<SheetSharing | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [mode, setMode] = useState<"workspace" | "chosen">("workspace");
  const [shares, setShares] = useState<SheetShare[]>([]);
  const [typed, setTyped] = useState("");
  const [level, setLevel] = useState<"view" | "edit">("view");
  const [said, setSaid] = useState<{ text: string; tone: "ok" | "bad" } | null>(null);
  const [saving, setSaving] = useState(false);
  const listId = `share-${sheetId}`;

  const take = (s: SheetSharing) => { setGot(s); setMode(s.sharing); setShares(s.shared_with); };
  useEffect(() => {
    readSharing(sheetId).then(s => { take(s); setFailed(null); })
      .catch(e => setFailed(e instanceof Error ? e.message : String(e)));
  }, [sheetId]);

  const dirty = useMemo(() => !!got && (mode !== got.sharing || JSON.stringify(shares.map(s => [s.kind, s.id, s.level]))
    !== JSON.stringify(got.shared_with.map(s => [s.kind, s.id, s.level]))), [got, mode, shares]);

  if (failed) return <span role="alert" style={{ color: "var(--red4)" }}>{failed}</span>;
  if (!got) return <span className="aug-fs-xs" style={MUTED}>Reading who it is shared with…</span>;

  const may = got.may_change;
  const maker = who(`user:${got.maker}`, me);
  const add = () => {
    const share = typedShare(typed, got.groups, level);
    if (!share) return;
    if (share.kind === "person" && share.id === got.maker) {
      setSaid({ text: `${maker === "you" ? "You" : maker} made it, and can always read and edit it.`, tone: "bad" });
      return;
    }
    setShares([...shares.filter(s => !(s.kind === share.kind && s.id === share.id)), share]);
    setTyped("");
    setSaid(null);
  };
  const save = async () => {
    setSaving(true);
    try {
      const s = await saveSharing(sheetId, mode, mode === "chosen" ? shares : []);
      take(s);
      setSaid({ text: s.sharing === "chosen" ? "Shared with the people and groups chosen" : "Shared with everyone in Workspace", tone: "ok" });
      onChanged?.(s);
    } catch (e) {
      setSaid({ text: e instanceof Error ? e.message : String(e), tone: "bad" });
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      {may ? (
        <Segmented label="Who it is shared with" value={mode} onChange={v => { setMode(v); setSaid(null); }}
          options={[{ value: "workspace", label: "Everyone in Workspace" }, { value: "chosen", label: "Only people chosen" }]} />
      ) : null}
      {mode === "workspace" ? (
        <span><b>Everyone in Workspace</b> can read and edit this sheet.</span>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <span className="aug-fs-xs" style={MUTED}>
            {maker === "you" ? "You" : maker} made it, and can always read and edit it. No one else can open it unless listed here.
          </span>
          {shares.length === 0 && <span className="aug-fs-xs" style={MUTED}>No one is chosen yet.</span>}
          {shares.map(s => (
            <div key={`${s.kind}:${s.id}`} style={{ display: "flex", alignItems: "center", gap: 6, minHeight: 26 }}>
              <span style={{ flex: "1 1 auto", minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                title={s.id}>
                {s.name ?? s.id}{KIND_WORDS[s.kind] && <span className="aug-fs-xs" style={MUTED}> · {KIND_WORDS[s.kind]}</span>}
              </span>
              {may ? (
                <>
                  <Segmented label={`What ${s.name ?? s.id} may do`} value={s.level}
                    onChange={v => setShares(shares.map(x => (x === s ? { ...x, level: v } : x)))}
                    options={[{ value: "view", label: "Can read" }, { value: "edit", label: "Can edit" }]} />
                  <Button variant="ghost" size="xs" aria-label={`Stop sharing with ${s.name ?? s.id}`}
                    onClick={() => setShares(shares.filter(x => x !== s))}><Icon name="close" size={12} /></Button>
                </>
              ) : (
                <span className="aug-fs-xs" style={MUTED}>{s.level === "edit" ? "can edit" : "can read"}</span>
              )}
            </div>
          ))}
          {may && (
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <Input value={typed} list={listId} placeholder="A person's sign-in name, or a group" aria-label="Add a person or a group"
                style={{ flex: "1 1 auto", minWidth: 0 }} onChange={e => setTyped(e.target.value)}
                onKeyDown={e => { if (e.key === "Enter") { e.preventDefault(); add(); } }} />
              <datalist id={listId}>
                {got.people.map(p => <option key={`person:${p}`} value={p} />)}
                {got.groups.map(g => <option key={`${g.kind}:${g.id}`} value={g.name}>{KIND_WORDS[g.kind]}</option>)}
              </datalist>
              <Segmented label="What they may do" value={level} onChange={setLevel}
                options={[{ value: "view", label: "Read" }, { value: "edit", label: "Edit" }]} />
              <Button variant="outline" size="xs" disabled={!typed.trim()} onClick={add}>Add</Button>
            </div>
          )}
        </div>
      )}
      {!may && (
        <span className="aug-fs-xs" style={MUTED}>
          You {got.access === "edit" ? "can edit it" : "can read it"}. Only {maker}, who made it, can change who it is shared with.
        </span>
      )}
      {said && (
        <span role={said.tone === "bad" ? "alert" : "status"} className="aug-fs-xs"
          style={{ color: said.tone === "bad" ? "var(--red4)" : "var(--t2)" }}>{said.text}</span>
      )}
      {may && dirty && (
        <div style={{ display: "flex", justifyContent: "flex-end" }}>
          <Button size="xs" disabled={saving || (mode === "chosen" && shares.length === 0)} onClick={() => void save()}>
            {saving ? "Saving…" : "Save"}
          </Button>
        </div>
      )}
    </>
  );
}
