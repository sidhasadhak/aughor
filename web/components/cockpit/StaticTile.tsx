"use client";

/**
 * StaticTile — a Note and an Image, the two elements of a cockpit that measure nothing (the
 * canvas, docs/COCKPIT_CANVAS_2026-10-08.md §3).
 *
 * A static thing says it is static. A note shows who wrote it and when; an image who uploaded
 * it, when, and its file name. Neither shows a status, a period or a comparison, because
 * neither was measured for one: a reader must never take a number in a note for a figure the
 * platform read. The stamps are the server's — a browser cannot write them — and an image the
 * reader may not see, or that is gone, stands as its caption and says why.
 *
 * The doors are a person's own: edit the words, change the caption, pick a size, take it off.
 * They show when the tile is pointed at or focused, as a card's do.
 */
import { useState, type ReactNode } from "react";

import { Foot, Frame, Title } from "@/components/cockpit/CockpitTile";
import { NoteProse } from "@/components/cockpit/NoteProse";
import { SizePick } from "@/components/cockpit/SizePick";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { MAX_CAPTION, MAX_NOTE, SPAN, type Size } from "@/lib/cockpit/catalog";
import { formatDateTime } from "@/lib/format";

/** What a static tile may ask of its cockpit. Each is absent on a cockpit the reader may not change. */
export interface StaticDoors {
  onTakeOff?: (key: string) => void;
  onResize?: (key: string, size: Size) => void;
  onEditNote?: (key: string, text: string) => void;
  onRecaption?: (key: string, caption: string) => void;
}

/** What the cockpit's read says of an uploaded image: its stamps, and whether the reader may see it. */
export interface ImageStamp {
  file_name: string;
  uploaded_by: string;
  uploaded_at: string;
  readable: boolean;
  why: string;
  /** Where its bytes are read from, when they may be. */
  url: string;
}

export function person(name: string): string {
  return (name || "").replace(/^user:/, "") || "someone";
}

function DoorsBar({ children }: { children: ReactNode }) {
  return (
    <div className="opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100"
      data-testid="cockpit-tile-doors"
      style={{ position: "absolute", top: 8, right: 8, display: "flex", gap: 2, alignItems: "center", background: "var(--bg-2)", borderRadius: "var(--r2)" }}>
      {children}
    </div>
  );
}

export function NoteTile({ elementKey, text, author, writtenAt, size, doors }: {
  elementKey: string | null;
  text: string;
  author?: string;
  writtenAt?: string;
  size: Size;
  doors: StaticDoors;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(text);
  const own = elementKey !== null;
  const stamp = author
    ? `${person(author)} · written ${writtenAt ? formatDateTime(writtenAt) : "just now"}`
    : "Not yet kept";
  return (
    <Frame testid="cockpit-note" doors={own && !editing ? (
      <DoorsBar>
        {doors.onEditNote && (
          <Button variant="ghost" size="icon-xs" aria-label="Edit the note" title="Change its words. The note is re-stamped when kept."
            onClick={() => { setDraft(text); setEditing(true); }}><Icon name="edit" /></Button>
        )}
        {doors.onResize && <SizePick value={size} label="Size of the note" onPick={s => doors.onResize?.(elementKey, s)} />}
        {doors.onTakeOff && (
          <Button variant="ghost" size="icon-xs" aria-label="Take off this cockpit" title="Take the note off. The version before keeps it."
            onClick={() => doors.onTakeOff?.(elementKey)}><Icon name="close" /></Button>
        )}
      </DoorsBar>
    ) : undefined}>
      <Title title="Note" right={<span className="aug-fs-xs" data-testid="note-chip" style={{ color: "var(--t3)", whiteSpace: "nowrap" }}>Your words</span>} />
      {editing ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 6, flex: 1 }}>
          <Textarea aria-label="The note's words" value={draft} maxLength={MAX_NOTE} autoFocus
            onChange={e => setDraft(e.target.value)} style={{ minHeight: 88 }} />
          <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
            <Button size="xs" disabled={!draft.trim() || draft.trim() === text}
              onClick={() => { doors.onEditNote?.(elementKey as string, draft); setEditing(false); }}>Keep</Button>
            <Button size="xs" variant="ghost" onClick={() => setEditing(false)}>Cancel</Button>
            <span className="aug-fs-xs" style={{ marginLeft: "auto", color: "var(--t3)", fontVariantNumeric: "tabular-nums" }}>{draft.length} / {MAX_NOTE}</span>
          </div>
        </div>
      ) : (
        <div style={{ flex: 1, minHeight: 0, overflow: "auto" }}><NoteProse text={text} /></div>
      )}
      <Foot icon="user">{stamp} · not measured, cited by nothing</Foot>
    </Frame>
  );
}

export function ImageTile({ elementKey, caption, stamp, size, doors }: {
  elementKey: string | null;
  caption: string;
  /** Undefined when the cockpit's read said nothing of this object: then it is not shown, and said so. */
  stamp?: ImageStamp;
  size: Size;
  doors: StaticDoors;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(caption);
  const own = elementKey !== null;
  const shown = !!stamp?.readable;
  return (
    <Frame testid="cockpit-image" dashed={!shown} doors={own && !editing ? (
      <DoorsBar>
        {doors.onRecaption && (
          <Button variant="ghost" size="icon-xs" aria-label="Change the caption" title="Change the caption"
            onClick={() => { setDraft(caption); setEditing(true); }}><Icon name="edit" /></Button>
        )}
        {doors.onResize && <SizePick value={size} label="Size of the image" onPick={s => doors.onResize?.(elementKey, s)} />}
        {doors.onTakeOff && (
          <Button variant="ghost" size="icon-xs" aria-label="Take off this cockpit" title="Take the image off. The version before keeps it."
            onClick={() => doors.onTakeOff?.(elementKey)}><Icon name="close" /></Button>
        )}
      </DoorsBar>
    ) : undefined}>
      {editing ? (
        <div style={{ display: "flex", gap: 6, alignItems: "center", paddingRight: 64 }}>
          <Input aria-label="The image's caption" value={draft} maxLength={MAX_CAPTION} autoFocus onChange={e => setDraft(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter" && draft.trim()) { doors.onRecaption?.(elementKey as string, draft); setEditing(false); } if (e.key === "Escape") setEditing(false); }} />
          <Button size="xs" disabled={!draft.trim() || draft.trim() === caption}
            onClick={() => { doors.onRecaption?.(elementKey as string, draft); setEditing(false); }}>Keep</Button>
          <Button size="xs" variant="ghost" onClick={() => setEditing(false)}>Cancel</Button>
        </div>
      ) : (
        <Title title={caption} right={<span className="aug-fs-xs" style={{ color: "var(--t3)", whiteSpace: "nowrap" }}>Static</span>} />
      )}
      {shown ? (
        <div style={{ flex: 1, minHeight: 0, display: "flex", alignItems: "center", justifyContent: "center", overflow: "hidden", borderRadius: "var(--r2)" }}>
          {/* An uploaded file, not a Next asset: it is read from the API with the reader's own access. */}
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={stamp!.url} alt={caption} data-testid="cockpit-image-bytes"
            style={{ maxWidth: "100%", maxHeight: SPAN[size].h === 2 ? 360 : 160, objectFit: "contain", display: "block" }} />
        </div>
      ) : (
        <div className="aug-fs-sm" data-testid="cockpit-image-withheld" style={{ color: "var(--t2)", display: "flex", alignItems: "center", gap: 8 }}>
          <Icon name="eyeoff" size={16} /> {stamp?.why || "This image is not shown: the cockpit's read said nothing of it."}
        </div>
      )}
      <Foot icon="attach">
        {stamp ? `${stamp.file_name} · uploaded by ${person(stamp.uploaded_by)} · ${formatDateTime(stamp.uploaded_at)}` : "An uploaded image"} · no period, no comparison
      </Foot>
    </Frame>
  );
}
