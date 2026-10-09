"use client";

/**
 * ComposedCockpit — a cockpit drawn from a spec (Arc CT, CT-1 and CT-2; ROADMAP §3.50; the
 * canvas, docs/COCKPIT_CANVAS_2026-10-08.md).
 *
 * The law of the arc: the spec arranges, the card store measures. This component draws tabs
 * and sections from the spec, and hands every card to `CockpitTile`, which draws the card's own
 * run at its metric's unit — nothing about what a card measures is decided in this file. (Until
 * the user's "make the cockpit look like the mockup", 2026-09-28, a card was drawn with the
 * Briefing's `PinnedCardBody` unchanged; the face changed, the law did not.)
 *
 * Since the canvas a section also holds a person's own Note and Image, drawn by `StaticTile`,
 * and every element has a size from the catalog's closed set: a column span cut to what the
 * section has, and a row span. The size changes the room, never the measurement. A person
 * resizes by the corner of a tile or by its size pick; either lands as one kept version through
 * `doors.onResize`, and a cockpit the reader may not change offers neither.
 *
 * Three things it will not do:
 *   - draw a spec the rules refuse. It says why instead, in the rules' own sentences.
 *   - let a condition read anything the host did not publish. The state a cockpit renders
 *     against is the open tab plus the host's tree, laid over whatever the spec seeded.
 *   - hide a card without saying so. A section counts the cards waiting on a condition, a
 *     card the reader may not see stays where it is and says it is withheld, and a card
 *     that fails to draw says that too. The library wraps every element in an error
 *     boundary of its own that draws NOTHING when a component throws; the boundary here
 *     sits inside it, so the library's never gets the chance.
 *
 * The Briefing draws a person's cockpits with it (`BriefingCockpits`), behind `cockpit.composed`.
 */
import {
  Component, createContext, useContext, useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent,
  type ReactNode, type RefObject,
} from "react";
import { evaluateVisibility, type Spec, type VisibilityCondition } from "@json-render/core";
import {
  JSONUIProvider, Renderer, createStateStore, useBoundProp, useStateStore,
  type ComponentRegistry, type ComponentRenderProps,
} from "@json-render/react";

import type { CardState } from "@/components/brief/PinnedCardBody";
import { CockpitTile, SaidTile, WIDE, WithheldTile, tileShape, type TileDoors } from "@/components/cockpit/CockpitTile";
import {
  ActionButtonPiece, ObjectDetailPiece, ObjectTablePiece, PiecesProvider, ProcessBoardPiece,
} from "@/components/cockpit/OntologyPieces";
import { ImageTile, NoteTile, type ImageStamp, type StaticDoors } from "@/components/cockpit/StaticTile";
import { Icon } from "@/components/ui/icon";
import { Refusal } from "@/components/ui/states";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { BriefingRange, CockpitCard } from "@/lib/api";
import { SPAN, sizeOf, type ComponentName, type Size, type Tone } from "@/lib/cockpit/catalog";
import { stateModel, type CockpitHostState } from "@/lib/cockpit/hostState";
import { checkCockpitSpec, openingTab } from "@/lib/cockpit/rules";

/** What a cockpit may ask of the page that holds it. The static doors and `onResize` are absent
 *  on a cockpit the reader may not change — a published one, a strip. */
export interface CockpitDoors extends TileDoors, StaticDoors {
  /** Arc OC-4 — place a table of a segment, from a process board's open-and-overdue count. */
  onPlaceTable?: (entity: string, segment: string) => void;
}

interface CockpitContextValue {
  elements: Spec["elements"];
  cards: Map<string, CardState>;
  host: CockpitHostState;
  doors: CockpitDoors;
  sym: string;
  images: Record<string, ImageStamp>;
  range: BriefingRange | null;
  schema?: string;
}

const CockpitContext = createContext<CockpitContextValue | null>(null);

/** The section an element is drawn in: its key, how many columns it draws, and the keys it
 *  holds in order. The renderer hands a component its element and not its key, so the key of
 *  what is drawn is found here, among the section's children, by what the element says. */
const SectionKeys = createContext<{ key: string | null; columns: number; children: string[] }>({ key: null, columns: 1, children: [] });

function useCockpit(): CockpitContextValue {
  const ctx = useContext(CockpitContext);
  if (!ctx) throw new Error("a cockpit component was drawn outside ComposedCockpit");
  return ctx;
}

function sameList(a: unknown, b: unknown): boolean {
  return Array.isArray(a) && Array.isArray(b) && a.length === b.length && a.every((v, i) => v === b[i]);
}

/** The key of the element being drawn. Two elements that say exactly the same thing in one
 *  section are one thing to a reader, and the first is it. */
function useElementKey(type: ComponentName, props: unknown): string | null {
  const { elements } = useCockpit();
  const { children } = useContext(SectionKeys);
  const said = JSON.stringify(props);
  return children.find(k => elements[k]?.type === type && JSON.stringify(elements[k]?.props) === said) ?? null;
}

/** The rule down a card's left edge. A tone is emphasis; it never replaces the card's own frame. */
const TONE_RULE: Record<Tone, string> = {
  good: "var(--grn3)", warn: "var(--amb3)", bad: "var(--red3)", info: "var(--blue3)", neutral: "var(--b2)",
};

function CockpitRoot({ element, children }: ComponentRenderProps<{ title: string }>) {
  // The title names the cockpit for a screen reader and for the history. It is not drawn as a
  // header: the strip of cockpits above it already carries the name, and a panel does not
  // repeat its own title.
  return <div role="region" aria-label={element.props.title} data-testid="cockpit">{children}</div>;
}

function CockpitTabs({ element, children, bindings }: ComponentRenderProps<{ value: string }>) {
  const { elements } = useCockpit();
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
  const { elements } = useCockpit();
  const { state } = useStateStore();
  return (children ?? []).filter(key => {
    const cond = elements[key]?.visible as VisibilityCondition | undefined;
    return cond !== undefined && !evaluateVisibility(cond, { stateModel: state });
  }).length;
}

function CockpitTab({ element, children }: ComponentRenderProps<{ name: string; label: string }>) {
  const waiting = useWaiting(element.children);
  return (
    <TabsContent value={element.props.name}>
      {children}
      {waiting > 0 && (
        <div className="aug-fs-sm" data-testid="cockpit-waiting-sections" style={{ color: "var(--t3)", marginTop: 16, display: "flex", alignItems: "center", gap: 6 }}>
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

/** How many columns a section draws: the spec's, when it says, never more than fit. Width 0 is
 *  a section not yet measured (or a test's DOM), and draws as asked. */
function useColumns(asked: number | null | undefined): [RefObject<HTMLDivElement | null>, number] {
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
  return [ref, Math.min(asked ?? MAX_AUTO_COLUMNS, fit)];
}

function CockpitSection({ element, children }: ComponentRenderProps<{ title: string; columns?: number | null }>) {
  const { elements } = useCockpit();
  const waiting = useWaiting(element.children);
  const [ref, columns] = useColumns(element.props.columns);
  const held = element.children ?? [];
  // A section's children are its own — each element is held by exactly one — so the list names it.
  const key = useMemo(
    () => Object.keys(elements).find(k => elements[k]?.type === "Section" && sameList(elements[k]?.children, held)) ?? null,
    [elements, held]);
  const keys = useMemo(() => ({ key, columns, children: held }), [key, columns, held]);
  return (
    <section data-testid="cockpit-section" style={{ marginTop: 20 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 12, marginBottom: 10 }}>
        <div className="aug-fs-h2" style={{ fontWeight: 600, color: "var(--t1)" }}>{element.props.title}</div>
        {waiting > 0 && (
          <div className="aug-fs-sm" data-testid="cockpit-waiting" style={{ color: "var(--t3)", display: "flex", alignItems: "center", gap: 6 }}>
            <Icon name="eyeoff" size={13} />
            {waiting === 1 ? "1 card waits on a condition" : `${waiting} cards wait on a condition`}
          </div>
        )}
      </div>
      <div ref={ref} data-columns={columns} style={{
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

/** The cell an element is drawn in: its place in the grid, by its size, and the corner that
 *  changes it. `children` is handed the element's key, which only this cell knows. */
function Cell({ type, props, size, testid, extra, children }: {
  type: ComponentName;
  props: Record<string, unknown>;
  /** The size drawn: the element's own, or — for a card that says none — what its shape asks. */
  size: Size;
  testid: string;
  extra?: { attrs?: Record<string, string | undefined>; style?: Record<string, unknown> };
  children: (key: string | null) => ReactNode;
}) {
  const { doors } = useCockpit();
  const { columns } = useContext(SectionKeys);
  const key = useElementKey(type, props);
  const ref = useRef<HTMLDivElement>(null);
  const [preview, setPreview] = useState<{ w: number; h: number } | null>(null);
  const span = preview ?? SPAN[size];
  const w = Math.min(span.w, columns), h = span.h;
  const resizable = !!doors.onResize && key !== null;
  return (
    <div ref={ref} className="group" data-testid={testid} data-element={key ?? undefined} data-size={size} {...extra?.attrs} style={{
      position: "relative", borderRadius: "var(--r3)", minWidth: 0,
      gridColumn: w > 1 ? `span ${w}` : undefined,
      gridRow: h > 1 ? `span ${h}` : undefined,
      minHeight: h > 1 ? TALL_MIN : undefined,
      boxShadow: preview ? "0 0 0 2px var(--blue3) inset" : undefined,
      ...extra?.style,
    }}>
      {children(key)}
      {resizable && (
        <ResizeCorner cell={ref} columns={columns} from={{ w: Math.min(SPAN[size].w, columns), h: SPAN[size].h }} onPreview={setPreview}
          onDone={(nw, nh) => { const s = sizeOf(nw, nh); if (s && key) doors.onResize?.(key, s); }} />
      )}
    </div>
  );
}

function CockpitCard({ element }: ComponentRenderProps<{ card: string; tone?: Tone | null; size?: Size | null }>) {
  const { cards, host, doors, sym, range, schema } = useCockpit();
  const id = element.props.card;
  const tone = element.props.tone ?? null;
  const cs = cards.get(id);
  const status = host.cards[id]?.status ?? "unmeasured";
  // A card that says no size takes what its shape asks, as it did before sizes: a chart or a
  // table two columns, a figure one.
  const size: Size = element.props.size ?? (!!cs && WIDE[tileShape(cs)] ? "wide" : "small");
  return (
    <Cell type="Card" props={element.props as Record<string, unknown>} size={size} testid="cockpit-card"
      extra={{ attrs: { "data-card": id, "data-tone": tone ?? undefined },
        style: { boxShadow: tone ? `inset 3px 0 0 ${TONE_RULE[tone]}` : undefined, paddingLeft: tone ? 3 : 0 } }}>
      {key => status === "withheld"
        ? <WithheldTile />
        : !cs
          ? <SaidTile what="Not one of your cards">The cockpit places a card you do not have.</SaidTile>
          : (
            <CardBoundary key={`${id}:${cs.run ? JSON.stringify(cs.run.rows).length : 0}:${cs.failed ? 1 : 0}`}>
              <CockpitTile cs={cs as CardState & { card: CockpitCard }} status={status} sym={sym} doors={doors}
                place={{ elementKey: key, size, range, schema }} />
            </CardBoundary>
          )}
    </Cell>
  );
}

function CockpitNote({ element }: ComponentRenderProps<{ text: string; size?: Size | null; author?: string; written_at?: string }>) {
  const { doors } = useCockpit();
  const own = !!(doors.onTakeOff || doors.onEditNote || doors.onResize);
  return (
    <Cell type="Note" props={element.props as Record<string, unknown>} size={element.props.size ?? "small"} testid="cockpit-note-cell">
      {key => (
        <NoteTile elementKey={own ? key : null} text={element.props.text} author={element.props.author}
          writtenAt={element.props.written_at} size={element.props.size ?? "small"} doors={doors} />
      )}
    </Cell>
  );
}

function CockpitImage({ element }: ComponentRenderProps<{ object: string; caption: string; size?: Size | null }>) {
  const { doors, images } = useCockpit();
  const own = !!(doors.onTakeOff || doors.onRecaption || doors.onResize);
  return (
    <Cell type="Image" props={element.props as Record<string, unknown>} size={element.props.size ?? "small"} testid="cockpit-image-cell"
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

function CockpitProcessBoard({ element }: ComponentRenderProps<{ process: string; size?: Size | null }>) {
  return (
    <Cell type="ProcessBoard" props={element.props as Record<string, unknown>} size={element.props.size ?? "full"} testid="cockpit-piece-cell">
      {() => <ProcessBoardPiece process={element.props.process} />}
    </Cell>
  );
}

function CockpitObjectTable({ element }: ComponentRenderProps<{
  entity: string; segment?: string | null; columns?: string[] | null; sort?: string | null; descending?: boolean | null;
  size?: Size | null;
}>) {
  const size = element.props.size ?? "wide";
  return (
    <Cell type="ObjectTable" props={element.props as Record<string, unknown>} size={size} testid="cockpit-piece-cell">
      {key => (
        <ObjectTablePiece elementKey={key} entity={element.props.entity} segment={element.props.segment}
          columns={element.props.columns} sort={element.props.sort} descending={element.props.descending}
          tall={SPAN[size].h === 2} />
      )}
    </Cell>
  );
}

function CockpitObjectDetail({ element, children }: ComponentRenderProps<{ follows: string; size?: Size | null }>) {
  return (
    <Cell type="ObjectDetail" props={element.props as Record<string, unknown>} size={element.props.size ?? "small"} testid="cockpit-piece-cell">
      {() => <ObjectDetailPiece follows={element.props.follows}>{children}</ObjectDetailPiece>}
    </Cell>
  );
}

function CockpitActionButton({ element }: ComponentRenderProps<{ action: string }>) {
  return <ActionButtonPiece action={element.props.action} />;
}

/** One renderer per catalog component — a missing or an extra name is a type error. */
const REGISTRY = {
  Cockpit: CockpitRoot,
  Tabs: CockpitTabs,
  Tab: CockpitTab,
  Section: CockpitSection,
  Card: CockpitCard,
  Note: CockpitNote,
  Image: CockpitImage,
  ProcessBoard: CockpitProcessBoard,
  ObjectTable: CockpitObjectTable,
  ObjectDetail: CockpitObjectDetail,
  ActionButton: CockpitActionButton,
} satisfies Record<ComponentName, unknown>;

const NO_IMAGES: Record<string, ImageStamp> = {};

export function ComposedCockpit({ spec, cards, host, doors, sym = "$", images = NO_IMAGES, range = null, schema, connectionId }: {
  spec: unknown;
  cards: CardState[];
  host: CockpitHostState;
  doors: CockpitDoors;
  /** The symbol a money figure is written with (`currency_symbol` from the cockpit's read). */
  sym?: string;
  /** What the cockpit's read says of each image it places, by object id. */
  images?: Record<string, ImageStamp>;
  /** The range the cockpit is read for; a bigger figure shows its metric's trend over it. */
  range?: BriefingRange | null;
  schema?: string;
  /** The connection the ontology's pieces read (Arc OC-4). */
  connectionId?: string;
}) {
  // A spec is known by what it says, not by which object says it: a caller that parses the
  // same JSON again on every render hands over a new object each time, and that must not
  // close the tab a reader opened.
  const written = useMemo(() => JSON.stringify(spec) ?? "", [spec]);
  // eslint-disable-next-line react-hooks/exhaustive-deps -- keyed on what the spec says
  const check = useMemo(() => checkCockpitSpec(spec), [written]);

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
  const context = useMemo<CockpitContextValue>(() => ({
    elements: check.valid ? (spec as Spec).elements : {},
    cards: new Map(cards.map(c => [c.card.id, c])),
    host,
    doors,
    sym,
    images,
    range,
    schema,
    // eslint-disable-next-line react-hooks/exhaustive-deps -- keyed on what the spec and the range say
  }), [check.valid, written, cards, host, doors, sym, images, rangeKey, schema]);

  if (!check.valid) {
    return (
      <Refusal
        kind="Refused · the cockpit's spec"
        claim="This cockpit is not drawn, because its spec breaks the rules a cockpit is held to."
        detail={
          <ul data-testid="cockpit-refusal" style={{ margin: 0, paddingLeft: 18 }}>
            {check.issues.map((issue, i) => <li key={`${issue.code}-${issue.elementKey ?? ""}-${i}`}>{issue.message}</li>)}
          </ul>
        }
      />
    );
  }

  return (
    <CockpitContext.Provider value={context}>
      <PiecesProvider connectionId={connectionId} schema={schema} elements={context.elements} onPlaceTable={doors.onPlaceTable}>
        <JSONUIProvider registry={REGISTRY as ComponentRegistry} store={store}>
          <Renderer spec={spec as Spec} registry={REGISTRY as ComponentRegistry} />
        </JSONUIProvider>
      </PiecesProvider>
    </CockpitContext.Provider>
  );
}
