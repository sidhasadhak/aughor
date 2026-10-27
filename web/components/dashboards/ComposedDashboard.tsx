"use client";

/**
 * ComposedDashboard — a dashboard drawn from a spec (Arc CT, CT-1 and CT-2; ROADMAP §3.50; the
 * canvas, docs/COCKPIT_CANVAS_2026-10-08.md).
 *
 * The law of the arc: the spec arranges, the card store measures. This component draws tabs
 * and sections from the spec, and hands every card to `DashboardTile`, which draws the card's own
 * run at its metric's unit — nothing about what a card measures is decided in this file. (Until
 * the user's "make the dashboard look like the mockup", 2026-09-28, a card was drawn with the
 * Briefing's `PinnedCardBody` unchanged; the face changed, the law did not.)
 *
 * Since the canvas a section also holds a person's own Note and Image, drawn by `StaticTile`,
 * and every element has a size from the catalog's closed set: a column span cut to what the
 * section has, and a row span. The size changes the room, never the measurement. A person
 * resizes by the corner of a tile or by its size pick; either lands as one kept version through
 * `doors.onResize`, and a dashboard the reader may not change offers neither.
 *
 * Three things it will not do:
 *   - draw a spec the rules refuse. It says why instead, in the rules' own sentences.
 *   - let a condition read anything the host did not publish. The state a dashboard renders
 *     against is the open tab plus the host's tree, laid over whatever the spec seeded.
 *   - hide a card without saying so. A section counts the cards waiting on a condition, a
 *     card the reader may not see stays where it is and says it is withheld, and a card
 *     that fails to draw says that too. The library wraps every element in an error
 *     boundary of its own that draws NOTHING when a component throws; the boundary here
 *     sits inside it, so the library's never gets the chance.
 *
 * The Briefing draws a person's dashboards with it (`BriefingDashboards`), behind `dashboard.composed`.
 */
import {
  Children, Component, createContext, useCallback, useContext, useEffect, useImperativeHandle, useLayoutEffect, useMemo, useRef, useState,
  type PointerEvent as ReactPointerEvent, type ReactNode, type Ref, type RefObject,
} from "react";
import { evaluateVisibility, type Spec, type VisibilityCondition } from "@json-render/core";
import {
  JSONUIProvider, Renderer, createStateStore, useBoundProp, useStateStore,
  type ComponentRegistry, type ComponentRenderProps,
} from "@json-render/react";

import type { CardState } from "@/components/brief/PinnedCardBody";
import { CanvasScale, CellBoxContext, OFF_GRID, useMeasured, type CellBox } from "@/components/dashboards/cellBox";
import { QuestionPiece } from "@/components/dashboards/QuestionPiece";
import { DashboardTile, SaidTile, WIDE, WithheldTile, tileShape, type QueryWaiting, type TileDoors } from "@/components/dashboards/DashboardTile";
import { ActionButtonsPiece } from "@/components/dashboards/ActionButtonsPiece";
import { ReadSlotContext, type ReadSlot, type ReadStatus } from "@/components/dashboards/readSlot";
import { ChooseOnePiece, ObjectListPiece, ObjectMapPiece, ObjectSearchPiece, ObjectTimelinePiece } from "@/components/dashboards/AppPieces";
import {
  ActionButtonPiece, FilterBar, NotFiltered, ObjectBreakdownPiece, ObjectChartPiece, ObjectDetailPiece, ObjectFigurePiece,
  ObjectFiltersPiece, ObjectTablePiece, PiecesProvider, ProcessBoardPiece, ValuesBar, chooseWords, useFiltering, usePieceFiltering, usePieces,
  type FilterProperty,
} from "@/components/dashboards/OntologyPieces";
import { ImageTile, NoteTile, type ImageStamp, type StaticDoors } from "@/components/dashboards/StaticTile";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { Refusal } from "@/components/ui/states";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { runCard, type BriefingRange, type CardRunResult, type DashboardCard } from "@/lib/api";
import {
  FILTER_DEFAULT_PX, FILTER_WIDTH, GRADE, GRID, LIMITS, SPAN, rowsTall, sizeOf, type ActionButtonDef, type ComponentName,
  type GridKind, type Layout, type Size, type Tone,
} from "@/lib/dashboards/catalog";
import { boxOf, clampBox, type Box } from "@/lib/dashboards/edit";
import { stateModel, type DashboardHostState } from "@/lib/dashboards/hostState";
import { checkDashboardSpec, openingTab } from "@/lib/dashboards/rules";
import type { WireSpec } from "@/lib/dashboards/sets";
import { valuesFor, valuesRead, type ValuesSent } from "@/lib/dashboards/values";

/** What a dashboard may ask of the page that holds it. The static doors and `onResize` are absent
 *  on a dashboard the reader may not change — a published one, a strip. */
export interface DashboardDoors extends TileDoors, StaticDoors {
  /** Arc OC-4 — place a table of a segment, from a process board's open-and-overdue count. */
  onPlaceTable?: (entity: string, segment: string) => void;
  /** Arc AP-1 — give an element its room on its section's grid, one grade at a time. `measured` is the room every element
   *  of a section not yet on the grid has on screen, so moving it onto the grid keeps what the reader saw. */
  onRegrid?: (key: string, box: Box, measured: Record<string, Box>) => void;
  /** Arc AP-1 — the filter column's width, in grades of 40 px. */
  onFilterWidth?: (grades: number) => void;
  /** Arc AP-1 — the builder: a piece, the filter column or a section pointed at is the one chosen to set up. */
  onSelect?: (key: string) => void;
  /** Arc AP-4 — an empty section's offer: a piece placed in it, or sections of its own laid out in it. */
  onAddPiece?: (sectionKey: string) => void;
  onLayOut?: (sectionKey: string, layout: Layout) => void;
  /** Arc AP-6 — what each placed element read: refused (with why), still reading, or read cleanly; null once it goes. */
  onReadState?: (key: string, state: ReadState | null) => void;
}

/** What the builder may ask of a dashboard it draws (Arc AP-1): an element's room on its section's grid — measured from
 *  the screen when the section is not on the grid yet — and one grade more or less of it, as Alt+arrows give. */
export interface DashboardHandle {
  room: (key: string) => Box | null;
  step: (key: string, dw: number, dh: number) => void;
}

type Stepper = { room: () => Box | null; step: (dw: number, dh: number) => void };

interface DashboardContextValue {
  elements: Spec["elements"];
  cards: Map<string, CardState>;
  host: DashboardHostState;
  doors: DashboardDoors;
  /** The doors a tile is handed: the size picked by name goes where the grid's handles resize instead (Arc AP-1). */
  tileDoors: DashboardDoors;
  sym: string;
  images: Record<string, ImageStamp>;
  range: BriefingRange | null;
  schema?: string;
  /** The connection the dashboard reads — what a Question asks of. */
  connectionId?: string;
  /** The element chosen in the builder, outlined where it is drawn. */
  selected: string | null;
  /** Arc AP-2 — the elements that read the set, value or choice chosen in the builder, dashed where they are drawn. */
  reads: Set<string>;
  /** Each drawn element's room and steps, by key, for the builder's − and + (`DashboardHandle`). */
  steppers: Map<string, Stepper>;
}

const DashboardContext = createContext<DashboardContextValue | null>(null);

/** The section an element is drawn in: its key, how many columns it draws, and the keys it
 *  holds in order. The renderer hands a component its element and not its key, so the key of
 *  what is drawn is found here, among the section's children, by what the element says. */
const SectionKeys = createContext<{ key: string | null; columns: number; children: string[]; grid: boolean; stacked: boolean }>(
  { key: null, columns: 1, children: [], grid: false, stacked: false });

function useDashboard(): DashboardContextValue {
  const ctx = useContext(DashboardContext);
  if (!ctx) throw new Error("a dashboard component was drawn outside ComposedDashboard");
  return ctx;
}

function sameList(a: unknown, b: unknown): boolean {
  return Array.isArray(a) && Array.isArray(b) && a.length === b.length && a.every((v, i) => v === b[i]);
}

/** The key of the element being drawn. Two elements that say exactly the same thing in one
 *  section are one thing to a reader, and the first is it. */
function useElementKey(type: ComponentName, props: unknown): string | null {
  const { elements } = useDashboard();
  const { children } = useContext(SectionKeys);
  const said = JSON.stringify(props);
  return children.find(k => elements[k]?.type === type && JSON.stringify(elements[k]?.props) === said) ?? null;
}

/** The rule down a card's left edge. A tone is emphasis; it never replaces the card's own frame. */
const TONE_RULE: Record<Tone, string> = {
  good: "var(--grn3)", warn: "var(--amb3)", bad: "var(--red3)", info: "var(--blue3)", neutral: "var(--b2)",
};

/** The filter column's width beside the pieces it narrows, when a person has set none (the approved mockup's). */
const FILTER_COLUMN = FILTER_DEFAULT_PX;

function DashboardRoot({ element, children }: ComponentRenderProps<{ title: string }>) {
  // The title names the dashboard for a screen reader and for the history. It is not drawn as a
  // header: the strip of dashboards above it already carries the name, and a panel does not
  // repeat its own title.
  const { elements, doors, selected } = useDashboard();
  const firstKey = element.children?.[0] ?? "";
  const first = elements[firstKey];
  const [preview, setPreview] = useState<number | null>(null);
  if (first?.type !== "ObjectFilters") {
    return <div role="region" aria-label={element.props.title} data-testid="dashboard"><ValuesBar />{children}</div>;
  }
  // A dashboard started from an object: its filter column at the left, the pieces it narrows beside it, and above them
  // what is chosen and how many objects that leaves (the rules hold the column to the root's first child, once).
  const [column, ...rest] = Children.toArray(children);
  const props = first.props as { entity: string; properties: FilterProperty[]; w?: number | null; set?: string | null };
  // Arc AP-1 — its width in grades of 40 px, when a person set one; else as it was drawn before
  const grades = preview ?? props.w ?? null;
  const width = grades ? grades * GRADE : FILTER_COLUMN;
  return (
    <div role="region" aria-label={element.props.title} data-testid="dashboard"
      style={{ display: "grid", gridTemplateColumns: `${width}px minmax(0, 1fr)`, gap: 14, alignItems: "start" }}>
      <div className="group" data-testid="dashboard-filter-column" data-width={width} data-selected={selected === firstKey || undefined}
        onPointerDownCapture={doors.onSelect ? () => doors.onSelect?.(firstKey) : undefined}
        style={{ position: "relative", alignSelf: "stretch", minWidth: 0, borderRadius: "var(--r3)",
          outline: selected === firstKey ? "2px solid var(--accent)" : undefined, outlineOffset: 2 }}>
        {column}
        {doors.onFilterWidth && (
          <WidthHandle from={grades ?? Math.round(FILTER_COLUMN / GRADE)} onPreview={setPreview}
            onDone={g => doors.onFilterWidth?.(g)} />
        )}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 14, minWidth: 0 }}>
        <ValuesBar spaced={false} />
        <FilterBar entity={props.entity} properties={props.properties} set={props.set} />
        {rest}
      </div>
    </div>
  );
}

function DashboardTabs({ element, children, bindings }: ComponentRenderProps<{ value: string }>) {
  const { elements } = useDashboard();
  const [open, setOpen] = useBoundProp<string>(element.props.value, bindings?.value);
  const tabs = (element.children ?? []).map(key => {
    const props = elements[key]?.props as { name: string; label: string };
    return { key, name: props.name, label: props.label };
  });
  return (
    <Tabs value={open ?? tabs[0]?.name} onValueChange={v => setOpen(String(v))}>
      <TabsList>
        {tabs.map(t => <TabsTrigger key={t.key} value={t.name}>{t.label}</TabsTrigger>)}
      </TabsList>
      {children}
    </Tabs>
  );
}

/** How many of an element's children a condition is hiding right now. */
function useWaiting(children: string[] | undefined): number {
  const { elements } = useDashboard();
  const { state } = useStateStore();
  return (children ?? []).filter(key => {
    const cond = elements[key]?.visible as VisibilityCondition | undefined;
    return cond !== undefined && !evaluateVisibility(cond, { stateModel: state });
  }).length;
}

function DashboardTab({ element, children }: ComponentRenderProps<{ name: string; label: string }>) {
  const waiting = useWaiting(element.children);
  return (
    <TabsContent value={element.props.name}>
      {children}
      {waiting > 0 && (
        <div className="aug-fs-sm" data-testid="dashboard-waiting-sections" style={{ color: "var(--t3)", marginTop: 16, display: "flex", alignItems: "center", gap: 6 }}>
          <Icon name="eyeoff" size={13} />
          {waiting === 1 ? "1 section waits on a condition" : `${waiting} sections wait on a condition`}
        </div>
      )}
    </TabsContent>
  );
}

/** The narrowest a tile is drawn. A section never asks for more columns than fit. */
const MIN_TILE = 200;
const GAP = 12;
const MAX_AUTO_COLUMNS = 4;
/** The room a second row gives a tile when nothing beside it sets the row's height. */
const TALL_MIN = 320;
/** A section on the grid narrower than this draws its elements one under another, each across its whole width. */
const NARROW_GRID = 560;

/** How many columns a section draws: the spec's, when it says, never more than fit — and how wide it is. Width 0 is
 *  a section not yet measured (or a test's DOM), and draws as asked. */
function useColumns(asked: number | null | undefined): [RefObject<HTMLDivElement | null>, number, number] {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => setWidth(el.clientWidth));
    ro.observe(el);
    setWidth(el.clientWidth);
    return () => ro.disconnect();
  }, []);
  const fit = width > 0 ? Math.max(1, Math.floor((width + GAP) / (MIN_TILE + GAP))) : MAX_AUTO_COLUMNS;
  return [ref, Math.min(asked ?? MAX_AUTO_COLUMNS, fit), width];
}

type SectionProps = { title?: string | null; columns?: number | null; grid?: number | null; layout?: Layout | null; w?: number | null };

/** A section's own key. Each element's children list is its own object in the spec the renderer draws, so an empty
 *  section is told from another empty one by it (Arc AP-4); a list equal by its keys is the fallback, as before. */
function useSectionKey(element: { children?: string[] }): string | null {
  const { elements } = useDashboard();
  return useMemo(() => Object.keys(elements).find(k => elements[k]?.type === "Section" && elements[k]?.children === element.children)
    ?? Object.keys(elements).find(k => elements[k]?.type === "Section" && sameList(elements[k]?.children, element.children ?? [])) ?? null,
  [elements, element.children]);
}

/** A section: one laid out in sections of its own, one that holds nothing yet, or one that holds pieces (Arc AP-4). */
function DashboardSection(props: ComponentRenderProps<SectionProps>) {
  if (props.element.props.layout) return <LaidOutSection {...props} />;
  if (!(props.element.children ?? []).length) return <EmptySection {...props} />;
  return <PiecesSection {...props} />;
}

/** The outline a section wears in the builder while it is the one chosen. */
function useChosenOutline(key: string | null) {
  const { doors, selected } = useDashboard();
  return {
    "data-selected": (key !== null && selected === key) || undefined,
    onPointerDownCapture: doors.onSelect && key ? () => doors.onSelect?.(key) : undefined,
    style: { borderRadius: "var(--r3)", outline: key !== null && selected === key ? "1px dashed var(--accent)" : undefined, outlineOffset: 6 },
  };
}

/** Arc AP-4 — a section split into sections of its own: side by side by their widths in twelfths (stacked when the
 *  page is too narrow), one under another, or one at a time as tabs — each tab called by its section's title. */
function LaidOutSection({ element, children }: ComponentRenderProps<SectionProps>) {
  const { elements } = useDashboard();
  const key = useSectionKey(element);
  const chosen = useChosenOutline(key);
  const [box, room] = useMeasured<HTMLDivElement>();
  const kids = Children.toArray(children);
  const held = element.children ?? [];
  const [tab, setTab] = useState(0);
  const layout = element.props.layout as Layout;
  const narrow = room.width > 0 && room.width < NARROW_GRID;
  return (
    <section data-testid="dashboard-layout" data-layout={layout} data-key={key ?? undefined} aria-label={element.props.title ?? "Sections"}
      {...chosen} style={{ ...chosen.style, marginTop: element.props.title ? 20 : 0 }}>
      {element.props.title && <div className="aug-fs-h2" style={{ fontWeight: 600, color: "var(--t1)", marginBottom: 10 }}>{element.props.title}</div>}
      {layout === "tabs" ? (
        <>
          <div role="tablist" aria-label={element.props.title ?? "Sections"} style={{ display: "flex", gap: 4, borderBottom: "1px solid var(--b1)", marginBottom: 12 }}>
            {held.map((k, i) => (
              <Button key={k} size="sm" variant="ghost" role="tab" aria-selected={i === tab} data-testid="dashboard-layout-tab" onClick={() => setTab(i)}
                style={{ borderRadius: 0, color: i === tab ? "var(--t1)" : "var(--t3)", borderBottom: i === tab ? "2px solid var(--accent)" : "2px solid transparent" }}>
                {String(elements[k]?.props?.title ?? `Tab ${i + 1}`)}
              </Button>
            ))}
          </div>
          {/* every tab stays drawn, the ones not shown hidden — a reader's choices in one survive a look at another */}
          {kids.map((node, i) => <div key={held[i] ?? i} role="tabpanel" hidden={i !== tab}>{node}</div>)}
        </>
      ) : (
        <div ref={box} style={layout === "columns" ? {
          display: "grid", gap: GRID.gap * 1.5, alignItems: "start", gridTemplateColumns: `repeat(${narrow ? 1 : GRID.columns}, minmax(0, 1fr))`,
        } : { display: "flex", flexDirection: "column", gap: 4 }}>
          {kids.map((node, i) => {
            const w = Number(elements[held[i]]?.props?.w ?? GRID.columns);
            return <div key={held[i] ?? i} data-testid="dashboard-layout-cell" data-w={layout === "columns" ? w : undefined}
              style={layout === "columns" ? { gridColumn: `span ${narrow ? 1 : Math.min(GRID.columns, Math.max(1, w))}`, minWidth: 0 } : { minWidth: 0 }}>{node}</div>;
          })}
        </div>
      )}
    </section>
  );
}

/** Arc AP-4 — a section that holds nothing yet. In the builder it says what it may hold — a piece, or sections of its
 *  own — as Workshop's blank app does (the user, 2026-10-11); a reader is drawn nothing there. */
function EmptySection({ element }: ComponentRenderProps<SectionProps>) {
  const { doors } = useDashboard();
  const key = useSectionKey(element);
  const chosen = useChosenOutline(key);
  const [splitting, setSplitting] = useState(false);
  if (!doors.onSelect) return null;
  return (
    <section data-testid="dashboard-empty-section" data-key={key ?? undefined} aria-label={element.props.title ?? "Section"} {...chosen}
      style={{ ...chosen.style, minHeight: 160, display: "flex", flexDirection: "column", border: "1.5px dashed var(--b2)",
        borderColor: key !== null && chosen["data-selected"] ? "var(--accent)" : "var(--b2)" }}>
      <div className="aug-fs-sm" style={{ padding: "8px 12px", color: "var(--t2)", borderBottom: "1px dashed var(--b1)" }}>{element.props.title ?? "Section"}</div>
      <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 8, padding: 16 }}>
        {doors.onAddPiece && key && (
          <Button size="sm" variant="outline" data-testid="empty-section-add" onClick={() => doors.onAddPiece?.(key)} style={{ minWidth: 180 }}>
            <Icon name="plus" size={13} /> Add a piece
          </Button>
        )}
        {doors.onLayOut && key && (splitting ? (
          <span style={{ display: "inline-flex", gap: 4 }} role="group" aria-label="Split it into">
            {(["columns", "rows", "tabs"] as const).map(l => (
              <Button key={l} size="xs" variant="ghost" data-testid={`empty-section-${l}`} onClick={() => { setSplitting(false); doors.onLayOut?.(key, l); }}>
                {l === "columns" ? "Columns" : l === "rows" ? "Rows" : "Tabs"}
              </Button>
            ))}
          </span>
        ) : (
          <Button size="sm" variant="ghost" data-testid="empty-section-split" onClick={() => setSplitting(true)} style={{ minWidth: 180 }}>
            <Icon name="column" size={13} /> Split into…
          </Button>
        ))}
      </div>
    </section>
  );
}

function PiecesSection({ element, children }: ComponentRenderProps<SectionProps>) {
  const { elements, doors, selected } = useDashboard();
  // A section named as the dashboard is named says nothing new: its heading is not drawn (a dashboard started from an
  // object holds one such section).
  const named = Object.values(elements).find(el => el?.type === "Cockpit")?.props as { title?: string } | undefined;
  const heading = element.props.title !== named?.title;
  const waiting = useWaiting(element.children);
  const [ref, columns, width] = useColumns(element.props.columns);
  // Arc AP-1 — on the grid: twelve columns and rows of one grade, each element placed by its w and h
  const gridded = element.props.grid === GRID.columns;
  const stacked = gridded && width > 0 && width < NARROW_GRID;
  const held = element.children ?? [];
  const key = useSectionKey(element);
  const keys = useMemo(() => ({ key, columns, children: held, grid: gridded, stacked }), [key, columns, held, gridded, stacked]);
  return (
    // in the builder a click anywhere in a section chooses it — and a click on one of its pieces then chooses the piece
    <section data-testid="dashboard-section" aria-label={element.props.title ?? "Section"} data-key={key ?? undefined} data-selected={(key !== null && selected === key) || undefined}
      onPointerDownCapture={doors.onSelect && key ? () => doors.onSelect?.(key) : undefined}
      style={{ marginTop: heading ? 20 : 0, borderRadius: "var(--r3)",
        outline: key !== null && selected === key ? "1px dashed var(--accent)" : undefined, outlineOffset: 6 }}>
      <div style={{ display: heading || waiting > 0 ? "flex" : "none", justifyContent: "space-between", alignItems: "baseline", gap: 12, marginBottom: 10 }}>
        <div className="aug-fs-h2" style={{ fontWeight: 600, color: "var(--t1)" }}>{heading ? element.props.title : ""}</div>
        {waiting > 0 && (
          <div className="aug-fs-sm" data-testid="dashboard-waiting" style={{ color: "var(--t3)", display: "flex", alignItems: "center", gap: 6 }}>
            <Icon name="eyeoff" size={13} />
            {waiting === 1 ? "1 card waits on a condition" : `${waiting} cards wait on a condition`}
          </div>
        )}
      </div>
      <div ref={ref} data-columns={gridded ? GRID.columns : columns} data-grid={gridded ? GRID.columns : undefined}
        style={gridded ? {
          display: "grid", gap: GRID.gap, alignItems: "stretch", gridAutoRows: `${GRID.row}px`,
          gridTemplateColumns: `repeat(${stacked ? 1 : GRID.columns}, minmax(0, 1fr))`,
        } : {
          display: "grid", gap: GAP, alignItems: "stretch", gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))`,
        }}>
        <SectionKeys.Provider value={keys}>{children}</SectionKeys.Provider>
      </div>
    </section>
  );
}

/** A card that throws while drawing says so, in its own place. Keyed by the card, so a
 *  refresh that brings a run it CAN draw gets a fresh start. */
class CardBoundary extends Component<{ children: ReactNode }, { failed: string | null }> {
  state = { failed: null as string | null };

  static getDerivedStateFromError(error: unknown) {
    return { failed: error instanceof Error ? error.message : String(error) };
  }

  render() {
    if (this.state.failed === null) return this.props.children;
    return <SaidTile what="Could not be drawn">This card is here, and drawing it failed: {this.state.failed}</SaidTile>;
  }
}

const clamp = (lo: number, hi: number, v: number) => Math.max(lo, Math.min(hi, v));

/** The corner a person drags to resize a tile. It snaps to whole columns and rows — never to
 *  pixels — and lands once, on release, as one of the catalog's sizes. */
function ResizeCorner({ cell, columns, from, onPreview, onDone }: {
  cell: RefObject<HTMLDivElement | null>;
  columns: number;
  from: { w: number; h: number };
  onPreview: (span: { w: number; h: number } | null) => void;
  onDone: (w: number, h: number) => void;
}) {
  const down = (ev: ReactPointerEvent<HTMLSpanElement>) => {
    const el = cell.current;
    const grid = el?.parentElement;
    if (!el || !grid) return;
    ev.preventDefault();
    ev.stopPropagation();
    const target = ev.currentTarget;
    const colW = (grid.clientWidth - GAP * (columns - 1)) / columns;
    const rowH = (el.getBoundingClientRect().height - GAP * (from.h - 1)) / from.h;
    const x0 = ev.clientX, y0 = ev.clientY;
    let w = from.w, h = from.h;
    try { target.setPointerCapture(ev.pointerId); } catch { /* an engine without capture still gets the moves over the handle */ }
    const move = (mv: PointerEvent) => {
      const nw = clamp(1, Math.min(3, columns), from.w + Math.round((mv.clientX - x0) / (colW + GAP)));
      const nh = clamp(1, 2, from.h + Math.round((mv.clientY - y0) / (rowH + GAP)));
      if (nw !== w || nh !== h) { w = nw; h = nh; onPreview({ w, h }); }
    };
    const up = () => {
      target.removeEventListener("pointermove", move);
      target.removeEventListener("pointerup", up);
      target.removeEventListener("pointercancel", up);
      onPreview(null);
      if (w !== from.w || h !== from.h) onDone(w, h);
    };
    target.addEventListener("pointermove", move);
    target.addEventListener("pointerup", up);
    target.addEventListener("pointercancel", up);
  };
  return (
    <span data-testid="resize-corner" title="Drag to resize · snaps to the grid" aria-hidden="true" onPointerDown={down}
      className="opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100"
      style={{ position: "absolute", right: 3, bottom: 2, width: 18, height: 18, display: "grid", placeItems: "center",
        fontSize: 11, color: "var(--t3)", cursor: "nwse-resize", touchAction: "none", userSelect: "none", borderRadius: 4 }}>
      ◢
    </span>
  );
}

/** What every element of a section measures on screen, as columns (twelfths of the section) and rows of one grade —
 *  so a section moving onto the grid keeps the room each element had for the reader (Arc AP-1). */
function measureSection(grid: HTMLElement): Record<string, Box> {
  const colW = (grid.clientWidth - GRID.gap * (GRID.columns - 1)) / GRID.columns;
  const out: Record<string, Box> = {};
  if (colW <= 0) return out;
  for (const child of Array.from(grid.children) as HTMLElement[]) {
    const key = child.dataset.element;
    // the layout's own px — the builder's canvas may draw the dashboard scaled, and the grid is laid out unscaled
    const r = { width: child.offsetWidth, height: child.offsetHeight };
    if (!key || !r.width || !r.height) continue;
    out[key] = { w: Math.round((r.width + GRID.gap) / (colW + GRID.gap)), h: Math.round((r.height + GRID.gap) / GRADE) };
  }
  return out;
}

type Edge = "w" | "h" | "both";

/** A handle's look: a short bar on the edge it moves, in the accent, shown while the element is pointed at or focused. */
const HANDLE = "opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100 group-focus:opacity-100";

/** The handles a person drags to resize an element one grade at a time (Arc AP-1; the user, 2026-10-10: "adjusted one
 *  grade point at a time"): the right edge for its columns, the bottom edge for its rows, the corner for both. Each
 *  snaps grade by grade, says the size it would land on, and lands once, on release. On a section not yet on the grid
 *  every element is measured first, so moving the section onto the grid keeps what the reader saw. */
function GridHandles({ cell, kind, from, gridded, onPreview, onDone }: {
  cell: RefObject<HTMLDivElement | null>;
  kind: GridKind;
  /** The element's room now: its own on the grid; null off it, where it is measured when a drag begins. */
  from: Box | null;
  gridded: boolean;
  onPreview: (b: Box | null, columnPx: number) => void;
  onDone: (b: Box, measured: Record<string, Box>) => void;
}) {
  const [said, setSaid] = useState<Box | null>(null);
  const scale = useContext(CanvasScale);
  const lim = LIMITS[kind];
  const down = (edge: Edge) => (ev: ReactPointerEvent<HTMLSpanElement>) => {
    const el = cell.current;
    const grid = el?.parentElement;
    if (!el || !grid) return;
    ev.preventDefault();
    ev.stopPropagation();
    const target = ev.currentTarget;
    const measured = gridded ? {} : measureSection(grid);
    const start = from ?? measured[el.dataset.element ?? ""];
    if (!start) return;
    const colW = (grid.clientWidth - GRID.gap * (GRID.columns - 1)) / GRID.columns;
    const x0 = ev.clientX, y0 = ev.clientY;
    let w = start.w, h = start.h;
    try { target.setPointerCapture(ev.pointerId); } catch { /* an engine without capture still sends the moves over the handle */ }
    const move = (mv: PointerEvent) => {
      const nw = edge === "h" ? start.w : clamp(lim.w[0], lim.w[1], start.w + Math.round((mv.clientX - x0) / scale / (colW + GRID.gap)));
      const nh = edge === "w" ? start.h : clamp(lim.h[0], lim.h[1], start.h + Math.round((mv.clientY - y0) / scale / GRADE));
      if (nw !== w || nh !== h) { w = nw; h = nh; onPreview({ w, h }, colW); setSaid({ w, h }); }
    };
    const up = () => {
      target.removeEventListener("pointermove", move);
      target.removeEventListener("pointerup", up);
      target.removeEventListener("pointercancel", up);
      onPreview(null, colW);
      setSaid(null);
      if (w !== start.w || h !== start.h) onDone({ w, h }, measured);
    };
    target.addEventListener("pointermove", move);
    target.addEventListener("pointerup", up);
    target.addEventListener("pointercancel", up);
  };
  const bar = (edge: Edge, place: Record<string, string | number>, cursor: string, title: string) => (
    <span key={edge} data-testid={`grid-handle-${edge}`} title={title} aria-hidden="true" onPointerDown={down(edge)} className={HANDLE}
      style={{ position: "absolute", zIndex: 3, background: "var(--accent)", borderRadius: 3, cursor, touchAction: "none", ...place }} />
  );
  return (
    <>
      {bar("w", { right: -4, top: "50%", width: 5, height: 30, transform: "translateY(-50%)" }, "ew-resize", "Drag: one column at a time")}
      {bar("h", { bottom: -4, left: "50%", height: 5, width: 30, transform: "translateX(-50%)" }, "ns-resize", "Drag: one row at a time")}
      {bar("both", { right: -5, bottom: -5, width: 11, height: 11 }, "nwse-resize", "Drag: columns and rows · Alt+arrows: one grade")}
      {said && (
        <span data-testid="grid-size-said" className="aug-fs-sm" style={{ position: "absolute", right: 12, bottom: 10, zIndex: 4,
          background: "var(--bg-3)", border: "1px solid var(--b2)", color: "var(--t1)", borderRadius: "var(--r2)", padding: "1px 8px",
          fontVariantNumeric: "tabular-nums", pointerEvents: "none" }}>
          {said.w} × {said.h}
        </span>
      )}
    </>
  );
}

/** The filter column's handle: its right edge, moved one grade of 40 px at a time, between 200 and 400 px (Arc AP-1). */
function WidthHandle({ from, onPreview, onDone }: { from: number; onPreview: (g: number | null) => void; onDone: (g: number) => void }) {
  const [said, setSaid] = useState<number | null>(null);
  const scale = useContext(CanvasScale);
  const down = (ev: ReactPointerEvent<HTMLSpanElement>) => {
    ev.preventDefault();
    ev.stopPropagation();
    const target = ev.currentTarget;
    const x0 = ev.clientX;
    let g = from;
    try { target.setPointerCapture(ev.pointerId); } catch { /* the moves still come over the handle */ }
    const move = (mv: PointerEvent) => {
      const ng = clamp(FILTER_WIDTH.least, FILTER_WIDTH.most, from + Math.round((mv.clientX - x0) / scale / GRADE));
      if (ng !== g) { g = ng; onPreview(g); setSaid(g); }
    };
    const up = () => {
      target.removeEventListener("pointermove", move);
      target.removeEventListener("pointerup", up);
      target.removeEventListener("pointercancel", up);
      onPreview(null);
      setSaid(null);
      if (g !== from) onDone(g);
    };
    target.addEventListener("pointermove", move);
    target.addEventListener("pointerup", up);
    target.addEventListener("pointercancel", up);
  };
  return (
    <>
      <span data-testid="filter-width-handle" title="Drag: 40 px at a time" aria-hidden="true" onPointerDown={down} className={HANDLE}
        style={{ position: "absolute", right: -9, top: 40, width: 5, height: 30, zIndex: 3, background: "var(--accent)", borderRadius: 3,
          cursor: "ew-resize", touchAction: "none" }} />
      {said !== null && (
        <span data-testid="filter-width-said" className="aug-fs-sm" style={{ position: "absolute", right: 4, top: 8, zIndex: 4,
          background: "var(--bg-3)", border: "1px solid var(--b2)", color: "var(--t1)", borderRadius: "var(--r2)", padding: "1px 8px",
          fontVariantNumeric: "tabular-nums", pointerEvents: "none" }}>{said * GRADE} px</span>
      )}
    </>
  );
}

/** What a placed element read, as the builder's checks count it (Arc AP-6). */
export interface ReadState { status: "ok" | ReadStatus; reason: string }
let lastMark = 0;

/** What a cell read, from the marks of what it draws: refused when any part of it is — what to fix outranks what is
 *  still coming — still reading while any part is, and read cleanly when nothing marks it. */
export function readStateOf(held: { status: ReadStatus; reason: string }[]): ReadState {
  const refused = held.find(m => m.status === "refused");
  if (refused) return { status: "refused", reason: refused.reason };
  return held.some(m => m.status === "reading") ? { status: "reading", reason: "" } : { status: "ok", reason: "" };
}

/** Alt+arrows: one grade wider, narrower, taller or shorter. */
const STEP: Record<string, [number, number]> = { ArrowRight: [1, 0], ArrowLeft: [-1, 0], ArrowDown: [0, 1], ArrowUp: [0, -1] };

/** The cell an element is drawn in: its place in the grid, by its size, and the handles that change it. `children` is
 *  handed the element's key, which only this cell knows.
 *
 *  Off the grid (a section sized by name) it spans the columns and rows its size names, as before. On the grid it spans
 *  its own w columns and h rows, and what it draws is told its box (`CellBoxContext`) so it fills it. Where the reader
 *  may resize — the dashboard's own — its handles move it one grade at a time, and so do Alt+arrows on it. */
function Cell({ type, props, size, testid, extra, children }: {
  type: ComponentName;
  props: Record<string, unknown>;
  /** The size drawn off the grid: the element's own, or — for a card that says none — what its shape asks. */
  size: Size;
  testid: string;
  extra?: { attrs?: Record<string, string | undefined>; style?: Record<string, unknown> };
  children: (key: string | null) => ReactNode;
}) {
  const { doors, selected, steppers, reads } = useDashboard();
  const { columns, grid: gridded, stacked } = useContext(SectionKeys);
  const key = useElementKey(type, props);
  // Arc AP-6 — what this cell's element read, as what it draws marks it: refused, still reading, or read cleanly
  const [marks, setMarks] = useState<Record<number, { status: ReadStatus; reason: string }>>({});
  const slot = useMemo<ReadSlot>(() => ({
    mark: (status, reason) => {
      const id = ++lastMark;
      setMarks(m => ({ ...m, [id]: { status, reason } }));
      return () => setMarks(m => { const rest = { ...m }; delete rest[id]; return rest; });
    },
  }), []);
  const readState = readStateOf(Object.values(marks));
  const onReadState = doors.onReadState;
  useEffect(() => { if (key) onReadState?.(key, readState); }, [key, readState.status, readState.reason, onReadState]); // eslint-disable-line react-hooks/exhaustive-deps -- by what it says
  useEffect(() => () => { if (key) onReadState?.(key, null); }, [key, onReadState]);
  const ref = useRef<HTMLDivElement>(null);
  const [preview, setPreview] = useState<Box | null>(null);
  const [ghostColumn, setGhostColumn] = useState(0);
  // the size-by-name corner's own preview, where the grid is not offered
  const [corner, setCorner] = useState<{ w: number; h: number } | null>(null);
  const kind = type in LIMITS ? (type as GridKind) : null;
  const own: Box | null = gridded ? { w: Number(props.w) || 1, h: Number(props.h) || 1 } : null;
  const regrid = !!doors.onRegrid && key !== null && kind !== null;
  // the size picked by name stays only where the grid is not offered, and never on a section already on the grid
  const resizable = !regrid && !gridded && !!doors.onResize && key !== null;
  const chosen = key !== null && selected === key;
  const span = SPAN[size];

  const done = (b: Box, measured: Record<string, Box>) => { if (key) doors.onRegrid?.(key, b, measured); };
  const step = (dw: number, dh: number) => {
    if (!kind || !key) return;
    const grid = ref.current?.parentElement;
    const measured = gridded || !grid ? {} : measureSection(grid);
    const from = own ?? measured[key] ?? boxOf({ type, props, children: [] }, columns);
    const next = clampBox(type, { w: from.w + dw, h: from.h + dh });
    if (next.w !== from.w || next.h !== from.h) done(next, measured);
  };
  // the builder's − and + reach this element by its key (Arc AP-1) — registered as the layout is committed, before the
  // builder reads the room again, so its readout is never a step behind
  useLayoutEffect(() => {
    if (!regrid || !key) return;
    steppers.set(key, {
      step,
      room: () => {
        const grid = ref.current?.parentElement;
        return own ?? (grid ? measureSection(grid)[key] ?? null : null) ?? boxOf({ type, props, children: [] }, columns);
      },
    });
    return () => { steppers.delete(key); };
  });

  const box: CellBox = gridded ? { onGrid: true, w: (preview ?? own ?? { w: 1 }).w, h: (preview ?? own ?? { h: 1 }).h } : OFF_GRID;
  const style: Record<string, unknown> = gridded
    ? { gridColumn: `span ${stacked ? 1 : Math.min(box.w, GRID.columns)}`, gridRow: `span ${box.h}`, minHeight: 0 }
    : { gridColumn: Math.min((corner ?? span).w, columns) > 1 ? `span ${Math.min((corner ?? span).w, columns)}` : undefined,
        gridRow: (corner ?? span).h > 1 ? `span ${(corner ?? span).h}` : undefined,
        minHeight: (corner ?? span).h > 1 ? TALL_MIN : undefined,
        boxShadow: corner ? "0 0 0 2px var(--blue3) inset" : undefined };
  // a drag's landing in blue; the builder's chosen element in the accent
  const ring = preview ? "2px solid var(--blue3)" : chosen ? "2px solid var(--accent)" : key !== null && reads.has(key) ? "2px dashed var(--accent)" : undefined;
  return (
    <div ref={ref} className="group" data-testid={testid} data-element={key ?? undefined} data-size={gridded ? undefined : size}
      data-w={gridded ? box.w : undefined} data-h={gridded ? box.h : undefined} data-selected={chosen || undefined} {...extra?.attrs}
      onPointerDownCapture={doors.onSelect && key ? () => doors.onSelect?.(key) : undefined}
      tabIndex={regrid ? 0 : undefined}
      aria-label={regrid ? "Alt and the arrow keys resize this one grade at a time" : undefined}
      onKeyDown={regrid ? e => {
        const d = e.altKey ? STEP[e.key] : undefined;
        if (!d || e.target !== e.currentTarget) return;
        e.preventDefault();
        step(d[0], d[1]);
      } : undefined}
      style={{ position: "relative", borderRadius: "var(--r3)", minWidth: 0, outline: ring, outlineOffset: 2, ...style, ...extra?.style }}>
      <ReadSlotContext.Provider value={slot}><CellBoxContext.Provider value={box}>{children(key)}</CellBoxContext.Provider></ReadSlotContext.Provider>
      {/* off the grid a drag draws where the element would land, until the section moves onto the grid on release */}
      {preview && !gridded && ghostColumn > 0 && (
        <span data-testid="grid-ghost" aria-hidden="true" style={{ position: "absolute", left: 0, top: 0, zIndex: 2, pointerEvents: "none",
          width: preview.w * ghostColumn + (preview.w - 1) * GRID.gap, height: rowsTall(preview.h),
          border: "2px dashed var(--blue3)", borderRadius: "var(--r3)" }} />
      )}
      {regrid && kind && (
        <GridHandles cell={ref} kind={kind} from={own} gridded={gridded}
          onPreview={(b, col) => { setPreview(b); setGhostColumn(col); }} onDone={done} />
      )}
      {resizable && (
        <ResizeCorner cell={ref} columns={columns} from={{ w: Math.min(span.w, columns), h: span.h }} onPreview={setCorner}
          onDone={(nw, nh) => { const s = sizeOf(nw, nh); if (s && key) doors.onResize?.(key, s); }} />
      )}
    </div>
  );
}

/** Arc AP-8 — a card of a person's own query that reads the dashboard's values: run here, with them as the page holds them
 *  now — the page that keeps the dashboard runs it without, and would only be told it holds none — again whenever one
 *  changes; or what it waits on. Every other card is as the page ran it. */
function useValuedRun(cs: CardState | undefined, range: BriefingRange | null | undefined): {
  cs: CardState | undefined; waits: QueryWaiting | null; onRefresh: (() => void) | null;
} {
  const { valueOf, wire } = usePieces();
  const names = valuesRead(cs?.card.sql);
  const now = names.length ? valuesFor(names, wire.values, valueOf) : null;
  const sent = now && "values" in now ? JSON.stringify(now.values) : "";
  const [tick, setTick] = useState(0);
  const refresh = useCallback(() => setTick(t => t + 1), []);
  const key = cs && sent ? `${cs.card.id}|${sent}|${JSON.stringify(range ?? null)}|${tick}` : "";
  const [got, setGot] = useState<{ key: string; run?: CardRunResult; failed?: boolean } | null>(null);
  useEffect(() => {
    if (!key || !cs) return;
    let alive = true;
    runCard(cs.card.id, range, { values: JSON.parse(sent) as ValuesSent })
      .then(run => { if (alive) setGot({ key, run }); })
      .catch(() => { if (alive) setGot({ key, failed: true }); });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- keyed on what it is sent
  }, [key]);
  if (!cs || !now) return { cs, waits: null, onRefresh: null };
  const onRefresh = refresh;
  const card = cs.card;
  if ("refused" in now) {
    const run = { columns: [], rows: [], row_count: 0, caveats: [], error: now.refused, value: null, refresh: card.refresh, shown: null } as CardRunResult;
    return { cs: { card, run }, waits: null, onRefresh };
  }
  if ("waiting" in now) return { cs: { card }, waits: { waiting: <>{chooseWords(wire, now.waiting)} — this reads {now.label} from it.</> }, onRefresh };
  if ("reading" in now || !got || got.key !== key) return { cs: { card }, waits: { reading: true }, onRefresh };
  return { cs: { card, run: got.run, failed: got.failed }, waits: null, onRefresh };
}

function DashboardCard({ element }: ComponentRenderProps<{ card: string; tone?: Tone | null; size?: Size | null }>) {
  const { cards, host, tileDoors, sym, range, schema } = useDashboard();
  const id = element.props.card;
  const tone = element.props.tone ?? null;
  const valued = useValuedRun(cards.get(id), range);
  const cs = valued.cs;
  const own = valued.onRefresh;
  const doors = useMemo(() => (own ? { ...tileDoors, onRefresh: own } : tileDoors), [tileDoors, own]);
  const status = host.cards[id]?.status ?? "unmeasured";
  // A card that says no size takes what its shape asks, as it did before sizes: a chart or a
  // table two columns, a figure one.
  const size: Size = element.props.size ?? (!!cs && WIDE[tileShape(cs)] ? "wide" : "small");
  // a saved card is a fixed query: the reader's filters cannot narrow it, and it says so while one is on
  const filtering = useFiltering();
  return (
    <Cell type="Card" props={element.props as Record<string, unknown>} size={size} testid="dashboard-card"
      extra={{ attrs: { "data-card": id, "data-tone": tone ?? undefined },
        style: { boxShadow: tone ? `inset 3px 0 0 ${TONE_RULE[tone]}` : undefined, paddingLeft: tone ? 3 : 0 } }}>
      {key => <>{filtering.on && <NotFiltered />}{status === "withheld"
        ? <WithheldTile />
        : !cs
          ? <SaidTile what="Not one of your cards">The dashboard places a card you do not have.</SaidTile>
          : (
            <CardBoundary key={`${id}:${cs.run ? JSON.stringify(cs.run.rows).length : 0}:${cs.failed ? 1 : 0}`}>
              <DashboardTile cs={cs as CardState & { card: DashboardCard }} status={status} sym={sym} doors={doors}
                place={{ elementKey: key, size, range, schema }} waits={valued.waits} />
            </CardBoundary>
          )}</>}
    </Cell>
  );
}

function DashboardNote({ element }: ComponentRenderProps<{ text: string; size?: Size | null; author?: string; written_at?: string }>) {
  const { tileDoors: doors } = useDashboard();
  const own = !!(doors.onTakeOff || doors.onEditNote || doors.onResize);
  return (
    <Cell type="Note" props={element.props as Record<string, unknown>} size={element.props.size ?? "small"} testid="dashboard-note-cell">
      {key => (
        <NoteTile elementKey={own ? key : null} text={element.props.text} author={element.props.author}
          writtenAt={element.props.written_at} size={element.props.size ?? "small"} doors={doors} />
      )}
    </Cell>
  );
}

/** PENDING 54 — a question the agent answers on its rhythm. The dashboard reads the answers kept and never asks. */
function DashboardQuestion({ element }: ComponentRenderProps<{ automation: string; first?: string; size?: Size | null }>) {
  const { connectionId } = useDashboard();
  return (
    <Cell type="Question" props={element.props as Record<string, unknown>} size={element.props.size ?? "wide"} testid="dashboard-question-cell"
      extra={{ attrs: { "data-automation": element.props.automation } }}>
      {() => <QuestionPiece automation={element.props.automation} first={element.props.first} connectionId={connectionId} />}
    </Cell>
  );
}

function DashboardImage({ element }: ComponentRenderProps<{ object: string; caption: string; size?: Size | null }>) {
  const { tileDoors: doors, images } = useDashboard();
  const own = !!(doors.onTakeOff || doors.onRecaption || doors.onResize);
  return (
    <Cell type="Image" props={element.props as Record<string, unknown>} size={element.props.size ?? "small"} testid="dashboard-image-cell"
      extra={{ attrs: { "data-object": element.props.object } }}>
      {key => (
        <ImageTile elementKey={own ? key : null} caption={element.props.caption} stamp={images[element.props.object]}
          size={element.props.size ?? "small"} doors={doors} />
      )}
    </Cell>
  );
}

// ── Arc OC-4 — the pieces bound to the ontology ─────────────────────────────────────────────
// Each is drawn in a cell like any element; what it reads is `OntologyPieces`'. Left out, a board or a table takes
// the room its rows ask for, and a detail one column.

function DashboardProcessBoard({ element }: ComponentRenderProps<{ process: string; size?: Size | null }>) {
  const filtering = useFiltering();
  return (
    <Cell type="ProcessBoard" props={element.props as Record<string, unknown>} size={element.props.size ?? "full"} testid="dashboard-piece-cell">
      {() => <>{filtering.on && <NotFiltered />}<ProcessBoardPiece process={element.props.process} /></>}
    </Cell>
  );
}

function DashboardObjectTable({ element }: ComponentRenderProps<{
  entity?: string | null; segment?: string | null; columns?: string[] | null; sort?: string | null; descending?: boolean | null;
  size?: Size | null; set?: string | null; set_from?: string | null; chooses?: string | null; ticks?: string | null;
}>) {
  const p = element.props;
  const size = p.size ?? "wide";
  const filtering = usePieceFiltering(p as Record<string, unknown>);
  return (
    <Cell type="ObjectTable" props={p as Record<string, unknown>} size={size} testid="dashboard-piece-cell">
      {key => (<>
        {filtering.on && !filtering.narrows && <NotFiltered />}
        <ObjectTablePiece elementKey={key} entity={p.entity} segment={p.segment} set={p.set} setFrom={p.set_from}
          chooses={p.chooses} ticks={p.ticks} columns={p.columns} sort={p.sort} descending={p.descending}
          tall={SPAN[size].h === 2} />
      </>)}
    </Cell>
  );
}

function DashboardObjectDetail({ element, children }: ComponentRenderProps<{ follows: string; size?: Size | null }>) {
  return (
    <Cell type="ObjectDetail" props={element.props as Record<string, unknown>} size={element.props.size ?? "small"} testid="dashboard-piece-cell">
      {() => <ObjectDetailPiece follows={element.props.follows}>{children}</ObjectDetailPiece>}
    </Cell>
  );
}

function DashboardActionButton({ element }: ComponentRenderProps<{ action: string }>) {
  return <ActionButtonPiece action={element.props.action} />;
}

// ── a dashboard started from an object (2026-10-10) ─────────────────────────────────────────────────
// The filter column is drawn by the root, beside the rest; a figure and a chart are drawn in cells like any piece.

function DashboardObjectFilters({ element }: ComponentRenderProps<{ entity: string; properties: FilterProperty[]; set?: string | null }>) {
  return <ObjectFiltersPiece entity={element.props.entity} properties={element.props.properties} set={element.props.set} />;
}

function DashboardObjectFigure({ element }: ComponentRenderProps<{
  entity?: string | null; label: string; agg: string; path?: string | null; format?: string | null; size?: Size | null;
  set?: string | null; of?: string | null; shows?: string | null;
}>) {
  const { sym } = useDashboard();
  const p = element.props;
  const filtering = usePieceFiltering(p as Record<string, unknown>);
  return (
    <Cell type="ObjectFigure" props={p as Record<string, unknown>} size={p.size ?? "small"} testid="dashboard-piece-cell">
      {() => <>{filtering.on && !filtering.narrows && <NotFiltered />}
        <ObjectFigurePiece entity={p.entity} set={p.set} of={p.of} shows={p.shows} label={p.label} agg={p.agg}
          path={p.path} format={p.format} sym={sym} /></>}
    </Cell>
  );
}

function DashboardObjectBreakdown({ element }: ComponentRenderProps<{
  entity?: string | null; set?: string | null; label: string; by: string; size?: Size | null;
  measures: { agg: string; path?: string | null; label?: string | null; format?: string | null }[];
  top?: number | null; show?: string | null;
}>) {
  const { sym } = useDashboard();
  const p = element.props;
  const filtering = usePieceFiltering(p as Record<string, unknown>);
  return (
    <Cell type="ObjectBreakdown" props={p as Record<string, unknown>} size={p.size ?? "wide"} testid="dashboard-piece-cell">
      {() => <>{filtering.on && !filtering.narrows && <NotFiltered />}
        <ObjectBreakdownPiece entity={p.entity} set={p.set} label={p.label} by={p.by} measures={p.measures} top={p.top}
          show={p.show} sym={sym} /></>}
    </Cell>
  );
}

function DashboardObjectChart({ element }: ComponentRenderProps<{
  entity?: string | null; label: string; time: string; days?: number | null; size?: Size | null;
  agg?: string | null; path?: string | null; format?: string | null; split?: string | null; top?: number | null; set?: string | null;
}>) {
  const { sym } = useDashboard();
  const p = element.props;
  const filtering = usePieceFiltering(p as Record<string, unknown>);
  return (
    <Cell type="ObjectChart" props={p as Record<string, unknown>} size={p.size ?? "full"} testid="dashboard-piece-cell">
      {() => <>{filtering.on && !filtering.narrows && <NotFiltered />}
        <ObjectChartPiece entity={p.entity} set={p.set} label={p.label} time={p.time} days={p.days ?? 30} agg={p.agg} path={p.path}
          format={p.format} split={p.split} top={p.top} sym={sym} /></>}
    </Cell>
  );
}

// ── Arc AP-3 — buttons that run declared actions on what a reader chose or ticked ─────────────────────────────────

function DashboardActionButtons({ element }: ComponentRenderProps<{ buttons: ActionButtonDef[]; size?: Size | null }>) {
  return (
    <Cell type="ActionButtons" props={element.props as Record<string, unknown>} size={element.props.size ?? "small"} testid="dashboard-piece-cell">
      {() => <ActionButtonsPiece buttons={element.props.buttons} />}
    </Cell>
  );
}

// ── Arc AP-4 — the pieces the picker adds: each reads an entity or a set as a table does, narrowed by the filters ──────

type SetProps = { entity?: string | null; set?: string | null; set_from?: string | null; chooses?: string | null; size?: Size | null };

function DashboardObjectList({ element }: ComponentRenderProps<SetProps & {
  ticks?: string | null; title: string; figure?: string | null; mark?: string | null; sort?: string | null; descending?: boolean | null;
}>) {
  const p = element.props;
  const filtering = usePieceFiltering(p as Record<string, unknown>);
  return (
    <Cell type="ObjectList" props={p as Record<string, unknown>} size={p.size ?? "tall"} testid="dashboard-piece-cell">
      {key => <>{filtering.on && !filtering.narrows && <NotFiltered />}
        <ObjectListPiece elementKey={key} entity={p.entity} set={p.set} setFrom={p.set_from} chooses={p.chooses} ticks={p.ticks}
          title={p.title} figure={p.figure} mark={p.mark} sort={p.sort} descending={p.descending} /></>}
    </Cell>
  );
}

function DashboardObjectMap({ element }: ComponentRenderProps<SetProps & { lat: string; lng: string; label?: string | null }>) {
  const p = element.props;
  const filtering = usePieceFiltering(p as Record<string, unknown>);
  return (
    <Cell type="ObjectMap" props={p as Record<string, unknown>} size={p.size ?? "large"} testid="dashboard-piece-cell">
      {key => <>{filtering.on && !filtering.narrows && <NotFiltered />}
        <ObjectMapPiece elementKey={key} entity={p.entity} set={p.set} setFrom={p.set_from} chooses={p.chooses} lat={p.lat} lng={p.lng} label={p.label} /></>}
    </Cell>
  );
}

function DashboardObjectTimeline({ element }: ComponentRenderProps<SetProps & { start: string; end: string; label: string }>) {
  const p = element.props;
  const filtering = usePieceFiltering(p as Record<string, unknown>);
  return (
    <Cell type="ObjectTimeline" props={p as Record<string, unknown>} size={p.size ?? "full"} testid="dashboard-piece-cell">
      {key => <>{filtering.on && !filtering.narrows && <NotFiltered />}
        <ObjectTimelinePiece elementKey={key} entity={p.entity} set={p.set} setFrom={p.set_from} chooses={p.chooses}
          start={p.start} end={p.end} label={p.label} /></>}
    </Cell>
  );
}

function DashboardChooseOne({ element }: ComponentRenderProps<{ entity?: string | null; set?: string | null; chooses: string; label: string; size?: Size | null }>) {
  const p = element.props;
  return (
    <Cell type="ChooseOne" props={p as Record<string, unknown>} size={p.size ?? "small"} testid="dashboard-piece-cell">
      {() => <ChooseOnePiece entity={p.entity} set={p.set} chooses={p.chooses} label={p.label} />}
    </Cell>
  );
}

function DashboardObjectSearch({ element }: ComponentRenderProps<{ entity: string; path: string; label: string; size?: Size | null }>) {
  const p = element.props;
  return (
    <Cell type="ObjectSearch" props={p as Record<string, unknown>} size={p.size ?? "small"} testid="dashboard-piece-cell">
      {() => <ObjectSearchPiece entity={p.entity} path={p.path} label={p.label} />}
    </Cell>
  );
}

// ── Arc AP-4 — a drawer: pieces opened beside the page when a reader chooses an object ───────────────────────────────

function DashboardDrawer({ element, children }: ComponentRenderProps<{ title: string; opens_on: string }>) {
  const ctx = useDashboard();
  const { doors, elements } = ctx;
  const { picked, pick, followable } = usePieces();
  const key = useMemo(() => Object.keys(elements).find(k => elements[k]?.type === "Drawer" && elements[k]?.children === element.children)
    ?? Object.keys(elements).find(k => elements[k]?.type === "Drawer" && sameList(elements[k]?.children, element.children ?? [])
      && elements[k]?.props?.opens_on === element.props.opens_on) ?? null, [elements, element.children, element.props.opens_on]);
  const outlined = useChosenOutline(key);
  const lands = followable.get(element.props.opens_on) ?? element.props.opens_on;
  const close = useCallback(() => pick(lands, null), [pick, lands]);
  const editing = !!doors.onSelect;
  const held = useMemo(() => element.children ?? [], [element.children]);
  const open = !editing && !!picked[lands] && held.length > 0;
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") close(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, close]);
  // what a drawer holds stacks one piece under another: it is resized on no grid and by no name
  const inner = useMemo<DashboardContextValue>(() => ({ ...ctx, doors: { ...ctx.doors, onRegrid: undefined, onResize: undefined },
    tileDoors: { ...ctx.tileDoors, onResize: undefined } }), [ctx]);
  const keys = useMemo(() => ({ key, columns: 1, children: held, grid: false, stacked: true }), [key, held]);
  const body = (
    <DashboardContext.Provider value={inner}>
      <SectionKeys.Provider value={keys}>{children}</SectionKeys.Provider>
    </DashboardContext.Provider>
  );
  if (editing) {
    // in the builder a drawer is drawn open, after the page, so a person sees and places what it holds
    return (
      <section data-testid="dashboard-drawer" data-key={key ?? undefined} data-editing="true" aria-label={element.props.title} {...outlined}
        style={{ ...outlined.style, display: "flex", flexDirection: "column", gap: 10, padding: 12, border: "1.5px dashed var(--b2)" }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
          <span className="aug-fs-sm" style={{ color: "var(--t1)", fontWeight: 600 }}>{element.props.title}</span>
          <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>A drawer — opens beside the page when “{element.props.opens_on.replace(/-/g, " ")}” is chosen</span>
        </div>
        {held.length > 0 && body}
        {doors.onAddPiece && key && (
          <Button size="sm" variant="outline" data-testid="drawer-add" onClick={() => doors.onAddPiece?.(key)} style={{ alignSelf: "flex-start" }}>
            <Icon name="plus" size={13} /> Add a piece
          </Button>
        )}
      </section>
    );
  }
  if (!open) return null;
  return (
    <aside role="dialog" aria-label={element.props.title} data-testid="dashboard-drawer" data-key={key ?? undefined}
      style={{ position: "fixed", top: "var(--topbar)", right: 0, bottom: 0, width: "min(460px, 100vw)", zIndex: 40, display: "flex", flexDirection: "column",
        background: "var(--bg-1)", borderLeft: "1px solid var(--b1)", boxShadow: "var(--shadow-lg)" }}>
      <header style={{ display: "flex", alignItems: "center", gap: 8, padding: "12px 16px", borderBottom: "1px solid var(--b1)" }}>
        <span className="aug-fs-ui" style={{ flex: 1, minWidth: 0, color: "var(--t1)", fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {element.props.title}
        </span>
        <Button size="icon-xs" variant="ghost" aria-label="Close the drawer" data-testid="dashboard-drawer-close" onClick={close}><Icon name="close" /></Button>
      </header>
      <div style={{ flex: 1, minHeight: 0, overflow: "auto", padding: 16, display: "flex", flexDirection: "column", gap: 12 }}>{body}</div>
    </aside>
  );
}

/** One renderer per catalog component — a missing or an extra name is a type error. */
const REGISTRY = {
  Cockpit: DashboardRoot,
  Tabs: DashboardTabs,
  Tab: DashboardTab,
  Section: DashboardSection,
  Card: DashboardCard,
  Note: DashboardNote,
  Image: DashboardImage,
  ProcessBoard: DashboardProcessBoard,
  ObjectTable: DashboardObjectTable,
  ObjectDetail: DashboardObjectDetail,
  ActionButton: DashboardActionButton,
  ObjectFilters: DashboardObjectFilters,
  ObjectFigure: DashboardObjectFigure,
  ObjectChart: DashboardObjectChart,
  ObjectBreakdown: DashboardObjectBreakdown,
  ActionButtons: DashboardActionButtons,
  ObjectList: DashboardObjectList,
  ObjectMap: DashboardObjectMap,
  ObjectTimeline: DashboardObjectTimeline,
  ChooseOne: DashboardChooseOne,
  ObjectSearch: DashboardObjectSearch,
  Drawer: DashboardDrawer,
  Question: DashboardQuestion,
} satisfies Record<ComponentName, unknown>;

const NO_IMAGES: Record<string, ImageStamp> = {};
const NO_READS: readonly string[] = [];

export function ComposedDashboard({ spec, cards, host, doors, sym = "$", images = NO_IMAGES, range = null, schema, connectionId, dashboardId,
  selected = null, handle, reads = NO_READS, asGroup, onSaid }: {
  spec: unknown;
  cards: CardState[];
  host: DashboardHostState;
  doors: DashboardDoors;
  /** The symbol a money figure is written with (`currency_symbol` from the dashboard's read). */
  sym?: string;
  /** What the dashboard's read says of each image it places, by object id. */
  images?: Record<string, ImageStamp>;
  /** The range the dashboard is read for; a bigger figure shows its metric's trend over it. */
  range?: BriefingRange | null;
  schema?: string;
  /** The connection the ontology's pieces read (Arc OC-4). */
  connectionId?: string;
  /** The dashboard drawn: a reader's filters are remembered under it, in their browser. */
  dashboardId?: string;
  /** Arc AP-1 — the element chosen in the builder, outlined where it is drawn. */
  selected?: string | null;
  /** Arc AP-1 — filled with what the builder may ask of the elements drawn. */
  handle?: Ref<DashboardHandle>;
  /** Arc AP-2 — the elements that read what the builder has chosen in its Data tab. */
  reads?: readonly string[];
  /** Arc AP-6 — the group the dashboard is previewed as: every object read as the person and a member of it. */
  asGroup?: string;
  /** Arc AP-6 — each line the object door said beside a read (what a row policy withholds), once. */
  onSaid?: (line: string) => void;
}) {
  // A spec is known by what it says, not by which object says it: a caller that parses the
  // same JSON again on every render hands over a new object each time, and that must not
  // close the tab a reader opened.
  const written = useMemo(() => JSON.stringify(spec) ?? "", [spec]);
  // eslint-disable-next-line react-hooks/exhaustive-deps -- keyed on what the spec says
  const check = useMemo(() => checkDashboardSpec(spec), [written]);

  // One store per spec. The host's tree is laid over it on every change, so a spec can seed
  // the open tab and nothing else, and a reader's choice of tab survives a refresh of the cards.
  const store = useMemo(
    () => createStateStore(stateModel(openingTab(spec), host)),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the host is laid over below, not at creation
    [written],
  );
  useEffect(() => {
    store.update({ "/range": { status: host.range.status }, "/cards": host.cards });
  }, [store, host]);

  const rangeKey = JSON.stringify(range ?? null);
  // the pieces a set chosen in the builder's Data tab is read by (Arc AP-2), as one key: a new array each render is not news
  const readsKey = reads.join("\n");
  const steppers = useMemo(() => new Map<string, Stepper>(), []);
  useImperativeHandle(handle, () => ({
    room: key => steppers.get(key)?.room() ?? null,
    step: (key, dw, dh) => steppers.get(key)?.step(dw, dh),
  }), [steppers]);
  // Arc AP-8c — a value read from a query of the dashboard's own reads a card the dashboard places
  const cardSql = useCallback((card: string) => {
    const found = cards.find(c => c.card.id === card);
    return found ? found.card.sql ?? "" : undefined;
  }, [cards]);
  const context = useMemo<DashboardContextValue>(() => ({
    elements: check.valid ? (spec as Spec).elements : {},
    cards: new Map(cards.map(c => [c.card.id, c])),
    host,
    doors,
    tileDoors: doors.onRegrid ? { ...doors, onResize: undefined } : doors,
    sym,
    images,
    range,
    schema,
    connectionId,
    selected,
    steppers,
    reads: new Set(readsKey ? readsKey.split("\n") : []),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- keyed on what the spec and the range say
  }), [check.valid, written, cards, host, doors, sym, images, rangeKey, schema, connectionId, selected, steppers, readsKey]);

  if (!check.valid) {
    return (
      <Refusal
        kind="Refused · the dashboard's spec"
        claim="This dashboard is not drawn, because its spec breaks the rules a dashboard is held to."
        detail={
          <ul data-testid="dashboard-refusal" style={{ margin: 0, paddingLeft: 18 }}>
            {check.issues.map((issue, i) => <li key={`${issue.code}-${issue.elementKey ?? ""}-${i}`}>{issue.message}</li>)}
          </ul>
        }
      />
    );
  }

  return (
    <DashboardContext.Provider value={context}>
      <PiecesProvider connectionId={connectionId} schema={schema} elements={context.elements} onPlaceTable={doors.onPlaceTable}
        asGroup={asGroup} onSaid={onSaid}
        sets={check.valid ? (spec as WireSpec).sets : undefined} values={check.valid ? (spec as WireSpec).values : undefined}
        dashboardId={dashboardId} cardSql={cardSql}>
        <JSONUIProvider registry={REGISTRY as ComponentRegistry} store={store}>
          <Renderer spec={spec as Spec} registry={REGISTRY as ComponentRegistry} />
        </JSONUIProvider>
      </PiecesProvider>
    </DashboardContext.Provider>
  );
}
