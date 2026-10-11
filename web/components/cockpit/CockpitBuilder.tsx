"use client";

/**
 * CockpitBuilder — a cockpit built in place (Arc AP-1; ROADMAP §3.57; docs/COCKPIT_APP_BUILDER_STUDY_2026-10-10.md
 * §4.4 and §4.7; design-mockups/cockpit-builder.html, screen 2).
 *
 * The user, 2026-10-10: "In the current nothing is editable." A cockpit opens to be read; Edit opens this — the
 * cockpit between its layout and the setup of what is chosen, as Workshop lays out its editor:
 *
 *   - left, the layout: the cockpit as a tree of lines, each named by what it reads (`lib/cockpit/names.ts`), and at
 *     its foot the change asked in words, which a model may only arrange;
 *   - middle, the canvas: the cockpit as its reader sees it, live — a table still lists, a filter still narrows — with
 *     the chosen element outlined, and above it a bar to move it, take it off, and step its width and height one grade
 *     at a time. The cockpit is laid out at least as wide as the mockup's page and fits a narrower screen, saying the
 *     zoom; at 1920 × 1080 it draws at 100%;
 *   - right, the setup of the element chosen (`PieceSetup`), or the history while it is open.
 *
 * It holds no store and keeps nothing itself: every change is handed to `onChange` as the next spec, checked by the
 * rules first so a change they refuse is said and never drawn. The page keeps it — one version for a burst.
 */
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { CanvasScale } from "@/components/cockpit/cellBox";
import type { CockpitHandle, ReadState } from "@/components/cockpit/ComposedCockpit";
import { PieceSetup } from "@/components/cockpit/PieceSetup";
import { ChoiceSetup, DataPane, SetSetup, ValueSetup } from "@/components/cockpit/WiringSetup";
import { Segmented } from "@/components/ui/segmented";
import { Button } from "@/components/ui/button";
import { Icon, type IconName } from "@/components/ui/icon";
import { toast } from "@/components/ui/toast";
import { FILTER_DEFAULT_PX, FILTER_WIDTH, GRADE, LIMITS, type GridKind } from "@/lib/cockpit/catalog";
import {
  addSectionInside, canMove, duplicate, inColumns, moveWithin, outline, setFilterWidth, setSectionWidth, splitSection, takeOffAll,
  type Box, type CockpitSpec, type Side,
} from "@/lib/cockpit/edit";
import { lineOf, nameOf, setTitles } from "@/lib/cockpit/names";
import { readersOf } from "@/lib/cockpit/sets";
import { checkCockpitSpec } from "@/lib/cockpit/rules";
import { withUniqueKeys } from "@/lib/listKeys";
import { cachedObjectCatalog } from "@/lib/objects";

/** The name the ontology gives each entity, by its id and its api name — "Customer Order" for `order` — read once a
 *  connection from the object catalog the pieces already read. An entity it does not name keeps its id, in words. */
function useEntityTitles(connectionId: string): (id: string) => string | undefined {
  const [names, setNames] = useState<Record<string, string>>({});
  useEffect(() => {
    let alive = true;
    cachedObjectCatalog(connectionId).then(c => {
      if (!alive || !c) return;
      const out: Record<string, string> = {};
      for (const t of c.object_types) for (const k of [t.object_type, t.id]) if (k && t.display_name) out[k.toLowerCase()] = t.display_name;
      setNames(out);
    }).catch(() => { /* the ids stand, in words */ });
    return () => { alive = false; };
  }, [connectionId]);
  return id => names[id.toLowerCase()];
}

/** The narrowest the canvas lays a cockpit out: the mockup's page. A narrower canvas draws it scaled to fit. */
export const MIN_LAYOUT = 1100;
/** The canvas's own margin around the cockpit. */
const PAD = 16;

const ICON: Record<string, IconName> = {
  Cockpit: "gauge", Tab: "panel", Section: "layers", Card: "metric", Note: "text", Image: "attach", ProcessBoard: "process",
  ObjectTable: "table", ObjectDetail: "list", ActionButton: "bolt", ObjectFilters: "filter", ObjectFigure: "num", ObjectChart: "chart",
};

/** The pane's small uppercase heading. */
function PaneLabel({ children }: { children: ReactNode }) {
  return (
    <div className="aug-fs-xs" style={{ color: "var(--t3)", textTransform: "uppercase", letterSpacing: ".06em", padding: "12px 12px 6px" }}>
      {children}
    </div>
  );
}

/** The cockpit as a tree of lines: each named by what it reads, the chosen one marked. */
export function LayoutTree({ spec, selected, onSelect, cardTitle, entityTitle }: {
  spec: CockpitSpec; selected: string | null; onSelect: (key: string) => void; cardTitle?: (id: string) => string | undefined;
  entityTitle?: (id: string) => string | undefined;
}) {
  const lines = outline(spec);
  return (
    <div role="tree" aria-label="The cockpit's layout" data-testid="builder-layout" style={{ padding: "0 6px 8px" }}>
      {lines.map(line => {
        const { kind, title } = nameOf(spec.elements, line.key, cardTitle, entityTitle, setTitles(spec));
        const el = spec.elements[line.key];
        const room = el.props.w && el.props.h ? `${el.props.w} × ${el.props.h}` : "";
        const on = selected === line.key;
        return (
          <button key={line.key} type="button" role="treeitem" aria-selected={on} data-testid="builder-line" data-key={line.key}
            onClick={() => onSelect(line.key)} className="aug-fs-sm"
            style={{ display: "flex", alignItems: "center", gap: 7, width: "100%", padding: `4px 6px 4px ${6 + line.depth * 14}px`,
              border: 0, borderRadius: "var(--r2)", background: on ? "var(--accent-a3, var(--bg-3))" : "transparent", cursor: "pointer",
              color: on ? "var(--t1)" : "var(--t2)", textAlign: "left", font: "inherit" }}>
            <span aria-hidden="true" style={{ display: "inline-flex", color: on ? "var(--accent-11, var(--t1))" : "var(--t3)" }}>
              <Icon name={ICON[line.type] ?? "dot"} size={13} />
            </span>
            <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {title || kind.charAt(0).toUpperCase() + kind.slice(1)}
            </span>
            <span className="aug-fs-xs" style={{ color: "var(--t3)", flex: "none", fontVariantNumeric: "tabular-nums" }}>{room || (title ? kind : "")}</span>
          </button>
        );
      })}
    </div>
  );
}

/** − n + : one grade less or more of a width or a height, never past what the kind may take. */
function Steps({ label, value, least, most, onStep }: { label: string; value: number | null; least: number; most: number; onStep: (d: number) => void }) {
  return (
    <span data-testid={`builder-steps-${label.toLowerCase()}`} title="One grade at a time · Alt+arrows"
      style={{ display: "inline-flex", alignItems: "center", gap: 3 }}>
      <span className="aug-fs-xs" style={{ color: "var(--t3)", marginRight: 2 }}>{label}</span>
      <Button size="xs" variant="outline" aria-label={`${label}: one grade less`} disabled={value === null || value <= least} onClick={() => onStep(-1)}>−</Button>
      <span className="aug-fs-sm" data-testid={`builder-${label.toLowerCase()}`} style={{ minWidth: 22, textAlign: "center", color: "var(--t1)", fontVariantNumeric: "tabular-nums" }}>
        {value ?? "—"}
      </span>
      <Button size="xs" variant="outline" aria-label={`${label}: one grade more`} disabled={value === null || value >= most} onClick={() => onStep(1)}>+</Button>
    </span>
  );
}

const Rule = () => <span aria-hidden="true" style={{ width: 1, height: 16, background: "var(--b2)", margin: "0 6px" }} />;

export function CockpitBuilder({ spec, onChange, cardTitle, bar, add, words, aside, above, connectionId, schema, wiringOn = false,
  structureOn = false, onAddPiece, checks, cardSetup, children }: {
  spec: CockpitSpec;
  /** Every change, as the next spec and the version's note. */
  onChange: (next: CockpitSpec, note: string) => void;
  cardTitle?: (id: string) => string | undefined;
  /** The edit bar, drawn by the page that keeps the cockpit. */
  bar: ReactNode;
  /** What may be added — a card, a note, a piece — under the layout. */
  add?: ReactNode;
  /** The change asked in words, at the foot of the layout. */
  words?: ReactNode;
  /** The history while it is open, in the setup's place. */
  aside?: ReactNode;
  /** What is drawn above the cockpit on the canvas: a composer open, what a keep said. */
  above?: ReactNode;
  connectionId: string;
  schema?: string;
  /** Arc AP-2 — whether this install wires cockpits: the Data tab, and what pieces read, then. */
  wiringOn?: boolean;
  /** Arc AP-4 — whether a cockpit may be split into sections: a section's split, its sections inside, a copy, a width. */
  structureOn?: boolean;
  /** Arc AP-4 — open the piece picker for a section: the one chosen, the one a chosen piece sits in, or none. */
  onAddPiece?: (section: string | null) => void;
  /** Arc AP-6 — what each element drawn read, by key: the checks chip counts them and lists the ones to fix. */
  checks?: Record<string, ReadState>;
  /** Arc AP-7 — the setup of a card the page knows more of (a card of a person's own query), by its id; null for none. */
  cardSetup?: (cardId: string) => ReactNode | null;
  /** The cockpit, drawn with the element chosen, the door that chooses one, the handle the steps use, and — while a
   *  set, a value or a choice is chosen — the pieces that read it. */
  children: (p: { selected: string | null; onSelect: (key: string) => void; handle: { current: CockpitHandle | null }; reads: string[] }) => ReactNode;
}) {
  const [chosen, setSelected] = useState<string | null>(null);
  const [tab, setTab] = useState<"layout" | "data">("layout");
  // a set, a value or a choice chosen in the Data tab: `set:<name>`, `value:<name>`, `choice:<name>`
  const [wire, setWire] = useState<string | null>(null);
  const wireName = wire ? wire.slice(wire.indexOf(":") + 1) : "";
  const wireKind = wire ? wire.slice(0, wire.indexOf(":")) : "";
  const reads = wire ? readersOf(spec, wireName).elements : [];
  const entityTitle = useEntityTitles(connectionId);
  const handle = useRef<CockpitHandle | null>(null);
  // an element taken off, by hand or by an undo, is no longer chosen; nor is an element while a set is
  const selected = !wire && chosen && spec.elements[chosen] ? chosen : null;
  const choose = (key: string) => { setWire(null); setSelected(key); };

  /** Hand a change on — or say why the rules refuse it, and draw nothing of it. */
  const apply = (next: CockpitSpec, note: string) => {
    const check = checkCockpitSpec(next);
    if (!check.valid) {
      toast.error("That change is not made", { description: check.issues[0]?.message.slice(0, 200) });
      return;
    }
    onChange(next, note);
  };

  // the canvas: laid out at least as wide as the mockup's page; scaled to fit a narrower canvas, unless the person asks 100%
  const canvas = useRef<HTMLDivElement>(null);
  const page = useRef<HTMLDivElement>(null);
  const [room, setRoom] = useState({ width: 0, height: 0 });
  const [whole, setWhole] = useState(false);
  useEffect(() => {
    const c = canvas.current, p = page.current;
    if (!c || !p || typeof ResizeObserver === "undefined") return;
    const read = () => setRoom({ width: c.clientWidth, height: p.offsetHeight });
    const ro = new ResizeObserver(read);
    ro.observe(c);
    ro.observe(p);
    read();
    return () => ro.disconnect();
  }, []);
  const avail = Math.max(0, room.width - 2 * PAD);
  const fits = avail > 0 ? Math.min(1, avail / MIN_LAYOUT) : 1;
  const scale = whole ? 1 : fits;
  const layout = avail > 0 ? Math.max(avail, MIN_LAYOUT) : undefined;
  const zoom = Math.round(scale * 100);

  // the chosen element's room, read again whenever the cockpit changes: its own on the grid, measured off it
  const el = selected ? spec.elements[selected] : undefined;
  const kind = el && el.type in LIMITS ? (el.type as GridKind) : null;
  const [box, setBox] = useState<Box | null>(null);
  useLayoutEffect(() => {
    setBox(kind && selected ? handle.current?.room(selected) ?? null : null);
  }, [kind, selected, spec, room.width]);
  const filterGrades = el?.type === "ObjectFilters" ? Number(el.props.w) || Math.round(FILTER_DEFAULT_PX / GRADE) : null;
  const named = selected ? nameOf(spec.elements, selected, cardTitle, entityTitle, setTitles(spec)) : null;
  const movable = !!selected && el?.type !== "Cockpit";
  const lines = useMemo(() => outline(spec).length, [spec]);

  const step = (dw: number, dh: number) => {
    if (selected && kind) handle.current?.step(selected, dw, dh);
  };
  // Arc AP-4 — a section chosen: where it may be split, what it holds, its width among columns
  const section = structureOn && el?.type === "Section" ? selected : null;
  const laidOut = !!section && !!el?.props.layout;
  const sectionW = section && inColumns(spec, section) ? Number(el?.props.w) || null : null;
  const split = (side: Side) => {
    if (!section) return;
    const done = splitSection(spec, section, side);
    if (!done.key) return;
    const check = checkCockpitSpec(done.spec);
    if (!check.valid) { toast.error("That change is not made", { description: check.issues[0]?.message.slice(0, 200) }); return; }
    onChange(done.spec, `split ${side} by hand`);
    setSelected(done.key);
  };
  // the section a piece goes in — or a drawer (Arc AP-4): the one chosen, or the one a chosen piece sits in
  const holds = (k: string) => (spec.elements[k]?.type === "Section" && !spec.elements[k].props.layout) || spec.elements[k]?.type === "Drawer";
  const target = selected && holds(selected) ? selected
    : selected ? Object.keys(spec.elements).find(k => holds(k) && spec.elements[k].children.includes(selected)) ?? null : null;

  return (
    <div data-testid="cockpit-builder" style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
      {bar}
      <div style={{ flex: 1, minHeight: 0, display: "grid", gridTemplateColumns: "232px minmax(0, 1fr) 304px" }}>
        <aside aria-label="Layout" style={{ minHeight: 0, overflow: "auto", borderRight: "1px solid var(--b1)", background: "var(--bg-1)", display: "flex", flexDirection: "column" }}>
          {wiringOn && (
            <div style={{ padding: "10px 10px 0" }}>
              <Segmented label="The left pane" value={tab} options={[{ value: "layout", label: "Layout" }, { value: "data", label: "Data" }]}
                onChange={v => { setTab(v as "layout" | "data"); if (v === "layout") setWire(null); }} />
            </div>
          )}
          {tab === "data" && wiringOn ? (
            <DataPane spec={spec} selected={wire} onSelect={key => { setWire(key); setSelected(null); }} onChange={apply}
              connectionId={connectionId} schema={schema} />
          ) : (
            <>
              <PaneLabel>Layout · {lines} {lines === 1 ? "line" : "lines"}</PaneLabel>
              <LayoutTree spec={spec} selected={selected} onSelect={choose} cardTitle={cardTitle} entityTitle={entityTitle} />
            </>
          )}
          {(add || onAddPiece) && (
            <>
              <PaneLabel>Add</PaneLabel>
              <div data-testid="builder-add" style={{ display: "flex", flexWrap: "wrap", gap: 2, padding: "0 8px 8px" }}>
                {onAddPiece && (
                  <Button size="xs" variant="secondary" data-testid="builder-add-piece" title="Every piece, by what it is for — placed in the section chosen."
                    onClick={() => onAddPiece(target)}>
                    <Icon name="plus" /> Add a piece
                  </Button>
                )}
                {add}
              </div>
            </>
          )}
          <div style={{ flex: 1 }} />
          {words && <div style={{ borderTop: "1px solid var(--b1)", padding: "10px 12px" }}>{words}</div>}
        </aside>

        <div style={{ minWidth: 0, minHeight: 0, display: "flex", flexDirection: "column", background: "var(--bg-0)" }}>
          <div data-testid="builder-selection" className="aug-fs-sm"
            style={{ display: "flex", alignItems: "center", gap: 4, padding: "6px 12px", borderBottom: "1px solid var(--b1)", minHeight: 40, flexWrap: "wrap" }}>
            {wire ? (
              <>
                <span className="aug-fs-xs" style={{ color: "var(--accent-11)", textTransform: "uppercase", letterSpacing: ".06em", marginRight: 6 }}>
                  {wireKind === "set" ? "Set" : wireKind === "value" ? "Value" : "Chosen"}
                </span>
                <span style={{ color: "var(--t1)" }}>{wireKind === "set" ? spec.sets?.[wireName]?.label : wireKind === "value" ? spec.values?.[wireName]?.label : wireName.replace(/[-_]/g, " ")}</span>
                <span className="aug-fs-xs" style={{ color: "var(--t3)", marginLeft: 10, flex: 1 }}>
                  {reads.length ? `the ${reads.length === 1 ? "piece that reads it is" : `${reads.length} pieces that read it are`} dashed` : "nothing on the cockpit reads it yet"}
                </span>
              </>
            ) : named ? (
              <>
                <span className="aug-fs-xs" style={{ color: "var(--accent-11)", textTransform: "uppercase", letterSpacing: ".06em", marginRight: 6 }}>{named.kind}</span>
                <span style={{ color: "var(--t1)", minWidth: 0, maxWidth: 280, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{named.title}</span>
                <span style={{ flex: 1 }} />
                {movable && (
                  <>
                    <Button size="xs" variant="ghost" aria-label="Move earlier" disabled={!canMove(spec, selected!, -1)}
                      onClick={() => apply(moveWithin(spec, selected!, -1), "moved by hand")}><Icon name="chevu" size={13} /></Button>
                    <Button size="xs" variant="ghost" aria-label="Move later" disabled={!canMove(spec, selected!, 1)}
                      onClick={() => apply(moveWithin(spec, selected!, 1), "moved by hand")}><Icon name="chevd" size={13} /></Button>
                    <Rule />
                    {section && (
                      <>
                        <span className="aug-fs-xs" style={{ color: "var(--t3)", textTransform: "uppercase", letterSpacing: ".06em", margin: "0 4px" }}>Split</span>
                        {(["above", "below", "left", "right"] as const).map(side => (
                          <Button key={side} size="xs" variant="ghost" aria-label={`Split it: a new section ${side === "left" || side === "right" ? `to the ${side}` : side}`}
                            data-testid={`builder-split-${side}`} onClick={() => split(side)}>
                            <Icon name={side === "above" ? "chevu" : side === "below" ? "chevd" : side === "left" ? "chevl" : "chevr"} size={13} />
                          </Button>
                        ))}
                        {laidOut && (
                          <Button size="xs" variant="ghost" data-testid="builder-add-section"
                            onClick={() => { const d = addSectionInside(spec, section); if (d.key) { apply(d.spec, "a section added inside by hand"); setSelected(d.key); } }}>
                            <Icon name="plus" size={13} /> Section inside
                          </Button>
                        )}
                        <Rule />
                      </>
                    )}
                    {structureOn && el?.type !== "ObjectFilters" && el?.type !== "Drawer" && (
                      <Button size="xs" variant="ghost" data-testid="builder-duplicate"
                        onClick={() => { const d = duplicate(spec, selected!); if (d.key) { apply(d.spec, "duplicated by hand"); setSelected(d.key); } }}>
                        <Icon name="copy" size={13} /> Duplicate
                      </Button>
                    )}
                    <Button size="xs" variant="ghost" data-testid="builder-take-off"
                      onClick={() => apply(takeOffAll(spec, selected!), "taken off by hand")}><Icon name="trash" size={13} /> Take off</Button>
                  </>
                )}
                {sectionW !== null && (
                  <>
                    <Rule />
                    <Steps label="Width" value={sectionW} least={1} most={12}
                      onStep={d => apply(setSectionWidth(spec, section!, sectionW + d), "a section's width stepped by hand")} />
                    <span className="aug-fs-xs" style={{ color: "var(--t3)", marginLeft: 4 }}>of 12</span>
                  </>
                )}
                {kind && (
                  <>
                    <Rule />
                    <Steps label="Width" value={box?.w ?? null} least={LIMITS[kind].w[0]} most={LIMITS[kind].w[1]} onStep={d => step(d, 0)} />
                    <Steps label="Height" value={box?.h ?? null} least={LIMITS[kind].h[0]} most={LIMITS[kind].h[1]} onStep={d => step(0, d)} />
                  </>
                )}
                {filterGrades !== null && (
                  <>
                    <Rule />
                    <Steps label="Width" value={filterGrades} least={FILTER_WIDTH.least} most={FILTER_WIDTH.most}
                      onStep={d => apply(setFilterWidth(spec, filterGrades + d), "the filter column resized by hand")} />
                    <span className="aug-fs-xs" style={{ color: "var(--t3)", marginLeft: 4 }}>{filterGrades * GRADE} px</span>
                  </>
                )}
              </>
            ) : (
              <span style={{ color: "var(--t3)", flex: 1 }}>Choose a piece on the cockpit, or a line in its layout.</span>
            )}
            {checks && <ChecksChip spec={spec} checks={checks} onChoose={choose} cardTitle={cardTitle} entityTitle={entityTitle} />}
            <Rule />
            <Button size="xs" variant="ghost" data-testid="builder-zoom" disabled={fits >= 1}
              title={fits >= 1 ? "The cockpit is drawn at its full size" : whole ? "Fit the cockpit to the canvas" : "Draw the cockpit at its full size"}
              onClick={() => setWhole(w => !w)}>
              {scale < 1 ? `Fit · ${zoom}%` : "100%"}
            </Button>
          </div>
          <div ref={canvas} data-testid="builder-canvas" style={{ flex: 1, minHeight: 0, overflow: "auto", padding: PAD }}>
            {above}
            <div style={{ width: layout ? layout * scale : undefined, height: room.height ? room.height * scale : undefined }}>
              <div ref={page} data-testid="builder-page" data-zoom={zoom}
                style={{ width: layout, transform: scale < 1 ? `scale(${scale})` : undefined, transformOrigin: "0 0" }}>
                <CanvasScale.Provider value={scale}>
                  {children({ selected, onSelect: choose, handle, reads })}
                </CanvasScale.Provider>
              </div>
            </div>
          </div>
        </div>

        <aside aria-label="Setup" data-testid="builder-setup"
          style={{ minHeight: 0, overflow: "auto", borderLeft: "1px solid var(--b1)", background: "var(--bg-1)" }}>
          {aside ?? (wireKind === "set" ? <SetSetup spec={spec} name={wireName} onChange={apply} onGone={() => setWire(null)} connectionId={connectionId} schema={schema} />
            : wireKind === "value" ? <ValueSetup spec={spec} name={wireName} onChange={apply} onGone={() => setWire(null)} />
              : wireKind === "choice" ? <ChoiceSetup spec={spec} name={wireName} />
                : <PieceSetup spec={spec} selected={selected} onChange={apply} connectionId={connectionId} schema={schema} cardTitle={cardTitle}
                  entityTitle={entityTitle} wiringOn={wiringOn} cardSetup={cardSetup} />)}
        </aside>
      </div>
    </div>
  );
}

/** Arc AP-6 — the checks chip: how many elements read cleanly, how many are still reading, and the ones to fix — each
 *  with why, a click choosing it. Counted over what the cockpit holds now, as each cell said it. */
function ChecksChip({ spec, checks, onChoose, cardTitle, entityTitle }: {
  spec: CockpitSpec; checks: Record<string, ReadState>; onChoose: (key: string) => void;
  cardTitle?: (id: string) => string | undefined; entityTitle?: (id: string) => string | undefined;
}) {
  const [open, setOpen] = useState(false);
  const held = Object.entries(checks).filter(([k]) => k in spec.elements);
  const fix = held.filter(([, c]) => c.status === "refused");
  const reading = held.filter(([, c]) => c.status === "reading").length;
  const clean = held.filter(([, c]) => c.status === "ok").length;
  if (!held.length) return null;
  return (
    <span style={{ position: "relative", marginLeft: 6 }}>
      <Button size="xs" variant={fix.length ? "secondary" : "ghost"} data-testid="builder-checks" aria-expanded={open} disabled={!fix.length}
        title={fix.length ? "The pieces that could not be read, and why" : "Every piece read cleanly"} onClick={() => setOpen(o => !o)}>
        <Icon name={fix.length ? "alert" : "check"} size={13} />
        {`${clean} read cleanly`}{reading ? ` · ${reading} reading` : ""}{fix.length ? ` · ${fix.length} to fix` : ""}
      </Button>
      {open && fix.length > 0 && (
        <span role="list" data-testid="builder-checks-list" style={{ position: "absolute", right: 0, top: "calc(100% + 4px)", zIndex: 30, width: 340,
          display: "flex", flexDirection: "column", gap: 2, padding: 6, background: "var(--bg-1)", border: "1px solid var(--b1)",
          borderRadius: "var(--r3)", boxShadow: "var(--shadow-md)" }}>
          {withUniqueKeys(fix, ([k]) => k).map(([id, [key, c]]) => (
            <Button key={id} role="listitem" variant="ghost" data-testid="builder-checks-item" onClick={() => { setOpen(false); onChoose(key); }}
              style={{ height: "auto", justifyContent: "flex-start", textAlign: "left", whiteSpace: "normal", padding: "6px 8px" }}>
              <span style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 0 }}>
                <span className="aug-fs-sm" style={{ color: "var(--t1)" }}>{lineOf(spec.elements, key, cardTitle, entityTitle, setTitles(spec))}</span>
                <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>{c.reason || "It could not be read."}</span>
              </span>
            </Button>
          ))}
        </span>
      )}
    </span>
  );
}

/** What a page hands its edit bar. */
export interface EditBarProps {
  picker: ReactNode;
  saved: ReactNode;
  canUndo: boolean;
  canRedo: boolean;
  onUndo: () => void;
  onRedo: () => void;
  actions: ReactNode;
  onDone: () => void;
}

/** The one bar of Edit mode: which cockpit, that it is being edited and when it was last kept, undo and redo, what may
 *  be added or done to it, and Done. */
export function EditBar({ picker, saved, canUndo, canRedo, onUndo, onRedo, actions, onDone }: EditBarProps) {
  return (
    <div data-testid="builder-bar" className="aug-fs-sm"
      style={{ display: "flex", alignItems: "center", gap: 8, padding: "7px 14px", borderBottom: "1px solid var(--b1)", background: "var(--bg-1)", flexWrap: "wrap" }}>
      {picker}
      <span className="aug-tag" style={{ color: "var(--accent-11)" }}>Editing</span>
      <span data-testid="builder-saved" style={{ color: "var(--t3)" }}>{saved}</span>
      <Button size="xs" variant="ghost" title="Undo the last change — kept as a version of its own" disabled={!canUndo} onClick={onUndo}>Undo</Button>
      <Button size="xs" variant="ghost" title="Redo what was undone" disabled={!canRedo} onClick={onRedo}>Redo</Button>
      <span style={{ flex: 1 }} />
      {actions}
      <Button size="sm" data-testid="builder-done" onClick={onDone}>Done</Button>
    </div>
  );
}
