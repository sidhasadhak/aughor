"use client";

/**
 * What gets posted — a Slack step's whole say over its post (2026-11-06; the user approved the
 * mockup `design-mockups/automation-what-gets-posted.html`).
 *
 * "User should be able to control everything that gets posted — the prompt, the picture or not,
 * what kind of picture." The engine used to decide the picture alone: the first result it could
 * find, drawn `auto`, titled with the automation's name, its legend the model's own aliases. Every
 * choice here writes the step's config (`automations/picture.py` reads it at post time), and the
 * preview beside it is the server's own plan over the chain's last run — what posts, not a guess.
 *
 * Words are not a second editor of `message`: the choice WRITES the binding the raw field holds
 * (`{$from: step1.summary}`, `step1.answer`, or both in order), and "My own words" is that field.
 */
import { useEffect, useMemo, useState } from "react";

import type { AutoEffect } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Segmented } from "@/components/ui/segmented";
import { SelectField } from "@/components/ui/select";
import { previewStepPicture, type PicturePreview } from "@/lib/api";
import { ANALYSIS_KIND } from "@/lib/automationFlow";

type Words = "summary" | "headline" | "both" | "own";
type Picture = "none" | "table" | "chart";
type Kind = "auto" | "bar" | "bar_horizontal" | "line" | "pie" | "counter";
type From = "main" | "over_time" | "every";
type Titling = "sentence" | "name" | "custom";

const KIND_LABEL: Record<Kind, string> = {
  auto: "Auto", bar: "Bars", bar_horizontal: "Horizontal bars", line: "Line", pie: "Pie", counter: "Number",
};
const FROM_LABEL: Record<From, string> = {
  main: "The answer's main result", over_time: "A result over time", every: "Every result, one picture each",
};

const sectionLabel: React.CSSProperties = {
  color: "var(--t3)", textTransform: "uppercase", letterSpacing: "0.06em",
};
const why: React.CSSProperties = { color: "var(--t3)" };

function refOf(v: unknown): string {
  return v && typeof v === "object" && "$from" in (v as object) ? String((v as { $from: unknown }).$from) : "";
}

/** The step the message reads from, and which of the words its bindings are. */
export function readWords(message: unknown, headline?: unknown): { source: string; words: Words } {
  const ref = refOf(message);
  const src = ref.split(".")[0] || "";
  if (ref.endsWith(".summary") && refOf(headline) === `${src}.answer`) return { source: src, words: "both" };
  if (ref.endsWith(".summary")) return { source: src, words: "summary" };
  if (ref.endsWith(".answer")) return { source: src, words: "headline" };
  return { source: src, words: "own" };
}

/** The config patch a choice of words writes: the message's binding, and the headline's when it
 *  leads (a field of its own, so the canvas draws both edges). */
export function writeWords(words: Words, source: string): Record<string, unknown> {
  if (words === "summary") return { message: { $from: `${source}.summary` }, headline: null };
  if (words === "headline") return { message: { $from: `${source}.answer` }, headline: null };
  if (words === "both") return { message: { $from: `${source}.summary` }, headline: { $from: `${source}.answer` } };
  return { message: "", headline: null };
}

/** "horizontal bars and pie: one series only, so Oct 28 would be left out · line: no time column in this
 *  result" — the kinds that share a reason said once, together. */
export function leftOutSentence(kinds: Kind[], preview: PicturePreview | null): string {
  const byWhy = new Map<string, Kind[]>();
  for (const k of kinds) {
    const w = preview?.kinds?.[k]?.why ?? "";
    byWhy.set(w, [...(byWhy.get(w) ?? []), k]);
  }
  return [...byWhy.entries()]
    .map(([w, ks]) => `${ks.map(k => KIND_LABEL[k].toLowerCase()).join(" and ")}${w ? `: ${w}` : ""}`)
    .join(" · ");
}

export function WhatGetsPosted({ automationId, index, e, siblings, onChange, onOpenStep }: {
  automationId?: string;
  index: number;
  e: AutoEffect;
  siblings: AutoEffect[];
  onChange: (e: AutoEffect) => void;
  /** Select another step on the canvas — the question lives on its own step. */
  onOpenStep?: (alias: string) => void;
}) {
  const cfg = e.config as Record<string, unknown>;
  const set = (patch: Record<string, unknown>) => onChange({ ...e, config: { ...e.config, ...patch } });
  const aliasAt = (s: AutoEffect, i: number) => (s.alias?.trim() ? s.alias.trim() : `step${i + 1}`);

  const { source, words } = readWords(cfg.message, cfg.headline);
  // The step the words come from: the bound one, else the nearest deep analysis before this step.
  let nearest = "";
  for (let i = index - 1; i >= 0 && !nearest; i--) if (siblings[i]?.kind === ANALYSIS_KIND) nearest = aliasAt(siblings[i], i);
  const sourceAlias = source || nearest;
  const sourceIndex = siblings.findIndex((s, i) => aliasAt(s, i) === sourceAlias);
  const sourceStep = sourceIndex >= 0 ? siblings[sourceIndex] : null;
  const question = sourceStep?.kind === ANALYSIS_KIND ? String(sourceStep.config.question ?? "") : "";

  const picture = (String(cfg.picture || "chart") as Picture);
  const kind = (String(cfg.chart_kind || "auto") as Kind);
  const from = (String(cfg.picture_from || "main") as From);
  const titling = (String(cfg.picture_title || "sentence") as Titling);
  const personNames = (cfg.picture_names && typeof cfg.picture_names === "object"
    ? cfg.picture_names : {}) as Record<string, string>;

  // The preview: the server's plan over the last run, re-asked a beat after the settings settle.
  const [preview, setPreview] = useState<PicturePreview | null>(null);
  const [error, setError] = useState("");
  const asked = useMemo(() => JSON.stringify(cfg), [cfg]);
  useEffect(() => {
    if (!automationId) return;
    let live = true;
    const t = setTimeout(() => {
      previewStepPicture(automationId, index, JSON.parse(asked))
        .then(p => { if (live) { setPreview(p); setError(""); } })
        .catch(err => { if (live) setError((err as Error).message); });
    }, 450);
    return () => { live = false; clearTimeout(t); };
  }, [automationId, index, asked]);

  const fits = (k: Kind) => preview?.kinds?.[k]?.ok !== false;
  const offered = (Object.keys(KIND_LABEL) as Kind[]).filter(k => fits(k) || k === kind);
  const leftOut = (Object.keys(KIND_LABEL) as Kind[]).filter(k => !fits(k) && k !== kind);
  const chosen = new Set((preview?.pictures ?? []).map(p => p.result));
  const labels = preview?.names?.labels ?? {};
  const nameRows = Object.keys(labels);
  const axis = personNames.axis ?? preview?.names?.y_title ?? "";

  return (
    <div data-testid="what-gets-posted" style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1.1fr)", gap: 16, minHeight: 0 }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 14, minWidth: 0 }}>
        {question && (
          <section style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <span className="aug-fs-xs" style={sectionLabel}>The question it answers · {sourceAlias}</span>
            <div className="aug-fs-sm" style={{ color: "var(--t2)", borderLeft: "2px solid var(--b2)", paddingLeft: 10 }}>{question}</div>
            {onOpenStep && (
              <div><Button size="xs" variant="secondary" onClick={() => onOpenStep(sourceAlias)}>Edit the question</Button></div>
            )}
          </section>
        )}

        <section style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <span className="aug-fs-xs" style={sectionLabel}>The words</span>
          <Segmented<Words> label="The words" value={words} size="1"
            onChange={w => set(writeWords(w, sourceAlias || "step1"))}
            options={[{ value: "summary", label: "Summary", title: "The summary the deep analysis wrote" },
                      { value: "headline", label: "Headline", title: "The deep analysis's one-line answer" },
                      { value: "both", label: "Both", title: "The headline, then the summary" },
                      { value: "own", label: "Own words", title: "What you write, posted as written" }]} />
          {words === "own" && (
            <Input value={typeof cfg.message === "string" ? cfg.message : ""} aria-label="The message, in my own words"
              placeholder="what the post says" onChange={ev => set({ message: ev.target.value })} />
          )}
          <span className="aug-fs-xs" style={why}>{words === "own" ? "Posted as written."
            : `${words === "both" ? "The headline, then the summary — read" : "Read"} from ${sourceAlias || "the step before"} on each run.`}</span>
        </section>

        <section style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <span className="aug-fs-xs" style={sectionLabel}>Picture</span>
          <Segmented<Picture> label="Picture" value={picture} onChange={v => set({ picture: v })}
            options={[{ value: "none", label: "None" }, { value: "table", label: "Table" }, { value: "chart", label: "Chart" }]} />
          <span className="aug-fs-xs" style={why}>Posted in the message&apos;s thread, so the message stays the answer.</span>
        </section>

        {picture === "chart" && (
          <section style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <span className="aug-fs-xs" style={sectionLabel}>Kind of chart</span>
            <Segmented<Kind> label="Kind of chart" value={kind} onChange={v => set({ chart_kind: v })}
              options={offered.map(k => ({ value: k, label: KIND_LABEL[k] }))} />
            {leftOut.length > 0 && (
              <span className="aug-fs-xs" style={why} data-testid="kinds-left-out">
                Not offered for this result — {leftOutSentence(leftOut, preview)}.
              </span>
            )}
            <span className="aug-fs-xs" style={why}>A kind the next run&apos;s rows cannot take is drawn as auto, and the picture says why.</span>
          </section>
        )}

        {picture !== "none" && (
          <>
            <section style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <span className="aug-fs-xs" style={sectionLabel}>Drawn from</span>
              <SelectField value={from} aria-label="Drawn from" onChange={ev => set({ picture_from: ev.target.value })}>
                {(Object.keys(FROM_LABEL) as From[]).map(f => <option key={f} value={f}>{FROM_LABEL[f]}</option>)}
              </SelectField>
              <span className="aug-fs-xs" style={why}>The deep analysis writes new results each run, so this is a rule, not a pick.
                {preview?.results?.length ? " On the last run it chose:" : ""}</span>
              {!!preview?.results?.length && (
                <ol style={{ margin: 0, paddingLeft: 18, display: "flex", flexDirection: "column", gap: 4 }}>
                  {preview.results.map((r, i) => (
                    <li key={i} className="aug-fs-xs" style={{ color: chosen.has(i) ? "var(--t1)" : "var(--t3)",
                      fontWeight: chosen.has(i) ? 500 : 400 }}>
                      {r.claim || r.columns.join(", ")} <span style={{ color: "var(--t3)", fontWeight: 400 }}>· {r.rows} row{r.rows === 1 ? "" : "s"}</span>
                    </li>
                  ))}
                </ol>
              )}
            </section>

            <section style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <span className="aug-fs-xs" style={sectionLabel}>Title</span>
              <Segmented<Titling> label="Title" value={titling} onChange={v => set({ picture_title: v })}
                options={[{ value: "sentence", label: "The result's own sentence" }, { value: "name", label: "The automation's name" },
                          { value: "custom", label: "My own words" }]} />
              {titling === "custom" && (
                <Input value={String(cfg.picture_title_text ?? "")} aria-label="The picture's title"
                  placeholder="the title" onChange={ev => set({ picture_title_text: ev.target.value })} />
              )}
            </section>

            {(nameRows.length > 0 || axis) && (
              <section style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                <span className="aug-fs-xs" style={sectionLabel}>Names</span>
                <table style={{ width: "100%", borderCollapse: "collapse" }}>
                  <tbody>
                    {nameRows.map(col => (
                      <tr key={col}>
                        <td className="aug-fs-xs" style={{ fontFamily: "var(--font-mono, monospace)", color: "var(--t3)", width: 72, padding: "3px 6px 3px 0" }}>{col}</td>
                        <td style={{ padding: "3px 0" }}>
                          <Input value={personNames[col] ?? labels[col] ?? ""} aria-label={`What ${col} is called`}
                            onChange={ev => set({ picture_names: { ...personNames, [col]: ev.target.value } })} />
                        </td>
                      </tr>
                    ))}
                    {axis !== "" && (
                      <tr>
                        <td className="aug-fs-xs" style={{ color: "var(--t3)", padding: "3px 6px 3px 0" }}>axis</td>
                        <td style={{ padding: "3px 0" }}>
                          <Input value={axis} aria-label="What the axis is called"
                            onChange={ev => set({ picture_names: { ...personNames, axis: ev.target.value } })} />
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
                <span className="aug-fs-xs" style={why}>Named from each column&apos;s own SQL. The model names columns afresh each run, so a name you
                  type applies whenever that column comes back; a new one is named from its query.</span>
              </section>
            )}
          </>
        )}
      </div>

      <div data-testid="post-preview" style={{ display: "flex", flexDirection: "column", gap: 8, minWidth: 0,
        // The post stays in view while its settings scroll beside it.
        position: "sticky", top: 0, alignSelf: "start" }}>
        <span className="aug-fs-xs" style={sectionLabel}>As Slack will show it{preview?.run_at ? ` · from the run at ${preview.run_at.slice(0, 16).replace("T", " ")}Z` : ""}</span>
        {!automationId && <span className="aug-fs-xs" style={why}>Save the chain once to see its post here.</span>}
        {error && <span className="aug-fs-xs" style={{ ...why, color: "var(--red4)" }}>The preview could not be drawn: {error}</span>}
        {preview?.said && <span className="aug-fs-xs" style={why}>{preview.said}</span>}
        {preview && !preview.said && (
          <div className="aug-fs-sm" style={{ background: "#fff", color: "#1d1c1d", borderRadius: "var(--r3)", padding: "12px 14px",
                        display: "flex", flexDirection: "column", gap: 10, lineHeight: 1.45 }}>
            <div style={{ whiteSpace: "pre-wrap" }}>{preview.words}</div>
            {preview.pictures.map((p, i) => (
              <div key={i} style={{ borderLeft: "3px solid #e8e8e8", paddingLeft: 10, display: "flex", flexDirection: "column", gap: 4 }}>
                <span className="aug-fs-xs" style={{ color: "#616061" }}>{p.note || "In the thread"}</span>
                {p.image ? <img src={p.image} alt={p.title} style={{ width: "100%", border: "1px solid #e8e8e8", borderRadius: 8 }} />
                  : <span className="aug-fs-xs" style={{ color: "#616061" }}>These rows have no honest {p.picture}; none is posted.</span>}
              </div>
            ))}
            {picture === "none" && <span className="aug-fs-xs" style={{ color: "#616061" }}>No picture.</span>}
          </div>
        )}
      </div>
    </div>
  );
}
