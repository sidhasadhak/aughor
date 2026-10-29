"use client";

/**
 * Arc BG (ROADMAP §3.66, §6 item 58) — the Briefing as an edition written for one reader.
 *
 * The user, 2026-10-29: "Imagine there is no structure to it. Only the periods like the week month year and
 * the custom day range." So the page has no fixed sections: the range and the reader decide, the server
 * measured every check the connection's Briefing guide keeps, and one model call chose and worded the
 * stories. What the page draws around them is code's: the figures, the usual ranges, the segments, the
 * calendar ahead, what could not be read and what the gates held back.
 *
 * Opening never spends (§6 item 58): the page READS the edition last written for the range and the reader
 * and writes one only when a person presses the button.
 */
import { useCallback, useEffect, useState } from "react";

import { BriefingGuidePanel } from "@/components/brief/BriefingGuidePanel";
import { BriefingOffNotice } from "@/components/brief/BriefingOff";
import { BriefSchedule } from "@/components/brief/BriefSchedule";
import { RangeBars, SegmentBars } from "@/components/brief/EditionFigure";
import { RangeControl, type RangeChoice } from "@/components/brief/BriefRange";
import { Button } from "@/components/ui/button";
import { Segmented } from "@/components/ui/segmented";
import { toast } from "@/components/ui/toast";
import {
  draftBriefingGuide, getGroups, putMyPreference, readBriefingEdition, readBriefingGuide, writeBriefingEdition,
  type AccessGroup, type BriefingEdition as Edition, type BriefingGuideResponse, type BriefingRange,
  type EditionFigure, type EditionStory,
} from "@/lib/api";
import { formatTimestamp } from "@/lib/format";
import {
  ORGANISATION, fromServerReader, kickerOf, readerOptions, toServerReader, writeLabel,
} from "@/lib/briefingEdition";

const PRESETS = ["last_week", "last_month", "last_year"] as const;
const RULE = "1px solid var(--b1)";

const when = (iso?: string): string => (iso ? formatTimestamp(iso, "short") : "");

function Kicker({ children, tone }: { children: React.ReactNode; tone?: "amber" | "green" | "dim" }) {
  const color = tone === "amber" ? "var(--amb4)" : tone === "green" ? "var(--grn4)" : tone === "dim" ? "var(--t3)" : "var(--blue4)";
  return <div className="aug-fs-xs" style={{ letterSpacing: "0.09em", textTransform: "uppercase", color, marginBottom: 6 }}>{children}</div>;
}

function Story({ story, period }: { story: EditionStory; period: string }) {
  const fig: EditionFigure | undefined = story.figures[0];
  // The segments come from whichever of the story's figures has them — "AOV rose while YOOX orders fell" reads
  // its storefronts from the orders figure, not the first one (seen live on LuxExperience, 2026-10-29).
  const segFig = story.figures.find(f => Object.values(f.cells || {}).some(v => v.cells.length > 0));
  const dims = segFig ? Object.entries(segFig.cells).filter(([, v]) => v.cells.length > 0) : [];
  const tone = story.reason === "new_level" ? "green" : story.reason === "watch" ? "dim" : "amber";
  return (
    <section data-testid="edition-story" style={{ display: "grid", gridTemplateColumns: fig ? "minmax(0,1.25fr) minmax(0,1fr)" : "1fr",
                                                   gap: 28, padding: "20px 0", borderBottom: RULE }}>
      <div>
        <Kicker tone={tone}>{kickerOf(story, fig, period)}</Kicker>
        <h3 className="aug-fs-h1" style={{ fontFamily: "var(--font-serif)", lineHeight: 1.25, fontWeight: 600, margin: "0 0 8px",
                     color: "var(--t1)" }}>{story.title}</h3>
        <p className="aug-fs-ui" style={{ margin: 0, lineHeight: 1.6, maxWidth: "62ch", color: "var(--t2)" }}>{story.body}</p>
        {fig?.like_for_like && (
          <p className="aug-fs-xs" style={{ color: "var(--t3)", margin: "6px 0 0" }}>A year earlier is read {fig.like_for_like}.</p>
        )}
      </div>
      {fig && (
        <div style={{ paddingTop: 22 }}>
          <div className="aug-fs-xs" style={{ color: "var(--t1)", fontWeight: 500 }}>{fig.label}</div>
          <RangeBars figure={fig} period={period} />
          {fig.usual && <div className="aug-fs-xs" style={{ color: "var(--t3)" }}>Shaded: its usual range, the {fig.usual.n} before.</div>}
          {dims.slice(0, 1).map(([dim, v]) => (
            <div key={dim} style={{ marginTop: 12 }}>
              <div className="aug-fs-xs" style={{ color: "var(--t1)", fontWeight: 500 }}>
                {segFig!.label} by {dim.replace(/_/g, " ")}, against its usual
              </div>
              <SegmentBars cells={v.cells} better={segFig!.better} />
              {v.cells.some(c => c.thin) && <div className="aug-fs-xs" style={{ color: "var(--t3)" }}>Grey: under 30 rows — too few to call.</div>}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function Lines({ title, sub, items, testId }: { title: string; sub: string; items: { key: string; node: React.ReactNode }[]; testId: string }) {
  if (!items.length) return null;
  return (
    <section data-testid={testId} style={{ display: "grid", gridTemplateColumns: "1fr 1fr", columnGap: 34, padding: "16px 0", borderBottom: RULE }}>
      <h4 className="aug-fs-h2" style={{ gridColumn: "1 / -1", fontFamily: "var(--font-serif)", fontWeight: 600, margin: "0 0 6px",
                   color: "var(--t1)", display: "flex", alignItems: "baseline", gap: 10 }}>
        {title}<span className="aug-fs-xs" style={{ fontFamily: "inherit", fontWeight: 400, color: "var(--t3)" }}>{sub}</span>
      </h4>
      {items.map(i => <div key={i.key} className="aug-fs-sm" style={{ lineHeight: 1.5, padding: "6px 0", borderTop: RULE }}>{i.node}</div>)}
    </section>
  );
}

export function BriefingEdition({ connectionId, schema, workspaceId }: {
  connectionId: string;
  schema?: string;
  workspaceId?: string;
}) {
  const [range, setRange] = useState<BriefingRange>({ preset: "last_week" });
  /** The reader asked for: undefined = the person's own, which the server resolves. */
  const [asked, setAsked] = useState<string | undefined>(undefined);
  /** The reader on screen — the one asked for, or the one the server said it read for. */
  const [reader, setReader] = useState<string | undefined>(undefined);
  const [groups, setGroups] = useState<AccessGroup[]>([]);
  const [edition, setEdition] = useState<Edition | null>(null);
  const [guide, setGuide] = useState<BriefingGuideResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [guideOpen, setGuideOpen] = useState(true);
  const [schedule, setSchedule] = useState(false);

  useEffect(() => {
    let alive = true;
    getGroups().then(c => { if (alive) setGroups(c.groups); }).catch(() => { /* readers fall back to the organisation */ });
    return () => { alive = false; };
  }, []);

  const loadGuide = useCallback(async () => {
    try { setGuide(await readBriefingGuide(connectionId, schema)); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  }, [connectionId, schema]);
  useEffect(() => { void loadGuide(); }, [loadGuide]);

  // A READ: the edition last written for this range and reader. Never a write.
  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError("");
    readBriefingEdition(connectionId, range, asked === undefined ? undefined : toServerReader(asked), schema, workspaceId)
      .then(e => {
        if (!alive) return;
        setEdition(e);
        if (asked === undefined) {
          // whose edition the server read — shown, without asking again
          const r = e.reader;
          setReader(fromServerReader(typeof r === "string" ? r : r?.group_id));
        }
      })
      .catch(e => { if (alive) setError(e instanceof Error ? e.message : String(e)); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [connectionId, schema, workspaceId, range, asked]);

  const chooseReader = (v: string) => {
    setReader(v);
    setAsked(v);
    putMyPreference("briefing_reader", toServerReader(v)).catch(() => toast.error("Your reader could not be kept; it holds for this visit"));
  };

  const write = async () => {
    setBusy("write");
    try { setEdition(await writeBriefingEdition(connectionId, range, toServerReader(reader ?? ORGANISATION), schema, workspaceId)); }
    catch (e) { toast.error(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(""); }
  };

  const draft = async () => {
    setBusy("draft");
    try { setGuide(await draftBriefingGuide(connectionId, schema)); }
    catch (e) { toast.error(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(""); }
  };

  const block = edition?.period;
  const period = block?.period ?? "week";
  const custom = range.preset === "custom";
  const readerName = readerOptions(groups).find(o => o.value === (reader ?? ORGANISATION))?.label ?? "The organisation";
  const figures = block?.measured ?? [];
  const hasGuide = !!guide?.available;

  return (
    // The layer around the Briefing does not scroll (it is overflow: hidden): the edition and the guide each
    // scroll on their own, the guide staying beside whatever story is in view.
    <div data-testid="briefing-edition" style={{ display: "grid", gridTemplateColumns: hasGuide && guideOpen ? "minmax(0,1fr) 372px" : "minmax(0,1fr)",
                                                  height: "100%", minHeight: 0 }}>
      <article style={{ padding: "22px 34px 40px", minWidth: 0, height: "100%", overflowY: "auto" }}>
        <div style={{ display: "flex", alignItems: "flex-end", gap: 16, paddingBottom: 10, borderBottom: "2px solid var(--t1)", flexWrap: "wrap" }}>
          <h1 className="aug-fs-display" style={{ fontFamily: "var(--font-serif)", fontWeight: 600, margin: 0, lineHeight: 1, color: "var(--t1)" }}>The Briefing</h1>
          {schema && <span className="aug-fs-sm" style={{ color: "var(--t2)" }}>{schema}</span>}
          <span style={{ marginLeft: "auto", display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <RangeControl value={range as RangeChoice} presets={[...PRESETS]}
              onChange={c => { if (c.preset !== "standing") setRange(c as BriefingRange); }} />
            {!hasGuide || guideOpen ? null : <Button size="sm" variant="ghost" onClick={() => setGuideOpen(true)}>The guide</Button>}
            <Button size="sm" variant="ghost" onClick={() => setSchedule(!schedule)}>{schedule ? "Close schedule" : "Schedule"}</Button>
          </span>
        </div>
        {schedule && <BriefSchedule connId={connectionId} />}
        <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 0 9px", borderBottom: RULE, flexWrap: "wrap" }}>
          <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>Reading as</span>
          <Segmented label="Reading as" value={reader ?? ORGANISATION} onChange={chooseReader} options={readerOptions(groups)} />
          <span className="aug-fs-xs" style={{ color: "var(--t3)", marginLeft: "auto" }}>the numbers are the same for every reader</span>
        </div>
        {block && (
          <div className="aug-fs-xs" data-testid="edition-dateline" style={{ display: "flex", gap: 14, padding: "7px 0", borderBottom: RULE, color: "var(--t3)", flexWrap: "wrap" }}>
            <b style={{ color: "var(--t2)", fontWeight: 500 }}>{block.covers}</b>
            <span>against {block.compared_with}{block.last_year_label ? `, and ${block.last_year_label}` : ""}</span>
            {edition?.built && (
              <span style={{ marginLeft: "auto" }}>
                written {when(edition.generated_at)} · {figures.length} figures measured
                {edition.guide?.state === "draft" ? " · from a draft guide no person has published" : ""}
              </span>
            )}
          </div>
        )}

        {error && <p className="aug-fs-sm" style={{ color: "var(--amb4)" }}>{error}</p>}
        {edition?.off ? <BriefingOffNotice off={edition.off} connectionId={connectionId} />
        : loading ? <p className="aug-fs-sm" style={{ color: "var(--t3)", padding: "22px 0" }}>Reading the edition…</p>
        : !hasGuide && guide ? (
          <section data-testid="edition-no-guide" style={{ padding: "26px 0" }}>
            <h2 className="aug-fs-display" style={{ fontFamily: "var(--font-serif)", margin: "0 0 8px", color: "var(--t1)" }}>This dataset has no Briefing guide yet</h2>
            <p className="aug-fs-sm" style={{ maxWidth: "62ch", margin: "0 0 12px" }}>
              The guide says how this dataset&apos;s Briefing is written — what matters here, what counts as news, who reads
              it. The Explorer drafts it at the end of an exploration; draft it now from what was learned (one model call).
            </p>
            <Button disabled={!!busy} onClick={() => void draft()}>{busy === "draft" ? "Drafting…" : "Draft the guide"}</Button>
          </section>
        ) : !edition?.built ? (
          <section data-testid="edition-unwritten" style={{ padding: "26px 0" }}>
            <h2 className="aug-fs-display" style={{ fontFamily: "var(--font-serif)", margin: "0 0 8px", color: "var(--t1)" }}>
              Not written yet for {readerName}
            </h2>
            <p className="aug-fs-sm" style={{ maxWidth: "62ch", margin: "0 0 12px" }}>
              The guide&apos;s {guide?.guide?.checks.length ?? 0} checks are measured for {block?.covers ?? "this range"}, then one
              model call writes the edition for {readerName}.
            </p>
            <Button disabled={!!busy} onClick={() => void write()}>{busy === "write" ? "Writing…" : writeLabel(period, custom)}</Button>
          </section>
        ) : (
          <>
            <section style={{ padding: "22px 0 18px", borderBottom: RULE }}>
              <Kicker>{`The ${custom ? "range" : period} for ${readerName}`}</Kicker>
              <h2 data-testid="edition-headline" className="aug-fs-display" style={{ fontFamily: "var(--font-serif)", lineHeight: 1.2, fontWeight: 600,
                                                          margin: "0 0 12px", maxWidth: "26ch", color: "var(--t1)" }}>{edition.headline}</h2>
              <p className="aug-fs-h2" style={{ lineHeight: 1.55, color: "var(--t1)", maxWidth: "66ch", margin: 0 }}>{edition.lede}</p>
            </section>
            {(edition.stories ?? []).map((s, i) => <Story key={`${s.check_ids.join("+")}-${i}`} story={s} period={period} />)}
            {!!edition.also_unusual?.length && (
              <section data-testid="edition-also-unusual" style={{ padding: "16px 0", borderBottom: RULE }}>
                <h4 className="aug-fs-h2" style={{ fontFamily: "var(--font-serif)", fontWeight: 600, margin: "0 0 6px", color: "var(--t1)" }}>
                  Also unusual <span className="aug-fs-xs" style={{ fontWeight: 400, color: "var(--t3)" }}>carried for every reader</span>
                </h4>
                {edition.also_unusual.map(a => <div key={a.check_id} className="aug-fs-sm" style={{ padding: "6px 0", borderTop: RULE }}>{a.line}</div>)}
              </section>
            )}
            <Lines title="Held steady" sub="inside their usual range — one line each" testId="edition-steady"
              items={(edition.steady ?? []).map(s => ({ key: s.check_id, node: s.line }))} />
            <Lines title="Coming up" sub="from the calendar the guide keeps" testId="edition-coming-up"
              items={(edition.coming_up ?? []).map(c => ({ key: `${c.date}-${c.name}`, node: c.line }))} />
            <Lines title="Not read" sub="what this edition could not measure, and why" testId="edition-not-read"
              items={(edition.not_read ?? []).map((n, i) => ({ key: `${i}-${n.label.slice(0, 24)}`,
                node: <><b style={{ fontWeight: 600, color: "var(--t2)" }}>{n.label}</b>{n.reason ? ` — ${n.reason}` : ""}</> }))} />
            <Lines title="Held back" sub="sentences the checks kept off this page" testId="edition-withheld"
              items={(edition.withheld ?? []).map((w, i) => ({ key: `${i}-${w.sentence.slice(0, 24)}`,
                node: <>&ldquo;{w.sentence}&rdquo; — {w.why}</> }))} />
            <section data-testid="edition-sources" className="aug-fs-xs" style={{ padding: "14px 0 0", color: "var(--t3)", lineHeight: 1.7 }}>
              {figures.map(f => (
                <details key={f.id} style={{ marginBottom: 2 }}>
                  <summary>{f.label}{f.metric ? ` · approved metric ${f.metric}` : ""} · {f.n} rows this range</summary>
                  <pre style={{ whiteSpace: "pre-wrap", fontFamily: "var(--font-mono)", margin: "4px 0 8px" }}>{f.sql}</pre>
                </details>
              ))}
            </section>
            <div style={{ display: "flex", gap: 10, alignItems: "center", marginTop: 16 }}>
              <Button size="sm" variant="secondary" disabled={!!busy} onClick={() => void write()} title="Measure again and write again — one model call">
                {busy === "write" ? "Writing…" : "Write it again"}
              </Button>
              <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>
                {edition.model_calls ?? 0} model call{edition.model_calls === 1 ? "" : "s"} · guide v{edition.guide?.version ?? "?"}
              </span>
            </div>
          </>
        )}
      </article>
      {hasGuide && guideOpen && guide && (
        <BriefingGuidePanel connectionId={connectionId} schema={schema} guide={guide} onChange={setGuide}
          readerId={toServerReader(reader ?? ORGANISATION)} onHide={() => setGuideOpen(false)} />
      )}
    </div>
  );
}
