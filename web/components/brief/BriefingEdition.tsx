"use client";

/**
 * Arc BC (ROADMAP §3.67, §6 item 59) — the Briefing as an edition the model composes, for one reader.
 *
 * The user, 2026-10-29: "let the LLMs use The Briefing as an open canvas to draw any element … everything with
 * citations and drill down possibilities … it should make sense right away to any user!" So the page holds no
 * sections of its own: after the range and the reader, it draws the blocks the model composed — the answer in a
 * sentence first — each from the sources the server ran. Every cited number opens its source beside the page; a
 * drill writes one level deeper under its block; a question is answered under the page.
 *
 * Opening never spends (§6 item 58): the page READS the edition last written for the range and the reader, and
 * writes one only when a person presses the button.
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import { BriefingGuidePanel } from "@/components/brief/BriefingGuidePanel";
import { BriefingOffNotice } from "@/components/brief/BriefingOff";
import { BriefSchedule } from "@/components/brief/BriefSchedule";
import { RangeControl, type RangeChoice } from "@/components/brief/BriefRange";
import { EditionBlocks } from "@/components/brief/blocks/EditionBlocks";
import { EditionAsk, EditionEvidence } from "@/components/brief/blocks/EditionEvidence";
import { Button } from "@/components/ui/button";
import { Segmented } from "@/components/ui/segmented";
import { toast } from "@/components/ui/toast";
import {
  draftBriefingGuide, drillBriefingEdition, getGroups, giveBriefingDecision, putMyPreference, readBriefingEdition,
  readBriefingGuide, writeBriefingEdition,
  type AccessGroup, type BriefingEdition as Edition, type BriefingGuideResponse, type BriefingRange, type EditionBlock,
} from "@/lib/api";
import { formatTimestamp } from "@/lib/format";
import { ORGANISATION, fromServerReader, readerOptions, toServerReader, writeLabel } from "@/lib/briefingEdition";

const PRESETS = ["last_week", "last_month", "last_year"] as const;
const RULE = "1px solid var(--b1)";

const when = (iso?: string): string => (iso ? formatTimestamp(iso, "short") : "");

export function BriefingEdition({ connectionId, schema, workspaceId, canvasId, onDeepAnalysis }: {
  connectionId: string;
  schema?: string;
  workspaceId?: string;
  /** A Data Canvas: its own edition, reading only the canvas's tables. */
  canvasId?: string;
  /** Hand a question to deep analysis (the Data Canvas). */
  onDeepAnalysis?: (q: string) => void;
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
  const [side, setSide] = useState<"sources" | "guide" | "">("sources");
  const [picked, setPicked] = useState<string>("");
  const [drilling, setDrilling] = useState("");
  const [giving, setGiving] = useState("");
  const [askSeed, setAskSeed] = useState<{ q: string; n: number } | null>(null);
  const [hidden, setHidden] = useState<Set<string>>(new Set());
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
    setPicked("");
    readBriefingEdition(connectionId, range, asked === undefined ? undefined : toServerReader(asked), schema, workspaceId, canvasId)
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
  }, [connectionId, schema, workspaceId, canvasId, range, asked]);

  const chooseReader = (v: string) => {
    setReader(v);
    setAsked(v);
    putMyPreference("briefing_reader", toServerReader(v)).catch(() => toast.error("Your reader could not be kept; it holds for this visit"));
  };

  const write = async () => {
    setBusy("write");
    try { setEdition(await writeBriefingEdition(connectionId, range, toServerReader(reader ?? ORGANISATION), schema, workspaceId, canvasId)); }
    catch (e) { toast.error(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(""); }
  };

  const draft = async () => {
    setBusy("draft");
    try { setGuide(await draftBriefingGuide(connectionId, schema)); }
    catch (e) { toast.error(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(""); }
  };

  const onCite = useCallback((id: string) => { setPicked(id); setSide("sources"); }, []);

  const onDrill = useCallback(async (block: EditionBlock, column: string, segment?: unknown) => {
    if (!block.source) return;
    setDrilling(`${block.id}:${column}`);
    try {
      const out = await drillBriefingEdition(connectionId, range, toServerReader(reader ?? ORGANISATION),
        { source_id: block.source, column, segment: segment as string | number | boolean | null | undefined, after: block.id },
        schema, workspaceId, canvasId);
      setEdition(e => {
        if (!e?.blocks) return e;
        const blocks = [...e.blocks];
        blocks.splice(out.at, 0, out.block);
        return { ...e, blocks, sources: { ...(e.sources ?? {}), [out.source.id]: out.source } };
      });
    } catch (e) { toast.error(e instanceof Error ? e.message : String(e)); }
    finally { setDrilling(""); }
  }, [connectionId, range, reader, schema, workspaceId, canvasId]);

  const onGive = useCallback(async (block: EditionBlock, groupId: string) => {
    setGiving(`${block.id}:${groupId}`);
    try {
      const got = await giveBriefingDecision(connectionId, range, toServerReader(reader ?? ORGANISATION),
        { block_id: block.id, group_id: groupId }, schema, workspaceId, canvasId);
      setEdition(e => e && ({ ...e, given: [...(e.given ?? []).filter(g => !(g.block === got.block && g.group_id === got.group_id)), got] }));
    } catch (e) { toast.error(e instanceof Error ? e.message : String(e)); }
    finally { setGiving(""); }
  }, [connectionId, range, reader, schema, workspaceId, canvasId]);

  const onDecide = useCallback((action: string, block: EditionBlock) => {
    if (action === "not_now") { setHidden(h => new Set(h).add(block.id)); return; }
    const q = (block.text ?? "").replace(/\{([^{}|]+)\|[A-Za-z0-9_-]+\}/g, "$1");
    if (onDeepAnalysis) onDeepAnalysis(q);
    else setAskSeed(s => ({ q, n: (s?.n ?? 0) + 1 }));
  }, [onDeepAnalysis]);

  const period = edition?.period;
  const periodWord = period?.period ?? "week";
  const custom = range.preset === "custom";
  const readerName = readerOptions(groups).find(o => o.value === (reader ?? ORGANISATION))?.label ?? "The organisation";
  const teams = useMemo(() => groups.filter(g => g.kind === "function").map(g => ({ id: g.id, name: g.name }))
    .sort((a, b) => a.name.localeCompare(b.name)), [groups]);
  const hasGuide = !!guide?.available;
  const ownCanvas = edition?.canvas?.own ? edition.canvas : null;
  const blocks = useMemo(() => (edition?.blocks ?? []).filter(b => !hidden.has(b.id)), [edition, hidden]);
  const sources = edition?.sources ?? {};
  const used = useMemo(() => {
    const ids = new Set<string>();
    blocks.forEach(b => {
      if (b.source) ids.add(b.source);
      (b.chain ?? []).forEach(c => ids.add(c));
      [b.text, b.sub, b.title].forEach(t => (t ?? "").replace(/\{[^{}|]+\|([A-Za-z0-9_-]+)\}/g, (_m, id: string) => { ids.add(id); return ""; }));
    });
    return [...ids].map(id => sources[id]).filter(Boolean);
  }, [blocks, sources]);

  return (
    // The layer around the Briefing does not scroll (it is overflow: hidden): the edition and the side panel each
    // scroll on their own, the panel staying beside whatever block is in view.
    <div data-testid="briefing-edition" style={{ display: "grid", gridTemplateColumns: side ? "minmax(0,1fr) 380px" : "minmax(0,1fr)",
                                                  height: "100%", minHeight: 0 }}>
      <article style={{ padding: "20px 34px 48px", minWidth: 0, height: "100%", overflowY: "auto" }}>
        <div style={{ maxWidth: 960, margin: "0 auto" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
            <h1 className="aug-fs-h2" style={{ fontWeight: 600, margin: 0, color: "var(--t1)" }}>The Briefing</h1>
            {period && <span className="aug-fs-sm" style={{ color: "var(--t3)" }}>{period.covers}</span>}
            <span style={{ marginLeft: "auto", display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
              <RangeControl value={range as RangeChoice} presets={[...PRESETS]}
                onChange={c => { if (c.preset !== "standing") setRange(c as BriefingRange); }} />
              {!canvasId && <Button size="sm" variant="ghost" onClick={() => setSchedule(!schedule)}>{schedule ? "Close schedule" : "Schedule"}</Button>}
              {!side && <Button size="sm" variant="ghost" onClick={() => setSide("sources")}>Sources &amp; guide</Button>}
            </span>
          </div>
          {schedule && <BriefSchedule connId={connectionId} />}
          <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 0", flexWrap: "wrap" }}>
            <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>Reading as</span>
            <Segmented label="Reading as" value={reader ?? ORGANISATION} onChange={chooseReader} options={readerOptions(groups)} />
          </div>
          {edition?.built && period && (
            <p className="aug-fs-xs" data-testid="edition-dateline" style={{ color: "var(--t3)", margin: "0 0 4px" }}>
              What changed in {period.covers}, written for <b style={{ color: "var(--t2)", fontWeight: 500 }}>{readerName}</b>, against{" "}
              {period.compared_with}. Every underlined number opens where it came from.
              {edition.guide?.state === "draft" ? " Written from a draft guide no person has published." : ""}
            </p>
          )}
          {edition?.canvas && (
            <p className="aug-fs-xs" data-testid="edition-canvas"
              style={{ color: "var(--t2)", margin: "6px 0 4px", padding: "6px 10px", borderLeft: "2px solid var(--blue4)", background: "var(--bg-1)" }}>
              {edition.canvas.own
                ? <>This canvas reads <b style={{ color: "var(--t1)", fontWeight: 500 }}>{edition.canvas.tables.join(", ")}</b>, so its
                    edition is its own: {edition.canvas.checks_inside.length} of the guide&apos;s{" "}
                    {edition.canvas.checks_inside.length + edition.canvas.checks_outside.length} checks, and the model looks only at
                    these tables.{edition.built && edition.canvas.checks_outside.length > 0
                      ? ` Left out, because they read other tables: ${edition.canvas.checks_outside.join(", ")}.` : ""}</>
                : <>This canvas reads every table of {edition.canvas.dataset || "this dataset"}, so its Briefing is the dataset&apos;s own
                    edition — the one the Briefing page shows, written once.</>}
            </p>
          )}

          {error && <p className="aug-fs-sm" style={{ color: "var(--amb4)" }}>{error}</p>}
          {edition?.off ? <BriefingOffNotice off={edition.off} connectionId={connectionId} />
          : loading ? <p className="aug-fs-sm" style={{ color: "var(--t3)", padding: "22px 0" }}>Reading the edition…</p>
          : !hasGuide && guide ? (
            <section data-testid="edition-no-guide" style={{ padding: "26px 0" }}>
              <h2 className="aug-fs-display" style={{ margin: "0 0 8px", color: "var(--t1)" }}>This dataset has no Briefing guide yet</h2>
              <p className="aug-fs-sm" style={{ maxWidth: "62ch", margin: "0 0 12px" }}>
                The guide says how this dataset&apos;s Briefing is written — what matters here, what counts as news, who reads
                it. The Explorer drafts it at the end of an exploration; draft it now from what was learned (one model call).
              </p>
              <Button disabled={!!busy} onClick={() => void draft()}>{busy === "draft" ? "Drafting…" : "Draft the guide"}</Button>
            </section>
          ) : !edition?.built ? (
            <section data-testid="edition-unwritten" style={{ padding: "26px 0" }}>
              <h2 className="aug-fs-display" style={{ margin: "0 0 8px", color: "var(--t1)" }}>Not written yet for {readerName}</h2>
              {ownCanvas && (
                <>
                  <p className="aug-fs-sm" style={{ maxWidth: "62ch", margin: "0 0 10px" }}>
                    <b style={{ color: "var(--t1)", fontWeight: 500 }}>Measured here:</b> {ownCanvas.checks_inside.join(", ") || "none of the guide's checks"}.
                  </p>
                  {ownCanvas.checks_outside.length > 0 && (
                    <p className="aug-fs-sm" style={{ maxWidth: "62ch", margin: "0 0 10px" }}>
                      <b style={{ color: "var(--t1)", fontWeight: 500 }}>Left out, because they read other tables:</b> {ownCanvas.checks_outside.join(", ")}.
                    </p>
                  )}
                </>
              )}
              <p className="aug-fs-sm" style={{ maxWidth: "62ch", margin: "0 0 12px" }}>
                {ownCanvas ? `The ${ownCanvas.checks_inside.length}` : `The guide's ${guide?.guide?.checks.length ?? 0}`} checks are measured for{" "}
                {period?.covers ?? "this range"}; then the model looks into what moved — at most 8 queries of its own
                {ownCanvas ? ", on these tables only" : ""} — and composes the page for {readerName}. Every number it writes is checked
                against what was measured. It takes about a minute.
              </p>
              <Button disabled={!!busy} onClick={() => void write()}>{busy === "write" ? "Looking into it and writing…" : writeLabel(periodWord, custom)}</Button>
            </section>
          ) : (
            <>
              {edition.drawn_by_code && (
                <p className="aug-fs-sm" data-testid="edition-by-code" style={{ color: "var(--amb4)", margin: "8px 0" }}>
                  This edition was drawn by code from what was measured: {edition.drawn_by_code}.
                </p>
              )}
              <EditionBlocks blocks={blocks} sources={sources} figures={period?.measured ?? []} drillColumns={edition.drill_columns}
                currency={edition.currency_code ?? ""} connectionId={connectionId} schema={schema}
                onCite={onCite} onDrill={(b, c, s) => void onDrill(b, c, s)} onDecide={onDecide} drilling={drilling}
                teams={teams} given={edition.given} onGive={(b, g) => void onGive(b, g)} giving={giving} />
              {(!!edition.withheld?.length || !!edition.left_out?.length) && (
                <section data-testid="edition-withheld" className="aug-fs-xs" style={{ color: "var(--t3)", borderTop: RULE, paddingTop: 10, marginTop: 18 }}>
                  {edition.withheld?.map((w, i) => (
                    <div key={`w-${i}`}>Held back{w.sentence ? `: “${w.sentence}”` : " a block"} — {w.why}</div>
                  ))}
                  {edition.left_out?.map((l, i) => <div key={`l-${i}`}>Left out: {l}</div>)}
                </section>
              )}
              {period && (
                <EditionAsk key={askSeed?.n ?? 0} connectionId={connectionId} schema={schema} canvasId={canvasId} periodKey={period.key}
                  reader={toServerReader(reader ?? ORGANISATION)} seed={askSeed?.q} onDeeper={onDeepAnalysis} />
              )}
              <div className="aug-fs-xs" style={{ display: "flex", gap: 10, alignItems: "center", marginTop: 18, color: "var(--t3)" }}>
                <Button size="sm" variant="secondary" disabled={!!busy} onClick={() => void write()}
                  title="Measure again, look again and write again">
                  {busy === "write" ? "Looking into it and writing…" : "Write it again"}
                </Button>
                <span>
                  written {when(edition.generated_at)} · {edition.model_steps ?? 0} model steps · {edition.queries ?? 0} queries
                  of its own · guide v{edition.guide?.version ?? "?"}
                </span>
              </div>
            </>
          )}
        </div>
      </article>
      {side && (
        <aside aria-label="Sources and guide" style={{ borderLeft: RULE, background: "var(--bg-1)", height: "100%", minHeight: 0,
                                                       display: "flex", flexDirection: "column" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "10px 14px", borderBottom: RULE }}>
            <Segmented label="Side panel" value={side} onChange={v => setSide(v as "sources" | "guide")}
              options={[{ value: "sources", label: "Sources" }, ...(hasGuide ? [{ value: "guide", label: "Guide" }] : [])]} />
            <Button size="xs" variant="ghost" style={{ marginLeft: "auto" }} onClick={() => setSide("")}>Hide</Button>
          </div>
          <div style={{ flex: 1, minHeight: 0, overflowY: "auto", padding: side === "sources" ? "14px 16px 30px" : 0 }}>
            {side === "guide" && guide ? (
              <BriefingGuidePanel connectionId={connectionId} schema={schema} guide={guide} onChange={setGuide}
                readerId={toServerReader(reader ?? ORGANISATION)} onHide={() => setSide("sources")} />
            ) : (
              <EditionEvidence source={picked ? sources[picked] ?? null : null} used={used} onPick={setPicked} onClose={() => setPicked("")} />
            )}
          </div>
        </aside>
      )}
    </div>
  );
}
