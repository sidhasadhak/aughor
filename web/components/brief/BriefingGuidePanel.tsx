"use client";

/**
 * Arc BG (ROADMAP §3.66) — the connection's Briefing guide, beside its edition.
 *
 * How this dataset's Briefing is written, as the Explorer drafted it and people corrected it: the
 * business, what each range is for here, fair comparisons, the calendar, what to read with care, the
 * checks an edition measures, and the readers. A panel a person opens on purpose (never a pop-up); every
 * change is a new version, and editions read the published one once there is one — said at the top.
 */
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "@/components/ui/toast";
import {
  addBriefingReader, draftBriefingGuide, publishBriefingGuide, saveBriefingGuide, saveGroup,
  type BriefingGuideDoc, type BriefingGuideResponse, type GuideReader,
} from "@/lib/api";
import { groupIdOf } from "@/lib/briefingEdition";

const H = ({ children }: { children: React.ReactNode }) => (
  <h3 className="aug-label" style={{ margin: "14px 0 4px", color: "var(--t3)" }}>{children}</h3>
);
const Ev = ({ children }: { children: React.ReactNode }) =>
  children ? <span className="aug-fs-xs" style={{ color: "var(--t3)" }}> {children}</span> : null;

function stateWords(r: BriefingGuideResponse): string {
  const read = r.editions_read;
  if (!read) return "";
  return read.state === "published"
    ? `Editions read version ${read.version}, published.`
    : `Editions read version ${read.version}, a draft no person has published yet.`;
}

export function BriefingGuidePanel({ connectionId, schema, guide, onChange, readerId, onHide }: {
  connectionId: string;
  schema?: string;
  guide: BriefingGuideResponse;
  onChange: (g: BriefingGuideResponse) => void;
  /** The reader the edition beside it is written for — marked in the readers list. */
  readerId: string;
  onHide: () => void;
}) {
  const doc = guide.guide;
  const ver = guide.version;
  const [busy, setBusy] = useState<string>("");
  const [editing, setEditing] = useState<BriefingGuideDoc | null>(null);
  const [adding, setAdding] = useState<{ name: string; watches: string } | null>(null);
  const [history, setHistory] = useState(false);

  const run = async (what: string, fn: () => Promise<BriefingGuideResponse>) => {
    setBusy(what);
    try { onChange(await fn()); } catch (e) { toast.error(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(""); }
  };

  const addReader = (r: { name: string; watches: string; check_ids?: string[] }) => run("reader", async () => {
    const id = groupIdOf(r.name);
    if (!id) throw new Error("A reader needs a name");
    await saveGroup({ id, name: r.name, description: r.watches });
    const out = await addBriefingReader(connectionId, { group_id: id, name: r.name, watches: r.watches,
                                                        check_ids: r.check_ids }, schema);
    setAdding(null);
    return out;
  });

  if (!doc || !ver) return null;
  return (
    <aside data-testid="briefing-guide" aria-label="Briefing guide"
      style={{ borderLeft: "1px solid var(--b1)", background: "var(--bg-1)", padding: "18px 20px 30px",
               height: "100%", overflowY: "auto", minWidth: 0 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
        <h2 className="aug-fs-h1" style={{ fontFamily: "var(--font-serif)", fontWeight: 600, margin: 0, color: "var(--t1)" }}>
          Briefing guide
        </h2>
        <span className="aug-fs-xs" style={{ padding: "1px 8px", borderRadius: "var(--r-pill)", background: "var(--vio1)",
                                             color: "var(--vio4)" }}>v{ver.version} · {ver.state}</span>
      </div>
      <p className="aug-fs-xs" style={{ color: "var(--t3)", margin: "4px 0 2px" }}>
        How this dataset&apos;s Briefing is written. This version kept by {ver.by || "someone unnamed"}
        {ver.note ? ` — ${ver.note}` : ""}.
      </p>
      <p className="aug-fs-xs" data-testid="guide-editions-read" style={{ color: "var(--t2)", margin: "0 0 10px" }}>
        {stateWords(guide)}
      </p>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 6 }}>
        {ver.state !== "published" && (
          <Button size="sm" disabled={!!busy} onClick={() => run("publish", () => publishBriefingGuide(connectionId, schema))}>
            {busy === "publish" ? "Publishing…" : "Publish this version"}
          </Button>
        )}
        <Button size="sm" variant="secondary" disabled={!!busy} onClick={() => setEditing(editing ? null : doc)}>
          {editing ? "Cancel" : "Edit"}
        </Button>
        <Button size="sm" variant="ghost" disabled={!!busy} title="One model call; kept as a new draft"
          onClick={() => run("draft", () => draftBriefingGuide(connectionId, schema))}>
          {busy === "draft" ? "Drafting…" : "Redraft"}
        </Button>
        <Button size="sm" variant="ghost" onClick={onHide}>Hide</Button>
      </div>

      {editing ? (
        <div style={{ display: "grid", gap: 8 }}>
          <H>The business</H>
          <Textarea aria-label="The business" value={editing.business} rows={4}
            onChange={e => setEditing({ ...editing, business: e.target.value })} />
          {(["week", "month", "year"] as const).map(k => (
            <label key={k} className="aug-fs-sm" style={{ display: "grid", gap: 4 }}>
              <span style={{ color: "var(--t3)" }}>What a {k} is for</span>
              <Textarea aria-label={`What a ${k} is for`} value={editing.ranges[k]} rows={2}
                onChange={e => setEditing({ ...editing, ranges: { ...editing.ranges, [k]: e.target.value } })} />
            </label>
          ))}
          <Button size="sm" disabled={!!busy}
            onClick={() => run("save", async () => {
              const out = await saveBriefingGuide(connectionId, editing, "edited by a person", schema);
              setEditing(null);
              return out;
            })}>
            {busy === "save" ? "Saving…" : "Save as a draft"}
          </Button>
        </div>
      ) : (
        <>
          <H>The business</H>
          <p className="aug-fs-sm" style={{ margin: 0 }}>{doc.business}</p>
          <H>What each range is for</H>
          <ul className="aug-fs-sm" style={{ margin: 0, paddingLeft: 16 }}>
            {(["week", "month", "year", "custom"] as const).filter(k => doc.ranges[k]).map(k => (
              <li key={k} style={{ marginBottom: 4 }}><b style={{ color: "var(--t1)", fontWeight: 500 }}>
                {k[0].toUpperCase() + k.slice(1)}</b> — {doc.ranges[k]}</li>
            ))}
          </ul>
          <H>What counts as news</H>
          <p className="aug-fs-sm" style={{ margin: 0 }}>
            A figure is news when it leaves its usual range — the {doc.news.usual_week ?? 8} weeks before
            (for a week), give or take one standard deviation. One more than {doc.news.floor_sd ?? 2} away
            is on every reader&apos;s edition.
          </p>
          {doc.comparisons.length > 0 && (<><H>Fair comparisons</H>
            <ul className="aug-fs-sm" style={{ margin: 0, paddingLeft: 16 }}>
              {doc.comparisons.map((c, i) => (
                <li key={`${i}-${c.text.slice(0, 20)}`} style={{ marginBottom: 4 }}>{c.text}
                  {c.exclude_from_last_year && (
                    <span className="aug-fs-xs" style={{ display: "block", color: "var(--t3)" }}>
                      Compared without {c.exclude_from_last_year.value}
                      {c.exclude_from_last_year.until ? ` before ${c.exclude_from_last_year.until}` : ""} —
                      {guide.editions_read?.state === "published" ? " applied." : " applied once a person publishes the guide."}
                    </span>
                  )}<Ev>{c.evidence}</Ev></li>
              ))}
            </ul></>)}
          {doc.calendar.length > 0 && (<><H>The calendar</H>
            <p className="aug-fs-sm" style={{ margin: 0 }}>
              {doc.calendar.map(d => `${d.name} (${d.when})`).join(" · ")}
            </p></>)}
          {doc.care.length > 0 && (<><H>Read with care</H>
            <ul className="aug-fs-sm" style={{ margin: 0, paddingLeft: 16 }}>
              {doc.care.map((c, i) => <li key={`${i}-${c.text.slice(0, 20)}`} style={{ marginBottom: 4 }}>{c.text}<Ev>{c.evidence}</Ev></li>)}
            </ul></>)}
          <H>What an edition measures · {doc.checks.length}</H>
          <ul className="aug-fs-sm" style={{ margin: 0, paddingLeft: 16 }}>
            {doc.checks.map(c => <li key={c.id} style={{ marginBottom: 3 }}>{c.label}
              <Ev>{c.metric ? `approved metric ${c.metric}` : c.evidence}</Ev></li>)}
          </ul>
          {doc.dropped.length > 0 && (
            <p className="aug-fs-xs" data-testid="guide-dropped" style={{ color: "var(--t3)", margin: "6px 0 0" }}>
              Kept out: {doc.dropped.map(d => `${d.label} (${d.reason})`).join("; ")}.
            </p>
          )}
        </>
      )}

      <H>Readers</H>
      <div className="aug-fs-sm" style={{ display: "grid" }}>
        {doc.readers.length === 0 && <span style={{ color: "var(--t3)" }}>No reader added yet — editions are written for the organisation.</span>}
        {doc.readers.map(r => (
          <div key={r.group_id} style={{ display: "grid", gridTemplateColumns: "116px 1fr", gap: 8, padding: "4px 0",
                                         borderTop: "1px solid var(--b1)" }}>
            <b style={{ fontWeight: 500, color: r.group_id === readerId ? "var(--blue4)" : "var(--t1)" }}>{r.name}</b>
            <span>{r.watches} <Ev>{r.check_ids.length} checks</Ev></span>
          </div>
        ))}
      </div>
      {doc.proposed_readers.length > 0 && (
        <div data-testid="guide-proposed-readers" style={{ marginTop: 8 }}>
          <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>The guide proposes:</span>
          {doc.proposed_readers.map((r: GuideReader) => (
            <div key={r.name} className="aug-fs-sm" style={{ display: "flex", gap: 8, alignItems: "center", padding: "3px 0" }}>
              <span style={{ flex: 1 }}><b style={{ fontWeight: 500, color: "var(--t1)" }}>{r.name}</b> — {r.watches}</span>
              <Button size="sm" variant="secondary" disabled={!!busy}
                onClick={() => addReader({ name: r.name, watches: r.watches, check_ids: r.check_ids })}>Add</Button>
            </div>
          ))}
        </div>
      )}
      {adding ? (
        <div style={{ display: "grid", gap: 6, marginTop: 8 }}>
          <Input aria-label="Reader's name" placeholder="Product" value={adding.name}
            onChange={e => setAdding({ ...adding, name: e.target.value })} />
          <Textarea aria-label="What they watch" rows={3} value={adding.watches}
            placeholder="What this department or team watches and decides, in your words"
            onChange={e => setAdding({ ...adding, watches: e.target.value })} />
          <div style={{ display: "flex", gap: 6 }}>
            <Button size="sm" disabled={!!busy || !adding.name.trim()} title="One model call maps the words onto the guide's checks"
              onClick={() => addReader(adding)}>{busy === "reader" ? "Adding…" : "Add the reader"}</Button>
            <Button size="sm" variant="ghost" onClick={() => setAdding(null)}>Cancel</Button>
          </div>
        </div>
      ) : (
        <Button size="sm" variant="ghost" style={{ marginTop: 6 }} onClick={() => setAdding({ name: "", watches: "" })}>
          + Add a reader
        </Button>
      )}

      <H>History</H>
      <Button size="sm" variant="ghost" onClick={() => setHistory(!history)}>
        {history ? "Hide" : `${guide.versions.length} versions`}
      </Button>
      {history && (
        <ol className="aug-fs-xs" style={{ margin: "4px 0 0", paddingLeft: 16, color: "var(--t2)" }}>
          {guide.versions.map(v => (
            <li key={v.version}>v{v.version} · {v.state} · {v.by}{v.note ? ` — ${v.note}` : ""}</li>
          ))}
        </ol>
      )}
    </aside>
  );
}
